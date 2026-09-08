"""Corrections log for the Korea Daily Brief.

The brief tells every reader it is automatically generated and may contain
errors. Until now there was no way to say so when it actually did. Issues have
gone out with a fabricated seismic event, a presidential trip that was never
scheduled, an appointment that was a year old, and a poll that sat unchanged
for thirty-one days. None of that was ever acknowledged in the product.

A correction is written by a person, never by the model. The model is what got
it wrong; asking it to file the correction reintroduces the same failure. This
module is therefore a small human-authored log with a CLI:

    python corrections.py --was "Reported renewed seismic activity at Punggye-ri" \\
                          --now "No seismic event occurred. The entry was a model fabrication." \\
                          --section "Satellite & Location Watch" \\
                          --issue 2026-08-14

Entries render in the brief for RUN_DAYS after they are filed, then retire to
the log, which stays in the repo as a permanent record.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

LOG_PATH = Path(__file__).parent / "corrections.json"

# How long a filed correction keeps appearing in the brief.
RUN_DAYS = 3


def _today() -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")


def load() -> list[dict]:
    """Every correction ever filed, oldest first. Never raises."""
    try:
        data = json.loads(LOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = data.get("corrections") if isinstance(data, dict) else data
    return entries if isinstance(entries, list) else []


def active(as_of: str | None = None) -> list[dict]:
    """Corrections still inside their run window, newest first.

    Rendering is driven by this; everything else stays in the log for the
    record. A malformed date is skipped rather than raising, so a hand-edited
    file can never take the brief down.
    """
    as_of = as_of or _today()
    try:
        cutoff = date.fromisoformat(as_of) - timedelta(days=RUN_DAYS - 1)
    except ValueError:
        return []
    out = []
    for entry in load():
        try:
            filed = date.fromisoformat(str(entry.get("filed", ""))[:10])
        except ValueError:
            continue
        if filed >= cutoff and entry.get("was") and entry.get("now"):
            out.append(entry)
    out.sort(key=lambda e: str(e.get("filed", "")), reverse=True)
    return out


def file_correction(was: str, now: str, section: str = "",
                    issue: str = "", filed: str | None = None) -> dict:
    """Append one correction and write the log. Returns the stored entry."""
    if not was.strip() or not now.strip():
        raise ValueError("both --was and --now are required")
    entry = {
        "filed": filed or _today(),
        "issue": issue.strip(),      # the dated issue that carried the error
        "section": section.strip(),
        "was": was.strip(),
        "now": now.strip(),
    }
    entries = load()
    entries.append(entry)
    LOG_PATH.write_text(
        json.dumps({"corrections": entries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return entry


def main() -> int:
    ap = argparse.ArgumentParser(description="File a correction to the Korea Daily Brief.")
    ap.add_argument("--was", help="what the brief said")
    ap.add_argument("--now", help="what is correct")
    ap.add_argument("--section", default="", help="section that carried it")
    ap.add_argument("--issue", default="", help="date of the issue, YYYY-MM-DD")
    ap.add_argument("--list", action="store_true", help="show active corrections and exit")
    args = ap.parse_args()
    if args.list:
        entries = active()
        if not entries:
            print("No active corrections.")
        for e in entries:
            print(f"{e['filed']}  {e.get('section') or '—'}: {e['was']} -> {e['now']}")
        return 0
    if not args.was or not args.now:
        ap.error("--was and --now are required unless --list is given")
    entry = file_correction(args.was, args.now, args.section, args.issue)
    print(f"Filed {entry['filed']}"
          + (f" (issue {entry['issue']})" if entry["issue"] else "")
          + f"\n  was: {entry['was']}\n  now: {entry['now']}")
    print(f"\nIt will appear in the brief for the next {RUN_DAYS} days.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
