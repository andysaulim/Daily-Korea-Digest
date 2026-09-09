"""Reconstruct archive.json from the pages that are still published.

Every issue ever sent is still on the site at its own URL, because the Pages
deploy keeps files it is not publishing. What was lost is the index that lists
them: `archive.json` was rebuilt from an empty list every run and overwrote
the accumulated one, so the archive page showed a single issue.

`run.py` no longer does that, but the index it now maintains starts from
whatever survived. This walks back through the calendar, asks the site whether
each day's page exists, and rebuilds the manifest from the answers.

Run it once, from somewhere that can reach the published site:

    python rebuild_archive.py --since 2025-01-01 --out public/archive.json

Then commit or deploy the file it writes. It is safe to re-run: it merges with
any existing manifest rather than replacing it, and it never deletes an entry
for a page it could not reach, since a network failure is not evidence that a
page is gone.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_BASE = "https://andysaulim.github.io/Daily-Korea-Digest"


def _dates(since: date, until: date):
    day = since
    while day <= until:
        yield day
        day += timedelta(days=1)


def probe(base: str, since: date, until: date, timeout: int = 10,
          workers: int = 12) -> list[str]:
    """Dates whose digest page answers. Missing pages are simply absent."""
    import requests
    from concurrent.futures import ThreadPoolExecutor

    session = requests.Session()

    def _one(day: date):
        slug = day.isoformat()
        url = f"{base.rstrip('/')}/digest_{slug}.html"
        try:
            resp = session.head(url, timeout=timeout, allow_redirects=True)
            if resp.status_code == 405:      # some hosts refuse HEAD
                resp = session.get(url, timeout=timeout, stream=True)
            return slug if resp.status_code == 200 else None
        except Exception:
            return None

    days = list(_dates(since, until))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        found = [slug for slug in pool.map(_one, days) if slug]
    return sorted(found)


def merge(existing: list, found_dates: list[str], base: str) -> list:
    """Add any found date the manifest is missing, keeping richer entries.

    An entry already in the manifest carries a headline and word count that
    probing cannot recover, so it always wins over a reconstructed stub.
    """
    by_date = {}
    for entry in existing or []:
        if isinstance(entry, dict) and entry.get("date"):
            by_date[entry["date"]] = entry
    for slug in found_dates:
        by_date.setdefault(slug, {
            "date": slug,
            "headline_re": "",
            "top_stories_count": 0,
            "word_count": 0,
            "url": f"digest_{slug}.html",
            "reconstructed": True,
        })
    return sorted(by_date.values(), key=lambda e: e["date"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default=DEFAULT_BASE, help="published site root")
    ap.add_argument("--since", required=True, help="earliest date to probe, YYYY-MM-DD")
    ap.add_argument("--until", default=date.today().isoformat(),
                    help="latest date to probe, YYYY-MM-DD (default today)")
    ap.add_argument("--out", default="public/archive.json")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what was found and write nothing")
    args = ap.parse_args()

    since = datetime.strptime(args.since, "%Y-%m-%d").date()
    until = datetime.strptime(args.until, "%Y-%m-%d").date()
    if since > until:
        print("--since is after --until")
        return 2

    span = (until - since).days + 1
    print(f"Probing {span} days at {args.base} …")
    found = probe(args.base, since, until)
    print(f"  {len(found)} issues found"
          + (f", from {found[0]} to {found[-1]}" if found else ""))
    if not found:
        print("  Nothing answered. Check --base, or whether the site is reachable "
              "from here; an empty result is not evidence the pages are gone.")
        return 1

    out = Path(args.out)
    try:
        existing = json.loads(out.read_text(encoding="utf-8"))
        existing = existing if isinstance(existing, list) else []
    except (OSError, ValueError):
        existing = []

    merged = merge(existing, found, args.base)
    added = len(merged) - len(existing)
    print(f"  manifest: {len(existing)} entries -> {len(merged)} ({added} added)")

    if args.dry_run:
        print("  --dry-run: nothing written")
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  wrote {out}")
    print("  Deploy or commit this file, then the archive page will list them all.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
