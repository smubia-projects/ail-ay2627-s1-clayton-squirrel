"""scan_jobs: the marketing filter and the daily cap on emails sent to the AI model."""

from datetime import date
from types import SimpleNamespace

import pytest

import db
import scan_jobs
from app import AIError

TODAY = date(2026, 10, 7)


def new_job() -> dict:
    return {"checked": 0, "total": None, "added": 0, "needs_review": 0, "skipped": 0, "filtered": 0,
            "failed": 0, "remaining": 0, "limit_reached": False, "daily_limit_reached": False,
            "state": "running", "message": None}


@pytest.fixture
def ai_calls(monkeypatch):
    """Replaces the AI model: every email reads as 'not a benefit'. Returns the list of calls."""
    calls = []

    def fake_extract(text, received_date, today):
        calls.append(text)
        return SimpleNamespace(is_benefit=False, needs_review=False)
    monkeypatch.setattr(scan_jobs, "extract_benefit_from_email", fake_extract)
    return calls


def read_today(user_id: str, today: date = TODAY) -> int:
    with db.connect() as conn:
        return scan_jobs.emails_read_today(conn, user_id, today)


# --- Marketing filter ---------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Weekly rewards! 50% off everything. Shop now. Unsubscribe",
    "View this email in your browser. New arrivals are here. Unsubscribe here.",
    "FLASH SALE ends tonight, don’t miss out. unsubscribe",
])
def test_marketing_blasts_are_filtered(text):
    assert scan_jobs.looks_promotional(text)


@pytest.mark.parametrize("text", [
    # A real benefit in a marketing-looking email: kept for the AI model.
    "Your voucher code ABC is valid until 1 Dec. Shop now. Unsubscribe",
    "Rewards newsletter: you’ve earned 500 points. 20% off. Unsubscribe",  # curly apostrophe
    "Your membership renews on 3 Jan. Shop now. Unsubscribe",
    # Not enough to call it marketing.
    "Big sale, 20% off, shop now",  # no unsubscribe link
    "Your statement is ready. Unsubscribe",  # no marketing phrase
])
def test_possible_benefits_are_not_filtered(text):
    assert not scan_jobs.looks_promotional(text)


def test_filtered_email_skips_the_ai_and_is_never_read_again(user, ai_calls):
    job = new_job()
    email = {"text": "40% off, shop now. Unsubscribe", "received_date": None}
    assert scan_jobs.extract_and_store(user["id"], job, "m1", email, "gmail", "gmail:m1", {}, TODAY)
    assert ai_calls == []
    assert job["filtered"] == 1 and job["checked"] == 1
    assert read_today(user["id"]) == 0  # doesn't use up the daily cap
    with db.connect() as conn:
        row = conn.execute("SELECT done, filtered FROM processed_emails WHERE message_id = 'm1'").fetchone()
        assert (row["done"], row["filtered"]) == (1, 1)
        assert "m1" in scan_jobs.finished_emails(conn, user["id"])


# --- Daily cap -------------------------------------------------------------------

def test_daily_cap_stops_ai_calls(user, ai_calls, monkeypatch):
    monkeypatch.setattr(scan_jobs, "DAILY_EMAIL_CAP", 3)
    job = new_job()
    for i in range(5):
        email = {"text": f"Your voucher {i}", "received_date": None}
        scan_jobs.extract_and_store(user["id"], job, f"m{i}", email, "gmail", f"gmail:m{i}", {}, TODAY)
    assert len(ai_calls) == 3
    assert job["daily_limit_reached"]
    assert job["remaining"] == 2
    assert read_today(user["id"]) == 3
    # The two over the cap aren't marked as read, so a later scan picks them up.
    with db.connect() as conn:
        assert scan_jobs.finished_emails(conn, user["id"]) == {"m0", "m1", "m2"}


def test_cap_resets_the_next_day(user, ai_calls, monkeypatch):
    monkeypatch.setattr(scan_jobs, "DAILY_EMAIL_CAP", 1)
    email = {"text": "Your voucher", "received_date": None}
    scan_jobs.extract_and_store(user["id"], new_job(), "a", email, "gmail", "gmail:a", {}, TODAY)
    scan_jobs.extract_and_store(user["id"], new_job(), "b", email, "gmail", "gmail:b", {}, TODAY)
    scan_jobs.extract_and_store(user["id"], new_job(), "b", email, "gmail", "gmail:b", {}, date(2026, 10, 8))
    assert len(ai_calls) == 2


