"""
Korea Daily Brief — Week in Review
Synthesizes Saturday-through-Friday daily digests into a "Top 10" weekly edition.
Run: python weekly.py [--no-send]
Triggered Fridays at 9:00 AM ET via GitHub Actions (GitHub often runs it hours late), or manually.
"""
import json
import os
import time
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import anthropic
import httpx


WEEKLY_SYSTEM_PROMPT = """You are the senior intelligence analyst for the CSIS Korea Chair. You produce the Korea Daily Brief — Week in Review edition, a concise synthesis of the week's Korea-related developments for senior policymakers.

Your readers are experts who received the daily briefs but want a consolidated weekend read highlighting what mattered most this week. Be ruthlessly concise — they've already seen the details. Your job is synthesis, pattern recognition, and forward-looking assessment.

RULES:
- SOURCE-OR-SKIP: Every claim — every date, destination, name, number, and event — must appear explicitly in the daily digest data provided below. If a detail is not in the digests, it does not exist; omit it. An omission is always better than an invention. You have NO other knowledge; do not add anything from memory or general awareness.
- NO COMPOSITE FACTS: Do NOT merge separate developments into a single combined claim. If the digests mention a Latin America trip in one place and US tariff talks in another, you may NOT construct a single "five-nation itinerary including Washington" — that is fabrication. State only the specific trips/events/meetings each digest actually reported, exactly as reported. Do not infer an itinerary, a destination, or a meeting that was not stated.
- NO EXTRAPOLATION: Do not project, predict, or assume plans (e.g. "will visit Washington", "the trip covers X") unless a daily digest explicitly reported that plan with that specific.
- Synthesis means CONDENSING what was reported across the week, not generating new connective facts. Pattern recognition is about recurring themes, not inventing links.
- No editorializing. Present patterns and let readers draw conclusions.
- Highlight what CHANGED this week, not what remained stable.
- English only: no Korean script anywhere, outlet names in English (Newsis, not 뉴시스; Kyunghyang Shinmun, not 경향신문). Translate a Korean term rather than quoting it.
- No em dashes; use commas or full stops. No middle dots or arrows.
- Write as the brief itself: never refer to "the digests" or "the daily briefs" in the text.
- Report, do not interpret: no "signals", "underscores", "highlights", or what an event "suggests".
- Return ONLY valid JSON. No markdown fences, no preamble."""


WEEKLY_USER_PROMPT_TEMPLATE = """Today is {date_str} (Friday). Synthesize this week's daily digests (Saturday through Friday) into a Week in Review.

DAILY DIGESTS THIS WEEK:
{digests_json}

Return a JSON object with:
- week_label: string (e.g. "May 17-23, 2026")
- re_line: 1-sentence summary of the week's most important development (under 80 chars)
- top_10: array of the 10 most consequential stories this week, ranked by significance. Each: rank (1-10), headline (concise, factual), body (2-3 sentences synthesizing the week's coverage of THIS ONE story), first_reported (month and day, e.g. "Oct 19"), category (e.g. "Security", "Diplomacy", "Economy", "DPRK", "US-ROK", "Trade"), sources (array of outlet names that covered this story). GROUNDING: each story must correspond to actual coverage in the daily digests, and every specific in the body (dates, destinations, names, figures) must appear in that coverage — do NOT combine two different stories into one, and do NOT enrich a story with details from elsewhere in the week. If fewer than 10 consequential stories occurred, return as many as the data supports — do not pad with trivial items.
- dprk_statements: object summarizing the week's DPRK official statements — kim_appearances (count of days Kim appeared), notable_quotes (up to 3 most significant official quotes from the week, each with speaker and quote text), watch_flags (count of days with watch flag), silence_days (count of days with KCNA silence), summary (2-3 sentences on the week's official posture)
- bp_changes: array of facility status changes this week (only facilities whose status or note changed). Each: name, status_start, status_end, change_summary (1 sentence)
- market_weekly: object with bok_action (null, or one sentence on any Bank of Korea rate decision this week). KOSPI, the won and polling are computed from the data; do not return them.
- calendar_next_week: array of 3-5 key events in the coming 7 days, AFTER today. Each: date (YYYY-MM-DD), headline, detail (1 sentence). Only dated, scheduled events a digest reported (rate decisions, court rulings, summits and visits, Assembly votes, data releases, exercises). Never an anniversary or commemoration, and never an event dated today or earlier.
- bottom_line: 2-3 sentences. The single most important takeaway from this week and what to watch next week. Be ruthlessly concise.
- story_count_total: total Tier 1 articles processed across all daily digests this week
"""


