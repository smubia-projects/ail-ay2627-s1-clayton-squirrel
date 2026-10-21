"""
imap_sync.py

Connects email accounts (Gmail, Yahoo, iCloud, AOL, Fastmail, ...) over IMAP
with an app password, and scans them for benefit emails the same way
gmail_sync.py scans Gmail (search, then AI extraction via scan_jobs).

- Only IMAP over TLS on port 993 is used.
- The inbox is opened read-only and messages are fetched with BODY.PEEK, so
  scanning never marks email as read or changes anything.
- Outlook/Hotmail don't allow password sign-in any more; they use Connect
  Outlook (outlook_sync.py) instead.
- Gmail over IMAP needs no Google verification (unlike "Connect Gmail", whose
  read-only Gmail scope is restricted), so anyone can connect it. Its scan
  matches the Gmail API's: it opens All Mail (so archived email is included),
  searches with Gmail's own query (gmail_sync.SEARCH_QUERY, via X-GM-RAW) and
  links each benefit back to its thread (X-GM-THRID).
"""

import email
import imaplib
import ipaddress
import logging
import re
import socket
import ssl
from datetime import date, timedelta
from email import policy
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import quote

import config
import db
import gmail_sync
import loyalty
import reminders
import scan_jobs
from mailtext import html_to_text

log = logging.getLogger(__name__)

PORT = 993
TIMEOUT_S = 30

# Domain -> IMAP server, so most people only type their address and app password.
_SERVERS = {
    "icloud.com": "imap.mail.me.com", "me.com": "imap.mail.me.com", "mac.com": "imap.mail.me.com",
    "aol.com": "imap.aol.com", "aim.com": "imap.aol.com",
    "ymail.com": "imap.mail.yahoo.com", "rocketmail.com": "imap.mail.yahoo.com",
    "fastmail.com": "imap.fastmail.com", "fastmail.fm": "imap.fastmail.com",
    "zoho.com": "imap.zoho.com", "zohomail.com": "imap.zoho.com",
    "gmx.com": "imap.gmx.com", "gmx.net": "imap.gmx.net", "gmx.de": "imap.gmx.net",
    "mail.com": "imap.mail.com",
    "yandex.com": "imap.yandex.com", "yandex.ru": "imap.yandex.com",
}
_OUTLOOK = {"outlook.com", "hotmail.com", "live.com", "msn.com", "passport.com"}
_GMAIL = {"gmail.com", "googlemail.com"}
GMAIL_HOST = "imap.gmail.com"
GMAIL_APP_PASSWORDS_URL = "https://myaccount.google.com/apppasswords"
_HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_EMAIL = re.compile(r"^[^@\s]+@([^@\s]+\.[^@\s]+)$")
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class ImapError(Exception):
    """A problem to show the user as is."""


class ImapAuthError(ImapError):
    """The server rejected the address or app password."""


def _domain(address: str) -> str:
    m = _EMAIL.match(address)
    if not m:
        raise ImapError("Enter a valid email address.")
    return m.group(1).lower()


def server_for(address: str) -> Optional[str]:
    """The known IMAP server for an address, or None if the user must enter it."""
    domain = _domain(address)
    if domain in _OUTLOOK or domain.startswith(("outlook.", "hotmail.", "live.")):
        raise ImapError("Outlook and Hotmail don't allow app passwords. Use Connect Outlook instead.")
    if domain in _GMAIL:
        return GMAIL_HOST
    if domain.startswith("yahoo."):
        return "imap.mail.yahoo.com"
    return _SERVERS.get(domain)


