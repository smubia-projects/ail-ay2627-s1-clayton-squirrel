"""API tests with the model call stubbed out: no network, no API key needed."""

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import llm
from app.main import app

client = TestClient(app)
TODAY = date.today()


def completion(content: str, finish_reason: str = "stop") -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish_reason}]}


@pytest.fixture
def model(monkeypatch):
    """Replaces the OpenRouter call; tests set `model.reply` and read `model.payloads`."""

    class Stub:
        reply = completion("ok")
        payloads: list = []

    stub = Stub()
    stub.payloads = []

    def fake(payload):
        stub.payloads.append(payload)
        return stub.reply

    monkeypatch.setattr(llm, "_create_completion", fake)
    return stub


def benefit_reply(**overrides) -> str:
    record = {
        "is_benefit": True,
        "benefit_name": "Free pastry with any coffee",
        "provider": "Bluebird Bakery",
        "type": "voucher",
        "category": "dining",
        "value": "1 free pastry",
        "expiry_date": (TODAY + timedelta(days=9)).isoformat(),
        "expiry_confidence": "explicit",
        "expiry_reasoning": "The email gives an exact date.",
        "terms_summary": "One per visit.",
        "code": "BLUE-PASTRY",
        "source_snippet": "Valid until ...",
    }
    record.update(overrides)
    return json.dumps(record)


EMAIL = "Subject: A little something for you\n\nShow code BLUE-PASTRY for a free pastry with any coffee."


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_root_is_not_served():
    assert client.get("/").status_code == 404


def test_extract_text(model):
    model.reply = completion(benefit_reply())
    r = client.post("/api/extract", json={"text": EMAIL})
    assert r.status_code == 200
    body = r.json()
    assert body["subject"] == "A little something for you"
    assert body["benefit"]["code"] == "BLUE-PASTRY"
    assert body["benefit"]["needs_review"] is False
    sent = model.payloads[0]
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["messages"][0]["role"] == "system"


def test_extract_drops_invented_code_and_flags_ambiguous(model):
    model.reply = completion(benefit_reply(code="MADE-UP", expiry_confidence="ambiguous"))
    benefit = client.post("/api/extract", json={"text": EMAIL}).json()["benefit"]
    assert benefit["code"] is None
    assert benefit["expiry_date"] is None
    assert benefit["needs_review"] is True


def test_extract_eml(model):
    model.reply = completion(benefit_reply())
    eml = (
        "From: Bluebird Bakery <hi@bluebird.example>\r\n"
        "Subject: A little something for you\r\n"
        "Date: Mon, 5 Oct 2026 09:00:00 +0800\r\n"
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
        "<html><body><p>Show code BLUE-PASTRY for a free pastry.</p></body></html>\r\n"
    )
    body = client.post("/api/extract", json={"eml": eml}).json()
    assert body["received_date"] == "2026-10-05"
    assert body["subject"] == "A little something for you"
    assert "BLUE-PASTRY for a free pastry" in model.payloads[0]["messages"][1]["content"]


def test_extract_needs_text(model):
    assert client.post("/api/extract", json={"text": "hi"}).status_code == 400
    assert model.payloads == []


def test_model_failures_map_to_4xx_5xx_not_503(model):
    model.reply = completion("not json")
    assert client.post("/api/extract", json={"text": EMAIL}).status_code == 422
    model.reply = completion("", finish_reason="length")
    assert client.post("/api/extract", json={"text": EMAIL}).status_code == 422


def test_missing_key_is_502(monkeypatch):
    monkeypatch.setattr(llm.settings, "openrouter_api_key", "")
    r = client.post("/api/extract", json={"text": EMAIL})
    assert r.status_code == 502


BENEFITS = [
    {"benefit_name": "Gym credit", "provider": "PeakFit", "type": "voucher", "category": "wellness",
     "expiry_date": (TODAY + timedelta(days=3)).isoformat(), "expiry_confidence": "explicit"},
    {"benefit_name": "Used one", "provider": "X", "used_on": TODAY.isoformat()},
]


def test_digest(model):
    model.reply = completion(json.dumps({
        "ranked_benefits": [{"id": 0, "urgency_score": 5, "reason": "expires in 3 days"},
                            {"id": 7, "urgency_score": 4, "reason": "invented"}],
        "digest_text": "Use your gym credit first.",
    }))
    body = client.post("/api/digest", json={"benefits": BENEFITS, "today": TODAY.isoformat()}).json()
    assert body["digest_text"] == "Use your gym credit first."
    assert [r["benefit_name"] for r in body["ranked_benefits"]] == ["Gym credit"]  # used + invented dropped


def test_digest_empty_skips_model(model):
    body = client.post("/api/digest", json={"benefits": []}).json()
    assert body["ranked_benefits"] == []
    assert model.payloads == []


def test_ask(model):
    model.reply = completion("Use **Gym credit** (PeakFit) by Friday.")
    r = client.post("/api/ask", json={"question": "What should I use?", "benefits": BENEFITS})
    assert r.json() == {"answer": "Use **Gym credit** (PeakFit) by Friday."}
    prompt = model.payloads[0]["messages"][1]["content"]
    assert "Gym credit" in prompt and "Used one" not in prompt


def test_ask_tolerates_odd_fields(model):
    model.reply = completion("fine")
    odd = [{"benefit_name": "x" * 1000, "provider": None, "terms_summary": "t" * 5000, "source": "card",
            "credit_total": 15, "days_until_expiry": 3}]
    assert client.post("/api/ask", json={"question": "hi", "benefits": odd}).status_code == 200


def test_cors_preflight():
    r = client.options("/api/ask", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
