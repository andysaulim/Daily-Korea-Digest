"""
CSIS Korea Digest — HTML Renderer
Beyond Parallel × CSIS Korea Chair
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
_SEC = 'style="padding:20px 32px;border-bottom:1px solid #E0E0E0;" class="sec"'
_SEC_BG = lambda bg: f'style="padding:20px 32px;background:{bg};border-bottom:1px solid #E0E0E0;" class="sec"'
_H2 = lambda color: f'style="margin:0 0 12px 0;font-size:13px;color:{color};text-transform:uppercase;letter-spacing:1px;font-family:Arial,sans-serif;"'


def render(digest: dict) -> str:
    date_str = datetime.now(timezone.utc).strftime("%m/%d/%Y")
    editor_note = _esc(digest.get("editor_note", ""))
    story_count = digest.get("story_count", 0)
    oped_count = digest.get("oped_count", 0)
    academic_count = digest.get("academic_count", 0)
    gen_time = datetime.now(timezone.utc).strftime("%H:%M UTC")

    sections = []

    # ── 1. Header with Logo ──────────────────────────────────────────────
    logo_url = digest.get("logo_url", "https://raw.githubusercontent.com/andysaulim/Daily-Korea-News/main/assets/csis-korea-chair-logo.png")
    sections.append(f"""
    <div style="background:#FFFFFF;padding:20px 32px 16px;border-bottom:1px solid #E0E0E0;" class="sec header">
      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td style="vertical-align:middle;">
            <!--[if !mso]><!-->
            <img src="{logo_url}" alt="" width="420" style="max-width:100%;height:auto;display:block;" />
            <!--<![endif]-->
            <!--[if mso]>
            <table cellpadding="0" cellspacing="0" border="0"><tr>
              <td style="font-size:26px;font-weight:700;color:#1B2A4A;font-family:Georgia,serif;padding-right:12px;border-right:2px solid #8BAFCB;">CSIS</td>
              <td style="padding-left:12px;font-size:11px;color:#1B2A4A;font-family:Arial,sans-serif;line-height:1.3;text-transform:uppercase;letter-spacing:0.5px;padding-right:12px;border-right:2px solid #8BAFCB;">Center for Strategic &amp;<br>International Studies</td>
              <td style="padding-left:12px;font-size:13px;font-weight:700;color:#C0392B;font-family:Arial,sans-serif;text-transform:uppercase;letter-spacing:1px;">Korea<br>Chair</td>
            </tr></table>
            <![endif]-->
            <noscript>
              <table cellpadding="0" cellspacing="0" border="0"><tr>
                <td style="font-size:26px;font-weight:700;color:#1B2A4A;font-family:Georgia,serif;padding-right:12px;border-right:2px solid #8BAFCB;">CSIS</td>
                <td style="padding-left:12px;font-size:11px;color:#1B2A4A;font-family:Arial,sans-serif;line-height:1.3;text-transform:uppercase;letter-spacing:0.5px;padding-right:12px;border-right:2px solid #8BAFCB;">Center for Strategic &amp;<br>International Studies</td>
                <td style="padding-left:12px;font-size:13px;font-weight:700;color:#C0392B;font-family:Arial,sans-serif;text-transform:uppercase;letter-spacing:1px;">Korea<br>Chair</td>
              </tr></table>
            </noscript>
          </td>
        </tr>
      </table>
    </div>
    <div style="background:#1B2A4A;color:#fff;padding:20px 32px;" class="sec">
      <h1 style="margin:0;font-size:22px;font-weight:700;font-family:Georgia,serif;color:#fff;">
        CSIS Korea Digest
      </h1>
      <div style="margin-top:6px;font-size:13px;opacity:0.8;">{_esc(date_str)}</div>
    </div>
    """)

    # ── 2. Market Indicators ───────────────────────────────────────────────
    markets = digest.get("market_indicators") or {}
    if markets:
        kospi = markets.get("kospi") or {}
        brent = markets.get("brent") or {}
        krw = markets.get("usd_krw") or {}
        sections.append(f"""
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#1B2A4A;color:#fff;border-bottom:1px solid rgba(255,255,255,0.1);">
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

    # ── 3. Metrics bar ─────────────────────────────────────────────────────
    sections.append(f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#F8F9FA;border-bottom:1px solid #E0E0E0;">
      <tr>
        <td width="33%" align="center" style="padding:10px 4px;font-family:Arial,sans-serif;">
          <div style="font-size:20px;font-weight:700;color:#1B2A4A;">{story_count}</div>
          <div style="font-size:11px;color:#555;">Stories</div>
        </td>
        <td width="34%" align="center" style="padding:10px 4px;font-family:Arial,sans-serif;">
          <div style="font-size:20px;font-weight:700;color:#1B2A4A;">{oped_count}</div>
          <div style="font-size:11px;color:#555;">Op-Eds</div>
        </td>
        <td width="33%" align="center" style="padding:10px 4px;font-family:Arial,sans-serif;">
          <div style="font-size:20px;font-weight:700;color:#1B2A4A;">{academic_count}</div>
          <div style="font-size:11px;color:#555;">Academic</div>
        </td>
      </tr>
    </table>
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

    # ── 5. Morning Memo ────────────────────────────────────────────────────
    if editor_note:
        sections.append(f"""
        <div style="padding:20px 32px;border-bottom:2px solid #1B2A4A;" class="sec">
          <h2 {_H2("#1B2A4A")}>Morning Memo</h2>
          <p style="margin:0;font-size:14px;line-height:1.6;color:#333;font-style:italic;font-family:Georgia,serif;">
            {editor_note}
          </p>
        </div>
        """)

    # ── 6. On This Day in Korea ────────────────────────────────────────────
    on_this_day = digest.get("on_this_day") or []
    if on_this_day:
        otd_html = ""
        for item in on_this_day[:1]:
            date = _esc(item.get("date", ""))
            event = _esc(item.get("event", ""))
            relevance = _esc(item.get("relevance", ""))
            otd_html += f"""
            <div style="margin-bottom:6px;">
              <div style="font-size:12px;"><strong>{date}:</strong> {event}</div>
              <div style="font-size:11px;color:#2980B9;font-style:italic;">{relevance}</div>
            </div>"""
        sections.append(f"""
        <div style="padding:16px 32px;background:#F0EDE4;border-bottom:1px solid #E0E0E0;" class="sec">
          <h2 style="margin:0 0 8px 0;font-size:12px;color:#7F8C8D;text-transform:uppercase;letter-spacing:1px;font-family:Arial,sans-serif;">On This Day in Korea</h2>
          {otd_html}
        </div>
        """)

    # ── 7. Overnight Flash ────────────────────────────────────────────────
    overnight = digest.get("overnight_items") or []
    if overnight:
        items_html = ""
        for item in overnight:
            cat = _esc(item.get("category", ""))
            headline = _esc(item.get("headline", ""))
            body = _esc(item.get("body_text", ""))
            src = _esc(item.get("source", ""))
            url = item.get("url", "")
            items_html += f"""
            <div style="margin-bottom:12px;padding-left:14px;border-left:3px solid #1B2A4A;">
              <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:0.5px;">{cat} &middot; {src}</div>
              <div style="font-size:13px;font-weight:600;color:#1B2A4A;">
                {_link_or_text(headline, url)}
              </div>
              <div style="font-size:12px;line-height:1.4;color:#444;">{body}</div>
            </div>"""
        sections.append(f"""
        <div {_SEC}>
          <h2 {_H2("#C0392B")}>Overnight Flash</h2>
          {items_html}
        </div>
        """)

    # ── 8. Top Stories ────────────────────────────────────────────────────
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
            <div style="margin-bottom:20px;padding:14px;background:#F8F9FA;border-radius:6px;border-left:4px solid #1B2A4A;">
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

    # ── 9. Key Stat of the Day ───────────────────────────────────────────
    key_stat = digest.get("key_stat") or {}
    if key_stat and key_stat.get("number"):
        sections.append(f"""
        <div style="padding:16px 32px;background:#1B2A4A;color:#fff;border-bottom:1px solid #E0E0E0;text-align:center;" class="sec">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;opacity:0.6;margin-bottom:2px;">Stat of the Day</div>
          <div class="key-stat-num" style="font-size:32px;font-weight:700;font-family:Georgia,serif;">{_esc(str(key_stat.get("number", "")))}</div>
          <div style="font-size:12px;opacity:0.85;margin-top:2px;">{_esc(key_stat.get("label", ""))}</div>
          <div style="font-size:11px;opacity:0.65;margin-top:4px;font-style:italic;">{_esc(key_stat.get("context", ""))}</div>
          {"<div style='font-size:10px;opacity:0.45;margin-top:4px;'>Source: " + _esc(key_stat.get("source", "")) + "</div>" if key_stat.get("source") else ""}
        </div>
        """)

    # ── 10. BP Facility Tracker ─────────────────────────────────────────
    locations = digest.get("bp_locations") or []
    if locations:
        loc_rows = ""
        for loc in locations:
            name = _esc(loc.get("name", ""))
            status = loc.get("status", "normal")
            note = _esc(loc.get("note", ""))
            loc_rows += f"""
            <tr>
              <td style="padding:3px 0;" width="16">{_dot(status)}</td>
              <td style="padding:3px 8px;font-size:12px;font-weight:600;color:#1B2A4A;white-space:nowrap;">{name}</td>
              <td style="padding:3px 8px;font-size:11px;color:#555;">{note}</td>
            </tr>"""
        sections.append(f"""
        <div {_SEC}>
          <h2 {_H2("#1B2A4A")}>BP Facility Tracker</h2>
          <div style="margin-bottom:8px;font-size:10px;color:#888;">
            {_dot("normal")} Normal &nbsp;&nbsp;
            {_dot("activity")} Activity &nbsp;&nbsp;
            {_dot("elevated")} Elevated &nbsp;&nbsp;
            {_dot("alert")} Alert
          </div>
          <table width="100%" cellpadding="0" cellspacing="0" border="0" class="loc-table">
            {loc_rows}
          </table>
        </div>
        """)

    # ── 11. KCNA Delta ─────────────────────────────────────────────────────
    kcna = digest.get("kcna_delta") or {}
    if kcna:
        bottom_line = _esc(kcna.get("bottom_line", kcna.get("delta_note", "")))
        us_tone = _esc(str(kcna.get("us_tone", "—")))
        rok_tone = _esc(str(kcna.get("rok_tone", "—")))
        russia_tone = _esc(str(kcna.get("russia_tone", "—")))
        china_tone = _esc(str(kcna.get("china_tone", "—")))
        kim_today = "Yes" if kcna.get("kim_appearance_today") else "No"
        kim_activity = _esc(kcna.get("kim_activity", "")) if kcna.get("kim_activity") else ""
        days_absent = kcna.get("days_since_last_appearance")
        watch = kcna.get("watch_flag", False)
        silence = kcna.get("silence_today", False)
        tone_shift = _esc(kcna.get("tone_shift", "")) if kcna.get("tone_shift") else ""
        output_vol = _esc(kcna.get("output_volume", "")) if kcna.get("output_volume") else ""

        # Doctrinal shift (high priority — rendered prominently)
        doctrinal = _esc(kcna.get("doctrinal_shift", "")) if kcna.get("doctrinal_shift") else ""
        doctrinal_html = ""
        if doctrinal:
            doctrinal_html = f"<div style='margin:8px 0;padding:6px 12px;background:#8E44AD;color:#fff;border-radius:4px;font-size:12px;'><strong>Doctrinal shift:</strong> {doctrinal}</div>"

        # Key quotes from KCNA
        key_quotes = kcna.get("key_quotes") or []
        quotes_html = ""
        if key_quotes:
            for q in key_quotes[:2]:
                qt = _esc(q.get("quote", ""))
                src_art = _esc(q.get("source_article", ""))
                sig = _esc(q.get("significance", ""))
                quotes_html += f"""<div style='margin-top:8px;padding:8px 12px;background:rgba(0,0,0,0.04);border-radius:4px;border-left:2px solid #888;'>
                  <div style='font-size:12px;color:#333;font-style:italic;line-height:1.4;'>&ldquo;{qt}&rdquo;</div>
                  <div style='font-size:10px;color:#888;margin-top:3px;'>{src_art}</div>
                  <div style='font-size:11px;color:#2980B9;margin-top:2px;'>{sig}</div>
                </div>"""

        key_phrases = kcna.get("key_phrase_changes") or []
        phrases_html = ""
        if key_phrases:
            phrases_html = "<div style='margin-top:8px;font-size:11px;color:#555;'><strong>New rhetoric:</strong> " + ", ".join(_esc(str(p)) for p in key_phrases) + "</div>"

        # Propaganda focus
        prop_focus = kcna.get("propaganda_focus") or []
        prop_html = ""
        if prop_focus:
            prop_html = "<div style='margin-top:6px;font-size:11px;color:#555;'><strong>Focus:</strong> " + " · ".join(_esc(str(p)) for p in prop_focus) + "</div>"

        # Notable omissions
        omissions = _esc(kcna.get("notable_omissions", "")) if kcna.get("notable_omissions") else ""
        omissions_html = ""
        if omissions:
            omissions_html = f"<div style='margin-top:6px;font-size:11px;color:#E67E22;'><strong>Notable omission:</strong> {omissions}</div>"

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
                    senior_items += f" <span style='color:#2980B9;font-style:italic;'>{sig}</span>"
                senior_items += "</div>"
            senior_html = f"<div style='margin-top:8px;font-size:11px;color:#555;'>{senior_items}</div>"

        kim_line = f"<strong>Kim Jong Un:</strong> {'Appeared' if kim_today == 'Yes' else 'No appearance'}"
        if kim_today == "Yes" and kim_activity:
            kim_line += f" — {kim_activity}"
        elif days_absent and kim_today == "No":
            kim_line += f" ({days_absent} days since last)"

        vol_html = f"<span style='font-size:11px;color:#888;margin-left:8px;'>{output_vol}</span>" if output_vol else ""

        bg = '#FBE9E7' if watch else '#FDF6E3'
        sections.append(f"""
        <div {_SEC_BG(bg)}>
          <h2 {_H2("#1B2A4A")}>KCNA Delta {'<span style="color:#C0392B;">&#9888; WATCH</span>' if watch else ''}{vol_html}</h2>
          {"<div style='margin-bottom:10px;padding:6px 12px;background:#C0392B;color:#fff;border-radius:4px;font-size:12px;font-weight:600;'>&#9888; Complete KCNA silence today</div>" if silence else ""}
          <div style="margin-bottom:10px;font-size:13px;color:#333;">{kim_line}</div>
          <table class="tone-table" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:10px;">
            <tr>
              <td width="25%" style="padding:3px 8px;font-size:10px;text-transform:uppercase;color:#888;letter-spacing:0.5px;">Toward US</td>
              <td width="25%" style="padding:3px 8px;font-size:10px;text-transform:uppercase;color:#888;letter-spacing:0.5px;">Toward ROK</td>
              <td width="25%" style="padding:3px 8px;font-size:10px;text-transform:uppercase;color:#888;letter-spacing:0.5px;">Toward Russia</td>
              <td width="25%" style="padding:3px 8px;font-size:10px;text-transform:uppercase;color:#888;letter-spacing:0.5px;">Toward China</td>
            </tr>
            <tr>
              <td style="padding:3px 8px;font-size:14px;font-weight:700;color:{_tone_color(us_tone)};">{us_tone}</td>
              <td style="padding:3px 8px;font-size:14px;font-weight:700;color:{_tone_color(rok_tone)};">{rok_tone}</td>
              <td style="padding:3px 8px;font-size:14px;font-weight:700;color:{_tone_color(russia_tone)};">{russia_tone}</td>
              <td style="padding:3px 8px;font-size:14px;font-weight:700;color:{_tone_color(china_tone)};">{china_tone}</td>
            </tr>
          </table>
          {"<div style='margin-bottom:6px;font-size:12px;color:#C0392B;font-weight:600;'>&#8644; " + tone_shift + "</div>" if tone_shift else ""}
          {doctrinal_html}
          <p style="margin:0;font-size:12px;line-height:1.5;color:#333;">{bottom_line}</p>
          {quotes_html}
          {prop_html}
          {phrases_html}
          {omissions_html}
          {senior_html}
        </div>
        """)

    # ── 12. ROK Government Activity ────────────────────────────────────────
    rok_gov = digest.get("rok_government") or []
    if rok_gov:
        gov_html = ""
        for item in rok_gov:
            ministry = _esc(item.get("ministry", ""))
            official = _esc(item.get("official", ""))
            action = _esc(item.get("action", ""))
            detail = _esc(item.get("detail", ""))
            official_line = f' <span style="font-size:11px;color:#555;font-weight:400;">— {official}</span>' if official else ""
            gov_html += f"""
            <div style="margin-bottom:8px;padding-left:12px;border-left:3px solid #2980B9;">
              <div style="font-size:11px;color:#2980B9;font-weight:600;text-transform:uppercase;">{ministry}</div>
              <div style="font-size:13px;font-weight:600;color:#1B2A4A;">{action}{official_line}</div>
              <div style="font-size:12px;line-height:1.4;color:#555;">{detail}</div>
            </div>"""
        sections.append(f"""
        <div {_SEC}>
          <h2 {_H2("#2980B9")}>ROK Government Activity</h2>
          {gov_html}
        </div>
        """)

    # ── 13. ROK National Assembly ────────────────────────────────────────
    rok_assembly = digest.get("rok_assembly") or []
    if rok_assembly:
        asm_html = ""
        for item in rok_assembly:
            committee = _esc(item.get("committee", ""))
            action = _esc(item.get("action", ""))
            detail = _esc(item.get("detail", ""))
            asm_html += f"""
            <div style="margin-bottom:8px;padding-left:12px;border-left:3px solid #7F8C8D;">
              <div style="font-size:11px;color:#7F8C8D;font-weight:600;text-transform:uppercase;">{committee}</div>
              <div style="font-size:13px;font-weight:600;color:#1B2A4A;">{action}</div>
              <div style="font-size:12px;line-height:1.4;color:#555;">{detail}</div>
            </div>"""
        sections.append(f"""
        <div {_SEC}>
          <h2 {_H2("#7F8C8D")}>National Assembly</h2>
          {asm_html}
        </div>
        """)

    # ── 14. Also Today (includes Trade/Tech/Energy) ────────────────────────
    combined_also = digest.get("also_today") or []
    if combined_also:
        items_html = ""
        for item in combined_also:
            cat = _esc(item.get("category", ""))
            headline = _esc(item.get("headline", ""))
            body = _esc(item.get("body_text", ""))
            src = _esc(item.get("source", ""))
            url = item.get("url", "")
            bar_color = _color_bar(item.get("color_bar_class", "cb-navy"))
            items_html += f"""
            <div style="margin-bottom:10px;padding-left:12px;border-left:3px solid {bar_color};">
              <div style="font-size:11px;color:#888;text-transform:uppercase;">{cat} &middot; {src}</div>
              <div style="font-size:13px;font-weight:600;color:#1B2A4A;">
                {_link_or_text(headline, url)}
              </div>
              <div style="font-size:12px;line-height:1.4;color:#555;">{body}</div>
            </div>"""
        sections.append(f"""
        <div {_SEC}>
          <h2 {_H2("#1B2A4A")}>Also Today</h2>
          {items_html}
        </div>
        """)

    # ── 15. US-Korea Trade & Investment Deals ───────────────────────────────
    us_korea = digest.get("us_korea_deals") or {}
    # Support both old (array) and new (object with deals/tariff/package) format
    if isinstance(us_korea, list):
        deal_list = us_korea
        tariff_snap = None
        inv_package = None
    else:
        deal_list = us_korea.get("deals") or []
        tariff_snap = us_korea.get("tariff_snapshot")
        inv_package = us_korea.get("investment_package")

    has_content = True  # Always show — investment tracker is persistent
    if has_content:
        header_html = ""

        # Tariff snapshot bar
        if tariff_snap:
            header_html += f"""
            <div style="margin-bottom:12px;padding:8px 12px;background:#FDF6E3;border-radius:4px;border-left:3px solid #D4AC0D;">
              <div style="font-size:10px;text-transform:uppercase;color:#888;letter-spacing:0.5px;">Tariff Snapshot</div>
              <div style="font-size:13px;font-weight:600;color:#1B2A4A;">{_esc(tariff_snap)}</div>
            </div>"""

        # $350B investment package tracker — always show
        inv = inv_package or {}
        announced = _esc(str(inv.get("announced_to_date", "—")))
        total = _esc(str(inv.get("total_pledged", "$350B")))
        pct = inv.get("pct_fulfilled", 0)
        latest = _esc(inv.get("latest_update", "No new deals today"))
        bar_width = min(max(int(pct), 0), 100)
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
            bar_color = sector_colors.get(sector, "#1B2A4A")
            value_badge = f'<span style="display:inline-block;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:700;color:#fff;background:#27AE60;margin-left:6px;">{value}</span>' if value else ""
            deals_html += f"""
            <div style="margin-bottom:10px;padding-left:12px;border-left:3px solid {bar_color};">
              <div style="font-size:11px;color:#888;text-transform:uppercase;">{_esc(sector)} &middot; {src}</div>
              <div style="font-size:13px;font-weight:600;color:#1B2A4A;">
                {_link_or_text(headline, url)}{value_badge}
              </div>
              <div style="font-size:11px;color:#2980B9;">{parties}</div>
              <div style="font-size:12px;line-height:1.4;color:#555;">{detail}</div>
            </div>"""

        sections.append(f"""
        <div {_SEC}>
          <h2 {_H2("#16A085")}>US-Korea Trade &amp; Investment</h2>
          {header_html}
          {deals_html}
        </div>
        """)

    # ── 16. Op-Eds & Commentary ────────────────────────────────────────────
    opeds = digest.get("opeds_today") or []
    if opeds:
        items_html = ""
        for op in opeds:
            src = _esc(op.get("source", ""))
            arg = _esc(op.get("central_argument", ""))
            summary = _esc(op.get("summary", ""))
            so_what = _esc(op.get("policy_so_what", ""))
            url = op.get("url", "")
            items_html += f"""
            <div style="margin-bottom:12px;padding-left:12px;border-left:3px solid #D4AC0D;">
              <div style="font-size:11px;color:#888;">{src}</div>
              <div style="font-size:13px;font-weight:600;color:#1B2A4A;">
                {_link_or_text(arg, url)}
              </div>
              <div style="font-size:12px;line-height:1.4;color:#555;">{summary}</div>
              {"<div style='font-size:11px;color:#2980B9;margin-top:3px;'><strong>So what:</strong> " + so_what + "</div>" if so_what else ""}
            </div>"""
        sections.append(f"""
        <div {_SEC}>
          <h2 {_H2("#D4AC0D")}>Op-Eds &amp; Commentary</h2>
          {items_html}
        </div>
        """)

    # ── 16. Statements & Social ────────────────────────────────────────────
    social = digest.get("social_statements") or []
    if social:
        cards_html = ""
        for s in social:
            initials = _esc(s.get("avatar_initials", "?"))
            who = _esc(s.get("who", ""))
            handle = _esc(s.get("handle_context", ""))
            quote = _esc(s.get("quote_text", ""))
            note = _esc(s.get("analyst_note", ""))
            url = s.get("url", "")
            badge_color = _social_badge(s.get("badge_class", "sb-p"))
            source_link = f'<a href="{url}" style="font-size:10px;color:#2980B9;text-decoration:none;">Source &#8594;</a>' if url and url != "#" and url.startswith("http") else ""
            cards_html += f"""
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
        sections.append(f"""
        <div {_SEC}>
          <h2 {_H2("#1B2A4A")}>Official Statements</h2>
          {cards_html}
        </div>
        """)

    # ── 17. Academic Monitor ───────────────────────────────────────────────
    academic = digest.get("academic_today") or []
    if academic:
        items_html = ""
        for a in academic:
            src = _esc(a.get("source", ""))
            tier = _esc(a.get("journal_tier", ""))
            summary = _esc(a.get("summary", ""))
            implication = _esc(a.get("policy_implication", ""))
            url = a.get("url", "")
            read_link = f'<a href="{url}" style="font-size:11px;color:#2980B9;">Read &#8594;</a>' if url and url != "#" and url.startswith("http") else ""
            items_html += f"""
            <div style="margin-bottom:12px;padding-left:12px;border-left:3px solid #8E44AD;">
              <div style="font-size:11px;color:#888;">{src} &middot; {tier}</div>
              <div style="font-size:12px;line-height:1.4;color:#555;">{summary}</div>
              {"<div style='font-size:11px;color:#8E44AD;margin-top:3px;'><strong>Implication:</strong> " + implication + "</div>" if implication else ""}
              {read_link}
            </div>"""
        sections.append(f"""
        <div {_SEC}>
          <h2 {_H2("#8E44AD")}>Academic Monitor</h2>
          {items_html}
        </div>
        """)

    # ── 18. Footer ─────────────────────────────────────────────────────────
    sections.append(f"""
    <div style="padding:16px 32px;background:#F8F9FA;text-align:center;" class="sec footer">
      <div style="font-size:11px;color:#999;line-height:1.5;">
        CSIS Korea Digest &middot; CSIS Korea Chair<br>
        Generated {gen_time} &middot; Read alongside primary sources<br>
        <span style="color:#bbb;">Produced by CSIS Korea Chair</span>
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
  <title>CSIS Korea Digest &mdash; {_esc(date_str)}</title>
  <style type="text/css">
    /* Reset */
    body, table, td, div, p {{ margin:0; padding:0; }}
    img {{ border:0; display:block; }}
    /* Mobile responsive */
    @media only screen and (max-width: 620px) {{
      .wrapper {{ width:100% !important; }}
      .sec, .header, .footer {{ padding:16px 14px !important; }}
      .loc-table td {{ display:block !important; width:100% !important; padding:3px 0 !important; }}
      .loc-table td[style*="white-space"] {{ white-space:normal !important; }}
      .tone-table td {{ display:block !important; width:100% !important; padding:4px 8px !important; }}
      h1 {{ font-size:19px !important; }}
      h2 {{ font-size:12px !important; }}
      h3 {{ font-size:14px !important; }}
      .key-stat-num {{ font-size:24px !important; }}
      img {{ max-width:100% !important; height:auto !important; }}
    }}
    /* Dark mode support */
    @media (prefers-color-scheme: dark) {{
      .wrapper {{ background:#1a1a1a !important; }}
      .wrapper .sec {{ background:#222 !important; border-bottom-color:#333 !important; }}
      .wrapper h1, .wrapper h2, .wrapper h3 {{ color:#E0E0E0 !important; }}
      .wrapper p, .wrapper div {{ color:#CCC !important; }}
      .wrapper a {{ color:#5DADE2 !important; }}
      .wrapper .footer {{ background:#1a1a1a !important; }}
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
