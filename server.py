"""
server.py

Local web server for the Squirrel dashboard. Standard library only (plus
the cryptography package). AI features call the OpenAI API.

The dashboard is the React app in frontend/. Build it once, then run:

    cd frontend && npm install && npm run build && cd ..
    python3 server.py            # then open http://127.0.0.1:8000

While working on the frontend, run `npm run dev` in frontend/ instead; it
proxies /api requests to this server.

Users sign in with an email + password or with Google. Benefits come from two
places: a scan of the user's email (Gmail, or other providers over IMAP; read-only,
via AI extraction) and the
perks of credit cards they add. Data is stored in instance/benefitapp.db.
"""

import config  # noqa: F401  (loads .env before anything reads the environment)

import base64
import hashlib
import json
import mimetypes
import re
import secrets
import logging
import threading
from dataclasses import asdict, fields
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from typing import Optional
from urllib.parse import parse_qs, quote, urlsplit

import account
import auto_scan
import auth
import cards
import db
import gmail_sync
import google_api
import imap_sync
import limits
import mailer
import microsoft_api
import outlook_sync
import reminders
import scan_jobs
from app import CATEGORIES, MODEL, TYPES, ExtractedBenefit, ExtractionError, describe_ai_error
from BenefitIntelligence import ask_about_benefits, build_weekly_digest

log = logging.getLogger(__name__)

DIST_DIR = (config.ROOT / "frontend" / "dist").resolve()
MAX_BODY_BYTES = 64 * 1024
OAUTH_STATE_COOKIE = "benefitapp_oauth_state"
OAUTH_STATE_MAX_AGE = timedelta(minutes=10)

_BENEFIT_FIELDS = {f.name for f in fields(ExtractedBenefit)}
# Client-side routes of the React app; each serves index.html.
FRONTEND_ROUTES = {"/benefits", "/assistant", "/connections", "/reset-password", "/verify-email", "/privacy", "/terms"}


# Sent with every response. Framing is blocked so another site can't trick
# people into clicking Delete account or Disconnect inside an invisible frame.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",  # never send page URLs (which can hold OAuth codes) to other sites
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=(), payment=(), usb=()",
}
if config.SECURE_COOKIES:  # only once Squirrel is served over https
    SECURITY_HEADERS["Strict-Transport-Security"] = "max-age=31536000"

_INLINE_SCRIPT = re.compile(rb"<script>(.*?)</script>", re.S)


