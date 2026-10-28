"""Every number and date in the brief, checked against the article it cites.

The model sees each article as a title and a summary (collect.py caps the
summary at 800 characters; for most Google News items it is little more than
the headline). A figure or a date in the brief that is in none of the
articles an item cites, and not in the reference data the prompt carries
(markets, polling, trackers), did not come from the sources. On 28 October
the brief said the Bank of Korea "held at 2.50%" citing a WSJ story that
said 3.00%, and listed a meeting "next month" as November 1.

`apply` enforces rather than warns:
  * a sentence of body text that carries an unsupported figure is removed;
  * an item whose headline carries one is removed, except a top story,
    which keeps its place and is reported (the lead is never dropped by a
    heuristic);
  * an item left with no body is removed.
Nothing is rewritten: what survives is what the model wrote.

What is not checked: an item whose cited article is not in today's input
(nothing to check it against), integers under 10 written as digits, years,
and quotations. If the pass would remove an implausible share of the brief,
it removes nothing and reports why, so a fault here can never empty an issue.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

# ── What counts as a figure ────────────────────────────────────────────────
_SCALE = {"thousand": 1e3, "million": 1e6, "mn": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "b": 1e9,
          "trillion": 1e12, "tn": 1e12, "t": 1e12, "만": 1e4, "억": 1e8, "조": 1e12}
_NUM = re.compile(
    r"(?<![0-9A-Za-z.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?"           # 1,325.22 / 4.4 / 58
    r"(?:\s?(%|percent|per cent|%p|percentage points?)"          # 3.00% / 13 percent
    r"|\s?(thousand|million|billion|trillion|mn|bn|tn)\b"         # 4.4 million
    r"|(?<=\d)(m|b|t)\b"                                          # $1.5b
    r"|\s?(조|억|만))?", re.I)
_KO_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s?조\s?(\d{1,4})\s?억")  # 1조3800억
_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split())}
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_EN_DATE = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?!\d|,\d)", re.I)
_EN_DATE_DM = re.compile(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\b", re.I)
_KO_DATE = re.compile(r"(?:(\d{1,2})\s?월\s?)?(\d{1,2})\s?일")
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_KO_WEEKDAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
_RELATIVE = re.compile(r"\b(today|yesterday|tomorrow|this week|last week|next week|overnight|earlier)\b|오늘|어제|내일", re.I)


def _value(m: re.Match) -> tuple[float, str] | None:
    whole, frac, pct, scale, short, ko = m.groups()
    try:
        v = float(whole.replace(",", "") + ("." + frac if frac else ""))
    except ValueError:
        return None
    kind = ""
    if pct:
        kind = "pct"
    unit = (scale or short or ko or "").lower()
    if unit:
        v *= _SCALE.get(unit, 1)
    return v, kind


def figures(text: str) -> list[tuple[float, str, str]]:
    """(value, kind, as written) for each figure worth checking in brief text."""
    out = []
    for m in _NUM.finditer(text or ""):
        got = _value(m)
        if not got:
            continue
        v, kind = got
        raw = m.group(0).strip()
        whole = m.group(1).replace(",", "")
        plain = not (m.group(2) or m.group(3) or m.group(4) or m.group(5) or m.group(6))
        if plain and len(whole) == 4 and 1900 <= int(whole) <= 2100:
            continue                                    # a year
        if plain and int(whole) < 10:
            continue                                    # small counts: too noisy to enforce
        # part of a date ("October 21") is checked as a date, not a figure
        tail = text[max(0, m.start() - 12):m.start()]
        if plain and re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+$", tail, re.I):
            continue
        if plain and re.match(r"\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", text[m.end():m.end() + 5], re.I):
            continue
        out.append((v, kind, raw))
    return out


def source_values(text: str) -> list[tuple[float, str]]:
    """Every figure a source text states, in any of the forms the brief may render it."""
    vals = []
    for m in _NUM.finditer(text or ""):
        got = _value(m)
        if got:
            vals.append(got)
    for m in _KO_AMOUNT.finditer(text or ""):
        vals.append((float(m.group(1)) * 1e12 + float(m.group(2)) * 1e8, ""))
    for w, n in _WORDS.items():
        if re.search(rf"\b{w}\b", text or "", re.I):
            vals.append((float(n), ""))
    return vals


def _close(a: float, b: float, decimals: int = 0) -> bool:
    """Is b, as stated, what the brief's a rounds from?

    Small figures must agree to the brief's own precision: "2.50%" is not
    2.47, and "40%" covers 39.6 to 40.4. Large ones ("4.4 million",
    "60 trillion won") may be rounded by up to 2.5%.
    """
    if a == b:
        return True
    if abs(a) >= 1000 and b:
        return abs(a - b) / abs(b) <= 0.025
    return abs(a - b) <= 0.5 * 10 ** -decimals + 1e-9


def supported(fig: tuple[float, str, str], vals: list[tuple[float, str]]) -> bool:
    v, _, raw = fig
    m = re.search(r"\.(\d+)", raw)
    decimals = len(m.group(1)) if m and abs(v) < 1000 else 0
    return any(_close(v, sv, decimals) for sv, _ in vals)


# ── Dates ──────────────────────────────────────────────────────────────────
def dates(text: str) -> list[tuple[int, int, str]]:
    out = []
    for m in _EN_DATE.finditer(text or ""):
        out.append((_MONTHS[m.group(1)[:3].lower()], int(m.group(2)), m.group(0)))
    for m in _EN_DATE_DM.finditer(text or ""):
        out.append((_MONTHS[m.group(2)[:3].lower()], int(m.group(1)), m.group(0)))
    return [d for d in out if 1 <= d[1] <= 31]


def date_supported(month: int, day: int, text: str, pub: date | None, today: date) -> bool:
    """A date is supported when the source states it, names its weekday, or
    speaks relatively ("on Tuesday", "yesterday") and the date is within a
    few days of when it was published."""
    for mm, dd, _ in dates(text):
        if (mm, dd) == (month, day):
            return True
    for m in _KO_DATE.finditer(text or ""):
        mm = int(m.group(1)) if m.group(1) else None
        if int(m.group(2)) == day and (mm is None or mm == month):
            return True
    try:
        when = date(today.year, month, day)
    except ValueError:
        return False
    if abs((when - today).days) > 200:                  # December read in January
        try:
            when = date(today.year + (1 if when < today else -1), month, day)
        except ValueError:
            return False
    # What happened on the day it was published, or the day before ("on
    # Tuesday" in a Wednesday-morning story): reporting of the day itself.
    if any(abs((when - d).days) <= 1 for d in (pub, today) if d):
        return True
    low = (text or "").lower()
    if _WEEKDAYS[when.weekday()] in low or _KO_WEEKDAYS[when.weekday()] in (text or ""):
        return True
    anchor = pub or today
    if _RELATIVE.search(text or "") and abs((when - anchor).days) <= 2:
        return True
    return False


# ── The brief ──────────────────────────────────────────────────────────────
# (section, fields whose figures remove the item, fields whose figures remove a sentence)
SECTIONS = {
    "top_stories": (("headline",), ("body", "body_text", "why_it_matters")),
    "overnight_items": (("headline",), ("body", "body_text")),
    "also_today": (("headline",), ("body", "body_text")),
    "business_economy": (("headline",), ("body", "body_text", "detail")),
    "northeast_asia": (("headline",), ("body", "body_text")),
    "capitol_hill": (("headline",), ("body", "body_text", "detail")),
    "korea_world": (("headline",), ("body", "body_text")),
    "rok_government": (("action",), ("detail",)),
    "rok_personnel": ((), ("detail",)),
    "social_statements": ((), ("context", "analyst_note")),
    "opeds_today": (("headline",), ("summary", "central_argument")),
    "academic_today": (("headline",), ("summary", "central_argument")),
}
_URL_KEYS = ("url", "secondary_url", "source_url", "gnews_url")
_NEVER_DROP = {"top_stories"}
# More than this share of checked items losing something means the checker,
# not the brief, is wrong: report and change nothing.
MAX_SHARE = 0.4


# Korean names for the subjects a figure most often belongs to, so a Korean
# report of the same event counts ("한은, 기준금리 연 3.00% 동결" for the BOK).
_ALIASES = {
    "bank of korea": ("한은", "한국은행", "기준금리"), "bok": ("한은", "한국은행", "기준금리"),
    "kospi": ("코스피",), "samsung": ("삼성",), "hynix": ("하이닉스",), "hyundai": ("현대",),
    "hanwha": ("한화",), "north korea": ("북한",), "exports": ("수출",), "births": ("출생",),
    "gdp": ("성장률", "GDP"), "inflation": ("물가",), "unemployment": ("실업",),
}


def _subject_articles(item: dict, index, cited: list[dict]) -> list[dict]:
    """Korean-language articles on the item's subject (by the aliases above)."""
    head = str(item.get("headline") or item.get("action") or "").lower()
    keys = [ko for en, kos in _ALIASES.items() if re.search(rf"\b{re.escape(en)}\b", head) for ko in kos]
    if not keys:
        return []
    out = []
    for a in index.values():
        if a in cited:
            continue
        t = f'{a.get("title", "")} {a.get("summary", "")}'
        if any(k in t for k in keys):
            out.append(a)
            if len(out) >= 12:
                break
    return out


