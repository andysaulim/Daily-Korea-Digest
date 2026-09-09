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
NAVY = "#1B2A4A"          # masthead / footer ground (shared across the four briefs)
BAND = "#0052B4"          # nameplate band — Korea's identity colour (taeguk blue)
NAVY_DATA = "#051F3D"     # market strip ground
NAVY_PANEL = "#0A1E38"    # KCNA dark panel
INK = "#1A222E"
RED_ON_NAVY = "#E8697A"
BLUE_ON_NAVY = "#8FB6E8"
UP_GREEN = "#2E7D4F"      # semantic up (white ground)
DOWN_RED = "#A93226"      # semantic down (white ground)
MONO = "'Courier New',Courier,monospace"
SANS = "Arial,Helvetica,sans-serif"
SERIF = "Georgia,'Times New Roman',serif"
# One muted grey and one body grey. There were six, three of which failed
# contrast on white; a reader should not be able to tell two greys apart.
MUTE = "#6B7280"          # labels, meta, source lines
BODY_INK = "#4A5260"      # running body copy




# ── Dark mode ───────────────────────────────────────────────────────────────
# Every colour in this brief is applied inline, because email clients strip
# stylesheets. Dark mode is therefore a mapping from the light palette to a
# dark one, and it is generated from the two tables below rather than written
# as selectors by hand.
#
# The hand-written version rotted immediately: its selectors matched only
# `div`, `h3` and `a`, while the markup also uses `td`, `p` and `span`, and it
# enumerated a subset of the colours actually in use. The accent blue on every
# section label had no rule at all. Readers on Apple Mail saw headlines at
# 1.1:1 against the background — invisible.
#
# `_check_dark_coverage()` runs in the render test and fails when any inline
# colour reaching the output is absent from these tables, so a new colour
# cannot ship without its dark counterpart.

_DARK_TEXT = {
    "#0047A0": "#7FB0F0",   # accent — section labels, kickers, links
    "#1A222E": "#E8E6E1",   # ink — headlines
    "#1B2A4A": "#D5D8DC",   # navy used as type, not as ground
    "#2C3E50": "#D5D8DC",   # sub-headings
    "#2C3540": "#D5D8DC",
    "#4A5260": "#C4C8CE",   # body copy
    "#55607A": "#C4C8CE",
    "#5A6472": "#C4C8CE",
    "#6B7280": "#9AA3AE",   # muted labels and meta
    "#CD2E3A": "#F08A94",   # alert red
    "#A93226": "#F08A94",   # semantic down
    "#2E7D4F": "#5FBF87",   # semantic up
    "#B26A00": "#E0A64A",   # semantic caution
}

_DARK_BG = {
    "#fff":     "#262A30",  # cards
    "#FFFFFF":  "#262A30",
    "#F0F0F0":  "#2A2E34",
    "#F7F8FA":  "#1A1D22",  # utility bar
    "#F5F7FA":  "#22262C",  # table header rows
    "#EDF2FA":  "#1C2A3E",  # Today at a Glance
    "#F0F5FB":  "#16222F",  # Gallup spotlight
    "#FBF0F1":  "#2A1518",  # discourse flag
    "#FBF3F0":  "#2A1D15",  # caution panel
    "#EEF3F9":  "#1C2A3E",  # inset panels
    "#E7EBF0":  "#22262C",
    "#E4EFE7":  "#16281C",  # positive status fill
    "#F8F9FA":  "#22262C",
}

# Colours that need no dark variant: they already sit on a dark ground
# (masthead, market strip, KCNA panel, footer, accent chips) or are white on
# an accent fill.
_DARK_EXEMPT = {
    "#fff", "#FFFFFF", "#8FA0B5", "#8FB6E8", "#7B90AC", "#E8697A",
    "#0047A0", "#0052B4", "#1B2A4A", "#051F3D", "#0A1E38", "#2E3644",
    "#EBEBEB", "#E4E7EB", "#E8E8E8", "#EEF0F3", "#D5DAE1", "#F2F3F5",
    "#5A6472",  # badge fill — legible in both schemes, needs no variant
    # Status-chip fills: a saturated ground with white type, readable either way.
    "#CD2E3A", "#2E7D4F", "#A93226", "#B26A00",
    # The dark palette's own values, so re-scanning a dark rule is not a miss.
    "#E8E6E1", "#121212", "#1a1a1a", "#1E2126", "#262A30", "#04182F",
    "#16222F", "#1A1D22", "#2A1518", "#1C2A3E", "#22262C", "#2A1D15",
    "#16281C", "#2A2E34",
    "#F0F0F0",  # retired utility band; kept so an old copy still maps
    # The KCNA panel and the market strip are dark grounds in both schemes,
    # so their type and status dots are already light-on-dark.
    "#E0E0E0", "#E8E8E8", "#A8B6C8", "#A0AEC0", "#D8DEE8",
    "#27AE60", "#C0392B", "#69C88E", "#E8697A",
}


def _dark_mode_css() -> str:
    """Build the dark media query from the palette maps.

    Selectors are descendants of `.wrapper`, so the wrapper's own white ground
    is left to the explicit rule below rather than being caught by the card
    rule. Backgrounds are written `background:` throughout, so a `color:`
    substring match cannot collide with one.
    """
    lines = [
        "    @media (prefers-color-scheme: dark) {",
        "      body { background:#121212 !important; }",
        "      .wrapper { background:#1a1a1a !important; }",
        "      .wrapper .sec { background:#1E2126 !important; border-bottom-color:#4A526073D !important; }",
        "      .wrapper .nav-row { background:#1A1D22 !important; border-bottom-color:#4A526073D !important; }",
        "      .wrapper h1, .wrapper h2, .wrapper h3 { color:#E8E6E1 !important; }",
        "      .wrapper .footer { background:#04182F !important; }",
        "      .wrapper .kcna-dark, .wrapper .kcna-dark table, .wrapper .kcna-dark > div { background:#0A1E38 !important; }",
        "      .wrapper .item-card, .wrapper .story-card, .wrapper .gov-grid div, .wrapper .loc-grid div { background:#262A30 !important; border-color:#4A526073D !important; }",
        "      .wrapper .sentiment-spotlight { background:#16222F !important; }",
        "      .wrapper .sentiment-discourse { background:#2A1518 !important; }",
        "      .wrapper .mkt-table td { border-color:rgba(255,255,255,0.08) !important; }",
        "      .wrapper .sentiment-table td, .wrapper .cal-table { border-color:#4A526073D !important; }",
        "      .wrapper td[style*=\"border-bottom:1px solid #E8E8E8\"], .wrapper table[style*=\"border-bottom:1px solid #E8E8E8\"] { border-color:#4A526073D !important; }",
    ]
    for light, dark in _DARK_TEXT.items():
        lines.append(f'      .wrapper [style*="color:{light}"] {{ color:{dark} !important; }}')
    for light, dark in _DARK_BG.items():
        lines.append(f'      .wrapper [style*="background:{light}"] {{ background-color:{dark} !important; }}')
    lines.append("    }")
    return "\n".join(lines)


_DARK_CSS = _dark_mode_css()


def _check_dark_coverage(html: str) -> list[str]:
    """Every inline colour in the output must have a dark counterpart.

    Called by the render test. This is the guard that keeps dark mode from
    silently rotting the next time someone adds a colour.
    """
    import re as _re
    body = html.split("<body", 1)[-1]
    missing = []
    for hexv in set(_re.findall(r"(?<!-)color:\s*(#[0-9A-Fa-f]{3,6})", body)):
        if hexv not in _DARK_TEXT and hexv not in _DARK_EXEMPT:
            missing.append(f"text colour {hexv} has no dark mapping")
    for hexv in set(_re.findall(r"background:\s*(#[0-9A-Fa-f]{3,6})", body)):
        if hexv not in _DARK_BG and hexv not in _DARK_EXEMPT:
            missing.append(f"background {hexv} has no dark mapping")
    return sorted(missing)


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





def _link_or_text(text: str, url: str, style: str = "color:#1A222E;text-decoration:none;") -> str:
    """Render as <a> only if url is a real link, otherwise plain text.
    NOTE: `text` should already be HTML-escaped by the caller via _esc()."""
    if url and url != "#" and url.startswith("http"):
        return f'<a href="{_esc(url)}" style="{style}">{text}</a>'
    return text


# ── Section padding helper (responsive via class) ────────────────────────
_SEC = 'style="padding:20px 32px;border-bottom:1px solid #EBEBEB;" class="sec"'


def _sec_label(label: str, color: str = TAEGUK_BLUE) -> str:
    return (f'<div style="font-size:11px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:1.5px;color:{color};font-family:Arial,sans-serif;'
            f'margin-bottom:14px;padding-bottom:6px;border-bottom:2px solid {color};">'
            f'{label}</div>')


def _item_block(cat: str, src: str, headline: str, body: str, url: str,
                 bar_color: str = TAEGUK_BLUE, extra_html: str = "") -> str:
    """One card treatment for every list item in the brief.

    Top stories, overnight, business, regional and wire items used to carry
    three different treatments — bordered cards, bare underlined links, and a
    red-barred block — for the same kind of content. That read as two products
    stitched together. This is the single form: white card, accent left rule,
    kicker, headline in ink with no underline, body, source last and muted.
    """
    kicker = " &middot; ".join(x for x in (cat, src) if x)
    return f"""
            <div class="item-card" style="margin-bottom:10px;padding:12px 14px;background:#fff;border-radius:3px;border-left:3px solid {bar_color};border-top:1px solid #EEF0F3;border-right:1px solid #EEF0F3;border-bottom:1px solid #EEF0F3;">
              {"<div style='font-size:10px;text-transform:uppercase;letter-spacing:1px;color:" + bar_color + ";font-weight:700;margin-bottom:4px;'>" + kicker + "</div>" if kicker else ""}
              <div style="font-size:14px;font-weight:600;color:#1A222E;font-family:Georgia,serif;line-height:1.4;">
                {_link_or_text(headline, url)}
              </div>
              {"<div style='font-family:Georgia,serif;font-size:13px;line-height:1.5;color:#4A5260;margin-top:4px;'>" + body + "</div>" if body else ""}
              {extra_html}
            </div>"""


_CHROME_WORDS = _re.compile(
    r"For Internal Use Only|Read online|Download PDF|Past issues|Back to top|"
    r"Top Stories|Pyongyang|Trade|Markets|Polling|Upcoming|"
    r"Center for Strategic and International Studies", _re.I)


