"""
reminders.py

Emails users before their benefits expire. server.py starts a background
thread that calls run_due() every 15 minutes; each user gets at most one email
per check, listing every benefit whose reminder day has come.

- Each benefit has its own reminder, set from its ⋯ menu: data["reminder"] is
  None (DEFAULT_DAYS before), "off", or a number of days before expiry
  (DAY_CHOICES, 1 week to 1 year).
- reminder_settings keeps each user's time zone, and an on/off switch with no
  screen of its own: it keeps the demo account (an example.com address) quiet.
- Each benefit is reminded once per expiry date (reminders_sent), so a
  changed date gets a new reminder. Card credits are a new benefit each
  period, so they're reminded every period.
- Benefits waiting for review are skipped: their date isn't confirmed.
- A failed send is tried again at the next check. reminder_settings.failing_since
  keeps when the failures started, so the app can tell the user.
- Days and SEND_FROM_HOUR follow each user's own time zone (sent by their
  browser; the server's until it is), so nothing arrives before 8am where they
  are. A reminder whose day has already passed when it's set up (a benefit
  added 2 days before it expires, with a 1-week reminder) goes out at the next
  check.
"""

import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import cards
import config
import db
import mailer

DEFAULT_DAYS = 7
DAY_CHOICES = (7, 14, 30, 60, 90, 180, 365)
SEND_FROM_HOUR = 8
CHECK_EVERY_SECONDS = 15 * 60

log = logging.getLogger(__name__)