def _load_week_digests() -> list[dict]:
    """Load daily digest JSON files from Saturday through Friday (today)."""
    tz = ZoneInfo("America/New_York")
    today = datetime.now(tz).date()
    # Friday = weekday 4. Find the preceding Saturday (weekday 5).
    # If today is Friday, last Saturday is 6 days ago.
    days_since_saturday = (today.weekday() - 5) % 7
    if days_since_saturday == 0:
        days_since_saturday = 7
    start_date = today - timedelta(days=days_since_saturday)

    digests = []
    d = start_date
    while d <= today:
        date_slug = d.strftime("%Y-%m-%d")
        for pattern in [f"digest_{date_slug}.json", f"public/digest_{date_slug}.json"]:
            path = Path(pattern)
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    data["_date"] = date_slug
                    digests.append(data)
                except (json.JSONDecodeError, IOError):
                    continue
                break
        d += timedelta(days=1)
    return digests


def _summarize_digest(d: dict) -> dict:
    """Extract key fields from a daily digest for the weekly prompt."""
    return {
        "date": d.get("_date", "unknown"),
        "re_line": d.get("re_line", ""),
        "top_stories": [
            {"headline": s.get("headline", ""), "category": s.get("category_tag", ""),
             "source": s.get("source", ""), "body": s.get("body", s.get("body_text", ""))[:200]}
            for s in (d.get("top_stories") or [])
        ],
        "overnight_headlines": [
            {"headline": s.get("headline", ""), "source": s.get("source", "")}
            for s in (d.get("overnight_items") or [])
        ],
        "also_today_headlines": [s.get("headline", "") for s in (d.get("also_today") or [])],
        "kcna_delta": {
            "silence_today": (d.get("kcna_delta") or {}).get("silence_today"),
            "watch_flag": (d.get("kcna_delta") or {}).get("watch_flag"),
            "bottom_line": (d.get("kcna_delta") or {}).get("bottom_line"),
            "kim_appearance_today": (d.get("kcna_delta") or {}).get("kim_appearance_today"),
            "key_quotes": (d.get("kcna_delta") or {}).get("key_quotes") or [],
        },
        "bp_locations": [
            {"name": loc.get("name"), "status": loc.get("status"), "note": loc.get("note", "")[:100]}
            for loc in (d.get("bp_locations") or [])
            if loc.get("status") in ("elevated", "alert")
        ],
        "market_indicators": {
            "kospi": (d.get("market_indicators") or {}).get("kospi"),
            "usd_krw": (d.get("market_indicators") or {}).get("usd_krw"),
        },
        "sentiment": {
            "presidential_approval": (d.get("public_sentiment") or {}).get("presidential_approval"),
            "party_ruling": (d.get("public_sentiment") or {}).get("party_ruling"),
            "party_opposition": (d.get("public_sentiment") or {}).get("party_opposition"),
        },
        "deals": [
            {"company": deal.get("company"), "value": deal.get("value"), "sector": deal.get("sector")}
            for deal in ((d.get("us_korea_deals") or {}).get("investment_package") or {}).get("known_deals") or []
        ],
        "northeast_asia": [
            {"headline": s.get("headline", ""), "source": s.get("source", "")}
            for s in (d.get("northeast_asia") or [])[:3]
        ],
        "business_economy": [
            {"headline": s.get("headline", "")}
            for s in (d.get("business_economy") or [])[:3]
        ],
        "capitol_hill": [
            {"headline": s.get("headline", ""), "source": s.get("source", ""),
             "category": s.get("category", "")}
            for s in (d.get("capitol_hill") or [])[:4]
        ],
        "korea_world": [
            {"headline": s.get("headline", ""), "source": s.get("source", ""),
             "region": s.get("region", "")}
            for s in (d.get("korea_world") or [])[:3]
        ],
        "calendar_watch": d.get("calendar_watch") or [],
        # Collected from the committee schedules, not written by a model.
        "hill_calendar": [{"date": e.get("date"), "committee": e.get("committee"),
                           "title": e.get("title")} for e in (d.get("hill_calendar") or [])[:5]],
        "story_count": d.get("story_count", 0),
    }


