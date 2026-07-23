"""
Weekly Gallup baseline updater.

Runs every Friday (gallup-update.yml workflow) after Gallup Korea's
morning release. Scrapes the latest weekly poll via the same Korean
Wikipedia tables the daily collector uses, validates it, and rewrites
gallup_baseline.json — the single source of truth for polling fallbacks
in collect.py and the CONFIRMED baseline in digest.py's prompt.

Behavior:
  - New same-poll data found and sane  -> update JSON (workflow commits it)
  - Scrape failed / data unchanged     -> leave JSON alone
  - Baseline older than ALERT_DAYS     -> email the operator (needs GMAIL_*)

Exit code is always 0 — the workflow decides whether to commit by
checking `git diff`. Trends (up/down/stable) are computed against the
previous baseline values.
"""
import json
import os
import re
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

BASELINE_PATH = Path(__file__).parent / "gallup_baseline.json"
ALERT_DAYS = 21
OPERATOR_EMAIL = "alim@csis.org"

MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]


def _load_baseline() -> dict:
    try:
        return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _pct(value) -> float | None:
    """'57%' -> 57.0"""
    m = re.search(r"(\d{1,2}(?:\.\d+)?)", str(value or ""))
    return float(m.group(1)) if m else None


def _trend(new: float | None, old: float | None) -> str:
    if new is None or old is None:
        return "stable"
    diff = new - old
    if diff >= 1:
        return "up"
    if diff <= -1:
        return "down"
    return "stable"


def _normalize_date_label(raw: str) -> tuple[str, str]:
    """Convert a wiki date cell into (survey_dates_label, sort_key).

    Handles '6월 2주차' (month/week) and ISO-ish '2026-06-12' formats.
    The label must start 'Month D, YYYY' so pipeline_health.py can parse
    its age. sort_key is YYYY-MM-DD for newer-than comparison.
    """
    now = datetime.now(timezone.utc)
    m = re.search(r"(\d{1,2})월\s*(\d)주", raw or "")
    if m:
        month, week = int(m.group(1)), int(m.group(2))
        # Gallup surveys Tue-Thu; approximate a representative mid-week day.
        day = min(28, max(1, week * 7 - 3))
        year = now.year
        # Guard the January-reading-December-data edge
        if month == 12 and now.month == 1:
            year -= 1
        label = f"{MONTH_NAMES[month - 1]} {day}, {year} ({week}주차)"
        return label, f"{year}-{month:02d}-{day:02d}"
    m = re.search(r"(20\d{2})[-./]\s*(\d{1,2})[-./]\s*(\d{1,2})", raw or "")
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        label = f"{MONTH_NAMES[month - 1]} {day}, {year}"
        return label, f"{year}-{month:02d}-{day:02d}"
    return "", ""


def _current_sort_key(baseline: dict) -> str:
    """Derive a YYYY-MM-DD sort key (the survey START date) from the stored
    survey_dates label. Handles same-month ranges ('June 9-11, 2026'),
    cross-month ranges ('June 30-July 2, 2026'), single dates ('July 3, 2026'),
    and week-suffixed labels ('July 3, 2026 (1주차)') by taking the first
    'Month Day' found plus any 4-digit year in the string."""
    raw = baseline.get("survey_dates", "")
    md = re.search(r"([A-Z][a-z]+)\s+(\d{1,2})", raw)
    yr = re.search(r"(20\d{2})", raw)
    if not md or not yr or md.group(1) not in MONTH_NAMES:
        return ""
    return f"{yr.group(1)}-{MONTH_NAMES.index(md.group(1)) + 1:02d}-{int(md.group(2)):02d}"


def _sane(pres, dp, ppp, ind) -> list[str]:
    """Sanity-check scraped percentages. Returns list of problems."""
    problems = []
    if pres is None or not (20 <= pres <= 90):
        problems.append(f"approval {pres} outside 20-90")
    if dp is None or not (3 <= dp <= 70):
        problems.append(f"DP {dp} outside 3-70")
    if ppp is None or not (3 <= ppp <= 70):
        problems.append(f"PPP {ppp} outside 3-70")
    if ind is not None and not (3 <= ind <= 60):
        problems.append(f"independents {ind} outside 3-60")
    if pres is not None and dp is not None and abs(pres - dp) < 0.01 and ppp is None:
        problems.append("approval == DP with no PPP — likely column misread")
    return problems


def _email_operator(subject: str, body: str) -> bool:
    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASS")
    if not (user and password):
        print("  (no GMAIL credentials — skipping alert email)")
        return False
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = OPERATOR_EMAIL
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
            s.login(user, password)
            s.sendmail(user, [OPERATOR_EMAIL], msg.as_string())
        print(f"  Alert emailed to {OPERATOR_EMAIL}")
        return True
    except Exception as e:
        print(f"  ⚠ Alert email failed: {e}")
        return False


