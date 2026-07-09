"""
Article corpus analytics.

Reads the monthly index shards written by corpus.py (public/corpus/index_*.json)
and reports trends over time — collection volume by tier, which sources actually
make the newsletter (selection rate), the source leaderboard, and topic frequency.

Usage:
    python corpus_stats.py                 # all local shards under public/corpus/
    python corpus_stats.py 2026-07         # a single month
    python corpus_stats.py --fetch         # pull recent shards from GitHub Pages
    python corpus_stats.py --dir some/path # read shards from another directory

Like cost_report.py, this is a standalone read-only tool — it never touches the
pipeline or the daily send path.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_DIR = Path("public/corpus")


def load_shards(shard_dir: Path, month: str | None = None) -> list[dict]:
    """Load index rows from local monthly shards. If month is given (YYYY-MM),
    load only that shard."""
    rows: list[dict] = []
    if not shard_dir.exists():
        return rows
    pattern = f"index_{month}.json" if month else "index_*.json"
    for path in sorted(shard_dir.glob(pattern)):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                rows.extend(data)
        except (json.JSONDecodeError, OSError):
            continue
    return rows


def fetch_shards(months: int = 3) -> list[dict]:
    """Fetch the last `months` monthly shards from GitHub Pages via corpus.py."""
    try:
        from corpus import fetch_recent_index
    except ImportError:
        return []
    # ~31 days per month of lookback; fetch_recent_index dedups by shard.
    return fetch_recent_index(n_days=months * 31)


def daily_volume(rows: list[dict]) -> dict[str, dict]:
    """Per-day counts: total collected and how many were published."""
    by_day: dict[str, dict] = defaultdict(lambda: {"total": 0, "used": 0})
    for r in rows:
        d = r.get("date", "?")
        by_day[d]["total"] += 1
        if r.get("used"):
            by_day[d]["used"] += 1
    return dict(sorted(by_day.items()))


def tier_breakdown(rows: list[dict]) -> dict[int, dict]:
    """Per-tier collected vs. published, for selection-rate analysis."""
    by_tier: dict[int, dict] = defaultdict(lambda: {"total": 0, "used": 0})
    for r in rows:
        t = r.get("tier", 0)
        by_tier[t]["total"] += 1
        if r.get("used"):
            by_tier[t]["used"] += 1
    return dict(sorted(by_tier.items()))


def source_leaderboard(rows: list[dict], top_n: int = 20) -> list[tuple]:
    """(source, collected, published) sorted by published desc, then collected."""
    stats: dict[str, dict] = defaultdict(lambda: {"total": 0, "used": 0})
    for r in rows:
        src = (r.get("source") or "unknown").strip() or "unknown"
        stats[src]["total"] += 1
        if r.get("used"):
            stats[src]["used"] += 1
    ranked = sorted(stats.items(), key=lambda kv: (kv[1]["used"], kv[1]["total"]), reverse=True)
    return [(s, v["total"], v["used"]) for s, v in ranked[:top_n]]


def topic_trends(rows: list[dict], top_n: int = 20) -> list[tuple]:
    """Most frequent topic tags across the corpus."""
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        for t in (r.get("topics") or []):
            counts[str(t).strip()] += 1
    return sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:top_n]


def _pct(used: int, total: int) -> str:
    return f"{(100 * used / total):.0f}%" if total else "—"


def print_report(rows: list[dict]):
    if not rows:
        print("No corpus data found.\n"
              "The corpus accumulates from the first pipeline run after the feature\n"
              "was deployed — there may simply be nothing recorded yet.")
        return

    dates = sorted({r.get("date", "") for r in rows if r.get("date")})
    total = len(rows)
    used = sum(1 for r in rows if r.get("used"))
    print(f"Corpus: {total:,} articles across {len(dates)} day(s) "
          f"({dates[0]} → {dates[-1]}), {used:,} published ({_pct(used, total)})\n")

    print("── Selection rate by tier ─────────────────────────────")
    print(f"{'Tier':<6} {'Collected':>10} {'Published':>10} {'Rate':>7}")
    for tier, v in tier_breakdown(rows).items():
        label = {1: "T1", 2: "T2", 3: "T3", 4: "T4"}.get(tier, str(tier))
        print(f"{label:<6} {v['total']:>10,} {v['used']:>10,} {_pct(v['used'], v['total']):>7}")

    print("\n── Source leaderboard (by published) ──────────────────")
    print(f"{'Source':<28} {'Collected':>10} {'Published':>10} {'Rate':>7}")
    for src, t, u in source_leaderboard(rows):
        print(f"{src[:28]:<28} {t:>10,} {u:>10,} {_pct(u, t):>7}")

    print("\n── Top topics ─────────────────────────────────────────")
    trends = topic_trends(rows)
    if trends:
        for topic, ct in trends:
            print(f"  {ct:>5,}  {topic}")
    else:
        print("  (no topic tags recorded)")

    print("\n── Daily volume ───────────────────────────────────────")
    print(f"{'Date':<12} {'Collected':>10} {'Published':>10}")
    for d, v in daily_volume(rows).items():
        print(f"{d:<12} {v['total']:>10,} {v['used']:>10,}")


def main():
    ap = argparse.ArgumentParser(description="Korea Daily Brief corpus analytics")
    ap.add_argument("month", nargs="?", help="Limit to a month, e.g. 2026-07")
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR,
                    help=f"Directory of index_*.json shards (default: {DEFAULT_DIR})")
    ap.add_argument("--fetch", action="store_true",
                    help="Fetch recent shards from GitHub Pages instead of reading locally")
    ap.add_argument("--months", type=int, default=3, help="With --fetch: months to pull")
    args = ap.parse_args()

    if args.fetch:
        rows = fetch_shards(args.months)
        if args.month:
            rows = [r for r in rows if str(r.get("date", "")).startswith(args.month)]
    else:
        rows = load_shards(args.dir, args.month)
    print_report(rows)


if __name__ == "__main__":
    sys.exit(main())
