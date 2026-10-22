"""
benefit_intelligence.py

Copied from the repo-root BenefitIntelligence.py: the urgency-ranked weekly
digest and the grounded assistant. Only the imports changed (extraction.py and
llm.py instead of app.py); prompts, schema and post-processing are unchanged.

  3. Urgency/value ranking + weekly digest: takes the user's benefit records
     and produces a ranked priority list plus a short plain-language summary.
  4. Grounded assistant: answers open-ended questions using ONLY the user's
     own benefit records, not the model's general knowledge.
"""

import json
import re
from dataclasses import asdict
from datetime import date
from typing import List, Dict, Any, Optional

from app.extraction import ExtractedBenefit
from app.llm import call_structured, call_text


def _days_until(expiry_date: Optional[str], today: date) -> Optional[int]:
    """Computed in code so the model never has to do date arithmetic."""
    if not expiry_date:
        return None
    try:
        return (date.fromisoformat(expiry_date) - today).days
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 3. Urgency-ranking + weekly digest
# ---------------------------------------------------------------------------

DIGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "ranked_benefits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "The id of the benefit from the input list.",
                    },
                    "urgency_score": {
                        "type": "integer",
                        "enum": [1, 2, 3, 4, 5],
                        "description": "1 (low) to 5 (act now) — weighs expiry proximity against stated/inferred value.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "One short phrase, e.g. 'expires in 4 days, high value'.",
                    },
                },
                "required": ["id", "urgency_score", "reason"],
                "additionalProperties": False,
            },
        },
        "digest_text": {
            "type": "string",
            "description": (
                "2-3 sentence plain-language weekly summary, e.g. "
                "'3 benefits need attention this week: your gym credit "
                "expires Friday, ...'"
            ),
        },
    },
    "required": ["ranked_benefits", "digest_text"],
    "additionalProperties": False,
}

DIGEST_SYSTEM_PROMPT = """\
You help prioritize a user's tracked benefits/vouchers/memberships. Given a \
list of benefits with their expiry dates, days until expiry, values, and \
types and categories, rank them by urgency — weighing how soon they expire against how \
valuable they seem (use the stated value if given, otherwise your best \
judgement from the type/category/terms). Refer to each benefit by its id, and rank \
every benefit exactly once.

Only reason about the benefits given to you. Do not invent benefits that \
aren't in the list, and never state a specific expiry date for anything \
marked needs_review: true — refer to those as "needs review" instead.
"""


def build_weekly_digest(
    benefits: List[ExtractedBenefit], today: Optional[date] = None
) -> Dict[str, Any]:
    """
    benefits: the user's currently tracked ExtractedBenefit records (mix of
    confirmed and needs_review is fine — the model is told which is which).

    Returns {"ranked_benefits": [{benefit_name, provider, urgency_score,
    reason}, ...], "digest_text": str}, sorted most urgent first.
    """
    if not benefits:
        return {"ranked_benefits": [], "digest_text": "You have no tracked benefits yet."}

    today = today or date.today()
    payload = [
        {
            "id": i,
            "benefit_name": b.benefit_name,
            "provider": b.provider,
            "type": b.type,
            "category": b.category,
            "value": b.value,
            "points": b.points,
            # Unverified dates are withheld so the model can't repeat them.
            "expiry_date": None if b.needs_review else b.expiry_date,
            "days_until_expiry": None if b.needs_review else _days_until(b.expiry_date, today),
            "needs_review": b.needs_review,
        }
        for i, b in enumerate(benefits)
    ]

    result = call_structured(
        DIGEST_SYSTEM_PROMPT,
        f"Today's date: {today.isoformat()}\n\nBenefits:\n{json.dumps(payload, indent=2)}",
        DIGEST_SCHEMA,
        effort="low",
        name="digest",
    )

    # Deterministic check: keep only ids that exist, each at most once, then
    # attach the real names from our records (never the model's spelling).
    ranked, seen = [], set()
    for item in result["ranked_benefits"]:
        i = item["id"]
        if not 0 <= i < len(benefits) or i in seen:
            continue
        seen.add(i)
        ranked.append({
            "benefit_name": benefits[i].benefit_name,
            "provider": benefits[i].provider,
            "urgency_score": item["urgency_score"],
            "reason": item["reason"],
        })
    ranked.sort(key=lambda r: r["urgency_score"], reverse=True)

    return {"ranked_benefits": ranked, "digest_text": result["digest_text"]}


