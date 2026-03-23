"""
Beyond Parallel Locations Tracker
Persistent tracking of monitored facility status across digest runs.
Carries forward last_report dates and status so Claude doesn't have to invent them.
"""
import json
from pathlib import Path
from datetime import datetime, timezone

TRACKER_FILE = Path(__file__).parent / "bp_tracker.json"

# The 8 monitored locations
DEFAULT_LOCATIONS = [
    {"name": "Yongbyon Nuclear Complex", "status": "normal", "note": "No new reporting", "last_report": "unknown", "direction": ""},
    {"name": "Sinpo South Shipyard", "status": "normal", "note": "No new reporting", "last_report": "unknown", "direction": ""},
    {"name": "THAAD Site — Seongju County", "status": "normal", "note": "No new reporting", "last_report": "unknown", "direction": ""},
    {"name": "Sohae Satellite Launch Station", "status": "normal", "note": "No new reporting", "last_report": "unknown", "direction": ""},
    {"name": "Punggye-ri Nuclear Test Site", "status": "normal", "note": "No new reporting", "last_report": "unknown", "direction": ""},
    {"name": "Tumangang–Khasan (NK-Russia border)", "status": "normal", "note": "No new reporting", "last_report": "unknown", "direction": ""},
    {"name": "Sinuiju–Dandong (NK-China border)", "status": "normal", "note": "No new reporting", "last_report": "unknown", "direction": ""},
    {"name": "Rason SEZ", "status": "normal", "note": "No new reporting", "last_report": "unknown", "direction": ""},
]


def _load() -> dict:
    if TRACKER_FILE.exists():
        try:
            return json.loads(TRACKER_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {"locations": {loc["name"]: loc for loc in DEFAULT_LOCATIONS}, "last_updated": None}


def _save(data: dict):
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    TRACKER_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def update_from_digest(digest: dict):
    """Extract bp_locations from digest and persist any updates."""
    locations = digest.get("bp_locations") or []
    if not locations:
        return

    data = _load()
    for loc in locations:
        name = loc.get("name", "")
        if not name:
            continue
        note = loc.get("note", "")
        status = loc.get("status", "normal")
        existing = data["locations"].get(name)

        # Accept the update if:
        # 1. There's a substantive note (not "no new reporting"), OR
        # 2. The location is new to the tracker, OR
        # 3. The status changed from what we had before
        has_substance = note and "no new reporting" not in note.lower()
        is_new = existing is None
        status_changed = existing and existing.get("status", "normal") != status

        if has_substance or is_new or status_changed:
            data["locations"][name] = {
                "name": name,
                "status": status,
                "note": note if has_substance else (existing or {}).get("note", "No new reporting"),
                "last_report": loc.get("last_report", (existing or {}).get("last_report", "unknown")),
                "direction": loc.get("direction", ""),
            }

    _save(data)


def build_context_block() -> str:
    """Build context for the digest prompt with last-known facility status."""
    data = _load()
    locs = data.get("locations", {})
    if not locs:
        return ""

    lines = ["BP LOCATIONS HISTORY (last known status from persistent tracker):"]
    lines.append(
        "CARRY-FORWARD RULE: For each location, copy the note and status below "
        "VERBATIM into your bp_locations output UNLESS today's articles contain a "
        "specific newer report about that facility. NEVER replace a substantive "
        "note with 'No new reporting' — the tracker's note IS the most recent "
        "known status and must be preserved for readers. Only update a location's "
        "note when you have a concrete new source (satellite imagery, think tank "
        "report, or news article) with new information.\n"
    )

    for name, loc in locs.items():
        status = loc.get("status", "normal")
        note = loc.get("note", "No new reporting")
        last = loc.get("last_report", "unknown")
        direction = loc.get("direction", "")
        dir_str = f" (trending: {direction})" if direction else ""
        lines.append(f"  - {name}: [{status}]{dir_str} — {note} (last report: {last})")

    return "\n".join(lines)
