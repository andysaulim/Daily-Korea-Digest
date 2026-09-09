"""
Korea Daily Brief — Email Sender
Sends the rendered HTML digest via Gmail SMTP (app password).
"""
import os
import re
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# HTML → Plain Text Converter
# ─────────────────────────────────────────────────────────────────────────────

def _html_to_plain_text(html: str) -> str:
    """Convert digest HTML into readable plain text for text-only email clients.

    Uses regex-based transformations (no external HTML parser required).
    The output is readable in a terminal or plain-text email viewer.
    """
    text = html

    # Remove <head>...</head> entirely (CSS, meta tags, etc.)
    text = re.sub(r'<head[^>]*>.*?</head>', '', text, flags=re.DOTALL | re.IGNORECASE)

    # Remove <style>...</style> blocks
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)

    # Remove <script>...</script> blocks
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)

    # Remove HTML comments
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)

    # Remove conditional comments (<!--[if ...]>...<![endif]-->)
    text = re.sub(r'<!\[if[^\]]*\]>.*?<!\[endif\]>', '', text, flags=re.DOTALL | re.IGNORECASE)

    # Convert <h2> to === SECTION NAME ===
    def _h2_replace(m):
        inner = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        return f"\n\n=== {inner.upper()} ===\n"
    text = re.sub(r'<h2[^>]*>(.*?)</h2>', _h2_replace, text, flags=re.DOTALL | re.IGNORECASE)

    # Convert <h1> to a prominent header
    def _h1_replace(m):
        inner = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        return f"\n{'=' * 60}\n  {inner}\n{'=' * 60}\n"
    text = re.sub(r'<h1[^>]*>(.*?)</h1>', _h1_replace, text, flags=re.DOTALL | re.IGNORECASE)

    # Convert <h3> to --- Section ---
    def _h3_replace(m):
        inner = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        return f"\n--- {inner} ---\n"
    text = re.sub(r'<h3[^>]*>(.*?)</h3>', _h3_replace, text, flags=re.DOTALL | re.IGNORECASE)

    # Convert <a href="url">text</a> to text (url)
    def _link_replace(m):
        url = m.group(1).strip()
        link_text = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        # Skip mailto links and anchors
        if url.startswith('#') or url.startswith('mailto:'):
            return link_text
        # If link text is the same as URL, just show URL
        if link_text == url or not link_text:
            return url
        return f"{link_text} ({url})"
    text = re.sub(r'<a[^>]+href="([^"]*)"[^>]*>(.*?)</a>', _link_replace, text, flags=re.DOTALL | re.IGNORECASE)
    # Adjacent links ran together as "Read online (url)Download PDF (url)".
    text = re.sub(r'\)(?=[A-Z])', ')  ', text)

    # Convert <li> to   - item
    def _li_replace(m):
        inner = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        return f"\n  - {inner}"
    text = re.sub(r'<li[^>]*>(.*?)</li>', _li_replace, text, flags=re.DOTALL | re.IGNORECASE)

    # Convert <br> and <br/> to newlines
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)

    # Convert </p>, </div>, </tr> to newlines (block-level endings)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</tr>', '\n', text, flags=re.IGNORECASE)

    # Cells are separated by a space, not a pipe. This brief is built from
    # nested layout tables — the masthead, every section, the footer — so a
    # pipe per cell produced pages of stray "  |" lines with nothing beside
    # them. A space keeps the one case that reads well (the market strip on
    # one line: "KOSPI 6,562.72 +1.4%") without inventing table rules that are
    # not there.
    text = re.sub(r'<td[^>]*>', ' ', text, flags=re.IGNORECASE)

    # Convert <hr> to a separator line
    text = re.sub(r'<hr[^>]*/?>', '\n' + '-' * 50 + '\n', text, flags=re.IGNORECASE)

    # Strip all remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # Decode common HTML entities
    entity_map = {
        '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"',
        '&apos;': "'", '&nbsp;': ' ', '&mdash;': '--', '&ndash;': '-',
        '&middot;': '*', '&bull;': '*', '&ldquo;': '"', '&rdquo;': '"',
        '&lsquo;': "'", '&rsquo;': "'", '&hellip;': '...',
        '&copy;': '(c)', '&reg;': '(R)', '&trade;': '(TM)',
        '&#9650;': '^', '&#9660;': 'v', '&#8594;': '->', '&#8592;': '<-',
        '&#x2022;': '*',
    }
    for entity, char in entity_map.items():
        text = text.replace(entity, char)

    # Decode numeric HTML entities (&#NNN; and &#xHHH;)
    def _decode_numeric(m):
        try:
            if m.group(1):
                return chr(int(m.group(1)))
            elif m.group(2):
                return chr(int(m.group(2), 16))
        except (ValueError, OverflowError):
            return m.group(0)
        return m.group(0)
    text = re.sub(r'&#(\d+);|&#x([0-9a-fA-F]+);', _decode_numeric, text)

    # Collapse multiple blank lines to at most two
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Collapse multiple spaces on a line (but preserve leading whitespace for list items)
    text = re.sub(r'[^\S\n]{3,}', '  ', text)

    # Drop lines left holding only separator punctuation after tag stripping.
    text = "\n".join("" if re.fullmatch(r"[\s|·*—–-]*", ln) else ln
                     for ln in text.split("\n"))
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Clean up lines: strip trailing whitespace per line
    lines = [line.rstrip() for line in text.split('\n')]
    text = '\n'.join(lines)

    # Remove leading blank lines
    text = text.lstrip('\n')

    # Ensure trailing newline
    if not text.endswith('\n'):
        text += '\n'

    return text


