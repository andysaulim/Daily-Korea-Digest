"""A short email to the owner after each run: what was dropped, flagged or fell back.

Everything the pipeline reports goes to the run log, which nobody reads at
7 AM. The warnings were real (Analysis short, quotes dropped, the BOK rate
on a stale fallback for weeks) and the brief went out anyway, looking fine.
This reads the same lines the log gets and mails them, sorted, so a problem
is visible the morning it happens.

`start()` tees stdout from the top of run.main(); `send()` is registered with
atexit, so a run that stops on a validation failure still reports. Goes to
HEALTH_REPORT_TO, or to the sending account itself; HEALTH_REPORT=0 turns it
off. Never raises.
"""
from __future__ import annotations

import atexit
import html
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

_LINES: list[str] = []
FACTS: dict = {}          # filled in by run.py: sent, words, bytes, audio, cost, design, issue


class _Tee:
    def __init__(self, stream):
        self._s = stream
        self._buf = ""

    def write(self, text):
        try:
            self._buf += text
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                if line.strip():
                    _LINES.append(line.rstrip())
        except Exception:                                       # noqa: BLE001
            pass
        return self._s.write(text)

    def flush(self):
        return self._s.flush()

    def __getattr__(self, name):
        return getattr(self._s, name)


def start() -> None:
    if not isinstance(sys.stdout, _Tee):
        sys.stdout = _Tee(sys.stdout)
    atexit.register(send)


# (heading, pattern) in the order the email shows them; a line goes under the first that matches.
GROUPS = [
    ("Problems", re.compile(r"::error|🚨|ALERT|CRITICAL|Traceback|🚫")),
    ("Removed by the checks", re.compile(
        r"title=(?:Fact check|Upcoming check)|removed|dropped|Removed|Dropped|🧹|cut the sentence", re.I)),
    ("Fell back to stored data", re.compile(r"fallback|last known|baseline used|stale|using .*baseline", re.I)),
    ("Flagged", re.compile(r"::warning|::notice|⚠|WARN", re.I)),
]
_SKIP = re.compile(r"Node\.js 20 is deprecated|^\s*OK\s|checks passed", re.I)
MAX_PER_GROUP = 25


def _clean(line: str) -> str:
    """'::warning title=Analysis left out::the section ran…' -> 'Analysis left out: the section ran…'"""
    m = re.match(r"::(?:warning|notice|error)(?: title=([^:]*))?::(.*)", line.strip())
    if m:
        title = (m.group(1) or "").replace("%3A", ":").replace("%2C", ",")
        msg = m.group(2).replace("%0A", " ").replace("%0D", "").replace("%25", "%")
        line = f"{title}: {msg}" if title else msg
    return re.sub(r"\s+", " ", line).strip()


def grouped(lines: list[str] | None = None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {g: [] for g, _ in GROUPS}
    seen = set()
    for raw in lines if lines is not None else _LINES:
        if _SKIP.search(raw):
            continue
        for name, pat in GROUPS:
            if pat.search(raw):
                text = _clean(raw)
                if text and text not in seen:
                    seen.add(text)
                    out[name].append(text)
                break
    return out


def build(lines: list[str] | None = None, facts: dict | None = None) -> tuple[str, str]:
    """(subject, html) for the report."""
    facts = FACTS if facts is None else facts
    groups = grouped(lines)
    now = datetime.now(ZoneInfo("America/New_York"))
    status = "sent" if facts.get("sent") else ("NOT SENT" if facts.get("sent") is False else "run ended")
    n_removed, n_problems = len(groups["Removed by the checks"]), len(groups["Problems"])
    subject = (f"Brief health, {now:%b} {now.day}: {status}"
               + (f", {n_problems} problem{'s' if n_problems != 1 else ''}" if n_problems else "")
               + (f", {n_removed} removed" if n_removed else "")
               + (f", {len(groups['Fell back to stored data'])} fallback" if groups["Fell back to stored data"] else ""))
    stats = [f"<b>{html.escape(status.capitalize())}</b>"]
    for key, label in (("words", "words"), ("bytes", "bytes"), ("audio_minutes", "min audio"),
                       ("cost", "model cost")):
        v = facts.get(key)
        if v not in (None, "", 0):
            stats.append(f"{v:,} {label}" if isinstance(v, int) else f"{html.escape(str(v))} {label}")
    body = (f'<p style="margin:0 0 12px;">{" &ensp; ".join(stats)}</p>')
    if facts.get("run_url"):
        body += f'<p style="margin:0 0 12px;"><a href="{html.escape(facts["run_url"])}">Run log</a></p>'
    for name, _ in GROUPS:
        items = groups[name]
        if not items:
            continue
        shown = items[:MAX_PER_GROUP]
        body += (f'<h3 style="margin:16px 0 6px;font-size:14px;">{name} ({len(items)})</h3><ul style="margin:0;padding-left:18px;">'
                 + "".join(f'<li style="margin:0 0 4px;">{html.escape(t[:400])}</li>' for t in shown)
                 + (f"<li>and {len(items) - len(shown)} more in the run log</li>" if len(items) > len(shown) else "")
                 + "</ul>")
    if not any(groups.values()):
        body += "<p>Nothing was dropped, flagged or fell back.</p>"
    page = (f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.5;color:#111;'
            f'max-width:640px;">{body}<p style="color:#666;font-size:11px;margin-top:18px;">'
            f'Korea Daily Brief run report, {now:%-I:%M %p} ET. For the owner only.</p></div>')
    return subject, page


_SENT = False


def send() -> None:
    """Mail the report once. Never raises."""
    global _SENT
    if _SENT or os.environ.get("HEALTH_REPORT", "1") == "0":
        return
    _SENT = True
    try:
        to = [a.strip() for a in re.split(r"[,;\s]+", os.environ.get("HEALTH_REPORT_TO", "")) if "@" in a]
        to = to or [os.environ.get("GMAIL_USER", "").strip()]
        if not to[0] or not os.environ.get("GMAIL_APP_PASS"):
            return
        run_id, repo = os.environ.get("GITHUB_RUN_ID"), os.environ.get("GITHUB_REPOSITORY")
        if run_id and repo:
            FACTS.setdefault("run_url", f"https://github.com/{repo}/actions/runs/{run_id}")
        subject, page = build()
        from send_email import send as _send
        _send(page, subject=subject, recipients=to)
    except Exception as e:                                      # noqa: BLE001
        try:
            sys.__stdout__.write(f"  ⚠  Health report not sent: {e}\n")
        except Exception:                                       # noqa: BLE001
            pass