def generate_weekly(digests: list[dict]) -> dict:
    """Generate weekly summary via Claude API."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Missing ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)

    summaries = [_summarize_digest(d) for d in digests]
    tz = ZoneInfo("America/New_York")
    date_str = datetime.now(tz).strftime("%A, %B %-d, %Y")

    user_prompt = WEEKLY_USER_PROMPT_TEMPLATE.format(
        date_str=date_str,
        digests_json=json.dumps(summaries, ensure_ascii=False, indent=1),
    )

    print(f"\n🤖  Generating weekly summary ({len(digests)} daily digests)...")
    t0 = time.time()
    collected = []
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=6000,
        system=[{
            "type": "text",
            "text": WEEKLY_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[
            {"role": "user", "content": user_prompt},
        ],
    ) as stream:
        for text in stream.text_stream:
            collected.append(text)
    elapsed = time.time() - t0
    raw_text = "".join(collected)
    print(f"    ⏱  Weekly generation: {elapsed:.0f}s")

    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    return json.loads(text)


def _num(text) -> float | None:
    try:
        return float(str(text).replace(",", "").replace("%", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def market_week(digests: list[dict]) -> dict:
    """KOSPI and the won over the week, from the dailies' own figures.

    The model used to be asked for these, and read a key the digests do not
    have ("krw_usd"), so the won came back empty on 23 October. The first
    and last figures of the week are arithmetic, not synthesis.
    """
    out = {}
    for key, name in (("kospi", "kospi"), ("usd_krw", "krw")):
        vals = [(d.get("_date"), _num(((d.get("market_indicators") or {}).get(key) or {}).get("value")))
                for d in digests]
        vals = [(day, v) for day, v in vals if v]
        if len(vals) >= 2:
            (d0, v0), (d1, v1) = vals[0], vals[-1]
            out[name] = {"open": v0, "close": v1, "change_pct": (v1 - v0) / v0 * 100,
                         "from": d0, "to": d1}
        elif vals:
            out[name] = {"close": vals[-1][1], "to": vals[-1][0]}
    return out


def sentiment_week(digests: list[dict]) -> dict:
    """The latest Gallup Korea reading the week's dailies carried (one poll, never mixed)."""
    for d in reversed(digests):
        ps = d.get("public_sentiment") or {}
        appr = ps.get("presidential_approval") or {}
        if appr.get("value"):
            return {"approval": appr.get("value"), "poll": appr.get("last_updated", ""),
                    "source": appr.get("source", "Gallup Korea"),
                    "ruling": (ps.get("party_ruling") or {}).get("value"),
                    "opposition": (ps.get("party_opposition") or {}).get("value")}
    return {}


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def next_week_events(events: list, today) -> list[dict]:
    """Next week's calendar, dated and in the future, with no anniversaries.

    On 23 October the list led with a one-year anniversary dated that day.
    """
    import re
    import korea_calendar
    out = []
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        raw = str(ev.get("date", ""))
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
        item = {"headline": ev.get("headline", ""), "detail": ev.get("detail", "")}
        if m:
            item.update(month=_MONTHS[int(m.group(2)) - 1], day=int(m.group(3)))
        else:
            item["date"] = raw
        n = korea_calendar.normalize(item, today)
        if not n or n["_end"] <= today.isoformat() or korea_calendar.off_topic(n):
            continue
        out.append(n)
    return sorted(out, key=lambda n: n["_date"])


def pyongyang_week(digests: list[dict]) -> dict:
    """The week's Pyongyang Watch from the dailies' kcna_delta, day by day.

    The model's summary covered the week in three sentences and left most of
    it out: which day Kim was seen and doing what, what KCNA led with each
    day, and who around him appeared. All of that is in the dailies already.
    """
    import re
    from render import _v2_first_sentence
    out = {"days": [], "kim_seen": [], "officials": [], "watch_flags": 0, "silence_days": 0, "longest_gap": 0}
    officials: dict[str, dict] = {}
    gap = 0
    for d in digests:
        k = d.get("kcna_delta") or {}
        if not k:
            continue
        try:
            day = datetime.strptime(d.get("_date", ""), "%Y-%m-%d").strftime("%a %b %-d")
        except ValueError:
            day = d.get("_date", "")
        lead = re.sub(r"\s*[—–]\s*", ", ", str(k.get("bottom_line") or "")).strip()
        # The first clause of the first sentence: KCNA's lead that day. The
        # daily's bottom lines run on through semicolons into what to watch.
        first = _v2_first_sentence(lead).split("; ")[0].rstrip(" .;,") if lead else ""
        out["days"].append((day, first + "." if first else ""))
        if k.get("kim_appearance_today"):
            act = re.sub(r"^Kim Jong Un\s+", "", str(k.get("kim_activity") or "")).strip().rstrip(".")
            out["kim_seen"].append((day, act))
            gap = 0
        else:
            gap += 1
            since = k.get("days_since_last_appearance")
            out["longest_gap"] = max(out["longest_gap"], gap, since if isinstance(since, int) else 0)
        out["watch_flags"] += bool(k.get("watch_flag"))
        out["silence_days"] += bool(k.get("silence_today"))
        for o in k.get("senior_officials") or []:
            name = str(o.get("name") or "").strip()
            if not name or "unnamed" in name.lower():
                continue
            rec = officials.setdefault(name, {"days": [], "act": ""})
            short = day.split(" ", 1)[1] if " " in day else day
            if short not in rec["days"]:
                rec["days"].append(short)
            rec["act"] = str(o.get("activity") or rec["act"]).strip()
    out["officials"] = sorted(((n, r["days"], r["act"]) for n, r in officials.items()),
                              key=lambda t: -len(t[1]))[:4]
    return out