def _baseline_age_days(baseline: dict) -> int | None:
    key = _current_sort_key(baseline)
    if not key:
        return None
    try:
        dt = datetime.strptime(key, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except ValueError:
        return None


def main() -> int:
    print("📊  Weekly Gallup baseline check")
    baseline = _load_baseline()
    print(f"  Current: {baseline.get('poll', '?')} · {baseline.get('survey_dates', '?')}")
    current_key = _current_sort_key(baseline)
    stale_age = _baseline_age_days(baseline)

    # Fetch + merge the latest weekly poll from Korean news (labeled extraction,
    # multi-article merge). Only accepts a poll strictly newer than the baseline.
    rec = {}
    try:
        from gallup_fetch import fetch_latest_gallup
        rec = fetch_latest_gallup(newest_sort_key=current_key)
    except Exception as e:
        print(f"  ⚠ Fetch failed: {e}")

    # Carry-forward, NOT all-or-nothing: approval anchors the update; any party
    # field the parse missed inherits the prior baseline value.
    def _carry(field):
        return _pct((baseline.get(field) or {}).get("value"))

    pres = rec.get("approval")
    if pres is None or not rec.get("sort_key"):
        print("  No newer complete-enough poll found (need approval + survey date).")
        if stale_age is not None and stale_age > ALERT_DAYS:
            _email_operator(
                f"⚠ Gallup baseline is {stale_age} days stale — manual update needed",
                f"The weekly Gallup auto-update could not parse a newer poll,\n"
                f"and the current baseline ({baseline.get('poll')}, "
                f"{baseline.get('survey_dates')}) is {stale_age} days old.\n\n"
                f"Please update gallup_baseline.json manually with the latest\n"
                f"Gallup Korea weekly numbers (gallup.co.kr, released Fridays).")
        return 0

    dp = rec.get("dp") if rec.get("dp") is not None else _carry("party_ruling")
    ppp = rec.get("ppp") if rec.get("ppp") is not None else _carry("party_opposition")
    ind = rec.get("ind") if rec.get("ind") is not None else _carry("party_independent")
    label = rec.get("survey_label") or rec["sort_key"]
    carried = [n for n, v in (("DP", rec.get("dp")), ("PPP", rec.get("ppp")),
                              ("ind", rec.get("ind"))) if v is None]
    poll_name = f"Gallup Korea #{rec['poll_no']}" if rec.get("poll_no") else f"Gallup Korea (week of {label})"

    print(f"  Parsed {poll_name}: approval {pres}%, DP {dp}%, PPP {ppp}%, ind {ind}%"
          + (f"  (carried forward: {', '.join(carried)})" if carried else ""))

    problems = _sane(pres, dp, ppp, ind)
    if problems:
        print(f"  ✗ Sanity check failed: {'; '.join(problems)} — no update.")
        if stale_age is not None and stale_age > ALERT_DAYS:
            _email_operator(
                f"⚠ Gallup auto-update parsed implausible numbers — check manually",
                f"Parsed {poll_name}: approval {pres}, DP {dp}, PPP {ppp}, ind {ind}\n"
                f"Failed sanity: {'; '.join(problems)}. Baseline left unchanged "
                f"({stale_age} days old).")
        return 0

    old = {k: _pct((baseline.get(k) or {}).get("value"))
           for k in ("presidential_approval", "party_ruling",
                     "party_opposition", "party_independent")}
    updated = dict(baseline)
    updated.update({
        "poll": poll_name,
        "survey_dates": label,
        "source": "Gallup Korea",
        "presidential_approval": {"value": f"{pres:g}%",
                                  "trend": _trend(pres, old["presidential_approval"])},
        "party_ruling": {"value": f"{dp:g}%", "party": "Democratic Party",
                         "party_kr": "더불어민주당",
                         "trend": _trend(dp, old["party_ruling"])},
        "party_opposition": {"value": f"{ppp:g}%", "party": "People Power Party",
                             "party_kr": "국민의힘",
                             "trend": _trend(ppp, old["party_opposition"])},
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "updated_by": "gallup_update.py (auto, news-parse)",
    })
    if ind is not None:
        updated["party_independent"] = {"value": f"{ind:g}%",
                                        "trend": _trend(ind, old["party_independent"])}
    # Spotlight isn't reliably in short news text — carry forward; the daily
    # digest still picks up a fresh spotlight from that day's articles.

    BASELINE_PATH.write_text(
        json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  ✅ Baseline updated -> {poll_name} ({label}): approval {pres:g}%, "
          f"DP {dp:g}%, PPP {ppp:g}%, ind {ind if ind is None else format(ind, 'g')}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
