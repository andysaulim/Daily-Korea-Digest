"""Approval-rating history for the Korea Daily Brief.

gallup_baseline.json holds a single snapshot — the current approved poll — so
the brief could print "40%" but never "40%, down from 51% in July". Readers
judge a trend, not a number.

This module keeps an append-only series alongside the baseline. Both writers
(gallup_update.py's weekly fetch and run.py's persist-from-digest) call
`record()` whenever the baseline advances to a newer survey. One point per
survey date; re-recording the same survey is a no-op, so a re-run cannot
inflate the series.

The series lives inside gallup_baseline.json under "history" rather than in a
separate file, because that file is already committed back to the repo by the
workflow and so survives the Actions cache being cleared.
"""
from __future__ import annotations

import json
from pathlib import Path

BASELINE_PATH = Path(__file__).parent / "gallup_baseline.json"

# Enough points to show a trend without turning the sparkline into noise.
MAX_POINTS = 26
# Below this the shape is meaningless, so the brief renders no sparkline.
MIN_POINTS_TO_RENDER = 3


def _load() -> dict:
    try:
        return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _pct(value) -> float | None:
    """'40%' or 40 -> 40.0. Returns None for anything unparseable."""
    if value is None:
        return None
    try:
        return float(str(value).strip().rstrip("%").strip())
    except (TypeError, ValueError):
        return None


def history() -> list[dict]:
    """The recorded series, oldest first. Never raises."""
    series = _load().get("history")
    if not isinstance(series, list):
        return []
    out = []
    for point in series:
        if isinstance(point, dict) and _pct(point.get("approval")) is not None:
            out.append(point)
    out.sort(key=lambda p: str(p.get("date", "")))
    return out


def delta() -> tuple[float, str] | None:
    """Change in approval from the previous survey to the latest, and its date.

    Returns (points_change, previous_survey_label) or None when fewer than two
    surveys are on record. The renderer showed a bare up/down arrow taken from
    the model's own `trend` field: direction with no magnitude, and no way to
    tell which survey it was measured against. This is the arithmetic, from
    the series the pipeline already stores.
    """
    series = history()
    if len(series) < 2:
        return None
    latest, prior = series[-1], series[-2]
    a, b = _pct(latest.get("approval")), _pct(prior.get("approval"))
    if a is None or b is None:
        return None
    return round(a - b, 1), str(prior.get("label") or prior.get("date") or "")


def record(sort_key: str, approval, label: str = "",
           baseline: dict | None = None) -> dict | None:
    """Append one point if `sort_key` is a survey we have not recorded.

    Returns the stored point, or None when nothing was added. Callers hold the
    baseline dict they are about to write, so pass it in and this returns the
    updated dict for them to write once — avoiding a read-modify-write race
    between the two writers.
    """
    value = _pct(approval)
    if not sort_key or value is None:
        return None
    data = baseline if baseline is not None else _load()
    series = [p for p in (data.get("history") or []) if isinstance(p, dict)]
    if any(str(p.get("date", "")) == sort_key for p in series):
        return None
    point = {"date": sort_key, "approval": value}
    if label:
        point["label"] = label
    series.append(point)
    series.sort(key=lambda p: str(p.get("date", "")))
    data["history"] = series[-MAX_POINTS:]
    return point


def sparkline_html(color: str = "#0052B4", width_px: int = 108,
                   height_px: int = 26) -> str:
    """A table-based sparkline of the approval series.

    Deliberately not inline SVG: Outlook strips it. This is a row of table
    cells with a coloured block sized by value, which every mail client
    renders. Returns "" when there are too few points to mean anything.
    """
    series = history()
    if len(series) < MIN_POINTS_TO_RENDER:
        return ""
    values = [_pct(p["approval"]) for p in series]
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    bar_w = max(2, int(width_px / max(len(values), 1)) - 1)
    cells = ""
    for i, v in enumerate(values):
        # Scale into the box, keeping a 3px floor so a low point stays visible.
        h = 3 + int((v - lo) / span * (height_px - 4))
        last = i == len(values) - 1
        fill = color if last else "#B9C6DA"
        cells += (f'<td style="padding:0 1px 0 0;vertical-align:bottom;">'
                  f'<div style="width:{bar_w}px;height:{h}px;background:{fill};'
                  f'font-size:0;line-height:0;">&nbsp;</div></td>')
    first_label = series[0].get("label") or str(series[0].get("date", ""))[:7]
    return (f'<table cellpadding="0" cellspacing="0" border="0" '
            f'style="height:{height_px}px;"><tr>{cells}</tr>'
            f'<tr><td colspan="{len(values)}" style="padding-top:3px;'
            f'font-family:Arial,sans-serif;font-size:9px;color:#9AA3AE;'
            f'white-space:nowrap;">{values[0]:g}% since {first_label} '
            f'&rarr; {values[-1]:g}%</td></tr></table>')
