"""
db.py

SQLite storage (standard library) for users, sessions, connections and
benefits, plus encryption for stored Google tokens.

Everything lives in instance/: the database and, unless BENEFITAPP_SECRET_KEY
is set, the key that encrypts Gmail refresh tokens and IMAP app passwords.
Losing the key means users have to reconnect their email; nothing else
depends on it.
"""

import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional

from cryptography.fernet import Fernet

from config import INSTANCE_DIR

DB_PATH = INSTANCE_DIR / "benefitapp.db"
KEY_PATH = INSTANCE_DIR / "secret.key"
REMOVED_KEEP_DAYS = 30  # removed benefits can be restored for this long, then they're deleted for good

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name          TEXT,
    password_hash TEXT,             -- NULL for Google-only accounts
    google_sub    TEXT UNIQUE,      -- Google's stable account id
    created_at    TEXT NOT NULL,
    -- When the user proved they own the address (Google said so, or they used
    -- a reset link sent to it). NULL means never: anyone could have typed it.
    email_verified_at TEXT,
    -- Last time the user used the app (auth.user_for_session, at most hourly).
    last_active_at TEXT,
    -- The daily scan (auto_scan.py): off (0) until the user turns it on, and
    -- the user's local date it last started.
    auto_scan         INTEGER NOT NULL DEFAULT 0,
    auto_scan_last_on TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,    -- sha256 of the cookie value; the raw token is never stored
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);

