"""
llm.py

The one place that talks to the AI model. A port of the call helpers in the
repo-root app.py (`_create_response`, `call_structured`, `call_text`) from
OpenAI's Responses API to OpenRouter's OpenAI-compatible chat/completions API.

Structured calls use `response_format: {"type": "json_schema", strict: true}`
so the reply matches the schema; refusals, cut-off output and invalid JSON all
become ExtractionError, and API failures become AIError, exactly as before.
"""

import json
import re
import socket
import time
import urllib.error
import urllib.request

from app.config import settings

MAX_ATTEMPTS = 3  # rate limits, 5xx and connection errors are retried with backoff
MAX_TOKENS = 4000  # replies are short records or a ~120-word answer; caps cost per call
TIMEOUT_S = 120


class ExtractionError(Exception):
    """The model call finished but didn't produce a usable result."""


class AIError(Exception):
    """The OpenRouter API call itself failed."""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable  # worth trying again after a short wait


def _api_error(status: int, body: bytes) -> AIError:
    try:
        error = json.loads(body).get("error") or {}
    except (ValueError, AttributeError):
        error = {}
    detail = error.get("message") or f"HTTP {status}"
    if status == 401:
        return AIError("The AI service rejected the API key (check OPENROUTER_API_KEY).")
    if status == 402:
        return AIError("The AI service account is out of credit.")
    if status == 429:
        return AIError("The AI service is busy. Wait a minute and try again.", retryable=True)
    if status in (400, 404) and "model" in detail.lower():
        return AIError(f"The AI model '{settings.openrouter_model}' isn't available (check OPENROUTER_MODEL).")
    return AIError(f"AI service error ({status}): {detail}", retryable=status >= 500)


def _create_completion(payload: dict) -> dict:
    """POSTs to OpenRouter's chat/completions, retrying transient failures."""
    key = settings.openrouter_api_key.strip()
    if not key:
        raise AIError("No AI API key is configured on the server (OPENROUTER_API_KEY).")

    model = settings.openrouter_model
    # DeepSeek thinks first by default; these calls have a TIMEOUT_S budget.
    extra = {"reasoning_effort": "none"} if "deepseek" in model.lower() else {}
    body = json.dumps({"model": model, **extra, **payload}).encode()
    url = settings.openrouter_base_url.rstrip("/") + "/chat/completions"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        request = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-Title": "Squirrel (AI Lodge demo)",
        })
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as e:
            error = _api_error(e.code, e.read())
            if not error.retryable or attempt == MAX_ATTEMPTS:
                raise error from e
            delay = float(e.headers.get("retry-after") or 2 ** attempt)
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            if attempt == MAX_ATTEMPTS:
                raise AIError("Couldn't reach the AI service. Try again in a moment.") from e
            delay = 2 ** attempt
        time.sleep(min(delay, 10))
    raise AssertionError("unreachable")


def _output_text(response: dict) -> str:
    """The reply text, turning errors, refusals and cut-off output into ExtractionError."""
    if response.get("error"):
        raise ExtractionError(f"model failed: {response['error'].get('message', 'unknown error')}")
    choices = response.get("choices") or []
    if not choices:
        raise ExtractionError("model returned no choices")
    choice = choices[0]
    message = choice.get("message") or {}
    if message.get("refusal"):
        raise ExtractionError("model declined the request")
    if choice.get("finish_reason") == "length":
        raise ExtractionError("model output was cut off (max_tokens)")
    text = message.get("content")
    if isinstance(text, list):  # some providers return content parts
        text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
    if not text or not text.strip():
        raise ExtractionError("model returned no text output")
    return text


def _base_payload(system: str, user_content: str, effort: str) -> dict:
    return {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": MAX_TOKENS,
        # OpenRouter's unified reasoning setting; ignored by models without reasoning.
        "reasoning": {"effort": effort},
    }


def _parse_json(text: str) -> dict:
    """Parses the reply, tolerating a ```json fence some models add around it."""
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ExtractionError(f"model output was not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ExtractionError("model output was not a JSON object")
    return data


def call_structured(system: str, user_content: str, schema: dict, effort: str = "medium",
                    name: str = "result") -> dict:
    """
    One model call whose reply the API constrains to `schema` (strict
    structured outputs). Shared by every AI feature so there's one place that
    handles refusals, truncation and parsing.

    Raises AIError on API failures and ExtractionError when the model refuses
    or its output is unusable.
    """
    payload = _base_payload(system, user_content, effort)
    payload["response_format"] = {
        "type": "json_schema",
        "json_schema": {"name": name, "schema": schema, "strict": True},
    }
    # Only route to providers that honour response_format for this model.
    payload["provider"] = {"require_parameters": True}
    return _parse_json(_output_text(_create_completion(payload)))


def call_text(system: str, user_content: str, effort: str = "low") -> str:
    """One model call that returns plain text. Same error handling as call_structured."""
    return _output_text(_create_completion(_base_payload(system, user_content, effort))).strip()
