"""
mailer.py

Sends the app's own emails (password reset links) over SMTP. Standard
library only.

Without SMTP settings in .env, the email is printed in the server terminal
instead, so password resets still work when running locally.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage

import config

log = logging.getLogger(__name__)


def send(to: str, subject: str, text: str) -> None:
    if not config.EMAIL_ENABLED:
        print(f"\n  --- Email not sent (SMTP_HOST isn't set). It would go to {to}: ---\n"
              f"  Subject: {subject}\n\n{text}\n  ---\n", flush=True)
        return

    message = EmailMessage()
    message["From"] = config.MAIL_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)

    context = ssl.create_default_context()
    if config.SMTP_PORT == 465:
        smtp = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=context, timeout=20)
    else:
        smtp = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20)
        smtp.starttls(context=context)
    with smtp:
        if config.SMTP_USER:
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
        smtp.send_message(message)
    # Shortened address: enough to tell "sent" from "never tried" without logging who it was.
    name, _, domain = to.partition("@")
    log.info("Email sent to %s…@%s: %s", name[:2], domain, subject)
