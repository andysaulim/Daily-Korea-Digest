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


# ── Relative dates in carried-forward notes ─────────────────────────────────
# A note is copied forward verbatim for weeks. "Earlier this week" written in
# April still said "earlier this week" in October, and read as news. Each
# relative phrase is pinned to the note's own report date; where that date is
# unknown the note is flagged for the model instead.
_MON = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_RELATIVE_RE = re.compile(
    r"\b(earlier this week|this week|last week|this month|last month|this year|"
    r"yesterday|today|this morning|tonight)\b", re.I)


def _report_date(last_source_date) -> tuple[int, int, int | None] | None:
    """(year, month, day-or-None) from '2026-04', '2026-03-12' or 'Mar 12, 2026'."""
    s = str(last_source_date or "").strip()
    m = re.match(r"(\d{4})-(\d{1,2})(?:-(\d{1,2}))?", s)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else None
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%b %Y", "%B %Y"):
        try:
            d = datetime.strptime(s, fmt)
            return d.year, d.month, (d.day if "%d" in fmt else None)
        except ValueError:
            continue
    return None


def absolutize_note(note: str, last_source_date) -> tuple[str, bool]:
    """(note with relative time words pinned to the report date, still_relative).

    still_relative is True when the note has relative words that could not be
    pinned because the report date is unknown.
    """
    if not note or not _RELATIVE_RE.search(note):
        return note, False
    rd = _report_date(last_source_date)
    if not rd:
        return note, True
    y, mo, d = rd
    month = f"{_MON[mo - 1]} {y}"
    prev = f"{_MON[(mo - 2) % 12]} {y if mo > 1 else y - 1}"
    day = f"{_MON[mo - 1]} {d}, {y}" if d else None

    def sub(m: re.Match) -> str:
        w = m.group(1).lower()
        if w in ("this month",):
            return f"in {month}"
        if w == "last month":
            return f"in {prev}"
        if w == "this year":
            return f"in {y}"
        if w in ("earlier this week", "this week"):
            return f"the week of {day}" if day else f"in {month}"
        if w == "last week":
            return f"the week before {day}" if day else f"in {month}"
        if w == "yesterday" and d:
            try:
                from datetime import date, timedelta
                yd = date(y, mo, d) - timedelta(days=1)
                return f"on {_MON[yd.month - 1]} {yd.day}, {yd.year}"
            except ValueError:
                pass
        return f"on {day}" if day else f"in {month}"
    return _RELATIVE_RE.sub(sub, note), False


def absolutize_digest_notes(digest: dict) -> list[str]:
    """Pin relative dates in the digest's bp_locations notes. Returns log lines."""
    log = []
    for loc in digest.get("bp_locations") or []:
        if not isinstance(loc, dict) or not loc.get("note"):
            continue
        new, _ = absolutize_note(loc["note"], loc.get("last_source_date"))
        if new != loc["note"]:
            log.append(f"  - {loc.get('name', '?')}: {loc['note'][:60]!r} -> {new[:60]!r}")
            loc["note"] = new
    return log


def _stale(last_source_date, today=None) -> bool:
    """True when the last report is more than six months old."""
    rd = _report_date(last_source_date)
    if not rd:
        return False
    today = today or datetime.now(timezone.utc).date()
    return (today.year - rd[0]) * 12 + (today.month - rd[1]) > 6


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
            last = loc.get("last_source_date", (existing or {}).get("last_source_date", "unknown"))
            kept_note = note if has_substance else (existing or {}).get("note", "No new reporting")
            data["locations"][name] = {
                "name": name,
                "status": status,
                # Stored with absolute dates, since it will be carried forward.
                "note": absolutize_note(kept_note, last)[0],
                "last_source_date": last,
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
        "report, or news article) with new information. When carrying a note "
        "forward, replace relative time words with absolute dates.\n"
    )

    for name, loc in locs.items():
        status = loc.get("status", "normal")
        last = loc.get("last_source_date", "unknown")
        note, relative = absolutize_note(loc.get("note", "No new reporting"), last)
        direction = loc.get("direction", "")
        dir_str = f" (trending: {direction})" if direction else ""
        flags = ""
        if relative:
            flags += " [note uses relative time words and has no report date: state them as dates or drop them]"
        if _stale(last):
            flags += " [last report over six months old: present it as dated, not as the current state]"
        lines.append(f"  - {name}: [{status}]{dir_str} — {note} (last report: {last}){flags}")

    return "\n".join(lines)
