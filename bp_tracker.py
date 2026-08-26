"""
Beyond Parallel Locations Tracker
Persistent tracking of monitored facility status across digest runs.
Carries forward last_source_date dates and status so Claude doesn't have to invent them.
"""
import json
import re
from pathlib import Path
from datetime import datetime, timezone

TRACKER_FILE = Path(__file__).parent / "bp_tracker.json"


def _scrub_note(note: str) -> str:
    """Strip the known-fabricated 'Aug 2026 seismic event at Punggye-ri assessed
    as a nuclear test' sentence. No such event occurred — it was an AI
    fabrication that polluted the cached tracker and carried forward daily. Real
    content (DIA Tunnel 3 assessment, defector study, readiness) is preserved."""
    if not note:
        return note
    parts = re.split(r'(?<=[.!?])\s+', note)
    kept = [s for s in parts
            if not (re.search(r'seismic event', s, re.I)
                    and re.search(r'nuclear test|possible.*\btest\b', s, re.I))]
    return " ".join(kept).strip()


def _scrub_known_false(data: dict) -> dict:
    """Self-heal the tracker on load: remove known-fabricated content and
    downgrade a facility 'alert' that rested solely on it. Targeted at the
    Punggye-ri seismic-event fabrication; safe no-op otherwise."""
    locs = data.get("locations") or {}
    p = locs.get("Punggye-ri Nuclear Test Site")
    if p and "seismic event" in (p.get("note") or "").lower():
        cleaned = _scrub_note(p["note"])
        if cleaned != p.get("note"):
            p["note"] = cleaned
            if str(p.get("status", "")).lower() == "alert":
                p["status"] = "activity"
                p["direction"] = ""
    return data

# The 11 monitored locations
DEFAULT_LOCATIONS = [
    {"name": "Yongbyon Nuclear Complex", "status": "elevated", "note": "Apr 2026: Suspected uranium enrichment building (previously observed under construction in late 2025 near the centrifuge enrichment facility) is now complete — expanding DPRK enrichment capacity. 5 MWe reactor and IRT-2000 research reactor both operating; thermal cladding still observed on existing centrifuge facility roof.", "last_source_date": "2026-04", "direction": "up"},
    {"name": "Sinpo South Shipyard", "status": "activity", "note": "Apr 2026: Sinpo-B SSB drydocked at Sinpo South Shipyard as of Apr 15; Hero Kim Kun Ok SLBM submarine (Sinpo-C) not yet operational. Cargo vessel conversion/repurposing activity also observed. New submarine construction ongoing in separate bay.", "last_source_date": "2026-04", "direction": "up"},
    {"name": "THAAD Site — Seongju County", "status": "activity", "note": "Mar 2026: All 6 THAAD launchers redeployed to Middle East amid Iran tensions. At least 2 launchers may have returned to Seongju by late Mar 2026. Battery operational status uncertain.", "last_source_date": "2026-03", "direction": "down"},
    {"name": "Sohae Satellite Launch Station", "status": "elevated", "note": "Mar 2026: Kim Jong Un oversaw successful 2,500 kN solid-fuel engine test at Sohae (Mar 28-29). Two nearby villages razed for facility expansion (Mar 2026). New seaport and large assembly building construction progressing.", "last_source_date": "2026-03", "direction": "up"},
    {"name": "Punggye-ri Nuclear Test Site", "status": "activity", "note": "Nov 2025: ROK DIA assessed Tunnel No. 3 is test-ready and a nuclear test can be conducted at any time upon political decision. Site maintained at high readiness since mid-2024.", "last_source_date": "2025-11", "direction": "up"},
    {"name": "Tumangang–Khasan (NK-Russia border)", "status": "activity", "note": "2025-2026: New road bridge under construction at Tumangang-Khasan crossing — completion timeline accelerated from Dec 2026 to Summer 2026. Passenger rail service resumed mid-2025. Ore and tank car traffic increasing.", "last_source_date": "2026-03", "direction": "up"},
    {"name": "Sinuiju–Dandong (NK-China border)", "status": "activity", "note": "Mar 12, 2026: Cross-border passenger train service resumed between Sinuiju and Dandong after COVID-era suspension. New Yalu River Bridge may open in 2026.", "last_source_date": "2026-03-12", "direction": "up"},
    {"name": "Rason SEZ", "status": "activity", "note": "Nov 2025: Chinese businesspeople re-entry to Rason SEZ expanded. Coal exports through Rason at highest levels in years throughout 2025. Arms export berth also active (see Vostochny entry).", "last_source_date": "2025-11", "direction": "up"},
    {"name": "Yellow Sea NLL", "status": "normal", "note": "Sep 26, 2025: 140m DPRK merchant vessel Toksong crossed NLL near Baengnyeong Island, advanced 5km south. ROK Navy fired ~60 warning shots; vessel retreated after 1 hour. Ship switched AIS nationality to China and flew Chinese flag. First NLL intrusion in three years.", "last_source_date": "2025-09-26", "direction": ""},
    {"name": "Yellow Sea PMZ", "status": "activity", "note": "Atlantic Amsterdam (converted oil rig, Chinese aquaculture platform) relocated out of PMZ Jan 27-28, 2026 to Weihai shipyard following Lee Jae-myung Beijing state visit. Two giant aquaculture cages (Shen Lan 1, Shen Lan 2) and 13 buoys remain in the PMZ.", "last_source_date": "2026-01-28", "direction": "down"},
    {"name": "Vostochny/Dunai (Russian Far East)", "status": "activity", "note": "Jan 2026: Arms shipments slowed due to ice — one Russian vessel (likely Angara or Lady R) visited Rason, docked Jan 14 at arms export berth. Cargo routed to Vostochny. Since Sep 2023: 64 voyages by 4 vessels (Angara, Maria, Maya-1, Lady R) delivered ~15,800 containers (~4.2-5.8M munitions) from Rajin to Vostochny/Dunai.", "last_source_date": "2026-01", "direction": "up"},
]


def _load() -> dict:
    if TRACKER_FILE.exists():
        try:
            return _scrub_known_false(json.loads(TRACKER_FILE.read_text()))
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
        note = _scrub_note(loc.get("note", ""))
        status = loc.get("status", "normal")
        # If scrubbing removed the fabricated seismic claim that was the basis of
        # an alert, don't persist the alert.
        if (str(status).lower() == "alert" and "seismic event" in (loc.get("note") or "").lower()
                and "seismic event" not in note.lower()):
            status = "activity"
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
                "last_source_date": loc.get("last_source_date", (existing or {}).get("last_source_date", "unknown")),
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
        last = loc.get("last_source_date", "unknown")
        direction = loc.get("direction", "")
        dir_str = f" (trending: {direction})" if direction else ""
        lines.append(f"  - {name}: [{status}]{dir_str} — {note} (last report: {last})")

    return "\n".join(lines)
