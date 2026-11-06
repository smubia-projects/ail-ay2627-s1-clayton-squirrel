"""
extraction.py

The benefit-extraction engine, copied from the repo-root app.py (sections 1-4:
output schema, system prompt, ExtractedBenefit, the AI call and the
deterministic validation layer). Only the import of the model-call helper
changed: it now comes from llm.py (OpenRouter) instead of app.py (OpenAI).

Design principles (unchanged from the original):
  1. Structured extraction is the detection engine, not a chatbot feature.
  2. The model NEVER invents a specific date without a stated or computable
     basis; ambiguous/unknown cases fall back to expiry_date=None and are
     routed to a "needs review" queue instead of being silently trusted.
  3. Validation (sanity-checking the model's output) is deterministic code,
     kept separate from the AI call itself.
"""

from dataclasses import dataclass, fields
from datetime import date
from typing import Optional, Union

from app.llm import call_structured


# ---------------------------------------------------------------------------
# 1. Output schema — the API constrains the model's reply to this exact shape
# ---------------------------------------------------------------------------

def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


# type: what kind of benefit it is. category: what it's spent on.
TYPES = ["membership", "subscription", "voucher", "other"]
CATEGORIES = ["entertainment", "transport", "travel", "dining", "wellness", "shopping", "other"]

