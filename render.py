"""
Korea Intelligence Digest — HTML Renderer
Beyond Parallel × CSIS Korea Chair
Takes structured digest JSON from Claude and renders a styled HTML email.
"""
from datetime import datetime, timezone


def _esc(text: str) -> str:
    """Escape HTML special characters."""
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
        "cb-navy": "#1B2A4A",
        "cb-red": "#C0392B",
        "cb-lt": "#2980B9",
        "cb-mid": "#7F8C8D",
        "cb-nkch": "#8E44AD",
        "cb-tech": "#16A085",
        "cb-biz": "#D4AC0D",
    }
    return colors.get(css_class, "#1B2A4A")


def _signal_badge(signal_type: str) -> str:
    badge_colors = {
        "ESCALATION": "#C0392B",
        "ANOMALY": "#8E44AD",
        "DEVELOPMENT": "#2980B9",
        "CONFIRMATION": "#27AE60",
        "CONTEXT": "#7F8C8D",
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


def _arrow(val: float) -> str:
    """Return up/down/flat arrow and color based on value change."""
    if val > 0:
        return f'<span style="color:#27AE60;">▲ +{val:.1f}%</span>'
    elif val < 0:
        return f'<span style="color:#C0392B;">▼ {val:.1f}%</span>'
    return '<span style="color:#7F8C8D;">— flat</span>'


def _location_dot(status: str) -> str:
    """Return colored dot for BP location status."""
    colors = {
        "normal": "#27AE60",
        "activity": "#D4AC0D",
        "elevated": "#E67E22",
        "alert": "#C0392B",
    }
    color = colors.get(status, "#7F8C8D")
    return f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{color};margin-right:6px;vertical-align:middle;"></span>'


def render(digest: dict) -> str:
    """Render digest JSON into a full HTML email string."""
    date_str = digest.get("digest_date", datetime.now(timezone.utc).strftime("%A, %d %B %Y"))
    tension = digest.get("tension_score", "?")
    re_line = _esc(digest.get("re_line", "Korea Intelligence Digest"))
    editor_note = _esc(digest.get("editor_note", ""))
    watch_flag = digest.get("watch_flag", False)
    story_count = digest.get("story_count", 0)
    oped_count = digest.get("oped_count", 0)
    academic_count = digest.get("academic_count", 0)

    if tension != "?" and int(tension) >= 7:
        tension_color = "#C0392B"
    elif tension != "?" and int(tension) >= 4:
        tension_color = "#D4AC0D"
    else:
        tension_color = "#27AE60"

    sections = []

    # ── Header ────────────────────────────────────────────────────────────
    sections.append(f"""
    <div style="background:#1B2A4A;color:#fff;padding:28px 32px;border-radius:6px 6px 0 0;">
      <div style="font-size:11px;letter-spacing:2px;text-transform:uppercase;opacity:0.7;margin-bottom:4px;">
        Beyond Parallel · CSIS Korea Chair
      </div>
      <h1 style="margin:0;font-size:22px;font-weight:700;font-family:'Georgia',serif;">
        Korea Intelligence Digest
      </h1>
      <div style="margin-top:8px;font-size:13px;opacity:0.8;">{_esc(date_str)}</div>
      <div style="margin-top:12px;padding:8px 14px;background:rgba(255,255,255,0.12);border-radius:4px;font-size:13px;">
        <strong>RE:</strong> {re_line}
      </div>
      {"<div style='margin-top:10px;padding:6px 12px;background:#C0392B;border-radius:4px;font-size:12px;font-weight:600;'>⚠ WATCH FLAG ACTIVE</div>" if watch_flag else ""}
    </div>
    """)

    # ── Market Indicators (KOSPI, Brent, KRW) ─────────────────────────────
    markets = digest.get("market_indicators", {})
    if markets:
        kospi = markets.get("kospi") or {}
        brent = markets.get("brent") or {}
        krw = markets.get("usd_krw") or {}

        sections.append(f"""
        <div style="background:#1B2A4A;color:#fff;padding:10px 32px 14px;display:flex;border-bottom:1px solid rgba(255,255,255,0.1);">
          <div style="flex:1;text-align:center;">
            <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;opacity:0.6;">KOSPI</div>
            <div style="font-size:18px;font-weight:700;">{_esc(str(kospi.get("value", "—")))}</div>
            <div style="font-size:11px;">{_arrow(kospi.get("change_pct", 0))}</div>
          </div>
          <div style="flex:1;text-align:center;border-left:1px solid rgba(255,255,255,0.15);border-right:1px solid rgba(255,255,255,0.15);">
            <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;opacity:0.6;">Brent Crude</div>
            <div style="font-size:18px;font-weight:700;">${_esc(str(brent.get("value", "—")))}</div>
            <div style="font-size:11px;">{_arrow(brent.get("change_pct", 0))}</div>
          </div>
          <div style="flex:1;text-align:center;">
            <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;opacity:0.6;">USD/KRW</div>
            <div style="font-size:18px;font-weight:700;">{_esc(str(krw.get("value", "—")))}</div>
            <div style="font-size:11px;">{_arrow(krw.get("change_pct", 0))}</div>
          </div>
        </div>
        """)

    # ── Metrics bar ───────────────────────────────────────────────────────
    sections.append(f"""
    <div style="display:flex;background:#F8F9FA;padding:12px 32px;border-bottom:1px solid #E0E0E0;font-size:12px;color:#555;">
      <div style="flex:1;text-align:center;">
        <div style="font-size:20px;font-weight:700;color:{tension_color};">{tension}/10</div>
        <div>Tension</div>
      </div>
      <div style="flex:1;text-align:center;">
        <div style="font-size:20px;font-weight:700;color:#1B2A4A;">{story_count}</div>
        <div>Stories</div>
      </div>
      <div style="flex:1;text-align:center;">
        <div style="font-size:20px;font-weight:700;color:#1B2A4A;">{oped_count}</div>
        <div>Op-Eds</div>
      </div>
      <div style="flex:1;text-align:center;">
        <div style="font-size:20px;font-weight:700;color:#1B2A4A;">{academic_count}</div>
        <div>Academic</div>
      </div>
    </div>
    """)

    # ── Editor's Morning Memo ─────────────────────────────────────────────
    if editor_note:
        sections.append(f"""
        <div style="padding:24px 32px;border-bottom:2px solid #1B2A4A;">
          <h2 style="margin:0 0 10px 0;font-size:14px;color:#1B2A4A;text-transform:uppercase;letter-spacing:1px;">
            Morning Memo
          </h2>
          <p style="margin:0;font-size:15px;line-height:1.65;color:#333;font-style:italic;font-family:'Georgia',serif;">
            {editor_note}
          </p>
        </div>
        """)

    # ── BP Locations Tracker ──────────────────────────────────────────────
    locations = digest.get("bp_locations") or []
    if locations:
        loc_html = ""
        for loc in locations:
            name = _esc(loc.get("name", ""))
            status = loc.get("status", "normal")
            note = _esc(loc.get("note", ""))
            loc_html += f"""
            <div style="display:flex;align-items:center;margin-bottom:6px;">
              {_location_dot(status)}
              <span style="font-size:13px;font-weight:600;color:#1B2A4A;min-width:200px;">{name}</span>
              <span style="font-size:12px;color:#555;margin-left:8px;">{note}</span>
            </div>
            """
        sections.append(f"""
        <div style="padding:24px 32px;border-bottom:1px solid #E0E0E0;">
          <h2 style="margin:0 0 14px 0;font-size:14px;color:#1B2A4A;text-transform:uppercase;letter-spacing:1px;">
            BP Facility Tracker
          </h2>
          <div style="display:flex;flex-wrap:wrap;gap:2px 24px;margin-bottom:10px;font-size:10px;color:#888;">
            <span>{_location_dot("normal")} Normal</span>
            <span>{_location_dot("activity")} Activity noted</span>
            <span>{_location_dot("elevated")} Elevated</span>
            <span>{_location_dot("alert")} Alert</span>
          </div>
          {loc_html}
        </div>
        """)

    # ── ROK Government Activity ───────────────────────────────────────────
    rok_gov = digest.get("rok_government") or []
    if rok_gov:
        gov_html = ""
        for item in rok_gov:
            ministry = _esc(item.get("ministry", ""))
            action = _esc(item.get("action", ""))
            detail = _esc(item.get("detail", ""))
            url = item.get("url", "")
            link = f' <a href="{url}" style="font-size:11px;color:#2980B9;">→</a>' if url else ""
            gov_html += f"""
            <div style="margin-bottom:10px;padding-left:12px;border-left:3px solid #2980B9;">
              <div style="font-size:11px;color:#2980B9;font-weight:600;text-transform:uppercase;">{ministry}</div>
              <div style="font-size:13px;font-weight:600;color:#1B2A4A;">{action}{link}</div>
              <div style="font-size:12px;line-height:1.5;color:#555;">{detail}</div>
            </div>
            """
        sections.append(f"""
        <div style="padding:24px 32px;border-bottom:1px solid #E0E0E0;">
          <h2 style="margin:0 0 14px 0;font-size:14px;color:#2980B9;text-transform:uppercase;letter-spacing:1px;">
            ROK Government Activity
          </h2>
          {gov_html}
        </div>
        """)

    # ── KCNA Delta ────────────────────────────────────────────────────────
    kcna = digest.get("kcna_delta") or {}
    if kcna:
        delta_note = _esc(kcna.get("delta_note", ""))
        us_tone = _esc(str(kcna.get("us_tone", "—")))
        rok_tone = _esc(str(kcna.get("rok_tone", "—")))
        russia_tone = _esc(str(kcna.get("russia_tone", "—")))
        china_tone = _esc(str(kcna.get("china_tone", "—")))
        kim_today = "Yes" if kcna.get("kim_appearance_today") else "No"
        days_absent = kcna.get("days_since_last_appearance")
        watch = kcna.get("watch_flag", False)
        silence = kcna.get("silence_today", False)

        def tone_color(tone: str) -> str:
            t = tone.lower()
            if t in ("hostile", "elevated"):
                return "#C0392B"
            elif t in ("warm", "very warm", "conciliatory"):
                return "#27AE60"
            return "#7F8C8D"

        key_phrases = kcna.get("key_phrase_changes", [])
        phrases_html = ""
        if key_phrases:
            phrases_html = "<div style='margin-top:10px;font-size:12px;color:#555;'><strong>New rhetoric:</strong> " + ", ".join(_esc(str(p)) for p in key_phrases) + "</div>"

        kim_line = f"<strong>Kim Jong Un:</strong> {'Appeared today' if kim_today == 'Yes' else 'No appearance'}"
        if days_absent and kim_today == "No":
            kim_line += f" ({days_absent} days since last)"

        sections.append(f"""
        <div style="padding:24px 32px;background:{'#FBE9E7' if watch else '#FDF6E3'};border-bottom:1px solid #E0E0E0;">
          <h2 style="margin:0 0 14px 0;font-size:14px;color:#1B2A4A;text-transform:uppercase;letter-spacing:1px;">
            KCNA Delta {'<span style="color:#C0392B;">⚠ WATCH</span>' if watch else ''}
          </h2>
          {"<div style='margin-bottom:12px;padding:8px 12px;background:#C0392B;color:#fff;border-radius:4px;font-size:12px;font-weight:600;'>⚠ Complete KCNA silence today</div>" if silence else ""}
          <div style="margin-bottom:12px;font-size:13px;color:#333;">{kim_line}</div>
          <table style="width:100%;border-collapse:collapse;margin-bottom:12px;">
            <tr style="font-size:11px;text-transform:uppercase;color:#888;letter-spacing:0.5px;">
              <td style="padding:4px 8px;">Toward US</td>
              <td style="padding:4px 8px;">Toward ROK</td>
              <td style="padding:4px 8px;">Toward Russia</td>
              <td style="padding:4px 8px;">Toward China</td>
            </tr>
            <tr style="font-size:14px;font-weight:700;">
              <td style="padding:4px 8px;color:{tone_color(us_tone)};">{us_tone}</td>
              <td style="padding:4px 8px;color:{tone_color(rok_tone)};">{rok_tone}</td>
              <td style="padding:4px 8px;color:{tone_color(russia_tone)};">{russia_tone}</td>
              <td style="padding:4px 8px;color:{tone_color(china_tone)};">{china_tone}</td>
            </tr>
          </table>
          <p style="margin:0;font-size:13px;line-height:1.5;color:#333;">{delta_note}</p>
          {phrases_html}
        </div>
        """)

    # ── Overnight Flash ───────────────────────────────────────────────────
    overnight = digest.get("overnight_items") or []
    if overnight:
        items_html = ""
        for item in overnight:
            cat = _esc(item.get("category", ""))
            headline = _esc(item.get("headline", ""))
            body = _esc(item.get("body_text", ""))
            src = _esc(item.get("source", ""))
            url = item.get("url", "#")
            items_html += f"""
            <div style="margin-bottom:16px;padding-left:14px;border-left:3px solid #1B2A4A;">
              <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:2px;">{cat} · {src}</div>
              <div style="font-size:14px;font-weight:600;color:#1B2A4A;margin-bottom:4px;">
                <a href="{url}" style="color:#1B2A4A;text-decoration:none;">{headline}</a>
              </div>
              <div style="font-size:13px;line-height:1.5;color:#444;">{body}</div>
            </div>
            """
        sections.append(f"""
        <div style="padding:24px 32px;border-bottom:1px solid #E0E0E0;">
          <h2 style="margin:0 0 16px 0;font-size:14px;color:#C0392B;text-transform:uppercase;letter-spacing:1px;">
            Overnight Flash
          </h2>
          {items_html}
        </div>
        """)

    # ── Top Stories ────────────────────────────────────────────────────────
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
            url = story.get("url", "#")
            stories_html += f"""
            <div style="margin-bottom:24px;padding:18px;background:#F8F9FA;border-radius:6px;border-left:4px solid #1B2A4A;">
              <div style="margin-bottom:8px;">
                {_signal_badge(sig)}
                <span style="font-size:11px;color:#888;margin-left:8px;text-transform:uppercase;">{cat}</span>
              </div>
              <h3 style="margin:0 0 8px 0;font-size:16px;color:#1B2A4A;">
                <a href="{url}" style="color:#1B2A4A;text-decoration:none;">{headline}</a>
              </h3>
              <p style="margin:0 0 10px 0;font-size:14px;line-height:1.6;color:#333;">{body}</p>
              {"<p style='margin:0 0 8px 0;font-size:13px;line-height:1.5;color:#2980B9;'><strong>So what:</strong> " + so_what + "</p>" if so_what else ""}
              {"<p style='margin:0 0 8px 0;font-size:13px;line-height:1.5;color:#8E44AD;'><strong>Pattern:</strong> " + pattern + "</p>" if pattern else ""}
              <div style="font-size:11px;color:#999;">{src_line}</div>
            </div>
            """
        sections.append(f"""
        <div style="padding:24px 32px;border-bottom:1px solid #E0E0E0;">
          <h2 style="margin:0 0 16px 0;font-size:14px;color:#1B2A4A;text-transform:uppercase;letter-spacing:1px;">
            Top Stories
          </h2>
          {stories_html}
        </div>
        """)

    # ── Also Today ────────────────────────────────────────────────────────
    also_today = digest.get("also_today") or []
    if also_today:
        items_html = ""
        for item in also_today:
            cat = _esc(item.get("category", ""))
            headline = _esc(item.get("headline", ""))
            body = _esc(item.get("body_text", ""))
            src = _esc(item.get("source", ""))
            url = item.get("url", "#")
            bar_color = _color_bar(item.get("color_bar_class", "cb-navy"))
            items_html += f"""
            <div style="margin-bottom:12px;padding-left:12px;border-left:3px solid {bar_color};">
              <div style="font-size:11px;color:#888;text-transform:uppercase;">{cat} · {src}</div>
              <div style="font-size:13px;font-weight:600;color:#1B2A4A;">
                <a href="{url}" style="color:#1B2A4A;text-decoration:none;">{headline}</a>
              </div>
              <div style="font-size:12px;line-height:1.5;color:#555;">{body}</div>
            </div>
            """
        sections.append(f"""
        <div style="padding:24px 32px;border-bottom:1px solid #E0E0E0;">
          <h2 style="margin:0 0 16px 0;font-size:14px;color:#1B2A4A;text-transform:uppercase;letter-spacing:1px;">
            Also Today
          </h2>
          {items_html}
        </div>
        """)

    # ── Trade & Tech ──────────────────────────────────────────────────────
    trade_tech = digest.get("trade_tech_stories") or []
    if trade_tech:
        items_html = ""
        for item in trade_tech:
            headline = _esc(item.get("headline", ""))
            body = _esc(item.get("body_text", ""))
            src = _esc(item.get("source", ""))
            url = item.get("url", "#")
            items_html += f"""
            <div style="margin-bottom:12px;padding-left:12px;border-left:3px solid #16A085;">
              <div style="font-size:11px;color:#888;">{src}</div>
              <div style="font-size:13px;font-weight:600;color:#1B2A4A;">
                <a href="{url}" style="color:#1B2A4A;text-decoration:none;">{headline}</a>
              </div>
              <div style="font-size:12px;line-height:1.5;color:#555;">{body}</div>
            </div>
            """
        sections.append(f"""
        <div style="padding:24px 32px;border-bottom:1px solid #E0E0E0;">
          <h2 style="margin:0 0 16px 0;font-size:14px;color:#16A085;text-transform:uppercase;letter-spacing:1px;">
            Trade · Tech · Energy
          </h2>
          {items_html}
        </div>
        """)

    # ── Social Statements ─────────────────────────────────────────────────
    social = digest.get("social_statements") or []
    if social:
        cards_html = ""
        for s in social:
            initials = _esc(s.get("avatar_initials", "?"))
            who = _esc(s.get("who", ""))
            handle = _esc(s.get("handle_context", ""))
            quote = _esc(s.get("quote_text", ""))
            note = _esc(s.get("analyst_note", ""))
            badge_color = _social_badge(s.get("badge_class", "sb-p"))
            cards_html += f"""
            <div style="margin-bottom:16px;padding:14px;background:#F8F9FA;border-radius:6px;border-left:3px solid {badge_color};">
              <div style="display:flex;align-items:center;margin-bottom:8px;">
                <div style="width:32px;height:32px;border-radius:50%;background:{badge_color};color:#fff;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;">{initials}</div>
                <div style="margin-left:10px;">
                  <div style="font-size:13px;font-weight:600;color:#1B2A4A;">{who}</div>
                  <div style="font-size:11px;color:#888;">{handle}</div>
                </div>
              </div>
              <p style="margin:0 0 8px 0;font-size:13px;line-height:1.5;color:#333;font-style:italic;">"{quote}"</p>
              {"<p style='margin:0;font-size:12px;color:#2980B9;'><strong>Analyst:</strong> " + note + "</p>" if note else ""}
            </div>
            """
        sections.append(f"""
        <div style="padding:24px 32px;border-bottom:1px solid #E0E0E0;">
          <h2 style="margin:0 0 16px 0;font-size:14px;color:#1B2A4A;text-transform:uppercase;letter-spacing:1px;">
            Statements &amp; Social
          </h2>
          {cards_html}
        </div>
        """)

    # ── Op-Eds ────────────────────────────────────────────────────────────
    opeds = digest.get("opeds_today") or []
    if opeds:
        items_html = ""
        for op in opeds:
            src = _esc(op.get("source", ""))
            tier = _esc(op.get("prestige_tier", ""))
            arg = _esc(op.get("central_argument", ""))
            summary = _esc(op.get("summary", ""))
            so_what = _esc(op.get("policy_so_what", ""))
            url = op.get("url", "#")
            items_html += f"""
            <div style="margin-bottom:14px;padding-left:12px;border-left:3px solid #D4AC0D;">
              <div style="font-size:11px;color:#888;">{src} · Tier {tier}</div>
              <div style="font-size:13px;font-weight:600;color:#1B2A4A;">
                <a href="{url}" style="color:#1B2A4A;text-decoration:none;">{arg}</a>
              </div>
              <div style="font-size:12px;line-height:1.5;color:#555;">{summary}</div>
              {"<div style='font-size:12px;color:#2980B9;margin-top:4px;'><strong>So what:</strong> " + so_what + "</div>" if so_what else ""}
            </div>
            """
        sections.append(f"""
        <div style="padding:24px 32px;border-bottom:1px solid #E0E0E0;">
          <h2 style="margin:0 0 16px 0;font-size:14px;color:#D4AC0D;text-transform:uppercase;letter-spacing:1px;">
            Op-Eds &amp; Commentary
          </h2>
          {items_html}
        </div>
        """)

    # ── Academic ──────────────────────────────────────────────────────────
    academic = digest.get("academic_today") or []
    if academic:
        items_html = ""
        for a in academic:
            src = _esc(a.get("source", ""))
            tier = _esc(a.get("journal_tier", ""))
            summary = _esc(a.get("summary", ""))
            implication = _esc(a.get("policy_implication", ""))
            url = a.get("url", "#")
            items_html += f"""
            <div style="margin-bottom:14px;padding-left:12px;border-left:3px solid #8E44AD;">
              <div style="font-size:11px;color:#888;">{src} · {tier}</div>
              <div style="font-size:12px;line-height:1.5;color:#555;">{summary}</div>
              {"<div style='font-size:12px;color:#8E44AD;margin-top:4px;'><strong>Implication:</strong> " + implication + "</div>" if implication else ""}
              <a href="{url}" style="font-size:11px;color:#2980B9;">Read →</a>
            </div>
            """
        sections.append(f"""
        <div style="padding:24px 32px;border-bottom:1px solid #E0E0E0;">
          <h2 style="margin:0 0 16px 0;font-size:14px;color:#8E44AD;text-transform:uppercase;letter-spacing:1px;">
            Academic Monitor
          </h2>
          {items_html}
        </div>
        """)

    # ── Footer ────────────────────────────────────────────────────────────
    sections.append("""
    <div style="padding:20px 32px;background:#F8F9FA;border-radius:0 0 6px 6px;text-align:center;">
      <div style="font-size:11px;color:#999;line-height:1.6;">
        Korea Intelligence Digest · Beyond Parallel × CSIS Korea Chair<br>
        This briefing is auto-generated and should be read alongside primary sources.<br>
        <span style="color:#bbb;">Produced by Beyond Parallel Ops</span>
      </div>
    </div>
    """)

    body = "\n".join(sections)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Korea Intelligence Digest — {_esc(date_str)}</title>
</head>
<body style="margin:0;padding:0;background:#E8E8E8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <div style="max-width:680px;margin:20px auto;background:#FFFFFF;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
    {body}
  </div>
</body>
</html>"""


if __name__ == "__main__":
    import json
    from pathlib import Path
    digest = json.loads(Path("digest.json").read_text())
    html = render(digest)
    Path("latest.html").write_text(html, encoding="utf-8")
    print(f"Rendered {len(html):,} bytes → latest.html")
