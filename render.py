"""
Korea Daily Brief — HTML Renderer
CSIS Korea Chair
Takes structured digest JSON from Claude and renders a styled HTML email.
Uses table-based layout for maximum email client compatibility.
"""
import re as _re
from datetime import datetime, timezone
from urllib.parse import urlparse as _urlparse


def _clean_src(raw: str) -> str:
    """Strip raw URLs from source lines, keeping only human-readable text.

    If the entire src_line is a URL, extract the domain as a label.
    If it contains a mix of text and URLs, remove the URL portions."""
    if not raw:
        return raw
    # If the whole string is a URL, extract domain
    stripped = raw.strip()
    if _re.match(r'^https?://', stripped) and ' ' not in stripped:
        try:
            host = _urlparse(stripped).hostname or ""
            # Remove www. prefix
            if host.startswith("www."):
                host = host[4:]
            return host if host else raw
        except Exception:
            return raw
    # Remove inline URLs from mixed text
    cleaned = _re.sub(r'https?://\S+', '', raw).strip()
    # Collapse multiple spaces
    cleaned = _re.sub(r'  +', ' ', cleaned)
    return cleaned if cleaned else raw


def _str(val) -> str:
    """Coerce a value to str — handles lists returned by Claude API."""
    if isinstance(val, list):
        return val[0] if val else ""
    return val if isinstance(val, str) else str(val) if val is not None else ""


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


# ── Design system: Taegukgi palette ──────────────────────────────────────
# Blue is the default accent; red is reserved for alert contexts. Monospace
# ('Courier New') is reserved for machine-measured values — prices, counts,
# percentages, dates in data displays. Human prose stays Georgia/Arial.
TAEGUK_RED = "#CD2E3A"
TAEGUK_BLUE = "#0047A0"
NAVY = "#072B52"          # masthead / footer ground
NAVY_DATA = "#051F3D"     # market strip ground
NAVY_PANEL = "#0A1E38"    # KCNA dark panel
INK = "#1A222E"
RED_ON_NAVY = "#E8697A"
BLUE_ON_NAVY = "#8FB6E8"
UP_GREEN = "#2E7D4F"      # semantic up (white ground)
DOWN_RED = "#A93226"      # semantic down (white ground)
MONO = "'Courier New',Courier,monospace"

_TAEGUK_RULE = (f'<div style="height:3px;background:{TAEGUK_RED};font-size:0;line-height:0;">&nbsp;</div>'
                f'<div style="height:3px;background:{TAEGUK_BLUE};font-size:0;line-height:0;">&nbsp;</div>')


def _color_bar(css_class: str) -> str:
    colors = {
        "cb-navy": TAEGUK_BLUE, "cb-red": TAEGUK_RED, "cb-lt": TAEGUK_BLUE,
        "cb-mid": "#7F8C8D", "cb-nkch": TAEGUK_RED, "cb-tech": TAEGUK_BLUE,
        "cb-biz": TAEGUK_BLUE,
    }
    return colors.get(css_class, TAEGUK_BLUE)


def _social_badge(badge_class: str) -> str:
    colors = {"sb-p": TAEGUK_BLUE, "sb-r": TAEGUK_RED, "sb-s": TAEGUK_BLUE}
    return colors.get(badge_class, TAEGUK_BLUE)


def _arrow(val) -> str:
    """Market strip delta — rendered on the navy data ground."""
    try:
        val = float(val)
    except (TypeError, ValueError):
        return '<span style="color:#7B90AC;">—</span>'
    if val > 0:
        return f'<span style="color:#69C88E;">&#9650; +{val:.1f}%</span>'
    elif val < 0:
        return f'<span style="color:#E8697A;">&#9660; {val:.1f}%</span>'
    return '<span style="color:#7B90AC;">— flat</span>'




def _cds_arrow(val) -> str:
    """CDS arrow — up (wider spread) is red/risk, down (tighter) is green.
    Rendered on the navy data ground."""
    try:
        val = float(val)
    except (TypeError, ValueError):
        return '<span style="color:#7B90AC;">—</span>'
    if val > 0:
        return f'<span style="color:#E8697A;">&#9650; +{val:.1f} bps</span>'
    elif val < 0:
        return f'<span style="color:#69C88E;">&#9660; {val:.1f} bps</span>'
    return '<span style="color:#7B90AC;">— flat</span>'


def _link_or_text(text: str, url: str, style: str = "color:#1B2A4A;text-decoration:underline;") -> str:
    """Render as <a> only if url is a real link, otherwise plain text.
    NOTE: `text` should already be HTML-escaped by the caller via _esc()."""
    if url and url != "#" and url.startswith("http"):
        return f'<a href="{_esc(url)}" style="{style}">{text}</a>'
    return text


# ── Section padding helper (responsive via class) ────────────────────────
_SEC = 'style="padding:20px 32px;border-bottom:1px solid #EBEBEB;" class="sec"'
_SEC_ALERT = f'style="padding:20px 32px;border-top:3px solid {TAEGUK_RED};border-bottom:1px solid #EBEBEB;" class="sec"'
_H2 = lambda color: f'style="margin:0 0 8px 0;font-size:11px;color:{color};text-transform:uppercase;letter-spacing:1.5px;font-family:Arial,sans-serif;font-weight:600;"'


def _sec_label(label: str, color: str = TAEGUK_BLUE) -> str:
    return (f'<div style="font-size:11px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:1.8px;color:{color};font-family:Arial,sans-serif;'
            f'margin-bottom:14px;padding-bottom:6px;border-bottom:2px solid {color};">'
            f'{label}</div>')