-- Email confirmation links (auth.create_verification_link). Like reset links,
-- only the token's sha256 is stored. email is the address the link was sent
-- to, so a link stops working if the address is changed afterwards.
CREATE TABLE IF NOT EXISTS email_verifications (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email      TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

-- One-time password reset links. Like sessions, only the token's sha256 is stored.
CREATE TABLE IF NOT EXISTS password_resets (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_states (
    state         TEXT PRIMARY KEY,
    purpose       TEXT NOT NULL,    -- 'login' or 'connect'
    user_id       TEXT,             -- set for 'connect'
    code_verifier TEXT NOT NULL,    -- PKCE
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gmail_connections (
    user_id           TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    email             TEXT NOT NULL,
    refresh_token_enc BLOB NOT NULL,
    connected_at      TEXT NOT NULL,
    last_sync_at      TEXT
);

-- Outlook / Hotmail / Microsoft 365, read through Microsoft Graph (outlook_sync.py).
-- Microsoft replaces the refresh token on each use, so it's saved again after every scan.
CREATE TABLE IF NOT EXISTS outlook_connections (
    user_id           TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    email             TEXT NOT NULL,
    refresh_token_enc BLOB NOT NULL,
    connected_at      TEXT NOT NULL,
    last_sync_at      TEXT
);

-- Email accounts read over IMAP (Yahoo, iCloud, AOL, ...) with an app password.
CREATE TABLE IF NOT EXISTS imap_accounts (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email        TEXT NOT NULL COLLATE NOCASE,
    host         TEXT NOT NULL,
    password_enc BLOB NOT NULL,     -- app password, encrypted like Gmail tokens
    connected_at TEXT NOT NULL,
    last_sync_at TEXT,
    UNIQUE (user_id, email)
);

-- Emails sent to the AI model. message_id is Gmail's id, 'outlook:<Graph id>' or
-- 'imap:<account id>:<uidvalidity>:<uid>'. done = 1 once it's been read, so
-- it's never read again; one the model keeps failing on is tried again by
-- later scans until failures reaches scan_jobs.MAX_TRIES, then skipped.
-- filtered = 1: scan_jobs.looks_promotional skipped it without the AI model.
-- To have those read again after changing the filter, delete those rows.
CREATE TABLE IF NOT EXISTS processed_emails (
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message_id TEXT NOT NULL,
    done       INTEGER NOT NULL DEFAULT 1,
    failures   INTEGER NOT NULL DEFAULT 0,
    filtered   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, message_id)
);

-- Inbox scans in progress (scan_jobs.py), by job key. A row left when the
-- server starts is a scan the last restart cut short.
CREATE TABLE IF NOT EXISTS running_scans (
    job_key    TEXT PRIMARY KEY,
    started_at TEXT NOT NULL
);

-- Emails sent to the AI model per user per day (the user's local date), for
-- scan_jobs.DAILY_EMAIL_CAP. Kept in the database so a restart doesn't reset it.
CREATE TABLE IF NOT EXISTS ai_email_usage (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day     TEXT NOT NULL,
    emails  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);

CREATE TABLE IF NOT EXISTS user_cards (
    id                TEXT PRIMARY KEY,
    user_id           TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    card_key          TEXT NOT NULL,
    anniversary_month INTEGER,
    added_at          TEXT NOT NULL,
    UNIQUE (user_id, card_key)
);

-- data is an ExtractedBenefit (app.py) as JSON. source_ref identifies where a
-- benefit came from ('gmail:<message id>', 'outlook:<Graph id>', 'imap:<account>:<uidvalidity>:<uid>',
-- 'card:<card>:<perk>:<period end>' or 'manual:<id>')
-- so the same benefit is never added twice. Dismissed rows are kept so they
-- don't come back on the next scan.
CREATE TABLE IF NOT EXISTS benefits (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source     TEXT NOT NULL,       -- 'gmail', 'outlook', 'imap', 'loyalty', 'card' or 'manual' (added by the user)
    source_ref TEXT NOT NULL,
    -- 'active'; 'dismissed' (removed, can be restored for REMOVED_KEEP_DAYS); or
    -- 'deleted': removed for good, data emptied. The row stays, with its
    -- source_ref, so scans and card or loyalty checks don't add it back.
    status     TEXT NOT NULL DEFAULT 'active',
    data       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    dismissed_at TEXT,                  -- when it was removed
    UNIQUE (user_id, source_ref)
);

-- Email reminders (reminders.py). No row means on. days_before and categories
-- are left from account-wide reminder settings, replaced by each benefit's own.
CREATE TABLE IF NOT EXISTS reminder_settings (
    user_id     TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    enabled     INTEGER NOT NULL,
    days_before INTEGER NOT NULL,
    categories  TEXT NOT NULL DEFAULT '{}',  -- JSON {category: days before, or "off"}
    timezone    TEXT,                        -- IANA name from the browser, e.g. "Asia/Singapore"
    failing_since TEXT                       -- first failed send since the last one that worked
);

-- One row per benefit and expiry date already reminded about.
CREATE TABLE IF NOT EXISTS reminders_sent (
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    benefit_id  TEXT NOT NULL,
    expiry_date TEXT NOT NULL,
    sent_at     TEXT NOT NULL,
    PRIMARY KEY (benefit_id, expiry_date)
);

-- Assistant questions and answers, newest shown first.
CREATE TABLE IF NOT EXISTS ask_history (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    question   TEXT NOT NULL,
    answer     TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ask_history_user ON ask_history (user_id, created_at);

-- Each user's last weekly digest. key is a hash of what it was built from
-- (their benefits and the date), so it's only rebuilt when one changes.
CREATE TABLE IF NOT EXISTS digest_cache (
    user_id    TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    key        TEXT NOT NULL,
    digest     TEXT NOT NULL,       -- JSON, as returned by /api/digest
    created_at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return secrets.token_hex(6)


def init() -> None:
    INSTANCE_DIR.mkdir(mode=0o700, exist_ok=True)
    with connect() as conn:
        verification_is_new = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'email_verifications'").fetchone() is None
        conn.executescript(SCHEMA)
        _add_columns(conn, "reminder_settings", {"categories": "TEXT NOT NULL DEFAULT '{}'", "timezone": "TEXT",
                                                 "failing_since": "TEXT"})
        if _add_columns(conn, "users", {"email_verified_at": "TEXT"}):
            # Accounts made before this column: Google had verified the address of any linked to Google.
            conn.execute("UPDATE users SET email_verified_at = created_at WHERE google_sub IS NOT NULL")
        if verification_is_new:
            # Email verification arrived on 6 October 2026. The owner knows everyone who signed up
            # before then, so their accounts count as confirmed.
            conn.execute("UPDATE users SET email_verified_at = COALESCE(email_verified_at, created_at)")
        _add_columns(conn, "processed_emails", {"done": "INTEGER NOT NULL DEFAULT 1",
                                                "failures": "INTEGER NOT NULL DEFAULT 0",
                                                "filtered": "INTEGER NOT NULL DEFAULT 0"})
        if _add_columns(conn, "benefits", {"dismissed_at": "TEXT"}):
            # Removed before this column: they get the full time in Recently removed from now.
            conn.execute("UPDATE benefits SET dismissed_at = ? WHERE status = 'dismissed'", (now_iso(),))
        _add_columns(conn, "users", {"last_active_at": "TEXT", "auto_scan": "INTEGER NOT NULL DEFAULT 0",
                                     "auto_scan_last_on": "TEXT"})
        _add_benefit_types(conn)


def _add_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> bool:
    """Adds columns that a database made by an older version doesn't have yet. True if any were added."""
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    added = False
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
            added = True
    return added


# Words that suggest a spending category, checked in this order. Used once, to
# give benefits saved before categories existed a best guess.
_CATEGORY_WORDS = {
    "dining": ["dining", "restaurant", "resy", "coffee", "cafe", "bakery", "drink", "food", "eats", "doordash",
               "grubhub", "dunkin", "pizza", "burger", "meal", "brunch"],
    "transport": ["uber", "lyft", "grab", "gojek", "ride", "taxi", "transit", "parking", "fuel", "petrol"],
    "travel": ["hotel", "airline", "airways", "flight", "fare", "miles", "night", "travel", "resort", "lounge"],
    "entertainment": ["movie", "cinema", "theatre", "stream", "music", "concert", "ticket", "stubhub", "netflix",
                      "spotify", "game"],
    "wellness": ["gym", "fitness", "spa", "dental", "health", "clinic", "yoga", "massage", "pharmacy"],
    "shopping": ["store", "shop", "retail", "gift card", "books", "grocery", "mall", "outdoor"],
}
_CATEGORY_FROM_TYPE = {"travel": "travel", "health": "wellness", "retail": "shopping"}
# Types that were dropped because the categories cover them.
_RETIRED_TYPES = {"travel", "health", "retail"}
_MEMBERSHIP_WORDS = ["points", "miles", "avios", "member", "plan", "rewards"]


def _guess_category(data: dict) -> str:
    text = " ".join(filter(None, [data.get("benefit_name"), data.get("provider"), data.get("terms_summary")])).lower()
    for category, words in _CATEGORY_WORDS.items():
        if any(w in text for w in words):
            return category
    return _CATEGORY_FROM_TYPE.get(data.get("type"), "other")


def _add_benefit_types(conn: sqlite3.Connection) -> None:
    """
    Benefits used to have one "category" (membership, voucher...). That is now
    "type", and "category" is what it's spent on (dining, travel...). Moves the
    old value across and guesses the new one, then turns the dropped types
    (travel, health, retail) into a membership or a voucher. Rows already
    updated are left alone.
    """
    for row in conn.execute("SELECT id, source, data FROM benefits").fetchall():
        data = json.loads(row["data"])
        if "type" in data and data["type"] not in _RETIRED_TYPES:
            continue
        if "type" not in data:
            data["type"] = data.get("category") or "other"
            data["category"] = _guess_category(data)
        if data["type"] in _RETIRED_TYPES:
            name = f"{data.get('benefit_name') or ''} {data.get('provider') or ''}".lower()
            loyalty = row["source"] == "loyalty" or any(w in name for w in _MEMBERSHIP_WORDS)
            data["type"] = "membership" if loyalty else "voucher"
        conn.execute("UPDATE benefits SET data = ? WHERE id = ?", (json.dumps(data), row["id"]))


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """One short-lived connection per unit of work; commits on success, rolls back on error."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Benefits
# ---------------------------------------------------------------------------

def _row_to_record(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "source": row["source"], **json.loads(row["data"])}


def list_benefits(conn: sqlite3.Connection, user_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM benefits WHERE user_id = ? AND status = 'active' ORDER BY created_at, rowid",
        (user_id,),
    )
    return [_row_to_record(r) for r in rows]


def get_benefit(conn: sqlite3.Connection, user_id: str, benefit_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM benefits WHERE id = ? AND user_id = ? AND status = 'active'",
        (benefit_id, user_id),
    ).fetchone()
    return _row_to_record(row) if row else None


def add_benefit(conn: sqlite3.Connection, user_id: str, source: str, source_ref: str, data: dict,
                benefit_id: Optional[str] = None) -> bool:
    """Returns False if a benefit with this source_ref already exists (active or dismissed)."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO benefits (id, user_id, source, source_ref, data, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (benefit_id or new_id(), user_id, source, source_ref, json.dumps(data), now_iso()),
    )
    return cur.rowcount == 1


def update_benefit_data(conn: sqlite3.Connection, user_id: str, benefit_id: str, data: dict) -> None:
    conn.execute(
        "UPDATE benefits SET data = ? WHERE id = ? AND user_id = ?",
        (json.dumps(data), benefit_id, user_id),
    )


def dismiss_benefit(conn: sqlite3.Connection, user_id: str, benefit_id: str) -> bool:
    """Removes a benefit. It stays in Recently removed for REMOVED_KEEP_DAYS, then is deleted for good."""
    cur = conn.execute(
        "UPDATE benefits SET status = 'dismissed', dismissed_at = ? WHERE id = ? AND user_id = ? AND status = 'active'",
        (now_iso(), benefit_id, user_id),
    )
    return cur.rowcount == 1


def restore_benefit(conn: sqlite3.Connection, user_id: str, benefit_id: str) -> Optional[dict]:
    """Brings back a removed benefit still in Recently removed. Returns it, or None if it's gone."""
    purge_removed_benefits(conn)
    cur = conn.execute(
        "UPDATE benefits SET status = 'active', dismissed_at = NULL "
        "WHERE id = ? AND user_id = ? AND status = 'dismissed'",
        (benefit_id, user_id),
    )
    return get_benefit(conn, user_id, benefit_id) if cur.rowcount == 1 else None


def list_removed_benefits(conn: sqlite3.Connection, user_id: str) -> list[dict]:
    """Recently removed benefits, newest first, each with removed_at and delete_on (the date it goes for good)."""
    purge_removed_benefits(conn)
    rows = conn.execute(
        "SELECT * FROM benefits WHERE user_id = ? AND status = 'dismissed' ORDER BY dismissed_at DESC, rowid DESC",
        (user_id,),
    )
    return [{**_row_to_record(r), "removed_at": r["dismissed_at"],
             "delete_on": (datetime.fromisoformat(r["dismissed_at"]) + timedelta(days=REMOVED_KEEP_DAYS)).isoformat()}
            for r in rows]


def purge_removed_benefits(conn: sqlite3.Connection) -> int:
    """Deletes for good (every user) benefits removed more than REMOVED_KEEP_DAYS ago. Returns how many."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=REMOVED_KEEP_DAYS)).isoformat(timespec="seconds")
    return conn.execute(
        "UPDATE benefits SET status = 'deleted', data = '{}', dismissed_at = NULL "
        "WHERE status = 'dismissed' AND dismissed_at < ?",
        (cutoff,),
    ).rowcount


# ---------------------------------------------------------------------------
# Assistant history
# ---------------------------------------------------------------------------

ASK_HISTORY_LIMIT = 50  # older entries are deleted as new ones arrive


def list_ask_history(conn: sqlite3.Connection, user_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, question, answer, created_at FROM ask_history WHERE user_id = ? "
        "ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (user_id, ASK_HISTORY_LIMIT),
    )
    return [dict(r) for r in rows]


def add_ask_history(conn: sqlite3.Connection, user_id: str, question: str, answer: str) -> dict:
    entry = {"id": new_id(), "question": question, "answer": answer, "created_at": now_iso()}
    conn.execute(
        "INSERT INTO ask_history (id, user_id, question, answer, created_at) VALUES (?, ?, ?, ?, ?)",
        (entry["id"], user_id, question, answer, entry["created_at"]),
    )
    conn.execute(
        "DELETE FROM ask_history WHERE user_id = ? AND id NOT IN "
        "(SELECT id FROM ask_history WHERE user_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?)",
        (user_id, user_id, ASK_HISTORY_LIMIT),
    )
    return entry


def clear_ask_history(conn: sqlite3.Connection, user_id: str) -> None:
    conn.execute("DELETE FROM ask_history WHERE user_id = ?", (user_id,))


# ---------------------------------------------------------------------------
# Token encryption
# ---------------------------------------------------------------------------

_fernet: Optional[Fernet] = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = os.environ.get("BENEFITAPP_SECRET_KEY", "").encode()
        if not key:
            if not KEY_PATH.exists():
                INSTANCE_DIR.mkdir(mode=0o700, exist_ok=True)
                # O_EXCL: never overwrite a key that appeared in the meantime.
                fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(Fernet.generate_key())
            key = KEY_PATH.read_bytes().strip()
        _fernet = Fernet(key)
    return _fernet


def encrypt(value: str) -> bytes:
    return _get_fernet().encrypt(value.encode())


def decrypt(token: bytes) -> str:
    return _get_fernet().decrypt(token).decode()
