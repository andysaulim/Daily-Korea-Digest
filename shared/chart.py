"""Table-based charts for the CSIS daily briefs.

Deliberately not inline SVG and not a generated image. Outlook strips SVG, and
mail clients block remote images by default — a blocked chart is a broken
chart. Everything here is nested tables with background colours, which every
client on the planet renders, including in dark mode and in print.

The module is generic: it draws a series someone else selected. Which series is
worth showing on a given day is an editorial judgement that belongs to each
edition, not here.
"""
from __future__ import annotations

__all__ = ["column_chart", "MIN_POINTS"]

# Below this a chart is decoration, not information.
MIN_POINTS = 3


def _esc(text) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _num(value) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip().rstrip("%").replace(",", ""))
    except (TypeError, ValueError):
        return None


def column_chart(points, *, accent: str, title: str = "", note: str = "",
                 height_px: int = 72, value_suffix: str = "",
                 highlight_last: bool = True) -> str:
    """Render a labelled column chart.

    `points` is a sequence of (label, value). Values that will not parse as a
    number are dropped rather than rendered as zero, because a false zero in a
    chart reads as a real reading of zero.

    Returns "" when there is too little to draw. Callers append the result
    directly, so an empty string simply means no section.
    """
    cleaned = [(str(lab), _num(val)) for lab, val in (points or [])]
    cleaned = [(lab, val) for lab, val in cleaned if val is not None]
    if len(cleaned) < MIN_POINTS:
        return ""

    values = [v for _, v in cleaned]
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    # Floor of 6px so the smallest column is still visibly a column.
    def _h(v: float) -> int:
        return 6 + int((v - lo) / span * (height_px - 6))

    cells, labels = "", ""
    for i, (label, value) in enumerate(cleaned):
        last = highlight_last and i == len(cleaned) - 1
        fill = accent if last else "#C3CEDE"
        value_txt = f"{value:g}{value_suffix}"
        cells += (
            f'<td valign="bottom" align="center" style="padding:0 2px;">'
            f'<div style="font-family:Arial,sans-serif;font-size:9px;'
            f'color:{"#33383F" if last else "#9AA3AE"};padding-bottom:3px;'
            f'white-space:nowrap;">{_esc(value_txt)}</div>'
            f'<div style="height:{_h(value)}px;background:{fill};'
            f'font-size:0;line-height:0;">&nbsp;</div></td>')
        labels += (
            f'<td align="center" style="padding:4px 2px 0;font-family:Arial,sans-serif;'
            f'font-size:9px;color:#9AA3AE;white-space:nowrap;">{_esc(label)}</td>')

    head = ""
    if title:
        head = (f'<div style="font-family:Arial,sans-serif;font-size:10px;'
                f'font-weight:700;text-transform:uppercase;letter-spacing:1.5px;'
                f'color:{accent};margin-bottom:9px;">{_esc(title)}</div>')
    foot = ""
    if note:
        foot = (f'<div style="font-family:Arial,sans-serif;font-size:11px;'
                f'color:#6B7280;margin-top:8px;line-height:1.45;">{_esc(note)}</div>')
    return (f'{head}<table cellpadding="0" cellspacing="0" border="0" width="100%">'
            f'<tr>{cells}</tr><tr>{labels}</tr></table>{foot}')