# ---------------------------------------------------------------------------
# 4. RAG assistant — grounded Q&A over the user's own benefit records
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "before", "by", "can", "do",
    "does", "for", "from", "have", "how", "i", "in", "is", "it", "my", "of",
    "on", "or", "should", "that", "the", "this", "to", "use", "what", "when",
    "which", "will", "with", "any", "all", "me", "benefit", "benefits",
}


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS}


# Up to this many benefits, the assistant sees all of them: a few hundred
# records fit easily in one prompt, and no search can drop the one that answers
# the question. Only past it does keyword search pick which ones to send.
SEND_ALL_UP_TO = 300


def _retrieve_relevant_benefits(
    question: str, benefits: List[ExtractedBenefit], max_results: int = SEND_ALL_UP_TO
) -> List[ExtractedBenefit]:
    """
    The benefits to answer from: all of them, up to max_results. Past that,
    the ones sharing the most words with the question (minus stopwords,
    whole-word match), so a keyword-free question still gets an answer.
    """
    if len(benefits) <= max_results:
        return benefits

    question_words = _words(question)

    def score(b: ExtractedBenefit) -> int:
        text = " ".join(
            filter(None, [b.benefit_name, b.provider, b.type, b.category, b.value, b.terms_summary])
        )
        return len(question_words & _words(text))

    # sorted() is stable, so benefits that tie keep their original order.
    return sorted(benefits, key=score, reverse=True)[:max_results]


ASSISTANT_SYSTEM_PROMPT = """\
You are a helpful assistant for a personal benefit/voucher tracker app. \
Answer the user's question using ONLY the benefit records provided below — \
never use outside knowledge about the providers named, and never invent a \
benefit, date, or term that isn't in the data. If the data doesn't contain \
enough information to answer, say so plainly rather than guessing.

Records with needs_review: true have not been verified — don't state their \
expiry dates as fact; tell the user to check them in the review queue.

When you reference a specific benefit, use its exact benefit_name so the user \
can find it in their dashboard.

Leave out benefits that have already expired (days_until_expiry below 0) \
unless the user asks about them.

How to write the answer (it's shown in a small chat bubble on a phone):
- Start with a one- or two-sentence direct answer.
- If a list helps, follow with a short bulleted list ("- "): at most 5 items, \
the most urgent first, one line each, like \
"**Benefit name** (Provider): what it's worth, use by 9 Oct". If there are \
more, say how many more there are instead of listing them.
- Write dates as day and short month ("9 Oct"), or "today" / "tomorrow"; \
never as 2026-10-09.
- Use **bold** only for benefit names. No headings, tables, nested lists or \
emoji.
- Mention benefits that need review in one short closing sentence, not a \
separate list.
- Keep the whole answer under about 120 words unless the user asks for detail.
"""


def ask_about_benefits(
    question: str, benefits: List[ExtractedBenefit], today: Optional[date] = None
) -> str:
    """
    Grounded Q&A: answers only from the user's own records (all of them, up to
    SEND_ALL_UP_TO) — this is what keeps answers accurate to what the user
    actually has, rather than the model's general knowledge.
    """
    if not benefits:
        return "You don't have any tracked benefits yet, so there's nothing to answer from."

    today = today or date.today()
    relevant = _retrieve_relevant_benefits(question, benefits)
    # Compact JSON with empty fields left out keeps a few hundred records small.
    records = [
        {k: v for k, v in {**asdict(b), "days_until_expiry": _days_until(b.expiry_date, today)}.items()
         if v not in (None, "", [])}
        for b in relevant
    ]

    return call_text(
        ASSISTANT_SYSTEM_PROMPT,
        f"Today's date: {today.isoformat()}\n\n"
        f"My tracked benefits:\n{json.dumps(records, separators=(',', ':'))}\n\n"
        f"Question: {question}",
    )