def _item_block(cat: str, src: str, headline: str, body: str, url: str,
                 bar_color: str = TAEGUK_BLUE, extra_html: str = "") -> str:
    """Render a standard border-left news item."""
    return f"""
            <div style="margin-bottom:10px;padding-left:12px;border-left:3px solid {bar_color};">
              <div style="font-size:11px;color:#888;text-transform:uppercase;">{cat} &middot; {src}</div>
              <div style="font-size:13px;font-weight:600;color:{INK};">
                {_link_or_text(headline, url)}
              </div>
              <div style="font-size:12px;line-height:1.4;color:#555;">{body}</div>
              {extra_html}
            </div>"""


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
    words += len(str(kcna.get("bottom_line", "")).split())
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
    <a name="top"></a>
    {_TAEGUK_RULE}
    <div bgcolor="{NAVY}" style="background-color:{NAVY};color:#fff;padding:22px 32px 18px;" class="sec">
      <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
        <td style="vertical-align:top;">
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:3px;color:rgba(255,255,255,0.65);font-family:Arial,sans-serif;margin-bottom:7px;">CSIS Korea Chair</div>
          <h1 style="margin:0;font-size:24px;font-weight:700;font-family:Georgia,'Times New Roman',serif;color:#fff;letter-spacing:0.3px;">
            Korea Daily Brief
          </h1>
          <div style="margin-top:7px;font-size:14px;font-weight:400;color:rgba(255,255,255,0.88);letter-spacing:0.3px;font-family:Georgia,serif;">{_esc(date_str)}</div>
        </td>
        <td style="vertical-align:top;text-align:right;">
          <div style="font-family:{MONO};font-size:11px;color:rgba(255,255,255,0.55);white-space:nowrap;">{gen_time}<br>{word_count:,} words &middot; {read_min} min read</div>
        </td>
      </tr></table>
      {"<div style='margin-top:14px;padding-top:12px;border-top:1px solid rgba(205,46,58,0.45);font-size:13px;color:rgba(255,255,255,0.92);font-family:Georgia,serif;line-height:1.55;'><strong style='color:" + RED_ON_NAVY + ";font-size:11px;letter-spacing:1.5px;font-family:Arial,sans-serif;'>RE:</strong>&nbsp; " + re_line + "</div>" if re_line else ""}
    </div>
    """)

    # ── 1b. Forward CTA — removed (placeholder for future subscribe link) ──

    # ── 2. Market Indicators ───────────────────────────────────────────────
    markets = digest.get("market_indicators") or {}
    if markets:
        kospi = markets.get("kospi") or {}
        brent = markets.get("brent") or {}
        krw = markets.get("usd_krw") or {}
        bok_rate = markets.get("bok_rate") or {}
        korea_cds = markets.get("korea_cds") or {}
        gdp = markets.get("gdp_estimate") or {}
        # Top row: KOSPI, Brent, USD/KRW
        sections.append(f"""
        <a name="markets"></a>
        <table class="mkt-table" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{NAVY_DATA};color:#fff;border-bottom:1px solid rgba(255,255,255,0.10);">
          <tr>
            <td width="33%" align="center" style="padding:11px 8px 13px;">
              <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#7B90AC;">KOSPI</div>
              <div style="font-family:{MONO};font-size:16px;font-weight:700;margin-top:3px;">{_esc(str(kospi.get("value", "—")))}</div>
              <div style="font-family:{MONO};font-size:11px;margin-top:2px;">{_arrow(kospi.get("change_pct", 0))}</div>
              {"<div style='font-family:" + MONO + ";font-size:10px;color:#7B90AC;margin-top:2px;'>as of " + _esc(kospi.get("as_of", "")) + "</div>" if kospi.get("as_of") else ""}
            </td>
            <td width="34%" align="center" style="padding:11px 8px 13px;border-left:1px solid rgba(255,255,255,0.10);border-right:1px solid rgba(255,255,255,0.10);">
              <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#7B90AC;">Brent Crude</div>
              <div style="font-family:{MONO};font-size:16px;font-weight:700;margin-top:3px;">${_esc(str(brent.get("value", "—")))}</div>
              <div style="font-family:{MONO};font-size:11px;margin-top:2px;">{_arrow(brent.get("change_pct", 0))}</div>
              {"<div style='font-family:" + MONO + ";font-size:10px;color:#7B90AC;margin-top:2px;'>as of " + _esc(brent.get("as_of", "")) + "</div>" if brent.get("as_of") else ""}
            </td>
            <td width="33%" align="center" style="padding:11px 8px 13px;">
              <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#7B90AC;">USD/KRW</div>
              <div style="font-family:{MONO};font-size:16px;font-weight:700;margin-top:3px;">{_esc(str(krw.get("value", "—")))}</div>
              <div style="font-family:{MONO};font-size:11px;margin-top:2px;">{_arrow(krw.get("change_pct", 0))}</div>
              {"<div style='font-family:" + MONO + ";font-size:10px;color:#7B90AC;margin-top:2px;'>as of " + _esc(krw.get("as_of", "")) + "</div>" if krw.get("as_of") else ""}
            </td>
          </tr>
        </table>
        <table class="mkt-table" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#04182F;color:#fff;border-bottom:1px solid rgba(255,255,255,0.08);">
          <tr>
            <td width="33%" align="center" style="padding:9px 8px 11px;">
              <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#7B90AC;">BOK Rate</div>
              <div style="font-family:{MONO};font-size:14px;font-weight:700;color:#D5DDE8;margin-top:2px;">{_esc(str(bok_rate.get("value", "—")))}</div>
              <div style="font-size:10px;color:#7B90AC;">{_esc(str(bok_rate.get("last_change", "")))}</div>
            </td>
            <td width="34%" align="center" style="padding:9px 8px 11px;border-left:1px solid rgba(255,255,255,0.10);border-right:1px solid rgba(255,255,255,0.10);">
              <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#7B90AC;">Korea 5Y CDS</div>
              <div style="font-family:{MONO};font-size:14px;font-weight:700;color:#D5DDE8;margin-top:2px;">{_esc(str(korea_cds.get("value", "—")))} bps</div>
              <div style="font-family:{MONO};font-size:10px;">{_cds_arrow(korea_cds.get("change_bps", 0))}</div>
              {"<div style='font-family:" + MONO + ";font-size:10px;color:#7B90AC;margin-top:2px;'>as of " + _esc(korea_cds.get("as_of", "")) + "</div>" if korea_cds.get("as_of") else ""}
            </td>
            <td width="33%" align="center" style="padding:9px 8px 11px;">
              <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#7B90AC;">GDP Est.</div>
              <div style="font-family:{MONO};font-size:14px;font-weight:700;color:#D5DDE8;margin-top:2px;">{_esc(str(gdp.get("value", "—")))}</div>
              <div style="font-size:10px;color:#7B90AC;">{_esc(str(gdp.get("source", "BOK")))}{" · " + _esc(str(gdp.get("period", ""))) if gdp.get("period") else ""}</div>
            </td>
          </tr>
        </table>
        """)

        # Third row: BOK ECOS indicators (only if data available)
        bok_ecos = markets.get("bok_ecos") or {}
        if bok_ecos:
            cpi_yoy = _esc(str(bok_ecos.get("cpi_yoy", "—")))
            unemployment = _esc(str(bok_ecos.get("unemployment", "—")))
            trade_balance = _esc(str(bok_ecos.get("trade_balance", "—")))
            consumer_conf = _esc(str(bok_ecos.get("consumer_confidence", "—")))
            # Build cells — only show indicators that have data
            ecos_cells = []
            if bok_ecos.get("cpi_yoy"):
                ecos_cells.append(("CPI (YoY)", cpi_yoy))
            if bok_ecos.get("unemployment"):
                ecos_cells.append(("Unemployment", unemployment))
            if bok_ecos.get("trade_balance"):
                ecos_cells.append(("Trade Bal.", trade_balance))
            if bok_ecos.get("consumer_confidence"):
                ecos_cells.append(("Consumer Conf.", consumer_conf))

            if ecos_cells:
                # Distribute widths evenly
                cell_width = f"{100 // len(ecos_cells)}%"
                cells_html = ""
                for i, (label, value) in enumerate(ecos_cells):
                    border = ' border-left:1px solid rgba(255,255,255,0.1);' if i > 0 else ''
                    cells_html += f"""
            <td width="{cell_width}" align="center" style="padding:8px 8px 10px;{border}">
              <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#7B90AC;">{label}</div>
              <div style="font-family:{MONO};font-size:14px;font-weight:700;color:#D5DDE8;margin-top:2px;">{value}</div>
              <div style="font-size:10px;color:#7B90AC;">BOK ECOS</div>
            </td>"""

                sections.append(f"""
        <table class="mkt-table" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#03142A;color:#fff;border-bottom:1px solid rgba(255,255,255,0.08);">
          <tr>{cells_html}
          </tr>
        </table>
        """)

    # ── 3. Morning Memo (top 3 at a glance) ─────────────────────────────────
    memo_items = digest.get("morning_memo") or []
    if memo_items:
        memo_html = ""
        for i, mi in enumerate(memo_items[:3]):
            memo_text = _esc(mi) if isinstance(mi, str) else _esc(mi.get("text", "") if isinstance(mi, dict) else str(mi or ""))
            num = i + 1
            memo_html += f"""
            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:10px;">
              <tr>
                <td width="28" style="vertical-align:top;padding-top:2px;">
                  <div style="width:24px;height:24px;border-radius:50%;background:{TAEGUK_BLUE};color:#FFFFFF;text-align:center;line-height:24px;font-size:12px;font-weight:700;font-family:Georgia,serif;">{num}</div>
                </td>
                <td style="padding-left:10px;vertical-align:top;">
                  <div style="font-size:14px;line-height:1.6;color:#2C3E50;font-family:Georgia,serif;">{memo_text}</div>
                </td>
              </tr>
            </table>"""
        sections.append(f"""
        <div style="padding:20px 32px;border-bottom:1px solid #EAEAEA;background:#FAFBFC;" class="sec">
          <a name="memo"></a>
          {_sec_label("Today at a Glance")}
          {memo_html}
        </div>
        """)

    # ── 4. Top Stories ────────────────────────────────────────────────────
    top_stories = digest.get("top_stories") or []
    if top_stories:
        stories_html = ""
        for story in top_stories:
            cat = _esc(_str(story.get("category_tag", story.get("category", ""))))
            headline = _esc(story.get("headline", ""))
            body = _esc(story.get("body", ""))
            so_what = _esc(story.get("so_what", ""))
            pattern = _esc(story.get("pattern_note", ""))
            src_line = _esc(_clean_src(story.get("src_line", story.get("source", ""))))
            url = story.get("url", "")
            cat_badge = f'<span style="display:inline-block;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:{TAEGUK_BLUE};font-weight:600;margin-bottom:6px;">{cat}</span>' if cat else ""
            stories_html += f"""
            <div class="story-card" style="margin-bottom:14px;padding:14px 16px;background:#fff;border-radius:3px;border-left:4px solid {TAEGUK_BLUE};box-shadow:0 1px 3px rgba(0,0,0,0.06);">
              {cat_badge}
              <h3 style="margin:0 0 8px 0;font-size:16px;color:{INK};font-family:Georgia,serif;line-height:1.4;">
                {_link_or_text(headline, url, style="color:" + INK + ";text-decoration:none;")}
              </h3>
              <p style="margin:0 0 8px 0;font-size:13px;line-height:1.6;color:#444;">{body}</p>
              {"<p style='margin:0 0 6px 0;font-size:12px;line-height:1.5;color:#4A5260;border-left:2px solid " + TAEGUK_BLUE + ";padding-left:10px;'><strong style='color:" + TAEGUK_BLUE + ";text-transform:uppercase;font-size:11px;letter-spacing:1px;'>So what</strong> — " + so_what + "</p>" if so_what else ""}
              {"<p style='margin:0 0 6px 0;font-size:12px;line-height:1.5;color:#4A5260;'><strong>Pattern:</strong> " + pattern + "</p>" if pattern else ""}
              <div style="font-size:10px;color:#AAA;margin-top:6px;">{src_line}</div>
            </div>"""
        sections.append(f"""
        <div {_SEC}>
          <a name="top-stories"></a>{_sec_label("Top Stories")}
          {stories_html}
        </div>
        """)

    # ── 4b. Overnight Flash (high-priority overnight items) ────────────
    overnight = digest.get("overnight_items") or []
    if overnight:
        flash_html = ""
        for item in overnight:
            cat_raw = _str(item.get("category", ""))
            cat = _esc(cat_raw)
            headline = _esc(item.get("headline", ""))
            body = _esc(item.get("body_text", ""))
            src = _esc(_clean_src(item.get("source", "")))
            url = item.get("url", "")
            flash_html += f"""
            <div style="margin-bottom:10px;padding-left:12px;border-left:3px solid {TAEGUK_RED};">
              <div style="font-size:11px;color:{TAEGUK_RED};text-transform:uppercase;font-weight:600;">{cat} &middot; {src}</div>
              <div style="font-size:13px;font-weight:600;color:{INK};">
                {_link_or_text(headline, url)}
              </div>
              <div style="font-size:12px;line-height:1.4;color:#555;">{body}</div>
            </div>"""
        sections.append(f"""
        <div {_SEC_ALERT}>
          <a name="overnight"></a>{_sec_label("&#9889; Overnight Flash", color=TAEGUK_RED)}
          {flash_html}
        </div>
        """)

    # (watch_today section removed — field was never in digest prompt schema)

    # ── 6. Key Stat of the Day ───────────────────────────────────────────
    key_stat = digest.get("key_stat") or {}
    if key_stat and key_stat.get("number") is not None and key_stat.get("number") != "":
        sections.append(f"""
        <a name="key-stat"></a>
        <div bgcolor="{NAVY}" style="padding:18px 32px;background-color:{NAVY};color:#fff;border-bottom:1px solid #EAEAEA;text-align:center;" class="sec">
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:2.5px;color:{BLUE_ON_NAVY};margin-bottom:7px;font-weight:600;">Stat of the Day</div>
          <div class="key-stat-num" style="font-family:{MONO};font-size:32px;font-weight:700;color:#fff;">{_esc(str(key_stat.get("number", "")))}</div>
          <div style="font-size:12px;color:rgba(255,255,255,0.85);margin-top:5px;font-family:Georgia,serif;">{_esc(key_stat.get("label", ""))}</div>
          <div style="font-size:11px;color:rgba(255,255,255,0.6);margin-top:6px;font-style:italic;max-width:480px;margin-left:auto;margin-right:auto;line-height:1.5;">{_esc(key_stat.get("context", ""))}</div>
          {"<div style='font-family:" + MONO + ";font-size:10px;color:rgba(255,255,255,0.4);margin-top:6px;'>Source: " + _esc(key_stat.get("source", "")) + "</div>" if key_stat.get("source") else ""}
        </div>
        """)

    # ── 7. DPRK Official Statements ───────────────────────────────────────
    kcna = digest.get("kcna_delta") or {}
    if kcna and any(kcna.values()):
        bottom_line = _esc(kcna.get("bottom_line", ""))
        watch = kcna.get("watch_flag", False)
        silence = kcna.get("silence_today", False)

        kim_today = "Yes" if kcna.get("kim_appearance_today") else "No"
        kim_activity = _esc(kcna.get("kim_activity", "")) if kcna.get("kim_activity") else ""
        days_absent = kcna.get("days_since_last_appearance")

        kim_line = ""
        kim_icon = ""
        if kim_today == "Yes":
            kim_icon = '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#27AE60;margin-right:6px;vertical-align:middle;"></span>'
            kim_line = "Public appearance"
            if kim_activity:
                kim_line += f" — {kim_activity}"
        else:
            kim_icon = '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#C0392B;margin-right:6px;vertical-align:middle;"></span>'
            kim_line = "No appearance"
            if days_absent:
                kim_line += f" ({days_absent}d since last)"

        # Kim Jong Un direct quotes — featured when he said something
        key_quotes = kcna.get("key_quotes") or []
        quotes_html = ""
        for q in key_quotes[:2]:
            qt = _esc(q.get("quote", ""))
            speaker = _esc(q.get("speaker", "Kim Jong Un"))
            src_art = _esc(q.get("source_article", ""))
            if not qt:
                continue
            speaker_line = f"<strong style='color:{RED_ON_NAVY};'>{speaker}</strong>"
            src_line = f" <span style='color:#7B90AC;'>— {src_art}</span>" if src_art else ""
            quotes_html += f"""<div style='margin-bottom:10px;padding:10px 14px;background:rgba(255,255,255,0.04);border-radius:4px;border-left:3px solid {TAEGUK_RED};'>
              <div style='font-size:13px;color:#E8E8E8;font-style:italic;line-height:1.5;'>&ldquo;{qt}&rdquo;</div>
              <div style='font-size:10px;margin-top:4px;'>{speaker_line}{src_line}</div>
            </div>"""

        # Top 3 KCNA articles — Kim-related items ranked first by the prompt
        top_articles = kcna.get("top_articles") or []
        articles_html = ""
        if top_articles:
            art_items = ""
            for i, art in enumerate(top_articles[:3], 1):
                a_headline = _esc(art.get("headline", ""))
                if not a_headline:
                    continue
                a_summary = _esc(art.get("summary", ""))
                a_src = _esc(art.get("source", ""))
                a_url = art.get("url", "")
                kim_badge = (f' <span style="font-family:{MONO};font-size:10px;font-weight:700;'
                             f'color:{RED_ON_NAVY};letter-spacing:0.5px;">KIM</span>'
                             if art.get("kim_related") else "")
                src_tag = f" <span style='color:#7B90AC;'>— {a_src}</span>" if a_src else ""
                art_items += f"""<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:8px;"><tr>
                  <td width="24" style="vertical-align:top;font-family:{MONO};font-size:13px;font-weight:700;color:{BLUE_ON_NAVY};padding-top:1px;">{i}.</td>
                  <td style="vertical-align:top;">
                    <div style="font-size:13px;font-weight:600;color:#E8E8E8;line-height:1.4;">{_link_or_text(a_headline, a_url, style="color:#E8E8E8;text-decoration:underline;")}{kim_badge}</div>
                    {"<div style='font-size:12px;color:#A8B6C8;line-height:1.5;margin-top:2px;'>" + a_summary + src_tag + "</div>" if a_summary else ""}
                  </td>
                </tr></table>"""
            if art_items:
                articles_html = f"""<div style="margin-top:4px;">
                  <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#7B90AC;margin-bottom:8px;">Top KCNA Articles</div>
                  {art_items}
                </div>"""

        sections.append(f"""
        <a name="kcna"></a>
        <div style="padding:0;border-bottom:1px solid #333;" class="sec kcna-dark">
          <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{NAVY_PANEL};">
            <tr>
              <td style="padding:12px 32px;">
                <span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1.8px;color:{BLUE_ON_NAVY};font-family:Arial,sans-serif;border-bottom:2px solid {TAEGUK_RED};padding-bottom:5px;display:inline-block;">Pyongyang Watch &middot; KCNA</span>
              </td>
            </tr>
          </table>
          <div style="padding:16px 32px;background:{NAVY_PANEL};color:#E0E0E0;">
            {"<div style='margin-bottom:12px;padding:8px 14px;background:" + TAEGUK_RED + ";color:#fff;border-radius:4px;font-size:12px;font-weight:600;'>&#9888; Complete KCNA silence today</div>" if silence else ""}
            {"<div style='margin-bottom:12px;padding:8px 14px;background:" + TAEGUK_RED + ";color:#fff;border-radius:4px;font-size:12px;font-weight:600;'>&#9888; WATCH FLAG — Unusual rhetoric or activity detected</div>" if watch and not silence else ""}
            <div style="padding:8px 12px;background:rgba(255,255,255,0.04);border-radius:4px;margin-bottom:12px;">
              <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#7B90AC;margin-bottom:4px;">Kim Jong Un</div>
              <div style="font-size:13px;color:#E0E0E0;font-weight:600;">{kim_icon}{kim_line}</div>
            </div>
            {quotes_html}
            {articles_html}
            {"<div style='margin-top:14px;padding:10px 14px;background:rgba(255,255,255,0.06);border-radius:4px;border-left:3px solid " + BLUE_ON_NAVY + ";font-size:13px;line-height:1.6;color:#E0E0E0;font-family:Georgia,serif;'><strong style='color:" + BLUE_ON_NAVY + ";'>Bottom line:</strong> " + bottom_line + "</div>" if bottom_line else ""}
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
                    src_link = f'<div style="margin-top:6px;font-size:11px;color:#888;">→ <a href="{_esc(source_url)}" style="color:#888;text-decoration:none;">{_esc(s_label)} ↗</a></div>'
                elif source_label:
                    src_link = f'<div style="margin-top:6px;font-size:11px;color:#888;">→ {_esc(source_label)}</div>'
                row_cards += f"""
                <td style="width:50%;padding:8px;vertical-align:top;">
                  <div style="background:#F5F7FA;border-radius:4px;padding:14px;min-height:100px;">
                    <div style="margin-bottom:6px;">{ministry_header}</div>
                    <div style="font-size:14px;font-weight:700;color:{INK};line-height:1.3;margin-bottom:6px;">{_esc(action)}</div>
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
                      <div class="cal-date" style="font-family:{MONO};font-size:17px;font-weight:700;color:{TAEGUK_BLUE};line-height:1.2;">{cal_day}</div>
                    </td>
                    <td style="padding:10px 0;vertical-align:top;">
                      <div style="font-size:13px;font-weight:600;color:#1B2A4A;margin-bottom:2px;">{cal_headline}</div>
                      <div style="font-size:12px;line-height:1.4;color:#555;">{cal_detail}</div>
                    </td>
                  </tr>
                </table>"""
            cal_html = f"""
            <div style="margin-top:20px;">
              <div style="padding:8px 0;border-bottom:1px solid {TAEGUK_BLUE};margin-bottom:4px;">
                <span style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:{TAEGUK_BLUE};">Upcoming</span>
              </div>
              {cal_items}
            </div>"""

        # Personnel changes (inline in ROK Gov)
        pers_html = ""
        if rok_personnel:
            action_colors = {"appointed": UP_GREEN, "nominated": TAEGUK_BLUE, "resigned": TAEGUK_RED, "dismissed": TAEGUK_RED, "confirmed": UP_GREEN}
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
          <a name="rok-gov"></a>{_sec_label("ROK Government")}
          <div style="font-size:10px;color:#888;font-family:Arial,sans-serif;margin-top:-10px;margin-bottom:10px;">President + Ministries &middot; {rok_date}</div>
          <div style="padding-top:4px;">
            {gov_grid_html}
            {pers_html}
            {asm_html}
            {cal_html}
          </div>
        </div>
        """)

    # ── 9b. Election Tracker ─────────────────────────────────────────────
    election = digest.get("election_tracker") or {}
    if election and election.get("election_name"):
        e_name = _esc(election.get("election_name", ""))
        e_date = _esc(election.get("election_date", ""))
        e_days = election.get("days_until", 0)
        e_summary = _esc(election.get("summary", ""))
        key_races = election.get("key_races") or []

        races_html = ""
        if key_races:
            race_rows = ""
            for r in key_races[:6]:
                region = _esc(r.get("region", ""))
                inc = _esc(r.get("incumbent_party", ""))
                chal = _esc(r.get("challenger_party", ""))
                status = _esc(r.get("status", ""))
                note = _esc(r.get("note", ""))
                inc_color = TAEGUK_BLUE if "Democratic" in inc or "DP" in inc else TAEGUK_RED
                chal_color = TAEGUK_RED if "People Power" in chal or "PPP" in chal else TAEGUK_BLUE
                race_rows += f"""
                <tr style="border-bottom:1px solid #E8E8E8;">
                  <td style="padding:6px 8px 6px 0;font-size:12px;font-weight:600;color:{INK};width:30%;">{region}</td>
                  <td style="padding:6px 4px;font-size:11px;vertical-align:middle;">
                    <span style="color:{inc_color};font-weight:600;">{inc}</span> vs <span style="color:{chal_color};font-weight:600;">{chal}</span>
                  </td>
                  <td style="padding:6px 4px;font-size:11px;font-weight:600;color:{INK};text-align:center;">{status}</td>
                  <td style="padding:6px 0 6px 4px;font-size:10px;color:#888;">{note}</td>
                </tr>"""
            races_html = f"""
            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:10px;border-top:1px solid #E8E8E8;">
              <tr style="border-bottom:1px solid #E8E8E8;">
                <td style="padding:4px 8px 4px 0;font-size:10px;color:#888;text-transform:uppercase;">Race</td>
                <td style="padding:4px 4px;font-size:10px;color:#888;text-transform:uppercase;">Parties</td>
                <td style="padding:4px 4px;font-size:10px;color:#888;text-transform:uppercase;text-align:center;">Status</td>
                <td style="padding:4px 0 4px 4px;font-size:10px;color:#888;text-transform:uppercase;">Note</td>
              </tr>
              {race_rows}
            </table>"""

        urgency_color = TAEGUK_RED if e_days <= 14 else TAEGUK_BLUE
        sections.append(f"""
        <div {_SEC}>
          <a name="election"></a>{_sec_label("Election Tracker")}
          <div style="margin-top:6px;">
            <span style="font-size:18px;font-weight:700;color:{INK};">{e_name}</span>
            <span style="display:inline-block;padding:2px 10px;border-radius:3px;font-family:{MONO};font-size:11px;font-weight:700;color:#fff;background:{urgency_color};margin-left:10px;vertical-align:middle;">{e_days} DAYS</span>
          </div>
          <div style="font-size:11px;color:#888;margin-top:4px;">{e_date}</div>
          <div style="font-size:13px;line-height:1.6;color:#444;margin-top:8px;">{e_summary}</div>
          {races_html}
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

        # ── Trade dashboard strip — the section's three key numbers in one
        # row (tariff rate / investment fulfilled / next trigger), followed
        # by compact detail tables. Replaces the old stacked cards.
        dash_cells = []
        sector_table = ""
        s122_line = ""
        meta_line = ""
        deals_breakdown = ""

        if tariff_tracker and tariff_tracker.get("headline_rate"):
            h_rate = _esc(str(tariff_tracker.get("headline_rate", "")))
            h_status = tariff_tracker.get("headline_status", "ACTIVE")
            # Escalation labels removed from the product — normalize legacy data
            if h_status == "ESCALATION":
                h_status = "ACTIVE"
            h_note = _esc(str(tariff_tracker.get("headline_note", "")))
            s122 = tariff_tracker.get("section_122_surcharge")
            last_change = _esc(str(tariff_tracker.get("last_change", "")))

            _tariff_status_colors = {"ACTIVE": TAEGUK_RED, "PAUSED": "#7F8C8D", "NEGOTIATING": TAEGUK_BLUE, "REDUCED": UP_GREEN}
            h_color = _tariff_status_colors.get(h_status, TAEGUK_RED)
            dash_cells.append((
                "US Tariff on ROK",
                f'<span style="font-family:{MONO};font-size:24px;font-weight:700;color:{TAEGUK_RED};">{h_rate}</span>',
                f'<span style="font-family:{MONO};font-size:11px;font-weight:700;color:{h_color};">{_esc(h_status)}</span>',
            ))

            # Sector rate rows — compact table under the strip
            sector_rows = ""
            for sr in (tariff_tracker.get("sector_rates") or []):
                sr_sector = _esc(sr.get("sector", ""))
                sr_rate = _esc(str(sr.get("rate", "")))
                sr_auth = _esc(sr.get("authority", ""))
                sr_st = sr.get("status", "ACTIVE")
                if sr_st == "ESCALATION":
                    sr_st = "ACTIVE"
                sr_color = _tariff_status_colors.get(sr_st, TAEGUK_RED)
                sr_note = _esc(sr.get("note", ""))
                sector_rows += f"""
                <tr style="border-bottom:1px solid #EDEFF2;">
                  <td style="padding:4px 6px 4px 0;font-size:11px;font-weight:600;color:{INK};">{sr_sector}</td>
                  <td style="padding:4px 6px;font-family:{MONO};font-size:13px;font-weight:700;color:{sr_color};text-align:center;white-space:nowrap;">{sr_rate}</td>
                  <td style="padding:4px 6px;font-size:10px;color:#888;text-transform:uppercase;white-space:nowrap;">{sr_auth}</td>
                  <td style="padding:4px 0 4px 6px;font-size:11px;color:#666;">{sr_note}</td>
                </tr>"""
            if sector_rows.strip():
                sector_table = f"""
                <div style="margin-top:12px;">
                  <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#78828F;font-weight:600;margin-bottom:4px;">Sector Rates</div>
                  <table class="tariff-sector" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top:1px solid #EDEFF2;">{sector_rows}
                  </table>
                </div>"""

            if s122:
                s122_line = f'<div style="margin-top:8px;font-size:11px;color:{TAEGUK_RED};font-weight:600;">+ Section 122 global surcharge: {_esc(str(s122))}</div>'
            note_bits = " &middot; ".join(b for b in (h_note, last_change) if b)
            if note_bits:
                meta_line = f'<div style="margin-top:4px;font-size:11px;color:#78828F;line-height:1.5;">{note_bits}</div>'

        if investment_pkg and investment_pkg.get("total_pledged"):
            pct = investment_pkg.get("pct_fulfilled", 0)
            announced = _esc(str(investment_pkg.get("announced_to_date", "")))
            pledged = _esc(str(investment_pkg.get("total_pledged", "")))
            dash_cells.append((
                "Investment Fulfilled",
                f'<span style="font-family:{MONO};font-size:24px;font-weight:700;color:{TAEGUK_BLUE};">{pct}%</span>',
                f'{announced} of {pledged}',
            ))

            # Deal breakdown — kept as a compact table
            known_deals = investment_pkg.get("known_deals") or []
            if known_deals:
                deal_rows = ""
                for kd in known_deals:
                    co = _esc(kd.get("company", ""))
                    val = _esc(kd.get("value", ""))
                    sect = _esc(kd.get("sector", ""))
                    deal_rows += f"""
                    <tr style="border-bottom:1px solid #E8EDF3;">
                      <td style="padding:4px 6px 4px 0;font-size:11px;font-weight:600;color:{INK};">{co}</td>
                      <td style="padding:4px 6px;font-family:{MONO};font-size:11px;font-weight:700;color:{UP_GREEN};text-align:right;white-space:nowrap;">{val}</td>
                      <td style="padding:4px 0 4px 6px;font-size:10px;color:#888;">{sect}</td>
                    </tr>"""
                deals_breakdown = f"""
                <div style="margin-top:12px;">
                  <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#78828F;font-weight:600;margin-bottom:4px;">Investment Deal Breakdown ({_esc(str(investment_pkg.get("latest_update", "")))})</div>
                  <table width="100%" cellpadding="0" cellspacing="0" border="0" class="deal-breakdown">
                    {deal_rows}
                  </table>
                </div>"""

        next_trigger = (_esc(str(tariff_tracker.get("next_trigger", "")))
                        if tariff_tracker and tariff_tracker.get("next_trigger") else "")
        if next_trigger:
            dash_cells.append((
                "Next Trigger",
                f'<span style="font-family:{MONO};font-size:12px;font-weight:700;color:{INK};line-height:1.45;display:inline-block;padding-top:5px;">{next_trigger}</span>',
                "",
            ))

        if dash_cells:
            cell_width = f"{100 // len(dash_cells)}%"
            cells_html = ""
            for i, (label, value, sub) in enumerate(dash_cells):
                border = "border-left:1px solid #E2E6EC;" if i else ""
                cells_html += f"""
                <td width="{cell_width}" align="center" style="padding:12px 10px 13px;vertical-align:top;{border}">
                  <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#78828F;margin-bottom:4px;">{label}</div>
                  <div>{value}</div>
                  {"<div style='font-size:11px;color:#78828F;margin-top:3px;'>" + sub + "</div>" if sub else ""}
                </td>"""
            header_html += f"""
            <table class="trade-dash" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#F5F7FA;border:1px solid #E2E6EC;border-radius:4px;">
              <tr>{cells_html}
              </tr>
            </table>
            {s122_line}
            {meta_line}
            {sector_table}
            {deals_breakdown}
            <div style="margin-bottom:16px;"></div>"""

        # US Trade Policy Tracker (Section 301, USTR, Commerce Dept)
        if trade_policy:
            status_colors = {"ACTIVE": TAEGUK_RED, "PENDING": "#7F8C8D", "RISK": TAEGUK_RED, "RESOLVED": UP_GREEN, "MONITOR": TAEGUK_BLUE}
            tracker_rows = ""
            for tr in trade_policy:
                item_text = _esc(tr.get("item", ""))
                detail_text = _esc(tr.get("detail", ""))
                agency = _esc(tr.get("agency", ""))
                item_url = tr.get("url", "")
                st = tr.get("status", "MONITOR")
                if st == "ESCALATION":
                    st = "ACTIVE"
                st_color = status_colors.get(st, "#7F8C8D")
                status_badge = f'<span style="font-family:{MONO};font-size:11px;font-weight:700;color:{st_color};letter-spacing:0.5px;">{_esc(st)}</span>'
                agency_tag = f'<span style="font-size:10px;color:#888;font-weight:400;"> · {agency}</span>' if agency else ""
                item_label = f'<a href="{_esc(item_url)}" style="color:{INK};text-decoration:underline;" target="_blank">{item_text}</a>' if item_url and item_url != "#" and item_url.startswith("http") else item_text
                tracker_rows += f"""
                <tr style="border-bottom:1px solid #F0F0F0;">
                  <td style="padding:6px 8px 6px 0;vertical-align:top;font-size:12px;font-weight:600;color:{INK};width:30%;">{item_label}{agency_tag}</td>
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
            "defense": TAEGUK_RED, "energy": TAEGUK_BLUE, "tech": TAEGUK_BLUE,
            "manufacturing": TAEGUK_BLUE, "trade": TAEGUK_BLUE, "tariff": TAEGUK_RED,
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
            bar_color = sector_colors.get(sector, TAEGUK_BLUE)
            wh_tracker = deal.get("wh_tracker", False)
            value_badge = f'<span style="display:inline-block;padding:1px 6px;border-radius:3px;font-family:{MONO};font-size:11px;font-weight:700;color:#fff;background:{UP_GREEN};margin-left:6px;">{value}</span>' if value else ""
            wh_badge = '<span style="display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600;color:' + INK + ';background:#E8E8E8;margin-left:6px;text-transform:uppercase;letter-spacing:0.5px;">WH Tracker</span>' if wh_tracker else ""
            # Source / parties attribution line on the right
            meta_right = f'<span style="font-size:11px;color:#888;">{parties}</span>' if parties else ""
            deals_html += f"""
            <div class="deal-card" style="margin-bottom:14px;padding:12px 0;border-top:1px solid #E8E8E8;">
              <div style="font-size:11px;color:#888;margin-bottom:2px;">{meta_right} {('&middot; ' + src) if src else ''}</div>
              <div style="font-size:15px;font-weight:700;color:{INK};line-height:1.3;margin-bottom:4px;">
                {_link_or_text(headline, url, style="color:" + INK + ";text-decoration:none;")}{value_badge}{wh_badge}
              </div>
              <div style="font-size:13px;line-height:1.5;color:#444;">{detail}</div>
              {"<div style='margin-top:6px;'>" + _link_or_text(_esc(src) + " ↗", url, style="font-size:11px;font-family:monospace;color:#888;text-decoration:none;") + "</div>" if src and url and url != "#" and url.startswith("http") else ""}
            </div>"""

        sections.append(f"""
        <div {_SEC}>
          <a name="trade"></a>{_sec_label("US-Korea Trade &amp; Investment")}
          {header_html}
          {deals_html}
        </div>
        """)

    # ── 11. Business & Economy ────────────────────────────────────────────
    biz_econ = digest.get("business_economy") or []
    if biz_econ:
        biz_html = ""
        biz_sector_colors = {
            "tech": TAEGUK_BLUE, "auto": TAEGUK_BLUE, "energy": TAEGUK_BLUE,
            "finance": TAEGUK_BLUE, "manufacturing": TAEGUK_BLUE,
            "real-estate": TAEGUK_BLUE, "macro": TAEGUK_RED,
        }
        for item in biz_econ:
            companies = item.get("companies") or []
            company_tags = ""
            if companies:
                company_tags = " ".join(
                    f'<span style="display:inline-block;padding:1px 5px;border-radius:3px;font-size:9px;background:#E8E8E8;color:#555;margin-right:3px;">{_esc(c)}</span>'
                    for c in companies[:3]
                )
                company_tags = f'<div style="margin-top:3px;">{company_tags}</div>'
            biz_html += _item_block(
                cat=_esc(_str(item.get("category", item.get("sector", "")))),
                src=_esc(_clean_src(item.get("source", ""))),
                headline=_esc(item.get("headline", "")),
                body=_esc(item.get("body_text", "")),
                url=item.get("url", ""),
                bar_color=biz_sector_colors.get(_str(item.get("sector", "")), TAEGUK_BLUE),
                extra_html=company_tags,
            )
        sections.append(f"""
        <div {_SEC}>
          <a name="business"></a>{_sec_label("Business &amp; Economy")}
          {biz_html}
        </div>
        """)

    # ── (Overnight Flash moved to position 4b — after Top Stories) ──────

    # ── 12. Northeast Asia Watch (Japan + China + Russia → Korea) ───────
    nea_items = digest.get("northeast_asia") or []
    if nea_items:
        # Alert-context categories get red; everything else defaults to blue
        _nea_red = {"japan-history", "territorial", "thaad-retaliation", "china-coercion",
                    "china-military", "russia-weapons", "russia-military", "russia-sanctions"}
        nea_cat_colors = {cat: TAEGUK_RED for cat in _nea_red}
        region_colors = {"Japan-Korea": "#5A6472", "China-Korea": "#5A6472", "Trilateral": "#5A6472", "Russia-Korea": "#5A6472"}
        nea_html = ""
        for item in nea_items:
            cat_raw = _str(item.get("category", ""))
            cat = _esc(cat_raw)
            headline = _esc(item.get("headline", ""))
            body = _esc(item.get("body_text", ""))
            src = _esc(_clean_src(item.get("source", "")))
            url = item.get("url", "")
            region = _str(item.get("region_tag", ""))
            is_reaction = item.get("is_reaction_source", False)
            bar_color = nea_cat_colors.get(cat_raw, TAEGUK_BLUE)
            reaction_badge = ""
            if is_reaction:
                badge_label = "PRC SOURCE" if "China" in region else "STATE MEDIA"
                reaction_badge = f'<span style="display:inline-block;padding:1px 5px;border-radius:3px;font-size:10px;font-weight:600;color:#fff;background:#888;margin-left:6px;">{badge_label}</span>'
            region_label = f'<span style="font-size:10px;padding:1px 5px;border-radius:3px;background:{region_colors.get(region, "#5A6472")};color:#fff;margin-right:6px;">{_esc(region)}</span>' if region else ""
            nea_html += f"""
            <div style="margin-bottom:10px;padding-left:12px;border-left:3px solid {bar_color};">
              <div style="font-size:11px;color:#888;text-transform:uppercase;">
                {region_label}{cat} &middot; {src}{reaction_badge}
              </div>
              <div style="font-size:13px;font-weight:600;color:{INK};">
                {_link_or_text(headline, url)}
              </div>
              <div style="font-size:12px;line-height:1.4;color:#555;">{body}</div>
            </div>"""
        sections.append(f"""
        <div {_SEC}>
          <a name="nea"></a>{_sec_label("Northeast Asia Watch")}
          {nea_html}
        </div>
        """)

    # ── 12c. Public Sentiment Tracker ──────────────────────────────────
    sentiment = digest.get("public_sentiment") or {}
    if sentiment and any(sentiment.values()):
        def _sentiment_cell(label, data, width="25%"):
            if not data or not data.get("value") or str(data.get("value")).strip().lower() in ("none", ""):
                return f"""
                <td width="{width}" align="center" style="padding:8px 6px;">
                  <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#888;">{label}</div>
                  <div style="font-family:{MONO};font-size:18px;font-weight:700;color:#888;">--</div>
                  <div style="font-size:10px;color:#999;">No recent data</div>
                </td>"""
            val = _esc(str(data.get("value", "")))
            trend = data.get("trend", "")
            source = _esc(str(data.get("source", "")))
            updated = _esc(str(data.get("last_updated", "")))
            trend_arrow = ""
            if trend == "up":
                trend_arrow = f'<span style="color:{UP_GREEN};">&#9650;</span>'
            elif trend == "down":
                trend_arrow = f'<span style="color:{DOWN_RED};">&#9660;</span>'
            elif trend == "stable":
                trend_arrow = '<span style="color:#888;">&#8594;</span>'
            return f"""
            <td width="{width}" align="center" style="padding:8px 6px;">
              <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#888;">{label}</div>
              <div style="font-family:{MONO};font-size:20px;font-weight:700;color:{INK};">{val} {trend_arrow}</div>
              <div style="font-size:10px;color:#999;">{source}</div>
              <div style="font-family:{MONO};font-size:10px;color:#999;">{updated}</div>
            </td>"""

        approval = sentiment.get("presidential_approval") or {}
        party_ruling = sentiment.get("party_ruling") or {}
        party_opp = sentiment.get("party_opposition") or {}
        party_ind = sentiment.get("party_independent") or {}
        discourse = sentiment.get("discourse_flag")

        discourse_html = ""
        if discourse:
            discourse_html = f"""
            <div class="sentiment-discourse" style="margin-top:8px;padding:6px 10px;background:#FBF0F1;border-radius:4px;border-left:3px solid {TAEGUK_RED};font-size:11px;color:#555;">
              <strong style="color:{TAEGUK_RED};">Discourse:</strong> {_esc(discourse)}
            </div>"""

        gallup_finding = sentiment.get("gallup_spotlight")
        spotlight_html = ""
        if gallup_finding:
            topic = _esc(str(gallup_finding.get("topic", "")))
            finding = _esc(str(gallup_finding.get("finding", "")))
            poll_date = _esc(str(gallup_finding.get("poll_date", "")))
            spotlight_html = f"""
            <div class="sentiment-spotlight" style="margin-top:10px;padding:8px 12px;background:#F0F5FB;border-radius:4px;border-left:3px solid {TAEGUK_BLUE};font-size:11px;color:#444;line-height:1.5;">
              <strong style="color:{TAEGUK_BLUE};">Gallup Korea Spotlight</strong>
              <span style="font-family:{MONO};font-size:10px;color:#999;margin-left:6px;">{poll_date}</span><br>
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
        <div {_SEC}>
          <a name="sentiment"></a>{_sec_label("Public Sentiment Tracker")}
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
            wire_html += _item_block(
                cat=_esc(_str(item.get("category", ""))),
                src=_esc(_clean_src(item.get("source", ""))),
                headline=_esc(item.get("headline", "")),
                body=_esc(item.get("body_text", "")),
                url=item.get("url", ""),
                bar_color=_color_bar(_str(item.get("color_bar_class", ""))),
            )
        sections.append(f"""
        <div {_SEC}>
          <a name="wire"></a>{_sec_label("The Wire")}
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
            source_link = f'<a href="{_esc(url)}" style="font-size:10px;color:{TAEGUK_BLUE};text-decoration:none;">Source &#8594;</a>' if url and url != "#" and url.startswith("http") else ""
            sa_html += f"""
            <div style="margin-bottom:12px;padding:12px;background:#F8F9FA;border-radius:6px;border-left:3px solid {badge_color};">
              <table cellpadding="0" cellspacing="0" border="0" style="margin-bottom:6px;">
                <tr>
                  <td width="36" style="vertical-align:middle;">
                    <div style="width:36px;height:36px;border-radius:50%;background:{badge_color};color:#fff;text-align:center;line-height:36px;font-size:13px;font-weight:700;">{initials}</div>
                  </td>
                  <td style="padding-left:8px;vertical-align:middle;">
                    <div style="font-size:12px;font-weight:600;color:{INK};">{who}</div>
                    <div style="font-size:10px;color:#888;">{handle}</div>
                  </td>
                </tr>
              </table>
              <p style="margin:0 0 6px 0;font-size:13px;line-height:1.5;color:#333;font-style:italic;">&ldquo;{quote}&rdquo;</p>
              {"<p style='margin:0;font-size:11px;color:" + TAEGUK_BLUE + ";'><strong>Analyst:</strong> " + note + "</p>" if note else ""}
              {source_link}
            </div>"""
        # Op-Eds
        for op in opeds:
            src = _esc(op.get("source", ""))
            title = _esc(op.get("headline", op.get("title", op.get("central_argument", ""))))
            summary = _esc(op.get("summary", ""))
            so_what = _esc(op.get("policy_so_what", ""))
            url = op.get("url", "")
            sa_html += f"""
            <div style="margin-bottom:12px;padding-left:12px;border-left:3px solid {TAEGUK_BLUE};">
              <div style="font-size:11px;color:#888;">{src}</div>
              <div style="font-size:13px;font-weight:600;color:{INK};">
                {_link_or_text(title, url)}
              </div>
              <div style="font-size:12px;line-height:1.4;color:#555;">{summary}</div>
              {"<div style='font-size:11px;color:" + TAEGUK_BLUE + ";margin-top:3px;'><strong>So what:</strong> " + so_what + "</div>" if so_what else ""}
            </div>"""
        # Academic
        for a in academic:
            src = _esc(a.get("source", ""))
            tier = _esc(a.get("journal_tier", ""))
            title = _esc(a.get("headline", a.get("title", "")))
            summary = _esc(a.get("summary", ""))
            implication = _esc(a.get("policy_implication", ""))
            url = a.get("url", "")
            read_link = f'<a href="{_esc(url)}" style="font-size:11px;color:{TAEGUK_BLUE};">Read &#8594;</a>' if url and url != "#" and url.startswith("http") else ""
            title_html = f'<div style="font-size:13px;font-weight:600;color:{INK};margin-bottom:4px;">{_link_or_text(title, url)}</div>' if title else ""
            sa_html += f"""
            <div style="margin-bottom:12px;padding-left:12px;border-left:3px solid {TAEGUK_BLUE};">
              <div style="font-size:11px;color:#888;">{src} &middot; {tier}</div>
              {title_html}
              <div style="font-size:12px;line-height:1.4;color:#555;">{summary}</div>
              {"<div style='font-size:11px;color:" + TAEGUK_BLUE + ";margin-top:3px;'><strong>Implication:</strong> " + implication + "</div>" if implication else ""}
              {read_link}
            </div>"""
        sections.append(f"""
        <div {_SEC}>
          <a name="analysis"></a>{_sec_label("Statements &amp; Analysis")}
          {sa_html}
        </div>
        """)

    # ── 14b. Satellite & Location Watch (moved to end — slow-moving section) ─
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
            <div style="margin-bottom:20px;padding:16px;border-left:3px solid {TAEGUK_BLUE};">
              <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:{TAEGUK_BLUE};font-weight:600;margin-bottom:6px;">{ir_source} · {ir_date} — {ir_label}</div>
              <div style="font-size:17px;font-weight:700;color:{INK};line-height:1.3;margin-bottom:8px;">{ir_headline}</div>
              <div style="font-size:13px;line-height:1.6;color:#444;">{ir_body}</div>
              {bp_ids_html}
              {source_links_html}
            </div>"""

        # BP Monitored Locations — 2-column card grid with status context
        _badge_styles = {
            "normal": ("#7F8C8D", "#F5F6F7", "MONITORING"),
            "activity": ("#7F8C8D", "#F5F6F7", "MONITORING"),
            "elevated": (TAEGUK_RED, "#FBF0F1", "ELEVATED"),
            "alert": (TAEGUK_RED, "#FBE9EA", "ALERT"),
        }
        elevated_count = sum(1 for l in locations if l.get("status", "normal") in ("elevated", "alert"))
        summary_html = ""
        if elevated_count:
            summary_html = f'<div style="font-size:11px;color:#888;margin-top:6px;margin-bottom:12px;">{elevated_count} of {len(locations)} sites at elevated or alert status</div>'
        else:
            summary_html = f'<div style="font-size:11px;color:#888;margin-top:6px;margin-bottom:12px;">{len(locations)} monitored sites</div>'

        loc_cards = ""
        for i in range(0, len(locations), 2):
            row_cards = ""
            for j in range(i, min(i + 2, len(locations))):
                loc = locations[j]
                name = _esc(loc.get("name", ""))
                status = loc.get("status", "normal")
                note = _esc(loc.get("note", ""))
                last_source_date = _esc(loc.get("last_source_date", ""))
                direction = loc.get("direction", "")
                b_color, b_bg, b_label = _badge_styles.get(status, ("#7F8C8D", "#F5F6F7", "MONITOR"))
                if direction == "up":
                    b_label += " &#9650;"
                elif direction == "down":
                    b_label += " &#9660;"
                status_badge = f'<span style="font-family:{MONO};font-size:11px;font-weight:700;color:{b_color};letter-spacing:0.5px;">{b_label}</span>'
                # Note rendering — style differently for carried-forward vs active
                note_html = ""
                if note and "no new reporting" in note.lower():
                    note_html = f'<div style="font-size:11px;line-height:1.4;color:#999;margin-top:4px;font-style:italic;">{note}</div>'
                elif note:
                    note_html = f'<div style="font-size:11px;line-height:1.4;color:#555;margin-top:4px;">{note}</div>'
                # Last report date — mono, machine-measured
                last_html = f'<div style="font-family:{MONO};font-size:11px;color:#999;margin-top:4px;">as of {last_source_date}</div>' if last_source_date and last_source_date != "unknown" else ""
                row_cards += f"""
                <td style="width:50%;padding:4px;vertical-align:top;">
                  <div style="background:{b_bg};border-radius:4px;padding:10px 12px;border-left:3px solid {b_color};">
                    <div style="font-size:12px;font-weight:700;color:{INK};margin-bottom:2px;">{name} &nbsp;{status_badge}</div>
                    {note_html}
                    {last_html}
                  </div>
                </td>"""
            if len(locations) - i == 1:
                row_cards += '<td style="width:50%;padding:4px;"></td>'
            loc_cards += f"<tr>{row_cards}</tr>"

        sections.append(f"""
        <div {_SEC}>
          <a name="satellite"></a>{_sec_label("Satellite &amp; Location Watch")}
          {summary_html}
          {img_report_html}
          <table width="100%" cellpadding="0" cellspacing="0" border="0" class="loc-grid">
            {loc_cards}
          </table>
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
        <div style="text-align:left;margin-bottom:18px;padding:12px 16px;background:rgba(143,182,232,0.10);border-radius:3px;border-left:2px solid {BLUE_ON_NAVY};">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:2px;color:{BLUE_ON_NAVY};margin-bottom:6px;font-weight:600;">On This Day &middot; <span style="font-family:{MONO};">{otd_date}</span></div>
          <div style="font-size:12px;color:rgba(255,255,255,0.85);line-height:1.5;font-family:Georgia,serif;">{otd_event}</div>
          <div style="font-size:11px;color:rgba(255,255,255,0.6);font-style:italic;margin-top:4px;line-height:1.4;">{otd_rel}</div>
        </div>"""
    sections.append(f"""
    {_TAEGUK_RULE}
    <div style="padding:20px 32px;background:{NAVY};text-align:center;" class="sec footer">
      {otd_footer}
      <div style="font-size:10px;text-transform:uppercase;letter-spacing:2px;color:rgba(255,255,255,0.45);font-family:Arial,sans-serif;line-height:2;">
        CSIS Korea Chair &nbsp;&middot;&nbsp; Korea Daily Brief
      </div>
      <div style="font-family:{MONO};font-size:10px;color:rgba(255,255,255,0.4);margin-top:2px;">generated {gen_time}</div>
      <div style="margin-top:8px;"><a href="#top" style="font-size:10px;color:rgba(255,255,255,0.4);text-decoration:none;letter-spacing:1px;">&#8593; Back to top</a></div>
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
    /* Mobile responsive — one declaration per pattern; no duplicates.
       Fixes from the Q3 2026 mobile audit are marked (A#). */
    @media only screen and (max-width: 620px) {{
      .wrapper {{ width:100% !important; }}
      .sec, .footer {{ padding:16px 16px !important; }}
      /* (A4) Masthead keeps presence on phones */
      h1 {{ font-size:22px !important; }}
      h2 {{ font-size:12px !important; }}
      h3 {{ font-size:14px !important; }}
      .key-stat-num {{ font-size:26px !important; }}
      /* (A10) Market strip STAYS 3-across on mobile — smaller mono, tighter pad */
      .mkt-table td {{ padding:8px 4px 10px !important; }}
      .mkt-table div[style*="font-size:16px"] {{ font-size:14px !important; }}
      .mkt-table div[style*="font-size:14px"] {{ font-size:13px !important; }}
      /* (A11) Grids stack — declared once each */
      .loc-grid td, .gov-grid td {{ display:block !important; width:100% !important; padding:5px 0 !important; }}
      .loc-grid tr, .gov-grid tr {{ display:block !important; }}
      .loc-grid div[style*="font-size:11px"] {{ font-size:12px !important; }}
      /* Calendar watch */
      .cal-table td[width="50"] {{ width:40px !important; padding:8px 6px 8px 0 !important; }}
      .cal-date {{ font-size:16px !important; }}
      /* Deal / business cards */
      .deal-card {{ padding:10px 0 !important; }}
      .deal-breakdown td {{ display:block !important; width:100% !important; padding:2px 8px !important; font-size:11px !important; white-space:normal !important; }}
      .deal-breakdown tr {{ display:block !important; border-bottom:1px solid #E8EDF3 !important; padding:4px 0 !important; }}
      /* (A7) Sentiment 2x2 — 47% leaves room for padding, no wrap */
      .sentiment-table td {{ display:inline-block !important; width:47% !important; box-sizing:border-box !important; padding:10px 4px !important; text-align:center !important; }}
      /* Trade dashboard strip — stays 3-across like the market strip */
      .trade-dash td {{ padding:9px 4px 10px !important; }}
      .trade-dash span[style*="font-size:24px"] {{ font-size:18px !important; }}
      .trade-dash span[style*="font-size:12px"] {{ font-size:11px !important; }}
      /* Tariff sector + trade policy tables — stack */
      .tariff-sector td, .trade-policy td {{ display:block !important; width:100% !important; padding:3px 8px !important; white-space:normal !important; }}
      .tariff-sector tr {{ display:block !important; border-bottom:1px solid #F0E0E0 !important; padding:4px 0 !important; }}
      .trade-policy tr {{ display:block !important; border-bottom:1px solid #E8E8E8 !important; padding:6px 0 !important; }}
      /* Story cards */
      .story-card {{ padding:12px 10px !important; }}
      /* (A3) Overflow safety */
      p, div, td {{ word-wrap:break-word !important; overflow-wrap:break-word !important; }}
      /* KCNA dark panel */
      .kcna-dark td {{ padding-left:16px !important; padding-right:16px !important; }}
      .kcna-dark > div {{ padding:16px 16px !important; }}
      .kcna-dark table td {{ white-space:normal !important; word-break:break-word !important; }}
      /* (A2) Legibility floor — real declarations only */
      body, td, div, p, span {{ -webkit-text-size-adjust:100%; }}
      div[style*="font-size:10px"], span[style*="font-size:10px"] {{ font-size:11px !important; }}
      /* (A1) Touch targets via min-height alone; no line-height bloat */
      a {{ min-height:44px; }}
      p a, div a, td a {{ min-height:auto; padding:6px 0; }}
      img {{ max-width:100% !important; height:auto !important; }}
    }}
    /* Tablet breakpoint — tighten padding, keep grids side-by-side */
    @media only screen and (min-width: 621px) and (max-width: 768px) {{
      .wrapper {{ width:100% !important; }}
      .sec, .footer {{ padding:16px 22px !important; }}
      h1 {{ font-size:22px !important; }}
      .deal-card {{ padding:12px 0 !important; }}
      /* (A5) Market strip numbers don't collide at 621px */
      .mkt-table td {{ padding:10px 10px 12px !important; }}
    }}
    /* Dark mode support — scoped selectors, no blanket color override (A6).
       The masthead, market strip, key stat, KCNA panel, and footer are
       already dark surfaces and need no inversion. */
    @media (prefers-color-scheme: dark) {{
      body {{ background:#121212 !important; }}
      .wrapper {{ background:#1a1a1a !important; }}
      .wrapper .sec {{ background:#1E2126 !important; border-bottom-color:#33373D !important; }}
      .wrapper h1, .wrapper h2, .wrapper h3 {{ color:#E8E6E1 !important; }}
      .wrapper .sec p {{ color:#C4C8CE !important; }}
      .wrapper a {{ color:#6FA8E8 !important; }}
      .wrapper .footer {{ background:#04182F !important; }}
      .wrapper .story-card {{ background:#262A30 !important; border-color:#33373D !important; }}
      .wrapper .kcna-dark, .wrapper .kcna-dark table, .wrapper .kcna-dark > div {{ background:#0A1E38 !important; }}
      .wrapper .gov-grid div {{ background:#262A30 !important; }}
      .wrapper .loc-grid div {{ background:#262A30 !important; border-color:#4A4F57 !important; }}
      .wrapper .loc-grid div[style*="color:#1A222E"] {{ color:#D5D8DC !important; }}
      .wrapper .loc-grid div[style*="color:#555"] {{ color:#AAA !important; }}
      .wrapper .loc-grid div[style*="color:#999"] {{ color:#8A9099 !important; }}
      .wrapper .sentiment-spotlight {{ background:#16222F !important; color:#C4C8CE !important; }}
      .wrapper .sentiment-discourse {{ background:#2A1518 !important; color:#C4C8CE !important; }}
      .wrapper .mkt-table td {{ border-color:rgba(255,255,255,0.08) !important; }}
    }}
  </style>
  <!--[if mso]>
  <style type="text/css">
    table {{ border-collapse:collapse; }}
    .wrapper {{ width:680px; }}
  </style>
  <![endif]-->
</head>
<body style="margin:0;padding:0;background:#F2F3F5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
  <!--[if mso]><table width="680" cellpadding="0" cellspacing="0" border="0" align="center"><tr><td><![endif]-->
  <div class="wrapper" style="max-width:680px;width:100%;margin:0 auto;background:#FFFFFF;overflow:hidden;box-shadow:0 2px 20px rgba(0,0,0,0.08);">
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