_ADDR_RE = re.compile(r"^[^@\s,;<>\"]+@[^@\s,;<>\"]+\.[A-Za-z]{2,}$")


def _parse_recipients(raw: str) -> list:
    """Split a recipient secret into clean addresses.

    GitHub secrets are edited in a textarea, so a multi-recipient DIGEST_TO
    often arrives newline-separated (or with a trailing newline). smtplib
    rejects any RCPT TO containing a newline outright, which failed the send
    after the digest had already been generated and paid for. Accept commas,
    semicolons, and any whitespace as separators, strip angle brackets, and
    drop anything that is not a plausible address.
    """
    out = []
    for part in re.split(r"[,;\s]+", (raw or "").strip()):
        addr = part.strip().strip("<>").strip()
        if not addr:
            continue
        if not _ADDR_RE.match(addr):
            print(f"  \u26a0  Skipping malformed recipient: {addr!r}")
            continue
        if addr not in out:
            out.append(addr)
    return out


def build_subject(re_line: Optional[str] = None, lead: Optional[str] = None,
                  now=None, limit: int = 78) -> str:
    """The subject line.

    House format: "Korea Daily Brief | Tuesday, September 8, 2026". A daily brief
    that arrives at the same hour every morning is found by its name, filtered
    by its name, and searched by its name, so the name comes first and the
    date is spelled out rather than left as digits.

    It replaced "Korea Daily Brief · 09/08/2026 — " followed by whatever
    survived of the RE line at a hundred characters, which cut mid-item and
    often mid-word because the RE line is a list of fragments.

    Setting DIGEST_SUBJECT_STYLE=lead puts the day's lead story after the
    date instead, for anyone who would rather the subject argue for opening it
    than name itself. Truncation there falls on a word boundary.
    """
    from zoneinfo import ZoneInfo
    now = now or datetime.now(ZoneInfo("America/New_York"))
    date_str = now.strftime("%A, %B %-d, %Y")
    base = f"Korea Daily Brief | {date_str}"

    if (os.environ.get("DIGEST_SUBJECT_STYLE") or "").strip().lower() != "lead":
        return base

    headline = (lead or "").strip()
    if not headline and re_line:
        headline = re.split(r"\s*[·•|]\s*|\s+—\s+", re_line.strip())[0].strip()
    headline = re.sub(r"\s+", " ", headline).rstrip(" .")
    if not headline:
        return base

    room = limit - len(base) - 3
    if room < 24:
        return base
    if len(headline) > room:
        cut = headline[:room]
        if " " in cut:
            cut = cut[:cut.rindex(" ")]
        headline = cut.rstrip(" ,;:") + "…"
    return f"{base} — {headline}"

