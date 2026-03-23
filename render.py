"""
Korea Daily Brief — HTML Renderer
CSIS Korea Chair
Takes structured digest JSON from Claude and renders a styled HTML email.
Uses table-based layout for maximum email client compatibility.
"""
from datetime import datetime, timezone


def _esc(text) -> str:
    if text is None or text == "":
        return ""
    text = str(text)
    if text == "None":
        return ""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _color_bar(css_class: str) -> str:
    colors = {
        "cb-navy": "#1B2A4A", "cb-red": "#C0392B", "cb-lt": "#2980B9",
        "cb-mid": "#7F8C8D", "cb-nkch": "#8E44AD", "cb-tech": "#16A085",
        "cb-biz": "#D4AC0D",
    }
    return colors.get(css_class, "#1B2A4A")


def _signal_badge(signal_type: str) -> str:
    badge_colors = {
        "ESCALATION": "#C0392B", "ANOMALY": "#8E44AD", "DEVELOPMENT": "#2980B9",
        "CONFIRMATION": "#27AE60", "CONTEXT": "#7F8C8D",
    }
    color = badge_colors.get(signal_type, "#7F8C8D")
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:3px;'
        f'font-size:11px;font-weight:600;color:#fff;background:{color};'
        f'letter-spacing:0.5px;">{_esc(signal_type)}</span>'
    )


def _social_badge(badge_class: str) -> str:
    colors = {"sb-p": "#1B2A4A", "sb-r": "#C0392B", "sb-s": "#8E44AD"}
    return colors.get(badge_class, "#1B2A4A")


def _arrow(val) -> str:
    try:
        val = float(val)
    except (TypeError, ValueError):
        return '<span style="color:#7F8C8D;">—</span>'
    if val > 0:
        return f'<span style="color:#27AE60;">&#9650; +{val:.1f}%</span>'
    elif val < 0:
        return f'<span style="color:#C0392B;">&#9660; {val:.1f}%</span>'
    return '<span style="color:#7F8C8D;">— flat</span>'




def _link_or_text(text: str, url: str, style: str = "color:#1B2A4A;text-decoration:none;") -> str:
    """Render as <a> only if url is a real link, otherwise plain text.
    NOTE: `text` should already be HTML-escaped by the caller via _esc()."""
    if url and url != "#" and url.startswith("http"):
        return f'<a href="{_esc(url)}" style="{style}">{text}</a>'
    return text


# ── Section padding helper (responsive via class) ────────────────────────
_SEC = 'style="padding:14px 32px;border-bottom:1px solid #E0E0E0;" class="sec"'
_SEC_BG = lambda bg: f'style="padding:14px 32px;background:{bg};border-bottom:1px solid #E0E0E0;" class="sec"'
_H2 = lambda color: f'style="margin:0 0 8px 0;font-size:12px;color:{color};text-transform:uppercase;letter-spacing:1px;font-family:Arial,sans-serif;"'
_PILL = lambda bg: f'style="display:inline-block;background:{bg};color:#fff;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1.2px;padding:4px 12px;border-radius:12px;font-family:Arial,sans-serif;margin-bottom:8px;"'


def _estimate_word_count(digest: dict) -> int:
    """Rough word count across all text fields for 'X min read' estimate."""
    words = 0
    for mi in (digest.get("morning_memo") or []):
        words += len(str(mi).split())
    words += len(str(digest.get("re_line", "")).split())
    for section_key in ("top_stories", "overnight_items", "also_today", "business_economy",
                         "opeds_today", "academic_today", "social_statements",
                         "northeast_asia"):
        for item in (digest.get(section_key) or []):
            for field in ("body", "body_text", "summary", "detail", "quote_text",
                          "so_what", "pattern_note", "central_argument", "analyst_note"):
                words += len(str(item.get(field, "")).split())
    kcna = digest.get("kcna_delta") or {}
    for field in ("bottom_line", "doctrinal_shift"):
        words += len(str(kcna.get(field, "")).split())
    return words


