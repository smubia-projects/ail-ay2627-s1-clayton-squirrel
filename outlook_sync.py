"""
outlook_sync.py

Scans a user's connected Outlook, Hotmail or Microsoft 365 mailbox for benefit
emails in a background thread, the same way gmail_sync.py scans Gmail: a
search narrows the mailbox to likely benefit emails, then each new one goes
through the AI extraction in scan_jobs.

- Searches every folder except Sent, Drafts, Deleted and Junk, so archived
  email counts.
- Each scan reads at most scan_jobs.MAX_EMAILS_PER_SCAN new emails; running
  another continues with older ones. Emails the AI model fails on are retried
  on the next scans (up to scan_jobs.MAX_TRIES times).
- Microsoft has no endpoint for an app to give up its own access, so
  disconnecting deletes the stored token and tells the user where to remove
  Squirrel from their Microsoft account.
"""

import logging
from datetime import date, timedelta
from typing import Optional

import config
import db
import loyalty
import microsoft_api
import reminders
import scan_jobs

log = logging.getLogger(__name__)


def _term(word: str) -> str:
    return word if word.isalpha() else f'"{word}"'


def search_query(today: date) -> str:
    """KQL for recent emails mentioning any benefit keyword."""
    since = today - timedelta(days=scan_jobs.SEARCH_DAYS)
    query = f"received>={since.isoformat()} AND ({' OR '.join(_term(w) for w in scan_jobs.KEYWORDS)})"
    # Squirrel's own reminders list benefits too; they aren't new ones.
    if config.MAIL_FROM_ADDRESS:
        query += f" AND NOT from:{config.MAIL_FROM_ADDRESS}"
    return query


def _job_key(user_id: str) -> str:
    return f"outlook:{user_id}"


def connection(user_id: str) -> Optional[dict]:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT email, connected_at, last_sync_at FROM outlook_connections WHERE user_id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def save_connection(user_id: str, email: str, refresh_token: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO outlook_connections (user_id, email, refresh_token_enc, connected_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET email = excluded.email, "
            "refresh_token_enc = excluded.refresh_token_enc, connected_at = excluded.connected_at",
            (user_id, email, db.encrypt(refresh_token), db.now_iso()),
        )


def disconnect(user_id: str) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM outlook_connections WHERE user_id = ?", (user_id,))
    scan_jobs.forget(_job_key(user_id))


def status(user_id: str) -> dict:
    return scan_jobs.status(_job_key(user_id))


def start_scan(user_id: str) -> dict:
    """Starts a scan unless one is already running. Returns the job status."""
    if connection(user_id) is None:
        raise microsoft_api.MicrosoftError("Connect Outlook first.")
    return scan_jobs.start(_job_key(user_id), lambda job: _run(user_id, job))


def _run(user_id: str, job: dict) -> None:
    try:
        _scan(user_id, job)
    except microsoft_api.MicrosoftAccessRevoked as e:
        log.warning("Outlook scan: access revoked (%s)", e)
        disconnect(user_id)
        scan_jobs.update(job, state="error", message="Outlook access was removed or expired. Connect Outlook again.")
    except microsoft_api.MicrosoftError as e:
        log.warning("Outlook scan failed: %s", e)
        scan_jobs.update(job, state="error", message=str(e))
    except Exception:
        log.exception("Outlook scan failed unexpectedly")
        scan_jobs.update(job, state="error", message="The scan failed unexpectedly. See the terminal running server.py.")


def _loyalty_finder(access_token: str, today: date) -> loyalty.Finder:
    since = loyalty.since(today)

    def find(program: dict, activity: bool) -> Optional[dict]:
        messages = microsoft_api.search_messages(
            access_token, loyalty.outlook_query(program, activity, since), 5, select="from,subject,receivedDateTime")
        # Search matches loosely, so confirm the sender's domain.
        for m in messages:
            headers = {"from": microsoft_api.from_header(m), "subject": m.get("subject") or "",
                       "received_date": microsoft_api.received_date(m)}
            if loyalty.sender_matches(program, headers["from"]):
                return headers
        return None
    return find


def _scan(user_id: str, job: dict) -> None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT refresh_token_enc FROM outlook_connections WHERE user_id = ?", (user_id,)
        ).fetchone()
        done = scan_jobs.finished_emails(conn, user_id, "outlook:")
        today = reminders.user_today(conn, user_id)
    if row is None:
        raise microsoft_api.MicrosoftError("Connect Outlook first.")

    access_token, refresh_token = microsoft_api.refresh(db.decrypt(row["refresh_token_enc"]))
    with db.connect() as conn:  # the old refresh token stops working soon
        conn.execute("UPDATE outlook_connections SET refresh_token_enc = ? WHERE user_id = ?",
                     (db.encrypt(refresh_token), user_id))

    scan_jobs.update(job, memberships=loyalty.detect(user_id, _loyalty_finder(access_token, today), today))
    skipped = microsoft_api.skipped_folder_ids(access_token)
    found = microsoft_api.search_messages(access_token, search_query(today), scan_jobs.SEARCH_LIMIT + 1)
    batch = [m["id"] for m in scan_jobs.take_batch(
        user_id, job, found, lambda m: m.get("parentFolderId") not in skipped and f"outlook:{m['id']}" not in done,
        today)]

    def tasks():
        for message_id in batch:
            email = microsoft_api.get_message(access_token, message_id)
            extra = {"source_link": email["link"], "source_label": email["subject"][:200] or None}
            key = f"outlook:{message_id}"
            yield key, email, "outlook", key, extra

    if not scan_jobs.extract_all(user_id, job, tasks(), today):
        return

    with db.connect() as conn:
        conn.execute("UPDATE outlook_connections SET last_sync_at = ? WHERE user_id = ?", (db.now_iso(), user_id))
    scan_jobs.update(job, state="done")
