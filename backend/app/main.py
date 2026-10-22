"""
Squirrel demo API (AI Lodge).

A stateless FastAPI service with the three AI features of Squirrel:

  POST /api/extract  one email (pasted text or an uploaded .eml) -> one benefit record
  POST /api/digest   the visitor's benefit list -> urgency-ranked weekly digest
  POST /api/ask      a question + the visitor's benefit list -> grounded answer
  GET  /api/health   liveness probe

Nothing is stored: the browser keeps the benefit list (localStorage) and sends
it with each digest/assistant request. No accounts, no inbox connections.
"""

import re
from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import Annotated, Optional, Union

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, BeforeValidator, Field

from app.benefit_intelligence import ask_about_benefits, build_weekly_digest
from app.config import settings
from app.eml import parse_eml
from app.extraction import ExtractedBenefit, extract_benefit_from_email
from app.llm import AIError, ExtractionError

app = FastAPI(title="Squirrel demo API", docs_url=None, redoc_url=None, openapi_url=None)

MAX_EMAIL_CHARS = 50_000  # pasted text; the extractor reads the first 8,000 anyway
MAX_EML_CHARS = 2_000_000  # raw .eml source, attachments included
MAX_BENEFITS = 300  # benefit_intelligence.SEND_ALL_UP_TO
MAX_BODY_BYTES = 2_500_000


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    """Rejects oversized bodies before they're read (an .eml with big attachments, or abuse)."""
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        return JSONResponse(status_code=413, content={"detail": {"message": "That email is too large (2 MB max)."}})
    return await call_next(request)


# Added last so it wraps everything (including the 413 above) with CORS headers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class ExtractIn(BaseModel):
    text: Optional[str] = Field(None, max_length=MAX_EMAIL_CHARS)
    eml: Optional[str] = Field(None, max_length=MAX_EML_CHARS)
    received_date: Optional[str] = Field(None, max_length=10)
    today: Optional[str] = Field(None, max_length=10)


def _clip(limit: int):
    """A string field cut to `limit` characters (None becomes ""), so odd data never fails a request."""
    return Annotated[str, BeforeValidator(lambda v: "" if v is None else str(v)[:limit])]


def _clip_optional(limit: int):
    return Annotated[Optional[str], BeforeValidator(lambda v: None if v is None else str(v)[:limit])]


class BenefitIn(BaseModel):
    """One of the visitor's benefits, as kept by the browser (ExtractedBenefit fields)."""

    is_benefit: bool = True
    benefit_name: _clip(200) = ""
    provider: _clip(200) = ""
    type: _clip(40) = "other"
    category: _clip(40) = "other"
    expiry_confidence: _clip(20) = "unknown"
    expiry_reasoning: _clip(300) = ""
    source_snippet: _clip(300) = ""
    value: _clip_optional(100) = None
    expiry_date: _clip_optional(10) = None
    terms_summary: _clip_optional(500) = None
    code: _clip_optional(64) = None
    points: Optional[int] = None
    reminder: Union[int, str, None] = None
    needs_review: bool = False
    review_reason: _clip_optional(200) = None
    used_on: _clip_optional(10) = None
    used_amount: Optional[float] = None

    def to_benefit(self) -> ExtractedBenefit:
        return ExtractedBenefit(**self.model_dump())


class DigestIn(BaseModel):
    benefits: list[BenefitIn] = Field(default_factory=list, max_length=MAX_BENEFITS)
    today: Optional[str] = Field(None, max_length=10)


class AskIn(BaseModel):
    question: str = Field(..., max_length=500)
    benefits: list[BenefitIn] = Field(default_factory=list, max_length=MAX_BENEFITS)
    today: Optional[str] = Field(None, max_length=10)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today(client_today: Optional[str]) -> date:
    """
    The visitor's local date when it's within a day of the server's (UTC) date,
    so "expires today" matches their clock; otherwise the server's date.
    """
    server_today = datetime.now(timezone.utc).date()
    try:
        candidate = date.fromisoformat(client_today or "")
    except ValueError:
        return server_today
    return candidate if abs((candidate - server_today).days) <= 1 else server_today


def _iso_date_or_none(value: Optional[str]) -> Optional[str]:
    try:
        return date.fromisoformat(value or "").isoformat()
    except ValueError:
        return None


def _ai_call(fn, *args):
    """Runs an AI call and maps its failures to HTTP errors (never 503: that's the kill switch)."""
    try:
        return fn(*args)
    except ExtractionError as e:
        raise HTTPException(status_code=422, detail={"message": f"The AI couldn't read that: {e}."}) from e
    except AIError as e:
        raise HTTPException(status_code=502, detail={"message": str(e)}) from e


def _tracked(benefits: list[BenefitIn]) -> list[ExtractedBenefit]:
    """Benefits worth answering from: real ones that haven't been used up (as server.py did)."""
    return [b.to_benefit() for b in benefits if b.is_benefit and not b.used_on]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/extract")
def extract(body: ExtractIn, request: Request):
    """One email in, one validated benefit record out (is_benefit=false when it isn't one)."""
    subject: Optional[str] = None
    received_date = _iso_date_or_none(body.received_date)
    if body.eml and body.eml.strip():
        parsed = parse_eml(body.eml)
        text = parsed["text"]
        subject = parsed["subject"] or None
        received_date = received_date or parsed["received_date"]
    else:
        text = (body.text or "").strip()
        match = re.search(r"^\s*Subject:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
        subject = match.group(1).strip()[:200] if match else None
    if len(text.strip()) < 20:
        raise HTTPException(status_code=400, detail={"message": "Paste a whole email (at least a sentence or two)."})

    today = _today(body.today)
    benefit = _ai_call(extract_benefit_from_email, text, received_date, today)
    return {"benefit": asdict(benefit), "subject": subject, "received_date": received_date}


@app.post("/api/digest")
def digest(body: DigestIn, request: Request):
    benefits = _tracked(body.benefits)
    today = _today(body.today)
    if not benefits:  # answered without the model, so it doesn't use up the limit
        return build_weekly_digest([], today)
    return _ai_call(build_weekly_digest, benefits, today)


@app.post("/api/ask")
def ask(body: AskIn, request: Request):
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail={"message": "Type a question first."})
    benefits = _tracked(body.benefits)
    today = _today(body.today)
    if not benefits:
        return {"answer": ask_about_benefits(question, [], today)}
    return {"answer": _ai_call(ask_about_benefits, question, benefits, today)}