def content_security_policy(html: bytes) -> str:
    """
    The CSP for the page: everything from Squirrel itself, plus Google Fonts.
    Inline scripts are allowed by their hash, read from the built page, so the
    theme script in index.html keeps working if it changes. 'unsafe-inline'
    styles are for React's style attributes; 'wasm-unsafe-eval' is for the
    code scanner's WebAssembly.
    """
    hashes = " ".join(f"'sha256-{base64.b64encode(hashlib.sha256(m).digest()).decode()}'"
                      for m in _INLINE_SCRIPT.findall(html))
    return "; ".join([
        "default-src 'self'",
        f"script-src 'self' 'wasm-unsafe-eval' {hashes}".strip(),
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data: blob:",
        "connect-src 'self'",
        "media-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])


def to_benefit(record: dict) -> ExtractedBenefit:
    return ExtractedBenefit(**{k: v for k, v in record.items() if k in _BENEFIT_FIELDS})


def credit_total(record: dict) -> Optional[float]:
    """A card credit's dollar amount for this period ("$15 ($35 in December)" gives 15), else None."""
    if record.get("source") != "card":
        return None
    value = record.get("value") or ""
    # "$15 ($35 in December)": the December period gets the larger amount.
    december = re.search(r"\$(\d+(?:\.\d+)?) in December", value)
    if december and (record.get("expiry_date") or "")[5:7] == "12":
        return float(december.group(1))
    m = re.search(r"\$(\d+(?:\.\d+)?)", value)
    return float(m.group(1)) if m else None


def with_days(record: dict, today: date) -> dict:
    """The record plus what the page shows about it; `today` is the date where the user is."""
    days = None
    if record.get("expiry_date"):
        try:
            days = (date.fromisoformat(record["expiry_date"]) - today).days
        except ValueError:
            pass
    return {**record, "days_until_expiry": days, "credit_total": credit_total(record)}


def parse_points(value) -> Optional[int]:
    """A points balance as typed ("12,500"), or None when empty. Raises ValueError with a message."""
    if value in (None, ""):
        return None
    try:
        points = int(str(value).replace(",", "").strip())
    except ValueError:
        raise ValueError("Enter points as a whole number, like 12500.") from None
    if not 0 <= points <= 10_000_000_000:
        raise ValueError("Enter a points balance between 0 and 10 billion.")
    return points


def user_today(user_id: str) -> date:
    with db.connect() as conn:
        return reminders.user_today(conn, user_id)


def user_benefits(user_id: str, today: date) -> list[dict]:
    with db.connect() as conn:
        cards.sync_card_benefits(conn, user_id, today)
        return db.list_benefits(conn, user_id)


LIMIT_NAMES = {"ask": "questions", "digest": "digests", "scan": "scans"}


def digest_key(benefits: list[ExtractedBenefit], today: date) -> str:
    """What a digest depends on: the benefits, the date (days left change daily) and the model."""
    raw = json.dumps([asdict(b) for b in benefits], sort_keys=True) + today.isoformat() + MODEL
    return hashlib.sha256(raw.encode()).hexdigest()


def _send_reset_email(address: str, link: str) -> None:
    try:
        mailer.send(address, "Reset your Squirrel password", (
            "Someone asked to reset the password for your Squirrel account.\n\n"
            f"Choose a new password here (the link works once, for {auth.RESET_LINK_MINUTES} minutes):\n{link}\n\n"
            "If it wasn't you, ignore this email: your password hasn't changed."))
    except Exception as e:  # noqa: BLE001 - a failed send must not crash the server
        log.warning("Couldn't send the password reset email: %s: %s", type(e).__name__, e)


def _send_verification_email(address: str, link: str) -> None:
    try:
        mailer.send(address, "Confirm your email for Squirrel", (
            "Welcome to Squirrel! Confirm this is your address so Squirrel can send you expiry reminders:\n"
            f"{link}\n\n"
            f"The link works once, for {auth.VERIFY_LINK_HOURS} hours.\n\n"
            "If you didn't sign up for Squirrel, ignore this email: nothing will be sent to you."))
    except Exception as e:  # noqa: BLE001 - a failed send must not crash the server
        log.warning("Couldn't send the confirmation email: %s: %s", type(e).__name__, e)


def send_verification(user_id: str) -> None:
    """Emails a confirmation link in the background (raises auth.AuthError when too many were sent)."""
    link = auth.create_verification_link(user_id)
    if link:
        threading.Thread(target=_send_verification_email, args=link, daemon=True).start()


def _cookie(name: str, value: str, *, max_age: int, path: str = "/") -> str:
    parts = [f"{name}={value}", f"Path={path}", f"Max-Age={max_age}", "HttpOnly", "SameSite=Lax"]
    if config.SECURE_COOKIES:
        parts.append("Secure")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "Squirrel/2.0"
    # Seconds a connection may sit without sending anything, so slow or stalled
    # clients can't hold server threads open forever.
    timeout = 30

    def end_headers(self) -> None:
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

    # --- helpers --------------------------------------------------------------

    def _send_json(self, status: int, payload, cookies: tuple[str, ...] = ()) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for c in cookies:
            self.send_header("Set-Cookie", c)
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._send_json(status, {"error": message})

    def _redirect(self, location: str, cookies: tuple[str, ...] = ()) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        for c in cookies:
            self.send_header("Set-Cookie", c)
        self.end_headers()

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise ValueError("request body too large")
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw or b"{}")
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        return data

    def _cookies(self) -> SimpleCookie:
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie") or "")
        except Exception:
            pass
        return jar

    def _cookie_value(self, name: str) -> Optional[str]:
        morsel = self._cookies().get(name)
        return morsel.value if morsel else None

    def _session_token(self) -> Optional[str]:
        return self._cookie_value(auth.SESSION_COOKIE)

    def _current_user(self) -> Optional[dict]:
        return auth.user_for_session(self._session_token())

    def _require_user(self) -> Optional[dict]:
        user = self._current_user()
        if user is None:
            self._error(HTTPStatus.UNAUTHORIZED, "Your session has ended. Sign in again.")
        return user

    def _session_cookie(self, user_id: str) -> str:
        token = auth.create_session(user_id)
        return _cookie(auth.SESSION_COOKIE, token, max_age=auth.SESSION_DAYS * 86400)

    def _over_limit(self, user: dict, kind: str) -> bool:
        """Uses up one of the user's hourly AI requests of this kind, or sends a 429 and returns True."""
        wait_minutes = limits.take(user["id"], kind)
        if wait_minutes is None:
            return False
        self._error(HTTPStatus.TOO_MANY_REQUESTS,
                    f"That's the most {LIMIT_NAMES[kind]} for one hour ({limits.LIMITS[kind]}). "
                    f"Try again in {wait_minutes} minute{'s' if wait_minutes != 1 else ''}.")
        return True

    def _call_ai(self, fn, *args):
        """Runs an AI call and maps its failures to HTTP errors. Returns (ok, result)."""
        try:
            return True, fn(*args)
        except Exception as e:
            described = describe_ai_error(e)
            if described is None:
                raise
            message, _ = described
            status = HTTPStatus.UNPROCESSABLE_ENTITY if isinstance(e, ExtractionError) else HTTPStatus.BAD_GATEWAY
            self._error(status, message)
        return False, None

    def _path_and_query(self) -> tuple[str, dict]:
        parts = urlsplit(self.path)
        return parts.path, {k: v[0] for k, v in parse_qs(parts.query).items()}

    # --- dispatch -------------------------------------------------------------

    def handle_one_request(self) -> None:
        # Any unexpected failure still returns a JSON error instead of an
        # empty response the page can't explain.
        try:
            super().handle_one_request()
        except Exception:
            log.exception("Unexpected error handling %s %s", self.command, self.path.split("?", 1)[0])
            try:
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR,
                            "Unexpected server error. See the terminal running server.py for details.")
            except Exception:
                pass

    def do_GET(self) -> None:
        path, query = self._path_and_query()
        if not path.startswith("/api/"):
            self._serve_frontend(path)
        elif path == "/api/session":
            self._session_info()
        elif path == "/api/auth/google/start":
            self._google_start(query)
        elif path == "/api/auth/google/callback":
            self._google_callback(query)
        elif path == "/api/auth/microsoft/start":
            self._microsoft_start()
        elif path == "/api/auth/microsoft/callback":
            self._microsoft_callback(query)
        elif path == "/api/benefits":
            if user := self._require_user():
                today = user_today(user["id"])
                self._send_json(HTTPStatus.OK, [with_days(r, today) for r in user_benefits(user["id"], today)])
        elif path == "/api/benefits/removed":
            if user := self._require_user():
                with db.connect() as conn:
                    self._send_json(HTTPStatus.OK, db.list_removed_benefits(conn, user["id"]))
        elif path == "/api/digest":
            if user := self._require_user():
                self._digest(user)
        elif path == "/api/ask/history":
            if user := self._require_user():
                with db.connect() as conn:
                    self._send_json(HTTPStatus.OK, db.list_ask_history(conn, user["id"]))
        elif path == "/api/gmail/status":
            if user := self._require_user():
                self._send_json(HTTPStatus.OK, {
                    "connection": gmail_sync.connection(user["id"]),
                    "scan": gmail_sync.status(user["id"]),
                })
        elif path == "/api/outlook/status":
            if user := self._require_user():
                self._send_json(HTTPStatus.OK, {
                    "connection": outlook_sync.connection(user["id"]),
                    "scan": outlook_sync.status(user["id"]),
                })
        elif path == "/api/imap":
            if user := self._require_user():
                self._send_json(HTTPStatus.OK, imap_sync.list_accounts(user["id"]))
        elif path == "/api/auto-scan":
            if user := self._require_user():
                self._send_json(HTTPStatus.OK, auto_scan.status(user["id"]))
        elif path == "/api/scan-failures":
            if user := self._require_user():
                with db.connect() as conn:
                    self._send_json(HTTPStatus.OK, {"count": scan_jobs.given_up(conn, user["id"])})
        elif path == "/api/cards":
            if user := self._require_user():
                with db.connect() as conn:
                    self._send_json(HTTPStatus.OK, {
                        "cards": cards.list_user_cards(conn, user["id"]),
                        "catalog": cards.public_catalog(),
                    })
        else:
            self._error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:
        path, _ = self._path_and_query()

        # Cross-site request forgery guard. SameSite=Lax cookies already stop
        # most of it; also require JSON (which plain HTML forms can't send)
        # and, when the browser says where the request came from, our origin.
        origin = self.headers.get("Origin")
        if origin and origin not in config.ALLOWED_ORIGINS:
            self._error(HTTPStatus.FORBIDDEN, "Request from an unexpected site was blocked.")
            return
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Send JSON.")
            return
        try:
            data = self._read_json()
        except (ValueError, json.JSONDecodeError) as e:
            self._error(HTTPStatus.BAD_REQUEST, f"invalid request: {e}")
            return

        if path == "/api/auth/register":
            self._register(data)
        elif path == "/api/auth/login":
            self._login(data)
        elif path == "/api/auth/forgot":
            self._forgot_password(data)
        elif path == "/api/auth/reset":
            self._reset_password(data)
        elif path == "/api/auth/verify-email":
            # Public: the link may be opened on a device that isn't signed in.
            try:
                self._send_json(HTTPStatus.OK, {"user": auth.verify_email(str(data.get("token") or ""))})
            except auth.AuthError as e:
                self._error(HTTPStatus.BAD_REQUEST, str(e))
        elif path == "/api/auth/logout":
            auth.end_session(self._session_token())
            self._send_json(HTTPStatus.OK, {"ok": True}, (_cookie(auth.SESSION_COOKIE, "", max_age=0),))
        elif not (user := self._require_user()):
            return
        elif path == "/api/account/delete":
            self._delete_account(user, data)
        elif path == "/api/account/verification":
            try:
                send_verification(user["id"])
            except auth.AuthError as e:
                self._error(HTTPStatus.TOO_MANY_REQUESTS, str(e))
                return
            self._send_json(HTTPStatus.OK, {"ok": True, "email_enabled": config.EMAIL_ENABLED})
        elif path == "/api/account/email":
            try:
                changed = auth.change_unverified_email(user["id"], str(data.get("email") or ""))
                send_verification(user["id"])
            except auth.AuthError as e:
                self._error(HTTPStatus.BAD_REQUEST, str(e))
                return
            self._send_json(HTTPStatus.OK, {"user": changed})
        elif path == "/api/ask":
            self._ask(user, data)
        elif path == "/api/benefits":
            self._create_benefit(user, data)
        elif path == "/api/ask/history/clear":
            with db.connect() as conn:
                db.clear_ask_history(conn, user["id"])
            self._send_json(HTTPStatus.OK, {"ok": True})
        elif path == "/api/gmail/scan":
            if self._over_limit(user, "scan"):
                return
            try:
                self._send_json(HTTPStatus.OK, gmail_sync.start_scan(user["id"]))
            except google_api.GoogleError as e:
                self._error(HTTPStatus.BAD_REQUEST, str(e))
        elif path == "/api/gmail/disconnect":
            gmail_sync.disconnect(user["id"])
            self._send_json(HTTPStatus.OK, {"ok": True})
        elif path == "/api/outlook/scan":
            if self._over_limit(user, "scan"):
                return
            try:
                self._send_json(HTTPStatus.OK, outlook_sync.start_scan(user["id"]))
            except microsoft_api.MicrosoftError as e:
                self._error(HTTPStatus.BAD_REQUEST, str(e))
        elif path == "/api/outlook/disconnect":
            outlook_sync.disconnect(user["id"])
            self._send_json(HTTPStatus.OK, {"ok": True, "remove_access_url": microsoft_api.PERSONAL_APPS_URL})
        elif path == "/api/imap":
            self._imap_action(lambda: imap_sync.add_account(
                user["id"], str(data.get("email") or ""), str(data.get("password") or ""), str(data.get("host") or "")))
        elif m := re.fullmatch(r"/api/imap/([0-9a-f]{12})/scan", path):
            if self._over_limit(user, "scan"):
                return
            self._imap_action(lambda: imap_sync.start_scan(user["id"], m.group(1)))
        elif m := re.fullmatch(r"/api/imap/([0-9a-f]{12})/remove", path):
            if imap_sync.remove_account(user["id"], m.group(1)):
                self._send_json(HTTPStatus.OK, {"ok": True})
            else:
                self._error(HTTPStatus.NOT_FOUND, "That email account is no longer connected.")
        elif path == "/api/auto-scan":
            if not isinstance(data.get("enabled"), bool):
                self._error(HTTPStatus.BAD_REQUEST, "enabled must be true or false.")
                return
            auto_scan.set_enabled(user["id"], data["enabled"])
            if data["enabled"]:
                auto_scan.maybe_start(user["id"])
            self._send_json(HTTPStatus.OK, auto_scan.status(user["id"]))
        elif path == "/api/scan-failures/retry":
            with db.connect() as conn:
                self._send_json(HTTPStatus.OK, {"count": scan_jobs.retry_given_up(conn, user["id"])})
        elif path == "/api/timezone":
            try:
                with db.connect() as conn:
                    reminders.save_timezone(conn, user["id"], data.get("timezone"))
            except ValueError as e:
                self._error(HTTPStatus.BAD_REQUEST, str(e))
                return
            self._send_json(HTTPStatus.OK, {"ok": True})
        elif path == "/api/cards":
            self._add_card(user, data)
        elif m := re.fullmatch(r"/api/cards/([0-9a-f]{12})/remove", path):
            if cards.remove_user_card(user["id"], m.group(1)):
                self._send_json(HTTPStatus.OK, {"ok": True})
            else:
                self._error(HTTPStatus.NOT_FOUND, "That card is no longer in your list.")
        elif m := re.fullmatch(r"/api/benefits/([0-9a-f]{12})/(approve|dismiss)", path):
            self._review(user, m.group(1), m.group(2), data)
        elif m := re.fullmatch(r"/api/benefits/([0-9a-f]{12})/restore", path):
            with db.connect() as conn:
                record = db.restore_benefit(conn, user["id"], m.group(1))
                today = reminders.user_today(conn, user["id"])
            if record is None:
                self._error(HTTPStatus.NOT_FOUND, "That benefit was deleted for good and can't be restored.")
            else:
                self._send_json(HTTPStatus.OK, with_days(record, today))
        elif m := re.fullmatch(r"/api/benefits/([0-9a-f]{12})/update", path):
            self._update_benefit(user, m.group(1), data)
        elif m := re.fullmatch(r"/api/benefits/([0-9a-f]{12})/quick", path):
            self._quick_update(user, m.group(1), data)
        else:
            self._error(HTTPStatus.NOT_FOUND, "not found")

    # --- accounts ---------------------------------------------------------------

    def _session_info(self) -> None:
        user = self._current_user()
        if user:
            auto_scan.maybe_start(user["id"])  # the app was opened while signed in
            with db.connect() as conn:
                reminders_failing_since = reminders.failing_since(conn, user["id"])
        self._send_json(HTTPStatus.OK, {
            "user": user,
            "google_enabled": config.GOOGLE_ENABLED,
            "microsoft_enabled": config.MICROSOFT_ENABLED,
            "gmail": gmail_sync.connection(user["id"]) if user else None,
            "auto_scan": auto_scan.status(user["id"]) if user else None,
            "reminders_failing_since": reminders_failing_since if user else None,
        })

    def _register(self, data: dict) -> None:
        try:
            user = auth.register(data.get("email", ""), data.get("password", ""), data.get("name", ""))
        except auth.AuthError as e:
            self._error(HTTPStatus.BAD_REQUEST, str(e))
            return
        send_verification(user["id"])
        self._send_json(HTTPStatus.OK, {"user": user}, (self._session_cookie(user["id"]),))

    def _login(self, data: dict) -> None:
        try:
            user = auth.login(data.get("email", ""), data.get("password", ""))
        except auth.AuthError as e:
            self._error(HTTPStatus.BAD_REQUEST, str(e))
            return
        self._send_json(HTTPStatus.OK, {"user": user}, (self._session_cookie(user["id"]),))

    def _forgot_password(self, data: dict) -> None:
        try:
            link = auth.create_reset_link(str(data.get("email") or ""))
        except auth.AuthError as e:
            self._error(HTTPStatus.BAD_REQUEST, str(e))
            return
        if link:
            # Sent in the background, so the response time doesn't reveal
            # whether the account exists.
            threading.Thread(target=_send_reset_email, args=link, daemon=True).start()
        self._send_json(HTTPStatus.OK, {"ok": True, "email_enabled": config.EMAIL_ENABLED})

    def _reset_password(self, data: dict) -> None:
        try:
            user = auth.reset_password(str(data.get("token") or ""), str(data.get("password") or ""))
        except auth.AuthError as e:
            self._error(HTTPStatus.BAD_REQUEST, str(e))
            return
        self._send_json(HTTPStatus.OK, {"user": user}, (self._session_cookie(user["id"]),))

    def _delete_account(self, user: dict, data: dict) -> None:
        try:
            account.delete_account(user["id"], str(data.get("password") or ""), str(data.get("email") or ""))
        except (auth.AuthError, account.AccountError) as e:
            self._error(HTTPStatus.BAD_REQUEST, str(e))
            return
        self._send_json(HTTPStatus.OK, {"ok": True}, (_cookie(auth.SESSION_COOKIE, "", max_age=0),))

    def _google_start(self, query: dict) -> None:
        """
        Browser navigation (not fetch). purpose=login signs in (name and email
        only); purpose=connect adds Gmail to the signed-in account.
        """
        if not config.GOOGLE_ENABLED:
            self._redirect("/?auth_error=" + quote("Google sign-in isn't set up on this server yet."))
            return
        purpose = query.get("purpose", "login")
        user = self._current_user() if purpose == "connect" else None
        if purpose not in ("login", "connect") or (purpose == "connect" and user is None):
            self._redirect("/?auth_error=" + quote("Sign in first, then connect Gmail."))
            return

        state = secrets.token_urlsafe(32)
        verifier = google_api.new_pkce_verifier()
        with db.connect() as conn:
            cutoff = (datetime.now(timezone.utc) - OAUTH_STATE_MAX_AGE).isoformat(timespec="seconds")
            conn.execute("DELETE FROM oauth_states WHERE created_at < ?", (cutoff,))
            conn.execute(
                "INSERT INTO oauth_states (state, purpose, user_id, code_verifier, created_at) VALUES (?, ?, ?, ?, ?)",
                (state, purpose, user["id"] if user else None, verifier, db.now_iso()),
            )
        url = google_api.authorization_url(
            state, verifier, gmail=purpose == "connect", login_hint=user["email"] if user else None
        )
        # The same state in a cookie ties the callback to this browser, so
        # nobody can finish a sign-in they started in someone else's browser.
        self._redirect(url, (_cookie(OAUTH_STATE_COOKIE, state, max_age=int(OAUTH_STATE_MAX_AGE.total_seconds()),
                                     path="/api/auth/google"),))

    def _google_callback(self, query: dict) -> None:
        clear_state = _cookie(OAUTH_STATE_COOKIE, "", max_age=0, path="/api/auth/google")

        def fail(message: str) -> None:
            self._redirect("/?auth_error=" + quote(message), (clear_state,))

        if query.get("error"):
            fail("Google sign-in was cancelled." if query["error"] == "access_denied"
                 else f"Google sign-in failed ({query['error']}).")
            return

        state = query.get("state", "")
        cookie_state = self._cookie_value(OAUTH_STATE_COOKIE)
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM oauth_states WHERE state = ?", (state,)).fetchone()
            conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        if (row is None or not cookie_state or not secrets.compare_digest(cookie_state, state)
                or datetime.fromisoformat(row["created_at"]) < datetime.now(timezone.utc) - OAUTH_STATE_MAX_AGE):
            fail("That sign-in link expired. Try again.")
            return

        try:
            tokens = google_api.exchange_code(query.get("code", ""), row["code_verifier"])
            claims = google_api.parse_id_token(tokens.get("id_token", ""))
        except google_api.GoogleError as e:
            fail(str(e))
            return

        cookies = [clear_state]
        if row["purpose"] == "login":
            try:
                user, password_removed = auth.find_or_create_google_user(
                    claims["sub"], claims["email"], bool(claims.get("email_verified")), claims.get("name"))
            except auth.AuthError as e:
                fail(str(e))
                return
            cookies.append(self._session_cookie(user["id"]))
            user_id = user["id"]
        else:
            user_id = row["user_id"]

        gmail_granted = google_api.GMAIL_SCOPE in tokens.get("scope", "").split()
        refresh_token = tokens.get("refresh_token")
        if gmail_granted and refresh_token:
            gmail_sync.save_connection(user_id, claims["email"], refresh_token)
            notice, page = "gmail_connected", "/connections"
        elif row["purpose"] == "connect":
            fail("Gmail wasn't connected. Tick the box that lets Squirrel read your email, then try again.")
            return
        else:
            notice, page = "signed_in", "/"
        if row["purpose"] == "login" and password_removed:
            notice = "password_removed"
        self._redirect(f"{page}?notice={notice}", tuple(cookies))

    def _microsoft_start(self) -> None:
        """Browser navigation (not fetch): "Connect Outlook" for the signed-in user."""
        user = self._current_user()
        if not config.MICROSOFT_ENABLED or user is None:
            self._redirect("/connections?auth_error=" + quote(
                "Outlook isn't set up on this server yet." if user else "Sign in first, then connect Outlook."))
            return
        state = secrets.token_urlsafe(32)
        verifier = microsoft_api.new_pkce_verifier()
        with db.connect() as conn:
            cutoff = (datetime.now(timezone.utc) - OAUTH_STATE_MAX_AGE).isoformat(timespec="seconds")
            conn.execute("DELETE FROM oauth_states WHERE created_at < ?", (cutoff,))
            conn.execute(
                "INSERT INTO oauth_states (state, purpose, user_id, code_verifier, created_at) VALUES (?, ?, ?, ?, ?)",
                (state, "outlook", user["id"], verifier, db.now_iso()),
            )
        # As with Google, the state in a cookie ties the callback to this browser.
        self._redirect(microsoft_api.authorization_url(state, verifier, login_hint=user["email"]),
                       (_cookie(OAUTH_STATE_COOKIE, state, max_age=int(OAUTH_STATE_MAX_AGE.total_seconds()),
                                path="/api/auth/microsoft"),))

    def _microsoft_callback(self, query: dict) -> None:
        # On this computer Microsoft sends the browser to localhost (see config); the
        # cookies belong to APP_URL's host, so continue there.
        app = urlsplit(config.APP_URL)
        if (self.headers.get("Host") or "") != app.netloc:
            self._redirect(config.APP_URL + self.path)
            return

        clear_state = _cookie(OAUTH_STATE_COOKIE, "", max_age=0, path="/api/auth/microsoft")

        def fail(message: str) -> None:
            self._redirect("/connections?auth_error=" + quote(message), (clear_state,))

        if query.get("error"):
            fail("Connecting Outlook was cancelled." if query["error"] == "access_denied"
                 else f"Microsoft sign-in failed: {query.get('error_description') or query['error']}"[:300])
            return

        state = query.get("state", "")
        cookie_state = self._cookie_value(OAUTH_STATE_COOKIE)
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM oauth_states WHERE state = ? AND purpose = 'outlook'",
                               (state,)).fetchone()
            conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        if (row is None or not cookie_state or not secrets.compare_digest(cookie_state, state)
                or datetime.fromisoformat(row["created_at"]) < datetime.now(timezone.utc) - OAUTH_STATE_MAX_AGE):
            fail("That link expired. Press Connect Outlook again.")
            return

        try:
            tokens = microsoft_api.exchange_code(query.get("code", ""), row["code_verifier"])
            granted = {s.lower() for s in tokens.get("scope", "").split()}
            if not tokens.get("refresh_token") or not any(s.endswith("mail.read") for s in granted):
                fail("Outlook wasn't connected: Squirrel needs permission to read your email. Try again.")
                return
            address = microsoft_api.mailbox_address(tokens["access_token"])
        except microsoft_api.MicrosoftError as e:
            fail(str(e))
            return
        outlook_sync.save_connection(row["user_id"], address, tokens["refresh_token"])
        self._redirect("/connections?notice=outlook_connected", (clear_state,))

    # --- benefits ---------------------------------------------------------------

    def _ask(self, user: dict, data: dict) -> None:
        question = (data.get("question") or "").strip()
        if not question:
            self._error(HTTPStatus.BAD_REQUEST, "Type a question first.")
            return
        if self._over_limit(user, "ask"):
            return
        today = user_today(user["id"])
        benefits = [to_benefit(r) for r in user_benefits(user["id"], today) if not r.get("used_on")]
        ok, answer = self._call_ai(ask_about_benefits, question, benefits, today)
        if ok:
            with db.connect() as conn:
                entry = db.add_ask_history(conn, user["id"], question, answer)
            self._send_json(HTTPStatus.OK, entry)

    def _digest(self, user: dict) -> None:
        """The weekly digest, from digest_cache unless the benefits or the date changed since it was made."""
        today = user_today(user["id"])
        benefits = [to_benefit(r) for r in user_benefits(user["id"], today) if not r.get("used_on")]
        key = digest_key(benefits, today)
        with db.connect() as conn:
            row = conn.execute("SELECT key, digest FROM digest_cache WHERE user_id = ?", (user["id"],)).fetchone()
        if row and row["key"] == key:
            self._send_json(HTTPStatus.OK, json.loads(row["digest"]))
            return
        if self._over_limit(user, "digest"):
            return
        ok, digest = self._call_ai(build_weekly_digest, benefits, today)
        if not ok:
            return
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO digest_cache (user_id, key, digest, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (user_id) DO UPDATE SET key = excluded.key, digest = excluded.digest, "
                "created_at = excluded.created_at",
                (user["id"], key, json.dumps(digest), db.now_iso()))
        self._send_json(HTTPStatus.OK, digest)

    def _review(self, user: dict, benefit_id: str, action: str, data: dict) -> None:
        with db.connect() as conn:
            record = db.get_benefit(conn, user["id"], benefit_id)
            if record is None:
                self._error(HTTPStatus.NOT_FOUND, "That benefit no longer exists.")
                return

            if action == "dismiss":
                db.dismiss_benefit(conn, user["id"], benefit_id)
                self._send_json(HTTPStatus.OK, {"ok": True})
                return
            today = reminders.user_today(conn, user["id"])

            expiry = (data.get("expiry_date") or "").strip() or None
            if expiry:
                try:
                    date.fromisoformat(expiry)
                except ValueError:
                    self._error(HTTPStatus.BAD_REQUEST, "Use a real date (YYYY-MM-DD).")
                    return
            record.update(
                expiry_date=expiry,
                expiry_confidence="explicit" if expiry else "unknown",
                expiry_reasoning="Confirmed by you." if expiry else "You confirmed this benefit has no expiry.",
                needs_review=False,
                review_reason=None,
            )
            stored = {k: v for k, v in record.items() if k not in ("id", "source")}
            db.update_benefit_data(conn, user["id"], benefit_id, stored)
        self._send_json(HTTPStatus.OK, with_days(record, today))

    def _read_benefit_fields(self, data: dict) -> Optional[dict]:
        """
        Validates the user-editable fields (name, provider, type, category, value or
        points, expiry date, terms). Returns them, or sends a 400 and returns None.
        """
        def text(key: str, limit: int, required: bool = False) -> Optional[str]:
            value = data.get(key)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{key} must be text.")
            value = (value or "").strip()
            if required and not value:
                raise ValueError("Give the benefit a name.")
            if len(value) > limit:
                raise ValueError(f"Keep {key.replace('_', ' ')} under {limit} characters.")
            return value or None

        try:
            fields_ = {
                "benefit_name": text("benefit_name", 200, required=True),
                "provider": text("provider", 200) or "",
                "type": data.get("type"),
                "category": data.get("category"),
                "value": text("value", 100),
                "expiry_date": text("expiry_date", 10),
                "terms_summary": text("terms_summary", 500),
                "code": text("code", 64),
            }
            if fields_["type"] not in TYPES:
                raise ValueError("Pick a type from the list.")
            if fields_["category"] not in CATEGORIES:
                raise ValueError("Pick a category from the list.")
            fields_["points"] = parse_points(data.get("points"))
            if fields_["expiry_date"]:
                try:
                    date.fromisoformat(fields_["expiry_date"])
                except ValueError:
                    raise ValueError("Use a real date (YYYY-MM-DD).") from None
        except ValueError as e:
            self._error(HTTPStatus.BAD_REQUEST, str(e))
            return None
        return fields_

    def _create_benefit(self, user: dict, data: dict) -> None:
        """A benefit the user types in themselves, not found in Gmail or a card."""
        fields_ = self._read_benefit_fields(data)
        if fields_ is None:
            return
        expiry = fields_["expiry_date"]
        record = ExtractedBenefit(
            is_benefit=True,
            expiry_confidence="explicit" if expiry else "unknown",
            expiry_reasoning="Added by you." if expiry else "Added by you, with no expiry.",
            source_snippet="",
            **fields_,
        )
        benefit_id = db.new_id()
        with db.connect() as conn:
            db.add_benefit(conn, user["id"], "manual", f"manual:{benefit_id}", asdict(record), benefit_id)
            stored = db.get_benefit(conn, user["id"], benefit_id)
            today = reminders.user_today(conn, user["id"])
        self._send_json(HTTPStatus.OK, with_days(stored, today))

    def _update_benefit(self, user: dict, benefit_id: str, data: dict) -> None:
        """Edits a benefit's details. Saving marks it as checked by the user."""
        fields_ = self._read_benefit_fields(data)
        if fields_ is None:
            return
        expiry = fields_.pop("expiry_date")

        with db.connect() as conn:
            record = db.get_benefit(conn, user["id"], benefit_id)
            if record is None:
                self._error(HTTPStatus.NOT_FOUND, "That benefit no longer exists.")
                return
            if expiry != record.get("expiry_date"):
                record.update(
                    expiry_date=expiry,
                    expiry_confidence="explicit" if expiry else "unknown",
                    expiry_reasoning="Set by you." if expiry else "You removed the expiry date.",
                )
            record.update(fields_, needs_review=False, review_reason=None)
            stored = {k: v for k, v in record.items() if k not in ("id", "source")}
            db.update_benefit_data(conn, user["id"], benefit_id, stored)
            today = reminders.user_today(conn, user["id"])
        self._send_json(HTTPStatus.OK, with_days(record, today))

    def _quick_update(self, user: dict, benefit_id: str, data: dict) -> None:
        """
        One-tap changes from a benefit's card, without the full edit form. Any of:
        used (true/false), used_amount (card credits: dollars spent this period),
        points (a new balance) and reminder. Undo sends the old values back.
        """
        with db.connect() as conn:
            record = db.get_benefit(conn, user["id"], benefit_id)
            if record is None:
                self._error(HTTPStatus.NOT_FOUND, "That benefit no longer exists.")
                return
            total = credit_total(record)
            today = reminders.user_today(conn, user["id"])
            try:
                if "used" in data:
                    if not isinstance(data["used"], bool):
                        raise ValueError("used must be true or false.")
                    if data["used"]:
                        record.update(used_on=today.isoformat(), used_amount=total)
                    else:
                        record.update(used_on=None, used_amount=None)
                if "used_amount" in data:
                    amount = data["used_amount"]
                    if total is None:
                        raise ValueError("Only card credits have a balance to spend.")
                    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
                        raise ValueError("Enter an amount, like 12.50.")
                    if not 0 <= amount <= total:
                        raise ValueError(f"Enter an amount between $0 and ${total:g}.")
                    amount = round(float(amount), 2)
                    record.update(used_amount=amount or None,
                                  used_on=today.isoformat() if amount >= total else None)
                if "points" in data:
                    record["points"] = parse_points(data["points"])
                if "reminder" in data:
                    record["reminder"] = reminders.parse_reminder(data["reminder"])
            except ValueError as e:
                self._error(HTTPStatus.BAD_REQUEST, str(e))
                return
            stored = {k: v for k, v in record.items() if k not in ("id", "source")}
            db.update_benefit_data(conn, user["id"], benefit_id, stored)
        self._send_json(HTTPStatus.OK, with_days(record, today))

    def _imap_action(self, fn) -> None:
        try:
            self._send_json(HTTPStatus.OK, fn())
        except imap_sync.ImapError as e:
            self._error(HTTPStatus.BAD_REQUEST, str(e))

    def _add_card(self, user: dict, data: dict) -> None:
        month = data.get("anniversary_month")
        if month in (None, ""):
            month = None
        elif not isinstance(month, int):
            self._error(HTTPStatus.BAD_REQUEST, "Pick a valid anniversary month.")
            return
        try:
            card = cards.add_user_card(user["id"], str(data.get("card_key", "")), month)
        except ValueError as e:
            self._error(HTTPStatus.BAD_REQUEST, str(e))
            return
        self._send_json(HTTPStatus.OK, card)

    # --- static frontend ----------------------------------------------------------

    def _serve_frontend(self, path: str) -> None:
        if path in ("", "/") or path.rstrip("/") in FRONTEND_ROUTES:
            path = "/index.html"
        if not (DIST_DIR / "index.html").exists():
            self._error(HTTPStatus.SERVICE_UNAVAILABLE,
                        "Frontend not built yet. Run: cd frontend && npm install && npm run build")
            return
        # Resolve and confirm the file is inside dist/, so "../" can't escape it.
        target = (DIST_DIR / path.lstrip("/")).resolve()
        if not target.is_relative_to(DIST_DIR) or not target.is_file():
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "image/svg+xml"):
            content_type += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Vite puts a content hash in asset filenames, so they can be cached
        # forever; index.html must always be re-checked to pick up new builds.
        cache = "public, max-age=31536000, immutable" if path.startswith("/assets/") else "no-cache"
        self.send_header("Cache-Control", cache)
        if target.suffix == ".html":
            self.send_header("Content-Security-Policy", content_security_policy(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args) -> None:
        # Paths only: query strings can carry OAuth codes.
        print(f"  {self.command} {self.path.split('?', 1)[0]} -> {args[1] if len(args) > 1 else ''}")


def setup_logging() -> None:
    """Warnings and errors go to the terminal and to instance/squirrel.log, which keeps the last few MB."""
    log_file = RotatingFileHandler(config.INSTANCE_DIR / "squirrel.log", maxBytes=1_000_000, backupCount=3,
                                   encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(), log_file])


if __name__ == "__main__":
    db.init()
    setup_logging()
    if interrupted := scan_jobs.mark_interrupted():
        log.warning("%d inbox scan(s) were cut short by the last restart", interrupted)
    server = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    reminders.start()
    print(f"Squirrel running at {config.APP_URL}  (Ctrl+C to stop)")
    if not config.GOOGLE_ENABLED:
        print("  Google sign-in and Gmail are off: set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET (see PROGRESS.md).")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
