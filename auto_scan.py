"""
auto_scan.py

The daily scan: scans every connected inbox (Gmail, Outlook, IMAP) once a day,
for users who turn it on. It's off until the user turns it on.

There is no background schedule, so nothing is scanned while the user is
away: a scan only starts when the user opens Squirrel while signed in
(server.py calls maybe_start from /api/session) or turns the daily scan on,
at most once per day in the user's time zone. It has the same limits as
pressing "Scan inbox" (scan_jobs: the daily AI cap and the marketing filter).

Which scans the last daily scan started is kept in memory, for its summary;
a restart forgets it (the scans' results are kept).
"""

import logging
import threading
from functools import partial
from typing import Callable

import db
import gmail_sync
import imap_sync
import outlook_sync
import reminders

log = logging.getLogger(__name__)

# User id -> a status function for each scan the user's last daily scan started.
_started: dict[str, list[Callable[[], dict]]] = {}
_lock = threading.Lock()


def is_enabled(user_id: str) -> bool:
    with db.connect() as conn:
        row = conn.execute("SELECT auto_scan FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(row and row["auto_scan"])


def set_enabled(user_id: str, enabled: bool) -> None:
    with db.connect() as conn:
        conn.execute("UPDATE users SET auto_scan = ? WHERE id = ?", (1 if enabled else 0, user_id))


def maybe_start(user_id: str) -> None:
    """Starts the daily scan if it's on and hasn't run yet today (the user's date). Call only for a signed-in user."""
    with db.connect() as conn:
        today = reminders.user_today(conn, user_id).isoformat()
        # Claimed in one statement, so requests arriving together start it once.
        claimed = conn.execute(
            "UPDATE users SET auto_scan_last_on = ? WHERE id = ? AND auto_scan = 1 "
            "AND (auto_scan_last_on IS NULL OR auto_scan_last_on < ?)",
            (today, user_id, today)).rowcount == 1
    if not claimed:
        return

    sources: list[tuple[Callable[[], dict], Callable[[], dict]]] = []  # (start, status)
    if gmail_sync.connection(user_id):
        sources.append((partial(gmail_sync.start_scan, user_id), partial(gmail_sync.status, user_id)))
    if outlook_sync.connection(user_id):
        sources.append((partial(outlook_sync.start_scan, user_id), partial(outlook_sync.status, user_id)))
    for account in imap_sync.list_accounts(user_id):
        sources.append((partial(imap_sync.start_scan, user_id, account["id"]),
                        partial(imap_sync.status, account["id"])))

    started = []
    for start, status in sources:
        try:
            start()  # a scan already running (started by hand) is left alone, and still counted here
            started.append(status)
        except Exception:
            log.exception("Daily scan: an inbox scan couldn't start")
    with _lock:
        _started[user_id] = started


def status(user_id: str) -> dict:
    """Whether the daily scan is on, and the progress and totals of the scans it last started."""
    with _lock:
        checks = list(_started.get(user_id, []))
    scans = [check() for check in checks]
    return {
        "enabled": is_enabled(user_id),
        "running": any(s["state"] == "running" for s in scans),
        "added": sum(s.get("added", 0) for s in scans),
        "needs_review": sum(s.get("needs_review", 0) for s in scans),
        "memberships": sum(s.get("memberships", 0) for s in scans),
        "errors": sum(s["state"] == "error" for s in scans),
    }
