"""
Tracker state between runs: the Actions cache, with the repository behind it.

The trackers are what keep the model's baselines real (Kim's last appearance,
the KCNA fortnight, facility statuses, which feeds have gone quiet). They used
to live only in the Actions cache, and every one of them treats a missing or
unreadable file as "start empty" and then saves. So a cache miss — GitHub
evicts an entry after seven days without a hit, and a repository has a size
cap — silently reset each tracker to nothing, and that empty state was cached
and carried forward as if it were the history.

Now the workflow also commits them, as it already did metrics.jsonl, and this
picks the newer of the two copies after the cache restore:

    python restore_state.py stash       # before the cache restore
    python restore_state.py reconcile   # after it

The cache usually wins (it is written even when the commit step fails). The
committed copy wins when the cache missed, or holds an older or corrupt file.
metrics.jsonl is merged line by line, so neither copy can drop the other's
rows. When neither copy exists the run still goes ahead, with an annotation
saying which tracker is starting from empty.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).parent
STASH = ".state-repo"

# file -> the field that says which copy is newer
TRACKERS = {
    "kim_tracker.json": "last_updated",
    "kcna_tracker.json": "last_updated",
    "bp_tracker.json": "last_updated",
    "feed_health.json": "total_runs",
}
METRICS = "metrics.jsonl"


def _read(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and data else None
    except (OSError, ValueError):
        return None


def _age_key(data: dict | None, field: str):
    """Comparable freshness; None sorts lowest."""
    if data is None:
        return (0, "")
    v = data.get(field)
    if v is None:
        return (1, "")
    return (2, f"{v:020d}" if isinstance(v, int) else str(v))


def stash(root: Path = HERE) -> list[str]:
    out = root / STASH
    out.mkdir(exist_ok=True)
    kept = []
    for name in (*TRACKERS, METRICS):
        src = root / name
        if src.exists():
            shutil.copy2(src, out / name)
            kept.append(name)
    return kept


def _merge_metrics(live: Path, repo: Path) -> int | None:
    """Union of both copies' rows in date order. Returns rows added, or None."""
    def lines(p: Path) -> list[str]:
        try:
            return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        except OSError:
            return []
    a, b = lines(live), lines(repo)
    if not b:
        return None
    seen, merged = set(), []
    for ln in a + b:
        if ln not in seen:
            seen.add(ln)
            merged.append(ln)
    if len(merged) == len(a):
        return 0

    def day(ln: str) -> str:
        try:
            return str(json.loads(ln).get("date", ""))[:10]
        except ValueError:
            return ""
    merged.sort(key=day)
    live.write_text("\n".join(merged) + "\n", encoding="utf-8")
    return len(merged) - len(a)


def reconcile(root: Path = HERE) -> list[str]:
    """Pick the newer copy of each tracker. Returns annotation lines."""
    notes = []
    stash_dir = root / STASH
    for name, field in TRACKERS.items():
        live, repo = root / name, stash_dir / name
        cached, committed = _read(live), _read(repo)
        if cached is None and committed is None:
            notes.append(f"::warning title=Tracker starts empty::{name} was in neither the "
                         f"cache nor the repository; it starts from an empty baseline today")
            continue
        if _age_key(committed, field) > _age_key(cached, field):
            why = ("missing from the cache" if not live.exists()
                   else "unreadable in the cache" if cached is None
                   else "older in the cache")
            shutil.copy2(repo, live)
            notes.append(f"::notice title=Tracker restored from the repository::{name} was "
                         f"{why}; using the committed copy ({field} {committed.get(field)})")
    added = _merge_metrics(root / METRICS, stash_dir / METRICS)
    if added:
        notes.append(f"::notice title=Metrics merged::{added} row(s) of metrics.jsonl were "
                     f"in the repository but not the cache, and were kept")
    return notes


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "stash":
        print(f"Committed state kept aside: {', '.join(stash()) or 'none'}")
        return 0
    if cmd == "reconcile":
        for line in reconcile():
            print(line)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