def _count_rendered_words(html_body: str) -> int:
    """Count the words a reader actually sees.

    The old estimate walked the digest dict and summed a fixed list of fields.
    It was wrong in both directions at once: it counted `so_what` and
    `pattern_note`, which were removed from the brief but stayed in the schema,
    while missing the ministry actions, trade status, calendar, official posts
    and On This Day, all of which do render. The published word count and the
    "X min read" beside it were both fiction, and the word-floor check in
    run.py was measuring the wrong number.

    Counting the assembled HTML cannot drift from what ships. Chrome — the
    utility links, the section nav, the footer lockup — is excluded so the
    figure reflects the brief, not the furniture.
    """
    text = _re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_body, flags=_re.S | _re.I)
    text = _re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&middot;", " ").replace("&nbsp;", " ").replace("&amp;", "&")
    text = _CHROME_WORDS.sub(" ", text)
    text = _re.sub(r"\s+", " ", text)
    return len([w for w in text.split() if any(c.isalnum() for c in w)])


def render(digest: dict) -> str:
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    date_str = now.strftime("%A, %B %-d, %Y")  # Thursday, March 20, 2026
    gen_time = now.strftime("%-I:%M %p ET")
    re_line = _esc(digest.get("re_line", ""))
    word_count = 0          # resolved from the assembled body; see %%WORDS%%
    # Issue number, when run.py supplied one, so the brief is citable.
    _issue_no = digest.get("issue_no")
    _issue_meta = (f'No. {int(_issue_no)} &middot; '
                   if isinstance(_issue_no, (int, float)) and _issue_no > 0 else "")
    read_min = 0

    web_url = digest.get("web_url", "")
    _footer_trade = ""
    _b = web_url[:-len("latest.html")] if web_url.endswith("latest.html") else ""
    archive_url = (_b + "archive.html") if _b else web_url
    if _b:
        _footer_trade = (f' &nbsp;&middot;&nbsp; <a href="{_b}trade.html" '
                         f'style="color:#8FB6E8;text-decoration:none;">Trade reference</a>')
    sections = []

    # ── 0. View in Browser bar (Read online · Print / PDF · Archive) ──────
    if web_url:
        base = web_url[:-len("latest.html")] if web_url.endswith("latest.html") else ""
        _a = ('display:inline-block;padding:4px 12px;margin:0 2px;'  # util-btn
              'font-family:Arial,sans-serif;font-size:11px;font-weight:700;'
              'letter-spacing:0.5px;color:rgba(255,255,255,0.92);background:rgba(255,255,255,0.10);'
              'border:1px solid rgba(255,255,255,0.22);border-radius:3px;'
              'text-decoration:none;white-space:nowrap;')
        links = [f'<a href="{_esc(web_url)}" style="{_a}">Read online</a>']
        if base:
            links.append(f'<a href="{_esc(base + "latest.pdf")}" style="{_a}">Download PDF</a>')
            links.append(f'<a href="{_esc(base + "archive.html")}" style="{_a}">Past issues</a>')
        sep = ''
        # The internal-use notice and the utility links each had a full-width
        # band to themselves, which put roughly 90px of chrome above the
        # nameplate before a reader reached a word of the brief. Same content,
        # one row: notice left, links right, collapsing to two centred rows on
        # a phone where they will not fit side by side.
        sections.append(f"""
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#2E3644;" class="util-row">
          <tr>
            <td class="util-cell" style="padding:7px 32px;font-family:Arial,sans-serif;font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:rgba(255,255,255,0.72);white-space:nowrap;">For Internal Use Only</td>
            <td class="util-cell" align="right" style="padding:5px 32px 5px 0;text-align:right;">{sep.join(links)}</td>
          </tr>
        </table>
        """)

    # ── 1. Header ────────────────────────────────────────────────────────
    sections.append(f"""
    <a name="top"></a>
    <div bgcolor="{BAND}" style="background-color:{BAND};color:#fff;padding:16px 32px 16px;border-bottom:1px solid rgba(255,255,255,0.18);" class="sec">
      <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
        <td style="vertical-align:top;">
          <div style="font-family:Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:rgba(255,255,255,0.78);margin-bottom:7px;">CSIS Korea Chair</div>
          <h1 style="margin:0 0 4px 0;font-size:28px;font-weight:700;font-family:Georgia,'Times New Roman',serif;color:#fff;letter-spacing:0.5px;">
            Korea Daily Brief
          </h1>
          <div style="margin-top:2px;font-size:16px;font-weight:400;color:rgba(255,255,255,0.85);font-family:Georgia,serif;">{_esc(date_str)}</div>
        </td>
        <td class="mast-meta" style="vertical-align:bottom;text-align:right;">
          <div style="font-family:{MONO};font-size:11px;color:rgba(255,255,255,0.72);white-space:nowrap;">{_issue_meta}%%WORDS%% words &middot; %%READMIN%% min read</div>
        </td>
      </tr></table>
      {"<div style='margin-top:14px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.28);font-size:13px;color:rgba(255,255,255,0.92);font-family:Georgia,serif;line-height:1.55;'><strong style='color:#FFFFFF;font-size:11px;letter-spacing:1.5px;font-family:Arial,sans-serif;'>RE:</strong>&nbsp; " + re_line + "</div>" if re_line else ""}
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
        # Top row: KOSPI, Brent, USD/KRW
        sections.append(f"""
        <a name="markets"></a>
        <table class="mkt-table" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{NAVY_DATA};color:#fff;border-bottom:1px solid rgba(255,255,255,0.10);">
          <tr>
            <td width="25%" align="center" style="padding:11px 6px 13px;">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#8FA0B5;">KOSPI</div>
              <div style="font-family:{MONO};font-size:16px;font-weight:700;margin-top:3px;">{_esc(str(kospi.get("value", "—")))}</div>
              <div style="font-family:{MONO};font-size:11px;margin-top:2px;">{_arrow(kospi.get("change_pct", 0))}</div>
            </td>
            <td width="25%" align="center" style="padding:11px 6px 13px;border-left:1px solid rgba(255,255,255,0.10);">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#8FA0B5;">USD/KRW</div>
              <div style="font-family:{MONO};font-size:16px;font-weight:700;margin-top:3px;">{_esc(str(krw.get("value", "—")))}</div>
              <div style="font-family:{MONO};font-size:11px;margin-top:2px;">{_arrow(krw.get("change_pct", 0))}</div>
            </td>
            <td width="25%" align="center" style="padding:11px 6px 13px;border-left:1px solid rgba(255,255,255,0.10);">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#8FA0B5;">Brent</div>
              <div style="font-family:{MONO};font-size:16px;font-weight:700;margin-top:3px;">${_esc(str(brent.get("value", "—")))}</div>
              <div style="font-family:{MONO};font-size:11px;margin-top:2px;">{_arrow(brent.get("change_pct", 0))}</div>
            </td>
            <td width="25%" align="center" style="padding:11px 6px 13px;border-left:1px solid rgba(255,255,255,0.10);">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#8FA0B5;">BOK Rate</div>
              <div style="font-family:{MONO};font-size:16px;font-weight:700;margin-top:3px;">{_esc(str(bok_rate.get("value", "—")))}</div>
              <div style="font-family:{MONO};font-size:11px;margin-top:2px;"><span style="color:#8FA0B5;">{_esc(str(bok_rate.get("last_change", "")))}</span></div>
            </td>
          </tr>
        </table>
        """)

    # ── 2c. Section navigation. Emitted as a placeholder here and resolved
    #      after every section is built, so links are only offered for
    #      sections that actually rendered. ─────────────────────────────────
    sections.append("%%NAV%%")

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
        <div style="padding:18px 32px 6px;" class="sec">
          <a name="memo"></a>
          <table width="100%" cellpadding="0" cellspacing="0" border="0" class="glance-panel" style="background:#EDF2FA;border-left:3px solid {TAEGUK_BLUE};">
            <tr><td style="padding:16px 20px 8px;">
              {_sec_label("Today at a Glance")}
              {memo_html}
            </td></tr>
          </table>
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
            src_line = _esc(_clean_src(story.get("src_line", story.get("source", ""))))
            url = story.get("url", "")
            cat_badge = f'<div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:{TAEGUK_BLUE};font-weight:700;margin-bottom:4px;">{cat}</div>' if cat else ""
            stories_html += f"""
            <div class="item-card story-card" style="margin-bottom:12px;padding:14px 16px;background:#fff;border-radius:3px;border-left:3px solid {TAEGUK_BLUE};border-top:1px solid #EEF0F3;border-right:1px solid #EEF0F3;border-bottom:1px solid #EEF0F3;">
              {cat_badge}
              <h3 style="margin:0 0 6px 0;font-size:16px;font-weight:600;color:{INK};font-family:Georgia,serif;line-height:1.4;">
                {_link_or_text(headline, url)}
              </h3>
              <p style="margin:0 0 6px 0;font-size:13px;line-height:1.6;font-family:Georgia,serif;color:#4A5260;">{body}</p>
              <div style="font-size:11px;color:#6B7280;margin-top:4px;">{src_line}</div>
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
            # A scan list, not a second Top Stories. One rule down the left,
            # one line per item, so the eye runs vertically instead of stopping
            # at a card border every three lines. The cards above carry the
            # weight; this section carries the breadth.
            tail = (f'<span style="color:#6B7280;"> &mdash; {body}</span>' if body else "")
            flash_html += (
                f'<tr>'
                f'<td style="padding:7px 10px 7px 0;vertical-align:top;white-space:nowrap;'
                f'font-family:Arial,sans-serif;font-size:10px;font-weight:700;'
                f'letter-spacing:0.5px;text-transform:uppercase;color:{TAEGUK_BLUE};'
                f'border-bottom:1px solid #EEF0F3;">{cat}</td>'
                f'<td style="padding:7px 0;vertical-align:top;font-family:Georgia,serif;'
                f'font-size:13px;line-height:1.45;color:{INK};'
                f'border-bottom:1px solid #EEF0F3;">'
                f'{_link_or_text(headline, url)}{tail}'
                f'<span style="font-family:Arial,sans-serif;font-size:11px;color:#6B7280;">'
                f' &middot; {src}</span></td>'
                f'</tr>')
        flash_html = (f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
                      f'class="flash-table" style="border-top:2px solid {TAEGUK_BLUE};">'
                      f'{flash_html}</table>')
        sections.append(f"""
        <div {_SEC}>
          <a name="overnight"></a>{_sec_label("Overnight")}
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
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:2px;color:{BLUE_ON_NAVY};margin-bottom:7px;font-weight:600;">Stat of the Day</div>
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
        data_unavailable = kcna.get("data_unavailable", False)
        # A genuine one-day "complete silence" is almost never real (KCNA
        # publishes daily), so never assert it on a collection failure.
        silence = kcna.get("silence_today", False) and not data_unavailable

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
            quotes_html += f"""<div style='margin-bottom:10px;padding:1px 0 1px 14px;border-left:3px solid {TAEGUK_RED};'>
              <div style='font-size:13px;font-family:Georgia,serif;color:#E8E8E8;font-style:italic;line-height:1.5;'>&ldquo;{qt}&rdquo;</div>
              <div style='font-size:10px;margin-top:4px;'>{speaker_line}{src_line}</div>
            </div>"""

        # Senior officials around Kim. Extracted by the prompt and, until now,
        # discarded at the render step.
        seniors = kcna.get("senior_officials") or []
        seniors_html = ""
        senior_rows = ""
        for off in seniors[:3]:
            o_name = _esc(off.get("name", ""))
            o_role = _esc(off.get("role", ""))
            o_act = _esc(off.get("activity", ""))
            if not o_name or not o_act:
                continue
            role_line = (f"<span style='color:#7B90AC;'> &middot; {o_role}</span>"
                         if o_role else "")
            senior_rows += (
                f"<div style='margin-bottom:7px;'>"
                f"<div style='font-size:13px;font-weight:600;font-family:Georgia,serif;color:#E8E8E8;'>{o_name}{role_line}</div>"
                f"<div style='font-size:12px;font-family:Georgia,serif;color:#A8B6C8;line-height:1.45;'>{o_act}</div>"
                f"</div>")
        if senior_rows:
            seniors_html = (
                f'<div style="margin-top:14px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.10);">'
                f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#7B90AC;margin-bottom:8px;">Senior Officials</div>'
                f'{senior_rows}</div>')

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
                    <div style="font-size:13px;font-weight:600;font-family:Georgia,serif;color:#E8E8E8;line-height:1.4;">{_link_or_text(a_headline, a_url, style="font-family:Georgia,serif;color:#E8E8E8;text-decoration:underline;")}{kim_badge}</div>
                    {"<div style='font-size:12px;font-family:Georgia,serif;color:#A8B6C8;line-height:1.5;margin-top:2px;'>" + a_summary + src_tag + "</div>" if a_summary else ""}
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
                <span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:{BLUE_ON_NAVY};font-family:Arial,sans-serif;border-bottom:2px solid {TAEGUK_RED};padding-bottom:5px;display:inline-block;">Pyongyang Watch &middot; KCNA</span>
              </td>
            </tr>
          </table>
          <div style="padding:16px 32px;background:{NAVY_PANEL};font-family:Georgia,serif;color:#E0E0E0;">
            {"<div style='margin-bottom:12px;padding:8px 14px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.15);border-radius:3px;font-size:12px;font-family:Georgia,serif;color:#A8B6C8;'>No new KCNA dispatches ingested today &mdash; showing last known status.</div>" if data_unavailable else ""}
            {"<div style='margin-bottom:12px;padding:8px 14px;background:" + TAEGUK_RED + ";color:#fff;border-radius:3px;font-size:12px;font-weight:600;'>Complete KCNA silence today</div>" if silence else ""}
            <div style="padding:0 0 12px;margin-bottom:14px;border-bottom:1px solid rgba(255,255,255,0.14);">
              <span style="font-family:Arial,sans-serif;font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#7B90AC;">Kim Jong Un</span>
              {"<span style='display:inline-block;margin-left:8px;padding:1px 7px;border-radius:3px;background:" + TAEGUK_RED + ";color:#fff;font-family:Arial,sans-serif;font-size:10px;font-weight:700;letter-spacing:1px;'>WATCH FLAG</span>" if watch and not silence and not data_unavailable else ""}
              <div style="font-size:15px;color:#E8E6E1;font-weight:600;margin-top:4px;">{kim_icon}{kim_line}</div>
            </div>
            {quotes_html}
            {articles_html}
            {seniors_html}
            {"<div style='margin-top:16px;padding:1px 0 1px 14px;border-left:3px solid " + BLUE_ON_NAVY + ";font-size:13px;line-height:1.6;color:#E0E0E0;font-family:Georgia,serif;'><strong style='color:" + BLUE_ON_NAVY + ";'>Bottom line:</strong> " + bottom_line + "</div>" if bottom_line else ""}
          </div>
        </div>
        """)

    # ── 9. ROK Government (merged: Gov + Personnel + Assembly + Calendar) ─
    rok_gov = digest.get("rok_government") or []
    # Fixed observances are arithmetic, not recall, so they are computed and
    # merged with whatever dated events the model found today. Upcoming shipped
    # empty once and past-dated before that; neither is possible now.
    try:
        import korea_calendar
        calendar_watch = korea_calendar.merge(digest.get("calendar_watch"))
    except Exception:
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
                # Who acted. The prompt has always extracted this; the card
                # showed only the ministry, so the name was thrown away.
                official = _esc(item.get("official", ""))
                official_line = (
                    f'<div style="font-size:12px;font-family:Georgia,serif;color:#4A5260;margin-bottom:4px;">{official}</div>'
                    if official and official.lower() not in ("none", "null", "n/a") else "")
                ministry_header = ""
                if ministry_korean:
                    ministry_header = f'<span style="font-size:11px;color:#6B7280;">{ministry_korean} · </span>'
                ministry_header += f'<span style="font-size:10px;color:#6B7280;text-transform:uppercase;letter-spacing:0.5px;">{ministry}</span>'
                # A ministry release and a story about it are not the same kind
                # of thing, and the card used to show one unlabelled link for
                # whichever it had. Label them: the primary document first,
                # the reporting under it.
                secondary_url = item.get("secondary_url", "")
                secondary_label = _esc(item.get("secondary_label", ""))
                _rows = []
                if source_url and source_url != "#" and source_url.startswith("http"):
                    s_label = source_label if source_label else ministry
                    _rows.append(
                        f'<span style="font-weight:700;color:{TAEGUK_BLUE};">Primary</span> '
                        f'<a href="{_esc(source_url)}" style="font-family:Georgia,serif;color:#4A5260;text-decoration:none;">'
                        f'{_esc(s_label)} &#8599;</a>')
                elif source_label:
                    _rows.append(f'<span style="font-weight:700;color:{TAEGUK_BLUE};">Primary</span> '
                                 f'{_esc(source_label)}')
                if secondary_url and str(secondary_url).startswith("http"):
                    _rows.append(
                        f'<span style="font-weight:700;">Reported</span> '
                        f'<a href="{_esc(secondary_url)}" style="font-family:Georgia,serif;color:#4A5260;text-decoration:none;">'
                        f'{secondary_label or "coverage"} &#8599;</a>')
                elif secondary_label:
                    _rows.append(f'<span style="font-weight:700;">Reported</span> {secondary_label}')
                src_link = ""
                if _rows:
                    src_link = ('<div style="margin-top:8px;padding-top:7px;'
                                'border-top:1px solid #E1E6ED;font-family:Arial,sans-serif;'
                                'font-size:11px;line-height:1.7;color:#6B7280;">'
                                + "<br>".join(_rows) + "</div>")
                row_cards += f"""
                <td style="width:50%;padding:8px;vertical-align:top;">
                  <div style="background:#F5F7FA;border-radius:3px;padding:14px;min-height:100px;">
                    <div style="margin-bottom:6px;">{ministry_header}</div>
                    <div style="font-size:14px;font-weight:700;color:{INK};line-height:1.3;margin-bottom:6px;">{_esc(action)}</div>
                    {official_line}
                    <div style="font-size:12px;line-height:1.5;font-family:Georgia,serif;color:#4A5260;">{_esc(detail)}</div>
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
                      <div style="font-size:10px;text-transform:uppercase;color:#6B7280;letter-spacing:0.5px;">{cal_month}</div>
                      <div class="cal-date" style="font-family:{MONO};font-size:17px;font-weight:700;color:{TAEGUK_BLUE};line-height:1.2;">{cal_day}</div>
                    </td>
                    <td style="padding:10px 0;vertical-align:top;">
                      <div style="font-size:13px;font-weight:600;color:#1B2A4A;margin-bottom:2px;">{cal_headline}</div>
                      <div style="font-size:12px;line-height:1.4;font-family:Georgia,serif;color:#4A5260;">{cal_detail}</div>
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
                pred_line = f'<div style="font-size:11px;color:#6B7280;margin-top:2px;">Replaces: {predecessor}</div>' if predecessor else ""
                pers_items += f"""
                <div style="margin-bottom:10px;padding-left:12px;border-left:3px solid {a_color};">
                  <div style="font-size:13px;font-weight:600;color:#1B2A4A;">{name}{action_badge}</div>
                  <div style="font-size:12px;font-family:Georgia,serif;color:#4A5260;">{position}</div>
                  <div style="font-size:12px;line-height:1.4;font-family:Georgia,serif;color:#4A5260;">{detail}</div>
                  {pred_line}
                </div>"""
            pers_html = f"""
            <div style="margin-top:16px;">
              <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;font-family:Georgia,serif;color:#2C3E50;margin-bottom:8px;padding-bottom:4px;border-bottom:1px solid #E8E8E8;">Personnel Changes</div>
              {pers_items}
            </div>"""

        # Assembly activity (inline in ROK Gov)
        asm_html = ""
        if rok_assembly:
            asm_items = ""
            for item in rok_assembly:
                _c = str(item.get("committee", "") or "")
                committee = _esc(_c.title() if _c.isupper() else _c)
                action = _esc(item.get("action", "") or item.get("activity", ""))
                detail = _esc(item.get("detail", ""))
                asm_items += f"""
                <div style="margin-bottom:11px;padding-left:12px;border-left:3px solid #C9D2DE;">
                  <div style="font-family:Georgia,serif;font-size:14px;font-weight:600;color:{INK};line-height:1.35;">{action}</div>
                  <div style="font-size:12px;color:#6B7280;margin-top:2px;">{committee}</div>
                  <div style="font-size:13px;line-height:1.5;font-family:Georgia,serif;color:#4A5260;margin-top:3px;">{detail}</div>
                </div>"""
            asm_html = f"""
            <div style="margin-top:16px;">
              <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:#6B7280;margin-bottom:8px;padding-bottom:4px;border-bottom:1px solid #E8E8E8;">National Assembly</div>
              {asm_items}
            </div>"""

        rok_date = _esc(str(digest.get("digest_date", "")))
        sections.append(f"""
        <div {_SEC}>
          <a name="rok-gov"></a>{_sec_label("ROK Government")}
          <div style="font-size:10px;color:#6B7280;font-family:Arial,sans-serif;margin-top:-10px;margin-bottom:10px;">President + Ministries &middot; {rok_date}</div>
          <div style="padding-top:4px;">
            {gov_grid_html}
            {pers_html}
            {asm_html}
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
                  <td style="padding:6px 0 6px 4px;font-size:10px;color:#6B7280;">{note}</td>
                </tr>"""
            races_html = f"""
            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:10px;border-top:1px solid #E8E8E8;">
              <tr style="border-bottom:1px solid #E8E8E8;">
                <td style="padding:4px 8px 4px 0;font-size:10px;color:#6B7280;text-transform:uppercase;">Race</td>
                <td style="padding:4px 4px;font-size:10px;color:#6B7280;text-transform:uppercase;">Parties</td>
                <td style="padding:4px 4px;font-size:10px;color:#6B7280;text-transform:uppercase;text-align:center;">Status</td>
                <td style="padding:4px 0 4px 4px;font-size:10px;color:#6B7280;text-transform:uppercase;">Note</td>
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
          <div style="font-size:11px;color:#6B7280;margin-top:4px;">{e_date}</div>
          <div style="font-size:13px;line-height:1.6;font-family:Georgia,serif;color:#4A5260;margin-top:8px;">{e_summary}</div>
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
    investment_ledger = (us_korea.get("investment_ledger") or []) if isinstance(us_korea, dict) else []

    state_of_play = _esc(us_korea.get("state_of_play", "")) if isinstance(us_korea, dict) else ""

    if deal_list or trade_policy or investment_pkg or tariff_tracker or investment_ledger:
        pillars = []        # shown in the daily brief
        standing = []       # reference — published to the standing page instead

        sop_html = ""
        if state_of_play:
            sop_html = (f'<div style="font-family:Georgia,serif;font-size:14px;line-height:1.6;'
                        f'color:#2C3540;margin-bottom:6px;">{state_of_play}</div>')

        _pillar_h = (lambda label, accent=TAEGUK_RED:
            f'<div style="font-size:12px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;'
            f'color:{NAVY};padding-bottom:5px;border-bottom:2px solid {accent};display:inline-block;'
            f'margin-bottom:12px;">{label}</div>')
        _box = (lambda inner:
            f'<div style="border:1px solid #DBE0E6;border-radius:3px;overflow:hidden;margin-top:12px;">{inner}</div>')

        # ── Pillar 1: Tariffs ──────────────────────────────────────────────
        if tariff_tracker and tariff_tracker.get("headline_rate"):
            # The big number is JUST the rate. Models sometimes append a whole
            # clause to headline_rate ("10% (Section 122 expired…)"); that would
            # render at 32px in a narrow cell and wrap one word per line. Keep
            # only the leading rate token; spill any trailing text into the note.
            _raw_rate = str(tariff_tracker.get("headline_rate", "")).strip()
            _rm = _re.match(r"\s*(\d{1,3}(?:\.\d+)?\s*%(?:\s*[-+/]\s*\d{1,3}(?:\.\d+)?\s*%)?)\s*(.*)",
                            _raw_rate, _re.DOTALL)
            if _rm:
                h_rate = _esc(_rm.group(1).strip())
                _rate_spill = _rm.group(2).strip().strip("()").strip()
            else:
                # No numeric rate (e.g. the surcharge expired) — never show a
                # truncated string as the big number. Lead with the status
                # instead; the descriptive text falls to the note.
                h_rate = ""
                _rate_spill = _raw_rate
            _has_rate = bool(h_rate)
            h_status = tariff_tracker.get("headline_status", "ACTIVE")
            if h_status == "ESCALATION":
                h_status = "ACTIVE"
            h_note = _esc(str(tariff_tracker.get("headline_note", "")))
            # If the rate field carried a trailing clause and there's no note,
            # use that clause as the note so nothing is lost.
            if _rate_spill and not h_note:
                h_note = _esc(_rate_spill)
            s122 = tariff_tracker.get("section_122_surcharge")
            # Only a SHORT recognized status becomes a pill. If the model wrote a
            # long clause into headline_status, treat it as the note instead —
            # never cram a sentence into the little pill beside the big rate.
            _status_pill = {"ACTIVE": ("#FBECEE", "#B0212F"), "EXPIRED": ("#EEF1F5", "#55607A"),
                            "PAUSED": ("#EEF1F5", "#55607A"), "NEGOTIATING": ("#E5EAF2", "#0047A0"),
                            "REDUCED": ("#E4EFE7", "#1E7940"), "PENDING": ("#EEF1F5", "#55607A")}
            _h_key = h_status.strip().upper()
            status_pill = ""
            note_text = h_note or "US baseline reciprocal rate on ROK goods"
            if _h_key in _status_pill:
                pill_bg, pill_fg = _status_pill[_h_key]
                status_pill = (f'<span style="display:inline-block;font-family:{MONO};font-size:11px;font-weight:700;'
                               f'letter-spacing:0.5px;padding:2px 8px;border-radius:3px;background:{pill_bg};color:{pill_fg};">{_esc(_h_key)}</span>')
            elif h_status.strip():
                # long/free-form status -> fold into the note so it reads normally
                note_text = h_note or _esc(h_status)

            # Number and short pill share one line; the note gets its OWN
            # full-width line below (so it can never wrap into a narrow column).
            if _has_rate:
                _hero_lead = (f'<span style="font-family:{MONO};font-size:32px;font-weight:700;color:{TAEGUK_RED};vertical-align:middle;">{h_rate}</span>'
                              + (f'&nbsp;&nbsp;{status_pill}' if status_pill else ''))
            else:
                # Status is the hero (e.g. EXPIRED), muted — not a red percentage.
                _sw = _esc(_h_key if _h_key in _status_pill else (h_status.strip() or "—"))
                _hero_lead = f'<span style="font-family:{MONO};font-size:24px;font-weight:700;color:#55607A;letter-spacing:0.5px;vertical-align:middle;">{_sw}</span>'
            hero = (f'<div style="margin-bottom:5px;">{_hero_lead}</div>'
                    f'<div style="font-size:13px;color:#5A6472;line-height:1.5;">{note_text}</div>')

            def _cap(_s, _n=80):
                _s = str(_s).strip()
                return _s if len(_s) <= _n else _s[:_n - 1].rstrip() + "…"
            watch = ""
            watch_bits = []
            # Section 122 belongs in "Watch this date" only while it's a FUTURE
            # item — once expired it's history, so drop it here (the expiry is
            # already stated in the note).
            if s122 and "expir" not in str(s122).lower():
                watch_bits.append(f"Section 122 surcharge {_esc(_cap(s122, 48))}")
            _nt_raw = str(tariff_tracker.get("next_trigger", "")).strip()
            if _nt_raw:
                watch_bits.append(f"next trigger: {_esc(_cap(_nt_raw, 90))}")
            if watch_bits:
                watch = (f'<div style="margin-top:12px;background:#FBF3F0;border:1px solid #F1D9D2;'
                         f'border-left:3px solid {TAEGUK_RED};border-radius:3px;padding:9px 13px;">'
                         f'<div style="font-size:10px;letter-spacing:1px;text-transform:uppercase;color:#A93226;font-weight:700;">Watch this date</div>'
                         f'<div style="font-size:13px;font-family:Georgia,serif;color:#4A5260;margin-top:2px;">{" &middot; ".join(watch_bits)}</div></div>')

            _sec_colors = {"ACTIVE": TAEGUK_RED, "PAUSED": "#7F8C8D", "NEGOTIATING": TAEGUK_BLUE, "REDUCED": UP_GREEN}
            sec_rows = ""
            for sr in (tariff_tracker.get("sector_rates") or []):
                sr_st = sr.get("status", "ACTIVE")
                if sr_st == "ESCALATION":
                    sr_st = "ACTIVE"
                sec_rows += (f'<tr style="border-top:1px solid #E7EBF0;">'
                             f'<td style="padding:7px 12px;font-size:13px;font-weight:600;color:{INK};">{_esc(sr.get("sector",""))}</td>'
                             f'<td style="padding:7px 8px;font-size:11px;color:#6B7280;text-transform:uppercase;text-align:right;white-space:nowrap;">{_esc(sr.get("authority",""))}</td>'
                             f'<td style="padding:7px 12px 7px 8px;font-family:{MONO};font-size:13px;font-weight:700;color:{_sec_colors.get(sr_st, TAEGUK_RED)};text-align:right;white-space:nowrap;">{_esc(str(sr.get("rate","")))}</td>'
                             f'</tr>')
            sector_box = ""
            if sec_rows:
                sector_box = _box(
                    f'<div style="background:#F5F7FA;padding:7px 12px;font-size:11px;text-transform:uppercase;'
                    f'letter-spacing:1px;color:{TAEGUK_BLUE};font-weight:700;border-bottom:1px solid #DBE0E6;">Sector Rates</div>'
                    f'<table width="100%" cellpadding="0" cellspacing="0" border="0" class="tariff-sector">{sec_rows}</table>')

            pillars.append(f'<div style="margin-top:6px;">{_pillar_h("Tariffs")}{hero}{watch}{sector_box}</div>')

        # ── Pillar 2: Investment ───────────────────────────────────────────
        if investment_pkg and investment_pkg.get("total_pledged"):
            pledged = _esc(str(investment_pkg.get("total_pledged", "")))
            announced = str(investment_pkg.get("announced_to_date") or "").strip()
            try:
                pct_int = int(investment_pkg.get("pct_fulfilled"))
            except (TypeError, ValueError):
                pct_int = None
            # Only show a fulfillment bar when there's a REAL official drawdown
            # figure. The $350B pledge is a government-level commitment; ordinary
            # Korean corporate US investments are NOT tranches of it, so absent an
            # official drawdown number we leave fulfillment unfilled rather than
            # inventing a percentage from unrelated deals.
            has_progress = bool(announced) and pct_int is not None and pct_int > 0

            if has_progress:
                bar_w = max(2, min(pct_int, 100))
                latest = _esc(str(investment_pkg.get("latest_update", "")))
                if len(latest) > 60:
                    latest = latest[:57].rstrip() + "…"
                bar = (f'<div style="font-size:13px;font-family:Georgia,serif;color:#4A5260;margin-bottom:7px;">'
                       f'<span style="font-family:{MONO};color:{NAVY};font-size:15px;font-weight:700;">{_esc(announced)}</span> '
                       f'announced of {pledged} pledged &middot; {pct_int}% fulfilled</div>'
                       f'<div style="background:#E7EBF0;border-radius:6px;height:16px;overflow:hidden;">'
                       f'<div style="background:{TAEGUK_BLUE};width:{bar_w}%;height:100%;border-radius:6px 0 0 6px;"></div></div>'
                       + (f'<div style="font-size:11px;color:#6B7280;margin-top:5px;text-align:right;">newest: {latest}</div>' if latest else ""))
            else:
                note = _esc(str(investment_pkg.get("note") or "").strip()) or (
                    "Government-level commitment under the US-Korea trade framework, "
                    "channeled through the Korea-US Strategic Investment Corporation. "
                    "No official drawdown figure reported; individual Korean corporate "
                    "US investments are tracked separately and are not pledge tranches.")
                bar = (f'<div><span style="font-family:{MONO};color:{NAVY};font-size:22px;font-weight:700;">{pledged}</span>'
                       f'<span style="font-size:12px;color:#6B7280;"> &nbsp;pledged</span></div>'
                       f'<div style="font-size:13px;color:#5A6472;line-height:1.55;margin-top:6px;">{note}</div>')

            # Deal table only lists deals officially attributed to the pledge
            # (the prompt no longer dumps unrelated corporate announcements here).
            deal_rows = ""
            for kd in (investment_pkg.get("known_deals") or []):
                sect = _esc(kd.get("sector", ""))
                deal_rows += (f'<tr style="border-top:1px solid #E7EBF0;">'
                              f'<td style="padding:7px 12px;font-size:13px;color:{INK};"><span style="font-weight:600;">{_esc(kd.get("company",""))}</span>'
                              + (f' <span style="color:#6B7280;font-size:11px;">{sect}</span>' if sect else "")
                              + f'</td>'
                              f'<td style="padding:7px 12px 7px 8px;font-family:{MONO};font-size:12px;font-weight:700;color:{UP_GREEN};text-align:right;white-space:nowrap;">{_esc(kd.get("value",""))}</td>'
                              f'</tr>')
            deal_box = ""
            if deal_rows:
                deal_box = _box(
                    f'<div style="background:#F5F7FA;padding:7px 12px;font-size:11px;text-transform:uppercase;'
                    f'letter-spacing:1px;color:{TAEGUK_BLUE};font-weight:700;border-bottom:1px solid #DBE0E6;">Committed Investment Deals</div>'
                    f'<table width="100%" cellpadding="0" cellspacing="0" border="0" class="deal-breakdown">{deal_rows}</table>')

            standing.append(f'<div style="margin-top:18px;">{_pillar_h("Investment &middot; " + pledged + " pledge", accent=TAEGUK_BLUE)}{bar}{deal_box}</div>')

        # ── Pillar 2b: Bilateral Investment Ledger ─────────────────────────
        # Corporate investment flows BOTH directions, tracked separately from
        # the $350B pledge. No summed total — amounts are as-reported and many
        # are non-binding (MOU/LOI).
        if investment_ledger:
            _dir_groups = {"rok_to_us": [], "us_to_rok": [], "partnership": []}
            for e in investment_ledger:
                if isinstance(e, dict):
                    _dir_groups.get(str(e.get("direction", "")).lower(),
                                    _dir_groups["partnership"]).append(e)
            _status_chip = {"binding": ("#E4EFE7", "#1E7940"), "loi": ("#FBF3F0", "#B0212F"),
                            "mou": ("#EEF1F5", "#55607A"), "announced": ("#F1F4F8", "#55607A")}
            _dir_meta = [("rok_to_us", "Korea &rarr; US", TAEGUK_RED),
                         ("us_to_rok", "US &rarr; Korea", TAEGUK_BLUE),
                         ("partnership", "Partnerships &amp; supply", "#5A6472")]
            blocks = ""
            for key, lbl, color in _dir_meta:
                rows = _dir_groups.get(key) or []
                if not rows:
                    continue
                r_html = ""
                for e in rows:
                    entity = _esc(str(e.get("entity", "")))
                    cp = _esc(str(e.get("counterparty") or "").strip())
                    ent = entity + (f' <span style="color:#6B7280;font-weight:400;">/ {cp}</span>' if cp else "")
                    sect = _esc(str(e.get("sector") or "").strip())
                    val = _esc(str(e.get("value") or "").strip())
                    st = str(e.get("status") or "").lower().strip()
                    chip = ""
                    if st:
                        cbg, cfg = _status_chip.get(st, ("#F1F4F8", "#55607A"))
                        chip = (f'<span style="display:inline-block;font-family:{MONO};font-size:10px;font-weight:700;'
                                f'letter-spacing:0.5px;padding:1px 5px;border-radius:3px;background:{cbg};color:{cfg};'
                                f'margin-left:6px;vertical-align:middle;">{_esc(st.upper())}</span>')
                    r_html += (f'<tr style="border-top:1px solid #EAEDF1;">'
                               f'<td style="padding:6px 10px 6px 0;font-size:13px;color:{INK};">'
                               f'<span style="font-weight:600;">{ent}</span>{chip}'
                               + (f'<div style="font-size:11px;color:#6B7280;margin-top:1px;">{sect}</div>' if sect else "")
                               + f'</td>'
                               f'<td style="padding:6px 0;font-family:{MONO};font-size:12px;font-weight:700;color:{NAVY};'
                               f'text-align:right;white-space:nowrap;vertical-align:top;">{val or "&mdash;"}</td></tr>')
                blocks += (f'<div style="font-size:11px;font-weight:700;letter-spacing:0.5px;color:{color};'
                           f'margin:12px 0 2px;">{lbl}</div>'
                           f'<table width="100%" cellpadding="0" cellspacing="0" border="0" class="ledger">{r_html}</table>')
            _led_note = ('<div style="font-size:11px;color:#6B7280;line-height:1.5;margin-top:4px;">'
                         'Corporate investment flows — separate from the $350B pledge. '
                         'MOU/LOI entries are non-binding; figures as reported, not summed.</div>')
            standing.append(f'<div style="margin-top:18px;">'
                           f'{_pillar_h("Bilateral Investment Ledger", accent=NAVY)}{blocks}{_led_note}</div>')

        # ── Pillar 3: New This Week (genuinely new deals only) ─────────────
        new_rows = ""
        for deal in deal_list:
            headline = _esc(deal.get("headline", ""))
            if not headline:
                continue
            value = _esc(deal.get("value", "")) if deal.get("value") else ""
            detail = _esc(deal.get("detail", ""))
            src2 = _esc(deal.get("source", ""))
            parties = _esc(deal.get("parties", ""))
            url = deal.get("url", "")
            val_badge = (f'<span style="display:inline-block;font-family:{MONO};font-size:11px;font-weight:700;'
                         f'color:#fff;background:{UP_GREEN};border-radius:3px;padding:1px 6px;margin-left:6px;">{value}</span>') if value else ""
            kind = ('<span style="display:inline-block;font-family:' + MONO + ';font-size:10px;font-weight:700;'
                    'letter-spacing:0.5px;padding:1px 6px;border-radius:3px;background:#E4EFE7;color:#2E7D4F;margin-left:6px;">New deal</span>')
            meta = " &middot; ".join(b for b in (parties, src2) if b)
            new_rows += (f'<tr><td style="padding:9px 0;border-top:1px solid #EAEDF1;">'
                         f'<div style="font-size:13px;font-weight:700;color:{INK};line-height:1.35;">{_link_or_text(headline, url, style="color:" + INK + ";text-decoration:none;")}{val_badge}{kind}</div>'
                         + (f'<div style="font-size:13px;font-family:Georgia,serif;color:#4A5260;line-height:1.45;margin-top:2px;">{detail}</div>' if detail else "")
                         + (f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:#6B7280;margin-top:2px;">{meta}</div>' if meta else "")
                         + '</td></tr>')
        if new_rows:
            pillars.append(f'<div style="margin-top:18px;">{_pillar_h("New This Week")}'
                           f'<table width="100%" cellpadding="0" cellspacing="0" border="0">{new_rows}</table></div>')

        # ── Pillar 4: Trade Policy Watch (STANDING background — not new) ────
        # Ongoing non-tariff US measures affecting Korea, carried forward as
        # reference and clearly framed as standing status (not weekly news).
        # Expired / resolved / lapsed measures are dropped.
        _pol_colors = {"ACTIVE": TAEGUK_RED, "PENDING": "#7F8C8D", "RISK": TAEGUK_RED, "MONITOR": TAEGUK_BLUE}
        pol_rows = ""
        for tr in trade_policy:
            item_text = _esc(tr.get("item", ""))
            if not item_text:
                continue
            st = str(tr.get("status", "MONITOR") or "").upper().strip()
            if st == "ESCALATION":
                st = "ACTIVE"
            detail_raw = str(tr.get("detail", "") or "")
            # Editorial rule: drop anything that has ended.
            if st in ("EXPIRED", "RESOLVED", "LAPSED", "CONCLUDED", "TERMINATED") \
               or _re.search(r"\b(expired|lapsed|concluded|terminated|no longer in effect)\b", detail_raw, _re.I):
                continue
            detail_text = _esc(detail_raw)
            agency = _esc(tr.get("agency", ""))
            item_url = tr.get("url", "")
            st_color = _pol_colors.get(st, "#7F8C8D")
            head = _link_or_text(item_text, item_url, style="color:" + INK + ";text-decoration:none;")
            status_span = f'<span style="font-family:{MONO};color:{st_color};font-weight:700;">{_esc(st)}</span>'
            meta = " &middot; ".join(b for b in (agency, status_span) if b)
            pol_rows += (f'<tr><td style="padding:8px 0;border-top:1px solid #EAEDF1;">'
                         f'<div style="font-size:13px;font-weight:600;color:{INK};line-height:1.35;">{head}</div>'
                         + (f'<div style="font-size:12px;font-family:Georgia,serif;color:#4A5260;line-height:1.45;margin-top:2px;">{detail_text}</div>' if detail_text else "")
                         + (f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:#6B7280;margin-top:2px;">{meta}</div>' if meta else "")
                         + '</td></tr>')
        if pol_rows:
            standing.append(f'<div style="margin-top:18px;">{_pillar_h("Trade Policy Watch", accent="#5A6472")}'
                           f'<div style="font-size:11px;color:#6B7280;line-height:1.5;margin:-4px 0 8px;">'
                           f'Standing US non-tariff measures affecting Korea &mdash; ongoing status, not new this week.</div>'
                           f'<table width="100%" cellpadding="0" cellspacing="0" border="0">{pol_rows}</table></div>')

        # The pledge tracker, bilateral ledger and standing policy watch move
        # at monthly cadence at best. Carrying them daily made this the longest
        # section in the brief by double and buried the tariff status, which is
        # the part that actually changes. They are published to a standing page
        # instead, linked from here and rebuilt on every run.
        _standing_link = ""
        if standing and web_url:
            _b = web_url[:-len("latest.html")] if web_url.endswith("latest.html") else ""
            if _b:
                # This was a grey sentence ending in a link, so the only route
                # to the ledger, the pledge tracker and the standing measures
                # read as a footnote and went unseen. It is a panel now, and it
                # says what is on the other side.
                _standing_link = (
                    f'<div style="margin-top:16px;padding-top:14px;border-top:1px solid #E4E7EB;">'
                    f'<a href="{_esc(_b + "trade.html")}" style="display:block;'
                    f'padding:12px 14px;background:#EEF3F9;border-left:3px solid {TAEGUK_BLUE};'
                    f'border-radius:3px;text-decoration:none;">'
                    f'<span style="font-family:Arial,sans-serif;font-size:10px;font-weight:700;'
                    f'letter-spacing:1.5px;text-transform:uppercase;color:{TAEGUK_BLUE};">'
                    f'Full trade reference &#8594;</span>'
                    f'<span style="display:block;font-family:Georgia,serif;font-size:13px;'
                    f'color:{INK};margin-top:4px;line-height:1.45;">Investment ledger, pledge '
                    f'tracker and standing policy measures. Rebuilt every run.</span></a></div>')
        digest["_trade_standing_html"] = "".join(standing)
        sections.append(f"""
        <div {_SEC}>
          <a name="trade"></a>{_sec_label("US-Korea Trade &amp; Investment")}
          {sop_html}
          {"".join(pillars)}
          {_standing_link}
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
                    f'<span style="display:inline-block;padding:1px 5px;border-radius:3px;font-size:10px;background:#E8E8E8;font-family:Georgia,serif;color:#4A5260;margin-right:3px;">{_esc(c)}</span>'
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
                reaction_badge = f'<span style="display:inline-block;padding:1px 5px;border-radius:3px;font-size:10px;font-weight:600;color:#fff;background:#5A6472;margin-left:6px;">{badge_label}</span>'
            # "Trilateral · Trilateral" when the region tag and category coincide.
            region_txt = _esc(region) + " &middot; " if region and region.lower() != cat_raw.lower() else ""
            nea_html += _item_block(cat=f"{region_txt}{cat}{reaction_badge}", src=src,
                                    headline=headline, body=body, url=url, bar_color=bar_color)
        sections.append(f"""
        <div {_SEC}>
          <a name="nea"></a>{_sec_label("Northeast Asia Watch")}
          {nea_html}
        </div>
        """)

    # ── 12c. Public Sentiment Tracker ──────────────────────────────────
    sentiment = digest.get("public_sentiment") or {}
    if sentiment and any(sentiment.values()):
        def _trend_mark(trend):
            if trend == "up":
                return f' <span style="font-size:18px;color:{UP_GREEN};vertical-align:middle;">&#9650;</span>'
            if trend == "down":
                return f' <span style="font-size:18px;color:{DOWN_RED};vertical-align:middle;">&#9660;</span>'
            return ""

        def _party_short(data, fallback):
            """The party's short English name, from the model when it sent one."""
            name = str((data or {}).get("party") or "").strip()
            for suffix in (" Party", "의 힘"):
                if name.endswith(suffix):
                    name = name[: -len(suffix)].strip()
            return name or fallback

        def _tile(label, sub, data):
            """Compact party tile: role on top, party name under it."""
            has = bool(data and data.get("value") and str(data.get("value")).strip().lower() not in ("none", ""))
            val = _esc(str(data.get("value"))) if has else "--"
            colour = INK if has else "#9AA3AE"
            # The line is always emitted so the three numbers sit on one baseline
            # whether or not a tile has a Korean name to show.
            # Always emitted so the three figures share a baseline whether or
            # not a tile has a party name under it.
            kr_html = (f'<div style="font-size:11px;line-height:1.4;color:#6B7280;'
                       f'font-family:Arial,sans-serif;">{_esc(str(sub)) if sub else "&nbsp;"}</div>')
            return f"""
                    <td width="33%" valign="top" align="center" style="padding:2px 4px;">
                      <div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#6B7280;font-family:Arial,sans-serif;white-space:nowrap;">{label}</div>
                      {kr_html}
                      <div style="font-family:Georgia,serif;font-size:22px;font-weight:700;color:{colour};margin-top:6px;line-height:1;">{val}{_trend_mark(data.get("trend") if has else None)}</div>
                    </td>"""

        approval = sentiment.get("presidential_approval") or {}
        party_ruling = sentiment.get("party_ruling") or {}
        party_opp = sentiment.get("party_opposition") or {}
        party_ind = sentiment.get("party_independent") or {}
        discourse = sentiment.get("discourse_flag")

        discourse_html = ""
        if discourse:
            discourse_html = f"""
            <div class="sentiment-discourse" style="margin-top:8px;padding:6px 10px;background:#FBF0F1;border-radius:3px;border-left:3px solid {TAEGUK_RED};font-size:11px;font-family:Georgia,serif;color:#4A5260;">
              <strong style="color:{TAEGUK_RED};">Discourse:</strong> {_esc(discourse)}
            </div>"""

        gallup_finding = sentiment.get("gallup_spotlight")
        spotlight_html = ""
        if gallup_finding:
            topic = _esc(str(gallup_finding.get("topic", "")))
            finding = _esc(str(gallup_finding.get("finding", "")))
            poll_date = _esc(str(gallup_finding.get("poll_date", "")))
            spotlight_html = f"""
            <div class="sentiment-spotlight" style="margin-top:10px;padding:8px 12px;background:#F0F5FB;border-radius:3px;border-left:3px solid {TAEGUK_BLUE};font-size:11px;font-family:Georgia,serif;color:#4A5260;line-height:1.5;">
              <strong style="color:{TAEGUK_BLUE};">Gallup Korea Spotlight</strong>
              <span style="font-family:{MONO};font-size:10px;color:#5A6472;margin-left:6px;">{poll_date}</span><br>
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
            <div style="margin-top:8px;font-size:10px;color:#6B7280;text-align:center;">
              Data from {_esc(poll_updated)} — newer polling may be available
            </div>"""
            except Exception:
                pass

        # Approval sparkline. Renders only once poll_history holds at least
        # three surveys; a bare number says nothing about direction.
        try:
            from poll_history import sparkline_html as _spark
            _spark_html = _spark(color=TAEGUK_BLUE)
        except Exception:
            _spark_html = ""
        sections.append(f"""
        <div {_SEC}>
          <a name="sentiment"></a>{_sec_label("Public Sentiment")}
          <table width="100%" cellpadding="0" cellspacing="0" border="0" class="sentiment-table">
            <tr>
              <td width="42%" valign="top" style="padding:4px 18px 4px 0;border-right:1px solid #E4E7EB;">
                <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#6B7280;font-family:Arial,sans-serif;">Presidential approval</div>
                <div class="hero-num" style="font-family:Georgia,serif;font-size:42px;font-weight:700;color:{TAEGUK_BLUE};line-height:1.05;margin-top:4px;">{_esc(str(approval.get("value") or "--"))}{_trend_mark(approval.get("trend"))}</div>
                <div style="font-size:11px;color:#6B7280;font-family:Arial,sans-serif;margin-top:5px;">{_esc(str(approval.get("source") or ""))}{" &middot; " + _esc(str(approval.get("last_updated") or "")) if approval.get("last_updated") else ""}</div>
                {"<div style='margin-top:9px;'>" + _spark_html + "</div>" if _spark_html else ""}
              </td>
              <td valign="top" style="padding:4px 0 4px 18px;">
                <table width="100%" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    {_tile("Ruling", _party_short(party_ruling, "Democratic"), party_ruling)}
                    {_tile("Opposition", _party_short(party_opp, "People Power"), party_opp)}
                    {_tile("Independents", "", party_ind)}
                  </tr>
                </table>
              </td>
            </tr>
          </table>
          {stale_html}
          {spotlight_html}
          {discourse_html}
        </div>
        """)

    # ── 12d. Upcoming (promoted out of ROK Government — the forward look
    #         is what readers act on and should not sit inside a ministry
    #         roundup). Same data key, its own section, before The Wire. ──
    if calendar_watch:
        up_rows = ""
        for cal in calendar_watch:
            up_rows += f"""
            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-bottom:1px solid #E8E8E8;">
              <tr>
                <td width="54" style="padding:9px 12px 9px 0;vertical-align:top;">
                  <table cellpadding="0" cellspacing="0" border="0" style="background:{TAEGUK_BLUE};">
                    <tr><td align="center" style="padding:4px 0 5px;width:46px;">
                      <div style="font-family:Arial,sans-serif;font-size:10px;font-weight:700;letter-spacing:1.5px;color:rgba(255,255,255,0.82);">{_esc(cal.get("month", ""))}</div>
                      <div style="font-family:Georgia,serif;font-size:19px;font-weight:700;color:#fff;line-height:1;">{_esc(str(cal.get("day", "")))}</div>
                    </td></tr>
                  </table>
                </td>
                <td style="padding:9px 0;vertical-align:top;">
                  <div style="font-family:Georgia,serif;font-size:15px;font-weight:700;color:#1B2A4A;">{_esc(cal.get("headline", ""))}</div>
                  <div style="font-family:Georgia,serif;font-size:13px;line-height:1.45;color:#4A5260;margin-top:3px;">{_esc(cal.get("detail", ""))}</div>
                </td>
              </tr>
            </table>"""
        sections.append(f"""
        <div {_SEC}>
          <a name="upcoming"></a>{_sec_label("Upcoming")}
          {up_rows}
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
    x_posts = digest.get("official_x_posts") or []
    if social or opeds or academic or x_posts:
        sa_html = ""
        # Officials on X — direct posts by tracked official accounts (attributed
        # to the account, which is the primary source for its own statement).
        if x_posts:
            xp_html = ""
            for xp in x_posts:
                if not isinstance(xp, dict):
                    continue
                # Tolerate both key conventions: the model often emits these
                # using the social_statements shape (who/quote_text/handle_context)
                # instead of the official_x_posts shape (name/post/handle).
                name = _esc(str(xp.get("name") or xp.get("who") or ""))
                handle_raw = str(xp.get("handle") or "").strip()
                if not handle_raw:
                    m = _re.search(r"@([A-Za-z0-9_]+)", str(xp.get("handle_context") or ""))
                    handle_raw = m.group(1) if m else ""
                handle = _esc(handle_raw.lstrip("@"))
                post = _esc(str(xp.get("post") or xp.get("quote_text") or ""))
                note = _esc(str(xp.get("analyst_note") or "").strip())
                if not post:
                    continue
                url = xp.get("url", "")
                link = (f'<a href="{_esc(url)}" style="font-size:10px;color:{TAEGUK_BLUE};text-decoration:none;">View on X &#8594;</a>'
                        if url and str(url).startswith("http") else "")
                xp_html += (f'<div style="margin-bottom:9px;padding-bottom:9px;border-bottom:1px solid #E1E8F0;">'
                            f'<div style="font-size:12px;font-weight:600;color:{INK};">{name}'
                            + (f' <span style="color:#55607A;font-weight:400;">@{handle}</span>' if handle else "")
                            + f'</div>'
                            f'<div style="font-size:13px;font-family:Georgia,serif;color:#2C3E50;line-height:1.45;margin:2px 0 3px;">&ldquo;{post}&rdquo;</div>'
                            + (f'<div style="font-size:11px;color:{TAEGUK_BLUE};line-height:1.4;margin-bottom:3px;"><strong>Context:</strong> {note}</div>' if note else "")
                            + f'{link}</div>')
            if xp_html:
                sa_html += (f'<div style="margin-bottom:14px;padding:12px 14px;background:#EEF3F9;'
                            f'border-radius:6px;border-left:3px solid {TAEGUK_BLUE};">'
                            f'<div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;'
                            f'color:{TAEGUK_BLUE};margin-bottom:9px;">Officials on X</div>'
                            f'{xp_html}'
                            f'<div style="font-size:10px;color:#55607A;line-height:1.4;margin-top:2px;">'
                            f'Direct posts by tracked official accounts, attributed as posted. Not independently verified beyond the post.</div>'
                            f'</div>')
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
                    <div style="font-size:10px;color:#6B7280;">{handle}</div>
                  </td>
                </tr>
              </table>
              <p style="margin:0 0 6px 0;font-size:13px;line-height:1.5;font-family:Georgia,serif;color:#4A5260;font-style:italic;">&ldquo;{quote}&rdquo;</p>
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
              <div style="font-size:11px;color:#6B7280;">{src}</div>
              <div style="font-size:13px;font-weight:600;color:{INK};">
                {_link_or_text(title, url)}
              </div>
              <div style="font-size:12px;line-height:1.4;font-family:Georgia,serif;color:#4A5260;">{summary}</div>
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
              <div style="font-size:11px;color:#6B7280;">{src} &middot; {tier}</div>
              {title_html}
              <div style="font-size:12px;line-height:1.4;font-family:Georgia,serif;color:#4A5260;">{summary}</div>
              {"<div style='font-size:11px;color:" + TAEGUK_BLUE + ";margin-top:3px;'><strong>Implication:</strong> " + implication + "</div>" if implication else ""}
              {read_link}
            </div>"""
        if sa_html.strip():
            sections.append(f"""
        <div {_SEC}>
          <a name="analysis"></a>{_sec_label("Analysis")}
          {sa_html}
        </div>
        """)

    # ── 14b. Satellite & Location Watch (moved to end — slow-moving section) ─
    locations = digest.get("bp_locations") or []
    imagery_report = digest.get("imagery_report") or {}
    if locations or imagery_report:
        # Featured imagery report (e.g., AEI / 38North analysis)
        img_report_html = ""
        # Only render the block when it carries actual reporting. A payload with
        # a label but no headline or body produced a bare "· — NEW IMAGERY
        # REPORTS" heading with nothing under it.
        if imagery_report and (imagery_report.get("headline")
                               or imagery_report.get("body")
                               or imagery_report.get("summary")):
            ir_source = _esc(imagery_report.get("source", ""))
            ir_date = _esc(imagery_report.get("date", ""))
            ir_label = _esc(imagery_report.get("label", "New imagery reports"))
            ir_headline = _esc(imagery_report.get("headline", ""))
            ir_body = _esc(imagery_report.get("body") or imagery_report.get("summary", ""))
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
                            _src_parts.append(f'<a href="{_esc(s_url)}" style="font-size:11px;font-family:monospace;color:#6B7280;text-decoration:none;">{s_label} ↗</a>')
                        else:
                            _src_parts.append(f'<span style="font-size:11px;font-family:monospace;color:#6B7280;">{s_label} ↗</span>')
                    else:
                        _src_parts.append(f'<span style="font-size:11px;font-family:monospace;color:#6B7280;">{_esc(str(s))} ↗</span>')
                source_links_html = "<div style='margin-top:8px;'>" + " &middot; ".join(_src_parts) + "</div>"
            bp_ids_html = ""
            if ir_bp_ids:
                bp_ids_html = "<div style='margin-top:6px;font-size:11px;color:#6B7280;'>→ " + " · ".join(_esc(str(b)) for b in ir_bp_ids) + "</div>"
            img_report_html = f"""
            <div style="margin-bottom:20px;padding:16px;border-left:3px solid {TAEGUK_BLUE};">
              <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:{TAEGUK_BLUE};font-weight:600;margin-bottom:6px;">{ir_source} · {ir_date} — {ir_label}</div>
              <div style="font-size:17px;font-weight:700;color:{INK};line-height:1.3;margin-bottom:8px;">{ir_headline}</div>
              <div style="font-size:13px;line-height:1.6;font-family:Georgia,serif;color:#4A5260;">{ir_body}</div>
              {bp_ids_html}
              {source_links_html}
            </div>"""

        # Split the watch list by recency. Every site carrying a status the
        # model set months ago reads as current, so eleven amber cards said
        # nothing: on 8 Sep 2026 all eleven were >60 days stale and ten of
        # eleven were non-normal. Show only what has been reported on
        # recently; name the rest honestly in one line.
        _FRESH_DAYS = 30

        def _age_days(loc):
            m = _re.match(r"(\d{4})-(\d{2})(?:-(\d{2}))?",
                          str(loc.get("last_source_date", "")).strip())
            if not m:
                return None
            try:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3) or 1)
                from datetime import date
                return (date.today() - date(y, mo, d)).days
            except ValueError:
                return None

        _fresh, _quiet = [], []
        for _loc in locations:
            _age = _age_days(_loc)
            if _age is not None and _age <= _FRESH_DAYS:
                _fresh.append(_loc)
            else:
                _quiet.append(_loc)
        # Never render an empty section: if nothing is fresh, show whatever is
        # newest so the reader still sees the watch list.
        if not _fresh and locations:
            _dated = [(l, _age_days(l)) for l in locations]
            _dated = [(l, a) for l, a in _dated if a is not None]
            if _dated:
                _dated.sort(key=lambda t: t[1])
                _fresh = [_dated[0][0]]
                _quiet = [l for l in locations if l is not _fresh[0]]
        quiet_html = ""
        if _quiet:
            _oldest = ""
            _dates = sorted(str(l.get("last_source_date", ""))[:7]
                            for l in _quiet if l.get("last_source_date"))
            if _dates:
                _oldest = f" &middot; oldest report {_esc(_dates[0])}"
            quiet_html = (f'<div style="font-size:11px;color:#6B7280;margin-top:10px;'
                          f'padding-top:9px;border-top:1px solid #EAEAEA;">'
                          f'{len(_quiet)} other monitored site{"s" if len(_quiet) != 1 else ""}: '
                          f'no new imagery in the last {_FRESH_DAYS} days{_oldest}.</div>')
        locations = _fresh

        # BP Monitored Locations — 2-column card grid with status context
        _badge_styles = {
            "normal": ("#7F8C8D", "#F5F6F7", "MONITORING"),
            "activity": ("#7F8C8D", "#F5F6F7", "MONITORING"),
            "elevated": (TAEGUK_RED, "#FBF0F1", "ELEVATED"),
            "alert": (TAEGUK_RED, "#FBE9EA", "ALERT"),
        }
        # Count against the full watch list, not the freshness-filtered view —
        # "1 of 1 sites at elevated status" was true of the filtered set and
        # meaningless to a reader.
        _all_locs = _fresh + _quiet
        elevated_count = sum(1 for l in _all_locs
                             if l.get("status", "normal") in ("elevated", "alert"))
        summary_html = ""
        if elevated_count:
            summary_html = f'<div style="font-size:11px;color:#6B7280;margin-top:6px;margin-bottom:12px;">{elevated_count} of {len(_all_locs)} sites at elevated or alert status</div>'
        else:
            summary_html = f'<div style="font-size:11px;color:#6B7280;margin-top:6px;margin-bottom:12px;">{len(_all_locs)} monitored sites</div>'

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
                    note_html = f'<div style="font-size:11px;line-height:1.4;color:#6B7280;margin-top:4px;font-style:italic;">{note}</div>'
                elif note:
                    note_html = f'<div style="font-size:11px;line-height:1.4;font-family:Georgia,serif;color:#4A5260;margin-top:4px;">{note}</div>'
                # Last report date — mono, machine-measured. Flag notes whose
                # last source is stale (>90 days) so a months-old status isn't
                # read as current (e.g. Yellow Sea PMZ carried from January).
                stale_flag = ""
                _dm = _re.match(r"(\d{4})-(\d{2})(?:-(\d{2}))?", str(loc.get("last_source_date", "")).strip())
                if _dm:
                    try:
                        from datetime import date as _date
                        _src = _date(int(_dm.group(1)), int(_dm.group(2)), int(_dm.group(3) or 1))
                        _age = (datetime.now(timezone.utc).date() - _src).days
                        if _age > 90:
                            stale_flag = (f' <span style="color:#B26A00;">&middot; no recent reporting '
                                          f'(~{_age // 30} mo)</span>')
                    except (ValueError, TypeError):
                        pass
                last_html = (f'<div style="font-family:{MONO};font-size:11px;color:#6B7280;margin-top:4px;">'
                             f'as of {last_source_date}{stale_flag}</div>'
                             if last_source_date and last_source_date != "unknown" else "")
                row_cards += f"""
                <td style="width:50%;padding:4px;vertical-align:top;">
                  <div style="background:{b_bg};border-radius:3px;padding:10px 12px;border-left:3px solid {b_color};">
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
          {quiet_html}
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
    otd_block = ""
    if on_this_day:
        otd_block = f"""
      <tr><td style="padding:20px 32px 8px;">
        <div style="font-family:Arial,sans-serif;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:2px;color:{BLUE_ON_NAVY};padding-bottom:7px;margin-bottom:11px;border-bottom:1px solid rgba(255,255,255,0.18);">On This Day</div>
        <div style="font-family:Georgia,serif;font-size:14px;line-height:1.55;color:rgba(255,255,255,0.88);"><strong style="color:{BLUE_ON_NAVY};">{otd_date}</strong> &nbsp; {otd_event}</div>
        {"<div style='font-family:Georgia,serif;font-size:13px;color:rgba(255,255,255,0.6);font-style:italic;margin-top:5px;'>" + otd_rel + "</div>" if otd_rel else ""}
      </td></tr>"""
    sections.append(f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{NAVY};border-top:3px solid {BAND};" class="sec footer">
      {otd_block}
      <tr><td style="padding:18px 32px 6px;text-align:center;">
        <!-- CSIS Korea Chair lockup, built in HTML rather than as an image:
             mail clients block images by default, and a blocked logo is a
             broken logo. This always renders, scales, and stays legible in
             dark mode. -->
        <table class="lockup" cellpadding="0" cellspacing="0" border="0" align="center" style="margin:0 auto;"><tr>
          <td style="padding-right:12px;font-family:Georgia,'Times New Roman',serif;font-size:26px;letter-spacing:2px;color:#FFFFFF;line-height:1;">CSIS</td>
          <td style="border-left:1px solid rgba(255,255,255,0.45);padding:2px 12px;font-family:Arial,sans-serif;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:rgba(255,255,255,0.82);line-height:1.35;text-align:left;">Geopolitics and Foreign<br>Policy Department</td>
          <td style="border-left:1px solid rgba(255,255,255,0.45);padding:2px 0 2px 12px;font-family:Arial,sans-serif;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:rgba(255,255,255,0.82);line-height:1.35;text-align:left;">Korea<br>Chair</td>
        </tr></table>
        <div style="font-family:Georgia,serif;font-size:13px;color:rgba(255,255,255,0.62);margin-top:12px;">Center for Strategic and International Studies &middot; Washington, DC</div>
        <div style="margin-top:11px;font-family:Arial,sans-serif;font-size:11px;letter-spacing:0.5px;">
          <a href="{_esc(web_url)}" style="color:{BLUE_ON_NAVY};text-decoration:none;">Read online</a> &nbsp;&middot;&nbsp;
          <a href="{_esc(archive_url)}" style="color:{BLUE_ON_NAVY};text-decoration:none;">Past issues</a>{_footer_trade}
        </div>
      </td></tr>
      <tr><td style="padding:12px 32px 10px;">
        <div style="border-top:1px solid rgba(255,255,255,0.14);padding-top:12px;text-align:left;font-family:Georgia,serif;font-size:12px;line-height:1.6;color:rgba(255,255,255,0.52);">
          This newsletter is automatically generated, so it may contain errors. Please check all information and sources before citing.
          To report errors or other issues, please contact Andy Lim at <a href="mailto:alim@csis.org" style="color:rgba(255,255,255,0.78);">alim@csis.org</a>.
        </div>
      </td></tr>
      <tr><td style="padding:0 32px 18px;text-align:left;">
        <div style="font-family:{MONO};font-size:10px;color:rgba(255,255,255,0.38);margin-bottom:9px;">{_issue_meta}generated {gen_time}</div>
        <a href="#top" style="font-family:Arial,sans-serif;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:{BLUE_ON_NAVY};text-decoration:none;">&#8593; Back to top</a>
      </td></tr>
    </table>
    """)

    # Resolve the navigation placeholder now that every section is known. At a
    # 1,600-2,000 word target the brief is too long to scan end to end and the
    # only link was "back to top". A quiet day that drops sections simply gets
    # fewer links, and fewer than four suppresses the row entirely.
    _NAV = [("Top Stories", "overnight"), ("Pyongyang", "kcna"),
            ("Trade", "trade"), ("Markets", "business"),
            ("Polling", "sentiment"), ("Upcoming", "upcoming"),
            ("Analysis", "analysis"), ("Satellite", "satellite")]
    body = "\n".join(sections)
    _links = [f'<a href="#{_a}" style="color:{TAEGUK_BLUE};text-decoration:none;white-space:nowrap;">{_l}</a>'
              for _l, _a in _NAV if f'a name="{_a}"' in body]
    _nav_html = ""
    if len(_links) >= 4:
        _nav_html = ('<div class="nav-row" style="background:#F7F8FA;border-bottom:1px solid #E4E7EB;'
                     'padding:8px 32px;text-align:center;font-family:Arial,sans-serif;'
                     'font-size:11px;line-height:1.9;color:#6B7280;" class="sec">'
                     + ' &nbsp;&middot;&nbsp; '.join(_links) + '</div>')
    body = body.replace("%%NAV%%", _nav_html)

    # Count what the body actually says, then stamp it into the masthead.
    word_count = _count_rendered_words(body)
    read_min = max(1, round(word_count / 250))
    body = (body.replace("%%WORDS%%", f"{word_count:,}")
                .replace("%%READMIN%%", str(read_min)))
    digest["_word_count"] = word_count      # run.py's floor check reads this

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
    /* Print — keep FULL colors and the exact on-screen look; only drop page
       chrome (shadow, page margins). print-color-adjust forces browsers to
       print background colors instead of stripping them. Works when printing
       the archived web page or the email via the browser's Print / Save as PDF. */
    @page {{ margin: 12mm; }}
    @media print {{
      * {{ -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; color-adjust: exact !important; }}
      html, body {{ background:#FFFFFF !important; }}
      .wrapper {{ box-shadow:none !important; width:680px !important; max-width:680px !important; margin:0 auto !important; }}
      a {{ text-decoration:none !important; }}
      /* Let everything flow across page breaks — avoiding breaks pushes content
         that doesn't fit to the next page, leaving big empty gaps. */
      * {{ page-break-inside: auto !important; }}
    }}
    /* Mobile responsive — one declaration per pattern; no duplicates.
       Fixes from the Q3 2026 mobile audit are marked (A#). */
    @media only screen and (max-width: 620px) {{
      /* Notice and links will not sit side by side on a phone.
         No width:100% here: a table cell set to display:block already fills
         its row, and 100% plus horizontal padding is measured content-box,
         which pushed the whole document 28px wider than the screen and gave
         every section a horizontal scrollbar. */
      .util-row .util-cell {{ display:block !important; text-align:center !important;
        padding:5px 8px !important; white-space:normal !important; }}
      .flash-table td {{ display:block !important; width:100% !important;
        border-bottom:0 !important; padding:2px 0 !important; }}
      .flash-table tr {{ display:block !important; padding:6px 0 !important;
        border-bottom:1px solid #EEF0F3 !important; }}
      .util-row .util-cell a {{ padding:4px 7px !important; margin:1px !important;
        font-size:11px !important; letter-spacing:0.3px !important; }}
      .wrapper {{ width:100% !important; }}
      /* The metadata line is nowrap, so sitting beside the title it set a
         211px floor on the masthead row. A table cannot shrink below the
         min-content width of its cells, so the whole 680px wrapper stopped at
         about 325px and every section inherited that floor: the brief scrolled
         sideways on a 320px screen. Stacked under the date it wraps freely. */
      .mast-meta {{ display:block !important; text-align:left !important;
        padding-top:8px !important; }}
      .mast-meta div {{ white-space:normal !important; }}
      /* The CSIS lockup is three cells side by side with rules between them.
         Its min-content width is 293px, which with the footer padding put a
         325px floor under the whole table — the last thing still forcing a
         320px screen to scroll sideways. Stacked and centred it costs three
         short lines and fits any screen. */
      .lockup td {{ display:block !important; border-left:0 !important;
        text-align:center !important; padding:3px 0 !important; }}
      /* Public Sentiment put the approval hero and three party tiles in one
         row. On a phone that left each tile 72px, so "RULING PARTY" and
         "OPPOSITION" ran into each other. Hero above, tiles below, each tile
         then has about 114px and the labels sit clear. */
      .sentiment-table > tbody > tr > td {{ display:block !important;
        width:100% !important; border-right:0 !important;
        padding:0 0 12px 0 !important; }}
      .sentiment-table > tbody > tr > td + td {{ padding:12px 0 0 0 !important;
        border-top:1px solid #E4E7EB !important; }}
      /* 9px labels are too small to read on a phone. */
      .cal-table div[style*="font-size:10px"], .lockup td {{ font-size:10px !important; }}
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
      /* Party tiles, three across under the approval hero. This rule dates
         from the old four-equal-column layout and still said 47%, which put
         two tiles on one line and orphaned the third. The outer cells are
         handled by the stacking rule above, whose selector is more specific. */
      .sentiment-table table td {{ display:inline-block !important; width:32% !important;
        box-sizing:border-box !important; padding:8px 2px !important; text-align:center !important; }}
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
{_DARK_CSS}
  </style>
  <!--[if mso]>
  <style type="text/css">
    table {{ border-collapse:collapse; }}
    .wrapper {{ width:680px; }}
  </style>
  <![endif]-->
</head>
<body style="margin:0;padding:0;background:#F2F3F5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
  <!-- Centered fixed-width TABLE wrapper (not a max-width div): survives when
       a client strips the <style> block on forward/reply, so the layout keeps
       its shape. The .wrapper class lets the mobile media query flex it to
       100% while the <style> block is present. -->
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0;padding:0;background:#F2F3F5;">
    <tr>
      <td align="center" valign="top" style="padding:0;">
        <!--[if mso]><table width="680" cellpadding="0" cellspacing="0" border="0" align="center"><tr><td><![endif]-->
        <table role="presentation" class="wrapper" width="680" cellpadding="0" cellspacing="0" border="0" align="center" style="width:680px;max-width:680px;margin:0 auto;background:#FFFFFF;font-family:Arial,Helvetica,sans-serif;box-shadow:0 2px 20px rgba(0,0,0,0.08);">
          <tr>
            <td style="padding:0;">
              {body}
            </td>
          </tr>
        </table>
        <!--[if mso]></td></tr></table><![endif]-->
      </td>
    </tr>
  </table>
</body>
</html>"""


if __name__ == "__main__":
    import json
    from pathlib import Path
    digest = json.loads(Path("digest.json").read_text())
    html = render(digest)
    Path("latest.html").write_text(html, encoding="utf-8")
    print(f"Rendered {len(html):,} bytes -> latest.html")
