"""
eml.py

Turns an uploaded .eml file into the plain text the extractor reads. Adapted
from the repo-root imap_sync.parse_message() and mailtext.html_to_text(), so an
uploaded email is read exactly the way a scanned inbox email was.
"""

import email
import re
from email import policy
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Optional


class _TextFromHtml(HTMLParser):
    _SKIP = {"script", "style", "head", "title"}
    _BREAK = {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "table"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BREAK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextFromHtml()
    parser.feed(html)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v ‌]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def parse_eml(raw: str) -> dict:
    """{"text", "received_date", "subject"} from the raw source of one email."""
    msg = email.message_from_string(raw, policy=policy.default)

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
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        body = html_to_text(content) if part.get_content_subtype() == "html" else content.strip()

    received: Optional[str] = None
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
