#!/usr/bin/env python3
"""Test every configured feed and report which candidate answered.

Why this exists: eleven feeds had delivered nothing for eleven consecutive
runs, and the run log could say so but not say why — a source that is silent
because its URL moved looks exactly like a source that published nothing.
Telling them apart needs a request to each candidate, which the pipeline does
not make in isolation.

Run it anywhere with outbound network access:

    python check_feeds.py              # every feed
    python check_feeds.py --silent     # only feeds that returned nothing
    python check_feeds.py --name RAND  # one feed

Exit code is 1 if any feed returns nothing from any candidate, so it can gate
a scheduled check without gating a send.
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import collect

# The feed dictionaries, with how their values are shaped. A tiered dict holds
# (candidates, tier); a plain one holds candidates directly.
_DICTS = [
    ("Tier 1 news", "TIER1_FEEDS", False),
    ("Tier 2 analysis", "TIER2_FEEDS", True),
    ("Tier 3 academic", "TIER3_FEEDS", True),
    ("Tier 4 DPRK", "TIER4_FEEDS", False),
    ("Satellite imagery", "SATELLITE_IMAGERY_FEEDS", False),
]


def _candidates(value, tiered: bool) -> list[str]:
    raw = value[0] if tiered and isinstance(value, tuple) else value
    return [raw] if isinstance(raw, str) else list(raw)


def _probe(name: str, cands: list[str]) -> tuple[str, int, int, str]:
    """Return (name, winning candidate index, item count, which URL won).

    Each candidate is parsed exactly as the collector parses it, so a pass here
    means the collector would get the same items.
    """
    for i, url in enumerate(cands):
        try:
            entries = collect._parse_feed(url)
        except Exception:
            entries = []
        if entries:
            return name, i, len(entries), url
    return name, -1, 0, cands[-1] if cands else ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--silent", action="store_true",
                    help="only show feeds that returned nothing")
    ap.add_argument("--name", help="check a single feed by name")
    args = ap.parse_args()

    jobs: list[tuple[str, str, list[str]]] = []
    for label, attr, tiered in _DICTS:
        d = getattr(collect, attr, None)
        if not isinstance(d, dict):
            continue
        for name, value in d.items():
            if args.name and args.name.lower() not in name.lower():
                continue
            jobs.append((label, name, _candidates(value, tiered)))

    if not jobs:
        print("No feeds matched.")
        return 1

    results: dict[str, tuple[int, int, str]] = {}
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = {pool.submit(_probe, n, c): (g, n) for g, n, c in jobs}
        for fut in as_completed(futures):
            name, idx, count, url = fut.result()
            results[name] = (idx, count, url)

    dead: list[str] = []
    fallback_only: list[str] = []
    for label, attr, _t in _DICTS:
        rows = [(g, n, c) for g, n, c in jobs if g == label]
        if not rows:
            continue
        shown = False
        for _g, name, cands in sorted(rows, key=lambda r: r[1].lower()):
            idx, count, url = results.get(name, (-1, 0, ""))
            if idx < 0:
                dead.append(name)
            elif idx > 0:
                fallback_only.append(name)
            elif args.silent:
                continue
            if not shown:
                print(f"\n{label}")
                shown = True
            if idx < 0:
                verdict = f"DEAD — no candidate answered ({len(cands)} tried)"
            else:
                which = "publisher" if "news.google.com" not in url else "Google News"
                nth = "" if idx == 0 else f", candidate {idx + 1}"
                verdict = f"{count:>3} items via {which}{nth}"
            print(f"  {name:28} {verdict}")

    print(f"\n{len(jobs)} feeds checked · {len(dead)} dead · "
          f"{len(fallback_only)} answered only on a later candidate")
    if dead:
        print("\nDead (returned nothing from any candidate):")
        for n in sorted(dead):
            print(f"  - {n}")
    if fallback_only:
        print("\nAnswered only on a fallback — the publisher feed in front of "
              "these is wrong or has moved:")
        for n in sorted(fallback_only):
            print(f"  - {n}  (now: {results[n][2][:70]})")
    return 1 if dead else 0


if __name__ == "__main__":
    sys.exit(main())
