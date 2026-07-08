"""
Monthly API cost breakdown from metrics.jsonl.

Usage:
    python cost_report.py            # all months
    python cost_report.py 2026-06    # one month

Token/cost fields are recorded per run by digest.py (via run.py) starting
June 2026. Runs before that appear as "untracked" — they predate cost
logging, so their spend is unknown, not zero. The weekly Friday synthesis
(weekly.py) runs in a separate workflow and is not tracked here (~$0.20/wk).
"""
import json
import sys
from collections import defaultdict
from pathlib import Path


def load_metrics(path: str = "metrics.jsonl") -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def monthly_breakdown(rows: list[dict]) -> dict:
    """Group runs by YYYY-MM. Returns {month: aggregate dict}."""
    months = defaultdict(lambda: {
        "runs": 0, "tracked_runs": 0, "api_calls": 0,
        "input_tokens": 0, "output_tokens": 0,
        "cache_write_tokens": 0, "cache_read_tokens": 0,
        "est_cost_usd": 0.0,
    })
    for row in rows:
        month = str(row.get("date", ""))[:7]
        if len(month) != 7:
            continue
        m = months[month]
        m["runs"] += 1
        if "est_cost_usd" in row:
            m["tracked_runs"] += 1
            m["api_calls"] += row.get("api_calls", 0)
            m["input_tokens"] += row.get("input_tokens", 0)
            m["output_tokens"] += row.get("output_tokens", 0)
            m["cache_write_tokens"] += row.get("cache_write_tokens", 0)
            m["cache_read_tokens"] += row.get("cache_read_tokens", 0)
            m["est_cost_usd"] += row.get("est_cost_usd", 0.0)
    return dict(sorted(months.items()))


def print_report(months: dict, only_month: str | None = None):
    if not months:
        print("No data in metrics.jsonl yet.")
        return
    header = (f"{'Month':<9} {'Runs':>5} {'Calls':>6} {'Tokens in':>12} "
              f"{'Tokens out':>11} {'Est. cost':>10} {'$/run':>7}")
    print(header)
    print("─" * len(header))
    total_cost = 0.0
    for month, m in months.items():
        if only_month and month != only_month:
            continue
        untracked = m["runs"] - m["tracked_runs"]
        cost = m["est_cost_usd"]
        total_cost += cost
        per_run = cost / m["tracked_runs"] if m["tracked_runs"] else 0.0
        print(f"{month:<9} {m['runs']:>5} {m['api_calls']:>6} "
              f"{m['input_tokens']:>12,} {m['output_tokens']:>11,} "
              f"{'$' + format(cost, '.2f'):>10} {'$' + format(per_run, '.2f'):>7}"
              + (f"   ({untracked} untracked)" if untracked else ""))
    if not only_month and len(months) > 1:
        print("─" * len(header))
        print(f"{'Total':<9} {'':>5} {'':>6} {'':>12} {'':>11} "
              f"{'$' + format(total_cost, '.2f'):>10}")
    print("\nNote: costs are estimates computed from per-call token counts at "
          "published per-model rates.\nAuthoritative billing lives at "
          "console.anthropic.com. Weekly synthesis (~$0.20/wk) not included.")


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    print_report(monthly_breakdown(load_metrics()), only)
