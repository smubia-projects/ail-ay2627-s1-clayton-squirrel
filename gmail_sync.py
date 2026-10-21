"""
gmail_sync.py

Scans a user's connected Gmail for benefit emails in a background thread and
runs each new one through the extraction engine in app.py.

- Gmail search narrows the inbox to likely benefit emails first, so the AI model
  only reads candidates.
- Each scan reads at most scan_jobs.MAX_EMAILS_PER_SCAN new emails, to keep API cost and
  wait time predictable. Running another scan continues with older ones.
- An email is marked as processed only after the AI model has read it, so emails
  that failed are retried on the next scans (up to scan_jobs.MAX_TRIES times).
"""

import logging
from typing import Optional
from urllib.parse import quote

import config
import db
import google_api
import loyalty
import reminders
import scan_jobs

log = logging.getLogger(__name__)


def _gmail_term(word: str) -> str:
    return f'"{word}"' if not word.isalpha() else word


SEARCH_QUERY = (
    f"newer_than:{scan_jobs.SEARCH_DAYS}d -in:chats -in:sent -in:drafts ("
    + " OR ".join(_gmail_term(w) for w in scan_jobs.KEYWORDS)
    + ")"
    # Squirrel's own reminders list benefits too; they aren't new ones.
    + (f" -from:{config.MAIL_FROM_ADDRESS}" if config.MAIL_FROM_ADDRESS else "")
)


def _job_key(user_id: str) -> str:
    return f"gmail:{user_id}"


def connection(user_id: str) -> Optional[dict]:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT email, connected_at, last_sync_at FROM gmail_connections WHERE user_id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def save_connection(user_id: str, email: str, refresh_token: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO gmail_connections (user_id, email, refresh_token_enc, connected_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET email = excluded.email, "
            "refresh_token_enc = excluded.refresh_token_enc, connected_at = excluded.connected_at",
            (user_id, email, db.encrypt(refresh_token), db.now_iso()),
        )


def disconnect(user_id: str, revoke: bool = True) -> None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT refresh_token_enc FROM gmail_connections WHERE user_id = ?", (user_id,)
        ).fetchone()
        conn.execute("DELETE FROM gmail_connections WHERE user_id = ?", (user_id,))
    if row and revoke:
        try:
            google_api.revoke(db.decrypt(row["refresh_token_enc"]))
        except Exception:
            pass  # key changed or token unreadable; the local copy is gone either way


def status(user_id: str) -> dict:
    return scan_jobs.status(_job_key(user_id))


def start_scan(user_id: str) -> dict:
    """Starts a scan unless one is already running. Returns the job status."""
    if connection(user_id) is None:
        raise google_api.GoogleError("Connect Gmail first.")
    return scan_jobs.start(_job_key(user_id), lambda job: _run(user_id, job))


def _run(user_id: str, job: dict) -> None:
    try:
        _scan(user_id, job)
    except google_api.GoogleAccessRevoked as e:
        log.warning("Gmail scan: access revoked (%s)", e)
        disconnect(user_id, revoke=False)
        scan_jobs.update(job, state="error", message="Gmail access was revoked or expired. Connect Gmail again.")
    except google_api.GoogleError as e:
        log.warning("Gmail scan failed: %s", e)
        scan_jobs.update(job, state="error", message=str(e))
    except Exception:
        log.exception("Gmail scan failed unexpectedly")
        scan_jobs.update(job, state="error", message="The scan failed unexpectedly. See the terminal running server.py.")


def _loyalty_finder(access_token: str) -> loyalty.Finder:
    def find(program: dict, activity: bool) -> Optional[dict]:
        # Gmail's from: search is loose, so confirm the sender's domain.
        for message in google_api.search_messages(access_token, loyalty.gmail_query(program, activity), 5):
            headers = google_api.get_message_headers(access_token, message["id"])
            if loyalty.sender_matches(program, headers["from"]):
                return headers
        return None
    return find


def _scan(user_id: str, job: dict) -> None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT email, refresh_token_enc FROM gmail_connections WHERE user_id = ?", (user_id,)
        ).fetchone()
        done = scan_jobs.finished_emails(conn, user_id)
        today = reminders.user_today(conn, user_id)
    if row is None:
        raise google_api.GoogleError("Connect Gmail first.")
    gmail_address = row["email"]

    access_token = google_api.refresh_access_token(db.decrypt(row["refresh_token_enc"]))
    scan_jobs.update(job, memberships=loyalty.detect(user_id, _loyalty_finder(access_token), today))
    matches = google_api.search_messages(access_token, SEARCH_QUERY, scan_jobs.SEARCH_LIMIT + 1)
    batch = scan_jobs.take_batch(user_id, job, matches, lambda m: m["id"] not in done, today)

    def tasks():
        for message in batch:
            email = google_api.get_message(access_token, message["id"])
            extra = {
                "source_link": f"https://mail.google.com/mail/?authuser={quote(gmail_address)}#all/{email['thread_id']}",
                "source_label": email["subject"][:200] or None,
            }
            yield message["id"], email, "gmail", f"gmail:{message['id']}", extra

    if not scan_jobs.extract_all(user_id, job, tasks(), today):
        return

    with db.connect() as conn:
        conn.execute("UPDATE gmail_connections SET last_sync_at = ? WHERE user_id = ?", (db.now_iso(), user_id))
    scan_jobs.update(job, state="done")
