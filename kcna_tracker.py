"""
KCNA Rhetoric Tracker
Persistent tracking of KCNA rhetoric data across digest runs.
Stores daily phrase counts, propaganda focus, output volume, and tone shifts
so the digest prompt can include real historical data instead of hallucinated baselines.
"""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

TRACKER_FILE = Path(__file__).parent / "kcna_tracker.json"
MAX_DAYS = 14  # keep 2 weeks of history


def _load() -> dict:
    """Load tracker data from disk."""
    if TRACKER_FILE.exists():
        try:
            return json.loads(TRACKER_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {"days": [], "last_updated": None}


def _save(data: dict):
    """Save tracker data to disk."""
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    TRACKER_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _normalize_date(date_str: str) -> str:
    """Normalize various date formats to YYYY-MM-DD."""
    for fmt in ("%Y-%m-%d", "%A, %B %d, %Y", "%A, %d %B %Y", "%B %d, %Y",
                "%d %B %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str  # return as-is if we can't parse


def update_from_digest(digest: dict):
    """Extract KCNA delta from a completed digest and persist it."""
    kcna = digest.get("kcna_delta") or {}
    if not kcna or not any(kcna.values()):
        return

    date_str = _normalize_date(digest.get("digest_date", ""))
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Build the day record
    day_record = {
        "date": date_str,
        "output_volume": kcna.get("output_volume"),
        "propaganda_focus": kcna.get("propaganda_focus") or [],
        "tone_shift": kcna.get("tone_shift"),
        "doctrinal_shift": kcna.get("doctrinal_shift"),
        "silence_today": kcna.get("silence_today", False),
        "watch_flag": kcna.get("watch_flag", False),
        "notable_omissions": kcna.get("notable_omissions"),
        "bottom_line": kcna.get("bottom_line"),
        "key_phrases": {},  # phrase -> count mapping for this day
    }

    # Extract phrase counts from key_phrase_changes
    for p in (kcna.get("key_phrase_changes") or []):
        phrase = p.get("phrase", "")
        count = p.get("count_this_week", 0)
        if phrase:
            day_record["key_phrases"][phrase] = count

    # Extract key quote if present
    quotes = kcna.get("key_quotes") or []
    if quotes:
        q = quotes[0]
        day_record["key_quote"] = q.get("quote", "")
        day_record["key_quote_source"] = q.get("source_article", "")

    data = _load()

    # Replace if same date exists, otherwise append
    data["days"] = [d for d in data["days"] if d.get("date") != date_str]
    data["days"].append(day_record)

    # Sort by date descending and trim to MAX_DAYS
    data["days"].sort(key=lambda d: d.get("date", ""), reverse=True)
    data["days"] = data["days"][:MAX_DAYS]

    _save(data)


def get_recent_days(limit: int = 7) -> list:
    """Return the most recent day records (newest first)."""
    data = _load()
    return sorted(data["days"], key=lambda d: d.get("date", ""), reverse=True)[:limit]


def build_context_block() -> str:
    """Build a context string for the digest prompt with KCNA rhetoric history.

    This gives Claude real data for phrase frequency comparisons
    instead of relying on hallucinated baselines.
    """
    recent = get_recent_days(7)
    if not recent:
        return ""

    lines = ["KCNA RHETORIC HISTORY (from persistent tracker — last 7 days):"]
    lines.append("Use this as ground truth for phrase frequency comparisons. "
                 "Do NOT invent 'count_prior' numbers — use the actual counts below.\n")

    for day in recent:
        date = day.get("date", "unknown")
        vol = day.get("output_volume", "unknown")
        silence = day.get("silence_today", False)
        watch = day.get("watch_flag", False)
        focus = day.get("propaganda_focus") or []
        tone = day.get("tone_shift")
        doctrinal = day.get("doctrinal_shift")
        omissions = day.get("notable_omissions")
        bottom = day.get("bottom_line", "")
        phrases = day.get("key_phrases") or {}

        flags = []
        if silence:
            flags.append("SILENCE")
        if watch:
            flags.append("WATCH")
        flag_str = f" [{', '.join(flags)}]" if flags else ""

        lines.append(f"--- {date}{flag_str} ---")
        lines.append(f"  Volume: {vol}")
        if focus:
            lines.append(f"  Focus: {', '.join(str(f) for f in focus)}")
        if tone:
            lines.append(f"  Tone shift: {tone}")
        if doctrinal:
            lines.append(f"  Doctrinal: {doctrinal}")
        if omissions:
            lines.append(f"  Omissions: {omissions}")
        if phrases:
            phrase_strs = [f"{ph}: {ct}" for ph, ct in phrases.items()]
            lines.append(f"  Phrases: {'; '.join(phrase_strs)}")
        if bottom:
            lines.append(f"  Bottom line: {bottom}")
        lines.append("")

    # Compute aggregate phrase frequencies across the window
    all_phrases: dict[str, list[int]] = {}
    for day in recent:
        for ph, ct in (day.get("key_phrases") or {}).items():
            if ph not in all_phrases:
                all_phrases[ph] = []
            all_phrases[ph].append(ct)

    if all_phrases:
        lines.append("AGGREGATE PHRASE COUNTS (last 7 days):")
        for ph, counts in sorted(all_phrases.items(), key=lambda x: sum(x[1]), reverse=True):
            total = sum(counts)
            days_seen = len(counts)
            lines.append(f"  \"{ph}\": total {total} mentions across {days_seen} day(s)")
        lines.append("")
        lines.append("For key_phrase_changes: set count_prior to the ACTUAL total from the days "
                     "BEFORE today in this tracker. Set count_this_week to today's count from "
                     "the KCNA articles you are processing now. The delta_label should reflect "
                     "the real change.")

    return "\n".join(lines)