def _same_story(item: dict, index, cited: list[dict]) -> list[dict]:
    """Other articles in today's input on the same story: most of the item's
    headline words in their title. A figure the model took from a second
    outlet's report of the same event is sourced, if not cited."""
    import links
    words = links.tokens(str(item.get("headline") or item.get("action") or ""))
    if len(words) < 4:
        return []
    out = []
    for a in index.values():
        if a in cited:
            continue
        t = index.tok(a) if hasattr(index, "tok") else links.tokens(a.get("title") or "")
        if len(words & t) >= max(3, int(0.4 * len(words))):
            out.append(a)
            if len(out) >= 6:
                break
    return out


def _cited(item: dict, index, lookup) -> list[dict]:
    arts = []
    urls = [item.get(k) for k in _URL_KEYS]
    for link in item.get("source_links") or []:
        if isinstance(link, dict):
            urls += [link.get("url"), link.get("gnews_url")]
    for u in urls:
        if isinstance(u, str) and u.startswith("http"):
            a = lookup(u, index)
            if a and a not in arts:
                arts.append(a)
    return arts


def _pub(a: dict) -> date | None:
    try:
        return date.fromisoformat(str(a.get("pub_date") or "")[:10])
    except ValueError:
        return None


_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'“(])")


def reference_text(payload: dict) -> str:
    """The figures the prompt hands the model directly: markets, polling, trackers."""
    # The policy rate is left out: prose must take it from an article. On 28
    # October the strip's stale 2.50% is what the brief repeated.
    markets = {k: v for k, v in (payload.get("market_indicators") or {}).items() if k != "bok_rate"}
    keep = {k: payload.get(k) for k in ("sentiment", "public_sentiment",
                                         "sentiment_baseline", "kcna_summary", "kim_tracker",
                                         "provocations", "hill_calendar", "think_tank_events")
            if payload.get(k)}
    keep["market_indicators"] = markets
    try:
        # The standing baselines the system prompt states (the $350B pledge,
        # tariff rates, the Special Investment Act vote) are sources too.
        # The standing reference blocks the prompt carries: trade baselines
        # and the investment pledge. Not the whole prompt, whose recent
        # coverage and calendars would make nearly any number "sourced".
        from digest import SYSTEM_PROMPT, _TRADE_BASELINES, _INVESTMENT_TRACKER
        SYSTEM_PROMPT = " ".join((SYSTEM_PROMPT, _TRADE_BASELINES, _INVESTMENT_TRACKER))
    except Exception:                                           # noqa: BLE001
        SYSTEM_PROMPT = ""
    try:
        return json.dumps(keep, ensure_ascii=False, default=str) + " " + SYSTEM_PROMPT
    except Exception:                                           # noqa: BLE001
        return SYSTEM_PROMPT