def render_weekly(weekly: dict, digests: list[dict] | None = None) -> str:
    """The Week in Review in the daily's v2 design.

    Every part is the daily's own (render._v2_*): the nameplate, the numbered
    navy bars on white cards, the charcoal Pyongyang Watch, the blue date
    boxes, the black sign-off and the navy footer, so a change to the daily's
    identity reaches the weekly with nothing to remember. Only the
    arrangement is the weekly's.
    """
    import re
    import render as R
    from html import escape as _esc
    digests = digests or []
    tz = ZoneInfo("America/New_York")
    now = datetime.now(tz)
    base = (os.environ.get("WEB_URL") or "https://andysaulim.github.io/Daily-Korea-Digest").rstrip("/") + "/"
    ctx = {"web_url": base + "latest.html", **({"audio_url": weekly["audio_url"]} if weekly.get("audio_url") else {})}
    SANS, SERIF = R._V2_SANS, R._V2_SERIF

    def card(anchor: str, label: str, inner: str) -> str:
        return (f'<!--v2--><div><a name="{anchor}" id="{anchor}"></a>'
                f'{R._v2_bar(label)}{inner}</div>')

    def kicker(text: str) -> str:
        return (f'<div style="font-size:12px;font-weight:700;line-height:1.35;color:{R._V2_TEAL};'
                f'margin-bottom:2px;">{text}</div>') if text else ""

    # ── Masthead: the daily's strip and nameplate, the weekly's name ──────
    link = (lambda href, text: f'<a href="{_esc(href)}" style="color:{R._V2_NAVY};font-weight:700;'
                               f'text-decoration:none;white-space:nowrap;">{text}</a>')
    strip = ('<table width="100%" cellpadding="0" cellspacing="0" border="0" class="no-print v2-strip"><tr>'
             f'<td style="padding:9px 16px;font-family:{SANS};font-size:11px;font-weight:700;color:#3D4149;">'
             'For internal use only</td>'
             f'<td align="right" style="padding:9px 16px 9px 0;font-family:{SANS};font-size:11px;text-align:right;">'
             f'{link(base + "latest.html", "Today&#8217;s brief")}&emsp; {link(base + "archive.html", "Past issues")}'
             '</td></tr></table>')
    mark = R._v2_wordmark(ctx) or (
        f'<span class="v2-csis" style="font-family:{SERIF};font-size:32px;line-height:30px;color:#FFFFFF;">CSIS</span>')
    count = weekly.get("story_count_total") or sum(int(d.get("story_count") or 0) for d in digests)
    facts = [f'<span style="white-space:nowrap;">{len(digests)} daily briefs</span>'] if digests else []
    if count:
        facts.append(f'<span style="white-space:nowrap;">{int(count):,} articles</span>')
    facts.append('<span style="white-space:nowrap;">%%READMIN%% min read</span>')
    band = (f'<div class="v2-gap" style="padding:0 16px;"><div bgcolor="{R._V2_NAVY}" class="mast-band" '
            f'style="background-color:{R._V2_NAVY};padding:30px 16px 22px;text-align:center;">'
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" class="v2-mrow v2-namebox" '
            'style="margin:0 auto;border:2px solid #4A90D0;border-radius:6px;"><tr>'
            f'<td class="v2-mk" valign="middle" style="padding:8px 10px 8px 12px;vertical-align:middle;">{mark}</td>'
            '<td class="v2-nbt" valign="middle" style="vertical-align:middle;padding:8px 12px 8px 10px;'
            'border-left:1px solid #4A90D0;">'
            f'<h1 class="v2-name" style="margin:0;font-family:{SANS};font-size:18px;font-weight:700;white-space:nowrap;'
            'letter-spacing:1px;line-height:1.2;color:#FFFFFF;">KOREA WEEK IN REVIEW</h1></td></tr></table>'
            f'<div class="v2-mdate" style="margin-top:16px;font-family:{SANS};font-size:13px;line-height:1.6;'
            f'color:{R._V2_FOOT};"><b style="white-space:nowrap;color:#FFFFFF;">'
            f'{_esc(weekly.get("week_label", ""))}</b><!--c-->'
            + "".join(f"&emsp; {f}" for f in facts) + '<!--/c--></div></div></div>')
    # The daily's Listen card, when this week has an episode.
    listen = ""
    if weekly.get("audio_url"):
        mins = weekly.get("audio_minutes")
        title = f"Listen, {int(mins)} min" if isinstance(mins, (int, float)) and mins > 0 else "Listen to this week&#8217;s review"
        listen = R._v2_gap(
            f'<a href="{_esc(weekly["audio_url"])}" class="listen-bar" style="display:block;background:#FFFFFF;text-decoration:none;">'
            '<table width="100%" cellpadding="0" cellspacing="0" border="0" role="presentation"><tr>'
            f'<td style="padding:12px 0 12px 20px;vertical-align:middle;font-family:{SANS};">'
            f'<div class="listen-title" style="font-size:14px;font-weight:700;color:{R._V2_INK};">{title}</div>'
            f'<div class="listen-sub" style="font-size:12px;color:{R._V2_META};margin-top:1px;">The Week in Review, read aloud</div></td>'
            f'<td align="right" style="padding:12px 20px 12px 8px;vertical-align:middle;font-family:{SANS};">'
            f'<span class="listen-btn" style="display:inline-block;border:1px solid {R._V2_NAVY};padding:6px 12px;'
            f'font-size:13px;font-weight:700;color:{R._V2_NAVY};white-space:nowrap;">Play</span></td>'
            '</tr></table></a>', top=12, bottom=0)
    masthead = f'<!--v2--><a name="top" id="top"></a>{strip}{band}{listen}%%TOCCARD%%'

    sections = []

    # ── The week in brief: the bottom line, on the glance's tint ──────────
    bottom = _esc(weekly.get("bottom_line", ""))
    if bottom:
        sections.append(
            '<!--v2--><div><a name="memo" id="memo"></a>'
            f'{R._v2_bar("The Week in Brief", numbered=False)}'
            '<table width="100%" cellpadding="0" cellspacing="0" border="0" class="v2-glance"><tr>'
            f'<td style="padding:8px 0 6px;font-family:{SANS};font-size:14px;line-height:1.55;color:{R._V2_INK};">'
            f'{R._emphasis(bottom)}</td></tr></table></div>')

    # ── Top 10: one numbered circle per story, level with its headline ────
    rows = ""
    for i, st in enumerate(weekly.get("top_10") or []):
        rank = i + 1
        # Filled for the top three, outlined for the rest: one shape, so the
        # column of numbers reads as a list.
        fill = (f"background:{R._V2_ACCENT};color:#FFFFFF;border:1px solid {R._V2_ACCENT};" if rank <= 3 else
                f"background:#FFFFFF;color:{R._V2_NAVY};border:1px solid {R._V2_NAVY};")
        num = (f'<div style="width:24px;height:24px;box-sizing:border-box;border-radius:50%;{fill}'
               f'text-align:center;line-height:22px;font-size:13px;font-weight:700;font-family:{SERIF};">{rank}</div>')
        meta = [_esc(str(st.get("category", "")))]
        if st.get("first_reported"):
            meta.append("first reported " + _esc(str(st["first_reported"])))
        srcs = ", ".join(_esc(x) for x in (st.get("sources") or []) if x)
        line = ", ".join(m for m in meta if m)
        rows += ('<table width="100%" cellpadding="0" cellspacing="0" border="0" class="v2-it" '
                 f'style="border-top:1px solid {R._V2_HAIR};"><tr>'
                 f'<td width="36" valign="top" style="padding:13px 0 0;vertical-align:top;">{num}</td>'
                 f'<td valign="top" style="padding:12px 0 13px;vertical-align:top;font-family:{SANS};">'
                 f'<h3 style="margin:0;{R._V2_HEAD.replace("15px", "16px")}">{R._emphasis(_esc(st.get("headline", "")))}</h3>'
                 f'<p style="margin:5px 0 0;font-size:14px;line-height:1.55;color:{R._V2_BODY};">'
                 f'{R._emphasis(_esc(st.get("body", "")))}</p>'
                 + (f'<div style="font-size:12px;line-height:1.5;color:{R._V2_META};margin-top:6px;">'
                    + (f'<b style="color:{R._V2_TEAL};">{line}</b>' if line else "")
                    + (". " if line and srcs else "") + srcs + '</div>' if line or srcs else "")
                 + '</td></tr></table>')
    if rows:
        sections.append(card("top-stories", "Top 10 Stories", rows))

    # ── Pyongyang Watch: the week from the dailies' own record ────────────
    pw = pyongyang_week(digests)
    dprk = weekly.get("dprk_statements") or {}
    inner = ""
    if pw["days"]:
        seen = pw["kim_seen"]
        n = len(pw["days"])
        kim = (f"Seen on {len(seen)} of {n} days: " + "; ".join(
                   f"<b>{_esc(day)}</b>" + (f", {_esc(act)}" if act else "") for day, act in seen)
               if seen else f"No public appearance in {n} days")
        if pw["longest_gap"] >= 3:
            kim += f". Longest absence: {pw['longest_gap']} days"
        extra = []
        if pw["watch_flags"]:
            extra.append(f"watch flag up on {pw['watch_flags']} day{'s' if pw['watch_flags'] != 1 else ''}")
        if pw["silence_days"]:
            extra.append(f"KCNA silent on {pw['silence_days']} day{'s' if pw['silence_days'] != 1 else ''}")
        inner += (f'<div class="v2-it" style="padding:12px 0;border-top:1px solid {R._V2_HAIR};">'
                  f'<div style="font-size:12px;font-weight:700;color:{R._V2_TEAL};margin-bottom:2px;">Kim Jong Un'
                  + (f'<span style="color:{R.TAEGUK_RED};">, {", ".join(extra)}</span>' if extra else "")
                  + f'</div><div style="font-size:14px;line-height:1.5;color:{R._V2_INK};">{kim}.</div></div>')
    if dprk.get("summary"):
        inner += (f'<div class="v2-it" style="padding:10px 0 12px;border-top:1px solid {R._V2_HAIR};'
                  f'font-size:14px;line-height:1.55;color:{R._V2_BODY};">{R._emphasis(_esc(dprk["summary"]))}</div>')
    quotes = ""
    for q in (dprk.get("notable_quotes") or [])[:3]:
        qt = _esc(q.get("quote") or q.get("text") or "")
        if qt:
            quotes += (f'<div class="v2-it" style="padding:10px 0;border-top:1px solid {R._V2_HAIR};">'
                       f'<div style="padding-left:12px;border-left:3px solid {R.TAEGUK_RED};font-size:14px;line-height:1.5;'
                       f'font-style:italic;color:{R._V2_INK};">&ldquo;{qt}&rdquo;</div>'
                       f'<div style="font-size:12px;color:{R._V2_META};margin-top:4px;padding-left:15px;">'
                       f'<b style="color:{R._V2_INK};">{_esc(q.get("speaker", ""))}</b></div></div>')
    if quotes:
        inner += R._v2_subhead("In their words") + quotes
    if pw["days"]:
        inner += R._v2_subhead("Day by day") + "".join(
            f'<div class="v2-it" style="padding:9px 0 10px;border-top:1px solid {R._V2_HAIR};font-size:14px;'
            f'line-height:1.5;color:{R._V2_BODY};"><b style="color:{R._V2_INK};">{_esc(day)}</b>&ensp;'
            f'{R._emphasis(_esc(lead))}</div>' for day, lead in pw["days"] if lead)
    if pw["officials"]:
        inner += R._v2_subhead("Senior officials") + "".join(
            f'<div class="v2-it" style="padding:9px 0 10px;border-top:1px solid {R._V2_HAIR};">'
            f'<div style="font-size:14px;font-weight:700;line-height:1.4;color:{R._V2_INK};">{_esc(name)}'
            f'<span style="font-weight:400;color:{R._V2_META};">, in KCNA on {len(days)} day{"s" if len(days) != 1 else ""}'
            f' ({_esc(", ".join(days))})</span></div>'
            f'<div style="font-size:14px;line-height:1.5;color:{R._V2_BODY};margin-top:2px;">{_esc(act)}</div></div>'
            for name, days, act in pw["officials"])
    if inner:
        sections.append(card("kcna", "Pyongyang Watch", inner))

    # ── Facilities that changed ───────────────────────────────────────────
    fac = ""
    for b in weekly.get("bp_changes") or []:
        if not isinstance(b, dict) or not b.get("name"):
            continue
        st0, st1 = (str(b.get(k) or "").strip().capitalize() for k in ("status_start", "status_end"))
        status = f"{st1}, from {st0.lower()}" if st0 and st1 and st0 != st1 else (st1 or st0)
        fac += R._v2_row(kicker(_esc(status)), _esc(b["name"]), "", R._emphasis(_esc(b.get("change_summary", ""))))
    if fac:
        sections.append(card("locations", "Location Watch", fac))

    # ── The numbers: KOSPI and the won over the week, the latest poll ─────
    mk = market_week(digests)
    sent = sentiment_week(digests)
    cells = []

    def cell(label, value, sub):
        rule = "border-left:1px solid #E2E6EC;" if cells else ""
        cells.append(
            '<!--[if mso]><td width="140" valign="top"><![endif]-->'
            f'<div class="v2-cell" style="display:inline-block;vertical-align:top;width:140px;box-sizing:border-box;'
            f'padding:10px 0 9px;{rule}text-align:center;font-family:{SANS};">'
            f'<div style="font-size:11px;font-weight:700;text-transform:uppercase;color:{R._V2_META};white-space:nowrap;">{label}</div>'
            f'<div style="font-size:16px;font-weight:700;color:{R._V2_NAVY};margin-top:3px;line-height:1.15;white-space:nowrap;">{value}</div>'
            f'<div style="font-size:11px;line-height:1.35;color:{R._V2_META};margin-top:2px;">{sub or "&nbsp;"}</div></div>'
            '<!--[if mso]></td><![endif]-->')

    def signed(v):
        if v is None:
            return ""
        if abs(v) < 0.05:
            return f'<span style="color:{R._V2_META};">flat on the week</span>'
        col, sign = (R.UP_GREEN, "+") if v > 0 else (R.DOWN_RED, "&minus;")
        return f'<span style="color:{col};">{sign}{abs(v):.1f}% on the week</span>'

    for key, label, fmt in (("kospi", "KOSPI", "{:,.2f}"), ("krw", "USD/KRW", "{:,.2f}")):
        m = mk.get(key)
        if m:
            cell(label, fmt.format(m["close"]), signed(m.get("change_pct")))
    if sent.get("approval"):
        cell("Lee approval", _esc(str(sent["approval"])), _esc(f'{sent.get("source", "")}, {sent.get("poll", "")}'.strip(", ")))
    numbers = ""
    if cells:
        numbers = ('<!--[if mso]><table cellpadding="0" cellspacing="0" border="0"><tr><![endif]-->'
                   f'<div style="text-align:center;font-size:0;padding:4px 0 2px;">{"".join(cells)}</div>'
                   '<!--[if mso]></tr></table><![endif]-->')
    bok = _esc((weekly.get("market_weekly") or {}).get("bok_action") or "")
    if bok:
        numbers += (f'<div class="v2-it" style="padding:10px 0 4px;border-top:1px solid {R._V2_HAIR};'
                    f'font-size:14px;line-height:1.5;color:{R._V2_BODY};"><b style="color:{R._V2_NAVY};">'
                    f'Bank of Korea:</b> {R._emphasis(bok)}</div>')
    if numbers:
        sections.append(card("markets", "Markets and Polling", numbers))

    # ── Next week: the daily's blue date boxes ────────────────────────────
    cal = "".join(R._v2_cal_row(ev["month"], str(ev["day"]), "", R._emphasis(_esc(ev["headline"])),
                                R._emphasis(_esc(ev.get("detail", ""))))
                  for ev in next_week_events(weekly.get("calendar_next_week"), now.date()))
    if cal:
        sections.append(card("upcoming", "Next Week", cal))

    # ── Sign-off and footer ───────────────────────────────────────────────
    addr = R._v2_reply_address()
    signoff = ('<div style="font-size:15px;font-weight:700;line-height:1.35;color:#FFFFFF;">'
               'That&#8217;s the week. The daily brief returns tomorrow at 7 AM.</div>')
    if addr:
        signoff += (f'<div class="v2-rule" style="margin-top:12px;padding-top:9px;border-top:1px solid #3A4048;'
                    f'font-size:13px;line-height:1.5;color:{R._V2_ON_BLACK};">Feedback and tips are welcome. '
                    f'Reply to this email or write to <a href="mailto:{_esc(addr)}" style="color:#FFFFFF;'
                    f'font-weight:700;">{_esc(addr)}</a>.</div>')
    signoff = R._v2_gap('<table width="100%" cellpadding="0" cellspacing="0" border="0" class="v2-card v2-signoff" '
                        f'style="background:{R._V2_BLACK};"><tr><td class="v2-in" style="padding:16px 20px 14px;'
                        f'font-family:{SANS};">{signoff}</td></tr></table>')
    footer = (R._v2_footer(ctx, now)
              .replace("Korea Daily Brief as a member", "Korea Week in Review as a member")
              .replace(">Read online</a>", ">Today&#8217;s brief</a>"))

    body = masthead + "".join(R._v2_card(s) for s in sections) + '<!--c-->' + signoff + '<!--/c-->' + footer
    body = R._v2_finish(body)
    words = R._count_rendered_words(R._v2_unchrome(body))
    body = body.replace("%%READMIN%%", str(max(1, round(words / 250))))

    html = f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>Korea Week in Review, {_esc(weekly.get("week_label", ""))}</title>