def test_cap_is_per_user(user, ai_calls, monkeypatch):
    from conftest import make_user
    other = make_user("sam@example.com")
    monkeypatch.setattr(scan_jobs, "DAILY_EMAIL_CAP", 1)
    email = {"text": "Your voucher", "received_date": None}
    scan_jobs.extract_and_store(user["id"], new_job(), "a", email, "gmail", "gmail:a", {}, TODAY)
    scan_jobs.extract_and_store(other["id"], new_job(), "a", email, "gmail", "gmail:a", {}, TODAY)
    assert len(ai_calls) == 2


def test_take_batch_respects_what_is_left_of_the_cap(user, ai_calls, monkeypatch):
    monkeypatch.setattr(scan_jobs, "DAILY_EMAIL_CAP", 3)
    job = new_job()
    assert len(scan_jobs.take_batch(user["id"], job, list(range(10)), lambda m: True, TODAY)) == 3
    assert job["daily_limit_reached"] and job["remaining"] == 7

    email = {"text": "Your voucher", "received_date": None}
    for key in ("a", "b", "c"):
        scan_jobs.extract_and_store(user["id"], new_job(), key, email, "gmail", f"gmail:{key}", {}, TODAY)
    job = new_job()
    assert scan_jobs.take_batch(user["id"], job, list(range(10)), lambda m: True, TODAY) == []
    assert job["daily_limit_reached"]


def test_take_batch_without_cap_pressure(user):
    job = new_job()
    batch = scan_jobs.take_batch(user["id"], job, list(range(10)), lambda m: m % 2 == 0, TODAY)
    assert batch == [0, 2, 4, 6, 8]
    assert not job["daily_limit_reached"] and job["remaining"] == 0


def test_error_that_stops_the_scan_gives_its_slot_back(user, monkeypatch):
    def missing_key(*args):
        raise AIError("OPENAI_API_KEY is not set")
    monkeypatch.setattr(scan_jobs, "extract_benefit_from_email", missing_key)
    monkeypatch.setattr(scan_jobs, "describe_ai_error", lambda e: ("No API key.", True))
    job = new_job()
    email = {"text": "Your voucher", "received_date": None}
    assert not scan_jobs.extract_and_store(user["id"], job, "a", email, "gmail", "gmail:a", {}, TODAY)
    assert job["state"] == "error"
    assert read_today(user["id"]) == 0


def test_failed_email_still_counts_and_is_retried(user, monkeypatch):
    def refusal(*args):
        raise AIError("model refused")
    monkeypatch.setattr(scan_jobs, "extract_benefit_from_email", refusal)
    monkeypatch.setattr(scan_jobs, "describe_ai_error", lambda e: ("Refused.", False))
    job = new_job()
    email = {"text": "Your voucher", "received_date": None}
    for _ in range(scan_jobs.MAX_TRIES):
        assert scan_jobs.extract_and_store(user["id"], job, "a", email, "gmail", "gmail:a", {}, TODAY)
    assert job["failed"] == scan_jobs.MAX_TRIES
    assert read_today(user["id"]) == scan_jobs.MAX_TRIES  # each try was a paid call
    with db.connect() as conn:  # given up on after MAX_TRIES
        assert "a" in scan_jobs.finished_emails(conn, user["id"])


def test_given_up_emails_can_be_tried_again(user, monkeypatch):
    def refusal(*args):
        raise AIError("model refused")
    monkeypatch.setattr(scan_jobs, "extract_benefit_from_email", refusal)
    monkeypatch.setattr(scan_jobs, "describe_ai_error", lambda e: ("Refused.", False))
    email = {"text": "Your voucher", "received_date": None}
    for _ in range(scan_jobs.MAX_TRIES):
        scan_jobs.extract_and_store(user["id"], new_job(), "a", email, "gmail", "gmail:a", {}, TODAY)
    scan_jobs.extract_and_store(user["id"], new_job(), "b", email, "gmail", "gmail:b", {}, TODAY)  # failed once
    with db.connect() as conn:
        assert scan_jobs.given_up(conn, user["id"]) == 1
        assert scan_jobs.given_up(conn, "someone-else") == 0
        assert scan_jobs.retry_given_up(conn, user["id"]) == 1
        assert scan_jobs.given_up(conn, user["id"]) == 0
        assert "a" not in scan_jobs.finished_emails(conn, user["id"])


