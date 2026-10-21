"""reminders.py: who gets a reminder email, when, and only once."""

from datetime import date, datetime, timezone

import db
import reminders
from conftest import add_benefit, make_user

# 2 Oct 2026, 09:00 in Singapore (01:00 UTC).
MORNING = datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc)
# 2 Oct 2026, 07:00 in Singapore: before reminders go out.
EARLY = datetime(2026, 10, 1, 23, 0, tzinfo=timezone.utc)

SETTINGS = {"enabled": True, "timezone": "Asia/Singapore"}
TODAY = date(2026, 10, 2)


def b(**data) -> dict:
    return {"id": "x", "benefit_name": "Voucher", "expiry_date": "2026-10-09", **data}


# --- Which benefits are due (no email involved) ----------------------------------------

def test_default_is_one_week_before():
    assert reminders.due([b(expiry_date="2026-10-09")], SETTINGS, set(), TODAY)  # 7 days out
    assert not reminders.due([b(expiry_date="2026-10-10")], SETTINGS, set(), TODAY)  # 8 days out


def test_due_through_the_expiry_day_but_not_after():
    assert reminders.due([b(expiry_date="2026-10-02")], SETTINGS, set(), TODAY)
    assert not reminders.due([b(expiry_date="2026-10-01")], SETTINGS, set(), TODAY)


def test_custom_reminder_days_and_off():
    assert reminders.due([b(expiry_date="2026-11-01", reminder=30)], SETTINGS, set(), TODAY)
    assert not reminders.due([b(reminder="off")], SETTINGS, set(), TODAY)


def test_skips_review_used_undated_and_already_sent():
    skipped = [b(id="1", needs_review=True), b(id="2", used_on="2026-10-01"), b(id="3", expiry_date=None)]
    assert reminders.due(skipped, SETTINGS, set(), TODAY) == []
    assert reminders.due([b()], SETTINGS, {("x", "2026-10-09")}, TODAY) == []
    # A changed expiry date is a new reminder.
    assert reminders.due([b(expiry_date="2026-10-08")], SETTINGS, {("x", "2026-10-09")}, TODAY)


def test_soonest_first():
    items = reminders.due([b(id="a", expiry_date="2026-10-08"), b(id="b", expiry_date="2026-10-03")],
                          SETTINGS, set(), TODAY)
    assert [i["id"] for i in items] == ["b", "a"]


def test_parse_reminder():
    assert reminders.parse_reminder(None) is None
    assert reminders.parse_reminder("off") == "off"
    assert reminders.parse_reminder("30") == 30
    for bad in ("5", "soon", 1000):
        try:
            reminders.parse_reminder(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} was accepted")


# --- Sending ------------------------------------------------------------------------------------

def test_sends_once(user, sent_emails):
    add_benefit(user["id"], benefit_name="Spa voucher", expiry_date="2026-10-05")
    assert reminders.run_due(MORNING) == 1
    assert reminders.run_due(MORNING) == 0  # the next 15-minute check
    ((to, subject, text),) = sent_emails
    assert to == user["email"]
    assert "Spa voucher" in subject and "Spa voucher" in text


def test_several_benefits_share_one_email(user, sent_emails):
    add_benefit(user["id"], benefit_name="A", expiry_date="2026-10-05")
    add_benefit(user["id"], benefit_name="B", expiry_date="2026-10-06")
    assert reminders.run_due(MORNING) == 1
    assert sent_emails[0][1] == "Reminder: 2 benefits expiring soon"


def test_nothing_before_8am_local_time(user, sent_emails):
    add_benefit(user["id"], expiry_date="2026-10-05")
    assert reminders.run_due(EARLY) == 0
    assert sent_emails == []


def test_follows_the_users_time_zone(sent_emails):
    # 23:00 UTC is 07:00 in Singapore (too early) but 19:00 in New York.
    sg = make_user("sg@example.com", timezone="Asia/Singapore")
    ny = make_user("ny@example.com", timezone="America/New_York")
    add_benefit(sg["id"], expiry_date="2026-10-05")
    add_benefit(ny["id"], expiry_date="2026-10-05")
    reminders.run_due(EARLY)
    assert [to for to, _, _ in sent_emails] == ["ny@example.com"]
    reminders.run_due(MORNING)  # 09:00 in Singapore
    assert [to for to, _, _ in sent_emails] == ["ny@example.com", "sg@example.com"]


def test_never_emails_an_unconfirmed_address(sent_emails):
    stranger = make_user("someone@example.com", verified=False)
    add_benefit(stranger["id"], expiry_date="2026-10-05")
    assert reminders.run_due(MORNING) == 0


def test_switched_off_user_gets_nothing(user, sent_emails):
    add_benefit(user["id"], expiry_date="2026-10-05")
    with db.connect() as conn:
        reminders.set_enabled(conn, user["id"], False)
    assert reminders.run_due(MORNING) == 0


def test_removed_benefits_are_not_reminded(user, sent_emails):
    bid = add_benefit(user["id"], expiry_date="2026-10-05")
    with db.connect() as conn:
        db.dismiss_benefit(conn, user["id"], bid)
    assert reminders.run_due(MORNING) == 0


def test_failed_send_is_tried_again(user, sent_emails, monkeypatch):
    add_benefit(user["id"], expiry_date="2026-10-05")
    import mailer

    def down(*args):
        raise OSError("SMTP server unreachable")
    monkeypatch.setattr(mailer, "send", down)
    assert reminders.run_due(MORNING) == 0
    monkeypatch.setattr(mailer, "send", lambda to, subject, text: sent_emails.append((to, subject, text)))
    assert reminders.run_due(MORNING) == 1


def test_failed_sends_are_recorded_until_one_works(user, sent_emails, monkeypatch):
    add_benefit(user["id"], expiry_date="2026-10-05")
    import mailer

    def down(*args):
        raise OSError("SMTP server unreachable")
    monkeypatch.setattr(mailer, "send", down)
    reminders.run_due(MORNING)
    with db.connect() as conn:
        first = reminders.failing_since(conn, user["id"])
        conn.execute("UPDATE reminder_settings SET failing_since = '2026-10-01T00:00:00+00:00' WHERE user_id = ?",
                     (user["id"],))
    assert first is not None
    reminders.run_due(MORNING)
    with db.connect() as conn:  # the first failure is kept
        assert reminders.failing_since(conn, user["id"]) == "2026-10-01T00:00:00+00:00"
        assert reminders.get_settings(conn, user["id"])["timezone"] == "Asia/Singapore"
    monkeypatch.setattr(mailer, "send", lambda to, subject, text: sent_emails.append((to, subject, text)))
    assert reminders.run_due(MORNING) == 1
    with db.connect() as conn:
        assert reminders.failing_since(conn, user["id"]) is None