def check(digest: dict, payload: dict, today: date | None = None) -> list[dict]:
    """Findings, one per unsupported figure or date: section, index, field, claim, kind."""
    import links
    today = today or date.today()
    index = links.corpus_index(payload or {})
    # The reference blocks' figures, not their dates: a "26" in "Feb 26" is
    # a day, and does not make a "26th" in the brief sourced.
    ref_vals = [(v, k) for v, k, _ in figures(reference_text(payload or {}))]
    findings = []
    for sec, (head_fields, body_fields) in SECTIONS.items():
        for i, item in enumerate(digest.get(sec) or []):
            if not isinstance(item, dict):
                continue
            arts = _cited(item, index, links.lookup)
            if not arts:
                continue                                # nothing to check against
            arts = arts + _same_story(item, index, arts)
            arts = arts + _subject_articles(item, index, arts)
            text = " ".join(f'{a.get("title", "")} {a.get("summary", "")}' for a in arts)
            vals = source_values(text) + ref_vals
            pub = max((p for p in (_pub(a) for a in arts) if p), default=None)
            for field in head_fields + body_fields:
                value = item.get(field)
                if not isinstance(value, str) or not value.strip():
                    continue
                for fig in figures(value):
                    if not supported(fig, vals):
                        findings.append({"section": sec, "index": i, "field": field, "claim": fig[2],
                                         "kind": "figure", "head": field in head_fields})
                for mm, dd, raw in dates(value):
                    if not date_supported(mm, dd, text, pub, today):
                        findings.append({"section": sec, "index": i, "field": field, "claim": raw,
                                         "kind": "date", "head": field in head_fields})
    # The glance and the stat of the day cite no article of their own: their
    # figures must appear in some article the brief cites, or the reference data.
    every = []
    for sec in SECTIONS:
        for item in digest.get(sec) or []:
            if isinstance(item, dict):
                every += _cited(item, index, links.lookup)
    all_text = " ".join(f'{a.get("title", "")} {a.get("summary", "")}' for a in every)
    all_vals = source_values(all_text) + ref_vals
    for i, mi in enumerate(digest.get("morning_memo") or []):
        text = mi if isinstance(mi, str) else (mi.get("text", "") if isinstance(mi, dict) else "")
        for fig in figures(text):
            if not supported(fig, all_vals):
                findings.append({"section": "morning_memo", "index": i, "field": "text",
                                 "claim": fig[2], "kind": "figure", "head": True})
    ks = digest.get("key_stat")
    if isinstance(ks, dict) and ks.get("number"):
        figs = figures(str(ks["number"])) or figures(str(ks["number"]) + " ")
        if figs and not supported(figs[0], all_vals):
            findings.append({"section": "key_stat", "index": 0, "field": "number",
                             "claim": str(ks["number"]), "kind": "figure", "head": True})

    # Upcoming: the day of each model item, against the article it cites.
    for i, c in enumerate(digest.get("calendar_watch") or []):
        if not isinstance(c, dict) or c.get("_source"):
            continue
        arts = _cited(c, index, links.lookup)
        if not arts:
            continue
        mon = _MONTHS.get(str(c.get("month", ""))[:3].lower())
        try:
            day = int(str(c.get("day", "")).split("-")[0])
        except ValueError:
            continue
        text = " ".join(f'{a.get("title", "")} {a.get("summary", "")}' for a in arts)
        if mon and not date_supported(mon, day, text, max((p for p in map(_pub, arts) if p), default=None), today):
            findings.append({"section": "calendar_watch", "index": i, "field": "day",
                             "claim": f'{c.get("month")} {day}', "kind": "date", "head": True})
    return findings