def render(digest: dict) -> str:
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    date_str = now.strftime("%A, %B %-d, %Y")  # Thursday, March 20, 2026
    gen_time = now.strftime("%-I:%M %p ET")
    re_line = _esc(digest.get("re_line", ""))
    word_count = _estimate_word_count(digest)
    read_min = max(1, round(word_count / 250))

    web_url = digest.get("web_url", "")
    sections = []

    # ── 0. View in Browser bar ────────────────────────────────────────────
    if web_url:
        sections.append(f"""
        <div style="background:#F0F0F0;padding:6px 32px;text-align:center;font-size:11px;color:#888;" class="sec">
          Email not rendering? <a href="{_esc(web_url)}" style="color:#2980B9;text-decoration:none;">Read online &#8594;</a>
        </div>
        """)

    # ── 1. Header ────────────────────────────────────────────────────────
    sections.append(f"""
    <div style="background:#1B2A4A;color:#fff;padding:14px 32px 12px;" class="sec">
      <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
        <td style="vertical-align:top;">
          <h1 style="margin:0;font-size:24px;font-weight:700;font-family:Georgia,serif;color:#fff;letter-spacing:0.5px;">
            Korea Daily Brief
          </h1>
          <div style="margin-top:4px;font-size:11px;color:rgba(255,255,255,0.7);font-family:Arial,sans-serif;">By Andy Lim &middot; CSIS Korea Chair</div>
          <div style="margin-top:6px;font-size:18px;font-weight:700;color:rgba(255,255,255,0.95);letter-spacing:0.5px;font-family:Georgia,serif;">{_esc(date_str)}</div>
        </td>
        <td style="vertical-align:top;text-align:right;">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:rgba(255,255,255,0.6);margin-bottom:2px;">{gen_time}</div>
          <div style="font-size:10px;color:rgba(255,255,255,0.55);">{word_count:,} words &middot; {read_min} min read</div>
        </td>
      </tr></table>
      {"<div style='margin-top:10px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.15);font-size:13px;color:rgba(255,255,255,0.85);font-family:Georgia,serif;'><strong style=" + '"' + "color:rgba(255,255,255,0.5);" + '"' + ">RE:</strong> " + re_line + "</div>" if re_line else ""}
    </div>
    """)

    # ── 1b. Forward CTA ─────────────────────────────────────────────────
    sections.append("""
        <div style="padding:8px 32px;background:#F8F9FA;border-bottom:1px solid #E0E0E0;" class="sec">
          <div style="font-size:11px;color:#888;font-family:Arial,sans-serif;">
            Know someone who'd find this useful? <a href="mailto:?subject=Korea%20Daily%20Brief&amp;body=Check%20out%20the%20Korea%20Daily%20Brief%20from%20CSIS%20Korea%20Chair." style="color:#2980B9;text-decoration:none;font-weight:600;">Forward to a colleague &rarr;</a>
          </div>
        </div>
        """)

    # ── 2. Market Indicators ───────────────────────────────────────────────
    markets = digest.get("market_indicators") or {}
    if markets:
        kospi = markets.get("kospi") or {}
        brent = markets.get("brent") or {}
        krw = markets.get("usd_krw") or {}
        bok_rate = markets.get("bok_rate") or {}
        exports = markets.get("monthly_exports") or {}
        gdp = markets.get("gdp_estimate") or {}
        # Top row: KOSPI, Brent, USD/KRW
        sections.append(f"""
        <a name="markets"></a>
        <table class="mkt-table" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#1B2A4A;color:#fff;border-bottom:1px solid rgba(255,255,255,0.1);">
          <tr>
            <td width="33%" align="center" style="padding:10px 8px 12px;">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;opacity:0.6;">KOSPI</div>
              <div style="font-size:18px;font-weight:700;">{_esc(str(kospi.get("value", "—")))}</div>
              <div style="font-size:11px;">{_arrow(kospi.get("change_pct", 0))}</div>
              {"<div style='font-size:10px;opacity:0.5;margin-top:2px;'>as of " + _esc(kospi.get("as_of", "")) + "</div>" if kospi.get("as_of") else ""}
            </td>
            <td width="34%" align="center" style="padding:10px 8px 12px;border-left:1px solid rgba(255,255,255,0.15);border-right:1px solid rgba(255,255,255,0.15);">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;opacity:0.6;">Brent Crude</div>
              <div style="font-size:18px;font-weight:700;">${_esc(str(brent.get("value", "—")))}</div>
              <div style="font-size:11px;">{_arrow(brent.get("change_pct", 0))}</div>
              {"<div style='font-size:10px;opacity:0.5;margin-top:2px;'>as of " + _esc(brent.get("as_of", "")) + "</div>" if brent.get("as_of") else ""}
            </td>
            <td width="33%" align="center" style="padding:10px 8px 12px;">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;opacity:0.6;">USD/KRW</div>
              <div style="font-size:18px;font-weight:700;">{_esc(str(krw.get("value", "—")))}</div>
              <div style="font-size:11px;">{_arrow(krw.get("change_pct", 0))}</div>
              {"<div style='font-size:10px;opacity:0.5;margin-top:2px;'>as of " + _esc(krw.get("as_of", "")) + "</div>" if krw.get("as_of") else ""}
            </td>
          </tr>
        </table>
        <table class="mkt-table" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#162340;color:#fff;border-bottom:1px solid rgba(255,255,255,0.08);">
          <tr>
            <td width="33%" align="center" style="padding:8px 8px 10px;">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;opacity:0.6;">BOK Rate</div>
              <div style="font-size:15px;font-weight:700;">{_esc(str(bok_rate.get("value", "—")))}</div>
              <div style="font-size:10px;opacity:0.6;">{_esc(str(bok_rate.get("last_change", "")))}</div>
            </td>
            <td width="34%" align="center" style="padding:8px 8px 10px;border-left:1px solid rgba(255,255,255,0.1);border-right:1px solid rgba(255,255,255,0.1);">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;opacity:0.6;">Exports{" (" + _esc(exports.get("month", "")) + ")" if exports.get("month") else " (Monthly)"}</div>
              <div style="font-size:15px;font-weight:700;">{_esc(str(exports.get("value", "—")))}</div>
              <div style="font-size:10px;">{_arrow(exports.get("change_pct", 0))}</div>
              {"<div style='font-size:10px;opacity:0.5;margin-top:2px;'>as of " + _esc(exports.get("as_of", exports.get("month", ""))) + "</div>" if exports.get("as_of") or exports.get("month") else ""}
            </td>
            <td width="33%" align="center" style="padding:8px 8px 10px;">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;opacity:0.6;">GDP Est. (QoQ)</div>
              <div style="font-size:15px;font-weight:700;">{_esc(str(gdp.get("value", "—")))}</div>
              <div style="font-size:10px;opacity:0.6;">{_esc(str(gdp.get("period", "")))}</div>
            </td>
          </tr>
        </table>
        """)

    # ── 3. Morning Memo (top 3 at a glance) ─────────────────────────────────
    memo_items = digest.get("morning_memo") or []
    if memo_items:
        memo_html = ""
        for mi in memo_items[:3]:
            memo_text = _esc(mi) if isinstance(mi, str) else _esc(mi.get("text", "") if isinstance(mi, dict) else str(mi or ""))
            memo_html += f"""
            <div style="margin-bottom:8px;padding-left:12px;border-left:3px solid #1B2A4A;">
              <div style="font-size:14px;line-height:1.5;color:#333;font-family:Georgia,serif;">{memo_text}</div>
            </div>"""
        sections.append(f"""
        <div style="padding:14px 32px;border-bottom:2px solid #1B2A4A;" class="sec">
          <a name="memo"></a><span {_PILL("#1B2A4A")}>Morning Memo</span>
          {memo_html}
        </div>
        """)

    # ── 4. Top Stories ────────────────────────────────────────────────────
    top_stories = digest.get("top_stories") or []
    if top_stories:
        stories_html = ""
        for story in top_stories:
            cat = _esc(story.get("category_tag", story.get("category", "")))
            headline = _esc(story.get("headline", ""))
            body = _esc(story.get("body", ""))
            so_what = _esc(story.get("so_what", ""))
            pattern = _esc(story.get("pattern_note", ""))
            src_line = _esc(story.get("src_line", story.get("source", "")))
            url = story.get("url", "")
            stories_html += f"""
            <div class="story-card" style="margin-bottom:12px;padding:10px 12px;background:#F8F9FA;border-radius:4px;border-left:4px solid #1B2A4A;">
              <h3 style="margin:0 0 6px 0;font-size:15px;color:#1B2A4A;font-family:Georgia,serif;">
                {_link_or_text(headline, url)}
              </h3>
              <p style="margin:0 0 8px 0;font-size:13px;line-height:1.5;color:#333;">{body}</p>
              {"<p style='margin:0 0 6px 0;font-size:12px;line-height:1.4;color:#2980B9;'><strong>So what:</strong> " + so_what + "</p>" if so_what else ""}
              {"<p style='margin:0 0 6px 0;font-size:12px;line-height:1.4;color:#8E44AD;'><strong>Pattern:</strong> " + pattern + "</p>" if pattern else ""}
              <div style="font-size:11px;color:#999;">{src_line}</div>
            </div>"""
        sections.append(f"""
        <div {_SEC}>
          <a name="top-stories"></a><span {_PILL("#2980B9")}>Top Stories</span>
          {stories_html}
        </div>
        """)

    # ── 4b. Overnight Flash (high-priority overnight items) ────────────
    overnight = digest.get("overnight_items") or []
    if overnight:
        _cat_colors_flash = {"NK-Russia": "#C0392B", "ROK Policy": "#1B2A4A", "US-Korea": "#2980B9",
                       "DPRK": "#8E44AD", "Security": "#E67E22", "Business": "#D4AC0D",
                       "Japan-Korea": "#1B6A4A", "China-Korea": "#8B0000", "Trilateral": "#2E4057"}
        flash_html = ""
        for item in overnight:
            cat = _esc(item.get("category", ""))
            headline = _esc(item.get("headline", ""))
            body = _esc(item.get("body_text", ""))
            src = _esc(item.get("source", ""))
            url = item.get("url", "")
            bar_color = _cat_colors_flash.get(item.get("category", ""), "#1B2A4A")
            flash_html += f"""
            <div style="margin-bottom:10px;padding-left:12px;border-left:3px solid {bar_color};">
              <div style="font-size:11px;color:#C0392B;text-transform:uppercase;font-weight:600;">{cat} &middot; {src}</div>
              <div style="font-size:13px;font-weight:600;color:#1B2A4A;">
                {_link_or_text(headline, url)}
              </div>
              <div style="font-size:12px;line-height:1.4;color:#555;">{body}</div>
            </div>"""
        sections.append(f"""
        <div {_SEC_BG("#FFF8F0")}>
          <a name="overnight"></a><span {_PILL("#C0392B")}>&#9889; Overnight Flash</span>
          {flash_html}
        </div>
        """)

    # (watch_today section removed — field was never in digest prompt schema)

    # ── 6. Key Stat of the Day ───────────────────────────────────────────
    key_stat = digest.get("key_stat") or {}
    if key_stat and key_stat.get("number") is not None and key_stat.get("number") != "":
        sections.append(f"""
        <a name="key-stat"></a>
        <div style="padding:12px 32px;background:#1B2A4A;color:#fff;border-bottom:1px solid #E0E0E0;text-align:center;" class="sec">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;opacity:0.6;margin-bottom:2px;">Stat of the Day</div>
          <div class="key-stat-num" style="font-size:32px;font-weight:700;font-family:Georgia,serif;">{_esc(str(key_stat.get("number", "")))}</div>
          <div style="font-size:12px;opacity:0.85;margin-top:2px;">{_esc(key_stat.get("label", ""))}</div>
          <div style="font-size:11px;opacity:0.65;margin-top:4px;font-style:italic;">{_esc(key_stat.get("context", ""))}</div>
          {"<div style='font-size:10px;opacity:0.45;margin-top:4px;'>Source: " + _esc(key_stat.get("source", "")) + "</div>" if key_stat.get("source") else ""}
        </div>
        """)

    # ── 7. KCNA Rhetoric Delta ──────────────────────────────────────────────
    kcna = digest.get("kcna_delta") or {}
    if kcna and any(kcna.values()):
        bottom_line = _esc(kcna.get("bottom_line", ""))
        watch = kcna.get("watch_flag", False)
        silence = kcna.get("silence_today", False)
        tone_shift = _esc(kcna.get("tone_shift", "")) if kcna.get("tone_shift") else ""
        output_vol = _esc(kcna.get("output_volume", "")) if kcna.get("output_volume") else ""

        # Doctrinal shift (high priority — rendered prominently)
        doctrinal = _esc(kcna.get("doctrinal_shift", "")) if kcna.get("doctrinal_shift") else ""
        doctrinal_html = ""
        if doctrinal:
            doctrinal_html = f"<div style='margin:12px 0;padding:8px 14px;background:#8E44AD;color:#fff;border-radius:4px;font-size:12px;'><strong>Doctrinal shift:</strong> {doctrinal}</div>"

        # Key quotes from KCNA — compact: single best quote only
        key_quotes = kcna.get("key_quotes") or []
        quotes_html = ""
        if key_quotes:
            q = key_quotes[0]
            qt = _esc(q.get("quote", ""))
            src_art = _esc(q.get("source_article", ""))
            quotes_html = f"""<div class="kcna-quote" style='margin-top:8px;padding:6px 12px;background:rgba(255,255,255,0.05);border-radius:4px;border-left:2px solid #555;'>
              <div style='font-size:12px;color:#D0D0D0;font-style:italic;line-height:1.4;'>&ldquo;{qt}&rdquo;</div>
              <div style='font-size:10px;color:#888;margin-top:2px;'>{src_art}</div>
            </div>"""

        # Notable omissions + Senior officials — combined into compact inline
        omissions = _esc(kcna.get("notable_omissions", "")) if kcna.get("notable_omissions") else ""
        omissions_html = ""
        if omissions:
            omissions_html = f"<div style='margin-top:6px;font-size:11px;color:#E67E22;'><strong>Omission:</strong> {omissions}</div>"

        senior = kcna.get("senior_officials") or []
        senior_html = ""
        if senior:
            senior_parts = []
            for s in senior[:2]:
                name = _esc(s.get("name", ""))
                act = _esc(s.get("activity", ""))
                senior_parts.append(f"<strong>{name}</strong>: {act}")
            senior_html = f"<div style='margin-top:6px;font-size:11px;color:#BBB;'>" + " · ".join(senior_parts) + "</div>"

        # Kim Jong Un line
        kim_today = "Yes" if kcna.get("kim_appearance_today") else "No"
        kim_activity = _esc(kcna.get("kim_activity", "")) if kcna.get("kim_activity") else ""
        days_absent = kcna.get("days_since_last_appearance")

        # Propaganda focus & Kim appearance as inline items
        prop_focus = kcna.get("propaganda_focus") or []
        prop_html = ""
        if prop_focus:
            prop_html = "<div style='margin-top:8px;font-size:11px;color:#888;'><strong style=\"color:#BBB;\">Focus:</strong> " + " · ".join(_esc(str(p)) for p in prop_focus) + "</div>"

        kim_line = ""
        if kim_today == "Yes":
            kim_line = f"Kim Jong Un public appearance"
            if kim_activity:
                kim_line += f" — {kim_activity}"
        else:
            kim_line = "No Kim Jong Un appearance"
            if days_absent:
                kim_line += f" ({days_absent} days since last)"

        kcna_baseline = _esc(kcna.get("baseline_period", ""))
        baseline_html = f"7-day baseline · {kcna_baseline}" if kcna_baseline else ""

        # Key phrase changes table
        phrases = kcna.get("key_phrase_changes") or []
        phrase_html = ""
        if phrases:
            phrase_rows = ""
            for p in phrases[:5]:
                ph = _esc(p.get("phrase", ""))
                ct_w = p.get("count_this_week", 0)
                ct_p = p.get("count_prior", 0)
                delta = _esc(p.get("delta_label", ""))
                # Color delta based on direction
                d_color = "#27AE60" if "↑" in delta else ("#C0392B" if "↓" in delta else "#888")
                phrase_rows += f"""
                <tr style="border-bottom:1px solid rgba(255,255,255,0.06);">
                  <td style="padding:4px 8px 4px 0;font-size:11px;color:#D0D0D0;">{ph}</td>
                  <td style="padding:4px 6px;font-size:11px;color:#888;text-align:center;white-space:nowrap;">{ct_p}</td>
                  <td style="padding:4px 6px;font-size:11px;color:#D0D0D0;text-align:center;white-space:nowrap;font-weight:600;">{ct_w}</td>
                  <td style="padding:4px 0 4px 6px;font-size:10px;color:{d_color};white-space:nowrap;">{delta}</td>
                </tr>"""
            phrase_html = f"""
            <div style="margin-top:12px;">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:rgba(255,255,255,0.6);margin-bottom:4px;">Phrase Frequency</div>
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr style="border-bottom:1px solid rgba(255,255,255,0.1);">
                  <td style="padding:3px 8px 3px 0;font-size:10px;color:rgba(255,255,255,0.5);text-transform:uppercase;">Phrase</td>
                  <td style="padding:3px 6px;font-size:10px;color:rgba(255,255,255,0.5);text-align:center;">Prior</td>
                  <td style="padding:3px 6px;font-size:10px;color:rgba(255,255,255,0.5);text-align:center;">This Wk</td>
                  <td style="padding:3px 0 3px 6px;font-size:10px;color:rgba(255,255,255,0.5);">Delta</td>
                </tr>
                {phrase_rows}
              </table>
            </div>"""

        sections.append(f"""
        <a name="kcna"></a>
        <div style="padding:0;border-bottom:1px solid #333;" class="sec kcna-dark">
          <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#1a2a1a;">
            <tr>
              <td style="padding:10px 32px;">
                <span style="font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:1.5px;color:#E8DCC8;font-family:Arial,sans-serif;">KCNA Rhetoric Delta</span>
                <span style="display:inline-block;width:60px;height:2px;background:#27AE60;vertical-align:middle;margin-left:10px;"></span>
              </td>
              <td style="padding:10px 32px;text-align:right;">
                <span style="font-size:11px;color:#8a8a8a;">{baseline_html}</span>
              </td>
            </tr>
          </table>
          <div style="padding:14px 32px;background:#1a2a1a;color:#E0E0E0;">
            {"<div style='margin-bottom:12px;padding:8px 14px;background:#C0392B;color:#fff;border-radius:4px;font-size:12px;font-weight:600;'>&#9888; Complete KCNA silence today</div>" if silence else ""}
            {"<div style='margin-bottom:12px;padding:8px 14px;background:#C0392B;color:#fff;border-radius:4px;font-size:12px;font-weight:600;'>&#9888; WATCH FLAG — Escalation-level rhetoric or unusual activity detected</div>" if watch and not silence else ""}
            {doctrinal_html}
            <table class="kcna-kv" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:10px;">
              <tr>
                <td style="vertical-align:top;width:50%;padding-right:12px;">
                  <div style="padding:8px 12px;background:rgba(255,255,255,0.04);border-radius:4px;">
                    <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:rgba(255,255,255,0.6);margin-bottom:4px;">Kim Jong Un</div>
                    <div style="font-size:13px;color:#E0E0E0;font-weight:600;">{kim_line}</div>
                  </div>
                </td>
                <td style="vertical-align:top;width:50%;">
                  <div style="padding:8px 12px;background:rgba(255,255,255,0.04);border-radius:4px;">
                    <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:rgba(255,255,255,0.6);margin-bottom:4px;">Output Volume</div>
                    <div style="font-size:13px;color:#E0E0E0;">{output_vol if output_vol else "—"}</div>
                    {"<div style='margin-top:3px;font-size:11px;color:#E67E22;font-weight:600;'>&#8644; " + tone_shift + "</div>" if tone_shift else ""}
                  </div>
                </td>
              </tr>
            </table>
            {prop_html}
            {quotes_html}
            {phrase_html}
            {omissions_html}
            {senior_html}
            {"<div style='margin-top:12px;padding:10px 14px;background:rgba(255,255,255,0.04);border-radius:4px;font-size:13px;line-height:1.6;color:#E0E0E0;font-family:Georgia,serif;'><strong style=" + chr(34) + "color:#E8DCC8;" + chr(34) + ">Bottom line:</strong> " + bottom_line + "</div>" if bottom_line else ""}
          </div>
        </div>
        """)

    # ── 8. Satellite & Location Watch ────────────────────────────────────
    locations = digest.get("bp_locations") or []
    imagery_report = digest.get("imagery_report") or {}
    if locations or imagery_report:
        # Featured imagery report (e.g., AEI / 38North analysis)
        img_report_html = ""
        if imagery_report:
            ir_source = _esc(imagery_report.get("source", ""))
            ir_date = _esc(imagery_report.get("date", ""))
            ir_label = _esc(imagery_report.get("label", "New imagery reports"))
            ir_headline = _esc(imagery_report.get("headline", ""))
            ir_body = _esc(imagery_report.get("body", ""))
            ir_sources = imagery_report.get("source_links") or []
            ir_bp_ids = imagery_report.get("bp_location_ids") or []
            source_links_html = ""
            if ir_sources:
                _src_parts = []
                for s in ir_sources:
                    if isinstance(s, dict):
                        s_label = _esc(s.get("label", s.get("source", "")))
                        s_url = s.get("url", "")
                        if s_url and s_url != "#" and s_url.startswith("http"):
                            _src_parts.append(f'<a href="{_esc(s_url)}" style="font-size:11px;font-family:monospace;color:#888;text-decoration:none;">{s_label} ↗</a>')
                        else:
                            _src_parts.append(f'<span style="font-size:11px;font-family:monospace;color:#888;">{s_label} ↗</span>')
                    else:
                        _src_parts.append(f'<span style="font-size:11px;font-family:monospace;color:#888;">{_esc(str(s))} ↗</span>')
                source_links_html = "<div style='margin-top:8px;'>" + " &middot; ".join(_src_parts) + "</div>"
            bp_ids_html = ""
            if ir_bp_ids:
                bp_ids_html = "<div style='margin-top:6px;font-size:11px;color:#888;'>→ " + " · ".join(_esc(str(b)) for b in ir_bp_ids) + "</div>"
            img_report_html = f"""
            <div style="margin-bottom:20px;padding:16px;border-left:3px solid #2980B9;">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.5px;color:#C0392B;font-weight:600;margin-bottom:6px;">{ir_source} · {ir_date} — {ir_label}</div>
              <div style="font-size:17px;font-weight:700;color:#1B4A6A;line-height:1.3;margin-bottom:8px;">{ir_headline}</div>
              <div style="font-size:13px;line-height:1.6;color:#444;">{ir_body}</div>
              {bp_ids_html}
              {source_links_html}
            </div>"""

        # BP Monitored Locations — 2-column card grid
        _badge_styles = {
            "normal": ("#27AE60", "#F0FAF0", "Normal"),
            "activity": ("#D4AC0D", "#FDF6E3", "Active"),
            "elevated": ("#E67E22", "#FFF3E0", "Elevated"),
            "alert": ("#C0392B", "#FBE9E7", "Alert"),
        }
        loc_cards = ""
        for i in range(0, len(locations), 2):
            row_cards = ""
            for j in range(i, min(i + 2, len(locations))):
                loc = locations[j]
                name = _esc(loc.get("name", ""))
                status = loc.get("status", "normal")
                note = _esc(loc.get("note", ""))
                last_report = _esc(loc.get("last_report", ""))
                direction = loc.get("direction", "")
                b_color, b_bg, b_label = _badge_styles.get(status, ("#7F8C8D", "#F5F5F5", "Monitor"))
                if direction == "up":
                    b_label += " &#9650;"
                elif direction == "down":
                    b_label += " &#9660;"
                status_badge = f'<span style="display:inline-block;padding:2px 8px;border-radius:3px;font-size:9px;font-weight:700;color:#fff;background:{b_color};letter-spacing:0.5px;">{b_label}</span>'
                note_html = f'<div style="font-size:11px;line-height:1.4;color:#666;margin-top:4px;">{note}</div>' if note else ""
                row_cards += f"""
                <td style="width:50%;padding:4px;vertical-align:top;">
                  <div style="background:{b_bg};border-radius:4px;padding:10px 12px;border-left:3px solid {b_color};min-height:60px;">
                    <div style="font-size:12px;font-weight:700;color:#1B2A4A;margin-bottom:3px;">{name}</div>
                    <div style="margin-bottom:4px;">{status_badge} <span style="font-size:9px;color:#999;margin-left:4px;">{last_report}</span></div>
                    {note_html}
                  </div>
                </td>"""
            if len(locations) - i == 1:
                row_cards += '<td style="width:50%;padding:4px;"></td>'
            loc_cards += f"<tr>{row_cards}</tr>"

        sections.append(f"""
        <div {_SEC}>
          <a name="satellite"></a><span {_PILL("#2C3E50")}>Satellite &amp; Location Watch</span>
          {img_report_html}
          <table width="100%" cellpadding="0" cellspacing="0" border="0" class="loc-grid">
            {loc_cards}
          </table>
        </div>
        """)

    # ── 9. ROK Government (merged: Gov + Personnel + Assembly + Calendar) ─
    rok_gov = digest.get("rok_government") or []
    calendar_watch = digest.get("calendar_watch") or []
    rok_personnel = digest.get("rok_personnel") or []
    rok_assembly = digest.get("rok_assembly") or []
    if rok_gov or calendar_watch or rok_personnel or rok_assembly:
        # 2x2 grid of ministry cards
        gov_rows = ""
        for i in range(0, len(rok_gov), 2):
            row_cards = ""
            for j in range(i, min(i + 2, len(rok_gov))):
                item = rok_gov[j]
                ministry = _esc(item.get("ministry", ""))
                ministry_korean = _esc(item.get("ministry_korean", ""))
                action = _esc(item.get("action", ""))
                detail = _esc(item.get("detail", ""))
                source_url = item.get("url", "")
                source_label = _esc(item.get("source_label", ""))
                ministry_header = ""
                if ministry_korean:
                    ministry_header = f'<span style="font-size:11px;color:#888;">{ministry_korean} · </span>'
                ministry_header += f'<span style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:0.3px;">{ministry}</span>'
                src_link = ""
                if source_url and source_url != "#" and source_url.startswith("http"):
                    s_label = source_label if source_label else ministry.lower()
                    src_link = f'<div style="margin-top:6px;font-size:11px;color:#888;">→ <a href="{_esc(source_url)}" style="color:#888;text-decoration:none;">{_esc(s_label)} ↗</a></div>'
                elif source_label:
                    src_link = f'<div style="margin-top:6px;font-size:11px;color:#888;">→ {_esc(source_label)}</div>'
                row_cards += f"""
                <td style="width:50%;padding:8px;vertical-align:top;">
                  <div style="background:#FAFAF5;border-radius:4px;padding:14px;min-height:100px;">
                    <div style="margin-bottom:6px;">{ministry_header}</div>
                    <div style="font-size:14px;font-weight:700;color:#1B2A4A;line-height:1.3;margin-bottom:6px;">{_esc(action)}</div>
                    <div style="font-size:12px;line-height:1.5;color:#555;">{_esc(detail)}</div>
                    {src_link}
                  </div>
                </td>"""
            if len(rok_gov) - i == 1:
                row_cards += '<td style="width:50%;padding:8px;"></td>'
            gov_rows += f"<tr>{row_cards}</tr>"

        gov_grid_html = ""
        if rok_gov:
            gov_grid_html = f"""
            <table width="100%" cellpadding="0" cellspacing="0" border="0" class="gov-grid">
              {gov_rows}
            </table>"""

        # Calendar — upcoming events (simple: date + headline + detail)
        cal_html = ""
        if calendar_watch:
            cal_items = ""
            for cal in calendar_watch:
                cal_month = _esc(cal.get("month", ""))
                cal_day = _esc(str(cal.get("day", "")))
                cal_headline = _esc(cal.get("headline", ""))
                cal_detail = _esc(cal.get("detail", ""))
                cal_items += f"""
                <table class="cal-table" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-bottom:1px solid #E8E8E8;">
                  <tr>
                    <td width="50" style="padding:10px 10px 10px 0;text-align:center;vertical-align:top;">
                      <div style="font-size:10px;text-transform:uppercase;color:#888;letter-spacing:0.5px;">{cal_month}</div>
                      <div class="cal-date" style="font-size:18px;font-weight:300;color:#1B2A4A;line-height:1.2;">{cal_day}</div>
                    </td>
                    <td style="padding:10px 0;vertical-align:top;">
                      <div style="font-size:13px;font-weight:600;color:#1B2A4A;margin-bottom:2px;">{cal_headline}</div>
                      <div style="font-size:12px;line-height:1.4;color:#555;">{cal_detail}</div>
                    </td>
                  </tr>
                </table>"""
            cal_html = f"""
            <div style="margin-top:20px;">
              <div style="padding:8px 0;border-bottom:1px solid #1B2A4A;margin-bottom:4px;">
                <span style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:#1B2A4A;">Upcoming</span>
                <span style="font-size:11px;color:#888;margin-left:8px;">14 days</span>
              </div>
              {cal_items}
            </div>"""

        # Personnel changes (inline in ROK Gov)
        pers_html = ""
        if rok_personnel:
            action_colors = {"appointed": "#27AE60", "nominated": "#2980B9", "resigned": "#E67E22", "dismissed": "#C0392B", "confirmed": "#16A085"}
            pers_items = ""
            for item in rok_personnel:
                position = _esc(item.get("position", ""))
                name = _esc(item.get("name", ""))
                action = item.get("action", "appointed")
                detail = _esc(item.get("detail", ""))
                predecessor = _esc(item.get("predecessor", ""))
                a_color = action_colors.get(action, "#1B2A4A")
                action_badge = f'<span style="display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600;color:#fff;background:{a_color};text-transform:uppercase;margin-left:6px;">{_esc(action)}</span>'
                pred_line = f'<div style="font-size:11px;color:#888;margin-top:2px;">Replaces: {predecessor}</div>' if predecessor else ""
                pers_items += f"""
                <div style="margin-bottom:10px;padding-left:12px;border-left:3px solid {a_color};">
                  <div style="font-size:13px;font-weight:600;color:#1B2A4A;">{name}{action_badge}</div>
                  <div style="font-size:12px;color:#555;">{position}</div>
                  <div style="font-size:12px;line-height:1.4;color:#555;">{detail}</div>
                  {pred_line}
                </div>"""
            pers_html = f"""
            <div style="margin-top:16px;">
              <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:#2C3E50;margin-bottom:8px;padding-bottom:4px;border-bottom:1px solid #E8E8E8;">Personnel Changes</div>
              {pers_items}
            </div>"""

        # Assembly activity (inline in ROK Gov)
        asm_html = ""
        if rok_assembly:
            asm_items = ""
            for item in rok_assembly:
                committee = _esc(item.get("committee", ""))
                action = _esc(item.get("action", ""))
                detail = _esc(item.get("detail", ""))
                asm_items += f"""
                <div style="margin-bottom:8px;padding-left:12px;border-left:3px solid #7F8C8D;">
                  <div style="font-size:11px;color:#7F8C8D;font-weight:600;text-transform:uppercase;">{committee}</div>
                  <div style="font-size:13px;font-weight:600;color:#1B2A4A;">{action}</div>
                  <div style="font-size:12px;line-height:1.4;color:#555;">{detail}</div>
                </div>"""
            asm_html = f"""
            <div style="margin-top:16px;">
              <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:#7F8C8D;margin-bottom:8px;padding-bottom:4px;border-bottom:1px solid #E8E8E8;">National Assembly</div>
              {asm_items}
            </div>"""

        rok_date = _esc(str(digest.get("digest_date", "")))
        sections.append(f"""
        <div {_SEC}>
          <a name="rok-gov"></a><span {_PILL("#1B6A4A")}>ROK Government</span> <span style="font-size:10px;color:#888;font-family:Arial,sans-serif;">President + Ministries &middot; {rok_date}</span>
          <div style="padding-top:4px;">
            {gov_grid_html}
            {pers_html}
            {asm_html}
            {cal_html}
          </div>
        </div>
        """)

    # ── 10. US-Korea Trade & Investment Deals ───────────────────────────────
    us_korea = digest.get("us_korea_deals") or {}
    if isinstance(us_korea, list):
        deal_list = us_korea
    else:
        deal_list = us_korea.get("deals") or []

    trade_policy = (us_korea.get("trade_policy") or []) if isinstance(us_korea, dict) else []
    investment_pkg = (us_korea.get("investment_package") or {}) if isinstance(us_korea, dict) else {}

    tariff_tracker = (us_korea.get("tariff_tracker") or {}) if isinstance(us_korea, dict) else {}

    if deal_list or trade_policy or investment_pkg or tariff_tracker:
        header_html = ""

        # Tariff dashboard card
        if tariff_tracker and tariff_tracker.get("headline_rate"):
            h_rate = _esc(str(tariff_tracker.get("headline_rate", "")))
            h_status = tariff_tracker.get("headline_status", "ACTIVE")
            h_note = _esc(str(tariff_tracker.get("headline_note", "")))
            s122 = tariff_tracker.get("section_122_surcharge")
            last_change = _esc(str(tariff_tracker.get("last_change", "")))
            next_trigger = _esc(str(tariff_tracker.get("next_trigger", ""))) if tariff_tracker.get("next_trigger") else ""

            _tariff_status_colors = {"ACTIVE": "#C0392B", "PAUSED": "#D4AC0D", "NEGOTIATING": "#2980B9", "ESCALATION": "#8E44AD", "REDUCED": "#27AE60"}
            h_color = _tariff_status_colors.get(h_status, "#C0392B")
            h_badge = f'<span style="display:inline-block;padding:2px 8px;border-radius:3px;font-size:10px;font-weight:700;color:#fff;background:{h_color};letter-spacing:0.5px;vertical-align:middle;margin-left:8px;">{_esc(h_status)}</span>'

            # Sector rate rows
            sector_rows = ""
            for sr in (tariff_tracker.get("sector_rates") or []):
                sr_sector = _esc(sr.get("sector", ""))
                sr_rate = _esc(str(sr.get("rate", "")))
                sr_auth = _esc(sr.get("authority", ""))
                sr_st = sr.get("status", "ACTIVE")
                sr_color = _tariff_status_colors.get(sr_st, "#C0392B")
                sr_note = _esc(sr.get("note", ""))
                sector_rows += f"""
                <tr style="border-bottom:1px solid #F0E0E0;">
                  <td style="padding:4px 6px 4px 0;font-size:11px;font-weight:600;color:#1B2A4A;">{sr_sector}</td>
                  <td style="padding:4px 6px;font-size:13px;font-weight:700;color:{sr_color};text-align:center;white-space:nowrap;">{sr_rate}</td>
                  <td style="padding:4px 6px;font-size:9px;color:#888;text-transform:uppercase;white-space:nowrap;">{sr_auth}</td>
                  <td style="padding:4px 0 4px 6px;font-size:10px;color:#666;">{sr_note}</td>
                </tr>"""

            s122_line = f'<div style="margin-top:6px;font-size:11px;color:#E67E22;font-weight:600;">+ Section 122 global surcharge: {_esc(str(s122))}</div>' if s122 else ""
            next_line = f'<div style="margin-top:4px;font-size:10px;color:#2980B9;">Next trigger: {next_trigger}</div>' if next_trigger else ""

            header_html += f"""
            <div style="margin-bottom:16px;padding:12px 14px;background:#FFF5F5;border-radius:4px;border:1px solid #F0D0D0;">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#C0392B;font-weight:600;margin-bottom:6px;">US Tariff Rate on South Korea</div>
              <div style="margin-bottom:6px;">
                <span style="font-size:28px;font-weight:700;color:#C0392B;">{h_rate}</span>
                {h_badge}
              </div>
              <div style="font-size:11px;color:#555;line-height:1.4;margin-bottom:8px;">{h_note}</div>
              {s122_line}
              <table class="tariff-sector" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:8px;border-top:1px solid #F0E0E0;">
                {sector_rows}
              </table>
              <div style="margin-top:8px;font-size:10px;color:#999;">{last_change}</div>
              {next_line}
            </div>"""

        # Investment package progress bar + deal breakdown
        if investment_pkg and investment_pkg.get("total_pledged"):
            pct = investment_pkg.get("pct_fulfilled", 0)
            bar_width = max(2, min(pct, 100))

            # Build deal breakdown list
            known_deals = investment_pkg.get("known_deals") or []
            deals_breakdown = ""
            if known_deals:
                deal_rows = ""
                for kd in known_deals:
                    co = _esc(kd.get("company", ""))
                    val = _esc(kd.get("value", ""))
                    sect = _esc(kd.get("sector", ""))
                    deal_rows += f"""
                    <tr style="border-bottom:1px solid #E8EDF3;">
                      <td style="padding:4px 6px 4px 0;font-size:11px;font-weight:600;color:#1B2A4A;">{co}</td>
                      <td style="padding:4px 6px;font-size:11px;font-weight:700;color:#27AE60;text-align:right;white-space:nowrap;">{val}</td>
                      <td style="padding:4px 0 4px 6px;font-size:10px;color:#888;">{sect}</td>
                    </tr>"""
                deals_breakdown = f"""
                <div style="margin-top:10px;">
                  <div style="font-size:9px;text-transform:uppercase;letter-spacing:1px;color:#888;font-weight:600;margin-bottom:4px;">Deal Breakdown</div>
                  <table width="100%" cellpadding="0" cellspacing="0" border="0" class="deal-breakdown">
                    {deal_rows}
                  </table>
                </div>"""

            header_html += f"""
            <div style="margin-bottom:16px;padding:12px 14px;background:#F0F7FF;border-radius:4px;border:1px solid #D6E9F8;">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#1B2A4A;font-weight:600;margin-bottom:6px;">ROK-US Investment Commitment</div>
              <div style="margin-bottom:4px;">
                <span style="font-size:22px;font-weight:700;color:#1B2A4A;">{_esc(str(investment_pkg.get("announced_to_date", "")))}</span>
                <span style="font-size:13px;color:#888;"> of {_esc(str(investment_pkg.get("total_pledged", "")))} pledged</span>
              </div>
              <div style="background:#E0E0E0;border-radius:4px;height:8px;overflow:hidden;">
                <div style="background:#27AE60;width:{bar_width}%;height:100%;border-radius:4px;"></div>
              </div>
              <div style="font-size:11px;color:#888;margin-top:4px;">{pct}% fulfilled &middot; {_esc(str(investment_pkg.get("latest_update", "")))}</div>
              {deals_breakdown}
            </div>"""

        # US Trade Policy Tracker (Section 301, USTR, Commerce Dept)
        if trade_policy:
            status_colors = {"ACTIVE": "#C0392B", "PENDING": "#D4AC0D", "RISK": "#E67E22", "ESCALATION": "#8E44AD", "RESOLVED": "#27AE60", "MONITOR": "#2980B9"}
            tracker_rows = ""
            for tr in trade_policy:
                item_text = _esc(tr.get("item", ""))
                detail_text = _esc(tr.get("detail", ""))
                agency = _esc(tr.get("agency", ""))
                st = tr.get("status", "MONITOR")
                st_color = status_colors.get(st, "#7F8C8D")
                status_badge = f'<span style="display:inline-block;padding:1px 6px;border-radius:3px;font-size:9px;font-weight:700;color:#fff;background:{st_color};letter-spacing:0.5px;">{_esc(st)}</span>'
                agency_tag = f'<span style="font-size:9px;color:#888;font-weight:400;"> · {agency}</span>' if agency else ""
                tracker_rows += f"""
                <tr style="border-bottom:1px solid #F0F0F0;">
                  <td style="padding:6px 8px 6px 0;vertical-align:top;font-size:12px;font-weight:600;color:#1B2A4A;width:30%;">{item_text}{agency_tag}</td>
                  <td style="padding:6px 4px;vertical-align:top;font-size:11px;color:#555;line-height:1.4;">{detail_text}</td>
                  <td style="padding:6px 0 6px 4px;vertical-align:top;text-align:right;white-space:nowrap;">{status_badge}</td>
                </tr>"""
            header_html += f"""
            <div style="margin-bottom:16px;">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#888;font-weight:600;margin-bottom:6px;">US Trade Policy Tracker</div>
              <table class="trade-policy" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top:1px solid #E8E8E8;">
                {tracker_rows}
              </table>
            </div>"""

        # Individual deals
        deals_html = ""
        sector_colors = {
            "defense": "#C0392B", "energy": "#16A085", "tech": "#8E44AD",
            "manufacturing": "#1B2A4A", "trade": "#D4AC0D", "tariff": "#E67E22",
        }
        for deal in deal_list:
            headline = _esc(deal.get("headline", ""))
            value = _esc(deal.get("value", "")) if deal.get("value") else ""
            sector = deal.get("sector", "trade")
            parties = _esc(deal.get("parties", ""))
            detail = _esc(deal.get("detail", ""))
            src = _esc(deal.get("source", ""))
            url = deal.get("url", "")
            d_tags = deal.get("tags") or []
            bar_color = sector_colors.get(sector, "#1B2A4A")
            wh_tracker = deal.get("wh_tracker", False)
            value_badge = f'<span style="display:inline-block;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:700;color:#fff;background:#27AE60;margin-left:6px;">{value}</span>' if value else ""
            wh_badge = '<span style="display:inline-block;padding:1px 6px;border-radius:3px;font-size:9px;font-weight:600;color:#1B2A4A;background:#E8E8E8;margin-left:6px;text-transform:uppercase;letter-spacing:0.5px;">WH Tracker</span>' if wh_tracker else ""
            # Source / parties attribution line on the right
            meta_right = f'<span style="font-size:11px;color:#888;">{parties}</span>' if parties else ""
            deals_html += f"""
            <div class="deal-card" style="margin-bottom:14px;padding:12px 0;border-top:1px solid #E8E8E8;">
              <div style="font-size:11px;color:#888;margin-bottom:2px;">{meta_right} {('&middot; ' + src) if src else ''}</div>
              <div style="font-size:15px;font-weight:700;color:#1B2A4A;line-height:1.3;margin-bottom:4px;">
                {_link_or_text(headline, url, style="color:#1B4A6A;text-decoration:none;")}{value_badge}{wh_badge}
              </div>
              <div style="font-size:13px;line-height:1.5;color:#444;">{detail}</div>
              {"<div style='margin-top:6px;'>" + _link_or_text(_esc(src) + " ↗", url, style="font-size:11px;font-family:monospace;color:#888;text-decoration:none;") + "</div>" if src and url and url != "#" and url.startswith("http") else ""}
            </div>"""

        sections.append(f"""
        <div style="padding:14px 32px;background:#F0F4F8;border-top:3px solid #1B2A4A;border-bottom:1px solid #E0E0E0;" class="sec">
          <a name="trade"></a><span {_PILL("#1B2A4A")}>US-Korea Trade &amp; Investment</span>
          {header_html}
          {deals_html}
        </div>
        """)

    # ── 11. Business & Economy ────────────────────────────────────────────
    biz_econ = digest.get("business_economy") or []
    if biz_econ:
        biz_html = ""
        biz_sector_colors = {
            "tech": "#8E44AD", "auto": "#1B2A4A", "energy": "#16A085",
            "finance": "#D4AC0D", "manufacturing": "#2980B9",
            "real-estate": "#E67E22", "macro": "#C0392B",
        }
        for item in biz_econ:
            cat = _esc(item.get("category", item.get("sector", "")))
            headline = _esc(item.get("headline", ""))
            body = _esc(item.get("body_text", ""))
            src = _esc(item.get("source", ""))
            url = item.get("url", "")
            bar_color = biz_sector_colors.get(item.get("sector", ""), "#1B2A4A")
            companies = item.get("companies") or []
            company_tags = ""
            if companies:
                company_tags = " ".join(
                    f'<span style="display:inline-block;padding:1px 5px;border-radius:3px;font-size:9px;background:#E8E8E8;color:#555;margin-right:3px;">{_esc(c)}</span>'
                    for c in companies[:3]
                )
                company_tags = f'<div style="margin-top:3px;">{company_tags}</div>'
            biz_html += f"""
            <div style="margin-bottom:10px;padding-left:12px;border-left:3px solid {bar_color};">
              <div style="font-size:11px;color:#888;text-transform:uppercase;">{cat} &middot; {src}</div>
              <div style="font-size:13px;font-weight:600;color:#1B2A4A;">
                {_link_or_text(headline, url)}
              </div>
              <div style="font-size:12px;line-height:1.4;color:#555;">{body}</div>
              {company_tags}
            </div>"""
        sections.append(f"""
        <div {_SEC}>
          <a name="business"></a><span {_PILL("#D4AC0D")}>Business &amp; Economy</span>
          {biz_html}
        </div>
        """)

    # ── (Overnight Flash moved to position 4b — after Top Stories) ──────

    # ── 12. Northeast Asia Watch (Japan + China + Russia → Korea) ───────
    nea_items = digest.get("northeast_asia") or []
    if nea_items:
        nea_cat_colors = {
            # Japan-Korea
            "japan-history": "#C0392B", "trilateral": "#2E4057", "gsomia": "#8E44AD",
            "japan-trade": "#D4AC0D", "japan-diplomatic": "#2980B9", "japan-defense": "#1B2A4A",
            "territorial": "#E67E22",
            # China-Korea
            "thaad-retaliation": "#C0392B", "china-coercion": "#E67E22",
            "rare-earth": "#D4AC0D", "china-diplomatic": "#2980B9",
            "china-military": "#8E44AD", "china-trade": "#1B2A4A", "china-opinion": "#16A085",
            # Russia-Korea
            "russia-weapons": "#C0392B", "russia-diplomatic": "#2980B9",
            "russia-labor": "#E67E22", "russia-sanctions": "#8E44AD", "russia-military": "#C0392B",
        }
        region_colors = {"Japan-Korea": "#1B6A4A", "China-Korea": "#8B0000", "Trilateral": "#2E4057", "Russia-Korea": "#7B241C"}
        nea_html = ""
        for item in nea_items:
            cat = _esc(item.get("category", ""))
            headline = _esc(item.get("headline", ""))
            body = _esc(item.get("body_text", ""))
            src = _esc(item.get("source", ""))
            url = item.get("url", "")
            sig = item.get("signal_type", "")
            region = item.get("region_tag", "")
            is_reaction = item.get("is_reaction_source", False)
            bar_color = nea_cat_colors.get(item.get("category", ""), region_colors.get(region, "#1B2A4A"))
            reaction_badge = ""
            if is_reaction:
                badge_label = "PRC SOURCE" if "China" in region else "STATE MEDIA"
                reaction_badge = f'<span style="display:inline-block;padding:1px 5px;border-radius:3px;font-size:9px;font-weight:600;color:#fff;background:#888;margin-left:6px;">{badge_label}</span>'
            region_label = f'<span style="font-size:9px;padding:1px 5px;border-radius:3px;background:{region_colors.get(region, "#888")};color:#fff;margin-right:6px;">{_esc(region)}</span>' if region else ""
            nea_html += f"""
            <div style="margin-bottom:10px;padding-left:12px;border-left:3px solid {bar_color};">
              <div style="font-size:11px;color:#888;text-transform:uppercase;">
                {region_label}{cat} &middot; {src}{reaction_badge}
                {"&nbsp;" + _signal_badge(sig) if sig else ""}
              </div>
              <div style="font-size:13px;font-weight:600;color:#1B2A4A;">
                {_link_or_text(headline, url)}
              </div>
              <div style="font-size:12px;line-height:1.4;color:#555;">{body}</div>
            </div>"""
        sections.append(f"""
        <div {_SEC}>
          <a name="nea"></a><span {_PILL("#2C3E50")}>Northeast Asia Watch</span>
          {nea_html}
        </div>
        """)

    # ── 12c. Public Sentiment Tracker ──────────────────────────────────
    sentiment = digest.get("public_sentiment") or {}
    if sentiment and any(sentiment.values()):
        def _sentiment_cell(label, data, width="25%"):
            if not data or not data.get("value"):
                return f"""
                <td width="{width}" align="center" style="padding:8px 6px;">
                  <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;opacity:0.6;">{label}</div>
                  <div style="font-size:16px;font-weight:700;color:#888;">--</div>
                  <div style="font-size:10px;opacity:0.5;">No recent data</div>
                </td>"""
            val = _esc(str(data.get("value", "")))
            trend = data.get("trend", "")
            source = _esc(str(data.get("source", "")))
            updated = _esc(str(data.get("last_updated", "")))
            trend_arrow = ""
            if trend == "up":
                trend_arrow = '<span style="color:#27AE60;">&#9650;</span>'
            elif trend == "down":
                trend_arrow = '<span style="color:#C0392B;">&#9660;</span>'
            elif trend == "stable":
                trend_arrow = '<span style="color:#888;">&#8594;</span>'
            return f"""
            <td width="{width}" align="center" style="padding:8px 6px;">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;opacity:0.6;">{label}</div>
              <div style="font-size:16px;font-weight:700;">{val} {trend_arrow}</div>
              <div style="font-size:10px;opacity:0.5;">{source}</div>
              <div style="font-size:10px;opacity:0.5;">{updated}</div>
            </td>"""

        approval = sentiment.get("presidential_approval") or {}
        party_ruling = sentiment.get("party_ruling") or {}
        party_opp = sentiment.get("party_opposition") or {}
        party_ind = sentiment.get("party_independent") or {}
        discourse = sentiment.get("discourse_flag")

        discourse_html = ""
        if discourse:
            discourse_html = f"""
            <div class="sentiment-discourse" style="margin-top:8px;padding:6px 10px;background:#FFF3E0;border-radius:4px;border-left:3px solid #E67E22;font-size:11px;color:#555;">
              <strong style="color:#E67E22;">Discourse:</strong> {_esc(discourse)}
            </div>"""

        gallup_finding = sentiment.get("gallup_spotlight")
        spotlight_html = ""
        if gallup_finding:
            topic = _esc(str(gallup_finding.get("topic", "")))
            finding = _esc(str(gallup_finding.get("finding", "")))
            poll_date = _esc(str(gallup_finding.get("poll_date", "")))
            spotlight_html = f"""
            <div class="sentiment-spotlight" style="margin-top:10px;padding:8px 12px;background:#EBF5FB;border-radius:4px;border-left:3px solid #2980B9;font-size:11px;color:#444;line-height:1.5;">
              <strong style="color:#2980B9;">Gallup Korea Spotlight</strong>
              <span style="font-size:9px;opacity:0.5;margin-left:6px;">{poll_date}</span><br>
              <span style="font-weight:600;">{topic}:</span> {finding}
            </div>"""

        # Check if polling data is stale (>7 days old)
        stale_html = ""
        poll_updated = (approval.get("last_updated") or "")
        if poll_updated and poll_updated != "recent":
            try:
                # Try common date formats from the collector
                poll_dt = None
                for fmt in ("%b %d, %Y", "%b %d %Y"):
                    try:
                        poll_dt = datetime.strptime(poll_updated, fmt).replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        continue
                if poll_dt and (now - poll_dt).days > 7:
                    stale_html = f"""
            <div style="margin-top:8px;font-size:10px;color:#999;text-align:center;">
              Data from {_esc(poll_updated)} — newer polling may be available
            </div>"""
            except Exception:
                pass

        sections.append(f"""
        <div style="padding:10px 32px;background:#F8F9FA;border-bottom:1px solid #E0E0E0;" class="sec">
          <a name="sentiment"></a><span {_PILL("#8E44AD")}>Public Sentiment Tracker</span>
          <table width="100%" cellpadding="0" cellspacing="0" border="0" class="sentiment-table">
            <tr>
              {_sentiment_cell("Presidential Approval", approval)}
              {_sentiment_cell(f"Ruling ({party_ruling.get('party_kr', 'DP')})" if party_ruling.get("party_kr") else "Ruling Party", party_ruling)}
              {_sentiment_cell(f"Opposition ({party_opp.get('party_kr', 'PPP')})" if party_opp.get("party_kr") else "Opposition", party_opp)}
              {_sentiment_cell("Independents (무당층)", party_ind)}
            </tr>
          </table>
          {stale_html}
          {spotlight_html}
          {discourse_html}
        </div>
        """)

    # ── 13. The Wire (Also Today — secondary news) ────────────────────
    combined_also = digest.get("also_today") or []
    if combined_also:
        wire_html = ""
        for item in combined_also:
            cat = _esc(item.get("category", ""))
            headline = _esc(item.get("headline", ""))
            body = _esc(item.get("body_text", ""))
            src = _esc(item.get("source", ""))
            url = item.get("url", "")
            bar_color = _color_bar(item.get("color_bar_class", ""))
            wire_html += f"""
            <div style="margin-bottom:10px;padding-left:12px;border-left:3px solid {bar_color};">
              <div style="font-size:11px;color:#888;text-transform:uppercase;">{cat} &middot; {src}</div>
              <div style="font-size:13px;font-weight:600;color:#1B2A4A;">
                {_link_or_text(headline, url)}
              </div>
              <div style="font-size:12px;line-height:1.4;color:#555;">{body}</div>
            </div>"""
        sections.append(f"""
        <div {_SEC}>
          <a name="wire"></a><span {_PILL("#7F8C8D")}>The Wire</span>
          {wire_html}
        </div>
        """)

    # ── 14. Statements & Analysis (merged: Statements + Op-Eds + Academic) ─
    social = digest.get("social_statements") or []
    opeds = digest.get("opeds_today") or []
    academic = digest.get("academic_today") or []
    if social or opeds or academic:
        sa_html = ""
        # Statements
        for s in social:
            initials = _esc(s.get("avatar_initials", "?"))
            who = _esc(s.get("who", ""))
            handle = _esc(s.get("handle_context", ""))
            quote = _esc(s.get("quote_text", ""))
            note = _esc(s.get("analyst_note", ""))
            url = s.get("url", "")
            badge_color = _social_badge(s.get("badge_class", "sb-p"))
            source_link = f'<a href="{_esc(url)}" style="font-size:10px;color:#2980B9;text-decoration:none;">Source &#8594;</a>' if url and url != "#" and url.startswith("http") else ""
            sa_html += f"""
            <div style="margin-bottom:12px;padding:12px;background:#F8F9FA;border-radius:6px;border-left:3px solid {badge_color};">
              <table cellpadding="0" cellspacing="0" border="0" style="margin-bottom:6px;">
                <tr>
                  <td width="36" style="vertical-align:middle;">
                    <div style="width:36px;height:36px;border-radius:50%;background:{badge_color};color:#fff;text-align:center;line-height:36px;font-size:13px;font-weight:700;">{initials}</div>
                  </td>
                  <td style="padding-left:8px;vertical-align:middle;">
                    <div style="font-size:12px;font-weight:600;color:#1B2A4A;">{who}</div>
                    <div style="font-size:10px;color:#888;">{handle}</div>
                  </td>
                </tr>
              </table>
              <p style="margin:0 0 6px 0;font-size:13px;line-height:1.5;color:#333;font-style:italic;">&ldquo;{quote}&rdquo;</p>
              {"<p style='margin:0;font-size:11px;color:#2980B9;'><strong>Analyst:</strong> " + note + "</p>" if note else ""}
              {source_link}
            </div>"""
        # Op-Eds
        for op in opeds:
            src = _esc(op.get("source", ""))
            arg = _esc(op.get("central_argument", ""))
            summary = _esc(op.get("summary", ""))
            so_what = _esc(op.get("policy_so_what", ""))
            url = op.get("url", "")
            sa_html += f"""
            <div style="margin-bottom:12px;padding-left:12px;border-left:3px solid #D4AC0D;">
              <div style="font-size:11px;color:#888;">{src}</div>
              <div style="font-size:13px;font-weight:600;color:#1B2A4A;">
                {_link_or_text(arg, url)}
              </div>
              <div style="font-size:12px;line-height:1.4;color:#555;">{summary}</div>
              {"<div style='font-size:11px;color:#2980B9;margin-top:3px;'><strong>So what:</strong> " + so_what + "</div>" if so_what else ""}
            </div>"""
        # Academic
        for a in academic:
            src = _esc(a.get("source", ""))
            tier = _esc(a.get("journal_tier", ""))
            summary = _esc(a.get("summary", ""))
            implication = _esc(a.get("policy_implication", ""))
            url = a.get("url", "")
            read_link = f'<a href="{_esc(url)}" style="font-size:11px;color:#2980B9;">Read &#8594;</a>' if url and url != "#" and url.startswith("http") else ""
            sa_html += f"""
            <div style="margin-bottom:12px;padding-left:12px;border-left:3px solid #8E44AD;">
              <div style="font-size:11px;color:#888;">{src} &middot; {tier}</div>
              <div style="font-size:12px;line-height:1.4;color:#555;">{summary}</div>
              {"<div style='font-size:11px;color:#8E44AD;margin-top:3px;'><strong>Implication:</strong> " + implication + "</div>" if implication else ""}
              {read_link}
            </div>"""
        sections.append(f"""
        <div {_SEC}>
          <a name="analysis"></a><span {_PILL("#1B2A4A")}>Statements &amp; Analysis</span>
          {sa_html}
        </div>
        """)

    # ── 15. Footer (with On This Day) ─────────────────────────────────────
    on_this_day = digest.get("on_this_day") or []
    otd_footer = ""
    if on_this_day:
        item = on_this_day[0]
        otd_date = _esc(item.get("date", ""))
        otd_event = _esc(item.get("event", ""))
        otd_rel = _esc(item.get("relevance", ""))
        otd_footer = f"""
        <div style="text-align:left;margin-bottom:14px;padding:10px 14px;background:rgba(255,255,255,0.08);border-radius:4px;">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:rgba(255,255,255,0.5);margin-bottom:4px;">On This Day</div>
          <div style="font-size:12px;color:rgba(255,255,255,0.85);"><strong>{otd_date}:</strong> {otd_event}</div>
          <div style="font-size:11px;color:rgba(255,255,255,0.7);font-style:italic;">{otd_rel}</div>
        </div>"""
    sections.append(f"""
    <div style="padding:16px 32px;background:#1B2A4A;text-align:center;" class="sec footer">
      {otd_footer}
      <div style="font-size:11px;color:rgba(255,255,255,0.6);line-height:1.5;">
        Korea Daily Brief &middot; By Andy Lim &middot; CSIS Korea Chair<br>
        {_esc(date_str)} &middot; {gen_time}<br>
        <span style="color:rgba(255,255,255,0.6);">Read alongside primary sources</span>
      </div>
      <div style="font-size:10px;color:rgba(255,255,255,0.55);margin-top:12px;line-height:1.5;">
        CSIS &middot; 1616 Rhode Island Ave NW &middot; Washington, DC 20036
      </div>
    </div>
    """)

    body = "\n".join(sections)

    return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <title>Korea Daily Brief &mdash; {_esc(date_str)}</title>
  <style type="text/css">
    /* Reset */
    body, table, td, div, p {{ margin:0; padding:0; }}
    img {{ border:0; display:block; }}
    /* Mobile responsive */
    @media only screen and (max-width: 620px) {{
      .wrapper {{ width:100% !important; }}
      .sec, .footer {{ padding:16px 14px !important; }}
      /* Market indicator table — stack on mobile */
      .mkt-table td {{ display:block !important; width:100% !important; padding:8px 14px !important; text-align:left !important; border-left:0 !important; border-right:0 !important; border-bottom:1px solid rgba(255,255,255,0.1) !important; }}
      /* BP Facility tracker — stack on mobile */
      .loc-grid td {{ display:block !important; width:100% !important; padding:4px 0 !important; }}
      .loc-grid tr {{ display:block !important; }}
      /* Calendar watch tables — stack date beside text on narrow screens */
      .cal-table td[width="50"] {{ width:40px !important; padding:8px 6px 8px 0 !important; }}
      /* ROK Government grid — stack on mobile */
      .gov-grid td {{ display:block !important; width:100% !important; padding:4px 0 !important; }}
      /* Calendar watch — reduce date font */
      .cal-date {{ font-size:18px !important; }}
      /* Deal / business cards — tighter on mobile */
      .deal-card {{ padding:10px !important; }}
      /* Deal breakdown table — full width on mobile */
      .deal-breakdown td {{ padding:3px 4px !important; font-size:10px !important; }}
      /* Sentiment tracker — 2x2 grid on mobile (no flexbox for Outlook) */
      .sentiment-table td {{ display:inline-block !important; width:48% !important; box-sizing:border-box !important; padding:10px 4px !important; text-align:center !important; }}
      /* Tariff sector table — stack on mobile */
      .tariff-sector td {{ display:block !important; width:100% !important; padding:4px 8px !important; }}
      /* Typography */
      h1 {{ font-size:19px !important; }}
      h2 {{ font-size:12px !important; }}
      h3 {{ font-size:14px !important; }}
      .key-stat-num {{ font-size:24px !important; }}
      img {{ max-width:100% !important; height:auto !important; }}
      /* Top story cards — reduce padding */
      .story-card {{ padding:12px 10px !important; }}
      /* Tighter body text on mobile */
      p, div {{ word-wrap:break-word !important; overflow-wrap:break-word !important; }}
      /* Quote cards in KCNA */
      .kcna-quote {{ padding:6px 10px !important; }}
      /* KCNA — reduce side padding so nothing is clipped on mobile */
      .kcna-dark td {{ padding-left:14px !important; padding-right:14px !important; }}
      .kcna-dark > div {{ padding:16px 14px !important; }}
      /* KCNA phrase table — prevent horizontal overflow */
      .kcna-dark table {{ table-layout:fixed !important; }}
      .kcna-dark table td {{ white-space:normal !important; word-break:break-word !important; }}
      /* Stack Kim / Output volume cards vertically on phones */
      .kcna-kv td {{ display:block !important; width:100% !important; padding-right:0 !important; padding-bottom:8px !important; }}
      /* Scale up tiny fonts for mobile readability */
      .mkt-table div {{ font-size:11px !important; }}
      .mkt-table div[style*="font-size:18px"], .mkt-table div[style*="font-size:15px"] {{ font-size:16px !important; }}
      /* Tariff headline rate — slightly smaller on mobile */
      .tariff-sector td {{ font-size:11px !important; }}
      /* Trade policy tracker — stack on narrow screens */
      .trade-policy td {{ display:block !important; width:100% !important; padding:4px 8px !important; }}
      .trade-policy tr {{ display:block !important; border-bottom:1px solid #E8E8E8 !important; padding:6px 0 !important; }}
    }}
    /* Tablet breakpoint — tighten padding, keep grids side-by-side */
    @media only screen and (min-width: 621px) and (max-width: 768px) {{
      .wrapper {{ width:100% !important; }}
      .sec, .footer {{ padding:14px 20px !important; }}
      h1 {{ font-size:21px !important; }}
      .deal-card {{ padding:12px !important; }}
      .mkt-table div[style*="font-size:18px"], .mkt-table div[style*="font-size:15px"] {{ font-size:16px !important; }}
    }}
    /* Dark mode support */
    @media (prefers-color-scheme: dark) {{
      body {{ background:#121212 !important; }}
      .wrapper {{ background:#1a1a1a !important; }}
      .wrapper .sec {{ background:#222 !important; border-bottom-color:#333 !important; }}
      .wrapper h1, .wrapper h2, .wrapper h3 {{ color:#E0E0E0 !important; }}
      .wrapper p, .wrapper div, .wrapper td, .wrapper span {{ color:#CCC !important; }}
      .wrapper a {{ color:#5DADE2 !important; }}
      .wrapper .footer {{ background:#0F1A2E !important; }}
      .wrapper .story-card {{ background:#2a2a2a !important; border-color:#333 !important; }}
      .wrapper .kcna-dark {{ background:#1a2a1a !important; }}
      .wrapper .kcna-dark table {{ background:#1a2a1a !important; }}
      .wrapper .gov-grid div {{ background:#2a2a2a !important; }}
      .wrapper .sentiment-spotlight {{ background:#1a2a3a !important; border-left-color:#2980B9 !important; color:#CCC !important; }}
      .wrapper .sentiment-discourse {{ background:#3a2a1a !important; border-left-color:#E67E22 !important; color:#CCC !important; }}
      .wrapper .deal-card {{ background:#2a2a2a !important; border-color:#333 !important; }}
      .wrapper .mkt-table td {{ border-color:#333 !important; }}
    }}
  </style>
  <!--[if mso]>
  <style type="text/css">
    table {{ border-collapse:collapse; }}
    .wrapper {{ width:680px; }}
  </style>
  <![endif]-->
</head>
<body style="margin:0;padding:0;background:#E8E8E8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
  <!--[if mso]><table width="680" cellpadding="0" cellspacing="0" border="0" align="center"><tr><td><![endif]-->
  <div class="wrapper" style="max-width:680px;width:100%;margin:0 auto;background:#FFFFFF;border-radius:6px;overflow:hidden;">
    {body}
  </div>
  <!--[if mso]></td></tr></table><![endif]-->
</body>
</html>"""


if __name__ == "__main__":
    import json
    from pathlib import Path
    digest = json.loads(Path("digest.json").read_text())
    html = render(digest)
    Path("latest.html").write_text(html, encoding="utf-8")
    print(f"Rendered {len(html):,} bytes -> latest.html")