BENEFIT_SCHEMA = {
    "type": "object",
    "properties": {
        "is_benefit": {
            "type": "boolean",
            "description": (
                "False if this email is not actually about a membership, "
                "voucher, or account perk (e.g. it's spam, a receipt for a "
                "one-off purchase, or unrelated). If false, other fields "
                "may be empty strings."
            ),
        },
        "benefit_name": {"type": "string"},
        "provider": {"type": "string"},
        "type": {
            "type": "string",
            "description": "What kind of benefit it is.",
            "enum": TYPES,
        },
        "category": {
            "type": "string",
            "description": "What it's spent on, e.g. a coffee voucher is dining, an Uber credit is transport.",
            "enum": CATEGORIES,
        },
        "value": _nullable({
            "type": "string",
            "description": 'e.g. "$50", "1 free item", "20% off"',
        }),
        "expiry_date": _nullable({
            "type": "string",
            "description": "ISO 8601 YYYY-MM-DD; null if not explicit/computable",
        }),
        "expiry_confidence": {
            "type": "string",
            "enum": ["explicit", "computed", "ambiguous", "unknown"],
            "description": (
                "explicit: an exact date was stated. "
                "computed: a relative duration was given and you calculated "
                "the date (e.g. 'valid 6 months from purchase on 1 Jan 2026'). "
                "ambiguous: multiple possible readings or vague wording "
                "(e.g. 'use it soon', 'valid this quarter'). "
                "unknown: no expiry information found at all."
            ),
        },
        "expiry_reasoning": {
            "type": "string",
            "description": "One short sentence on how the date was derived, or why it's uncertain.",
        },
        "terms_summary": _nullable({
            "type": "string",
            "description": "One-sentence plain-language summary of key conditions.",
        }),
        "code": _nullable({
            "type": "string",
            "description": (
                "The voucher, promo or redemption code to type or show at checkout, copied exactly "
                "as written (e.g. \"BDAY-7Q2K\"). null if the email has no such code. Not an "
                "order number, account number or membership number."
            ),
        }),
        "source_snippet": {
            "type": "string",
            "description": "The exact phrase the expiry info was drawn from, for user verification.",
        },
    },
    "required": [
        "is_benefit",
        "benefit_name",
        "provider",
        "type",
        "category",
        "value",
        "expiry_date",
        "expiry_confidence",
        "expiry_reasoning",
        "terms_summary",
        "code",
        "source_snippet",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
You extract structured membership/benefit/voucher details from raw email text \
for a benefit-tracking app. Reply with one record per email.

Critical rule: NEVER guess a specific expiry_date without either an explicit \
stated date or a clearly computable one (e.g. an explicit duration plus an \
explicit start date). If the wording is vague, contradictory, or missing, set \
expiry_date to null and expiry_confidence to "ambiguous" or "unknown" — do not \
provide a plausible-sounding date. A missed reminder is a minor inconvenience; \
a wrong reminder date is a real failure for the user.

Copy any voucher or promo code exactly as written. Never make one up: if \
there's no code in the email, set code to null.

Reading dates (the user is in Singapore):
- Numeric dates are day/month/year unless the email is clearly American: \
"11/10/2026" is 11 October 2026 and "4/10/26" is 4 October 2026. A date \
written this way is explicit.
- "End of October 2026" means 31 October 2026 (explicit). A month or day \
with no year means the next one on or after the email's received date \
(computed).
- For a date range ("7 to 9 Oct", "valid 28 Sep - 18 Oct"), the expiry is \
the last day.
- If the email lists several coupons or deals, each with its own "valid \
until" or offer date, the expiry is the latest of those dates (explicit), \
even if it has passed. Only use the offers' own dates: never the date of an \
event, a campaign the benefit isn't part of, a travel period or an \
application deadline.
- The ongoing perks of a membership (member discounts, earning rates) have \
no expiry. A points or miles balance with some points expiring on a date \
expires on that date.

A benefit is something the user holds or can redeem: a voucher or promo code, \
a credit or rebate, a points balance, a membership or its perks, a free trial, \
a birthday reward, or a time-limited offer they can claim. Set is_benefit to \
false for marketing spam, an unrelated receipt or newsletter, a product or \
feature announcement, a menu or shelf price ("now $6.50"), a bonus for buying \
more of something ("buy 2,500 coins, get 200 free"), and ads for opening a new \
card, loan or account that the user doesn't have yet (including bonuses that \
need one, like "apply by 31 Oct for 20,000 miles").
"""


# ---------------------------------------------------------------------------
# 2. Result type
# ---------------------------------------------------------------------------

@dataclass
class ExtractedBenefit:
    is_benefit: bool
    benefit_name: str
    provider: str
    type: str
    category: str
    expiry_confidence: str
    expiry_reasoning: str
    source_snippet: str
    value: Optional[str] = None
    expiry_date: Optional[str] = None
    terms_summary: Optional[str] = None
    code: Optional[str] = None  # a voucher or promo code; kept only if it appears in the email (see validate)
    points: Optional[int] = None  # a points/miles balance, entered by the user (never by the model)
    reminder: Union[int, str, None] = None  # set by the user: None (their default), "off" or days before expiry
    needs_review: bool = False  # set by validate(), not by the model
    review_reason: Optional[str] = None  # set by validate(), not by the model
    used_on: Optional[str] = None  # set by the user: the date they used it up (YYYY-MM-DD)
    used_amount: Optional[float] = None  # set by the user: card credits only, how much of this period's credit is spent

    @classmethod
    def from_model_output(cls, data: dict) -> "ExtractedBenefit":
        # Only accept schema fields; never let the model set review, points, reminder or usage fields.
        allowed = {f.name for f in fields(cls)} - {
            "needs_review", "review_reason", "points", "reminder", "used_on", "used_amount"}
        return cls(**{k: v for k, v in data.items() if k in allowed})


# ---------------------------------------------------------------------------
# 3. The AI call itself
# ---------------------------------------------------------------------------

def extract_benefit_from_email(
    email_text: str,
    received_date: Optional[str] = None,
    today: Optional[date] = None,
) -> ExtractedBenefit:
    """
    Calls the model once to extract a structured benefit record from raw email text.
    Truncates very long emails (forwarded chains, quoted history) to keep the
    signal-to-noise ratio high — see README 'known failure modes' re: long
    forwarded threads.

    Raises AIError on API failures and ExtractionError when the
    model refuses or its output is unusable.
    """
    today = today or date.today()
    # Dates go in the user turn (not the system prompt) so the system prompt
    # stays byte-identical across calls and remains cacheable.
    context = f"Today's date: {today.isoformat()}\n"
    if received_date:
        context += f"Email received date: {received_date}\n"
    truncated = email_text[:8000]  # keep prompt focused; long threads are a documented limitation

    data = call_structured(SYSTEM_PROMPT, context + "\n" + truncated, BENEFIT_SCHEMA, name="benefit")
    extracted = ExtractedBenefit.from_model_output(data)
    return validate(extracted, today=today, email_text=truncated)


# ---------------------------------------------------------------------------
# 4. Deterministic validation layer — NOT an AI call
#    This is where you can show judges you don't blindly trust model output.
# ---------------------------------------------------------------------------

def _flag(extracted: ExtractedBenefit, reason: str) -> None:
    extracted.needs_review = True
    extracted.review_reason = extracted.review_reason or reason


def validate(
    extracted: ExtractedBenefit, today: Optional[date] = None, email_text: Optional[str] = None
) -> ExtractedBenefit:
    """
    Sanity-checks the model's output with plain code. Anything suspicious
    routes the record into the "needs review" queue instead of silently
    entering the main tracker.
    """
    today = today or date.today()

    # A code is only kept if it appears in the email word for word, so the
    # model can't invent one. A wrong code at the till is worse than none.
    code = (extracted.code or "").strip()
    if not code or len(code) > 64 or (email_text is not None and code not in email_text):
        code = None
    extracted.code = code

    if extracted.expiry_confidence in ("ambiguous", "unknown"):
        extracted.expiry_date = None
        _flag(extracted, f"expiry is {extracted.expiry_confidence}")

    elif not extracted.expiry_date:
        # Model claimed explicit/computed confidence but gave no date.
        _flag(extracted, f"confidence '{extracted.expiry_confidence}' but no date given")

    if extracted.expiry_date:
        try:
            parsed = date.fromisoformat(extracted.expiry_date)
        except ValueError:
            extracted.expiry_date = None
            _flag(extracted, "expiry date is not a valid YYYY-MM-DD date")
        else:
            days_out = (parsed - today).days
            # Already expired or implausibly far out — likely a misread date.
            # Flag rather than trust.
            if days_out < 0:
                _flag(extracted, "expiry date is in the past")
            elif days_out > 365 * 5:
                _flag(extracted, "expiry date is more than 5 years away")

    return extracted
