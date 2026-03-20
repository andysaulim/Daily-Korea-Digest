"""
CSIS Korea Digest — Email Sender
CSIS Korea Chair
Sends the rendered HTML digest via Gmail SMTP (app password).
Configure via environment variables — no credentials in code.
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
def send(html: str, subject: Optional[str] = None, recipients: Optional[list] = None):
    """
    Send the digest HTML via Gmail SMTP.
    Required environment variables:
      GMAIL_USER      — your Gmail address (e.g. sau@beyondparallel.org)
      GMAIL_APP_PASS  — 16-char Gmail App Password (not your login password)
      DIGEST_TO       — comma-separated recipient list
    """
    gmail_user = os.environ["GMAIL_USER"]
    gmail_pass = os.environ["GMAIL_APP_PASS"]
    to_str     = os.environ.get("DIGEST_TO", gmail_user)
    if recipients is None:
        recipients = [r.strip() for r in to_str.split(",") if r.strip()]
    if subject is None:
        date_str = datetime.now(timezone.utc).strftime("%-d %B %Y")
        subject  = f"CSIS Korea Digest · {date_str}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"CSIS Korea Chair <{gmail_user}>"
    msg["To"]      = ", ".join(recipients)
    # Plain text fallback
    plain = (
        "CSIS Korea Digest — CSIS Korea Chair\n"
        "This digest is best viewed in an HTML-capable email client.\n"
        f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))
    print(f"\n📨  Sending digest to: {', '.join(recipients)}")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_pass)
        server.sendmail(gmail_user, recipients, msg.as_string())
    print(f"  ✅  Sent: {subject}")
if __name__ == "__main__":
    html = Path("digest.html").read_text(encoding="utf-8")
    send(html)