Reminder = Union[int, str, None]


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_settings(conn, user_id: str) -> dict:
    row = conn.execute("SELECT enabled, timezone FROM reminder_settings WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return {"enabled": True, "timezone": None}
    return {"enabled": bool(row["enabled"]), "timezone": row["timezone"]}


def set_enabled(conn, user_id: str, enabled: bool) -> None:
    """Turns all of a user's reminder emails on or off; the time zone is kept."""
    conn.execute(
        "INSERT INTO reminder_settings (user_id, enabled, days_before) VALUES (?, ?, ?) "
        "ON CONFLICT (user_id) DO UPDATE SET enabled = excluded.enabled",
        (user_id, int(enabled), DEFAULT_DAYS),
    )


def save_timezone(conn, user_id: str, name: str) -> None:
    """Raises ValueError if name isn't a known time zone."""
    if not valid_timezone(name):
        raise ValueError("Unknown time zone.")
    conn.execute(
        "INSERT INTO reminder_settings (user_id, enabled, days_before, timezone) VALUES (?, 1, ?, ?) "
        "ON CONFLICT (user_id) DO UPDATE SET timezone = excluded.timezone",
        (user_id, DEFAULT_DAYS, name),
    )


def failing_since(conn, user_id: str) -> Optional[str]:
    """When reminder emails to this user started failing (UTC, ISO), or None if the last one went out."""
    row = conn.execute("SELECT failing_since FROM reminder_settings WHERE user_id = ?", (user_id,)).fetchone()
    return row["failing_since"] if row else None


def _record_failure(conn, user_id: str) -> None:
    """Keeps the first failure, so the app can say how long reminders haven't been getting through."""
    conn.execute(
        "INSERT INTO reminder_settings (user_id, enabled, days_before, failing_since) VALUES (?, 1, ?, ?) "
        "ON CONFLICT (user_id) DO UPDATE SET failing_since = COALESCE(failing_since, excluded.failing_since)",
        (user_id, DEFAULT_DAYS, db.now_iso()),
    )


def valid_timezone(name) -> bool:
    if not isinstance(name, str) or not name or len(name) > 64:
        return False
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def local_now(settings: dict, now_utc: datetime) -> datetime:
    """The time where the user is (the server's time zone until their browser has told us theirs)."""
    if settings.get("timezone") and valid_timezone(settings["timezone"]):
        return now_utc.astimezone(ZoneInfo(settings["timezone"]))
    return now_utc.astimezone()


def user_today(conn, user_id: str) -> date:
    """
    Today's date where the user is. Everything that depends on the date (days
    left, card credit periods, "used on") uses this, not the server's date.
    """
    return local_now(get_settings(conn, user_id), datetime.now(timezone.utc)).date()


def parse_reminder(value) -> Reminder:
    """A benefit's reminder from a request: None (the default), "off" or days before expiry."""
    if value in (None, "", "default"):
        return None
    if value == "off":
        return "off"
    try:
        days = int(value)
    except (TypeError, ValueError):
        raise ValueError("Pick when to be reminded from the list.") from None
    if days not in DAY_CHOICES:
        raise ValueError("Pick when to be reminded from the list.")
    return days


# ---------------------------------------------------------------------------
# Working out what's due
# ---------------------------------------------------------------------------

def lead_days(benefit: dict, settings: dict) -> Optional[int]:
    """Days before expiry to remind about this benefit, or None for no reminder."""
    if not settings["enabled"]:
        return None
    choice = benefit.get("reminder")
    if choice == "off":
        return None
    return choice if isinstance(choice, int) else DEFAULT_DAYS


def due(benefits: list[dict], settings: dict, sent: set[tuple[str, str]], today: date) -> list[dict]:
    """The benefits to remind about today, soonest expiry first."""
    out = []
    for b in benefits:
        if b.get("needs_review") or b.get("used_on") or not b.get("expiry_date"):
            continue
        lead = lead_days(b, settings)
        if lead is None or (b["id"], b["expiry_date"]) in sent:
            continue
        try:
            expiry = date.fromisoformat(b["expiry_date"])
        except ValueError:
            continue
        if expiry - timedelta(days=lead) <= today <= expiry:
            out.append(b)
    return sorted(out, key=lambda b: b["expiry_date"])


# ---------------------------------------------------------------------------
# The email
# ---------------------------------------------------------------------------

def _when(expiry: date, today: date) -> str:
    days = (expiry - today).days
    on = f"{expiry:%a} {expiry.day} {expiry:%b}" + (f" {expiry.year}" if expiry.year != today.year else "")
    if days == 0:
        return "expires today"
    if days == 1:
        return f"expires tomorrow, {on}"
    return f"expires in {days} days, on {on}"


def _worth(b: dict) -> Optional[str]:
    if b.get("points") is not None:
        return f"{b['points']:,} {b.get('points_unit') or 'points'}"
    return b.get("value")


def compose(name: Optional[str], benefits: list[dict], today: date) -> tuple[str, str]:
    """(subject, text) of the reminder email."""
    if len(benefits) == 1:
        b = benefits[0]
        subject = f"Reminder: {b['benefit_name']} {_when(date.fromisoformat(b['expiry_date']), today).split(',')[0]}"
    else:
        subject = f"Reminder: {len(benefits)} benefits expiring soon"

    lines = [f"Hi {name.split()[0]}," if name else "Hi,", "",
             "This benefit is expiring soon:" if len(benefits) == 1 else "These benefits are expiring soon:", ""]
    for b in benefits:
        details = ", ".join(filter(None, [b.get("provider"), _worth(b)]))
        lines.append(f"- {b['benefit_name']}{f' ({details})' if details else ''}: "
                     f"{_when(date.fromisoformat(b['expiry_date']), today)}")
        if b.get("terms_summary"):
            lines.append(f"  {b['terms_summary']}")
    lines += ["", f"See everything in Squirrel: {config.APP_URL}/benefits", "",
              "To change when you're reminded about a benefit, or stop its reminders, "
              "choose Reminder in its ⋯ menu in Squirrel."]
    return subject, "\n".join(lines)


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def run_due(now: Optional[datetime] = None) -> int:
    """Sends every reminder that's due. Returns how many emails were sent."""
    now = now or datetime.now(timezone.utc)
    with db.connect() as conn:
        # Only confirmed addresses: an unconfirmed one may belong to someone else.
        users = conn.execute("SELECT id, email, name FROM users WHERE email_verified_at IS NOT NULL").fetchall()

    emails = 0
    for user in users:
        with db.connect() as conn:
            settings = get_settings(conn, user["id"])
            local = local_now(settings, now)
            if not settings["enabled"] or local.hour < SEND_FROM_HOUR:
                continue
            today = local.date()
            cards.sync_card_benefits(conn, user["id"], today)  # so a new period's credits are included
            benefits = db.list_benefits(conn, user["id"])
            sent = {(r["benefit_id"], r["expiry_date"]) for r in conn.execute(
                "SELECT benefit_id, expiry_date FROM reminders_sent WHERE user_id = ?", (user["id"],))}
        items = due(benefits, settings, sent, today)
        if not items:
            continue
        try:
            mailer.send(user["email"], *compose(user["name"], items, today))
        except Exception as e:  # noqa: BLE001 - try again at the next check
            log.warning("Reminder email to user %s failed: %s: %s", user["id"], type(e).__name__, e)
            with db.connect() as conn:
                _record_failure(conn, user["id"])
            continue
        with db.connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO reminders_sent (user_id, benefit_id, expiry_date, sent_at) VALUES (?, ?, ?, ?)",
                [(user["id"], b["id"], b["expiry_date"], db.now_iso()) for b in items],
            )
            conn.execute("UPDATE reminder_settings SET failing_since = NULL WHERE user_id = ?", (user["id"],))
        emails += 1
    return emails


def _loop() -> None:
    while True:
        try:
            run_due()
        except Exception:  # noqa: BLE001 - keep checking even if one run fails
            log.exception("Reminder check failed")
        try:
            # Same timer: benefits removed over db.REMOVED_KEEP_DAYS ago are deleted for good,
            # even for users who never open Recently removed.
            with db.connect() as conn:
                db.purge_removed_benefits(conn)
        except Exception:  # noqa: BLE001
            log.exception("Clearing removed benefits failed")
        time.sleep(CHECK_EVERY_SECONDS)


def start() -> None:
    threading.Thread(target=_loop, name="reminders", daemon=True).start()
