"""The recurring Korea calendar, computed rather than remembered.

Upcoming shipped empty. Before that it shipped past-dated entries. Both came
from the same arrangement: a list of one-off dates written into the prompt,
which went stale, plus a hard minimum telling the model to fill the section
anyway. Told to produce four events from an exhausted list, a model invents
them; told not to invent, it produces none.

Recurring dates do not need a model at all. Liberation Day is 15 August every
year. The party founding anniversary is 10 October. These are arithmetic, so
they are computed here and merged with whatever dated events the model found
in today's articles. The section is populated from facts either way, and a
date from this file cannot be wrong about the year, because it is derived from
today's date rather than recalled.

What is deliberately NOT here: anything that moves. Rate decisions, summits,
exercise start dates and statutory deadlines shift, so they must come from an
article that states them. A fixed anniversary is safe to compute; a scheduled
event is not.
"""
from __future__ import annotations

from datetime import date, timedelta

# (month, day, headline, detail). Fixed observances only — nothing that can be
# rescheduled. Keep this list short and certain; it is the floor, not the
# whole calendar.
RECURRING: list[tuple[int, int, str, str]] = [
    (1, 1, "Kim Jong Un New Year message",
     "Plenum readout sets the DPRK's stated line for the year."),
    (2, 16, "Day of the Shining Star",
     "Kim Jong Il's birthday. DPRK national holiday."),
    (3, 1, "Samiljeol (3·1 Independence Movement Day)",
     "ROK national holiday. Presidential address often addresses Japan ties."),
    (4, 15, "Day of the Sun",
     "Kim Il Sung's birthday, the largest DPRK anniversary. Parades possible."),
    (6, 6, "ROK Memorial Day (현충일)", "National day of remembrance."),
    (6, 25, "Korean War outbreak anniversary", "War began 25 June 1950."),
    (7, 27, "Korean War armistice anniversary",
     "Signed 27 July 1953. The DPRK marks it as Victory Day."),
    (8, 15, "Liberation Day (광복절)",
     "ROK national holiday. The presidential address is a set-piece on Japan "
     "policy and unification."),
    (9, 9, "DPRK founding day",
     "Parades and weapons displays have historically clustered on this date."),
    (10, 3, "National Foundation Day (개천절)", "ROK national holiday."),
    (10, 9, "Hangul Day (한글날)", "ROK national holiday."),
    (10, 10, "Workers' Party founding day",
     "Historically accompanied by military displays."),
    (12, 17, "Kim Jong Il death anniversary",
     "Mourning period; KCNA output typically drops."),
]

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _next_occurrence(month: int, day: int, today: date) -> date:
    """The next time this month/day falls, today included."""
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:              # 29 February in a common year
            continue
        if candidate >= today:
            return candidate
    return date(today.year + 1, month, day)


def upcoming(today: date | None = None, days: int = 30) -> list[dict]:
    """Recurring observances falling within the window, soonest first.

    Shaped like the model's own calendar_watch items so the renderer needs no
    special case.
    """
    today = today or date.today()
    horizon = today + timedelta(days=days)
    out = []
    for month, day, headline, detail in RECURRING:
        when = _next_occurrence(month, day, today)
        if today <= when <= horizon:
            out.append({
                "month": _MONTHS[when.month - 1],
                "day": when.day,
                "headline": headline,
                "detail": detail,
                "_source": "recurring",
                "_date": when.isoformat(),
            })
    return sorted(out, key=lambda item: item["_date"])


def merge(model_items: list | None, today: date | None = None,
          days: int = 30, limit: int = 5) -> list[dict]:
    """Combine the model's dated events with the computed observances.

    The model's items come first: an event it found in today's reporting is
    more informative than an anniversary anyone could look up. Recurring dates
    fill the remaining slots so the section is never empty, and are skipped
    when the model already reported the same day.
    """
    today = today or date.today()
    merged: list[dict] = []
    seen_days: set[tuple[str, int]] = set()

    for item in (model_items or []):
        if not isinstance(item, dict):
            continue
        headline = str(item.get("headline") or "").strip()
        if not headline:
            continue
        merged.append(item)
        month = str(item.get("month") or "").strip()[:3]
        try:
            seen_days.add((month, int(item.get("day"))))
        except (TypeError, ValueError):
            pass

    for item in upcoming(today, days):
        if len(merged) >= limit:
            break
        if (item["month"], item["day"]) in seen_days:
            continue
        merged.append(item)

    # A calendar reads in date order. Items the model dated with a month and
    # day sort by that; anything it left undated keeps its position at the end
    # rather than being dropped.
    def _key(item: dict) -> tuple:
        if item.get("_date"):
            return (0, item["_date"])
        month = str(item.get("month") or "").strip()[:3].title()
        try:
            m = _MONTHS.index(month) + 1
            d = int(item.get("day"))
        except (ValueError, TypeError):
            return (1, "")
        return (0, _next_occurrence(m, d, today).isoformat())

    return sorted(merged, key=_key)[:limit]
