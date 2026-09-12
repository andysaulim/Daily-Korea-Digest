"""
Korea Daily Brief — Week in Review
Synthesizes Saturday-through-Friday daily digests into a "Top 10" weekly edition.
Run: python weekly.py [--no-send]
Triggered Fridays at 5:00 PM ET via GitHub Actions, or manually.
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
- Return ONLY valid JSON. No markdown fences, no preamble."""


WEEKLY_USER_PROMPT_TEMPLATE = """Today is {date_str} (Friday). Synthesize this week's daily digests (Saturday through Friday) into a Week in Review.

DAILY DIGESTS THIS WEEK:
{digests_json}

Return a JSON object with:
- week_label: string (e.g. "May 17-23, 2026")
- re_line: 1-sentence summary of the week's most important development (under 80 chars)
- top_10: array of the 10 most consequential stories this week, ranked by significance. Each: rank (1-10), headline (concise, factual), body (2-3 sentences synthesizing the week's coverage of THIS ONE story), first_reported (date string), category (e.g. "Security", "Diplomacy", "Economy", "DPRK", "US-ROK", "Trade"), sources (array of outlet names that covered this story). GROUNDING: each story must correspond to actual coverage in the daily digests, and every specific in the body (dates, destinations, names, figures) must appear in that coverage — do NOT combine two different stories into one, and do NOT enrich a story with details from elsewhere in the week. If fewer than 10 consequential stories occurred, return as many as the data supports — do not pad with trivial items.
- dprk_statements: object summarizing the week's DPRK official statements — kim_appearances (count of days Kim appeared), notable_quotes (up to 3 most significant official quotes from the week, each with speaker and quote text), watch_flags (count of days with watch flag), silence_days (count of days with KCNA silence), summary (2-3 sentences on the week's official posture)
- bp_changes: array of facility status changes this week (only facilities whose status or note changed). Each: name, status_start, status_end, change_summary (1 sentence)
- market_weekly: object with kospi_open (Monday value), kospi_close (Friday value), kospi_change_pct (string e.g. "+1.2%"), krw_open (Monday), krw_close (Friday), krw_change_pct (string), bok_action (null or description of any rate decision)
- sentiment_weekly: object with approval_start (Monday presidential approval %), approval_end (Friday), party_ruling (latest %), party_opposition (latest %), source (e.g. "Gallup Korea")
- calendar_next_week: array of 3-5 key events in the coming 7 days. Each: date, headline, detail (1 sentence)
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
            "krw_usd": (d.get("market_indicators") or {}).get("krw_usd"),
        },
        "sentiment": {
            "presidential_approval": (d.get("sentiment") or {}).get("presidential_approval"),
            "party_ruling": (d.get("sentiment") or {}).get("party_ruling"),
            "party_opposition": (d.get("sentiment") or {}).get("party_opposition"),
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
        "calendar_watch": d.get("calendar_watch") or [],
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


def render_weekly(weekly: dict) -> str:
    """Render the Week in Review in the daily brief's house style.

    Everything visual here is imported from render.py rather than restated.
    This renderer predates the daily's redesign and had kept the older look:
    section titles set as navy type over a hairline rule, a gold accent
    (#C9A96E, #D4AC0D) the daily no longer uses anywhere, a green-black panel
    where the daily's is navy, a centred masthead where the daily's is left
    aligned, and no dark mode at all. Opened next to a daily issue the two
    read as separate publications.

    Importing the palette, the section bar and the dark-mode block means they
    cannot drift apart again: a change to the edition's identity reaches the
    weekly on its next run, with nothing to remember.
    """
    from html import escape as _esc
    from render import (_sec_label, _dark_mode_css, BAND, NAVY, INK, MUTE,
                        BODY_INK, NAVY_PANEL, BLUE_ON_NAVY, UP_GREEN, DOWN_RED)

    SERIF = "Georgia,'Times New Roman',serif"
    SANS = "Arial,Helvetica,sans-serif"
    PANEL = "#F5F7FA"          # the daily's panel grey
    RULE = "#E8E8E8"

    week_label = _esc(weekly.get("week_label", "This Week"))
    re_line = _esc(weekly.get("re_line", ""))
    bottom_line = _esc(weekly.get("bottom_line", ""))

    def _sec(label: str, body: str) -> str:
        """One section: the house bar, then its contents, on the .sec ground."""
        return (f'<div class="sec" style="padding:20px 32px;background:#FFFFFF;'
                f'border-bottom:1px solid {RULE};">{_sec_label(label)}{body}</div>')

    # ── Top 10 ───────────────────────────────────────────────────────────
    top_html = ""
    for story in (weekly.get("top_10") or []):
        rank = _esc(str(story.get("rank", "")))
        headline = _esc(story.get("headline", ""))
        body = _esc(story.get("body", ""))
        category = _esc(story.get("category", ""))
        sources = ", ".join(_esc(s) for s in (story.get("sources") or []))
        top_html += f"""
        <tr><td style="padding:14px 0;border-bottom:1px solid {RULE};">
            <table cellpadding="0" cellspacing="0" border="0"><tr>
                <td style="vertical-align:top;padding-right:12px;">
                    <div style="background:{NAVY};color:#FFFFFF;width:26px;height:26px;text-align:center;line-height:26px;font-family:{SANS};font-size:12px;font-weight:700;">{rank}</div>
                </td>
                <td style="vertical-align:top;">
                    <div style="font-family:{SERIF};font-size:15px;font-weight:700;color:{INK};line-height:1.35;">{headline}</div>
                    <div style="font-family:{SANS};font-size:10px;font-weight:700;color:{MUTE};text-transform:uppercase;letter-spacing:1.5px;margin-top:3px;">{category}</div>
                    <div style="font-family:{SERIF};font-size:13px;color:{BODY_INK};line-height:1.55;margin-top:6px;">{body}</div>
                    <div style="font-family:{SANS};font-size:11px;color:{MUTE};margin-top:5px;">{sources}</div>
                </td>
            </tr></table>
        </td></tr>"""

    # ── DPRK week summary ────────────────────────────────────────────────
    dprk = weekly.get("dprk_statements") or {}
    dprk_html = ""
    if dprk:
        kim_ct = _esc(str(dprk.get("kim_appearances", 0)))
        watch_ct = _esc(str(dprk.get("watch_flags", 0)))
        silence_ct = _esc(str(dprk.get("silence_days", 0)))
        summary = _esc(dprk.get("summary", ""))
        quotes_html = ""
        for q in (dprk.get("notable_quotes") or [])[:3]:
            speaker = _esc(q.get("speaker", ""))
            quote = _esc(q.get("quote", ""))
            if quote:
                quotes_html += f"""
                <div style="padding:9px 13px;background:rgba(255,255,255,0.05);border-left:3px solid {BLUE_ON_NAVY};margin-top:9px;">
                    <div style="font-family:{SERIF};font-size:13px;color:#E8E6E1;line-height:1.5;">&ldquo;{quote}&rdquo;</div>
                    <div style="font-family:{SANS};font-size:11px;color:{BLUE_ON_NAVY};margin-top:4px;">{speaker}</div>
                </div>"""
        dprk_html = f"""
        <table width="100%" cellpadding="0" cellspacing="0" border="0" class="kcna-dark" style="background:{NAVY_PANEL};">
            <tr><td style="padding:16px 20px;">
                <div style="font-family:{SANS};font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:2px;color:{BLUE_ON_NAVY};margin-bottom:10px;">DPRK Official Statements &middot; Week Summary</div>
                <div style="font-family:{SANS};font-size:11px;color:rgba(255,255,255,0.70);margin-bottom:9px;">Kim appearances: {kim_ct} &nbsp;&middot;&nbsp; Watch flags: {watch_ct} &nbsp;&middot;&nbsp; Silence days: {silence_ct}</div>
                <div style="font-family:{SERIF};font-size:13px;color:#E8E6E1;line-height:1.55;">{summary}</div>
                {quotes_html}
            </td></tr>
        </table>"""

    # ── Next week ────────────────────────────────────────────────────────
    cal_html = ""
    for event in (weekly.get("calendar_next_week") or []):
        date = _esc(event.get("date", ""))
        headline = _esc(event.get("headline", ""))
        detail = _esc(event.get("detail", ""))
        cal_html += f"""
        <tr><td style="padding:9px 0;border-bottom:1px solid {RULE};">
            <div style="font-family:{SERIF};font-size:14px;color:{INK};line-height:1.4;"><strong style="color:{NAVY};">{date}</strong> &mdash; {headline}</div>
            <div style="font-family:{SERIF};font-size:12px;color:{BODY_INK};margin-top:3px;line-height:1.5;">{detail}</div>
        </td></tr>"""

    # ── Markets ──────────────────────────────────────────────────────────
    mkt = weekly.get("market_weekly") or {}
    mkt_html = ""
    if mkt:
        def _signed(raw):
            """Colour a weekly move the way the daily strip does: green up,
            red down, ink when there is no sign to read."""
            text = _esc(str(raw if raw not in (None, "") else "—"))
            stripped = text.lstrip()
            if stripped.startswith("+"):
                return text, UP_GREEN
            if stripped.startswith(("-", "−")):
                return text, DOWN_RED
            return text, INK

        kospi_txt, kospi_col = _signed(mkt.get("kospi_change_pct"))
        krw_txt, krw_col = _signed(mkt.get("krw_change_pct"))
        bok = _esc(mkt.get("bok_action") or "No change")
        _cell = (f'font-family:{SANS};font-size:10px;font-weight:700;'
                 f'text-transform:uppercase;letter-spacing:1.5px;color:{MUTE};')
        mkt_html = f"""
        <table width="100%" cellpadding="0" cellspacing="0" border="0" class="mkt-table" style="background:{PANEL};margin-top:16px;">
            <tr>
                <td style="padding:13px 16px;text-align:center;width:33%;">
                    <div style="{_cell}">KOSPI</div>
                    <div style="font-family:{SERIF};font-size:17px;font-weight:700;color:{kospi_col};margin-top:3px;">{kospi_txt}</div>
                </td>
                <td style="padding:13px 16px;text-align:center;width:33%;border-left:1px solid {RULE};border-right:1px solid {RULE};">
                    <div style="{_cell}">KRW/USD</div>
                    <div style="font-family:{SERIF};font-size:17px;font-weight:700;color:{krw_col};margin-top:3px;">{krw_txt}</div>
                </td>
                <td style="padding:13px 16px;text-align:center;width:33%;">
                    <div style="{_cell}">BOK</div>
                    <div style="font-family:{SERIF};font-size:13px;color:{INK};margin-top:5px;">{bok}</div>
                </td>
            </tr>
        </table>"""

    tz = ZoneInfo("America/New_York")
    gen_time = datetime.now(tz).strftime("%-I:%M %p ET")
    story_count = _esc(str(weekly.get("story_count_total", 0)))

    _re_block = (
        f'<div style="margin-top:14px;padding-top:12px;'
        f'border-top:1px solid rgba(255,255,255,0.28);font-family:{SERIF};'
        f'font-size:13px;color:rgba(255,255,255,0.92);line-height:1.55;">'
        f'<strong style="color:#FFFFFF;font-size:11px;letter-spacing:1.5px;'
        f'font-family:{SANS};">RE:</strong>&nbsp; {re_line}</div>'
    ) if re_line else ""

    sections = "".join([
        _sec("Top 10 Stories",
             f'<table width="100%" cellpadding="0" cellspacing="0" border="0">{top_html}</table>'),
        _sec("North Korea &amp; Markets", dprk_html + mkt_html) if (dprk_html or mkt_html) else "",
        _sec("Next Week",
             f'<table width="100%" cellpadding="0" cellspacing="0" border="0">{cal_html}</table>')
        if cal_html else "",
        _sec("Bottom Line",
             f'<div style="padding:16px;background:{PANEL};border-left:3px solid {NAVY};">'
             f'<div style="font-family:{SERIF};font-size:14px;color:{INK};'
             f'line-height:1.6;">{bottom_line}</div></div>')
        if bottom_line else "",
    ])

    return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>Korea Week in Review &middot; {week_label}</title>
<style type="text/css">
{_dark_mode_css()}
    @media screen and (max-width: 600px) {{
      .wrapper {{ width:100% !important; max-width:680px !important; }}
      .sec {{ padding:16px 14px !important; }}
    }}
</style>
</head>
<body style="margin:0;padding:0;background:#F0F0F0;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#F0F0F0;">
<tr><td align="center" style="padding:20px 0;">
<table role="presentation" class="wrapper" width="680" cellpadding="0" cellspacing="0" border="0" align="center" style="width:680px;max-width:100%;margin:0 auto;background:#FFFFFF;font-family:{SANS};box-shadow:0 2px 20px rgba(0,0,0,0.08);">

<tr><td style="padding:0;">

  <div bgcolor="{BAND}" style="background-color:{BAND};color:#fff;padding:16px 32px;border-bottom:1px solid rgba(255,255,255,0.18);" class="sec mast-band">
    <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
      <td class="mast-main" style="vertical-align:top;">
        <div style="font-family:{SANS};font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:rgba(255,255,255,0.78);margin-bottom:7px;">CSIS Korea Chair</div>
        <h1 style="margin:0 0 4px 0;font-size:26px;font-weight:700;font-family:{SERIF};color:#fff;letter-spacing:0.5px;">Week in Review</h1>
        <div style="margin-top:2px;font-size:16px;font-weight:400;color:rgba(255,255,255,0.85);font-family:{SERIF};">{week_label}</div>
      </td>
      <td class="mast-meta" style="vertical-align:bottom;text-align:right;">
        <div style="font-family:{SANS};font-size:11px;letter-spacing:0.5px;color:rgba(255,255,255,0.72);white-space:nowrap;">{story_count} articles this week</div>
      </td>
    </tr></table>
    {_re_block}
  </div>

  {sections}

  <div class="footer" style="background:{NAVY};padding:22px 32px;text-align:center;">
    <div style="font-family:{SERIF};font-size:12px;line-height:1.6;color:rgba(255,255,255,0.80);">
      You are receiving the Korea Week in Review as a member of the CSIS Korea Chair distribution list.
    </div>
    <div style="font-family:{SANS};font-size:10px;text-transform:uppercase;letter-spacing:2px;color:rgba(255,255,255,0.45);line-height:2;margin-top:10px;">
      CSIS Korea Chair &nbsp;&middot;&nbsp; Week in Review &nbsp;&middot;&nbsp; Generated {gen_time}
    </div>
  </div>

</td></tr>
</table>
</td></tr></table>
</body></html>"""


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

    html = render_weekly(weekly)
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