def send(html: str, re_line: Optional[str] = None, subject: Optional[str] = None,
         lead: Optional[str] = None,
         recipients: Optional[list] = None):
    """
    Send the digest HTML via Gmail SMTP.
    Required environment variables:
      GMAIL_USER      — Gmail address (used for SMTP auth)
      GMAIL_APP_PASS  — 16-char Gmail App Password
      DIGEST_TO       — recipient list, separated by commas, semicolons, or newlines
    Optional:
      GMAIL_FROM        — sending alias (defaults to GMAIL_USER)
      DIGEST_REPLY_TO   — address replies go to (defaults to alim@csis.org)
      DIGEST_VISIBLE_TO — address shown on the To line (defaults to the reply address)
      DIGEST_FROM_NAME  — display name in the inbox (defaults to "Andy Lim · CSIS Korea Chair")
      SMTP_HOST/PORT/USER — send through another server, e.g. the institution's
                        own, which is the only way to make From the work
                        address when a Gmail alias is not available
    """
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_pass = os.environ.get("GMAIL_APP_PASS")
    if not gmail_user or not gmail_pass:
        raise RuntimeError("Missing GMAIL_USER or GMAIL_APP_PASS environment variables")
    gmail_user = gmail_user.strip()
    gmail_pass = gmail_pass.strip()
    # A GitHub Actions secret that is not set arrives as an empty string, not
    # as an absent key, so os.environ.get(..., default) returns "" and the
    # default never applies. Unset and empty must mean the same thing here, or
    # adding an optional secret to the workflow silently blanks a header.
    def _env(name: str, default: str = "") -> str:
        return (os.environ.get(name) or "").strip() or default

    from_addr = _env("GMAIL_FROM", gmail_user)
    smtp_host = _env("SMTP_HOST", "smtp.gmail.com")
    try:
        smtp_port = int(_env("SMTP_PORT", "465"))
    except ValueError:
        smtp_port = 465
    smtp_user = _env("SMTP_USER", gmail_user)
    # On the institution's own server the envelope sender is the account that
    # authenticated, which is also the address the brief should appear from.
    envelope_from = from_addr if smtp_host != "smtp.gmail.com" else gmail_user
    # Replies go to the desk, not to the mailbox that happens to send. Gmail
    # will only put an unverified alias in From, so the personal address stays
    # there while Reply-To and the visible To carry the work address — a reader
    # hitting reply reaches alim@csis.org without anyone having to notice.
    reply_to = _env("DIGEST_REPLY_TO", "alim@csis.org")
    display_to = _env("DIGEST_VISIBLE_TO", reply_to)
    to_str = _env("DIGEST_TO", gmail_user)

    if recipients is None:
        recipients = _parse_recipients(to_str)
    if not recipients:
        raise RuntimeError(
            "No valid recipients. DIGEST_TO parsed to an empty list — check the "
            "secret for stray punctuation or a missing address.")

    if subject is None:
        subject = build_subject(re_line=re_line, lead=lead)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    # Nearly every client lists the display name and hides the address behind
    # it, so when the sending address cannot be changed the label is the part
    # that does the work. Naming the person as well as the desk makes a Gmail
    # address read as deliberate rather than as an oversight, and it is the
    # name a recipient is looking for when they scan an inbox at 6 AM.
    from_name = _env("DIGEST_FROM_NAME", "Andy Lim · CSIS Korea Chair")
    msg["From"] = f"{from_name} <{from_addr}>"
    if reply_to:
        msg["Reply-To"] = f"Andy Lim <{reply_to}>"
    # Everyone is BCC'd, so this header is only what recipients see on the To
    # line. It should read as the desk, not as a personal Gmail address.
    msg["To"] = f"CSIS Korea Chair <{display_to}>" if display_to else from_addr
    # BCC recipients are NOT added as a header — they are passed only to
    # sendmail() so they receive the email without being visible to others.

    plain = _html_to_plain_text(html)
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    print(f"\n📨  Sending digest (BCC) to: {', '.join(recipients)}")
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Hardcoding Gmail meant the From address could never be the work
            # address, because Gmail refuses to send as an alias it has not
            # verified and that verification is not always available. Pointing
            # SMTP_HOST at the institution's own server is the real fix: the
            # brief then sends as alim@csis.org natively, with no alias
            # involved. Microsoft 365 is smtp.office365.com on port 587, which
            # needs STARTTLS rather than implicit SSL, so both are supported.
            if smtp_port == 465:
                with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
                    server.login(smtp_user, gmail_pass)
                    server.sendmail(envelope_from, recipients, msg.as_string())
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(smtp_user, gmail_pass)
                    server.sendmail(envelope_from, recipients, msg.as_string())
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
    html = Path("latest.html").read_text(encoding="utf-8")
    send(html)