def _strip_sentences(text: str, claims: list[str]) -> str:
    parts = _SENT.split(text)
    kept = [p for p in parts if not any(c in p for c in claims)]
    return " ".join(kept).strip()


def apply(digest: dict, payload: dict, today: date | None = None) -> tuple[list[str], list[dict]]:
    """Remove what the sources do not support. Returns (log lines, findings). Never raises."""
    try:
        findings = check(digest, payload, today)
    except Exception as e:                                      # noqa: BLE001
        return [f"Fact check skipped: {e}"], []
    if not findings:
        return [], []
    checked = sum(len(digest.get(s) or []) for s in SECTIONS) + len(digest.get("calendar_watch") or [])
    touched = {(f["section"], f["index"]) for f in findings}
    if checked >= 10 and len(touched) / checked > MAX_SHARE:
        return [f"Fact check found {len(findings)} unsupported figures or dates in {len(touched)} of "
                f"{checked} items; too many to be the brief's fault, so nothing was removed"], findings
    log, drop = [], set()
    by_item: dict = {}
    for f in findings:
        by_item.setdefault((f["section"], f["index"]), []).append(f)
    for (sec, i), fs in list(by_item.items()):
        claims = ", ".join(sorted({f["claim"] for f in fs}))
        if sec == "key_stat":
            digest["key_stat"] = None
            log.append(f"key_stat: removed ({claims} is in no article the brief cites)")
            del by_item[(sec, i)]
        elif sec == "morning_memo":
            drop.add((sec, i))
            log.append(f"morning_memo: removed item {i + 1} ({claims} is in no article the brief cites)")
            del by_item[(sec, i)]
    tops = len(digest.get("top_stories") or [])
    for (sec, i), fs in by_item.items():
        item = digest[sec][i]
        label = str(item.get("headline") or item.get("action") or item.get("who") or item.get("name") or "")[:70]
        claims = ", ".join(sorted({f["claim"] for f in fs}))
        # A lead goes too, so long as two remain: a wrong figure in the
        # first headline a reader sees is the worst place to keep one.
        lead_ok = sec not in _NEVER_DROP or tops > 2
        if any(f["head"] for f in fs) and lead_ok:
            if sec in _NEVER_DROP:
                tops -= 1
            drop.add((sec, i))
            log.append(f"{sec}: removed {label!r} ({claims} not in its source)")
            continue
        for field in {f["field"] for f in fs if not f["head"]}:
            before = item[field]
            item[field] = _strip_sentences(before, [f["claim"] for f in fs if f["field"] == field])
        bodies = [item.get(k) for k in SECTIONS.get(sec, ((), ()))[1] if k in item]
        if bodies and not any(isinstance(b, str) and b.strip() for b in bodies) and sec not in _NEVER_DROP:
            drop.add((sec, i))
            log.append(f"{sec}: removed {label!r} (nothing left once {claims} went)")
        elif any(f["head"] for f in fs):
            log.append(f"{sec}: kept lead {label!r}; its headline's {claims} is not in its source")
        else:
            log.append(f"{sec}: cut the sentence(s) with {claims} from {label!r}")
    for sec in {s for s, _ in drop}:
        digest[sec] = [it for j, it in enumerate(digest[sec]) if (sec, j) not in drop]
    return log, findings