def test_scan_cut_short_by_a_restart_shows_as_stopped(user):
    import threading
    release = threading.Event()
    finished = threading.Event()

    def slow_scan(job):
        release.wait(5)
        scan_jobs.update(job, state="done")

    scan_jobs.start("gmail:x", slow_scan)
    scan_jobs._jobs.clear()  # the restart: progress kept in memory is gone
    assert scan_jobs.mark_interrupted() == 1
    assert scan_jobs.status("gmail:x") == {"state": "error", "message": scan_jobs.INTERRUPTED}
    assert scan_jobs.mark_interrupted() == 0  # reported once

    release.set()
    scan_jobs.start("gmail:y", lambda job: finished.set())
    assert finished.wait(5)
    for _ in range(50):  # the row goes when the scan ends
        with db.connect() as conn:
            if not conn.execute("SELECT 1 FROM running_scans WHERE job_key = 'gmail:y'").fetchone():
                break
        release.wait(0.05)
    else:
        raise AssertionError("a finished scan was left marked as running")


# --- Expired and repeated offers ------------------------------------------------

def found(monkeypatch, **fields):
    """Replaces the AI model: every email reads as this benefit."""
    from app import ExtractedBenefit, validate

    def fake_extract(text, received_date, today):
        benefit = ExtractedBenefit(is_benefit=True, benefit_name="S$20 off", provider="iShopChangi",
                                   type="voucher", category="shopping", expiry_confidence="explicit",
                                   expiry_reasoning="", source_snippet="", **fields)
        return validate(benefit, today=today, email_text=text)
    monkeypatch.setattr(scan_jobs, "extract_benefit_from_email", fake_extract)


def stored(user_id: str) -> int:
    with db.connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM benefits WHERE user_id = ?", (user_id,)).fetchone()[0]


def test_already_expired_offer_is_skipped(user, monkeypatch):
    found(monkeypatch, expiry_date="2026-10-04")
    job = new_job()
    scan_jobs.extract_and_store(user["id"], job, "a", {"text": "until 4/10/26", "received_date": None},
                                "gmail", "gmail:a", {}, TODAY)
    assert stored(user["id"]) == 0 and job["skipped"] == 1


def test_same_code_in_a_second_email_is_skipped(user, monkeypatch):
    found(monkeypatch, expiry_date="2026-12-31", code="ISCNEW20")
    email = {"text": "Use code ISCNEW20 by 31/12/2026", "received_date": None}
    scan_jobs.extract_and_store(user["id"], new_job(), "a", email, "gmail", "gmail:a", {}, TODAY)
    job = new_job()
    scan_jobs.extract_and_store(user["id"], job, "b", {**email, "text": "Reminder: code ISCNEW20 still works"},
                                "gmail", "gmail:b", {}, TODAY)
    assert stored(user["id"]) == 1 and job["skipped"] == 1


def test_offer_without_a_code_is_kept_twice(user, monkeypatch):
    # Without a code there's no safe way to tell two offers apart.
    found(monkeypatch, expiry_date="2026-12-31")
    for key in ("a", "b"):
        scan_jobs.extract_and_store(user["id"], new_job(), key, {"text": "S$20 off", "received_date": None},
                                    "gmail", f"gmail:{key}", {}, TODAY)
    assert stored(user["id"]) == 2


# --- Gmail read both ways --------------------------------------------------------

def test_gmail_message_ids_match_the_gmail_api():
    import imap_sync

    class FakeImap:
        def uid(self, command, uids, items):
            assert command == "FETCH" and uids == "7,9" and items == "(X-GM-MSGID)"
            return "OK", [b"1 (X-GM-MSGID 1878177213564307915 UID 7)", b"2 (UID 9 X-GM-MSGID 255)"]
    assert imap_sync.gmail_message_ids(FakeImap(), ["7", "9"]) == {"7": "1a10a03987bbc9cb", "9": "ff"}
    assert imap_sync.gmail_message_ids(FakeImap(), []) == {}
