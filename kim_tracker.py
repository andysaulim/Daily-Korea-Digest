"""
Kim Jong Un Appearance Tracker
Persistent tracking of confirmed Kim Jong Un public appearances across digest runs.
"""
import json
from pathlib import Path
from datetime import datetime, timezone

TRACKER_FILE = Path(__file__).parent / "kim_tracker.json"


def _load() -> dict:
    """Load tracker data from disk."""
    if TRACKER_FILE.exists():
        return json.loads(TRACKER_FILE.read_text())
    return {"appearances": [], "last_updated": None}


def _save(data: dict):
    """Save tracker data to disk."""
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    TRACKER_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def get_recent_appearances(limit: int = 10) -> list:
    """Return the most recent confirmed appearances (newest first)."""
    data = _load()
    return sorted(data["appearances"], key=lambda x: x["date"], reverse=True)[:limit]


def get_last_appearance() -> dict | None:
    """Return the most recent confirmed appearance, or None."""
    recent = get_recent_appearances(1)
    return recent[0] if recent else None


def days_since_last_appearance() -> int | None:
    """Calculate days since last confirmed appearance."""
    last = get_last_appearance()
    if not last:
        return None
    try:
        last_date = datetime.strptime(last["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - last_date
        return delta.days
    except (ValueError, KeyError):
        return None


def record_appearance(date_str: str, activity: str, source: str):
    """Record a confirmed Kim Jong Un appearance. Deduplicates by date."""
    data = _load()
    existing_dates = {a["date"] for a in data["appearances"]}
    if date_str not in existing_dates:
        data["appearances"].append({
            "date": date_str,
            "activity": activity,
            "source": source,
        })
        _save(data)
        return True
    return False


def update_from_digest(digest: dict):
    """Extract Kim appearance data from a completed digest and persist it."""
    kcna = digest.get("kcna_delta") or {}
    if kcna.get("kim_appearance_today"):
        date_str = digest.get("digest_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        # Normalize date format (handle "Sunday, 22 March 2026" etc.)
        for fmt in ("%Y-%m-%d", "%A, %d %B %Y", "%d %B %Y", "%B %d, %Y"):
            try:
                parsed = datetime.strptime(date_str, fmt)
                date_str = parsed.strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
        activity = kcna.get("kim_activity", "Public appearance reported")
        record_appearance(date_str, activity, "KCNA digest")


def build_context_block() -> str:
    """Build a context string for the digest prompt with Kim appearance history."""
    recent = get_recent_appearances(10)
    days = days_since_last_appearance()

    if not recent:
        return "No Kim Jong Un appearance records in tracker. Determine from articles."

    lines = ["CONFIRMED KIM JONG UN APPEARANCES (from persistent tracker):"]
    for a in recent:
        lines.append(f"  - {a['date']}: {a['activity']} (source: {a['source']})")

    if days is not None:
        lines.append(f"\nDAYS SINCE LAST CONFIRMED APPEARANCE: {days}")
        lines.append("Use this as ground truth for days_since_last_appearance. Only override if today's articles confirm a MORE RECENT appearance.")
    return "\n".join(lines)
