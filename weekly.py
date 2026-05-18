"""
Korea Daily Brief — Weekly Summary Generator
Synthesizes the past 5-7 daily digests into a concise "Week in Review" edition.
Run: python weekly.py [--no-send]
Designed to run Fridays via a separate cron or manual trigger.
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
- Never fabricate. Every claim must trace to the daily digest data provided.
- No editorializing. Present patterns and let readers draw conclusions.
- Highlight what CHANGED this week, not what remained stable.
- Return ONLY valid JSON. No markdown fences, no preamble."""


WEEKLY_USER_PROMPT_TEMPLATE = """Today is {date_str} (Friday). Synthesize this week's daily digests into a Week in Review.

DAILY DIGESTS THIS WEEK:
{digests_json}

Return a JSON object with:
- week_label: string (e.g. "May 5-9, 2026")
- re_line: 1-sentence summary of the week's most important development (under 80 chars)
- top_5: array of the 5 most consequential stories this week. Each: headline, body (2-3 sentences synthesizing the week's coverage), first_reported (date string), category, significance (1 sentence — what decision or timeline this affects)
- escalation_trend: object with score_start (Monday tension index), score_end (Friday), direction (up/down/stable), driver (1 sentence explaining what moved it)
- kcna_weekly: object summarizing the week's KCNA output — total_articles (sum), dominant_themes (top 3 topics across the week), kim_appearances (count), notable_shifts (1-2 sentences on rhetoric changes from Monday to Friday), silence_days (count of days with 0 KCNA data)
- bp_changes: array of facility status changes this week (only facilities whose status or note changed from Monday to Friday). Each: name, status_start, status_end, change_summary (1 sentence)
- market_weekly: object with kospi_change (e.g. "+1.2%"), krw_change (e.g. "-0.3%"), bok_action (null or description of any rate decision)
- deals_weekly: array of new US-Korea deals announced this week (empty if none). Each: company, value, sector
- calendar_next_week: array of 3-5 key events in the coming 7 days. Each: date, headline, detail (1 sentence)
- bottom_line: 2-3 sentences. The single most important takeaway from this week and what to watch next week. Be ruthlessly concise.
- story_count_total: total Tier 1 articles processed across all daily digests this week
"""


def _load_week_digests() -> list[dict]:
    """Load daily digest JSON files from the past 7 days."""
    tz = ZoneInfo("America/New_York")
    today = datetime.now(tz).date()
    digests = []
    for days_back in range(7, 0, -1):
        d = today - timedelta(days=days_back)
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
    return digests