def _check_host(host: str) -> str:
    """
    Only public servers: a typed-in host must not point the app at the user's
    own machine or local network.
    """
    host = host.strip().lower().rstrip(".")
    if not _HOSTNAME.match(host):
        raise ImapError("Enter the IMAP server's name, like imap.example.com.")
    try:
        infos = socket.getaddrinfo(host, PORT, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise ImapError(f"Couldn't find the server {host}. Check the name.") from None
    if not all(ipaddress.ip_address(info[4][0]).is_global for info in infos):
        raise ImapError(f"{host} isn't a public email server.")
    return host


def _open(host: str, address: str, password: str) -> imaplib.IMAP4_SSL:
    try:
        conn = imaplib.IMAP4_SSL(host, PORT, ssl_context=ssl.create_default_context(), timeout=TIMEOUT_S)
    except ssl.SSLError:
        raise ImapError(f"{host} didn't offer a secure connection.") from None
    except OSError:
        raise ImapError(f"Couldn't connect to {host}. Check the server name and your internet connection.") from None
    try:
        conn.login(address, password)
    except imaplib.IMAP4.error:
        _close(conn)
        if host == GMAIL_HOST:
            raise ImapAuthError(
                "Google didn't accept that. Use an app password, not your Google password: turn on 2-Step "
                f"Verification, then create one at {GMAIL_APP_PASSWORDS_URL}."
            ) from None
        raise ImapAuthError(
            "Sign-in failed. Check the address, and use an app password: your normal password usually won't work."
        ) from None
    return conn


def _close(conn: imaplib.IMAP4_SSL) -> None:
    try:
        conn.logout()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def list_accounts(user_id: str) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, email, host, connected_at, last_sync_at FROM imap_accounts "
            "WHERE user_id = ? ORDER BY connected_at", (user_id,))
        accounts = [dict(r) for r in rows]
    for a in accounts:
        a["scan"] = scan_jobs.status(_job_key(a["id"]))
    return accounts


def add_account(user_id: str, address: str, password: str, host: str = "") -> dict:
    """Checks the sign-in works before saving anything. Raises ImapError."""
    address = address.strip()
    # App passwords are often shown in groups ("abcd efgh ..."); the spaces aren't part of them.
    password = re.sub(r"\s+", "", password)
    if not password:
        raise ImapError("Enter the app password.")
    if len(password) > 256:
        raise ImapError("That password is too long.")
    known = server_for(address)
    if not host.strip() and not known:
        raise ImapError(f"Squirrel doesn't know the server for {_domain(address)}. Enter it under IMAP server.")
    host = _check_host(host or known)

    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM imap_accounts WHERE user_id = ? AND email = ?",
                        (user_id, address)).fetchone():
            raise ImapError("That address is already connected.")

    conn = _open(host, address, password)
    try:
        _open_mailbox(conn, host)
    finally:
        _close(conn)

    account = {"id": db.new_id(), "email": address, "host": host, "connected_at": db.now_iso(), "last_sync_at": None}
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO imap_accounts (id, user_id, email, host, password_enc, connected_at) VALUES (?, ?, ?, ?, ?, ?)",
            (account["id"], user_id, address, host, db.encrypt(password), account["connected_at"]),
        )
    return {**account, "scan": {"state": "idle"}}


def remove_account(user_id: str, account_id: str) -> bool:
    """Deletes the stored app password. Benefits already found are kept."""
    with db.connect() as conn:
        removed = conn.execute("DELETE FROM imap_accounts WHERE id = ? AND user_id = ?",
                               (account_id, user_id)).rowcount == 1
        if removed:
            conn.execute("DELETE FROM processed_emails WHERE user_id = ? AND message_id LIKE ?",
                         (user_id, f"imap:{account_id}:%"))
    if removed:
        scan_jobs.forget(_job_key(account_id))
    return removed


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def status(account_id: str) -> dict:
    return scan_jobs.status(_job_key(account_id))


def _job_key(account_id: str) -> str:
    return f"imap:{account_id}"


def _imap_date(d: date) -> str:
    """IMAP's DD-Mon-YYYY, with English month names whatever the locale."""
    return f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year}"


def search_criteria(today: Optional[date] = None) -> str:
    """IMAP SEARCH for recent emails mentioning any benefit keyword (OR is binary in IMAP)."""
    since = (today or date.today()) - timedelta(days=scan_jobs.SEARCH_DAYS)
    terms = [f'TEXT "{w}"' for w in scan_jobs.KEYWORDS]
    expr = terms[-1]
    for term in reversed(terms[:-1]):
        expr = f"OR {term} {expr}"
    # Squirrel's own reminders list benefits too; they aren't new ones.
    not_ours = f' NOT FROM "{config.MAIL_FROM_ADDRESS}"' if config.MAIL_FROM_ADDRESS else ""
    return f"SINCE {_imap_date(since)}{not_ours} {expr}"


def _all_mail_folder(imap: imaplib.IMAP4_SSL) -> Optional[str]:
    """Gmail's All Mail folder (its name depends on the account's language), found by its \\All flag."""
    typ, data = imap.list()
    if typ != "OK":
        return None
    for line in data or []:
        if isinstance(line, bytes) and b"\\All" in line:
            m = re.search(rb'"([^"]*)"\s*$', line) or re.search(rb"(\S+)\s*$", line)
            if m:
                return m.group(1).decode()
    return None


