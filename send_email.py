"""
Korea Brief — Email Sender
Sends the rendered HTML digest via Gmail SMTP (app password).
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def send(html: str, re_line: Optional[str] = None, subject: Optional[str] = None,
         recipients: Optional[list] = None):
    """
    Send the digest HTML via Gmail SMTP.
    Required environment variables:
      GMAIL_USER      — Gmail address
      GMAIL_APP_PASS  — 16-char Gmail App Password
      DIGEST_TO       — comma-separated recipient list
    """
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_pass = os.environ.get("GMAIL_APP_PASS")
    if not gmail_user or not gmail_pass:
        raise RuntimeError("Missing GMAIL_USER or GMAIL_APP_PASS environment variables")
    to_str = os.environ.get("DIGEST_TO", gmail_user)

    if recipients is None:
        recipients = [r.strip() for r in to_str.split(",") if r.strip()]

    if subject is None:
        date_str = datetime.now(timezone.utc).strftime("%m/%d/%Y")
        if re_line:
            # Truncate RE: line for subject (max ~120 chars total)
            max_re = 100
            re_short = re_line[:max_re] + ("..." if len(re_line) > max_re else "")
            subject = f"Korea Brief · {date_str} — {re_short}"
        else:
            subject = f"Korea Brief · {date_str}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"CSIS Korea Chair <{gmail_user}>"
    msg["To"] = ", ".join(recipients)

    plain = (
        "Korea Brief — CSIS Korea Chair\n"
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
