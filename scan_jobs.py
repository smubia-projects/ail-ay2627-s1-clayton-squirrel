"""
scan_jobs.py

What every inbox scan shares, whatever the provider (gmail_sync.py,
imap_sync.py):

- the words that make an email a likely benefit email, and the scan limits;
- background jobs with progress the dashboard polls;
- the per-email step: AI extraction, then storing the benefit, run for
  several emails at once.

Each scan also runs loyalty.detect first (no AI), so memberships are found
even when the AI step can't run.

Limits on what reaches the AI model (and so on API cost):
- An email that looks like a marketing blast (looks_promotional) is skipped
  without calling the model, and never checked again.
- Each user's emails sent to the model are capped per day (DAILY_EMAIL_CAP),
  across every scan and provider, counted in the database. Emails over the cap
  wait for a later scan.

Scan progress lives in memory, so restarting the server mid-scan loses it
(emails already read stay processed). Which scans are running is also kept in
the database, so after a restart those show as stopped (mark_interrupted)
instead of quietly disappearing.

An email the AI model fails on (a refusal, unusable output) is tried again by
the next scans, at most MAX_TRIES times in all; after that it's skipped, so a
few bad emails can't use up every scan's limit and keep older emails from being
read. The user can have those tried again (retry_given_up).
"""

import sqlite3
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict
from datetime import date
from typing import Callable, Iterable

import db
from app import describe_ai_error, extract_benefit_from_email

# An email must mention one of these to be read at all, so the AI model only
# sees likely candidates.
KEYWORDS = [
    "voucher", "coupon", "gift card", "e-gift", "membership", "perk", "perks", "reward", "rewards",
    "points expire", "credit", "valid until", "expires on", "expiring", "free trial", "renewal", "complimentary",
]
SEARCH_DAYS = 180
SEARCH_LIMIT = 200  # newest matching emails considered per scan
MAX_EMAILS_PER_SCAN = 50  # caps API cost and wait time per press; the next scan continues
AI_WORKERS = 5  # emails read by the AI model at the same time
MAX_TRIES = 3  # times the AI model may fail on one email before it's skipped
DAILY_EMAIL_CAP = 100  # emails sent to the AI model per user per day (their local date), all scans together

# looks_promotional: an email is skipped as a marketing blast when it has an
# unsubscribe link, at least one other marketing phrase, and none of the
# phrases that point to the user's own benefit. Kept cautious on purpose:
# a real benefit that's skipped is worse than an email read for nothing.
_PROMO_PHRASES = [
    "view in browser", "view in your browser", "view this email in your browser", "view online", "view as a web page",
    "% off", "shop now", "shop the", "sale ends", "flash sale", "newsletter", "new arrivals", "new collection",
    "limited time", "don't miss", "best sellers", "bestsellers", "trending now", "deals of the",
]
_PERSONAL_PHRASES = [
    "your voucher", "your e-voucher", "your coupon", "your gift card", "your e-gift", "your reward", "your points",
    "your miles", "your membership", "your subscription", "your plan", "your credit", "your free trial",
    "your trial", "your benefit", "your perk", "your code", "voucher code", "promo code", "coupon code",
    "redemption code", "valid until", "valid till", "valid through", "expires on", "expiry date",
    "expiration date", "points expire", "will expire", "been credited", "you've earned", "you have earned",
    "you've received", "you have received", "renews on", "renewal date", "membership number", "member id",
    "points balance", "miles balance",
]


def looks_promotional(text: str) -> bool:
    """True for a marketing email that's very unlikely to hold one of the user's own benefits. No AI."""
    t = text.lower().replace("\u2019", "'")
    return ("unsubscribe" in t
            and any(p in t for p in _PROMO_PHRASES)
            and not any(p in t for p in _PERSONAL_PHRASES))


def emails_read_today(conn: sqlite3.Connection, user_id: str, today: date) -> int:
    row = conn.execute("SELECT emails FROM ai_email_usage WHERE user_id = ? AND day = ?",
                       (user_id, today.isoformat())).fetchone()
    return row["emails"] if row else 0


def _claim_ai_email(user_id: str, today: date) -> bool:
    """Counts one more email for the AI model today, unless the daily cap is reached. Safe across scans."""
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO ai_email_usage (user_id, day, emails) VALUES (?, ?, 1) "
            "ON CONFLICT (user_id, day) DO UPDATE SET emails = emails + 1 WHERE emails < ?",
            (user_id, today.isoformat(), DAILY_EMAIL_CAP))
        return cur.rowcount == 1