def _open_mailbox(imap: imaplib.IMAP4_SSL, host: str) -> None:
    """
    EXAMINEs (read-only: nothing can change) the mailbox to scan: All Mail for
    Gmail, so archived email counts, otherwise the inbox. Raises ImapError.
    """
    folder = _all_mail_folder(imap) if host == GMAIL_HOST else None
    typ, _ = imap.select(f'"{folder}"' if folder else "INBOX", readonly=True)
    if typ != "OK":
        raise ImapError("Signed in, but couldn't open the inbox.")


def _search(imap: imaplib.IMAP4_SSL, host: str, today: date) -> list[str]:
    """UIDs of likely benefit emails. Gmail takes the same query as the Gmail API scan."""
    if host == GMAIL_HOST:
        imap.literal = gmail_sync.SEARCH_QUERY.encode()  # sent as a literal: the query has quotes in it
        typ, data = imap.uid("SEARCH", "X-GM-RAW")
    else:
        typ, data = imap.uid("SEARCH", search_criteria(today))
    if typ != "OK":
        raise ImapError("The email server rejected the search. It may not support searching message text.")
    return [u.decode() for u in (data[0] or b"").split()]


def gmail_message_ids(imap: imaplib.IMAP4_SSL, uids: list[str]) -> dict[str, str]:
    """
    {uid: Gmail API message id} for these Gmail UIDs. X-GM-MSGID is the same
    number as the Gmail API's id, in decimal rather than hex.
    """
    if not uids:
        return {}
    typ, data = imap.uid("FETCH", ",".join(uids), "(X-GM-MSGID)")
    if typ != "OK":
        return {}
    ids = {}
    for line in data or []:
        text = line.decode(errors="replace") if isinstance(line, bytes) else ""
        uid, msgid = re.search(r"UID (\d+)", text), re.search(r"X-GM-MSGID (\d+)", text)
        if uid and msgid:
            ids[uid.group(1)] = format(int(msgid.group(1)), "x")
    return ids


