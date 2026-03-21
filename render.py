"""
Korea Daily Brief — HTML Renderer
CSIS Korea Chair
Takes structured digest JSON from Claude and renders a styled HTML email.
Uses table-based layout for maximum email client compatibility.
"""
from datetime import datetime, timezone


def _esc(text: str) -> str:
    if not text:
        return ""
    return (
        str(text)
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


def _dot(status: str) -> str:
    colors = {"normal": "#27AE60", "activity": "#D4AC0D", "elevated": "#E67E22", "alert": "#C0392B"}
    color = colors.get(status, "#7F8C8D")
    return f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{color};vertical-align:middle;"></span>'


def _tone_color(tone: str) -> str:
    t = str(tone).lower()
    if t in ("hostile", "elevated"):
        return "#C0392B"
    elif t in ("warm", "very warm", "conciliatory"):
        return "#27AE60"
    elif t == "silent":
        return "#E67E22"
    return "#7F8C8D"


def _link_or_text(text: str, url: str, style: str = "color:#1B2A4A;text-decoration:none;") -> str:
    """Render as <a> only if url is a real link, otherwise plain text."""
    if url and url != "#" and url.startswith("http"):
        return f'<a href="{url}" style="{style}">{text}</a>'
    return text


# ── Section padding helper (responsive via class) ────────────────────────
_SEC = 'style="padding:14px 32px;border-bottom:1px solid #E0E0E0;" class="sec"'
_SEC_BG = lambda bg: f'style="padding:14px 32px;background:{bg};border-bottom:1px solid #E0E0E0;" class="sec"'
_H2 = lambda color: f'style="margin:0 0 8px 0;font-size:12px;color:{color};text-transform:uppercase;letter-spacing:1px;font-family:Arial,sans-serif;"'


def _estimate_word_count(digest: dict) -> int:
    """Rough word count across all text fields for 'X min read' estimate."""
    words = 0
    for key in ("editor_note", "re_line"):
        words += len(str(digest.get(key, "")).split())
    for section_key in ("top_stories", "overnight_items", "also_today", "business_economy",
                         "opeds_today", "academic_today", "social_statements"):
        for item in (digest.get(section_key) or []):
            for field in ("body", "body_text", "summary", "detail", "quote_text",
                          "so_what", "pattern_note", "central_argument", "analyst_note"):
                words += len(str(item.get(field, "")).split())
    kcna = digest.get("kcna_delta") or {}
    for field in ("bottom_line", "doctrinal_shift"):
        words += len(str(kcna.get(field, "")).split())
    return words


def render(digest: dict) -> str:
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%A, %d %B %Y")  # Thursday, 20 March 2026
    editor_note = _esc(digest.get("editor_note", ""))
    story_count = digest.get("story_count", 0)
    oped_count = digest.get("oped_count", 0)
    academic_count = digest.get("academic_count", 0)
    gen_time = now.strftime("%H:%M UTC")
    re_line = _esc(digest.get("re_line", ""))
    word_count = _estimate_word_count(digest)
    read_min = max(1, round(word_count / 250))

    sections = []

    # ── 1. Header ────────────────────────────────────────────────────────
    logo_url = digest.get("logo_url", "https://raw.githubusercontent.com/andysaulim/Daily-Korea-News/main/assets/csis-korea-chair-logo.png")
    sections.append(f"""
    <div style="background:#FFFFFF;padding:14px 32px 10px;" class="sec header">
      <!--[if !mso]><!-->
      <img src="{logo_url}" alt="" width="420" style="max-width:100%;height:auto;display:block;" />
      <!--<![endif]-->
      <!--[if mso]>
      <table cellpadding="0" cellspacing="0" border="0"><tr>
        <td style="font-size:22px;font-weight:700;color:#1B2A4A;font-family:Georgia,serif;padding-right:10px;border-right:2px solid #8BAFCB;">CSIS</td>
        <td style="padding-left:10px;font-size:10px;color:#1B2A4A;font-family:Arial,sans-serif;line-height:1.3;text-transform:uppercase;letter-spacing:0.5px;">Korea Chair</td>
      </tr></table>
      <![endif]-->
      <noscript>
        <div style="font-size:16px;font-weight:700;color:#1B2A4A;font-family:Georgia,serif;">CSIS Korea Chair</div>
      </noscript>
    </div>
    <div style="background:#1B2A4A;color:#fff;padding:14px 32px 12px;" class="sec">
      <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
        <td style="vertical-align:top;">
          <h1 style="margin:0;font-size:24px;font-weight:700;font-family:Georgia,serif;color:#fff;letter-spacing:0.5px;">
            Korea Daily Brief
          </h1>
          <div style="margin-top:4px;font-size:13px;color:rgba(255,255,255,0.7);">{_esc(date_str)}</div>
        </td>
        <td style="vertical-align:top;text-align:right;">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:rgba(255,255,255,0.4);margin-bottom:2px;">{gen_time}</div>
          <div style="font-size:10px;color:rgba(255,255,255,0.35);">{story_count + oped_count + academic_count} sources &middot; {read_min} min read</div>
        </td>
      </tr></table>
      {"<div style='margin-top:10px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.15);font-size:13px;color:rgba(255,255,255,0.85);font-family:Georgia,serif;'><strong style=" + '"' + "color:rgba(255,255,255,0.5);" + '"' + ">RE:</strong> " + re_line + "</div>" if re_line else ""}
    </div>
    """)

    # ── 2. Market Indicators ───────────────────────────────────────────────
    markets = digest.get("market_indicators") or {}
    if markets:
        kospi = markets.get("kospi") or {}
        brent = markets.get("brent") or {}
        krw = markets.get("usd_krw") or {}
        sections.append(f"""
        <table class="mkt-table" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#1B2A4A;color:#fff;border-bottom:1px solid rgba(255,255,255,0.1);">
          <tr>
            <td width="33%" align="center" style="padding:10px 8px 12px;">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;opacity:0.6;">KOSPI</div>
              <div style="font-size:18px;font-weight:700;">{_esc(str(kospi.get("value", "—")))}</div>
              <div style="font-size:11px;">{_arrow(kospi.get("change_pct", 0))}</div>
            </td>
            <td width="34%" align="center" style="padding:10px 8px 12px;border-left:1px solid rgba(255,255,255,0.15);border-right:1px solid rgba(255,255,255,0.15);">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;opacity:0.6;">Brent Crude</div>
              <div style="font-size:18px;font-weight:700;">${_esc(str(brent.get("value", "—")))}</div>
              <div style="font-size:11px;">{_arrow(brent.get("change_pct", 0))}</div>
            </td>
            <td width="33%" align="center" style="padding:10px 8px 12px;">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;opacity:0.6;">USD/KRW</div>
              <div style="font-size:18px;font-weight:700;">{_esc(str(krw.get("value", "—")))}</div>
              <div style="font-size:11px;">{_arrow(krw.get("change_pct", 0))}</div>
            </td>
          </tr>
        </table>
        """)

    # ── 3. Morning Memo ────────────────────────────────────────────────────
    if editor_note:
        sections.append(f"""
        <div style="padding:14px 32px;border-bottom:2px solid #1B2A4A;" class="sec">
          <h2 {_H2("#1B2A4A")}>Morning Memo</h2>
          <p style="margin:0;font-size:14px;line-height:1.6;color:#333;font-style:italic;font-family:Georgia,serif;">
            {editor_note}
          </p>
        </div>
        """)

    # ── 4. What to Watch Today ─────────────────────────────────────────────
    watch_today = digest.get("watch_today") or []
    if watch_today:
        urgency_colors = {"critical": "#C0392B", "high": "#E67E22", "monitor": "#7F8C8D"}
        watch_html = ""
        for item in watch_today:
            headline = _esc(item.get("headline", ""))
            detail = _esc(item.get("detail", ""))
            time_str = _esc(item.get("time", ""))
            urgency = item.get("urgency", "monitor")
            decision = _esc(item.get("decision_point", ""))
            u_color = urgency_colors.get(urgency, "#7F8C8D")
            time_badge = f'<span style="display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600;color:#fff;background:{u_color};margin-left:6px;text-transform:uppercase;">{_esc(urgency)}</span>' if urgency else ""
            time_line = f'<span style="font-size:11px;color:#888;margin-left:8px;">{time_str}</span>' if time_str else ""
            watch_html += f"""
            <div style="margin-bottom:10px;padding-left:12px;border-left:3px solid {u_color};">
              <div style="font-size:13px;font-weight:600;color:#1B2A4A;">{headline}{time_badge}{time_line}</div>
              <div style="font-size:12px;line-height:1.4;color:#555;">{detail}</div>
              {"<div style='font-size:11px;color:#2980B9;margin-top:2px;font-style:italic;'>&#9654; " + decision + "</div>" if decision else ""}
            </div>"""
        sections.append(f"""
        <div {_SEC}>
          <h2 {_H2("#E67E22")}>What to Watch Today</h2>
          {watch_html}
        </div>
        """)

    # ── 5. Top Stories ────────────────────────────────────────────────────
    top_stories = digest.get("top_stories") or []
    if top_stories:
        stories_html = ""
        for story in top_stories:
            cat = _esc(story.get("category_tag", story.get("category", "")))
            sig = story.get("signal_type", "")
            headline = _esc(story.get("headline", ""))
            body = _esc(story.get("body", ""))
            so_what = _esc(story.get("so_what", ""))
            pattern = _esc(story.get("pattern_note", ""))
            src_line = _esc(story.get("src_line", story.get("source", "")))
            url = story.get("url", "")
            stories_html += f"""
            <div class="story-card" style="margin-bottom:12px;padding:10px 12px;background:#F8F9FA;border-radius:4px;border-left:4px solid #1B2A4A;">
              <div style="margin-bottom:6px;">
                {_signal_badge(sig)}
                <span style="font-size:11px;color:#888;margin-left:8px;text-transform:uppercase;">{cat}</span>
              </div>
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
          <h2 {_H2("#1B2A4A")}>Top Stories</h2>
          {stories_html}
        </div>
        """)

    # ── 6. Key Stat of the Day ───────────────────────────────────────────
    key_stat = digest.get("key_stat") or {}
    if key_stat and key_stat.get("number"):
        sections.append(f"""
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
    if kcna:
        bottom_line = _esc(kcna.get("bottom_line", kcna.get("delta_note", "")))
        watch = kcna.get("watch_flag", False)
        silence = kcna.get("silence_today", False)
        tone_shift = _esc(kcna.get("tone_shift", "")) if kcna.get("tone_shift") else ""
        output_vol = _esc(kcna.get("output_volume", "")) if kcna.get("output_volume") else ""

        # Doctrinal shift (high priority — rendered prominently)
        doctrinal = _esc(kcna.get("doctrinal_shift", "")) if kcna.get("doctrinal_shift") else ""
        doctrinal_html = ""
        if doctrinal:
            doctrinal_html = f"<div style='margin:12px 0;padding:8px 14px;background:#8E44AD;color:#fff;border-radius:4px;font-size:12px;'><strong>Doctrinal shift:</strong> {doctrinal}</div>"

        # Key quotes from KCNA
        key_quotes = kcna.get("key_quotes") or []
        quotes_html = ""
        if key_quotes:
            for q in key_quotes[:2]:
                qt = _esc(q.get("quote", ""))
                src_art = _esc(q.get("source_article", ""))
                sig = _esc(q.get("significance", ""))
                quotes_html += f"""<div class='kcna-quote' style='margin-top:8px;padding:8px 12px;background:rgba(255,255,255,0.05);border-radius:4px;border-left:2px solid #555;'>
                  <div style='font-size:12px;color:#D0D0D0;font-style:italic;line-height:1.4;'>&ldquo;{qt}&rdquo;</div>
                  <div style='font-size:10px;color:#888;margin-top:3px;'>{src_art}</div>
                  <div style='font-size:11px;color:#5DADE2;margin-top:2px;'>{sig}</div>
                </div>"""

        # Notable omissions
        omissions = _esc(kcna.get("notable_omissions", "")) if kcna.get("notable_omissions") else ""
        omissions_html = ""
        if omissions:
            omissions_html = f"<div style='margin-top:8px;font-size:11px;color:#E67E22;'><strong>Notable omission:</strong> {omissions}</div>"

        # Senior officials
        senior = kcna.get("senior_officials") or []
        senior_html = ""
        if senior:
            senior_items = ""
            for s in senior:
                name = _esc(s.get("name", ""))
                role = _esc(s.get("role", ""))
                act = _esc(s.get("activity", ""))
                sig = _esc(s.get("significance", ""))
                role_str = f' <span style="color:#888;">({role})</span>' if role else ""
                senior_items += f"<div style='margin-bottom:4px;'><strong>{name}</strong>{role_str}: {act}"
                if sig:
                    senior_items += f" <span style='color:#5DADE2;font-style:italic;'>{sig}</span>"
                senior_items += "</div>"
            senior_html = f"<div style='margin-top:10px;font-size:11px;color:#BBB;'>{senior_items}</div>"

        # Kim Jong Un line
        kim_today = "Yes" if kcna.get("kim_appearance_today") else "No"
        kim_activity = _esc(kcna.get("kim_activity", "")) if kcna.get("kim_activity") else ""
        days_absent = kcna.get("days_since_last_appearance")

        # Inline tone labels (compact row instead of 2x2 grid)
        country_configs = [
            ("US", "us_tone"),
            ("Russia", "russia_tone"),
            ("China", "china_tone"),
            ("ROK", "rok_tone"),
        ]
        tone_inline_parts = []
        for country_name, tone_key in country_configs:
            tone_val = _esc(str(kcna.get(tone_key, "—")))
            tone_qualifier = _esc(kcna.get(tone_key.replace("_tone", "_qualifier"), "")) if kcna.get(tone_key.replace("_tone", "_qualifier")) else ""
            label = f"{tone_val} — {tone_qualifier}" if tone_qualifier else tone_val
            t_color = _tone_color(tone_val)
            tone_inline_parts.append(
                f'<span style="color:#888;">{_esc(country_name)}:</span> '
                f'<span style="color:{t_color};font-weight:600;">{label}</span>'
            )
        tone_inline = f"""
        <div style="margin-bottom:12px;font-size:12px;line-height:1.8;">
          {"  &middot;  ".join(tone_inline_parts)}
        </div>"""

        # Propaganda focus & Kim appearance as inline items
        prop_focus = kcna.get("propaganda_focus") or []
        prop_html = ""
        if prop_focus:
            prop_html = "<div style='margin-top:8px;font-size:11px;color:#888;'><strong style=\"color:#BBB;\">Focus:</strong> " + " · ".join(_esc(str(p)) for p in prop_focus) + "</div>"

        kim_line_html = ""
        kim_line = ""
        if kim_today == "Yes":
            kim_line = f"Kim Jong Un public appearance"
            if kim_activity:
                kim_line += f" — {kim_activity}"
        else:
            kim_line = "No Kim Jong Un appearance"
            if days_absent:
                kim_line += f" ({days_absent} days since last)"

        # KCNA Watch link
        kcna_baseline = _esc(kcna.get("baseline_period", ""))
        kcna_watch_url = kcna.get("kcna_watch_url", "")
        baseline_html = ""
        if kcna_baseline:
            baseline_html = f"7-day baseline · {kcna_baseline}"
        if kcna_watch_url:
            baseline_html += f" · KCNA Watch ↗"
        elif not baseline_html:
            baseline_html = "7-day baseline · KCNA Watch ↗"

        sections.append(f"""
        <div style="padding:0;border-bottom:1px solid #333;" class="sec kcna-dark">
          <div style="padding:10px 32px;background:#1a2a1a;display:flex;justify-content:space-between;align-items:center;">
            <div style="display:flex;align-items:center;gap:10px;">
              <span style="font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:1.5px;color:#E8DCC8;font-family:Arial,sans-serif;">KCNA Rhetoric Delta</span>
              <span style="display:inline-block;width:60px;height:2px;background:#27AE60;"></span>
            </div>
            <span style="font-size:11px;color:rgba(255,255,255,0.4);">{baseline_html}</span>
          </div>
          <div style="padding:14px 32px;background:#1a2a1a;color:#E0E0E0;">
            {"<div style='margin-bottom:12px;padding:8px 14px;background:#C0392B;color:#fff;border-radius:4px;font-size:12px;font-weight:600;'>&#9888; Complete KCNA silence today</div>" if silence else ""}
            {doctrinal_html}
            {tone_inline}
            {"<div style='margin-bottom:8px;font-size:12px;color:#E67E22;font-weight:600;'>&#8644; " + tone_shift + "</div>" if tone_shift else ""}
            <div style="margin-bottom:8px;font-size:12px;color:#D0D0D0;">
              {"&#9679; " + kim_line if kim_line else ""}
              {"<span style='margin-left:12px;color:#888;'>" + output_vol + "</span>" if output_vol else ""}
            </div>
            {quotes_html}
            {prop_html}
            {omissions_html}
            {senior_html}
            {"<div style='margin-top:12px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.1);font-size:13px;line-height:1.6;color:#E0E0E0;font-family:Georgia,serif;'><strong style=" + chr(34) + "color:#E8DCC8;" + chr(34) + ">Bottom line:</strong> " + bottom_line + "</div>" if bottom_line else ""}
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
                            _src_parts.append(f'<a href="{s_url}" style="font-size:11px;font-family:monospace;color:#888;text-decoration:none;">{s_label} ↗</a>')
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

        # BP Monitored Locations status table
        loc_rows = ""
        _badge_styles = {
            "normal": ("#27AE60", "#E8F8F0", "Normal"),
            "activity": ("#D4AC0D", "#FDF6E3", "Active"),
            "elevated": ("#E67E22", "#FFF3E0", "Active ▲"),
            "alert": ("#C0392B", "#FBE9E7", "Active ▲"),
        }
        for loc in locations:
            name = _esc(loc.get("name", ""))
            status = loc.get("status", "normal")
            note = _esc(loc.get("note", ""))
            last_report = _esc(loc.get("last_report", ""))
            direction = loc.get("direction", "")  # "up", "down", or ""
            b_color, b_bg, b_label = _badge_styles.get(status, ("#7F8C8D", "#F5F5F5", "Monitor"))
            # Override label based on status and direction
            if status == "normal":
                b_label = "Monitor"
                b_color = "#888"
                b_bg = "#F5F5F5"
            elif direction == "down":
                b_label = "Active ↓"
                b_color = "#E67E22"
                b_bg = "#FFF3E0"
            elif direction == "up":
                b_label = "Active ▲"
            loc_rows += f"""
            <tr style="border-bottom:1px solid #F0F0F0;">
              <td style="padding:8px 0;vertical-align:top;">
                <div style="font-size:13px;font-weight:600;color:#1B2A4A;">{name}</div>
                <div style="font-size:11px;line-height:1.4;color:#666;margin-top:2px;">{note}</div>
              </td>
              <td style="padding:8px 8px;text-align:center;vertical-align:top;" width="90">
                <span style="display:inline-block;padding:2px 10px;border-radius:3px;font-size:10px;font-weight:600;color:{b_color};background:{b_bg};white-space:nowrap;">{b_label}</span>
                <div style="font-size:10px;color:#999;margin-top:2px;">{last_report}</div>
              </td>
            </tr>"""

        loc_date = _esc(str(digest.get("digest_date", "")))
        sections.append(f"""
        <div {_SEC}>
          <h2 {_H2("#1B2A4A")}>Satellite &amp; Location Watch <span style="font-size:10px;font-weight:400;color:#888;text-transform:none;letter-spacing:0;">BP catalogue &middot; {loc_date}</span></h2>
          <div style="padding-top:4px;">
            {img_report_html}
            <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:#1B2A4A;margin-bottom:8px;padding-bottom:4px;border-bottom:1px solid #E8E8E8;">BP Monitored Locations — Current Status</div>
            <table width="100%" cellpadding="0" cellspacing="0" border="0" class="loc-table">
              {loc_rows}
            </table>
          </div>
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
                    src_link = f'<div style="margin-top:6px;font-size:11px;color:#888;">→ <a href="{source_url}" style="color:#888;text-decoration:none;">{_esc(s_label)} ↗</a></div>'
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

        # Calendar Watch section
        cal_html = ""
        if calendar_watch:
            cal_items = ""
            cal_type_colors = {
                "watch": "#D4AC0D", "event": "#888", "hearing": "#C0392B",
                "exercise": "#2980B9", "deadline": "#E67E22", "anniversary": "#8E44AD",
                "risk": "#C0392B", "prep": "#C0392B",
            }
            for cal in calendar_watch:
                cal_month = _esc(cal.get("month", ""))
                cal_day = _esc(str(cal.get("day", "")))
                cal_type = _esc(cal.get("type", "event"))
                cal_type_label = _esc(cal.get("type_label", cal_type.upper()))
                cal_headline = _esc(cal.get("headline", ""))
                cal_detail = _esc(cal.get("detail", ""))
                cal_urgency = cal.get("urgency", "")
                t_color = cal_type_colors.get(cal_type.lower(), "#888")
                # Urgency suffix
                urgency_html = ""
                if cal_urgency and cal_urgency.lower() in ("critical", "elevated", "high"):
                    urgency_html = f' · <span style="color:#C0392B;font-weight:600;">{_esc(cal_urgency.upper())}</span>'
                cal_items += f"""
                <div style="display:flex;padding:14px 0;border-bottom:1px solid #E8E8E8;">
                  <div style="min-width:60px;text-align:center;padding-right:14px;">
                    <div style="font-size:10px;text-transform:uppercase;color:#C0392B;font-weight:600;letter-spacing:0.5px;">{cal_month}</div>
                    <div style="font-size:28px;font-weight:300;color:#1B2A4A;line-height:1;">{cal_day}</div>
                  </div>
                  <div style="flex:1;">
                    <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.5px;color:{t_color};font-weight:600;margin-bottom:3px;">{cal_type_label}{urgency_html}</div>
                    <div style="font-size:14px;font-weight:600;color:#1B2A4A;margin-bottom:3px;">{cal_headline}</div>
                    <div style="font-size:12px;line-height:1.5;color:#555;">{cal_detail}</div>
                  </div>
                </div>"""
            cal_html = f"""
            <div style="margin-top:20px;">
              <div style="padding:10px 0;display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid #1B2A4A;margin-bottom:4px;">
                <span style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:#1B2A4A;">Calendar Watch</span>
                <span style="font-size:11px;color:#888;">14 days forward</span>
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
          <h2 {_H2("#1B2A4A")}>ROK Government <span style="font-size:10px;font-weight:400;color:#888;text-transform:none;letter-spacing:0;">President + Ministries &middot; {rok_date}</span></h2>
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
    # Support both old (array) and new (object with deals/tariff/package) format
    if isinstance(us_korea, list):
        deal_list = us_korea
        tariff_snap = None
        inv_package = None
        status_tracker = []
    else:
        deal_list = us_korea.get("deals") or []
        tariff_snap = us_korea.get("tariff_snapshot")
        inv_package = us_korea.get("investment_package")
        status_tracker = us_korea.get("status_tracker") or []

    has_content = True  # Always show — investment tracker is persistent
    if has_content:
        header_html = ""

        # Status tracker table (policy items with status badges)
        tracker_status_colors = {
            "active": ("#27AE60", "#E8F8F0"), "passed": ("#27AE60", "#E8F8F0"),
            "risk": ("#C0392B", "#FBE9E7"), "monitor": ("#555", "#F5F5F5"),
            "pressure": ("#555", "#F5F5F5"), "stalled": ("#E67E22", "#FDF6E3"),
            "pending": ("#2980B9", "#EBF5FB"),
        }
        if status_tracker:
            tracker_rows = ""
            for tr_item in status_tracker:
                tr_name = _esc(tr_item.get("item", ""))
                tr_detail = _esc(tr_item.get("detail", ""))
                tr_status = tr_item.get("status", "monitor").lower()
                tr_color, tr_bg = tracker_status_colors.get(tr_status, ("#555", "#F5F5F5"))
                tracker_rows += f"""
                <tr>
                  <td style="padding:10px 14px;border-bottom:1px solid #E8E8E8;vertical-align:top;">
                    <div style="font-size:13px;font-weight:600;color:#1B2A4A;">{tr_name}</div>
                    <div style="font-size:12px;color:#666;line-height:1.4;margin-top:2px;">{tr_detail}</div>
                  </td>
                  <td style="padding:10px 14px;border-bottom:1px solid #E8E8E8;text-align:right;vertical-align:middle;white-space:nowrap;" width="100">
                    <span style="display:inline-block;padding:3px 10px;border-radius:3px;font-size:11px;font-weight:600;color:{tr_color};border:1.5px solid {tr_color};text-transform:uppercase;letter-spacing:0.5px;">{_esc(tr_status.upper())}</span>
                  </td>
                </tr>"""
            header_html += f"""
            <div style="margin-bottom:16px;background:#FAFAF5;border-radius:4px;overflow:hidden;">
              <div style="padding:10px 14px;background:#F0EDE4;">
                <span style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:#1B2A4A;">Korea Strategic Trade &amp; Investment — Status Tracker</span>
              </div>
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                {tracker_rows}
              </table>
            </div>"""

        # Tariff snapshot bar
        if tariff_snap and not status_tracker:
            header_html += f"""
            <div style="margin-bottom:12px;padding:8px 12px;background:#FDF6E3;border-radius:4px;border-left:3px solid #D4AC0D;">
              <div style="font-size:10px;text-transform:uppercase;color:#888;letter-spacing:0.5px;">Tariff Snapshot</div>
              <div style="font-size:13px;font-weight:600;color:#1B2A4A;">{_esc(tariff_snap)}</div>
            </div>"""

        # $350B investment package tracker — always show
        inv = inv_package or {}
        announced = _esc(str(inv.get("announced_to_date", "—")))
        total = _esc(str(inv.get("total_pledged", "$350B")))
        pct_raw = inv.get("pct_fulfilled", 0)
        try:
            pct = int(str(pct_raw).replace("%", "").strip())
        except (ValueError, TypeError):
            pct = 0
        latest = _esc(inv.get("latest_update", "No new deals today"))
        bar_width = min(max(pct, 0), 100)
        if True:
            header_html += f"""
            <div style="margin-bottom:12px;padding:8px 12px;background:#F8F9FA;border-radius:4px;border-left:3px solid #16A085;">
              <div style="font-size:10px;text-transform:uppercase;color:#888;letter-spacing:0.5px;">ROK Investment Commitment</div>
              <div style="font-size:14px;font-weight:700;color:#1B2A4A;margin-top:2px;">{announced} <span style="font-size:11px;font-weight:400;color:#888;">of {total} pledged</span></div>
              <div style="margin-top:4px;background:#E0E0E0;border-radius:3px;height:8px;overflow:hidden;">
                <div style="width:{bar_width}%;background:#16A085;height:100%;border-radius:3px;"></div>
              </div>
              <div style="font-size:11px;color:#555;margin-top:4px;">{pct}% fulfilled · {latest}</div>
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
            value_badge = f'<span style="display:inline-block;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:700;color:#fff;background:#27AE60;margin-left:6px;">{value}</span>' if value else ""
            # Category tags
            tags_html = ""
            if d_tags:
                tags_html = " ".join(
                    f'<span style="display:inline-block;padding:2px 6px;border:1px solid #2980B9;border-radius:2px;font-size:9px;font-weight:600;color:#2980B9;text-transform:uppercase;margin-right:4px;">{_esc(t)}</span>'
                    for t in d_tags[:3]
                )
                tags_html = f'<div style="margin-bottom:4px;">{tags_html}</div>'
            # Source / parties attribution line on the right
            meta_right = f'<span style="font-size:11px;color:#888;">{parties}</span>' if parties else ""
            deals_html += f"""
            <div style="margin-bottom:14px;padding:12px 0;border-top:1px solid #E8E8E8;">
              {tags_html}
              <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                <div style="flex:1;">
                  <div style="font-size:11px;color:#888;margin-bottom:2px;">{meta_right} {('&middot; ' + src) if src else ''}</div>
                </div>
              </div>
              <div style="font-size:15px;font-weight:700;color:#1B2A4A;line-height:1.3;margin-bottom:4px;">
                {_link_or_text(headline, url, style="color:#1B4A6A;text-decoration:none;")}{value_badge}
              </div>
              <div style="font-size:13px;line-height:1.5;color:#444;">{detail}</div>
              {"<div style='margin-top:6px;'><a href='" + url + "' style='font-size:11px;font-family:monospace;color:#888;text-decoration:none;'>" + _esc(src) + " ↗</a></div>" if src and url and url != "#" and url.startswith("http") else ""}
            </div>"""

        sections.append(f"""
        <div {_SEC}>
          <h2 {_H2("#1B2A4A")}>US-Korea Trade &amp; Investment <span style="font-size:10px;font-weight:400;color:#888;text-transform:none;letter-spacing:0;">deal tracker</span></h2>
          {header_html}
          {deals_html}
        </div>
        """)

    # ── 11. The Wire (merged: Overnight + Also Today + Business) ─────────
    overnight = digest.get("overnight_items") or []
    combined_also = digest.get("also_today") or []
    biz_econ = digest.get("business_economy") or []
    wire_items = overnight + combined_also + biz_econ
    if wire_items:
        wire_html = ""
        biz_sector_colors = {
            "tech": "#8E44AD", "auto": "#1B2A4A", "energy": "#16A085",
            "finance": "#D4AC0D", "manufacturing": "#2980B9",
            "real-estate": "#E67E22", "macro": "#C0392B",
        }
        for item in wire_items:
            cat = _esc(item.get("category", item.get("sector", "")))
            headline = _esc(item.get("headline", ""))
            body = _esc(item.get("body_text", ""))
            src = _esc(item.get("source", ""))
            url = item.get("url", "")
            bar_color = _color_bar(item.get("color_bar_class", ""))
            if not item.get("color_bar_class"):
                bar_color = biz_sector_colors.get(item.get("sector", ""), "#1B2A4A")
            companies = item.get("companies") or []
            company_tags = ""
            if companies:
                company_tags = " ".join(
                    f'<span style="display:inline-block;padding:1px 5px;border-radius:3px;font-size:9px;background:#E8E8E8;color:#555;margin-right:3px;">{_esc(c)}</span>'
                    for c in companies[:3]
                )
                company_tags = f'<div style="margin-top:3px;">{company_tags}</div>'
            wire_html += f"""
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
          <h2 {_H2("#1B2A4A")}>The Wire</h2>
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
            source_link = f'<a href="{url}" style="font-size:10px;color:#2980B9;text-decoration:none;">Source &#8594;</a>' if url and url != "#" and url.startswith("http") else ""
            sa_html += f"""
            <div style="margin-bottom:12px;padding:12px;background:#F8F9FA;border-radius:6px;border-left:3px solid {badge_color};">
              <table cellpadding="0" cellspacing="0" border="0" style="margin-bottom:6px;">
                <tr>
                  <td width="28" style="vertical-align:middle;">
                    <div style="width:28px;height:28px;border-radius:50%;background:{badge_color};color:#fff;text-align:center;line-height:28px;font-size:11px;font-weight:700;">{initials}</div>
                  </td>
                  <td style="padding-left:8px;vertical-align:middle;">
                    <div style="font-size:12px;font-weight:600;color:#1B2A4A;">{who}</div>
                    <div style="font-size:10px;color:#888;">{handle}</div>
                  </td>
                </tr>
              </table>
              <p style="margin:0 0 6px 0;font-size:12px;line-height:1.4;color:#333;font-style:italic;">&ldquo;{quote}&rdquo;</p>
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
            read_link = f'<a href="{url}" style="font-size:11px;color:#2980B9;">Read &#8594;</a>' if url and url != "#" and url.startswith("http") else ""
            sa_html += f"""
            <div style="margin-bottom:12px;padding-left:12px;border-left:3px solid #8E44AD;">
              <div style="font-size:11px;color:#888;">{src} &middot; {tier}</div>
              <div style="font-size:12px;line-height:1.4;color:#555;">{summary}</div>
              {"<div style='font-size:11px;color:#8E44AD;margin-top:3px;'><strong>Implication:</strong> " + implication + "</div>" if implication else ""}
              {read_link}
            </div>"""
        sections.append(f"""
        <div {_SEC}>
          <h2 {_H2("#1B2A4A")}>Statements &amp; Analysis</h2>
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
        <div style="text-align:left;margin-bottom:14px;padding:10px 14px;background:#F0EDE4;border-radius:4px;">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#7F8C8D;margin-bottom:4px;">On This Day</div>
          <div style="font-size:12px;color:#333;"><strong>{otd_date}:</strong> {otd_event}</div>
          <div style="font-size:11px;color:#2980B9;font-style:italic;">{otd_rel}</div>
        </div>"""
    sections.append(f"""
    <div style="padding:16px 32px;background:#F8F9FA;text-align:center;" class="sec footer">
      {otd_footer}
      <div style="font-size:11px;color:#999;line-height:1.5;">
        Korea Daily Brief &middot; CSIS Korea Chair<br>
        {_esc(date_str)} &middot; {gen_time}<br>
        <span style="color:#bbb;">Read alongside primary sources</span>
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
      .sec, .header, .footer {{ padding:16px 14px !important; }}
      /* Market indicator table — stack on mobile */
      .mkt-table td {{ display:block !important; width:100% !important; padding:8px 14px !important; text-align:left !important; border-left:0 !important; border-right:0 !important; border-bottom:1px solid rgba(255,255,255,0.1) !important; }}
      /* BP Facility tracker — wrap long names */
      .loc-table td {{ display:block !important; width:100% !important; padding:3px 0 !important; }}
      .loc-table td[style*="white-space"] {{ white-space:normal !important; }}
      .loc-table tr {{ display:block !important; padding:6px 0 !important; border-bottom:1px solid #f0f0f0 !important; }}
      /* KCNA tone table — 2x2 grid on mobile */
      .tone-table td {{ display:inline-block !important; width:48% !important; padding:6px 4px !important; box-sizing:border-box !important; }}
      /* ROK Government grid — stack on mobile */
      .gov-grid td {{ display:block !important; width:100% !important; padding:4px 0 !important; }}
      /* Calendar watch — reduce date font */
      .cal-date {{ font-size:22px !important; }}
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
    }}
    /* Dark mode support */
    @media (prefers-color-scheme: dark) {{
      .wrapper {{ background:#1a1a1a !important; }}
      .wrapper .sec {{ background:#222 !important; border-bottom-color:#333 !important; }}
      .wrapper h1, .wrapper h2, .wrapper h3 {{ color:#E0E0E0 !important; }}
      .wrapper p, .wrapper div {{ color:#CCC !important; }}
      .wrapper a {{ color:#5DADE2 !important; }}
      .wrapper .footer {{ background:#1a1a1a !important; }}
      .wrapper .story-card {{ background:#2a2a2a !important; }}
      .wrapper .kcna-dark {{ background:#1a2a1a !important; }}
      .wrapper .kcna-dark div {{ background:transparent !important; }}
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