def _release_ai_email(user_id: str, today: date) -> None:
    """Gives back a claimed email the AI model never read."""
    with db.connect() as conn:
        conn.execute("UPDATE ai_email_usage SET emails = MAX(emails - 1, 0) WHERE user_id = ? AND day = ?",
                     (user_id, today.isoformat()))


_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def status(key: str) -> dict:
    with _jobs_lock:
        job = _jobs.get(key)
        return dict(job) if job else {"state": "idle"}


def start(key: str, target: Callable[[dict], None]) -> dict:
    """Runs target(job) in a background thread unless a job with this key is running."""
    with _jobs_lock:
        job = _jobs.get(key)
        if job and job["state"] == "running":
            return dict(job)
        job = {"state": "running", "checked": 0, "total": None, "added": 0, "needs_review": 0,
               "skipped": 0, "filtered": 0, "failed": 0, "remaining": 0, "limit_reached": False,
               "daily_limit_reached": False, "memberships": 0, "message": None}
        _jobs[key] = job
    with db.connect() as conn:
        conn.execute("INSERT OR REPLACE INTO running_scans (job_key, started_at) VALUES (?, ?)", (key, db.now_iso()))

    def run() -> None:
        try:
            target(job)
        finally:
            with db.connect() as conn:
                conn.execute("DELETE FROM running_scans WHERE job_key = ?", (key,))

    threading.Thread(target=run, daemon=True).start()
    return dict(job)


INTERRUPTED = "The scan stopped when Squirrel restarted. Scan again to continue: emails already read won't be read again."


def mark_interrupted() -> int:
    """At startup: scans the restart cut short show as stopped, with a message. Returns how many."""
    with db.connect() as conn:
        keys = [r["job_key"] for r in conn.execute("SELECT job_key FROM running_scans")]
        conn.execute("DELETE FROM running_scans")
    with _jobs_lock:
        for key in keys:
            _jobs[key] = {"state": "error", "message": INTERRUPTED}
    return len(keys)


def update(job: dict, **changes) -> None:
    with _jobs_lock:
        job.update(changes)


def bump(job: dict, *counters: str) -> None:
    """Adds 1 to each counter. Safe while several emails are processed at once."""
    with _jobs_lock:
        for c in counters:
            job[c] += 1


def forget(key: str) -> None:
    with _jobs_lock:
        _jobs.pop(key, None)


def take_batch(user_id: str, job: dict, matches: list, is_new: Callable[[object], bool], today: date) -> list:
    """
    The emails this scan reads: of the newest SEARCH_LIMIT matches, the first
    MAX_EMAILS_PER_SCAN not read yet, and no more than what's left of today's
    DAILY_EMAIL_CAP. `matches` is newest first and searched with a limit of
    SEARCH_LIMIT + 1, so a search with more matches than the limit is noticed.
    Records the counts on the job; limit_reached means every email within the
    limit has been read but older matches exist.
    """
    with db.connect() as conn:
        allowance = max(DAILY_EMAIL_CAP - emails_read_today(conn, user_id, today), 0)
    candidates = [m for m in matches[:SEARCH_LIMIT] if is_new(m)]
    batch = candidates[:min(MAX_EMAILS_PER_SCAN, allowance)]
    remaining = len(candidates) - len(batch)
    update(job, total=len(batch), remaining=remaining,
           daily_limit_reached=remaining > 0 and len(batch) == allowance,
           limit_reached=remaining == 0 and len(matches) > SEARCH_LIMIT)
    return batch


def finished_emails(conn: sqlite3.Connection, user_id: str, prefix: str = "") -> set[str]:
    """Message keys (starting with prefix) not to send to the AI model again: read, or failed MAX_TRIES times."""
    return {r["message_id"] for r in conn.execute(
        "SELECT message_id FROM processed_emails WHERE user_id = ? AND message_id LIKE ? "
        "AND (done = 1 OR failures >= ?)",
        (user_id, f"{prefix}%", MAX_TRIES))}


def given_up(conn: sqlite3.Connection, user_id: str) -> int:
    """Emails the AI model failed on MAX_TRIES times, which scans now skip."""
    return conn.execute(
        "SELECT COUNT(*) FROM processed_emails WHERE user_id = ? AND done = 0 AND failures >= ?",
        (user_id, MAX_TRIES)).fetchone()[0]


def retry_given_up(conn: sqlite3.Connection, user_id: str) -> int:
    """Lets the next scans try those emails again (MAX_TRIES more times). Returns how many."""
    return conn.execute(
        "UPDATE processed_emails SET failures = 0 WHERE user_id = ? AND done = 0 AND failures >= ?",
        (user_id, MAX_TRIES)).rowcount