def _loyalty_finder(imap: imaplib.IMAP4_SSL) -> loyalty.Finder:
    since = _imap_date(loyalty.since())

    def find(program: dict, activity: bool) -> Optional[dict]:
        typ, data = imap.uid("SEARCH", loyalty.imap_criteria(program, activity, since))
        if typ != "OK":
            return None
        uids = sorted((data[0] or b"").split(), key=int, reverse=True)[:10]
        if not uids:
            return None
        typ, data = imap.uid("FETCH", b",".join(uids).decode(), "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        headers = [parse_headers(part[1]) for part in data or [] if isinstance(part, tuple)]
        # IMAP's FROM search matches any part of the address, so confirm the domain.
        matches = [h for h in headers if loyalty.sender_matches(program, h["from"])]
        return max(matches, key=lambda h: h["received_date"] or "", default=None)

    return find


def parse_headers(raw: bytes) -> dict:
    """{"from", "subject", "received_date"} from a message's headers."""
    msg = email.message_from_bytes(raw, policy=policy.default)

    def header(name: str) -> str:
        try:
            return str(msg[name] or "")
        except Exception:  # malformed header
            return ""

    received = None
    try:
        received = parsedate_to_datetime(header("date")).date().isoformat()
    except (TypeError, ValueError):
        pass
    return {"from": header("from"), "subject": header("subject"), "received_date": received}


def parse_message(raw: bytes) -> dict:
    """Same shape as google_api.get_message: {"text", "received_date", "subject"}."""
    msg = email.message_from_bytes(raw, policy=policy.default)

    def header(name: str) -> str:
        try:
            return str(msg[name] or "")
        except Exception:  # malformed header
            return ""

    body = ""
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is not None:
        try:
            content = part.get_content()
        except (LookupError, UnicodeError, AssertionError):
            content = (part.get_payload(decode=True) or b"").decode("utf-8", errors="replace")
        body = html_to_text(content) if part.get_content_subtype() == "html" else content.strip()

    received = None
    try:
        received = parsedate_to_datetime(header("date")).date().isoformat()
    except (TypeError, ValueError):
        pass

    header_lines = [f"{label}: {header(label)}" for label in ("From", "Subject", "Date") if header(label)]
    return {
        "text": "\n".join(header_lines) + "\n\n" + body,
        "received_date": received,
        "subject": header("subject"),
    }


def start_scan(user_id: str, account_id: str) -> dict:
    with db.connect() as conn:
        if not conn.execute("SELECT 1 FROM imap_accounts WHERE id = ? AND user_id = ?",
                            (account_id, user_id)).fetchone():
            raise ImapError("That email account is no longer connected.")
    return scan_jobs.start(_job_key(account_id), lambda job: _run(user_id, account_id, job))


def _run(user_id: str, account_id: str, job: dict) -> None:
    try:
        _scan(user_id, account_id, job)
    except ImapAuthError:
        scan_jobs.update(job, state="error", message=(
            "Sign-in failed: the app password may have been deleted or changed. "
            "Remove this account and add it again with a new app password."))
    except ImapError as e:
        scan_jobs.update(job, state="error", message=str(e))
    except (imaplib.IMAP4.error, OSError) as e:
        log.warning("IMAP scan failed: %r", e)
        scan_jobs.update(job, state="error", message="Lost the connection to the email server. Scan again to continue.")
    except Exception:
        log.exception("IMAP scan failed unexpectedly")
        scan_jobs.update(job, state="error", message="The scan failed unexpectedly. See the terminal running server.py.")


def _scan(user_id: str, account_id: str, job: dict) -> None:
    with db.connect() as conn:
        row = conn.execute("SELECT email, host, password_enc FROM imap_accounts WHERE id = ? AND user_id = ?",
                           (account_id, user_id)).fetchone()
        done = scan_jobs.finished_emails(conn, user_id, f"imap:{account_id}:")
        # Emails already read by a Gmail API scan (keyed by Gmail's message id, no prefix).
        read_by_gmail_api = {m for m in scan_jobs.finished_emails(conn, user_id) if ":" not in m}
        today = reminders.user_today(conn, user_id)
    if row is None:
        raise ImapError("That email account is no longer connected.")

    gmail = row["host"] == GMAIL_HOST
    imap = _open(row["host"], row["email"], db.decrypt(row["password_enc"]))
    try:
        _open_mailbox(imap, row["host"])
        uidvalidity = (imap.response("UIDVALIDITY")[1] or [b"0"])[0].decode()
        scan_jobs.update(job, memberships=loyalty.detect(user_id, _loyalty_finder(imap), today))
        uids = _search(imap, row["host"], today)
        uids = sorted(uids, key=int, reverse=True)[:scan_jobs.SEARCH_LIMIT + 1]  # newest first

        def key(uid: str) -> str:
            return f"imap:{account_id}:{uidvalidity}:{uid}"

        # The same Gmail inbox may have been scanned through the Gmail API: skip what that read.
        api_ids = gmail_message_ids(imap, uids) if gmail and read_by_gmail_api else {}
        batch = scan_jobs.take_batch(
            user_id, job, uids, lambda u: key(u) not in done and api_ids.get(u) not in read_by_gmail_api, today)

        def tasks():
            for uid in batch:
                # BODY.PEEK leaves the email unread. Gmail also gives the thread id, for the link.
                typ, data = imap.uid("FETCH", uid, "(X-GM-THRID BODY.PEEK[])" if gmail else "(BODY.PEEK[])")
                part = next((p for p in data or [] if isinstance(p, tuple)), None)
                if typ != "OK" or part is None:
                    scan_jobs.bump(job, "failed", "checked")
                    continue
                message = parse_message(part[1])
                extra = {"source_label": message["subject"][:200] or None, "source_account": row["email"]}
                thread = re.search(rb"X-GM-THRID (\d+)", part[0]) if gmail else None
                if thread:
                    # The Gmail API's thread id is the same number in hex.
                    extra["source_link"] = (f"https://mail.google.com/mail/?authuser={quote(row['email'])}"
                                            f"#all/{int(thread.group(1)):x}")
                yield key(uid), message, "imap", key(uid), extra

        if not scan_jobs.extract_all(user_id, job, tasks(), today):
            return
    finally:
        _close(imap)

    with db.connect() as conn:
        conn.execute("UPDATE imap_accounts SET last_sync_at = ? WHERE id = ?", (db.now_iso(), account_id))
    scan_jobs.update(job, state="done")
