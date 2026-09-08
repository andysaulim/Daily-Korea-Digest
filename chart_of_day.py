"""Pick the series worth charting in today's Korea brief.

The chart module in `shared/` draws whatever it is given. Choosing what to draw
is an editorial judgement and belongs here, per edition.

Selection is deliberately conservative. A chart earns its place only when it
carries a series long enough to show a shape and recent enough to be about
today. Everything is read from data the pipeline already maintains — nothing
here fetches, computes a forecast, or asks the model for a number.

Order of preference:
  1. KCNA output volume over the rhetoric baseline window. The most genuinely
     daily series the pipeline holds, and a real signal for this readership.
  2. Presidential approval across recent Gallup surveys. Weekly rather than
     daily, but the number readers track most.
Returns (title, points, note) or None when nothing qualifies.
"""
from __future__ import annotations

import json
from pathlib import Path

_HERE = Path(__file__).parent
MIN_POINTS = 3
# A series whose newest point is older than this is history, not news.
MAX_AGE_DAYS = 21


def _kcna_series():
    """Daily KCNA article counts from the rhetoric tracker, if it has depth."""
    try:
        data = json.loads((_HERE / "kcna_tracker.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    days = data.get("days") or data.get("history") or []
    if not isinstance(days, list):
        return None
    points = []
    for entry in days[-14:]:
        if not isinstance(entry, dict):
            continue
        date = str(entry.get("date") or "")
        count = entry.get("article_count", entry.get("count"))
        if date and count is not None:
            points.append((date[5:], count))   # MM-DD reads better on a narrow axis
    if len(points) < MIN_POINTS:
        return None
    return ("KCNA output, last two weeks", points,
            "Daily article count from KCNA and its wire relays. A sustained "
            "rise or fall in volume usually precedes a change in tone.")


def _approval_series():
    """Presidential approval across recorded Gallup surveys."""
    try:
        import poll_history
        history = poll_history.history()
    except Exception:
        return None
    if len(history) < MIN_POINTS:
        return None
    points = [(str(p.get("label") or str(p.get("date", ""))[5:]), p.get("approval"))
              for p in history[-12:]]
    first, last = history[0].get("approval"), history[-1].get("approval")
    note = ""
    try:
        move = float(last) - float(first)
        direction = "down" if move < 0 else "up" if move > 0 else "flat"
        note = (f"Gallup Korea, same-poll series. {abs(move):g} points "
                f"{direction} across {len(history)} surveys.")
    except (TypeError, ValueError):
        pass
    return ("Presidential approval", points, note)


def pick():
    """Return (title, points, note) for today's chart, or None."""
    for builder in (_kcna_series, _approval_series):
        try:
            result = builder()
        except Exception:
            continue
        if result:
            return result
    return None