def _record_failure(user_id: str, message_key: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO processed_emails (user_id, message_id, done, failures) VALUES (?, ?, 0, 1) "
            "ON CONFLICT (user_id, message_id) DO UPDATE SET failures = failures + 1",
            (user_id, message_key))


def _expired(result, today: date) -> bool:
    """An offer whose stated date has already passed: nothing left to track."""
    try:
        return bool(result.expiry_date) and date.fromisoformat(result.expiry_date) < today
    except ValueError:
        return False


def _have_code(conn: sqlite3.Connection, user_id: str, result) -> bool:
    """The same voucher code is already tracked (it often arrives in several emails)."""
    code = (getattr(result, "code", None) or "").strip().upper()
    return bool(code) and conn.execute(
        "SELECT 1 FROM benefits WHERE user_id = ? AND status = 'active' "
        "AND UPPER(TRIM(json_extract(data, '$.code'))) = ?", (user_id, code)
    ).fetchone() is not None


def extract_and_store(user_id: str, job: dict, message_key: str, email: dict,
                      source: str, source_ref: str, extra: dict, today: date) -> bool:
    """
    Reads one email ({"text", "received_date"}) with the AI model and stores
    any benefit found. `message_key` marks the email as processed; `extra` is
    merged into the stored benefit (e.g. a link back to the email). `today`
    is the date where the user is.

    Returns False when the scan must stop (an error every email would hit,
    like a missing API key); the job then already holds the message, and the
    email isn't counted as failed. Other failures are counted (see MAX_TRIES).
    A marketing email is marked as read without the AI model; one over the
    daily cap is left for a later scan. A benefit that has already expired,
    or whose voucher code is already tracked, is skipped.
    """
    if looks_promotional(email["text"]):
        with db.connect() as conn:
            conn.execute("INSERT INTO processed_emails (user_id, message_id, done, filtered) VALUES (?, ?, 1, 1) "
                         "ON CONFLICT (user_id, message_id) DO UPDATE SET done = 1, filtered = 1",
                         (user_id, message_key))
        bump(job, "filtered", "checked")
        return True
    if not _claim_ai_email(user_id, today):  # another scan used up the rest of today's cap
        update(job, daily_limit_reached=True)
        bump(job, "remaining")
        return True

    try:
        result = extract_benefit_from_email(email["text"], email["received_date"], today)
    except Exception as e:
        described = describe_ai_error(e)
        if described is None:
            _release_ai_email(user_id, today)
            raise
        text, fatal = described
        if fatal:
            _release_ai_email(user_id, today)
            update(job, state="error", message=text)
            return False
        _record_failure(user_id, message_key)
        bump(job, "failed", "checked")
        return True

    with db.connect() as conn:
        conn.execute("INSERT INTO processed_emails (user_id, message_id, done) VALUES (?, ?, 1) "
                     "ON CONFLICT (user_id, message_id) DO UPDATE SET done = 1",
                     (user_id, message_key))
        keep = result.is_benefit and not _expired(result, today) and not _have_code(conn, user_id, result)
        if keep:
            db.add_benefit(conn, user_id, source, source_ref, {**asdict(result), **extra})

    if not keep:
        bump(job, "skipped", "checked")
    elif result.needs_review:
        bump(job, "needs_review", "checked")
    else:
        bump(job, "added", "checked")
    return True


# (message_key, email, source, source_ref, extra): extract_and_store's arguments.
EmailTask = tuple[str, dict, str, str, dict]


def extract_all(user_id: str, job: dict, tasks: Iterable[EmailTask], today: date) -> bool:
    """
    Runs extract_and_store for each task, AI_WORKERS at a time. `tasks` is
    consumed in this thread, so a provider can fetch each email lazily (an
    IMAP connection can't be shared between threads). Returns False if the
    scan had to stop.
    """
    stop = threading.Event()

    def work(task: EmailTask) -> None:
        if not stop.is_set() and not extract_and_store(user_id, job, *task, today):
            stop.set()

    with ThreadPoolExecutor(AI_WORKERS) as pool:
        pending: set = set()
        for task in tasks:
            if stop.is_set():
                break
            pending.add(pool.submit(work, task))
            if len(pending) >= AI_WORKERS * 2:  # don't fetch far ahead of the AI model
                finished, pending = wait(pending, return_when=FIRST_COMPLETED)
                for f in finished:
                    f.result()  # re-raises unexpected errors
        for f in pending:
            f.result()
    return not stop.is_set()
