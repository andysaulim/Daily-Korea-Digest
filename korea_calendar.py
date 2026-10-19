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

import re
from datetime import date, timedelta

# (month, day, headline, detail). Fixed observances only — nothing that can be
# rescheduled. Keep this list short and certain; it is the floor, not the
# whole calendar.
RECURRING: list[tuple[int, int, str, str]] = [
    (1, 1, "Kim Jong Un New Year message",
     "Plenum readout sets the DPRK's stated line for the year."),
    (2, 16, "Day of the Shining Star",
     "Kim Jong Il's birthday. Watch for a Kim Jong Un appearance, a Kumsusan "
     "visit and a heavier KCNA output; round anniversaries have drawn parades."),
    (3, 1, "Samiljeol (3·1 Independence Movement Day)",
     "ROK national holiday. Presidential address often addresses Japan ties."),
    (4, 15, "Day of the Sun",
     "Kim Il Sung's birthday, the largest DPRK anniversary. Parades possible."),
    (6, 6, "ROK Memorial Day (현충일)",
     "Public holiday; markets and ministries closed. The president speaks at "
     "Seoul National Cemetery, usually on alliance and veterans' policy."),
    (6, 25, "Korean War outbreak anniversary",
     "The war began on this date in 1950. Commemorations draw alliance "
     "statements from Seoul and Washington, and DPRK counter-messaging."),
    (7, 27, "Korean War armistice anniversary",
     "Signed 27 July 1953. The DPRK marks it as Victory Day."),
    (8, 15, "Liberation Day (광복절)",
     "ROK national holiday. The presidential address is a set-piece on Japan "
     "policy and unification."),
    (9, 9, "DPRK founding day",
     "Parades and weapons displays have historically clustered on this date."),
    (10, 1, "ROK Armed Forces Day (국군의 날)",
     "Also the anniversary of the ROK-US Mutual Defense Treaty, signed in "
     "Washington on 1 October 1953. Recent years have brought a parade through "
     "central Seoul and new systems shown publicly; alliance statements from "
     "both capitals usually land the same day."),
    (10, 3, "National Foundation Day (개천절)",
     "Public holiday: KRX closed, ministries dark, no Assembly business. "
     "Expect a thin domestic news flow and few primary-source releases."),
    (10, 9, "Hangul Day (한글날)",
     "Public holiday: KRX closed, ministries dark. Falling within a week of "
     "개천절, the two often bracket a slow stretch for government news."),
    (10, 10, "Workers' Party founding day",
     "The party was founded on this date in 1945. Decennial anniversaries "
     "have brought large Kim Il Sung Square parades and new systems shown in "
     "public for the first time; watch pre-event imagery for assembly."),
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


_MONTH_NUM = {m.lower(): i for i, m in enumerate(_MONTHS, 1)}
_DATE_RE = re.compile(
    r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?!\d)"                # Oct 19, not "October 2026"
    r"(?:\s*[-–]\s*(?:([A-Za-z]{3})[a-z]*\.?\s+)?(\d{1,2})(?!\d))?"   # -23 / -Nov 2
    r"(?:,?\s*(\d{4}))?")                                       # , 2026


def _nearest_year(month: int, day: int, today: date) -> date | None:
    """The occurrence of month/day closest to today (an undated "Jan 5" read
    in December is next January; "Oct 10" read on 19 October is this year)."""
    best = None
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            cand = date(year, month, day)
        except ValueError:
            continue
        if best is None or abs((cand - today).days) < abs((best - today).days):
            best = cand
    return best


def normalize(item, today: date | None = None) -> dict | None:
    """One calendar item in the shape every reader uses, or None.

    The prompt never named the fields, so the model returned
    {date, event, detail, source} while merge() and the renderer read
    {month, day, headline}: 26 model items over ten days rendered as none.
    Both shapes are accepted; the result always carries month ("Oct"),
    day (int, first day of a range), headline, detail, source, and the
    ISO start and end dates in _date and _end. An item with no day that can
    be read ("November", "after the midterms") is not a calendar entry and
    returns None.
    """
    if not isinstance(item, dict):
        return None
    today = today or date.today()
    headline = str(item.get("headline") or item.get("event") or "").strip()
    if not headline:
        return None
    start = end = None
    month = str(item.get("month") or "").strip()[:3].lower()
    if month in _MONTH_NUM and str(item.get("day") or "").strip():
        try:
            start = _nearest_year(_MONTH_NUM[month], int(str(item["day"]).split("-")[0]), today)
        except (TypeError, ValueError):
            start = None
        end = start
    if start is None:
        m = _DATE_RE.search(str(item.get("date") or ""))
        if m and m.group(1).lower() in _MONTH_NUM:
            mon, d1 = _MONTH_NUM[m.group(1).lower()], int(m.group(2))
            try:
                start = (date(int(m.group(5)), mon, d1) if m.group(5)
                         else _nearest_year(mon, d1, today))
            except ValueError:
                start = None
            if start and m.group(4):
                emon = _MONTH_NUM.get((m.group(3) or m.group(1)).lower(), mon)
                try:
                    end = date(start.year + (1 if emon < start.month else 0), emon, int(m.group(4)))
                except ValueError:
                    end = start
            else:
                end = start
    if start is None:
        return None
    out = dict(item)
    out.update({
        "month": _MONTHS[start.month - 1],
        "day": start.day,
        "headline": headline,
        "detail": str(item.get("detail") or item.get("note") or "").strip(),
        "source": item.get("source") or "",
        "_date": start.isoformat(),
        "_end": (end or start).isoformat(),
    })
    out.pop("event", None)
    out.pop("note", None)
    return out


# What a US Korea-policy official would not act on. The prompt says so; this
# catches what got through anyway (a KBO playoff game and a commemorative
# stamp both reached the calendar in October 2026).
_OFF_TOPIC = re.compile(
    r"\b(KBO|baseball|football|soccer|playoffs?|semi-playoff|postseason|K League|"
    r"stamps?|K-?pop|concert|idol|drama|film festival|box office|esports?|"
    r"provocation anniversar(?:y|ies))\b", re.I)


def off_topic(item: dict) -> bool:
    text = f'{item.get("headline") or item.get("event") or ""} {item.get("detail") or ""}'
    return bool(_OFF_TOPIC.search(text))


def happening_on(items: list | None, day: date) -> list[dict]:
    """Normalized calendar items whose span includes `day`."""
    out = []
    for item in items or []:
        n = normalize(item, day)
        if n and n["_date"] <= day.isoformat() <= n["_end"]:
            out.append(n)
    return out


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

    for raw in (model_items or []):
        item = normalize(raw, today)
        # Unreadable dates, and events that are already over, are not upcoming.
        if item is None or item["_end"] < today.isoformat() or off_topic(item):
            continue
        merged.append(item)
        seen_days.add((item["month"], item["day"]))

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
