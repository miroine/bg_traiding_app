"""
Notification delivery — email (SMTP) and push (ntfy.sh). Standard library only.

Configure via environment variables; whatever isn't set is simply skipped, so this
degrades gracefully. `notify()` returns the list of channels that accepted the
message (useful for a "test notification" button and for logging in the runner).

Email:
    SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASS,
    ALERT_EMAIL_FROM (default SMTP_USER), ALERT_EMAIL_TO
Push (ntfy.sh — free, no account; pick a hard-to-guess topic):
    NTFY_TOPIC   e.g. "oslo-desk-a8f3k2"   (optional NTFY_SERVER, default https://ntfy.sh)
"""

from __future__ import annotations

import os


def send_email(subject: str, body: str) -> bool:
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    to = os.environ.get("ALERT_EMAIL_TO")
    if not (host and user and to):
        return False
    import smtplib
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("ALERT_EMAIL_FROM", user)
    msg["To"] = to
    msg.set_content(body)
    port = int(os.environ.get("SMTP_PORT", "587"))
    pw = os.environ.get("SMTP_PASS", "")
    with smtplib.SMTP(host, port, timeout=20) as s:
        s.starttls()
        if pw:
            s.login(user, pw)
        s.send_message(msg)
    return True


def send_ntfy(message: str, title: str = "Oslo Børs alert") -> bool:
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return False
    import urllib.request
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    req = urllib.request.Request(f"{server}/{topic}",
                                 data=message.encode("utf-8"),
                                 headers={"Title": title})
    urllib.request.urlopen(req, timeout=15)
    return True


def notify(subject: str, message: str) -> list:
    """Send via every configured channel. Returns the channels that succeeded."""
    sent = []
    for name, fn in (("email", lambda: send_email(subject, message)),
                     ("ntfy", lambda: send_ntfy(message, subject))):
        try:
            if fn():
                sent.append(name)
        except Exception:
            pass
    return sent


def channels_configured() -> list:
    ch = []
    if os.environ.get("SMTP_HOST") and os.environ.get("ALERT_EMAIL_TO"):
        ch.append("email")
    if os.environ.get("NTFY_TOPIC"):
        ch.append("ntfy")
    return ch
