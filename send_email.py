"""
Korea Daily Brief — Email Sender
Sends the rendered HTML digest via Gmail SMTP (app password).
"""
import os
import smtplib
import time
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
      GMAIL_USER      — Gmail address (used for SMTP auth)
      GMAIL_APP_PASS  — 16-char Gmail App Password
      DIGEST_TO       — comma-separated recipient list
    Optional:
      GMAIL_FROM      — sending alias (defaults to GMAIL_USER)
    """
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_pass = os.environ.get("GMAIL_APP_PASS")
    if not gmail_user or not gmail_pass:
        raise RuntimeError("Missing GMAIL_USER or GMAIL_APP_PASS environment variables")
    from_addr = os.environ.get("GMAIL_FROM", gmail_user)
    to_str = os.environ.get("DIGEST_TO", gmail_user)

    if recipients is None:
        recipients = [r.strip() for r in to_str.split(",") if r.strip()]

    if subject is None:
        from zoneinfo import ZoneInfo
        date_str = datetime.now(ZoneInfo("America/New_York")).strftime("%m/%d/%Y")
        if re_line:
            # Truncate RE: line for subject (max ~120 chars total)
            max_re = 100
            re_short = re_line[:max_re] + ("..." if len(re_line) > max_re else "")
            subject = f"Korea Daily Brief · {date_str} — {re_short}"
        else:
            subject = f"Korea Daily Brief · {date_str}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"CSIS Korea Chair <{from_addr}>"
    msg["To"] = from_addr
    # BCC recipients are NOT added as a header — they are passed only to
    # sendmail() so they receive the email without being visible to others.

    plain = (
        "Korea Daily Brief — CSIS Korea Chair\n"
        "This digest is best viewed in an HTML-capable email client.\n"
        f"Date: {datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d %-I:%M %p ET')}"
    )
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    print(f"\n📨  Sending digest (BCC) to: {', '.join(recipients)}")
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
                server.login(gmail_user, gmail_pass)
                server.sendmail(gmail_user, recipients, msg.as_string())
            print(f"  ✅  Sent: {subject}")
            return
        except smtplib.SMTPAuthenticationError as e:
            print(f"  ✗  Gmail auth failed: {e}")
            print("     Check GMAIL_USER and GMAIL_APP_PASS (use a 16-char App Password)")
            raise
        except (smtplib.SMTPException, OSError) as e:
            if attempt < max_retries - 1:
                wait = (attempt + 1) * 5
                print(f"  ⚠  SMTP error (retry {attempt + 1}/{max_retries} in {wait}s): {e}")
                time.sleep(wait)
            else:
                print(f"  ✗  SMTP failed after {max_retries} attempts: {e}")
                raise


if __name__ == "__main__":
    html = Path("digest.html").read_text(encoding="utf-8")
    send(html)