def _summarize_digest(d: dict) -> dict:
    """Extract key fields from a daily digest for the weekly prompt (reduce token count)."""
    return {
        "date": d.get("_date", "unknown"),
        "re_line": d.get("re_line", ""),
        "top_stories": [
            {"headline": s.get("headline", ""), "category": s.get("category_tag", ""), "source": s.get("source", "")}
            for s in (d.get("top_stories") or [])
        ],
        "overnight_headlines": [s.get("headline", "") for s in (d.get("overnight_items") or [])],
        "kcna_delta": {
            "silence_today": (d.get("kcna_delta") or {}).get("silence_today"),
            "watch_flag": (d.get("kcna_delta") or {}).get("watch_flag"),
            "output_volume": (d.get("kcna_delta") or {}).get("output_volume"),
            "bottom_line": (d.get("kcna_delta") or {}).get("bottom_line"),
            "propaganda_focus": (d.get("kcna_delta") or {}).get("propaganda_focus"),
            "kim_appearance_today": (d.get("kcna_delta") or {}).get("kim_appearance_today"),
        },
        "bp_changes": [
            {"name": loc.get("name"), "status": loc.get("status")}
            for loc in (d.get("bp_locations") or [])
            if loc.get("status") in ("elevated", "alert")
        ],
        "market_indicators": {
            "kospi": (d.get("market_indicators") or {}).get("kospi"),
            "krw_usd": (d.get("market_indicators") or {}).get("krw_usd"),
        },
        "deals": [
            {"company": deal.get("company"), "value": deal.get("value"), "sector": deal.get("sector")}
            for deal in ((d.get("us_korea_deals") or {}).get("investment_package") or {}).get("known_deals") or []
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
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        system=[{
            "type": "text",
            "text": WEEKLY_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        for text in stream.text_stream:
            collected.append(text)
    elapsed = time.time() - t0
    raw_text = "".join(collected)
    print(f"    ⏱  Weekly generation: {elapsed:.0f}s")

    # Strip markdown fences
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    return json.loads(text)


def render_weekly(weekly: dict) -> str:
    """Render weekly summary as HTML email."""
    week_label = weekly.get("week_label", "This Week")
    re_line = weekly.get("re_line", "")
    bottom_line = weekly.get("bottom_line", "")

    top_5_html = ""
    for i, story in enumerate(weekly.get("top_5") or [], 1):
        top_5_html += f"""
        <tr><td style="padding:12px 0; border-bottom:1px solid #eee;">
            <span style="display:inline-block; background:#1a1f36; color:#fff; border-radius:50%; width:22px; height:22px; text-align:center; line-height:22px; font-size:12px; margin-right:8px;">{i}</span>
            <strong>{story.get('headline', '')}</strong>
            <span style="color:#888; font-size:12px; margin-left:8px;">{story.get('category', '')}</span>
            <br><span style="color:#555; font-size:14px; line-height:1.5; display:block; margin-top:4px; padding-left:30px;">{story.get('body', '')}</span>
        </td></tr>"""

    calendar_html = ""
    for event in (weekly.get("calendar_next_week") or []):
        calendar_html += f"""
        <tr><td style="padding:6px 0; font-size:14px;">
            <strong>{event.get('date', '')}</strong> — {event.get('headline', '')}
        </td></tr>"""

    kcna = weekly.get("kcna_weekly") or {}
    kcna_html = ""
    if kcna:
        themes = ", ".join(kcna.get("dominant_themes") or [])
        kcna_html = f"""
        <table width="100%" style="margin:16px 0; background:#1a1f36; border-radius:8px; padding:16px;">
            <tr><td style="color:#fff; font-weight:600; padding:8px 16px;">KCNA Weekly</td></tr>
            <tr><td style="color:#ccc; padding:4px 16px; font-size:13px;">Articles: {kcna.get('total_articles', 'N/A')} | Kim appearances: {kcna.get('kim_appearances', 0)} | Silence days: {kcna.get('silence_days', 0)}</td></tr>
            <tr><td style="color:#ccc; padding:4px 16px; font-size:13px;">Themes: {themes}</td></tr>
            <tr><td style="color:#e2e8f0; padding:8px 16px; font-size:13px;">{kcna.get('notable_shifts', '')}</td></tr>
        </table>"""

    escalation = weekly.get("escalation_trend") or {}
    esc_html = ""
    if escalation:
        direction_arrow = {"up": "↑", "down": "↓", "stable": "→"}.get(escalation.get("direction", ""), "→")
        esc_html = f"""
        <div style="background:#f8f9fa; border-left:4px solid #1a1f36; padding:12px 16px; margin:16px 0; border-radius:0 6px 6px 0;">
            <strong>Tension Trend:</strong> {escalation.get('score_start', '?')}/10 → {escalation.get('score_end', '?')}/10 {direction_arrow}
            <br><span style="color:#555; font-size:13px;">{escalation.get('driver', '')}</span>
        </div>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Korea Daily Brief — Week in Review</title></head>
<body style="margin:0; padding:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; background:#f5f6f8;">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:640px; margin:0 auto; background:#fff;">
    <tr><td style="background:#1a1f36; padding:32px 24px; text-align:center;">
        <div style="font-size:11px; text-transform:uppercase; letter-spacing:1.8px; color:#8a8fa8;">CSIS Korea Chair</div>
        <h1 style="color:#fff; font-size:26px; margin:8px 0 4px; font-weight:700;">Week in Review</h1>
        <div style="color:#9ca0b8; font-size:15px;">{week_label}</div>
    </td></tr>
    <tr><td style="padding:24px;">
        <div style="background:#f0f4ff; border-radius:8px; padding:16px; margin-bottom:24px;">
            <strong style="color:#1a1f36;">RE:</strong> <span style="color:#333;">{re_line}</span>
        </div>

        <h2 style="font-size:18px; color:#1a1f36; margin:24px 0 12px; border-bottom:2px solid #1a1f36; padding-bottom:8px;">Top 5 Stories</h2>
        <table width="100%" cellpadding="0" cellspacing="0">{top_5_html}</table>

        {esc_html}
        {kcna_html}

        <h2 style="font-size:18px; color:#1a1f36; margin:24px 0 12px; border-bottom:2px solid #1a1f36; padding-bottom:8px;">Next Week</h2>
        <table width="100%" cellpadding="0" cellspacing="0">{calendar_html}</table>

        <div style="background:#1a1f36; border-radius:8px; padding:20px; margin-top:24px; color:#e2e8f0; font-size:14px; line-height:1.6;">
            <strong style="color:#fff;">Bottom Line</strong><br>{bottom_line}
        </div>
    </td></tr>
    <tr><td style="padding:16px 24px; text-align:center; color:#999; font-size:12px; border-top:1px solid #eee;">
        Korea Daily Brief — CSIS Korea Chair | Week in Review Edition
    </td></tr>
</table>
</body></html>"""


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Korea Daily Brief — Weekly Summary")
    parser.add_argument("--no-send", action="store_true", help="Render only, no email")
    args = parser.parse_args()

    digests = _load_week_digests()
    if not digests:
        print("⚠  No daily digests found for this week. Run daily pipeline first.")
        return

    print(f"📅  Found {len(digests)} daily digests for this week")
    weekly = generate_weekly(digests)

    # Save JSON
    tz = ZoneInfo("America/New_York")
    date_slug = datetime.now(tz).strftime("%Y-%m-%d")
    json_path = Path(f"weekly_{date_slug}.json")
    json_path.write_text(json.dumps(weekly, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"📄  Weekly JSON: {json_path}")

    # Render HTML
    html = render_weekly(weekly)
    html_path = Path(f"weekly_{date_slug}.html")
    html_path.write_text(html, encoding="utf-8")
    print(f"📄  Weekly HTML: {html_path}")

    # Also save daily digest JSONs for next week's reference
    for d in digests:
        d_date = d.get("_date", "unknown")
        d_path = Path(f"public/digest_{d_date}.json")
        d_path.parent.mkdir(exist_ok=True)
        if not d_path.exists():
            d.pop("_date", None)
            d_path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    # Send
    if not args.no_send:
        if os.environ.get("DIGEST_TO"):
            from send_email import send
            week_label = weekly.get("week_label", date_slug)
            re_short = weekly.get("re_line", "")[:80]
            subject = f"Korea Weekly Review · {week_label} — {re_short}"
            send(html, subject=subject)
            print("📧  Weekly email sent")
        else:
            print("⚠  DIGEST_TO not set — skipping email")
    else:
        print("  --no-send: skipping email")

    print("\n✅  Weekly summary done.\n")


if __name__ == "__main__":
    main()