<style type="text/css">
    p, div, td {{ word-wrap:break-word; overflow-wrap:break-word; }}
</style>
</head>
<body style="margin:0;padding:0;background:#F2F3F5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0;padding:0;background:#F2F3F5;">
<tr><td align="center" valign="top" style="padding:0;">
<!--[if mso]><table width="680" cellpadding="0" cellspacing="0" border="0" align="center"><tr><td><![endif]-->
<table role="presentation" class="wrapper" width="680" cellpadding="0" cellspacing="0" border="0" align="center" style="width:100%;max-width:680px;margin:0 auto;background:#FFFFFF;font-family:Arial,Helvetica,sans-serif;box-shadow:0 2px 20px rgba(0,0,0,0.08);">
<tr><td style="padding:0;">
{body}
</td></tr>
</table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr>
</table>
</body>
</html>"""
    return R._v2_page(html, re.sub(r"\s+", " ", str(weekly.get("re_line") or "")).strip(), base)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Korea Daily Brief — Week in Review")
    parser.add_argument("--no-send", action="store_true", help="Render only, no email")
    args = parser.parse_args()

    digests = _load_week_digests()
    if not digests:
        print("⚠  No daily digests found for this week. Run daily pipeline first.")
        return

    dates = [d.get("_date", "?") for d in digests]
    print(f"📅  Found {len(digests)} daily digests: {', '.join(dates)}")
    weekly = generate_weekly(digests)

    # ── Verification pass — check each top story's specifics against the source
    # daily digests; drop composites/unsupported claims (e.g. a fabricated
    # multi-nation itinerary). Best-effort: a failure removes nothing.
    try:
        from verify import verify_weekly_stories
        digests_json = json.dumps([_summarize_digest(d) for d in digests], ensure_ascii=False)
        vlog = verify_weekly_stories(weekly, digests_json)
        if vlog:
            print(f"\n🔎  Verification pass dropped {len(vlog)} unsupported weekly story(ies):")
            for m in vlog:
                print(m)
    except Exception as e:
        print(f"  ⚠  Weekly verification skipped (non-fatal): {e}")

    tz = ZoneInfo("America/New_York")
    date_slug = datetime.now(tz).strftime("%Y-%m-%d")
    json_path = Path(f"weekly_{date_slug}.json")
    json_path.write_text(json.dumps(weekly, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"📄  Weekly JSON: {json_path}")

    # The daily's English pass: outlet names in English, no Korean labels,
    # no em dashes. Prose left in Korean is reported, not rewritten.
    try:
        import english
        for w in english.apply(weekly):
            print(f"::warning title=Korean text in weekly::{w}")
    except Exception as e:                                      # noqa: BLE001
        print(f"  ⚠  English pass skipped (non-fatal): {e}")

    # The audio edition, before the email so it can carry a Listen card. The
    # MP3 goes to weekly_public/, which the workflow deploys to the site
    # beside the daily episodes. No ElevenLabs key: no card, nothing else lost.
    if not args.no_send:
        try:
            import podcast
            tz_now = datetime.now(ZoneInfo("America/New_York")).date()
            rec = podcast.produce_weekly(weekly, Path("weekly_public"), date_slug,
                                         pyongyang=pyongyang_week(digests),
                                         events=next_week_events(weekly.get("calendar_next_week"), tz_now))
            if rec:
                base = (os.environ.get("WEB_URL") or "https://andysaulim.github.io/Daily-Korea-Digest").rstrip("/")
                weekly["audio_url"] = f"{base}/{rec['file']}"
                weekly["audio_minutes"] = max(1, round(rec.get("audio_seconds", 0) / 60))
                print(f"🎧  Weekly audio: {rec.get('audio_bytes', 0):,} bytes, ~{weekly['audio_minutes']} min")
        except Exception as e:                                  # noqa: BLE001
            print(f"::warning title=Weekly audio skipped::{e}")

    html = render_weekly(weekly, digests)
    html_path = Path(f"weekly_{date_slug}.html")
    html_path.write_text(html, encoding="utf-8")
    print(f"📄  Weekly HTML: {html_path}")

    if not args.no_send:
        if os.environ.get("DIGEST_TO"):
            from send_email import send
            week_label = weekly.get("week_label", date_slug)
            # House format, the same shape as the daily's "Korea Daily Brief
            # | Tuesday, September 8, 2026": name first, because that is what
            # a reader filters and searches on, then the period it covers.
            # The RE: line used to be appended and pushed the subject past
            # what any client shows, burying the name it starts with.
            subject = f"Korea Week in Review | {week_label}"
            send(html, subject=subject)
            print("📧  Weekly email sent")
        else:
            print("⚠  DIGEST_TO not set — skipping email")
    else:
        print("  --no-send: skipping email")

    print("\n✅  Week in Review done.\n")


if __name__ == "__main__":
    main()
