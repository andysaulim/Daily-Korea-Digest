"""
Korea Daily Brief — HTML Renderer
CSIS Korea Chair
Takes structured digest JSON from Claude and renders a styled HTML email.
Uses table-based layout for maximum email client compatibility.
"""
import re as _re
from datetime import datetime, timezone
from urllib.parse import urlparse as _urlparse

import links as _linkq


def _issue_file(digest: dict, base: str, ext: str) -> str:
    """This issue's own published file: digest_{date}.{ext} under base.

    "Read online" and "Download PDF" pointed at latest.html and latest.pdf,
    so an email opened a week later showed that day's brief, not its own. The
    archive publishes digest_{date}.html and .pdf for every issue; the date
    comes from run.py (date_slug), else from digest_date. Falls back to the
    latest file only when no date can be found.
    """
    slug = str(digest.get("date_slug") or "").strip()
    if not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", slug):
        slug = ""
        raw = str(digest.get("digest_date") or "").strip()
        for fmt in ("%A, %B %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
            try:
                slug = datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
    if not base:
        return ""
    return f"{base}digest_{slug}.{ext}" if slug else f"{base}latest.{ext}"


def _top_story_sources(story: dict) -> str:
    """The source line under a top story, HTML.

    When run.py found a link for each outlet the story names (source_links),
    each outlet is its own link. Otherwise the line is shown as written;
    run.py has already cut it to the outlet the headline actually opens, so
    it never names an outlet a reader cannot reach.
    """
    raw = str(story.get("src_line") or story.get("source") or "")
    sl = [l for l in (story.get("source_links") or [])
          if isinstance(l, dict) and str(l.get("url", "")).startswith("http") and l.get("label")]
    if len(sl) < 2:
        return _esc(_clean_src(raw))
    _, tail = _linkq.split_outlets(raw)
    # The outlet the headline already opens is named, not linked a second time.
    head = str(story.get("url") or "")
    parts = [_esc(str(l["label"])) if l["url"] == head else
             f'<a href="{_esc(l["url"])}" style="color:#6B7280;text-decoration:underline;'
             f'text-decoration-color:#C9D1DC;">{_esc(str(l["label"]))}</a>' for l in sl]
    return " / ".join(parts) + (f", {_esc(tail)}" if tail else "")


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
    # Middle dots between outlets ("NK News · KCNA") read as machine-made
    # formatting; the linked form of the same line already uses a slash.
    cleaned = _re.sub(r'\s*\u00b7\s*', ' / ', cleaned)
    # Collapse multiple spaces
    cleaned = _re.sub(r'  +', ' ', cleaned)
    return cleaned if cleaned else raw


_HANGUL = _re.compile(r"[\u3131-\u318E\uAC00-\uD7A3]")


def _en_label(raw) -> str:
    """A label (committee, ministry, office) with its Korean name taken out.

    Korean belongs on the page only in a quote beside its translation. The
    model often adds the Korean name in brackets after the English one,
    "Education Committee (교육위원회)", and english.apply cleans only the
    source fields. Prose is not touched here.
    """
    s = str(raw or "")
    if not _HANGUL.search(s):
        return s

    def inner(m):
        keep = [p.strip() for p in m.group(1).split("/") if p.strip() and not _HANGUL.search(p)]
        return f" ({' / '.join(keep)})" if keep else ""
    s = _re.sub(r"\s*\(([^)]*)\)", lambda m: inner(m) if _HANGUL.search(m.group(1)) else m.group(0), s)
    s = _re.sub(r"[\u3131-\u318E\uAC00-\uD7A3][\u3131-\u318E\uAC00-\uD7A3\s]*", " ", s)
    return _re.sub(r"\s{2,}", " ", s).strip(" ,;/")


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
BODY_INK = "#353C48"      # running body copy




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
    "#353C48": "#C4C8CE",   # body copy
    "#55607A": "#C4C8CE",
    "#5A6472": "#C4C8CE",
    "#6B7280": "#9AA3AE",   # muted labels and meta
    "#CD2E3A": "#F08A94",   # alert red
    "#A93226": "#F08A94",   # semantic down
    "#2E7D4F": "#5FBF87",   # semantic up
    "#1E7940": "#5FBF87",   # positive chip type (New deal, binding, reduced)
    "#9A5B00": "#E0A64A",   # semantic caution
}

_DARK_BG = {
    "#E8E8E8": "#3A4048",   # tag chips (company names under business items)
    "#EDF3FB":  "#16233A",  # Stat of the Day, edition tint
    "#7E93B3":  "#55688A",  # poll sparkline, earlier readings
    "#fff":     "#262A30",  # cards
    "#FFFFFF":  "#262A30",
    "#F0F0F0":  "#2A2E34",
    "#F7F8FA":  "#1A1D22",  # utility bar
    "#F5F7FA":  "#22262C",  # table header rows
    "#EDF2FA":  "#1C2A3E",  # Today at a Glance
    "#F0F5FB":  "#16222F",  # Gallup spotlight
    "#FBF0F1":  "#2A1518",  # discourse flag
    "#FFFDF7":  "#2A2519",  # location card, elevated
    "#FFF8F8":  "#2A1B1C",  # location card, alert
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
    "#0B1626", "#B8C4D6",   # hybrid status line: already a dark strip in both modes
    "#fff", "#FFFFFF", "#8FA0B5", "#8FB6E8", "#7B90AC", "#E8697A",
    "#0047A0", "#0052B4", "#1B2A4A", "#051F3D", "#0A1E38", "#2E3644",
    "#EBEBEB", "#E4E7EB", "#E8E8E8", "#EEF0F3", "#D5DAE1", "#F2F3F5",
    "#5A6472",  # badge fill — legible in both schemes, needs no variant
    # The section-bar ring: already a lightened accent chosen to clear 4.5:1
    # on the black bar, and the bar is black in both schemes, so it needs no
    # dark variant of its own.
    "#167EFF",
    # The section bar and the footer are already black with white type, and
    # the pill buttons are dark type on a white fill. All read correctly in
    # either scheme, so none of them needs a dark variant.
    "#14181F",
    # Status-chip fills: a saturated ground with white type, readable either way.
    "#CD2E3A", "#2E7D4F", "#A93226", "#9A5B00",
    # The dark palette's own values, so re-scanning a dark rule is not a miss.
    "#E8E6E1", "#121212", "#1a1a1a", "#1E2126", "#262A30", "#04182F",
    "#16222F", "#1A1D22", "#2A1518", "#1C2A3E", "#22262C", "#2A1D15",
    "#16281C", "#2A2E34",
    "#F0F0F0",  # retired utility band; kept so an old copy still maps
    # The KCNA panel and the market strip are dark grounds in both schemes,
    # so their type and status dots are already light-on-dark.
    "#E0E0E0", "#E8E8E8", "#F0F0F0", "#C8D4E2", "#9FB3CC", "#A0AEC0", "#D8DEE8",
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
        "      .wrapper .sec { background:#1E2126 !important; border-bottom-color:#3A4048 !important; }",
        "      .wrapper .nav-row { background:#1A1D22 !important; border-bottom-color:#3A4048 !important; }",
        "      .wrapper h1, .wrapper h2, .wrapper h3 { color:#E8E6E1 !important; }",
        "      .wrapper .footer { background:#0B0E13 !important; }",
        "      .wrapper .footer-end { background:#1a1a1a !important; }",
        "      .wrapper .sec-bar { background:#0B0E13 !important; }",
        "      .wrapper .kcna-dark, .wrapper .kcna-dark table, .wrapper .kcna-dark > div { background:#0A1E38 !important; }",
        # Not the divs inside the ROK Government and Location Watch cards: the
        # card is the cell, and painting each line's div a shade lighter than
        # the cell striped every card in dark mode.
        "      .wrapper .item-card, .wrapper .story-card { background:#262A30 !important; border-color:#3A4048 !important; }",
        "      .wrapper .sentiment-spotlight { background:#16222F !important; }",
        "      .wrapper .item-row { border-bottom-color:#3A4048 !important; }",
        "      .wrapper .sentiment-discourse { background:#2A1518 !important; }",
        "      .wrapper .mkt-table td { border-color:rgba(255,255,255,0.08) !important; }",
        "      .wrapper .sentiment-table td, .wrapper .cal-table { border-color:#3A4048 !important; }",
        "      .wrapper td[style*=\"border-bottom:1px solid #E8E8E8\"], .wrapper table[style*=\"border-bottom:1px solid #E8E8E8\"] { border-color:#3A4048 !important; }",
    ]
    for light, dark in _DARK_TEXT.items():
        lines.append(f'      .wrapper [style*="color:{light}"] {{ color:{dark} !important; }}')
    for light, dark in _DARK_BG.items():
        lines.append(f'      .wrapper [style*="background:{light}"] {{ background-color:{dark} !important; }}')
    # Last, so it wins. The pill is dark type on a white fill; the generic
    # white-background mapping above darkens the fill and leaves the type
    # dark, which measures 1.23:1 — a button you cannot read. Equal
    # specificity, so order is the only thing that decides it.
    lines.append('      .wrapper .pill { background:#E8E6E1 !important; '
                 'color:#14181F !important; }')
    # The Listen bar is the same case: a white card with dark type, which the
    # generic mapping turned into dark type on a dark card (1.23:1). It keeps
    # a light card in dark mode, with its play button in the brand blue.
    lines.append('      .wrapper .listen-bar, .wrapper .listen-bar td { background:#E8E6E1 !important; }')
    lines.append('      .wrapper .listen-bar .listen-title, .wrapper .listen-bar .listen-len '
                 '{ color:#14181F !important; }')
    lines.append('      .wrapper .listen-bar .listen-sub { color:#3A4150 !important; }')
    lines.append('      .wrapper .listen-bar .listen-play { background:#0047A0 !important; '
                 'color:#FFFFFF !important; }')
    # The poll sparkline. Its bars are graphics, not text, so the contrast
    # check never looked at them and the chart was half-unreadable in each
    # mode: the active bar is navy, which measures 2.00 against the dark
    # ground, while the earlier readings are pale and vanish on white. The
    # light pair is set in poll_history; this is the dark one. 5.31 and 3.09.
    lines.append('      .wrapper .spark-bar[style*="background:#0047A0"] '
                 '{ background-color:#4D8FE8 !important; }')
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
        if hexv not in _DARK_TEXT and hexv not in _DARK_EXEMPT and hexv not in _V2_DARK_TEXT \
                and hexv not in _V2_DARK_EXEMPT:
            missing.append(f"text colour {hexv} has no dark mapping")
    for hexv in set(_re.findall(r"background:\s*(#[0-9A-Fa-f]{3,6})", body)):
        if hexv not in _DARK_BG and hexv not in _DARK_EXEMPT and hexv not in _V2_DARK_BG \
                and hexv not in _V2_DARK_EXEMPT:
            missing.append(f"background {hexv} has no dark mapping")
    return sorted(missing)


def _color_bar(css_class: str) -> str:
    # Only two states are worth signalling: ordinary and alert.
    return TAEGUK_RED if css_class in ("cb-red", "cb-nkch") else TAEGUK_BLUE


def _social_badge(badge_class: str) -> str:
    colors = {"sb-p": TAEGUK_BLUE, "sb-r": TAEGUK_RED, "sb-s": TAEGUK_BLUE}
    return colors.get(badge_class, TAEGUK_BLUE)


def _arrow(val) -> str:
    """Market strip delta — rendered on the navy data ground."""
    try:
        val = float(val)
    except (TypeError, ValueError):
        return '<span style="color:#9FB3CC;">—</span>'
    if val > 0:
        return f'<span style="color:#69C88E;">+{val:.1f}%</span>'
    elif val < 0:
        return f'<span style="color:#E8697A;">&minus;{abs(val):.1f}%</span>'
    return '<span style="color:#9FB3CC;">flat</span>'





def _link_or_text(text: str, url: str,
                  style: str = "color:#1B2A4A;text-decoration:underline;"
                               "text-decoration-color:#AEBBD0;text-decoration-thickness:1px;"
                               "text-underline-offset:4px;") -> str:
    """Render as <a> only if url is a real link, otherwise plain text.

    Underlined, in the navy the rest of the brief uses for links. The default
    used to be undecorated ink, so in the scan sections a headline that opened
    an article and one that did not looked identical, and nothing told a
    reader which lines were worth clicking. The line is a light blue-grey,
    one pixel, set below the descenders: still plainly a link, but no longer
    the heaviest mark on the page under a 20px serif headline. Clients that
    ignore decoration colour fall back to an ordinary underline.

    NOTE: `text` should already be HTML-escaped by the caller via _esc()."""
    if url and url != "#" and url.startswith("http"):
        return f'<a href="{_esc(url)}" style="{style}">{text}</a>'
    return text



def _emphasis(text: str) -> str:
    """Turn the model's **bold** and *italic* marks into tags, after escaping.

    Names and figures are what a reader scans a policy brief for, so the
    prompt asks for a person's name in **double asterisks** on first mention
    and a quantity in *single* ones. The model cannot emit HTML — every field
    goes through _esc() first — so this converts a narrow, fixed convention
    afterwards. Anything that is not one of these two exact shapes stays
    literal text, which is what keeps the escaping meaningful.
    """
    import re as _re
    text = _re.sub(r"\*\*(?!\s)([^*]{1,80}?)(?<!\s)\*\*",
                   r'<strong style="font-weight:700;">\1</strong>', text)
    text = _re.sub(r"(?<![*\w])\*(?!\s)([^*]{1,60}?)(?<!\s)\*(?![*\w])",
                   r"<em>\1</em>", text)
    return text

# ── Section padding helper (responsive via class) ────────────────────────
_SEC = 'style="padding:17px 32px;border-bottom:1px solid #EBEBEB;" class="sec"'


RING_ON_DARK = "#167EFF"   # the accent, lightened to read on the black bar

def _sec_label(label: str, color: str = RING_ON_DARK) -> str:
    """A section bar: black field, an accent ring, a white letterspaced label.

    The label used to be small coloured type over a hairline rule. In a
    2,000-word brief with a dozen sections that gave the reader no stop
    between them: the sections blurred into one another and a scan found no
    purchase. This is a hard stop.

    Black rather than each edition's own colour. Four editions with four
    coloured bars would read as decoration; black reads as structure, and the
    accent lands as one deliberate mark instead of a whole field. It is also
    the only colour that leaves the masthead as the single place a reader
    meets the edition's identity.

    Solid background and a text glyph, so it survives clients that block
    images and clients that drop background images.
    """
    if DESIGN == "v2":
        return _v2_bar(label)
    if SECTION_STYLE == "rule":
        _t = label.replace("&amp;", "&")
        _t = _t[:1].upper() + _t[1:].lower().replace("kcna", "KCNA").replace("rok", "ROK").replace("us-korea", "US-Korea").replace("& ", "&amp; ")
        return (f'<div class="sec-rule" style="border-top:3px solid #14181F;padding-top:8px;margin-bottom:12px;">'
                f'<span style="font-family:Georgia,serif;font-size:21px;font-weight:700;color:#14181F;">{_t}</span></div>')
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0" '
        'class="sec-bar" style="background:#14181F;margin-bottom:14px;">'
        '<tr><td style="padding:9px 14px;">'
        f'<span style="font-family:Arial,sans-serif;font-size:12px;color:{color};'
        'line-height:1;vertical-align:middle;margin-right:9px;">&#9679;</span>'
        '<span style="font-family:Arial,sans-serif;font-size:11px;font-weight:700;'
        'text-transform:uppercase;letter-spacing:2px;color:#FFFFFF;'
        f'vertical-align:middle;">{label}</span>'
        '</td></tr></table>')



def _subhead(text: str) -> str:
    """A group label inside a section.

    ROK Government already grouped its contents this way; Analysis and The
    Wire did not, which is why both read as undifferentiated streams.
    """
    if DESIGN == "v2":
        return _v2_subhead(text)
    return (f'<div style="font-family:Arial,sans-serif;font-size:11px;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:1.5px;color:#55607A;'
            f'margin:18px 0 9px;padding-bottom:5px;border-bottom:1px solid #E4E7EB;">'
            f'{text}</div>')


def _compact_row(cat: str, headline: str, url: str, src: str, body: str = "") -> str:
    """One wire item, in the same shape as every other news item in the brief.

    This was a two-column table: a category cell on the left, headline and a
    grey meta line on the right. It read as a different kind of object from
    the sections around it — the eye had to change mode to scan it, which is
    the opposite of what a wire is for.

    It is now the house item: a rule down the left, TAG&emsp;SOURCE in small grey
    caps, the headline, then the body. Same as the sections that read tightest,
    so The Wire scans like the rest of the brief instead of like a table.
    """
    if DESIGN == "v2":
        return _v2_row(_v2_kicker(src, cat), headline, url, body)
    tag_line = "&emsp;".join(x for x in (cat, src) if x)
    return (f'<div style="margin-bottom:11px;padding-left:12px;'
            f'border-left:3px solid {TAEGUK_BLUE};">'
            + (f'<div style="font-family:Arial,sans-serif;font-size:10px;color:{MUTE};'
               f'text-transform:uppercase;letter-spacing:1px;font-weight:600;'
               f'margin-bottom:2px;">{tag_line}</div>' if tag_line else "")
            + f'<div style="font-family:Georgia,serif;font-size:14px;font-weight:600;'
              f'color:{INK};line-height:1.4;">{_link_or_text(headline, url)}</div>'
            + (f'<div style="font-family:Georgia,serif;font-size:13px;line-height:1.5;'
               f'color:#353C48;margin-top:2px;">{body}</div>' if body else "")
            + '</div>')


def _item_block(cat: str, src: str, headline: str, body: str, url: str,
                 bar_color: str = TAEGUK_BLUE, extra_html: str = "") -> str:
    """One card treatment for every list item in the brief.

    Top stories, overnight, business, regional and wire items used to carry
    three different treatments — bordered cards, bare underlined links, and a
    red-barred block — for the same kind of content. That read as two products
    stitched together. This is the single form: white card, accent left rule,
    kicker, headline in ink with no underline, body, source last and muted.
    """
    kicker = "&emsp;".join(x for x in (cat, src) if x)
    if DESIGN == "v2":
        return _v2_item(cat, src, headline, body, url, bar_color, extra_html)
    if DESIGN == "refined":
        # Secondary items as a list, not a stack of cards: a hairline between
        # items, the kicker above, nothing boxed. Cards inside sections inside
        # bars was the most template-looking thing in the brief, and the
        # borders and padding cost height on every item.
        _k = ("<div style='font-family:Arial,sans-serif;font-size:10px;text-transform:uppercase;"
              "letter-spacing:1px;color:" + TAEGUK_BLUE + ";font-weight:700;margin-bottom:3px;'>" + kicker + "</div>") if kicker else ""
        _b = ("<div style='font-family:Georgia,serif;font-size:13px;line-height:1.5;color:#353C48;margin-top:3px;'>"
              + body + "</div>") if body else ""
        _rule = "border-left:3px solid " + bar_color + ";padding-left:10px;" if bar_color != TAEGUK_BLUE else ""
        return f"""
            <div class="item-row" style="padding:10px 0;border-bottom:1px solid #E6E8EC;{_rule}">
              {_k}
              <div style="font-size:15px;font-weight:700;color:#1A222E;font-family:Georgia,serif;line-height:1.35;">{_link_or_text(headline, url)}</div>
              {_b}
              {extra_html}
            </div>"""
    return f"""
            <div class="item-card" style="margin-bottom:8px;padding:10px 13px;background:#fff;border-radius:3px;border-left:3px solid {bar_color};border-top:1px solid #EEF0F3;border-right:1px solid #EEF0F3;border-bottom:1px solid #EEF0F3;">
              {"<div style='font-size:10px;text-transform:uppercase;letter-spacing:1px;color:" + TAEGUK_BLUE + ";font-weight:700;margin-bottom:4px;'>" + kicker + "</div>" if kicker else ""}
              <div style="font-size:14px;font-weight:600;color:#1A222E;font-family:Georgia,serif;line-height:1.4;">
                {_link_or_text(headline, url)}
              </div>
              {"<div style='font-family:Georgia,serif;font-size:13px;line-height:1.5;color:#353C48;margin-top:4px;'>" + body + "</div>" if body else ""}
              {extra_html}
            </div>"""


# How the audio edition shows in the masthead: "card" (a white bar under the
# nameplate), "line" (one quiet line in the RE line's place) or "pill" (a small
# button beside the issue meta).
LISTEN_STYLE = "card"

# "classic": every item in a bordered card. "refined": the first top story as a
# lead with a larger headline, secondary items as a ruled list. "hybrid": the
# classic cards and bars, plus a lead headline, large glance numerals and a
# status line (approval, days since Kim was seen) under the market strip.
# "v2": the CSIS newsletter system (grey ground, white cards, navy bars, teal
# kickers, one sans), as the China Room brief. Styling only; see the "Design
# v2" block below.
DESIGN = "classic"
# True when v2 renders for paper (run.write_preview_pdf): the print stylesheet
# and web fonts, and none of what does nothing on paper (the Listen card, the
# contents links, the links strip, buttons to web pages). v2 only; classic
# ignores it. Set together with FULL_TEXT.
PRINT = False
# True when rendering the web page (web_page.py), which is the full reference:
# anything that shortens an item's text for the email must leave it whole when
# this is set. Read it as one line, `if not FULL_TEXT: ...`.
FULL_TEXT = False
# Section headings: "bar" (black bar, white label) or "rule" (heavy ink rule,
# serif heading in sentence case). Masthead: "band" (blue band) or "white".
SECTION_STYLE = "bar"
MAST_STYLE = "band"

_CHROME_WORDS = _re.compile(
    r"For Internal Use Only|Read online|Download PDF|Listen to today.s brief|"
    r"The audio edition, read aloud|\d+ min(?= ?<)|Listen|Past issues|Back to top|"
    r"Top Stories|Pyongyang|Trade|Markets|Polling|Upcoming|"
    r"Center for Strategic and International Studies", _re.I)


# The Wire's group headings. The model writes its categories already cased
# ("DPRK", "ROK Economy", "US-Korea"); str.title() turned them into "Dprk",
# "Rok Economy" and "Us-Korea". Known categories in any case map to their
# display form; anything else is shown as written (a lower-case slug gets a
# capital first letter).
_WIRE_LABELS = {k.lower(): k for k in (
    "DPRK", "ROK", "ROK Economy", "ROK Politics", "ROK Society", "ROK Defense", "ROK Diplomacy",
    "US-Korea", "US-ROK", "NK-Russia", "NK-China", "NK-Russia-China", "Japan-Korea", "China-Korea",
    "Russia-Korea", "Inter-Korean", "Business", "Technology", "Economy", "Politics", "Defense",
    "Diplomacy", "Society", "Trade", "Markets", "Energy", "Other")}


def _wire_label(key: str) -> str:
    k = str(key or "").strip() or "Other"
    hit = _WIRE_LABELS.get(k.lower()) or _WIRE_LABELS.get(k.lower().replace("_", " "))
    if hit:
        return hit
    return k[:1].upper() + k[1:] if k == k.lower() else k


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
    text = text.replace("&middot;", " ").replace("&emsp;", " ").replace("&nbsp;", " ").replace("&amp;", "&")
    text = _CHROME_WORDS.sub(" ", text)
    text = _re.sub(r"\s+", " ", text)
    return len([w for w in text.split() if any(c.isalnum() for c in w)])


def _pledge_is_new(deal: dict, digest: dict, days: int = 7) -> bool:
    """A pledge project reported within `days` of the issue, or one not in the standing list."""
    try:
        from digest import PLEDGE_PROJECTS
    except Exception:                                           # noqa: BLE001
        return False
    name = " ".join(_re.sub(r"[^a-z0-9 ]+", " ", str(deal.get("company", "")).lower()).split())
    match = None
    for proj in PLEDGE_PROJECTS:
        key = " ".join(_re.sub(r"[^a-z0-9 ]+", " ", proj["project"].lower()).split())
        if name and (key in name or name in key):
            match = proj
            break
    if match is None:
        return True                     # reported by the model from today's sources
    try:
        reported = datetime.strptime(match.get("reported", ""), "%d %b %Y")
    except ValueError:
        return False
    raw = str(digest.get("digest_date", "")).strip()
    today = None
    for fmt, text in (("%Y-%m-%d", raw[:10]), ("%A, %B %d, %Y", raw), ("%B %d, %Y", raw)):
        try:
            today = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue
    if today is None:
        return False
    return 0 <= (today - reported).days <= days


_MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug",
                                      "sep", "oct", "nov", "dec"], 1)}


def _calendar_span(text: str, year: int):
    """'Oct 19-23, 2026' / 'October 20, 2026' / 'Oct 31-Nov 2' -> (start, end) dates, or None."""
    from datetime import date
    t = str(text or "").strip()
    m = _re.match(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:\s*[-–]\s*(?:([A-Za-z]{3})[a-z]*\.?\s+)?(\d{1,2}))?(?:,\s*(\d{4}))?", t)
    if not m or m.group(1).lower() not in _MON:
        return None
    y = int(m.group(5) or year)
    try:
        start = date(y, _MON[m.group(1).lower()], int(m.group(2)))
        end_mon = _MON.get((m.group(3) or m.group(1)).lower(), start.month)
        end = date(y, end_mon, int(m.group(4))) if m.group(4) else start
    except ValueError:
        return None
    return start, end


def _issue_day(digest: dict):
    """The issue date as a date, or None."""
    raw = str(digest.get("digest_date", "")).strip()
    for fmt, text in (("%Y-%m-%d", raw[:10]), ("%A, %B %d, %Y", raw), ("%B %d, %Y", raw)):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def hill_event_text(ev: dict, spoken: bool = False) -> str:
    """'Senate Foreign Relations hearing: The U.S.-ROK alliance', from a schedule entry.

    Built only from the fields the committee schedule carried. The Senate
    listing words every title "Hearings to examine ...", and a committee feed
    puts the date in its title; both are trimmed, nothing is added.
    """
    raw = _re.sub(r"\s+", " ", str(ev.get("title") or "")).strip()
    committee = str(ev.get("committee") or "").split(":")[0].strip()
    chamber = str(ev.get("chamber") or "").strip()
    if chamber and committee and not committee.lower().startswith(chamber.lower()):
        committee = f"{chamber} {committee}"
    kind = "markup" if _re.search(r"markup|mark-up|business meeting", raw, _re.I) else "hearing"
    title = _re.sub(r"^(?:(?:full committee|subcommittee)\s+)?(?:hearings?|markup|mark-up|business meeting)"
                    r"\s*(?:to examine|of|on|:|-|–)?\s*", "", raw, flags=_re.I)
    title = _re.sub(r"\s*[-–|,]\s*(?:\w+day,?\s+)?[A-Z][a-z]{2,8}\.? \d{1,2}, 20\d\d\s*$", "", title)
    title = title.rstrip(". ")
    if spoken:
        # "a Senate Foreign Relations hearing on the U.S.-ROK alliance": the
        # printed colon form read aloud is two headlines in a row.
        if title[1:2].islower():
            title = title[:1].lower() + title[1:]
        return f"a {committee} {kind} on {title}" if committee else title
    title = title[:1].upper() + title[1:]
    return f"{committee} {kind}: {title}" if committee else title


def hill_events(digest: dict) -> tuple[list, list]:
    """(today, coming up) from the collected congressional schedule.

    digest["hill_calendar"] is attached by run.py from the committee
    schedules, never written by the model, and is empty when they failed.
    """
    today = _issue_day(digest)
    if today is None:
        return [], []
    now, ahead = [], []
    for ev in digest.get("hill_calendar") or []:
        if not isinstance(ev, dict) or not ev.get("title"):
            continue
        try:
            d = datetime.strptime(str(ev.get("date", ""))[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if d == today:
            now.append(ev)
        if today <= d <= today.fromordinal(today.toordinal() + 7):
            ahead.append(ev)
    return now, ahead


def _happening_rows(digest: dict) -> list:
    """The events that fall on the issue date, as plain text, at most three."""
    raw = str(digest.get("digest_date", "")).strip()
    today = None
    for fmt, text in (("%Y-%m-%d", raw[:10]), ("%A, %B %d, %Y", raw), ("%B %d, %Y", raw)):
        try:
            today = datetime.strptime(text, fmt).date()
            break
        except ValueError:
            continue
    if today is None:
        return []
    # Same normalized shape as Upcoming and the audio edition: the model has
    # returned both {date, event} and {month, day, headline}.
    import korea_calendar
    rows = [c["headline"] for c in korea_calendar.happening_on(digest.get("calendar_watch"), today)]
    for ev in hill_events(digest)[0]:
        rows.append(hill_event_text(ev) + (f" ({ev['time']})" if ev.get("time") else ""))
    return [_str(r) for r in rows[:3]]


def _happening_today(digest: dict) -> str:
    """Up to three scheduled events that fall on the issue date, under Today at a Glance.

    Built from calendar_watch, which already carries the week's schedule; the
    strip shows only what happens today, so it is empty and absent on a day
    with nothing scheduled rather than padded with the week ahead.
    """
    rows = _happening_rows(digest)
    if not rows:
        return ""
    items = "".join(
        f'<tr><td style="padding:5px 0;font-family:Georgia,serif;font-size:14px;line-height:1.5;color:{INK};">'
        f'{_esc(c)}</td></tr>' for c in rows)
    return (f'<table width="100%" cellpadding="0" cellspacing="0" border="0" class="happening" '
            f'style="margin-top:12px;border-top:2px solid {INK};">'
            f'<tr><td style="padding:9px 0 2px;font-family:Arial,sans-serif;font-size:12px;font-weight:700;'
            f'color:{INK};">Happening today</td></tr>{items}</table>')


def _status_line(digest: dict) -> str:
    """One line under the market strip: the brief's own running indicators."""
    bits = []
    ap = ((digest.get("public_sentiment") or {}).get("presidential_approval") or {}).get("value")
    if ap:
        bits.append(f'Lee approval <b style="color:#FFFFFF;">{_esc(ap)}</b>')
    days = (digest.get("kcna_delta") or {}).get("days_since_last_appearance")
    if isinstance(days, int) and days > 0:
        bits.append(f'Kim Jong Un last seen <b style="color:#FFFFFF;">{days} day{"s" if days != 1 else ""} ago</b>')
    if not bits:
        return ""
    return (f'<table width="100%" cellpadding="0" cellspacing="0" border="0" class="status-line" '
            f'style="background:#0B1626;"><tr><td align="center" style="padding:7px 12px;font-family:Arial,sans-serif;'
            f'font-size:12px;color:#B8C4D6;">' + "&emsp;".join(bits) + '</td></tr></table>')


def render(digest: dict) -> str:
    from zoneinfo import ZoneInfo
    if DESIGN == "v2":
        # The email shows top stories in full and the first two sentences
        # (about fifty words at most) of everything else; the issue's web
        # page carries the rest.
        _v2_src = digest
        digest, _v2_more = _v2_shorten(digest)
    now = datetime.now(ZoneInfo("America/New_York"))
    date_str = now.strftime("%A, %B %-d, %Y")  # Thursday, March 20, 2026
    gen_time = now.strftime("%-I:%M %p ET")
    re_line = _esc(digest.get("re_line", ""))
    word_count = 0          # resolved from the assembled body; see %%WORDS%%
    # Issue number, when run.py supplied one, so the brief is citable.
    _issue_no = digest.get("issue_no")
    _issue_meta = (f'No.&nbsp;{int(_issue_no)}&emsp;'
                   if isinstance(_issue_no, (int, float)) and _issue_no > 0 else "")
    read_min = 0

    web_url = digest.get("web_url", "")
    _footer_trade = ""
    _b = web_url[:-len("latest.html")] if web_url.endswith("latest.html") else ""
    archive_url = (_b + "archive.html") if _b else web_url
    # Built where the other two footer links are built, so all three carry the
    # same pill. It was still a plain underlined-less link and sat next to two
    # buttons looking like an afterthought.
    _foot_btn = ('display:inline-block;padding:6px 15px;margin:0 4px;'
                 'font-family:Arial,sans-serif;font-size:11px;font-weight:700;'
                 'letter-spacing:0.5px;color:#14181F;background:#FFFFFF;'
                 'border-radius:3px;text-decoration:none;white-space:nowrap;')
    if _b:
        _footer_trade = (f'<a class="pill" href="{_b}trade.html" '
                         f'style="{_foot_btn}">Trade reference</a>')
    sections = []

    # ── 0. View in Browser bar (Read online&emsp;Print / PDF&emsp;Archive) ──────
    # v2 carries these links and the notice inside its masthead.
    if web_url and DESIGN != "v2":
        base = web_url[:-len("latest.html")] if web_url.endswith("latest.html") else ""
        # A solid pill. A translucent fill behind a hairline border renders
        # unpredictably across clients and reads as tentative; a filled
        # button reads as something you press.
        _a = ('display:inline-block;padding:6px 14px;margin:0 3px;'  # util-btn
              'font-family:Arial,sans-serif;font-size:11px;font-weight:700;'
              'letter-spacing:0.5px;color:#14181F;background:#FFFFFF;'
              'border-radius:3px;'
              'text-decoration:none;white-space:nowrap;')
        _online = _issue_file(digest, base, "html") or web_url
        links = [f'<a class="pill" href="{_esc(_online)}" style="{_a}">Read online</a>']
        if base:
            links.append(f'<a class="pill" href="{_esc(_issue_file(digest, base, "pdf"))}" style="{_a}">Download PDF</a>')
            # Only when run.py has confirmed an MP3 exists for this issue. The
            # link points at the dated file, not latest.mp3, so an old email
            # keeps playing its own day rather than whatever is newest.
            # The episode has its own bar in the masthead (below); a second
            # Listen pill here would be the same link twice.
            links.append(f'<a class="pill" href="{_esc(base + "archive.html")}" style="{_a}">Past issues</a>')
        sep = ''
        # The internal-use notice and the utility links each had a full-width
        # band to themselves, which put roughly 90px of chrome above the
        # nameplate before a reader reached a word of the brief. Same content,
        # one row: notice left, links right, collapsing to two centred rows on
        # a phone where they will not fit side by side.
        sections.append(f"""
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#2E3644;" class="util-row">
          <tr>
            <td class="util-cell" style="padding:7px 32px;font-family:Arial,sans-serif;font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:rgba(255,255,255,0.72);">For Internal Use Only</td>
            <td class="util-cell" align="right" style="padding:5px 32px 5px 0;text-align:right;">{sep.join(links)}</td>
          </tr>
        </table>
        """)

    # ── 1. Header ────────────────────────────────────────────────────────
    if MAST_STYLE == "white":
        _mb, _mf, _mk, _md, _mm = "#FFFFFF", "#14181F", TAEGUK_BLUE, "#5A6472", "#6B7280"
    else:
        _mb, _mf, _mk, _md, _mm = BAND, "#fff", "rgba(255,255,255,0.78)", "rgba(255,255,255,0.85)", "rgba(255,255,255,0.72)"
    # The bar under the nameplate: the audio edition when there is one, the
    # RE line otherwise. Email clients will not play audio inline (Gmail and
    # Outlook strip <audio>), so the bar is one large link to the episode,
    # which opens in the phone's or browser's own player.
    _listen_pill = ""
    if digest.get("audio_url") and LISTEN_STYLE in ("line", "pill"):
        _mins = digest.get("audio_minutes")
        _len = f"{int(_mins)} min" if isinstance(_mins, (int, float)) and _mins > 0 else ""
        _href = _esc(digest["audio_url"])
        if LISTEN_STYLE == "line":
            # One quiet line where the RE line sat, in the same hairline frame.
            _masthead_bar = (
                "<div style='margin-top:14px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.28);'>"
                f'<a href="{_href}" style="text-decoration:none;color:#FFFFFF;font-family:Arial,sans-serif;">'
                '<span style="display:inline-block;width:22px;height:22px;line-height:22px;border-radius:11px;'
                f'background:#FFFFFF;color:{BAND};text-align:center;font-size:10px;vertical-align:middle;">&#9654;&#xFE0E;</span>'
                '<span style="font-size:13px;font-weight:700;letter-spacing:0.3px;vertical-align:middle;margin-left:9px;">Listen to today&#8217;s brief</span>'
                + (f'<span style="font-size:12px;color:rgba(255,255,255,0.72);vertical-align:middle;margin-left:8px;">{_len}</span>' if _len else "")
                + "</a></div>")
        else:
            # A small pill beside the issue meta; nothing under the nameplate.
            _masthead_bar = ""
            _listen_pill = (
                f'<a href="{_href}" style="display:inline-block;margin-top:8px;padding:6px 12px;background:#FFFFFF;'
                'border-radius:14px;text-decoration:none;font-family:Arial,sans-serif;font-size:12px;font-weight:700;'
                f'color:#14181F;white-space:nowrap;"><span style="color:{BAND};">&#9654;&#xFE0E;</span>&nbsp; Listen'
                + (f'&emsp;{_len}' if _len else "") + "</a>")
    elif digest.get("audio_url"):
        _mins = digest.get("audio_minutes")
        _len = f"{int(_mins)} min" if isinstance(_mins, (int, float)) and _mins > 0 else "Audio"
        # The player page (chapters, transcript, subscribe) when there is one.
        _listen_href = digest.get("listen_url") or digest["audio_url"]
        _listen_label = "Listen, " + _len if _len != "Audio" else "Listen to today&#8217;s brief"
        _masthead_bar = (
            f'<a href="{_esc(_listen_href)}" class="listen-bar" '
            'style="display:block;margin-top:14px;padding:11px 14px;background:#FFFFFF;'
            'border-radius:4px;text-decoration:none;color:#14181F;">'
            '<table width="100%" cellpadding="0" cellspacing="0" border="0" role="presentation"><tr>'
            '<td width="34" style="vertical-align:middle;">'
            f'<span class="listen-play" style="display:inline-block;width:28px;height:28px;line-height:28px;border-radius:14px;'
            f'background:{BAND};color:#FFFFFF;text-align:center;font-size:12px;font-family:Arial,sans-serif;">&#9654;&#xFE0E;</span></td>'
            '<td style="vertical-align:middle;font-family:Arial,sans-serif;">'
            f'<div class="listen-title" style="font-size:14px;font-weight:700;color:#14181F;">{_listen_label}</div>'
            '<div class="listen-sub" style="font-size:12px;color:#353C48;margin-top:1px;">The audio edition, read aloud</div></td>'
            f'<td class="listen-len" align="right" style="vertical-align:middle;font-family:Arial,sans-serif;font-size:12px;font-weight:700;color:#353C48;white-space:nowrap;"></td>'
            '</tr></table></a>')
    # No RE line in its place: the owner dropped it (22 Oct). The glance
    # carries the same three stories a few lines down.
    else:
        _masthead_bar = ""
    sections.append(f"""
    <a name="top" id="top"></a>
    <div bgcolor="{_mb}" style="background-color:{_mb};color:{_mf};padding:{"22px 32px 16px" if MAST_STYLE == "white" else "16px 32px 16px"};border-bottom:{"4px double #14181F" if MAST_STYLE == "white" else "1px solid rgba(255,255,255,0.18)"};" class="sec mast-band{" mast-white" if MAST_STYLE == "white" else ""}">
      <table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
        <td class="mast-main" style="vertical-align:top;">
          <div style="font-family:Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:{_mk};margin-bottom:7px;">CSIS Korea Chair</div>
          <h1 style="margin:0 0 4px 0;font-size:{"36px" if MAST_STYLE == "white" else "26px"};font-weight:700;font-family:Georgia,'Times New Roman',serif;color:{_mf};letter-spacing:{"-0.3px" if MAST_STYLE == "white" else "0.5px"};">
            Korea Daily Brief
          </h1>
          <div style="margin-top:2px;font-size:16px;font-weight:400;color:{_md};font-family:Georgia,serif;">{_esc(date_str)}</div>
        </td>
        <td class="mast-meta" style="vertical-align:bottom;text-align:right;">
          <div style="font-family:Arial,sans-serif;font-size:11px;letter-spacing:0.5px;color:{_mm};white-space:nowrap;">{_issue_meta}%%WORDS%% words&emsp;%%READMIN%% min read</div>
          {_listen_pill}
        </td>
      </tr></table>
      {_masthead_bar}
    </div>
    """)
    if DESIGN == "v2":
        sections[-1] = _v2_masthead(digest, now, _masthead_bar)

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
        <a name="markets" id="markets"></a>
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
              <div style="font-family:Arial,sans-serif;font-size:11px;margin-top:2px;"><span style="color:#8FA0B5;">{_esc(str(bok_rate.get("last_change", "")))}</span></div>
            </td>
          </tr>
        </table>
        {_status_line(digest) if DESIGN == "hybrid" else ""}
        """)
    if DESIGN == "v2" and markets:
        sections.pop()          # v2 shows its number strip under the glance

    # ── 2c. Section navigation. Emitted as a placeholder here and resolved
    #      after every section is built, so links are only offered for
    #      sections that actually rendered. ─────────────────────────────────
    sections.append("%%NAV%%")

    # ── 3. Morning Memo (top 3 at a glance) ─────────────────────────────────
    memo_items = digest.get("morning_memo") or []
    if memo_items:
        memo_html = ""
        for i, mi in enumerate(memo_items[:3]):
            # The memo is the first thing read and the place the prompt most
            # wants a name bolded, so it converts emphasis like any body copy.
            memo_text = _emphasis(_esc(mi) if isinstance(mi, str) else _esc(mi.get("text", "") if isinstance(mi, dict) else str(mi or "")))
            num = i + 1
            memo_html += f"""
            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:10px;">
              <tr>
                <td width="28" style="vertical-align:top;padding-top:2px;">
                  {f'<div class="glance-num" style="font-family:Georgia,serif;font-size:34px;line-height:0.95;font-weight:700;color:{TAEGUK_RED};">{num}</div>' if DESIGN == "hybrid" else f'<div style="width:24px;height:24px;border-radius:50%;background:{TAEGUK_BLUE};color:#FFFFFF;text-align:center;line-height:24px;font-size:13px;font-weight:700;font-family:Georgia,serif;">{num}</div>'}
                </td>
                <td style="padding-left:10px;vertical-align:top;">
                  <div style="font-size:14px;line-height:1.6;color:#2C3E50;font-family:Georgia,serif;">{memo_text}</div>
                </td>
              </tr>
            </table>"""
        sections.append(f"""
        <div style="padding:18px 32px 6px;" class="sec">
          <a name="memo" id="memo"></a>
          <table width="100%" cellpadding="0" cellspacing="0" border="0" class="glance-panel" style="background:#EDF2FA;border-left:3px solid {TAEGUK_BLUE};">
            <tr><td style="padding:0;">{_sec_label("Today at a Glance")}</td></tr>
            <tr><td style="padding:0 20px 8px;">
              {memo_html}
            </td></tr>
          </table>
          {_happening_today(digest)}
        </div>
        """)
        if DESIGN == "v2":
            sections[-1] = _v2_glance(digest, memo_items)
    if DESIGN == "v2":
        # The memo first, so it is on a phone's first screen; then the hard
        # numbers. The contents line sits in the date card above both.
        sections.append(_v2_numbers(digest))

    # ── 4. Top Stories ────────────────────────────────────────────────────
    top_stories = digest.get("top_stories") or []
    if top_stories:
        stories_html = ""
        for _si, story in enumerate(top_stories):
            cat = _esc(_str(story.get("category_tag", story.get("category", ""))))
            headline = _emphasis(_esc(story.get("headline", "")))
            body = _emphasis(_esc(story.get("body", "")))
            src_line = _top_story_sources(story)
            url = story.get("url", "")
            cat_badge = f'<div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:{TAEGUK_BLUE};font-weight:700;margin-bottom:4px;">{cat}</div>' if cat else ""
            stories_html += f"""
            <div class="item-card story-card" style="margin-bottom:10px;padding:12px 15px;background:#fff;border-radius:3px;border-left:3px solid {TAEGUK_BLUE};border-top:1px solid #EEF0F3;border-right:1px solid #EEF0F3;border-bottom:1px solid #EEF0F3;">
              {cat_badge}
              <h3 style="margin:0 0 6px 0;font-size:{"22px" if DESIGN in ("refined", "hybrid") and _si == 0 else "16px"};font-weight:{"700" if DESIGN in ("refined", "hybrid") else "600"};color:{INK};font-family:Georgia,serif;line-height:{"1.25" if DESIGN in ("refined", "hybrid") and _si == 0 else "1.4"};">
                {_link_or_text(headline, url)}
              </h3>
              <p style="margin:0 0 6px 0;font-size:14px;line-height:1.55;font-family:Georgia,serif;color:#353C48;">{body}</p>
              <div style="font-size:11px;color:#6B7280;margin-top:4px;">{src_line}</div>
            </div>"""
        sections.append(f"""
        <div {_SEC}>
          <a name="top-stories" id="top-stories"></a>{_sec_label("Top Stories")}
          {stories_html}
        </div>
        """)
        if DESIGN == "v2":
            sections[-1] = _v2_top_stories(top_stories)

    # ── 4b. Overnight Flash (high-priority overnight items) ────────────
    overnight = digest.get("overnight_items") or []
    if overnight:
        flash_html = ""
        for item in overnight:
            # The prompt asks for category_tag; this read category, so the
            # left-hand label column rendered empty in every issue while the
            # other three editions showed theirs. Read the name the model is
            # told to use, keeping the old one as a fallback.
            cat_raw = _str(item.get("category_tag", item.get("category", "")))
            cat = _esc(cat_raw)
            headline = _emphasis(_esc(item.get("headline", "")))
            body = _emphasis(_esc(item.get("body_text", "")))
            src = _esc(_clean_src(item.get("source", "")))
            url = item.get("url", "")
            # A scan list, not a second Top Stories. One rule down the left,
            # one line per item, so the eye runs vertically instead of stopping
            # at a card border every three lines. The cards above carry the
            # weight; this section carries the breadth.
            # Headline on its own line, the clause beneath it. Running them
            # together behind an em-dash made a two-line wrap read as one long
            # sentence, and the eye could not find where an item ended.
            tail = (f'<div style="font-family:Georgia,serif;font-size:13px;'
                    f'line-height:1.45;color:#353C48;margin-top:2px;">{body}</div>'
                    if body else "")
            if DESIGN == "v2":
                # The house kicker above the headline, as everywhere else in
                # v2: the source, then the category.
                flash_html += _v2_row(_v2_kicker(src, cat), headline, url, body)
                continue
            flash_html += (
                f'<tr>'
                f'<td style="padding:7px 10px 7px 0;vertical-align:top;white-space:nowrap;'
                f'font-family:Arial,sans-serif;font-size:10px;font-weight:700;'
                f'letter-spacing:0.5px;text-transform:uppercase;color:{TAEGUK_BLUE};'
                f'border-bottom:1px solid #EEF0F3;">{cat}</td>'
                f'<td style="padding:7px 0;vertical-align:top;font-family:Georgia,serif;'
                f'font-size:13px;line-height:1.45;color:{INK};'
                f'border-bottom:1px solid #EEF0F3;">'
                f'<div>{_link_or_text(headline, url)}'
                f'<span style="font-family:Arial,sans-serif;font-size:11px;color:#6B7280;">'
                f'&emsp;{src}</span></div>{tail}</td>'
                f'</tr>')
        if DESIGN != "v2":
            flash_html = (f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
                          f'class="flash-table" style="border-top:2px solid {TAEGUK_BLUE};">'
                          f'{flash_html}</table>')
        sections.append(f"""
        <div {_SEC}>
          <a name="overnight" id="overnight"></a>{_sec_label("Overnight")}
          {flash_html}
        </div>
        """)

    # (watch_today section removed — field was never in digest prompt schema)

    # ── 6. Key Stat of the Day ───────────────────────────────────────────
    key_stat = digest.get("key_stat") or {}
    if key_stat and key_stat.get("number") is not None and key_stat.get("number") != "":
        sections.append(f"""
        <a name="key-stat" id="key-stat"></a>
        <div {_SEC}>
          {_sec_label("Stat of the Day")}
          <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#EDF3FB;border-top:2px solid {TAEGUK_BLUE};border-bottom:1px solid #E4E7EB;border-radius:3px;">
            <tr><td style="padding:14px 16px;">
              <div style="font-family:Georgia,serif;font-size:26px;font-weight:700;color:{TAEGUK_BLUE};line-height:1;">{_esc(str(key_stat.get("number", "")))}</div>
              <div style="font-family:Georgia,serif;font-size:14px;color:{INK};margin-top:5px;line-height:1.4;">{_esc(key_stat.get("label", ""))}</div>
              {"<div style='font-family:Georgia,serif;font-size:13px;color:#353C48;margin-top:4px;line-height:1.5;'>" + _emphasis(_esc(key_stat.get("context", ""))) + "</div>" if key_stat.get("context") else ""}
              {"<div style='font-family:Arial,sans-serif;font-size:11px;color:#55607A;margin-top:7px;'>" + _esc(key_stat.get("source", "")) + "</div>" if key_stat.get("source") else ""}
            </td></tr>
          </table>
        </div>
        """)
        if DESIGN == "v2":
            sections[-1] = _v2_stat(key_stat, _v2_more.get("key-stat", ""))

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
                kim_line += f": {kim_activity}"
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
            src_line = f" <span style='color:#9FB3CC;'>({src_art})</span>" if src_art else ""
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
            role_line = (f"<span style='color:#9FB3CC;'>&emsp;{o_role}</span>"
                         if o_role else "")
            senior_rows += (
                f"<div style='margin-bottom:7px;'>"
                f"<div style='font-size:13px;font-weight:600;font-family:Georgia,serif;color:#E8E8E8;'>{o_name}{role_line}</div>"
                f"<div style='font-size:13px;font-family:Georgia,serif;color:#C8D4E2;line-height:1.45;'>{o_act}</div>"
                f"</div>")
        if senior_rows:
            seniors_html = (
                f'<div style="margin-top:14px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.10);">'
                f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#9FB3CC;margin-bottom:8px;">Senior Officials</div>'
                f'{senior_rows}</div>')

        # Top 3 KCNA articles — Kim-related items ranked first by the prompt
        top_articles = kcna.get("top_articles") or []
        articles_html = ""
        if top_articles:
            art_items = ""
            for i, art in enumerate(top_articles[:3], 1):
                a_headline = _emphasis(_esc(art.get("headline", "")))
                if not a_headline:
                    continue
                a_summary = _emphasis(_esc(art.get("summary", "")))
                a_src = _esc(art.get("source", ""))
                a_url = art.get("url", "")
                kim_badge = (f' <span style="font-family:Arial,sans-serif;font-size:10px;font-weight:700;letter-spacing:0.5px;'
                             f'color:{RED_ON_NAVY};letter-spacing:0.5px;">KIM</span>'
                             if art.get("kim_related") else "")
                src_tag = f" <span style='color:#9FB3CC;'>({a_src})</span>" if a_src else ""
                art_items += f"""<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:8px;"><tr>
                  <td width="24" style="vertical-align:top;font-family:Arial,sans-serif;font-size:13px;font-weight:700;color:{BLUE_ON_NAVY};padding-top:1px;">{i}.</td>
                  <td style="vertical-align:top;">
                    <div style="font-size:13px;font-weight:600;font-family:Georgia,serif;color:#E8E8E8;line-height:1.4;">{_link_or_text(a_headline, a_url, style="font-family:Georgia,serif;color:#E8E8E8;text-decoration:underline;")}{kim_badge}</div>
                    {"<div style='font-size:13px;font-family:Georgia,serif;color:#C8D4E2;line-height:1.5;margin-top:2px;'>" + a_summary + src_tag + "</div>" if a_summary else ""}
                  </td>
                </tr></table>"""
            if art_items:
                articles_html = f"""<div style="margin-top:4px;">
                  <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#9FB3CC;margin-bottom:8px;">Top KCNA Articles</div>
                  {art_items}
                </div>"""

        sections.append(f"""
        <a name="kcna" id="kcna"></a>
        <div style="padding:0;border-bottom:1px solid #333;" class="sec kcna-dark">
          <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{NAVY_PANEL};">
            <tr>
              <td style="padding:12px 32px;">
                <span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:{BLUE_ON_NAVY};font-family:Arial,sans-serif;border-bottom:2px solid {TAEGUK_RED};padding-bottom:5px;display:inline-block;">Pyongyang Watch&emsp;KCNA</span>
              </td>
            </tr>
          </table>
          <div style="padding:16px 32px;background:{NAVY_PANEL};font-family:Georgia,serif;color:#E0E0E0;">
            {"<div style='margin-bottom:12px;padding:8px 14px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.15);border-radius:3px;font-size:13px;font-family:Georgia,serif;color:#C8D4E2;'>No new KCNA dispatches ingested today; showing last known status.</div>" if data_unavailable else ""}
            {"<div style='margin-bottom:12px;padding:8px 14px;background:" + TAEGUK_RED + ";color:#fff;border-radius:3px;font-size:13px;font-weight:600;'>Complete KCNA silence today</div>" if silence else ""}
            <div style="padding:0 0 12px;margin-bottom:14px;border-bottom:1px solid rgba(255,255,255,0.14);">
              <span style="font-family:Arial,sans-serif;font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#9FB3CC;">Kim Jong Un</span>
              {"<span style='display:inline-block;margin-left:8px;padding:1px 7px;border-radius:3px;background:" + TAEGUK_RED + ";color:#fff;font-family:Arial,sans-serif;font-size:10px;font-weight:700;letter-spacing:1px;'>WATCH FLAG</span>" if watch and not silence and not data_unavailable else ""}
              <div style="font-size:14px;color:#E8E6E1;font-weight:600;margin-top:4px;">{kim_icon}{kim_line}</div>
            </div>
            {quotes_html}
            {articles_html}
            {seniors_html}
            {"<div style='margin-top:16px;padding:1px 0 1px 14px;border-left:3px solid " + BLUE_ON_NAVY + ";font-size:13px;line-height:1.6;color:#E0E0E0;font-family:Georgia,serif;'><strong style='color:" + BLUE_ON_NAVY + ";'>Bottom line:</strong> " + bottom_line + "</div>" if bottom_line else ""}
          </div>
        </div>
        """)
        if DESIGN == "v2":
            sections[-1] = _v2_kcna(kcna, digest)

    # ── 9. ROK Government (merged: Gov + Personnel + Assembly + Calendar) ─
    rok_gov = digest.get("rok_government") or []
    # Fixed observances are arithmetic, not recall, so they are computed and
    # merged with whatever dated events the model found today. Upcoming shipped
    # empty once and past-dated before that; neither is possible now.
    try:
        import korea_calendar
        calendar_watch = korea_calendar.merge(digest.get("calendar_watch"), _issue_day(digest))
    except Exception:
        calendar_watch = digest.get("calendar_watch") or []
    rok_personnel = digest.get("rok_personnel") or []
    rok_assembly = digest.get("rok_assembly") or []
    if rok_gov or rok_personnel or rok_assembly:
        # 2x2 grid of ministry cards
        gov_rows = ""
        # v2 runs the cards in one column. In two, each card's text ran about
        # forty characters to a line, choppy for a paragraph, and the pair
        # could not narrow below 295px without the stylesheet.
        _cols = 1 if DESIGN == "v2" else 2
        for i in range(0, len(rok_gov), _cols):
            row_cards = ""
            for j in range(i, min(i + _cols, len(rok_gov))):
                item = rok_gov[j]
                ministry = _esc(_en_label(item.get("ministry", "")))
                action = _esc(item.get("action", ""))
                detail = _emphasis(_esc(item.get("detail", "")))
                source_url = item.get("url", "")
                source_label = _esc(item.get("source_label", ""))
                # Who acted. The prompt has always extracted this; the card
                # showed only the ministry, so the name was thrown away.
                official = _esc(_en_label(item.get("official", "")))
                official_line = (
                    f'<div style="font-size:13px;font-family:Georgia,serif;color:#353C48;margin-bottom:4px;">{official}</div>'
                    if official and official.lower() not in ("none", "null", "n/a") else "")
                ministry_header = ""
                ministry_header += f'<span style="font-size:10px;color:#6B7280;text-transform:uppercase;letter-spacing:0.5px;">{ministry}</span>'
                # A ministry release and a story about it are not the same kind
                # of thing, and the card used to show one unlabelled link for
                # whichever it had. Label them: the primary document first,
                # the reporting under it.
                secondary_url = item.get("secondary_url", "")
                secondary_label = _esc(item.get("secondary_label", ""))
                _rows = []
                if source_url and source_url != "#" and source_url.startswith("http"):
                    # "Primary" only for the government's own document. All 30
                    # cards in a ten-issue audit said Primary and every one
                    # opened a news outlet; those now name the outlet.
                    _raw_label = str(item.get("source_label") or "")
                    if _linkq.is_primary_url(source_url):
                        s_label = source_label if source_label else ministry
                        _rows.append(
                            f'<span style="font-weight:700;color:{TAEGUK_BLUE};">Primary</span> '
                            f'<a href="{_esc(source_url)}" style="font-family:Georgia,serif;color:#353C48;text-decoration:none;">'
                            f'{s_label}</a>')
                    else:
                        s_label = (_raw_label if _raw_label and _linkq.label_matches_url(_raw_label, source_url)
                                   else _linkq.publisher_name(source_url))
                        _rows.append(
                            f'<a href="{_esc(source_url)}" style="font-weight:700;color:#353C48;text-decoration:none;">'
                            f'{_esc(s_label)}</a>')
                elif source_label:
                    _rows.append(f'<span style="font-weight:700;">Source</span> {source_label}')
                if secondary_url and str(secondary_url).startswith("http"):
                    _rows.append(
                        f'<span style="font-weight:700;">Reported</span> '
                        f'<a href="{_esc(secondary_url)}" style="font-family:Georgia,serif;color:#353C48;text-decoration:none;">'
                        f'{secondary_label or "coverage"}</a>')
                elif secondary_label:
                    _rows.append(f'<span style="font-weight:700;">Reported</span> {secondary_label}')
                src_link = ""
                if _rows:
                    src_link = ('<div style="margin-top:8px;padding-top:7px;'
                                'border-top:1px solid #E1E6ED;font-family:Arial,sans-serif;'
                                'font-size:11px;line-height:1.7;color:#6B7280;">'
                                + "<br>".join(_rows) + "</div>")
                # Same fill treatment as the location cards: min-height sets a
                # floor but does not make a short card match a tall one beside
                # it, so the row still went ragged whenever two ministries said
                # different amounts.
                row_cards += f"""
                <td style="width:50%;padding:8px;vertical-align:top;" height="100%">
                  <table width="100%" cellpadding="0" cellspacing="0" border="0" height="100%" style="height:100%;">
                    <tr><td style="background:#F5F7FA;border-radius:3px;padding:14px;vertical-align:top;">
                      <div style="margin-bottom:6px;">{ministry_header}</div>
                      <div style="font-size:14px;font-weight:700;color:{INK};line-height:1.3;margin-bottom:6px;">{action}</div>
                      {official_line}
                      <div style="font-size:13px;line-height:1.5;font-family:Georgia,serif;color:#353C48;">{detail}</div>
                      {src_link}
                    </td></tr>
                  </table>
                </td>"""
            if len(rok_gov) - i == 1 and _cols == 2:
                row_cards += '<td style="width:50%;padding:8px;"></td>'
            gov_rows += f"<tr>{row_cards}</tr>"

        gov_grid_html = ""
        if rok_gov and DESIGN == "v2":
            gov_grid_html = _v2_rok_cards(rok_gov)
        elif rok_gov:
            gov_grid_html = f"""
            <table width="100%" cellpadding="0" cellspacing="0" border="0" class="gov-grid">
              {gov_rows}
            </table>"""

        # Personnel changes (inline in ROK Gov)
        pers_html = ""
        if rok_personnel:
            action_colors = {"appointed": UP_GREEN, "nominated": TAEGUK_BLUE, "resigned": TAEGUK_RED, "dismissed": TAEGUK_RED, "confirmed": UP_GREEN}
            pers_items = ""
            for item in rok_personnel:
                position = _esc(_en_label(item.get("position", "")))
                name = _esc(item.get("name", ""))
                action = item.get("action", "appointed")
                detail = _emphasis(_esc(item.get("detail", "")))
                predecessor = _esc(item.get("predecessor", ""))
                a_color = action_colors.get(action, "#1B2A4A")
                action_badge = f'<span style="display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600;color:#fff;background:{a_color};text-transform:uppercase;margin-left:6px;">{_esc(action)}</span>'
                pred_line = f'<div style="font-size:11px;color:#6B7280;margin-top:2px;">Replaces: {predecessor}</div>' if predecessor else ""
                pers_items += f"""
                <div style="margin-bottom:10px;padding-left:12px;border-left:3px solid {a_color};">
                  <div style="font-size:13px;font-weight:600;color:#1B2A4A;">{name}{action_badge}</div>
                  <div style="font-size:13px;font-family:Georgia,serif;color:#353C48;">{position}</div>
                  <div style="font-size:13px;line-height:1.4;font-family:Georgia,serif;color:#353C48;">{detail}</div>
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
                committee = _esc(_en_label(_c.title() if _c.isupper() else _c))
                action = _esc(item.get("action", "") or item.get("activity", ""))
                detail = _emphasis(_esc(item.get("detail", "")))
                asm_items += f"""
                <div style="margin-bottom:11px;padding-left:12px;border-left:3px solid #C9D2DE;">
                  <div style="font-family:Georgia,serif;font-size:14px;font-weight:600;color:{INK};line-height:1.35;">{action}</div>
                  <div style="font-size:13px;color:#6B7280;margin-top:2px;">{committee}</div>
                  <div style="font-size:13px;line-height:1.5;font-family:Georgia,serif;color:#353C48;margin-top:3px;">{detail}</div>
                </div>"""
            asm_html = f"""
            <div style="margin-top:16px;">
              <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:#6B7280;margin-bottom:8px;padding-bottom:4px;border-bottom:1px solid #E8E8E8;">National Assembly</div>
              {asm_items}
            </div>"""

        rok_date = _esc(str(digest.get("digest_date", "")))
        sections.append(f"""
        <div {_SEC}>
          <a name="rok-gov" id="rok-gov"></a>{_sec_label("ROK Government")}
          <div style="font-size:10px;color:#6B7280;font-family:Arial,sans-serif;margin-top:-10px;margin-bottom:10px;">President and ministries, {rok_date}</div>
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
        e_summary = _emphasis(_esc(election.get("summary", "")))
        key_races = election.get("key_races") or []

        races_html = ""
        if key_races:
            race_rows = ""
            for r in key_races[:6]:
                region = _esc(r.get("region", ""))
                inc = _esc(r.get("incumbent_party", ""))
                chal = _esc(r.get("challenger_party", ""))
                status = _esc(r.get("status", ""))
                note = _emphasis(_esc(r.get("note", "")))
                inc_color = TAEGUK_BLUE if "Democratic" in inc or "DP" in inc else TAEGUK_RED
                chal_color = TAEGUK_RED if "People Power" in chal or "PPP" in chal else TAEGUK_BLUE
                race_rows += f"""
                <tr style="border-bottom:1px solid #E8E8E8;">
                  <td style="padding:6px 8px 6px 0;font-size:13px;font-weight:600;color:{INK};width:30%;">{region}</td>
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
          <a name="election" id="election"></a>{_sec_label("Election Tracker")}
          <div style="margin-top:6px;">
            <span style="font-size:18px;font-weight:700;color:{INK};">{e_name}</span>
            <span style="display:inline-block;padding:2px 10px;border-radius:3px;font-family:Arial,sans-serif;letter-spacing:0.5px;font-size:11px;font-weight:700;color:#fff;background:{urgency_color};margin-left:10px;vertical-align:middle;">{e_days} DAYS</span>
          </div>
          <div style="font-size:11px;color:#6B7280;margin-top:4px;">{e_date}</div>
          <div style="font-size:13px;line-height:1.6;font-family:Georgia,serif;color:#353C48;margin-top:8px;">{e_summary}</div>
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
            f'<div style="font-size:13px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;'
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
                status_pill = (f'<span style="display:inline-block;font-family:Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.5px;'
                               f'letter-spacing:0.5px;padding:2px 8px;border-radius:3px;background:{pill_bg};color:{pill_fg};">{_esc(_h_key)}</span>')
            elif h_status.strip():
                # long/free-form status -> fold into the note so it reads normally
                note_text = h_note or _esc(h_status)

            # Number and short pill share one line; the note gets its OWN
            # full-width line below (so it can never wrap into a narrow column).
            if _has_rate:
                _hero_lead = (f'<span style="font-family:{MONO};font-size:26px;font-weight:700;color:{TAEGUK_RED};vertical-align:middle;">{h_rate}</span>'
                              + (f'&nbsp;&nbsp;{status_pill}' if status_pill else ''))
            else:
                # Status is the hero (e.g. EXPIRED), muted — not a red percentage.
                _sw = _esc(_h_key if _h_key in _status_pill else (h_status.strip() or "—"))
                _hero_lead = f'<span style="font-family:Georgia,serif;font-size:22px;font-weight:700;color:#55607A;letter-spacing:0.5px;vertical-align:middle;">{_sw}</span>'
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
                         f'<div style="font-size:13px;font-family:Georgia,serif;color:#353C48;margin-top:2px;">{"&emsp;".join(watch_bits)}</div></div>')

            _sec_colors = {"ACTIVE": TAEGUK_RED, "PAUSED": "#7F8C8D", "NEGOTIATING": TAEGUK_BLUE, "REDUCED": UP_GREEN}
            sec_rows = ""
            for sr in (tariff_tracker.get("sector_rates") or []):
                sr_st = sr.get("status", "ACTIVE")
                if sr_st == "ESCALATION":
                    sr_st = "ACTIVE"
                sec_rows += (f'<tr style="border-top:1px solid #E7EBF0;">'
                             f'<td style="padding:7px 12px;font-size:13px;font-weight:600;color:{INK};">{_esc(sr.get("sector",""))}</td>'
                             f'<td style="padding:7px 8px;font-size:11px;color:#6B7280;text-transform:uppercase;text-align:right;white-space:nowrap;">{_esc(sr.get("authority",""))}</td>'
                             f'<td style="padding:7px 12px 7px 8px;font-family:Georgia,serif;font-size:14px;font-weight:700;color:{_sec_colors.get(sr_st, TAEGUK_RED)};text-align:right;white-space:nowrap;">{_esc(str(sr.get("rate","")))}</td>'
                             f'</tr>')
            sector_box = ""
            if sec_rows:
                sector_box = _box(
                    f'<div style="background:#F5F7FA;padding:7px 12px;font-size:11px;text-transform:uppercase;'
                    f'letter-spacing:1px;color:{TAEGUK_BLUE};font-weight:700;border-bottom:1px solid #DBE0E6;">Sector Rates</div>'
                    f'<table width="100%" cellpadding="0" cellspacing="0" border="0" class="tariff-sector">{sec_rows}</table>')

            # The brief carries the status and the date to watch; the sector
            # table moves to the trade page, where it sat unchanged in the
            # brief day after day. A rate that changed since the last issue
            # still appears here, under "Changed since the last issue".
            _changed = digest.get("_tariff_changes") or []
            _keys = {" ".join(_re.sub(r"[^a-z0-9 ]+", " ", str(c).lower()).split()) for c in _changed}
            changed_rows = ""
            for sr in (tariff_tracker.get("sector_rates") or []):
                k = " ".join(_re.sub(r"[^a-z0-9 ]+", " ", str(sr.get("sector", "")).lower()).split())
                if k in _keys:
                    sr_st = "ACTIVE" if sr.get("status", "ACTIVE") == "ESCALATION" else sr.get("status", "ACTIVE")
                    changed_rows += (f'<tr style="border-top:1px solid #E7EBF0;">'
                                     f'<td style="padding:7px 12px;font-size:13px;font-weight:600;color:{INK};">{_esc(sr.get("sector",""))}</td>'
                                     f'<td style="padding:7px 12px 7px 8px;font-family:Georgia,serif;font-size:14px;font-weight:700;color:{_sec_colors.get(sr_st, TAEGUK_RED)};text-align:right;white-space:nowrap;">{_esc(str(sr.get("rate","")))}</td>'
                                     f'</tr>')
            n_rates = len(tariff_tracker.get("sector_rates") or [])
            changed_box = ""
            if changed_rows:
                changed_box = _box(
                    f'<div style="background:#F5F7FA;padding:7px 12px;font-size:11px;text-transform:uppercase;'
                    f'letter-spacing:1px;color:{TAEGUK_BLUE};font-weight:700;border-bottom:1px solid #DBE0E6;">Changed since the last issue</div>'
                    f'<table width="100%" cellpadding="0" cellspacing="0" border="0" class="tariff-sector">{changed_rows}</table>')
            rates_note = (f'<div style="font-size:13px;color:#5A6472;margin-top:8px;">{n_rates} sector rates in force'
                          + (", none changed since the last issue" if not changed_rows and digest.get("_tariff_changes") is not None else "")
                          + '. Full table on the trade reference page.</div>') if n_rates else ""
            pillars.append(f'<div style="margin-top:6px;">{_pillar_h("Tariffs")}{hero}{watch}{changed_box}{rates_note}</div>')
            if sector_box:
                standing.insert(0, f'<div style="margin-top:6px;">{_pillar_h("Sector tariff rates")}{sector_box}</div>')

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
                bar = (f'<div style="font-size:13px;font-family:Georgia,serif;color:#353C48;margin-bottom:7px;">'
                       f'<span style="font-family:{MONO};color:{NAVY};font-size:14px;font-weight:700;">{_esc(announced)}</span> '
                       f'announced of {pledged} pledged, {pct_int}% fulfilled</div>'
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
                       f'<span style="font-size:13px;color:#6B7280;"> &nbsp;pledged</span></div>'
                       f'<div style="font-size:13px;color:#5A6472;line-height:1.55;margin-top:6px;">{note}</div>')

            # Deal table only lists deals officially attributed to the pledge
            # (the prompt no longer dumps unrelated corporate announcements here).
            deal_rows = ""
            new_rows = ""
            _known = [kd for kd in (investment_pkg.get("known_deals") or []) if isinstance(kd, dict)]
            for kd in _known:
                sect = _esc(kd.get("sector", ""))
                row = (f'<tr style="border-top:1px solid #E7EBF0;">'
                       f'<td style="padding:7px 12px;font-size:13px;color:{INK};"><span style="font-weight:600;">{_esc(kd.get("company",""))}</span>'
                       + (f' <span style="color:#6B7280;font-size:11px;">{sect}</span>' if sect else "")
                       + f'</td>'
                       f'<td style="padding:7px 12px 7px 8px;font-family:Georgia,serif;font-size:13px;font-weight:700;color:{UP_GREEN};text-align:right;white-space:nowrap;">{_esc(kd.get("value",""))}</td>'
                       f'</tr>')
                deal_rows += row
                if _pledge_is_new(kd, digest):
                    new_rows += row
            deal_box = ""
            if deal_rows:
                deal_box = _box(
                    f'<div style="background:#F5F7FA;padding:7px 12px;font-size:11px;text-transform:uppercase;'
                    f'letter-spacing:1px;color:{TAEGUK_BLUE};font-weight:700;border-bottom:1px solid #DBE0E6;">$350B Pledge: Selected Projects</div>'
                    f'<table width="100%" cellpadding="0" cellspacing="0" border="0" class="deal-breakdown">{deal_rows}</table>')

            # The brief shows the pledge and what is new; the full project list
            # lives on the trade page. The block printed every selected project
            # and a three-line note every day, so a reader met the same Encinal
            # row for weeks. Only a project reported in the last seven days (or
            # one the model reported from today's sources) earns a row here.
            n_sel = len(_known)
            if n_sel:
                first = _known[0]
                summary = (f'{n_sel} project{"s" if n_sel != 1 else ""} selected so far'
                           + (f', led by {_esc(first.get("company", ""))} ({_esc(first.get("value", ""))})'
                              if first.get("value") else ""))
            else:
                summary = "No projects selected yet"
            compact = (f'<div><span style="font-family:{MONO};color:{NAVY};font-size:20px;font-weight:700;">{pledged}</span>'
                       f'<span style="font-size:13px;color:#6B7280;"> &nbsp;pledged, {summary}</span></div>')
            new_box = ""
            if new_rows:
                new_box = _box(
                    f'<div style="background:#F5F7FA;padding:7px 12px;font-size:11px;text-transform:uppercase;'
                    f'letter-spacing:1px;color:{TAEGUK_BLUE};font-weight:700;border-bottom:1px solid #DBE0E6;">New this week</div>'
                    f'<table width="100%" cellpadding="0" cellspacing="0" border="0" class="deal-breakdown">{new_rows}</table>')
            pillars.append(f'<div style="margin-top:18px;">{_pillar_h("Investment: " + pledged + " pledge", accent=TAEGUK_BLUE)}'
                           f'{bar if has_progress else compact}{new_box}</div>')
            if deal_box:
                standing.append(f'<div style="margin-top:18px;">{_pillar_h("Investment: " + pledged + " pledge", accent=TAEGUK_BLUE)}{bar}{deal_box}</div>')

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
            _dir_meta = [("rok_to_us", "Korea to US", TAEGUK_RED),
                         ("us_to_rok", "US to Korea", TAEGUK_BLUE),
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
                        chip = (f'<span style="display:inline-block;font-family:Arial,sans-serif;letter-spacing:0.5px;font-size:10px;font-weight:700;'
                                f'letter-spacing:0.5px;padding:1px 5px;border-radius:3px;background:{cbg};color:{cfg};'
                                f'margin-left:6px;vertical-align:middle;">{_esc(st.upper())}</span>')
                    r_html += (f'<tr style="border-top:1px solid #EAEDF1;">'
                               f'<td style="padding:6px 10px 6px 0;font-size:13px;color:{INK};">'
                               f'<span style="font-weight:600;">{ent}</span>{chip}'
                               + (f'<div style="font-size:11px;color:#6B7280;margin-top:1px;">{sect}</div>' if sect else "")
                               + f'</td>'
                               f'<td style="padding:6px 0;font-family:{MONO};font-size:13px;font-weight:700;color:{NAVY};'
                               f'text-align:right;white-space:nowrap;vertical-align:top;">{val or "&mdash;"}</td></tr>')
                blocks += (f'<div style="font-size:11px;font-weight:700;letter-spacing:0.5px;color:{color};'
                           f'margin:12px 0 2px;">{lbl}</div>'
                           f'<table width="100%" cellpadding="0" cellspacing="0" border="0" class="ledger">{r_html}</table>')
            _led_note = ('<div style="font-size:11px;color:#6B7280;line-height:1.5;margin-top:4px;">'
                         'Corporate investment flows, separate from the $350B pledge. '
                         'MOU/LOI entries are non-binding; figures as reported, not summed.</div>')
            standing.append(f'<div style="margin-top:18px;">'
                           f'{_pillar_h("Bilateral Investment Ledger", accent=NAVY)}{blocks}{_led_note}</div>')

        # ── Pillar 3: New This Week (genuinely new deals only) ─────────────
        new_rows = ""
        for deal in deal_list:
            headline = _emphasis(_esc(deal.get("headline", "")))
            if not headline:
                continue
            value = _esc(deal.get("value", "")) if deal.get("value") else ""
            detail = _emphasis(_esc(deal.get("detail", "")))
            src2 = _esc(deal.get("source", ""))
            # The model sometimes sends the parties as a list, which printed
            # as a Python literal: ['TAIHAN CABLE & SOLUTION', '...'].
            _parties = deal.get("parties", "")
            if isinstance(_parties, (list, tuple)):
                _parties = ", ".join(str(x) for x in _parties if x)
            parties = _esc(_parties)
            url = deal.get("url", "")
            val_badge = (f'<span style="display:inline-block;font-family:{MONO};font-size:11px;font-weight:700;'
                         f'color:#fff;background:{UP_GREEN};border-radius:3px;padding:1px 6px;margin-left:6px;">{value}</span>') if value else ""
            kind = ('<span style="display:inline-block;font-family:' + MONO + ';font-size:10px;font-weight:700;'
                    'letter-spacing:0.5px;padding:1px 6px;border-radius:3px;background:#E4EFE7;color:#1E7940;margin-left:6px;">New deal</span>')
            meta = "&emsp;".join(b for b in (parties, src2) if b)
            new_rows += (f'<tr><td style="padding:9px 0;border-top:1px solid #EAEDF1;">'
                         f'<div style="font-size:13px;font-weight:700;color:{INK};line-height:1.35;">{_link_or_text(headline, url, style="color:" + INK + ";text-decoration:none;")}{val_badge}{kind}</div>'
                         + (f'<div style="font-size:13px;font-family:Georgia,serif;color:#353C48;line-height:1.45;margin-top:2px;">{detail}</div>' if detail else "")
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
            status_span = f'<span style="font-family:Arial,sans-serif;font-weight:700;letter-spacing:0.5px;color:{st_color};">{_esc(st)}</span>'
            meta = "&emsp;".join(b for b in (agency, status_span) if b)
            pol_rows += (f'<tr><td style="padding:8px 0;border-top:1px solid #EAEDF1;">'
                         f'<div style="font-size:13px;font-weight:600;color:{INK};line-height:1.35;">{head}</div>'
                         + (f'<div style="font-size:13px;font-family:Georgia,serif;color:#353C48;line-height:1.45;margin-top:2px;">{detail_text}</div>' if detail_text else "")
                         + (f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:#6B7280;margin-top:2px;">{meta}</div>' if meta else "")
                         + '</td></tr>')
        if pol_rows:
            standing.append(f'<div style="margin-top:18px;">{_pillar_h("Trade Policy Watch", accent="#5A6472")}'
                           f'<div style="font-size:11px;color:#6B7280;line-height:1.5;margin:-4px 0 8px;">'
                           f'Standing US non-tariff measures affecting Korea: ongoing status, not new this week.</div>'
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
                    f'padding:13px 0;background:#FFFFFF;border-top:2px solid {TAEGUK_BLUE};'
                    f'border-radius:3px;text-decoration:none;">'
                    f'<span style="font-family:Arial,sans-serif;font-size:10px;font-weight:700;'
                    f'letter-spacing:1.5px;text-transform:uppercase;color:{TAEGUK_BLUE};">'
                    f'Full trade reference</span>'
                    f'<span style="display:block;font-family:Georgia,serif;font-size:13px;'
                    f'color:{INK};margin-top:4px;line-height:1.45;">Sector tariff rates, all $350B pledge projects, '
                    f'the investment ledger and standing policy measures.</span></a></div>')
        digest["_trade_standing_html"] = "".join(standing)
        sections.append(f"""
        <div {_SEC}>
          <a name="trade" id="trade"></a>{_sec_label("US-Korea Trade &amp; Investment")}
          {sop_html}
          {"".join(pillars)}
          {_standing_link}
        </div>
        """)
        if DESIGN == "v2" and isinstance(us_korea, dict):
            sections[-1] = _v2_trade(us_korea, digest, _b) or sections[-1]

    # ── 10b. Capitol Hill (US Congress on Korea) ─────────────────────────
    # Directly after the US-Korea material it belongs with. Shown when there
    # is either an item or a collected hearing in the week ahead; absent
    # otherwise, which is most days.
    hill_items = digest.get("capitol_hill") or []
    _hill_ahead = hill_events(digest)[1]
    if hill_items or _hill_ahead:
        hill_html = ""
        for item in hill_items:
            if not isinstance(item, dict):
                continue
            kicker = "&emsp;".join(_esc(_str(x)) for x in (item.get("chamber"), item.get("category"),
                                                               item.get("bill")) if _str(x))
            hill_html += _item_block(
                cat=kicker,
                src=_esc(_clean_src(item.get("source", ""))),
                headline=_emphasis(_esc(item.get("headline", ""))),
                body=_emphasis(_esc(item.get("body_text", ""))),
                url=item.get("url", ""),
            )
        if _hill_ahead:
            _today = _issue_day(digest)
            rows = ""
            for ev in _hill_ahead[:4]:
                try:
                    d = datetime.strptime(str(ev["date"])[:10], "%Y-%m-%d").date()
                    when = "Today" if d == _today else d.strftime("%a %b %-d")
                except (KeyError, ValueError):
                    when = ""
                if ev.get("time"):
                    when += f", {ev['time']}"
                rows += (f'<div style="font-family:Georgia,serif;font-size:13px;line-height:1.5;'
                         f'color:{BODY_INK};margin-bottom:5px;">'
                         f'<span style="font-family:Arial,sans-serif;font-size:11px;font-weight:700;'
                         f'color:{MUTE};white-space:nowrap;">{_esc(when)}</span> &nbsp;'
                         f'{_link_or_text(_esc(hill_event_text(ev)), str(ev.get("url") or ""))}</div>')
            if DESIGN != "v2":
                hill_html += _subhead("Coming up on the Hill") + rows
            # v2 lists the week's hearings in Upcoming, with the rest of the
            # forward look (_v2_upcoming), not twice.
        if hill_html:
            sections.append(f"""
        <div {_SEC}>
          <a name="hill" id="hill"></a>{_sec_label("Capitol Hill")}
          {hill_html}
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
                    f'<span style="display:inline-block;padding:1px 5px;border-radius:3px;font-size:10px;background:#E8E8E8;font-family:Georgia,serif;color:#353C48;margin-right:3px;">{_esc(c)}</span>'
                    for c in companies[:3]
                )
                company_tags = f'<div style="margin-top:3px;">{company_tags}</div>'
            biz_html += _item_block(
                cat=_esc(_str(item.get("category", item.get("sector", "")))),
                src=_esc(_clean_src(item.get("source", ""))),
                headline=_emphasis(_esc(item.get("headline", ""))),
                body=_emphasis(_esc(item.get("body_text", ""))),
                url=item.get("url", ""),
                bar_color=biz_sector_colors.get(_str(item.get("sector", "")), TAEGUK_BLUE),
                extra_html=company_tags,
            )
        sections.append(f"""
        <div {_SEC}>
          <a name="business" id="business"></a>{_sec_label("Business &amp; Economy")}
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
            headline = _emphasis(_esc(item.get("headline", "")))
            body = _emphasis(_esc(item.get("body_text", "")))
            src = _esc(_clean_src(item.get("source", "")))
            url = item.get("url", "")
            region = _str(item.get("region_tag", ""))
            is_reaction = item.get("is_reaction_source", False)
            bar_color = nea_cat_colors.get(cat_raw, TAEGUK_BLUE)
            reaction_badge = ""
            if is_reaction:
                badge_label = "PRC SOURCE" if "China" in region else "STATE MEDIA"
                reaction_badge = f'<span style="display:inline-block;padding:1px 5px;border-radius:3px;font-size:10px;font-weight:600;color:#fff;background:#5A6472;margin-left:6px;">{badge_label}</span>'
            # "Trilateral&emsp;Trilateral" when the region tag and category coincide.
            region_txt = _esc(region) + "&emsp;" if region and region.lower() != cat_raw.lower() else ""
            nea_html += _item_block(cat=f"{region_txt}{cat}{reaction_badge}", src=src,
                                    headline=headline, body=body, url=url, bar_color=bar_color)
        sections.append(f"""
        <div {_SEC}>
          <a name="nea" id="nea"></a>{_sec_label("Northeast Asia Watch")}
          {nea_html}
        </div>
        """)

    # ── 12b. Korea and the World (beyond the US and Northeast Asia) ──────
    world_items = [i for i in (digest.get("korea_world") or []) if isinstance(i, dict)]
    if world_items:
        world_html = ""
        for item in world_items:
            kicker = "&emsp;".join(_esc(_str(x)) for x in (item.get("region"), item.get("category"))
                                       if _str(x))
            world_html += _item_block(
                cat=kicker,
                src=_esc(_clean_src(item.get("source", ""))),
                headline=_emphasis(_esc(item.get("headline", ""))),
                body=_emphasis(_esc(item.get("body_text", ""))),
                url=item.get("url", ""),
            )
        sections.append(f"""
        <div {_SEC}>
          <a name="world" id="world"></a>{_sec_label("Korea and the World")}
          {world_html}
        </div>
        """)

    # ── 12c. Public Sentiment Tracker ──────────────────────────────────
    sentiment = digest.get("public_sentiment") or {}
    if sentiment and any(sentiment.values()):
        # The measured change against the previous survey, from the series the
        # pipeline already stores. The tile used to show a bare arrow taken
        # from the model's own `trend` field: a direction with no magnitude
        # and no way to tell which survey it was measured against, which is
        # what made "vs prior" meaningless.
        try:
            from poll_history import delta as _poll_delta
            _delta = _poll_delta()
        except Exception:
            _delta = None

        def _delta_line():
            """One line under the approval figure: the change and its baseline."""
            if not _delta:
                return ""
            pts, prior_label = _delta
            if pts > 0:
                mark, colour, sign = "", UP_GREEN, "+"
            elif pts < 0:
                mark, colour, sign = "", DOWN_RED, "&minus;"
            else:
                mark, colour, sign = "No change,", MUTE, ""
            against = f" vs {_esc(prior_label)}" if prior_label else " vs prior survey"
            return (f'<div style="font-family:Arial,sans-serif;font-size:11px;'
                    f'color:{colour};margin-top:4px;white-space:nowrap;">'
                    f'{mark + " " if mark else ""}{sign}{abs(pts) if pts else 0:g} pts'
                    f'<span style="color:{MUTE};">{against}</span></div>')

        def _party_short(data, fallback):
            """The party's short English name, from the model when it sent one."""
            name = str((data or {}).get("party") or "").strip()
            for suffix in (" Party", "의 힘"):
                if name.endswith(suffix):
                    name = name[: -len(suffix)].strip()
            return name or fallback

        def _tile(label, sub, data):
            """Compact party tile: role on top, party name under it.

            The arrow is gone from these. Three tiles each carrying a coloured
            triangle put four pieces of movement on one row, and none of them
            said how much: the section read as busy without being informative.
            Party standings are a snapshot; the measured change belongs to the
            approval series, where it can be computed.
            """
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
                      <div style="font-family:Georgia,serif;font-size:22px;font-weight:700;color:{colour};margin-top:6px;line-height:1;">{val}</div>
                    </td>"""

        approval = sentiment.get("presidential_approval") or {}
        party_ruling = sentiment.get("party_ruling") or {}
        party_opp = sentiment.get("party_opposition") or {}
        party_ind = sentiment.get("party_independent") or {}
        discourse = sentiment.get("discourse_flag")

        discourse_html = ""
        if discourse:
            discourse_html = f"""
            <div class="sentiment-discourse" style="margin-top:8px;padding:6px 10px;background:#FBF0F1;border-radius:3px;border-left:3px solid {TAEGUK_RED};font-size:11px;font-family:Georgia,serif;color:#353C48;">
              <strong style="color:{TAEGUK_RED};">Discourse:</strong> {_esc(discourse)}
            </div>"""

        gallup_finding = sentiment.get("gallup_spotlight")
        spotlight_html = ""
        if gallup_finding:
            topic = _esc(str(gallup_finding.get("topic", "")))
            finding = _esc(str(gallup_finding.get("finding", "")))
            poll_date = _esc(str(gallup_finding.get("poll_date", "")))
            spotlight_html = f"""
            <div class="sentiment-spotlight" style="margin-top:10px;padding:8px 12px;background:#F0F5FB;border-radius:3px;border-left:3px solid {TAEGUK_BLUE};font-size:11px;font-family:Georgia,serif;color:#353C48;line-height:1.5;">
              <strong style="color:{TAEGUK_BLUE};">Gallup Korea Spotlight</strong>
              <span style="font-family:Arial,sans-serif;font-size:10px;color:#5A6472;margin-left:6px;">{poll_date}</span><br>
              <span style="font-weight:600;">{topic}:</span> {finding}
            </div>"""

        # Flag polling the reader should not take as this week's.
        #
        # This badge existed and had never once appeared. It parsed only
        # "Sep 11, 2026" and "Sep 11 2026", while the collector passes the
        # baseline's survey_dates straight through — which reads "week of
        # 2026-09-11". Neither format matched, poll_dt stayed None, and the
        # check silently did nothing while the brief printed a three-week-old
        # approval rating as the current one.
        #
        # Parse the shapes actually produced, pull any ISO or long-form date
        # out of a longer label, and say the age in words rather than only
        # the date: a reader scanning a dashboard reads "38%" long before
        # they read a date underneath it.
        stale_html = ""
        _v2_stale = ""
        poll_updated = (approval.get("last_updated") or "")
        if poll_updated and poll_updated != "recent":
            try:
                poll_dt = None
                _iso = _re.search(r"(\d{4})-(\d{2})-(\d{2})", poll_updated)
                if _iso:
                    poll_dt = datetime(int(_iso.group(1)), int(_iso.group(2)),
                                       int(_iso.group(3)), tzinfo=timezone.utc)
                else:
                    # "June 9-11, 2026" and "Sep 11, 2026": take the last day
                    # named, which is when the survey finished.
                    _m = _re.search(r"([A-Z][a-z]+)\s+(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?,?\s+(\d{4})",
                                    poll_updated)
                    if _m:
                        _day = int(_m.group(3) or _m.group(2))
                        for _fmt in ("%B", "%b"):
                            try:
                                _mon = datetime.strptime(_m.group(1), _fmt).month
                                poll_dt = datetime(int(_m.group(4)), _mon, _day,
                                                   tzinfo=timezone.utc)
                                break
                            except ValueError:
                                continue
                if poll_dt:
                    _age = (now - poll_dt).days
                    if _age > 7:
                        _wks = _age // 7
                        _how_old = (f"{_wks} week{'s' if _wks != 1 else ''} old"
                                    if _wks else f"{_age} days old")
                        _v2_stale = (f"Gallup Korea publishes weekly; this reading is {_how_old} "
                                     f"({_esc(poll_updated)}).")
                        stale_html = f"""
            <div style="margin-top:8px;font-size:10px;color:{TAEGUK_RED};text-align:center;">
              Gallup Korea publishes weekly; this reading is {_how_old}
              ({_esc(poll_updated)})
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
          <a name="sentiment" id="sentiment"></a>{_sec_label("Public Sentiment")}
          <table width="100%" cellpadding="0" cellspacing="0" border="0" class="sentiment-table">
            <tr>
              <td width="42%" valign="top" style="padding:4px 18px 4px 0;border-right:1px solid #E4E7EB;">
                <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#6B7280;font-family:Arial,sans-serif;">Presidential approval</div>
                <div class="hero-num" style="font-family:Georgia,serif;font-size:42px;font-weight:700;color:{TAEGUK_BLUE};line-height:1.05;margin-top:4px;">{_esc(str(approval.get("value") or "--"))}</div>
                {_delta_line()}
                <div style="font-size:11px;color:#6B7280;font-family:Arial,sans-serif;margin-top:5px;">{_esc(str(approval.get("source") or ""))}{"&emsp;" + _esc(str(approval.get("last_updated") or "")) if approval.get("last_updated") else ""}</div>
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
        if DESIGN == "v2":
            sections[-1] = (_v2_sentiment_card(sentiment, _delta, _re.sub(r"<[^>]+>", "", _spark_html).strip(),
                                               _v2_stale) or _v2_sentiment(sections[-1]))

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
                      <div style="font-family:Georgia,serif;font-size:16px;font-weight:700;color:#fff;line-height:1;">{_esc(str(cal.get("day", "")))}</div>
                    </td></tr>
                  </table>
                </td>
                <td style="padding:9px 0;vertical-align:top;">
                  <div style="font-family:Georgia,serif;font-size:14px;font-weight:700;color:#1B2A4A;">{_emphasis(_esc(cal.get("headline", "")))}</div>
                  <div style="font-family:Georgia,serif;font-size:13px;line-height:1.45;color:#353C48;margin-top:3px;">{_emphasis(_esc(cal.get("detail", "")))}</div>
                </td>
              </tr>
            </table>"""
        sections.append(f"""
        <div {_SEC}>
          <a name="upcoming" id="upcoming"></a>{_sec_label("Upcoming")}
          {up_rows}
        </div>
        """)
        if DESIGN == "v2":
            sections.pop()
    if DESIGN == "v2":
        # The forward look in one place: the model's dated events and the
        # fixed observances (korea_calendar.merge, above) with the week's
        # committee hearings, in date order, each once.
        _up = _v2_upcoming(calendar_watch, hill_events(digest)[1], _issue_day(digest))
        if _up:
            sections.append(_up)

    # ── 13. The Wire (Also Today — secondary news) ────────────────────
    combined_also = digest.get("also_today") or []
    if combined_also:
        _groups = {}
        for item in combined_also:
            key = _str(item.get("category", "")).strip() or "Other"
            _groups.setdefault(_wire_label(key), []).append(item)
        wire_html = ""
        # One group heading beats a category badge repeated on every row.
        _multi = len(_groups) > 1
        for _cat, _items in _groups.items():
            rows = "".join(
                _compact_row(cat="" if _multi else _esc(_cat),
                             headline=_emphasis(_esc(i.get("headline", ""))),
                             url=i.get("url", ""),
                             src=_esc(_clean_src(i.get("source", ""))),
                             body=_emphasis(_esc(i.get("body_text", ""))))
                for i in _items)
            wire_html += ((_subhead(_esc(_cat)) if _multi else "")
                          + rows)
        sections.append(f"""
        <div {_SEC}>
          <a name="wire" id="wire"></a>{_sec_label("The Wire")}
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
                link = (f'<a href="{_esc(url)}" style="font-size:10px;color:{TAEGUK_BLUE};text-decoration:none;">View on X</a>'
                        if url and str(url).startswith("http") else "")
                xp_html += (f'<div style="margin-bottom:9px;padding-bottom:9px;border-bottom:1px solid #E1E8F0;">'
                            f'<div style="font-size:13px;font-weight:600;color:{INK};">{name}'
                            + (f' <span style="color:#55607A;font-weight:400;">@{handle}</span>' if handle else "")
                            + f'</div>'
                            f'<div style="font-size:13px;font-family:Georgia,serif;color:#2C3E50;line-height:1.45;margin:2px 0 3px;">&ldquo;{post}&rdquo;</div>'
                            + (f'<div style="font-size:11px;color:{TAEGUK_BLUE};line-height:1.4;margin-bottom:3px;"><strong>Context:</strong> {note}</div>' if note else "")
                            + f'{link}</div>')
            if xp_html:
                sa_html += (f'<div style="margin-bottom:14px;padding:13px 0 13px 16px;background:#FFFFFF;'
                            f'border-left:3px solid {TAEGUK_BLUE};">'
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
            source_link = f'<a href="{_esc(url)}" style="font-size:10px;color:{TAEGUK_BLUE};text-decoration:none;">Source</a>' if url and url != "#" and url.startswith("http") else ""
            sa_html += f"""
            <div style="margin-bottom:12px;padding:12px;background:#F8F9FA;border-radius:6px;border-left:3px solid {badge_color};">
              <table cellpadding="0" cellspacing="0" border="0" style="margin-bottom:6px;">
                <tr>
                  <td width="36" style="vertical-align:middle;">
                    <div style="width:36px;height:36px;border-radius:50%;background:{badge_color};color:#fff;text-align:center;line-height:36px;font-size:13px;font-weight:700;">{initials}</div>
                  </td>
                  <td style="padding-left:8px;vertical-align:middle;">
                    <div style="font-size:13px;font-weight:600;color:{INK};">{who}</div>
                    <div style="font-size:10px;color:#6B7280;">{handle}</div>
                  </td>
                </tr>
              </table>
              <p style="margin:0 0 6px 0;font-size:13px;line-height:1.5;font-family:Georgia,serif;color:#353C48;font-style:italic;">&ldquo;{quote}&rdquo;</p>
              {"<p style='margin:0;font-size:11px;color:" + TAEGUK_BLUE + ";'><strong>Analyst:</strong> " + note + "</p>" if note else ""}
              {source_link}
            </div>"""
        # Op-Eds. A column and a peer-reviewed paper are different kinds of
        # evidence; the section used to run them together behind one rule.
        if opeds:
            sa_html += _subhead("Commentary")
        for op in opeds:
            src = _esc(op.get("source", ""))
            title = _esc(op.get("headline", op.get("title", op.get("central_argument", ""))))
            summary = _emphasis(_esc(op.get("summary", "")))
            url = op.get("url", "")
            sa_html += f"""
            <div style="margin-bottom:13px;padding-left:12px;border-left:3px solid {TAEGUK_BLUE};">
              <div style="font-family:Arial,sans-serif;font-size:10px;font-weight:700;letter-spacing:0.5px;text-transform:uppercase;color:{TAEGUK_BLUE};">{src}</div>
              <div style="font-family:Georgia,serif;font-size:14px;font-weight:600;color:{INK};line-height:1.35;margin-top:2px;">
                {_link_or_text(title, url)}
              </div>
              <div style="font-size:13px;line-height:1.5;font-family:Georgia,serif;color:#353C48;margin-top:3px;">{summary}</div>
            </div>"""
        # Academic
        if academic:
            sa_html += _subhead("Research")
        for a in academic:
            src = _esc(a.get("source", ""))
            tier = _esc(a.get("journal_tier", ""))
            title = _esc(a.get("headline", a.get("title", "")))
            summary = _emphasis(_esc(a.get("summary", "")))
            implication = _esc(a.get("policy_implication", ""))
            url = a.get("url", "")
            read_link = f'<a href="{_esc(url)}" style="font-size:11px;color:{TAEGUK_BLUE};">Read</a>' if url and url != "#" and url.startswith("http") else ""
            title_html = f'<div style="font-family:Georgia,serif;font-size:14px;font-weight:600;color:{INK};line-height:1.35;margin:2px 0 3px;">{_link_or_text(title, url)}</div>' if title else ""
            _tier_chip = (f'<span style="display:inline-block;margin-left:6px;padding:1px 6px;'
                          f'border-radius:3px;background:#E7EBF0;font-family:Arial,sans-serif;'
                          f'font-size:10px;font-weight:700;letter-spacing:0.5px;color:#55607A;">{tier}</span>'
                          if tier else "")
            sa_html += f"""
            <div style="margin-bottom:13px;padding-left:12px;border-left:3px solid #55607A;">
              <div style="font-family:Arial,sans-serif;font-size:10px;font-weight:700;letter-spacing:0.5px;text-transform:uppercase;color:#55607A;">{src}{_tier_chip}</div>
              {title_html}
              <div style="font-size:13px;line-height:1.4;font-family:Georgia,serif;color:#353C48;">{summary}</div>
              {"<div style='font-size:11px;color:" + TAEGUK_BLUE + ";margin-top:3px;'><strong>Implication:</strong> " + implication + "</div>" if implication else ""}
              {read_link}
            </div>"""
        if sa_html.strip():
            sections.append(f"""
        <div {_SEC}>
          <a name="analysis" id="analysis"></a>{_sec_label("Analysis")}
          {sa_html}
        </div>
        """)
            if DESIGN == "v2":
                sections[-1] = _v2_analysis(social, opeds, academic, x_posts)

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
            ir_headline = _emphasis(_esc(imagery_report.get("headline", "")))
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
                            _src_parts.append(f'<a href="{_esc(s_url)}" style="font-size:11px;font-family:{MONO};color:#6B7280;text-decoration:none;">{s_label}</a>')
                        else:
                            # No arrow without a link: it promised a click that went nowhere.
                            _src_parts.append(f'<span style="font-size:11px;font-family:{MONO};color:#6B7280;">{s_label}</span>')
                    else:
                        _src_parts.append(f'<span style="font-size:11px;font-family:{MONO};color:#6B7280;">{_esc(str(s))}</span>')
                source_links_html = "<div style='margin-top:8px;'>" + "&emsp;".join(_src_parts) + "</div>"
            # v2: the outlets are already listed as links under the body, and
            # the label repeats the headline, so the kicker is the label kind
            # and the date. Together they ran to three lines of capitals.
            ir_kicker = (f"New imagery reports, {ir_date}" if DESIGN == "v2"
                         else f"{ir_source}&emsp;{ir_date}&emsp;{ir_label}")
            bp_ids_html = ""
            if ir_bp_ids:
                bp_ids_html = "<div style='margin-top:6px;font-size:11px;color:#6B7280;'>" + ", ".join(_esc(str(b)) for b in ir_bp_ids) + "</div>"
            img_report_html = f"""
            <div style="margin-bottom:20px;padding:16px;border-left:3px solid {TAEGUK_BLUE};">
              <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:{TAEGUK_BLUE};font-weight:600;margin-bottom:6px;">{ir_kicker}</div>
              <div style="font-size:17px;font-weight:700;color:{INK};line-height:1.3;margin-bottom:8px;">{ir_headline}</div>
              <div style="font-size:13px;line-height:1.6;font-family:Georgia,serif;color:#353C48;">{ir_body}</div>
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

        _changes = digest.get("_bp_changes")
        _all_sites = list(locations)
        _fresh, _quiet = [], []
        if isinstance(_changes, list):
            # Only sites with a new report since the last issue. The full
            # list moves to its own page: eleven cards of carried-forward
            # notes were the longest section in the brief, around 800 words
            # most days, and almost all of it unchanged from the day before.
            _keys = set(_changes)
            _fresh = [l for l in locations if l.get("name") in _keys]
            _quiet = [l for l in locations if l.get("name") not in _keys]
            if DESIGN == "v2":
                # By name with the punctuation ignored: english.apply turns
                # "THAAD Site — Seongju County" into "THAAD Site, Seongju
                # County" after the change list is taken, and a site with new
                # reporting then fell out of the watch. (Classic keeps its
                # exact match, so its bytes do not change.)
                _nk = lambda n: " ".join(_re.sub(r"[^a-z0-9]+", " ", str(n or "").lower()).split())
                _keys = {_nk(c) for c in _changes}
                _fresh = [l for l in locations if _nk(l.get("name")) in _keys]
                _quiet = [l for l in locations if _nk(l.get("name")) not in _keys]
        for _loc in ([] if isinstance(_changes, list) else locations):
            _age = _age_days(_loc)
            if _age is not None and _age <= _FRESH_DAYS:
                _fresh.append(_loc)
            else:
                _quiet.append(_loc)
        # Never render an empty section: if nothing is fresh, show whatever is
        # newest so the reader still sees the watch list.
        if not _fresh and locations and not isinstance(_changes, list):
            _dated = [(l, _age_days(l)) for l in locations]
            _dated = [(l, a) for l, a in _dated if a is not None]
            if _dated:
                _dated.sort(key=lambda t: t[1])
                _fresh = [_dated[0][0]]
                _quiet = [l for l in locations if l is not _fresh[0]]
        quiet_html = ""
        if isinstance(_changes, list):
            _b = (digest.get("web_url", "")[:-len("latest.html")]
                  if digest.get("web_url", "").endswith("latest.html") else "")
            _link = (f' <a href="{_esc(_b + "locations.html")}" style="color:{TAEGUK_BLUE};">'
                     f'Full location watch</a>' if _b else "")
            quiet_html = (f'<div style="font-size:13px;color:#5A6472;margin-top:10px;'
                          f'padding-top:9px;border-top:1px solid #EAEAEA;">'
                          + (f'{len(_quiet)} other monitored site{"s" if len(_quiet) != 1 else ""}: '
                             f'no new reporting since the last issue.' if _fresh else
                             f'No new reporting on any of the {len(_all_sites)} monitored sites since the last issue.')
                          + f'{_link}</div>')
        elif _quiet:
            _oldest = ""
            _dates = sorted(str(l.get("last_source_date", ""))[:7]
                            for l in _quiet if l.get("last_source_date"))
            if _dates:
                _oldest = f", oldest report {_esc(_dates[0])}"
            quiet_html = (f'<div style="font-size:11px;color:#6B7280;margin-top:10px;'
                          f'padding-top:9px;border-top:1px solid #EAEAEA;">'
                          f'{len(_quiet)} other monitored site{"s" if len(_quiet) != 1 else ""}: '
                          f'no new imagery in the last {_FRESH_DAYS} days{_oldest}.</div>')
        locations = _fresh

        # BP Monitored Locations — 2-column card grid with status context
        # Status is carried by the rule and the eyebrow, not by a tinted block.
        # Tinting the whole card made the two thirds of sites that are simply
        # being watched read as greyed out, and put the loudest colour behind
        # the longest text.
        # The second value was a background wash. Every card is white now and
        # status is carried by the top rule and the label, so the wash is gone
        # and the colour is used once rather than three times per card.
        _badge_styles = {
            "normal": ("#6B7280", "#FFFFFF", "MONITORING"),
            "activity": (TAEGUK_BLUE, "#FFFFFF", "ACTIVITY"),
            "elevated": ("#9A5B00", "#FFFFFF", "ELEVATED"),
            "alert": (TAEGUK_RED, "#FFFFFF", "ALERT"),
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
        if DESIGN == "v2" and elevated_count:
            # Name them: "2 of 11 sites at elevated or alert status" over a
            # single site at "Activity" read as if the count were wrong.
            _hot = [_esc(_re.sub(r"\s*[–—]\s*", "-", str(l.get("name") or "")))
                    for l in _all_locs if l.get("status", "normal") in ("elevated", "alert")]
            summary_html = (f'<div style="font-size:12px;line-height:1.5;color:#6B7280;margin-top:6px;margin-bottom:12px;">'
                            f'Elevated or alert, {elevated_count} of {len(_all_locs)} sites: {"; ".join(_hot)}.</div>')

        def _loc_grid(locations):
            loc_cards = ""
            _cols = 1 if DESIGN == "v2" else 2     # one column in v2, as ROK Government
            for i in range(0, len(locations), _cols):
                row_cards = ""
                for j in range(i, min(i + _cols, len(locations))):
                    loc = locations[j]
                    name = _esc(loc.get("name", ""))
                    status = loc.get("status", "normal")
                    note = _emphasis(_esc(loc.get("note", "")))
                    last_source_date = _esc(loc.get("last_source_date", ""))
                    direction = loc.get("direction", "")
                    b_color, b_bg, b_label = _badge_styles.get(status, ("#7F8C8D", "#F5F6F7", "MONITOR"))
                    if direction == "up":
                        b_label += ", RISING"
                    elif direction == "down":
                        b_label += ", EASING"
                    # The status sits above the name on its own line. Sharing a
                    # line, a long site name pushed the status onto a second row
                    # inside a half-width column, so it landed under the name and
                    # read as part of it.
                    status_badge = (f'<div style="font-family:Arial,sans-serif;font-size:10px;'
                                    f'font-weight:700;color:{b_color};letter-spacing:1.5px;'
                                    f'text-transform:uppercase;margin-bottom:5px;">{b_label}</div>')
                    # Note rendering — style differently for carried-forward vs active
                    note_html = ""
                    if note and "no new reporting" in note.lower():
                        note_html = (f'<div style="font-family:Georgia,serif;font-size:13px;'
                                     f'line-height:1.5;color:{MUTE};margin-top:5px;'
                                     f'font-style:italic;">{note}</div>')
                    elif note:
                        # 13px Georgia, like every other piece of body copy. At
                        # 11px the substance of the panel was the smallest text in
                        # the brief.
                        note_html = (f'<div style="font-family:Georgia,serif;font-size:13px;'
                                     f'line-height:1.5;color:{BODY_INK};margin-top:5px;">{note}</div>')
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
                                stale_flag = (f' <span style="color:#9A5B00;">, no recent reporting '
                                              f'(~{_age // 30} mo)</span>')
                        except (ValueError, TypeError):
                            pass
                    last_html = (f'<div style="font-family:Arial,sans-serif;font-size:11px;'
                                 f'color:{MUTE};margin-top:7px;">imagery as of '
                                 f'<span style="font-family:{MONO};">{last_source_date}</span>'
                                 f'{stale_flag}</div>'
                                 if last_source_date and last_source_date != "unknown" else "")
                    row_cards += f"""
                    <td style="width:50%;padding:4px;vertical-align:top;" height="100%">
                      <!-- The card fills its cell. Two <td>s in a row are already
                           the same height, but a <div> inside one only grows to fit
                           its own text, so a short note left a stub card beside a
                           tall one and the row looked broken. A nested table set to
                           height:100% stretches, which is the one way to do this
                           that Outlook honours. -->
                      <table width="100%" cellpadding="0" cellspacing="0" border="0" height="100%" style="height:100%;">
                        <tr><td style="background:#FFFFFF;border:1px solid #E4E7EB;border-top:2px solid {b_color};padding:13px 15px;vertical-align:top;">
                          {status_badge}
                          <div style="font-family:Georgia,serif;font-size:14px;font-weight:700;color:{INK};line-height:1.3;">{name}</div>
                          {note_html}
                          {last_html}
                        </td></tr>
                      </table>
                    </td>"""
                if len(locations) - i == 1 and _cols == 2:
                    row_cards += '<td style="width:50%;padding:4px;"></td>'
                loc_cards += f"<tr>{row_cards}</tr>"
            return loc_cards

        loc_cards = _loc_grid(locations)
        if isinstance(_changes, list):
            digest["_locations_standing_html"] = (
                f'{summary_html}<table width="100%" cellpadding="0" cellspacing="0" border="0" '
                f'class="loc-grid">{_loc_grid(_all_sites)}</table>')

        sections.append(f"""
        <div {_SEC}>
          <a name="satellite" id="satellite"></a>{_sec_label("Satellite &amp; Location Watch")}
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
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:2px;color:rgba(255,255,255,0.95);margin-bottom:6px;font-weight:600;">On This Day&emsp;<span style="font-family:{MONO};">{otd_date}</span></div>
          <div style="font-size:13px;color:rgba(255,255,255,0.85);line-height:1.5;font-family:Georgia,serif;">{otd_event}</div>
          <div style="font-size:11px;color:rgba(255,255,255,0.6);font-style:italic;margin-top:4px;line-height:1.4;">{otd_rel}</div>
        </div>"""
    otd_block = ""
    if on_this_day:
        otd_block = f"""
      <tr><td style="padding:20px 32px 8px;">
        <div style="font-family:Arial,sans-serif;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:2px;color:rgba(255,255,255,0.95);padding-bottom:7px;margin-bottom:11px;border-bottom:1px solid rgba(255,255,255,0.18);">On This Day</div>
        <div style="font-family:Georgia,serif;font-size:14px;line-height:1.55;color:rgba(255,255,255,0.88);"><strong style="color:{BLUE_ON_NAVY};">{otd_date}</strong> &nbsp; {otd_event}</div>
        {"<div style='font-family:Georgia,serif;font-size:13px;color:rgba(255,255,255,0.6);font-style:italic;margin-top:5px;'>" + otd_rel + "</div>" if otd_rel else ""}
      </td></tr>"""
    sections.append(f"""
    <!-- Black, not the band colour. The accent belongs to the masthead: used
         at both ends it stops being identity and becomes decoration, and the
         brief gains a second thing competing for the eye at the moment it
         should be closing. The hierarchy runs identity, then why you have
         this, then what you can do with it, then the legal line - and the
         legal line breaks onto white so the document ends rather than
         trailing off. -->
    <table width="100%" cellpadding="0" cellspacing="0" border="0" class="sec footer" style="background:#14181F;border-top:3px solid {TAEGUK_RED};">
      {otd_block}
      <tr><td style="padding:26px 32px 6px;text-align:center;">
        <!-- CSIS Korea Chair lockup, built in HTML rather than as an image:
             mail clients block images by default, and a blocked logo is a
             broken logo. This always renders, scales, and stays legible in
             dark mode. -->
        <table class="lockup" cellpadding="0" cellspacing="0" border="0" align="center" style="margin:0 auto;"><tr>
          <td style="padding-right:14px;font-family:Georgia,'Times New Roman',serif;font-size:38px;letter-spacing:3px;color:#FFFFFF;line-height:1;">CSIS</td>
          <td style="border-left:1px solid rgba(255,255,255,0.45);padding:3px 14px;font-family:Arial,sans-serif;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:rgba(255,255,255,0.82);line-height:1.4;text-align:left;">Geopolitics and Foreign<br>Policy Department</td>
          <td style="border-left:1px solid rgba(255,255,255,0.45);padding:3px 0 3px 14px;font-family:Arial,sans-serif;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:rgba(255,255,255,0.82);line-height:1.4;text-align:left;">Korea<br>Chair</td>
        </tr></table>
        <div style="font-family:Georgia,serif;font-size:13px;color:rgba(255,255,255,0.72);margin-top:14px;">Washington, D.C.</div>
      </td></tr>
      <tr><td style="padding:16px 32px 4px;text-align:center;">
        <div style="font-family:Georgia,serif;font-size:12px;line-height:1.6;color:rgba(255,255,255,0.80);max-width:none;margin:0 auto;white-space:normal;">
          You are receiving the Korea Daily Brief as a member of the CSIS Korea Chair distribution list.
        </div>
      </td></tr>
      <tr><td style="padding:14px 32px 4px;text-align:center;">
        <a class="pill" href="{_esc(_issue_file(digest, _b, "html") or web_url)}" style="{_foot_btn}">Read online</a>
        {f'<a class="pill" href="{_esc(digest["audio_url"])}" style="{_foot_btn}">Listen</a>' if digest.get("audio_url") else ""}
        <a class="pill" href="{_esc(archive_url)}" style="{_foot_btn}">Past issues</a>{_footer_trade}
      </td></tr>
      <tr><td style="padding:18px 32px 22px;text-align:center;">
        <div style="border-top:1px solid rgba(255,255,255,0.14);padding-top:14px;text-align:center;font-family:Georgia,serif;font-size:13px;line-height:1.6;color:rgba(255,255,255,0.72);max-width:520px;margin:0 auto;">
          This newsletter is automatically generated, so it may contain errors. Please check all information and sources before citing.
          To report errors or other issues, please contact Andy Lim at <a href="mailto:alim@csis.org" style="color:rgba(255,255,255,0.95);">alim@csis.org</a>.
        </div>
        <div style="margin-top:16px;">
          <a href="#top" style="font-family:Arial,sans-serif;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:rgba(255,255,255,0.95);text-decoration:none;">Back to top</a>
        </div>
      </td></tr>
    </table>
    <table width="100%" cellpadding="0" cellspacing="0" border="0" class="footer-end" style="background:#FFFFFF;">
      <tr><td style="padding:12px 32px 18px;text-align:center;font-family:Arial,sans-serif;font-size:10px;letter-spacing:0.5px;color:#6B7280;">
        &copy; {now.year} Center for Strategic and International Studies&emsp;{_issue_meta}generated {gen_time}
      </td></tr>
    </table>
    """)
    if DESIGN == "v2":
        sections[-1] = _v2_footer(digest, now)
        sections.insert(len(sections) - 1, _v2_signoff(digest))

    # Resolve the navigation placeholder now that every section is known. At a
    # 1,600-2,000 word target the brief is too long to scan end to end and the
    # only link was "back to top". A quiet day that drops sections simply gets
    # fewer links, and fewer than four suppresses the row entirely.
    # Label and anchor in document order. "Top Stories" pointed at #overnight,
    # so the one link a reader is most likely to try landed a section past
    # where it said it would. Every pair here is checked against the anchor the
    # section actually emitted, below.
    _NAV = [("Top Stories", "top-stories"), ("Overnight", "overnight"),
            ("Pyongyang", "kcna"), ("Seoul", "rok-gov"),
            ("Trade", "trade"), ("Markets", "business"),
            ("Polling", "sentiment"), ("Upcoming", "upcoming"),
            ("Analysis", "analysis"), ("Satellite", "satellite")]
    if DESIGN == "v2":
        sections = _v2_order([_v2_restyle(s, _v2_more) for s in sections])
    body = "\n".join(sections)
    if DESIGN == "v2":
        body = _v2_finish(body, next(iter(_v2_more.values()), "").split("#")[0])
    _links =[f'<a href="#{_a}" style="color:{TAEGUK_BLUE};text-decoration:underline;'
              f'text-underline-offset:2px;white-space:nowrap;">{_l}</a>'
              for _l, _a in _NAV if f'a name="{_a}"' in body]
    _nav_html = ""
    if len(_links) >= 4:
        # Unlabelled and unadorned, the row read as a subtitle rather than a
        # menu, so it went unused. It is now named and the links are underlined.
        _nav_html = ('<div class="nav-row sec" style="background:#F7F8FA;'
                     'border-bottom:1px solid #E4E7EB;padding:9px 32px;'
                     'text-align:center;font-family:Arial,sans-serif;'
                     'font-size:11px;line-height:1.9;color:#6B7280;">'
                     '<span style="font-size:10px;font-weight:700;'
                     'text-transform:uppercase;letter-spacing:1.5px;'
                     'color:#6B7280;">In this issue &nbsp;</span>'
                     + '&emsp;'.join(_links) + '</div>')
    body = body.replace("%%NAV%%", _nav_html)

    # Count what the body actually says, then stamp it into the masthead.
    word_count = _count_rendered_words(_v2_unchrome(body) if DESIGN == "v2" else body)
    read_min = max(1, round(word_count / 250))
    body = (body.replace("%%WORDS%%", f"{word_count:,}")
                .replace("%%READMIN%%", str(read_min)))
    digest["_word_count"] = word_count      # run.py's floor check reads this
    if DESIGN == "v2":
        _v2_src["_word_count"] = word_count

    html = f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <!-- Tell the client this brief handles its own theming. Without these, a
       dark-mode client applies its own inversion heuristics, and on a
       FORWARDED copy where the <style> block carrying the dark rules has
       been stripped, the result is a mixture: inline colours such as the
       black footer survive while everything around them is recoloured by the
       client. Declaring both schemes is what stops that guesswork. -->
  <meta name="color-scheme" content="light dark">
  <meta name="supported-color-schemes" content="light dark">
  <title>Korea Daily Brief, {_esc(date_str)}</title>
  <style type="text/css">
    /* Reset */
    body, table, td, div, p {{ margin:0; padding:0; }}
    img {{ border:0; display:block; }}
    /* Print - keep FULL colors and the exact on-screen look; only drop page
       chrome (shadow, page margins). print-color-adjust forces browsers to
       print background colors instead of stripping them. Works when printing
       the archived web page or the email via the browser's Print / Save as PDF. */
    @page {{ margin: 12mm; }}
    @media print {{
      * {{ -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; color-adjust: exact !important; }}
      html, body {{ background:#FFFFFF !important; }}
      .wrapper {{ box-shadow:none !important; width:680px !important; max-width:680px !important; margin:0 auto !important; }}
      a {{ text-decoration:none !important; }}
      /* Let everything flow across page breaks - avoiding breaks pushes content
         that doesn't fit to the next page, leaving big empty gaps. */
      * {{ page-break-inside: auto !important; }}
      /* Chrome is interface, not brief: a printed page carrying a "Read
         online" button bar and a jump menu is printing the controls. */
      .util-row, .nav-row, .no-print {{ display:none !important; }}
    }}
    /* Mobile responsive - one declaration per pattern; no duplicates.
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
      /* One nameplate size on a phone across all four briefs. This was the
         only masthead that never shrank, so it ran wider than its neighbours
         on the same screen. */
      h1 {{ font-size:22px !important; }}
      .mast-main {{ display:block !important; width:100% !important; }}
      .mast-meta {{ display:block !important; text-align:left !important;
        padding-top:8px !important; }}
      .mast-meta div {{ white-space:normal !important; }}
      /* The CSIS lockup is three cells side by side with rules between them.
         Its min-content width is 293px, which with the footer padding put a
         325px floor under the whole table - the last thing still forcing a
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
      /* The two label cells only. ".lockup td" also caught the CSIS
         wordmark and set it at 10px, smaller than the labels beside it. */
      .cal-table div[style*="font-size:10px"], .lockup td + td {{ font-size:10px !important; }}
      .sec, .footer {{ padding:16px 16px !important; }}
      /* (A4) Masthead keeps presence on phones */
      h1 {{ font-size:22px !important; }}
      h2 {{ font-size:13px !important; }}
      h3 {{ font-size:14px !important; }}
      .key-stat-num {{ font-size:26px !important; }}
      /* (A10) Market strip STAYS 3-across on mobile - smaller mono, tighter pad */
      .mkt-table td {{ padding:8px 4px 10px !important; }}
      .mkt-table div[style*="font-size:16px"] {{ font-size:14px !important; }}
      .mkt-table div[style*="font-size:14px"] {{ font-size:13px !important; }}
      /* (A11) Grids stack - declared once each */
      /* Child selectors only. A descendant selector also reached the td
         inside each card, zeroed its padding, and the text sat flush against
         the card's fill on every phone. */
      .loc-grid > tbody > tr > td, .gov-grid > tbody > tr > td {{ display:block !important; width:100% !important; padding:5px 0 !important; }}
      .loc-grid > tbody > tr, .gov-grid > tbody > tr {{ display:block !important; }}
      .loc-grid div[style*="font-size:10px"] {{ font-size:11px !important; }}
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
      /* Trade dashboard strip - stays 3-across like the market strip */
      .trade-dash td {{ padding:9px 4px 10px !important; }}
      .trade-dash span[style*="font-size:22px"] {{ font-size:18px !important; }}
      .trade-dash span[style*="font-size:13px"] {{ font-size:11px !important; }}
      /* Tariff sector + trade policy tables - stack */
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
      /* (A2) Legibility floor - real declarations only */
      body, td, div, p, span {{ -webkit-text-size-adjust:100%; }}
      div[style*="font-size:10px"], span[style*="font-size:10px"] {{ font-size:11px !important; }}
      /* (A1) Touch targets via min-height alone; no line-height bloat */
      a {{ min-height:44px; }}
      p a, div a, td a {{ min-height:auto; padding:6px 0; }}
      img {{ max-width:100% !important; height:auto !important; }}
    }}
    /* Tablet breakpoint - tighten padding, keep grids side-by-side */
    @media only screen and (min-width: 621px) and (max-width: 768px) {{
      .wrapper {{ width:100% !important; max-width:680px !important; }}
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
  <!-- Centered TABLE wrapper, fluid up to 680px. It was fixed at 680px with
       max-width:100%, which needs the mobile media query to shrink: a table's
       percentage max-width inside an auto-width cell is ignored, so when a
       client stripped the <style> block the brief stayed 680px wide on a
       phone. Outlook, which ignores max-width, gets the fixed ghost table. -->
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0;padding:0;background:#F2F3F5;">
    <tr>
      <td align="center" valign="top" style="padding:0;">
        <!--[if mso]><table width="680" cellpadding="0" cellspacing="0" border="0" align="center"><tr><td><![endif]-->
        <table role="presentation" class="wrapper" width="680" cellpadding="0" cellspacing="0" border="0" align="center" style="width:100%;max-width:680px;margin:0 auto;background:#FFFFFF;font-family:Arial,Helvetica,sans-serif;box-shadow:0 2px 20px rgba(0,0,0,0.08);">
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
    if DESIGN == "v2":
        return _v2_page(html, _v2_preheader(_v2_src), _v2_base(_v2_src))
    return _with_preheader(html, _v2_preheader(digest)) if not PRINT else html


def _with_preheader(html: str, preheader: str) -> str:
    """Put the inbox preview line first in the body, hidden.

    Without it Gmail previews the first text it finds, which was the utility
    bar: "For Internal Use Only Read online Download PDF Past issues". The run
    of joiners after the line keeps the client from padding the preview with
    the masthead's text.
    """
    if not preheader:
        return html
    b = html.find("<body")
    b = html.find(">", b) + 1
    if b <= 0:
        return html
    # Georgia and the body's own colour, so the hidden line adds no typeface
    # and no contrast failure to what the visual checks measure.
    return (html[:b] + '<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;'
            f'font-family:Georgia,serif;">{_esc(preheader)}' + "&zwnj;&nbsp;" * 24 + '</div>' + html[b:])


# ── Design v2 ──────────────────────────────────────────────────────────────
# Selected by DESIGN = "v2". The same fields as classic, in the design system
# of the CSIS sister newsletters (the China Room Engagement Brief). Everything
# specific to it lives in this block; render() calls in at a handful of
# marked points.
#
#   * A grey ground with each section a card; the gaps are the dividers.
#     Each card opens with a full-width navy bar: a muted blue Georgia
#     section number, a hairline, then the name in white capitals (_v2_card turns a
#     classic section into one). Every bar is plain navy and every card
#     white but the glance's tint and the stat's blue body.
#   * The top is an internal-use strip with the issue links, a navy band
#     holding one row: the official CSIS wordmark (an image with Georgia
#     alt text; Georgia text when there is no web URL) and the brief's name
#     in an outlined box as live text, then the date, number and read time,
#     the Listen card, then a card with a plain two-line row of contents
#     links (no numbers, one face). A hidden preheader opens the body (_v2_preheader).
#   * Stat of the day follows Overnight: the navy bar over a blue body. ROK Government is a
#     grid of agency cards; Public Sentiment classic's approval figure beside
#     three party boxes, the trend line under both; trade a
#     tracker table. The sign-off card is black, the footer navy with the
#     Korea Chair lockup.
#   * Items carry a teal kicker (source, then whatever category adds
#     meaning, then a date where the data has one; red for an alert item, as
#     classic marks them), a Georgia headline and the sans body, divided by
#     hairlines. Analysis is a research list; Upcoming and the Hill schedule
#     are a calendar; standing pages are outlined buttons.
#   * Kept from classic: the serif headline over a sans body, the glance's
#     pale blue tint with a left rule and its navy numbered circles, the
#     company chips under business items, the red alert kicker, the
#     "Bottom line" callout and the Stat of the Day's serif figure.
#     Pyongyang Watch is a card like the rest, not classic's navy panel.
#   * Two faces where the client has no web fonts (Gmail, Outlook): the
#     platform sans for body and furniture, Georgia for headlines and the
#     figures. Where it loads them (Apple Mail, the web page, the PDF), all
#     of it is Synthese, the CSIS brand face (_v2_font_css, _v2_print_head).
#     No size is larger than classic's: top
#     stories 16px, other headlines 15px at most. No arrows, dots or emoji.
#   * The tracker facts (KCNA watch flag trend, provocations logged) sit in
#     Pyongyang Watch (_v2_status_facts); the sites with new reporting are
#     Satellite & location watch's. The sign-off card closes the brief with
#     tomorrow's scheduled items and the reply address.
#   * Only top stories run in full. Every other item keeps up to two
#     sentences or about fifty words, whichever comes first (_v2_lead, cut
#     at a real sentence end), and the contents card links to the issue's
#     web page; FULL_TEXT turns this off for the web.
#   * Sections run in reading priority, not in the order they were added to
#     the code (_V2_ORDER).
#   * Nothing depends on the stylesheet. Gmail drops <style> for some accounts
#     and on some forwards; without it the page still fits a 320px screen,
#     because the number strip wraps by itself and nothing is nowrap wider
#     than a phone.
#   * Dark mode: v2's own colours have their own maps (_V2_DARK_*), written
#     into v2's stylesheet so classic's stays byte-identical.
#
# Classic sections are restyled in one pass (_v2_restyle) rather than edited,
# so a section added later in the house card style comes out in v2 as well.

# Two families, everywhere in v2: one sans stack and Georgia.
#
# The sans is the platform's own UI face, which reads best at 13-14px on a
# screen: San Francisco on Apple devices (-apple-system, BlinkMacSystemFont),
# Segoe UI on Windows and in Outlook, Roboto on Android (as sans-serif), then
# Arial. The names are unquoted, which CSS allows, because a quote would
# break the double- and single-quoted style attributes it is written into.
# v2 used to carry three sans stacks (classic's body stack, its own, and one
# with Korean faces on the wrapper); the brief has no Korean text outside a
# translated quote, so one stack serves the page.
#
# Georgia sets the headlines, the figures and the CSIS letters. "Times" is not
# in the stack: where Georgia is missing (Linux, ChromeOS, the PDF runner) it
# resolved to Times New Roman's clone. The space after the comma is
# deliberate: it keeps v2's own serif distinct from classic's
# "Georgia,serif", which _v2_style turns into the sans.
#
# Roboto and Helvetica Neue are not named: Android resolves sans-serif to
# Roboto anyway, and every Mac reader reaches San Francisco through the
# first two names. The stack is written about eighty times per issue, and
# the two names were 1.8KB of an email held under Gmail's clip.
_V2_SANS = "-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif"
_V2_SERIF = "Georgia, serif"      # headlines, figures and the CSIS letters
_V2_KO = _V2_SANS                 # kept for callers; the Korean faces are gone

# The CSIS newsletter palette, as in the China Room Engagement Brief.
_V2_NAVY = "#001F59"      # masthead, section bars, figures, buttons, footer
# Kickers and category labels. A shade darker than the reference's #007DAD
# (4.6:1 on white), which fell to 4.3:1 on the family tints below; this is
# 5.7:1 on white and 5.2:1 on the palest tint.
_V2_TEAL = "#006E9A"
_V2_INK = "#111418"       # headlines
_V2_BODY = "#2A2E35"      # running text
_V2_META = "#5F6670"      # meta, months, read time
_V2_GROUND = "#E6E9EE"    # the page behind the cards
_V2_HAIR = "#E3E6EA"      # the rule between items
_V2_FOOT = "#DCE4EC"      # footer type on navy
# Headline links in ink, undecorated, as in the reference: the headline is
# the link, and a rule under sixty headlines was the heaviest mark on a page.
_V2_LINK = f"color:{_V2_INK};text-decoration:none;"
# Classic's editorial signature: a serif headline over a sans body, which
# scans faster than one face for both. 15px, classic's size for an item.
_V2_HEAD = f"font-family:{_V2_SERIF};font-size:15px;font-weight:700;line-height:1.3;color:{_V2_INK};"
# The glance as classic sets it: a pale blue ground with a rule down the left.
_V2_TINT = "#EDF2FA"
_V2_TINT_RULE = "#D3DCE9"     # a hairline that still shows on the tint
_V2_ACCENT = "#0047A0"
# Northeast Asia categories classic paints red because of what they are, not
# their sector. Their kicker is red in v2 (classic's own alert red, 5.2:1).
_V2_ALERT_CATS = {"japan-history", "territorial", "thaad-retaliation", "china-coercion",
                  "china-military", "russia-weapons", "russia-military", "russia-sanctions"}
# A section's outer box before _v2_card turns it into a card. Kept for
# the KCNA panel, which builds its own wrapper.
_V2_SEC = (f'style="padding:22px 32px 24px;font-family:{_V2_SANS};" class="sec"')

# Classic's greys and accent, as the CSIS palette spells them. Only `color:`
# declarations are rewritten, never a background or a border.
_V2_RECOLOR = {
    "#1A222E": _V2_INK, "#1B2A4A": _V2_INK, "#14181F": _V2_INK,
    "#353C48": _V2_BODY, "#2C3E50": _V2_BODY, "#2C3540": _V2_BODY,
    "#6B7280": _V2_META, "#55607A": _V2_META, "#5A6472": _V2_META,
    "#0047A0": _V2_TEAL,
}

# Dark-mode counterparts for the colours only v2 uses. They are written into
# v2's own stylesheet rather than into _DARK_TEXT/_DARK_BG, which build the
# stylesheet classic ships: adding to those would change classic's bytes.
# _check_dark_coverage reads these too.
_V2_DARK_TEXT = {
    _V2_INK: "#E8E6E1", _V2_BODY: "#C4C8CE", _V2_META: "#9AA3AE",
    _V2_TEAL: "#5CBDE6", _V2_NAVY: "#8FB6E8", "#3D4149": "#C4C8CE",
}
_V2_DARK_BG = {_V2_GROUND: "#121212"}
# Already light on navy in both schemes.
_V2_DARK_EXEMPT = {_V2_NAVY, _V2_FOOT}

# No family code. Each bar used to carry a 5px edge on its left (flag red for
# the North, flag blue for the South, a light blue for Washington and the
# world) and each family's card a faint matching tint. The owner asked for
# plain navy bars; without the edge a tint had no key and read as an
# off-white card rather than a code, so the cards are white again too.
# Flag red and blue stay exempt from the dark map: they are the alert
# kicker and the ROK card rule, drawn as borders with their own dark rules.
_V2_DARK_EXEMPT |= {TAEGUK_RED, TAEGUK_BLUE}
_V2_DARK_BG.update({"#D6DFEA": "#3A4048"})      # the pledge bar's unfilled part
# The section numerals on the navy bar: a muted light blue (7.3:1), quiet
# beside the white name. They were red, which read as an alert on every bar;
# red is kept for alerts. They keep their colour in dark mode, as the bars do.
_V2_NUM = "#9FB3CC"
# The stat's body under its navy bar: the flag blue, white type, both schemes.
_V2_STAT_BG = TAEGUK_BLUE
# The sign-off card: black in both schemes, with light type.
_V2_BLACK = "#14181F"
_V2_ON_BLACK = "#B8C4D6"      # 9.7:1 on the black card
_V2_DARK_EXEMPT |= {_V2_NUM, _V2_STAT_BG, _V2_BLACK, _V2_ON_BLACK}

# Reading order. A policymaker at 6 a.m. wants what happened, then the two
# Koreas, then Washington, then the region; the forward look and the analysis
# next; the location watch last. The stat of the day follows Overnight, on
# the first screens. (A Leaders' words card once followed the top stories;
# the owner removed it, and its quotes are back under Statements.)
_V2_ORDER = ("top-stories", "overnight", "key-stat", "kcna", "rok-gov", "election",
             "trade", "hill", "nea", "world", "business", "upcoming", "analysis", "sentiment",
             "wire", "satellite")

# Bar labels in sentence case; the bar sets them in capitals, the contents line as written.
_V2_LABELS = {
    "today at a glance": "Today at a glance", "top stories": "Top stories",
    "pyongyang watch": "Pyongyang watch", "rok government": "ROK government",
    "election tracker": "Election tracker",
    "us-korea trade & investment": "US-Korea trade &amp; investment",
    "northeast asia watch": "Northeast Asia watch", "korea and the world": "Korea and the world",
    "business & economy": "Business &amp; economy", "public sentiment": "Public sentiment",
    "the wire": "The wire", "stat of the day": "Stat of the day",
    "satellite & location watch": "Satellite &amp; location watch",
}
# Contents entries, by anchor: a word or two each, so the line of links
# wraps to three or four lines on a phone where a grid of bar labels took
# eight rows.
_V2_TOC_SHORT = {
    "top-stories": "Top stories", "overnight": "Overnight", "kcna": "Pyongyang",
    "rok-gov": "Seoul", "election": "Election", "trade": "Trade", "hill": "Congress",
    "nea": "Northeast Asia", "world": "World", "business": "Business", "upcoming": "Upcoming",
    "analysis": "Analysis", "sentiment": "Polling", "wire": "Wire", "key-stat": "Stat of the day",
    "satellite": "Satellite",
}


def _v2_key(label: str) -> str:
    return _re.sub(r"<[^>]+>", "", label).replace("&amp;", "&").strip().lower()


def _v2_label(label: str) -> str:
    return _V2_LABELS.get(_v2_key(label), label)


def _v2_bar(label: str, numbered: bool = True) -> str:
    """Navy bar: a muted blue Georgia section number, a thin rule, the name in white capitals.

    The number is a marker until _v2_finish has seen which sections rendered
    (it also names the section for the contents line). It sits inside chrome
    markers so the word count is classic's.
    """
    mark = _v2_num_mark(label) if numbered else ""
    return ('<table width="100%" cellpadding="0" cellspacing="0" border="0" class="sec-bar" '
            f'style="background:{_V2_NAVY};"><tr><td style="padding:9px 20px;font-family:{_V2_SANS};'
            f'font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;line-height:1.35;'
            f'color:#FFFFFF;">{mark}{_v2_label(label)}</td></tr></table>')


def _v2_num_mark(label: str, color: str = _V2_NUM, rule: str = "#5B6F99") -> str:
    """The section number's placeholder: Georgia, muted blue on navy, a hairline after it."""
    return (f'<!--c--><span style="font-family:{_V2_SERIF};font-size:15px;letter-spacing:0;color:{color};'
            f'padding-right:9px;margin-right:9px;border-right:1px solid {rule};">%%V2N:{label}%%</span><!--/c-->')


def _v2_srctype(src: str) -> str:
    """A label for the kind of source, when the source line makes it plain."""
    s = (src or "").lower()
    if _re.search(r"\bkcna\b|rodong|uriminzokkiri|노동신문|조선중앙", s):
        return "DPRK state media"
    if _re.search(r"korea\.kr|\bmofa\b|\bmnd\b|ministry of|presidential office|대통령실|국방부|외교부|"
                  r"통일부|bank of korea|kostat|joint chiefs|합참", s):
        return "Primary"
    return ""


def _v2_cats(cat: str) -> list:
    """The parts of a category line worth printing beside the source.

    A slug such as "china-diplomatic" or "macro" restates the section it sits
    in; a region, a chamber or a bill number does not. A badge (PRC SOURCE)
    becomes plain words.
    """
    out = []
    for badge in _re.findall(r"<span[^>]*>(.*?)</span>", cat or "", _re.S):
        b = _re.sub(r"<[^>]+>", "", badge).strip()
        if b:
            out.append((b[:1] + b[1:].lower()).replace("Prc", "PRC"))      # "PRC SOURCE" as "PRC source"
    text = _re.sub(r"<span[^>]*>.*?</span>", "", cat or "", flags=_re.S)
    parts = [p.strip() for p in _re.split(r"&emsp;| ", text) if p.strip()]
    keep = [p for p in parts if not _re.fullmatch(r"[a-z]+(?:-[a-z]+)*", p) and p.lower() not in ("both", "other")]
    return (keep + out)[:3]


def _v2_when(text: str) -> str:
    """"@handle, Oct 19 2026" or "2026-10-19" as "October 19"; empty when there is no date in it."""
    t = str(text or "")
    m = _re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        try:
            return datetime(*map(int, m.groups())).strftime("%B %-d")
        except ValueError:
            return ""
    m = _re.search(r"\b(%s)[a-z]*\.? (\d{1,2})\b" % "|".join(x.title() for x in _MON), t)
    if m:
        try:
            return datetime(2000, _MON[m.group(1).lower()], int(m.group(2))).strftime("%B %-d")
        except ValueError:
            return ""
    return ""


# Publisher names as a reader knows them, for a feed's own name. Keys are
# lower case, after _v2_outlet has taken off a feed-variant suffix and a date.
_V2_OUTLET_NAMES = {
    "rok mofa": "Foreign Ministry", "mofa": "Foreign Ministry", "ministry of foreign affairs": "Foreign Ministry",
    "rok mnd": "Defense Ministry", "mnd": "Defense Ministry", "ministry of national defense": "Defense Ministry",
    "rok mou": "Unification Ministry", "mou": "Unification Ministry", "ministry of unification": "Unification Ministry",
    "rok jcs": "Joint Chiefs", "jcs": "Joint Chiefs",
    "nkpro": "NK Pro", "nk pro": "NK Pro", "nk news/newscord": "NK News", "nknews": "NK News",
    "ap news": "AP", "associated press": "AP", "bloomberg": "Bloomberg",
}
# What a feed adds to a publisher's name to tell its feeds apart: the
# language, the desk, the section. "Yonhap North Korea KO" is Yonhap.
_V2_FEED_SUFFIX = _re.compile(r"(?:\s+(?:English(?:\s+Edition)?|ENG|EN|KO|KR|Korean|Opinion|Op-?Eds?|Editorials?|Politics|"
                              r"North\s+Korea))+$", _re.I)
_V2_GLUED_DATE = _re.compile(r"\s+(?:(?:%s)[a-z]*\.?\s+\d{1,2}(?:,?\s+\d{4})?|\d{4}-\d{2}-\d{2})$"
                             % "|".join(x.title() for x in _MON))


def _v2_outlet(name: str) -> str:
    """One feed name as its publisher: "Yonhap North Korea KO" as "Yonhap", "NKPro" as "NK Pro".

    Takes off a date glued to the name, then feed-variant words (English, KO,
    Opinion, North Korea, Politics), then a ".com", and maps what is left
    through _V2_OUTLET_NAMES. A parenthesis ("(KCNA)") is kept. A name that
    would be left empty, or as the bare word Korea, is returned as it came.
    """
    raw = str(name or "").strip()
    via = _re.match(r"via\s+", raw, _re.I)
    if via:
        return raw[:via.end()] + _v2_outlet(raw[via.end():])
    m = _re.match(r"(.*?)(\s*\([^()]*\))?$", raw, _re.S)
    head, paren = m.group(1).strip(), (m.group(2) or "")
    t = _re.sub(r"\s*\|\s*", " ", head)
    t = _V2_GLUED_DATE.sub("", t)
    t = _V2_FEED_SUFFIX.sub("", t)
    t = _re.sub(r"\.com$", "", t, flags=_re.I).strip()
    t = _V2_OUTLET_NAMES.get(t.lower(), t)
    if not t or t.lower() == "korea":
        return raw
    return t + paren


def _v2_outlets(src: str) -> str:
    """A source line of one or more outlets ("A / B / C", links allowed), each named once.

    Each outlet is cleaned by _v2_outlet; an outlet named twice keeps its first
    place. A link keeps its target and gets the clean name as its text.
    """
    links = []

    def hold(m):
        links.append(m.group(0))
        return f"\x00{len(links) - 1}\x00"
    held = _re.sub(r"<a\b[^>]*>.*?</a>", hold, src or "", flags=_re.S)
    out, seen = [], set()
    for part in _re.split(r"\s+/\s+|,\s+", held):
        part = part.strip()
        if not part:
            continue
        lm = _re.fullmatch(r"\x00(\d+)\x00", part)
        if lm:
            am = _re.match(r"(<a\b[^>]*>)(.*?)(</a>)$", links[int(lm.group(1))], _re.S)
            name = _v2_outlet(_re.sub(r"<[^>]+>", "", am.group(2)))
            piece = am.group(1) + name + am.group(3)
        else:
            name = piece = _v2_outlet(_re.sub(r"\x00(\d+)\x00", lambda x: links[int(x.group(1))], part))
        key = _re.sub(r"<[^>]+>", "", name).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(piece)
    return " / ".join(out)


def _v2_kicker(src: str, cat: str = "", date: str = "", color: str = _V2_TEAL, outlet: bool = True) -> str:
    """The teal line above a headline: "Source, Category, Month Day". Red for an alert item.

    `src` is cleaned to publisher names (_v2_outlets) unless `outlet` is
    False, as for a person and their handle on an X post.
    """
    raw_src = src or ""
    src = _re.sub(r"\s*\u00b7\s*", ", ", raw_src)
    if outlet:
        src = _v2_outlets(src)
    parts = [src.strip()] if src and src.strip() else []
    parts += [c for c in _v2_cats(cat) if c.lower() not in _re.sub(r"<[^>]+>", "", src or "").lower()]
    kind = _v2_srctype(_re.sub(r"<[^>]+>", "", raw_src))
    if kind and kind not in parts:
        parts.append(kind)
    if date:
        parts.append(date)
    if not parts:
        return ""
    return (f'<div style="font-size:12px;font-weight:700;line-height:1.35;color:{color};'
            f'margin-bottom:2px;">{", ".join(parts)}</div>')


def _v2_alert(cat: str, bar_color: str) -> bool:
    """An item classic marks red for what it reports (coercion, a military move), not for its sector."""
    slugs = set(_re.findall(r"[a-z]+(?:-[a-z]+)+", _re.sub(r"<[^>]+>", "", cat or "")))
    return bar_color == TAEGUK_RED and bool(slugs & _V2_ALERT_CATS)


def _v2_item(cat, src, headline, body, url, bar_color, extra_html) -> str:
    """The house item: kicker, serif headline, body. A hairline between items, no box."""
    return (f'<div class="v2-it" style="padding:11px 0 12px;border-top:1px solid {_V2_HAIR};">'
            + _v2_kicker(src, cat, color=TAEGUK_RED if _v2_alert(cat, bar_color) else _V2_TEAL)
            + f'<div style="{_V2_HEAD}">{_link_or_text(headline, url, style=_V2_LINK)}</div>'
            + (f'<div style="font-size:14px;line-height:1.5;color:{_V2_BODY};margin-top:4px;">{body}</div>'
               if body else "")
            + extra_html + '</div>')


def _v2_row(kicker: str, headline: str, url: str, body: str = "") -> str:
    """A scan-list item (Overnight, The Wire): the house item one size down."""
    return (f'<div class="v2-it" style="padding:9px 0 10px;border-top:1px solid {_V2_HAIR};">{kicker}'
            f'<div style="{_V2_HEAD.replace("15px", "14px")}">'
            f'{_link_or_text(headline, url, style=_V2_LINK)}</div>'
            + (f'<div style="font-size:13px;line-height:1.5;color:{_V2_BODY};margin-top:2px;">{body}</div>'
               if body else "")
            + '</div>')


def _v2_subhead(text: str) -> str:
    """A group label inside a card: small navy capitals over a navy rule."""
    return (f'<div class="v2-sub" style="font-size:12px;font-weight:700;letter-spacing:1px;'
            f'text-transform:uppercase;color:{_V2_NAVY};margin:14px 0 0;padding-bottom:5px;'
            f'border-bottom:2px solid {_V2_NAVY};">{text}</div>')


def _v2_button(href: str, text: str) -> str:
    """An outlined navy link to a standing page. None on paper (PRINT)."""
    if PRINT:
        return ""
    return ('<table cellpadding="0" cellspacing="0" border="0" style="margin:14px 0 4px;"><tr>'
            f'<td class="v2-btn" style="border:1px solid {_V2_NAVY};padding:7px 14px;font-family:{_V2_SANS};">'
            f'<a href="{_esc(href)}" style="font-size:13px;font-weight:700;color:{_V2_NAVY};'
            f'text-decoration:none;">{text}</a></td></tr></table>')


def _v2_cal_row(month: str, day: str, label: str, title: str, why: str = "", where: str = "") -> str:
    """One calendar entry: classic's blue date box (month over the day, white on the flag blue), then
    label, title, why, where. Upcoming and the Hill schedule share it.

    The box is the original design's, which the owner asked back: a filled
    square, 46px wide, the month at 11px (classic's 10px, at the owner's
    floor) over the day numeral at 16px. Both stay white on blue in dark
    mode, as the flag blue is exempt from the dark map.
    """
    return ('<table width="100%" cellpadding="0" cellspacing="0" border="0" class="v2-it" '
            f'style="border-top:1px solid {_V2_HAIR};"><tr>'
            f'<td width="58" valign="top" style="padding:10px 12px 10px 0;vertical-align:top;font-family:{_V2_SANS};">'
            f'<table cellpadding="0" cellspacing="0" border="0" class="v2-date" style="background:{TAEGUK_BLUE};"><tr>'
            f'<td align="center" style="width:46px;padding:4px 0 5px;text-align:center;font-family:{_V2_SANS};">'
            f'<div style="font-size:11px;font-weight:700;letter-spacing:1px;line-height:1.3;color:{_V2_FOOT};">{month}</div>'
            f'<div style="font-family:{_V2_SERIF};font-size:16px;font-weight:700;line-height:1.1;color:#FFFFFF;">{day}</div>'
            '</td></tr></table></td>'
            f'<td valign="top" style="padding:10px 0;vertical-align:top;font-family:{_V2_SANS};">'
            + (f'<div style="font-size:12px;font-weight:700;letter-spacing:0.5px;text-transform:uppercase;'
               f'color:{_V2_TEAL};margin-bottom:2px;">{label}</div>' if label else "")
            + f'<div style="{_V2_HEAD}">{title}</div>'
            + (f'<div style="font-size:14px;line-height:1.5;color:{_V2_BODY};margin-top:3px;">{why}</div>' if why else "")
            + (f'<div style="font-size:12px;color:{_V2_META};margin-top:3px;">{where}</div>' if where else "")
            + '</td></tr></table>')


_V2_UP_LIMIT = 8
_V2_STOP = {"the", "a", "an", "of", "on", "and", "to", "for", "in", "with", "at", "by", "hearing",
            "hearings", "markup", "committee", "house", "senate", "us", "u", "s"}


def _v2_words(text: str) -> set:
    return {w for w in _re.findall(r"[a-z0-9]+", str(text or "").lower()) if w not in _V2_STOP and len(w) > 2}


def _v2_upcoming(calendar_watch: list, hill: list | None = None, today=None) -> str:
    """Upcoming: the dated events and observances (calendar_watch, already merged) and the
    week's committee hearings, in date order, at most _V2_UP_LIMIT rows.

    A hearing the model also listed (same day, two words of the title in
    common) appears once, as the model's entry. Nothing here is dated by the
    renderer: each row's date is the article's, the schedule's or the
    computed observance's. Empty when there is nothing to list.
    """
    entries = []
    for cal in calendar_watch or []:
        if not isinstance(cal, dict) or not cal.get("headline"):
            continue
        row = _v2_cal_row(_esc(str(cal.get("month", ""))).upper(), _esc(str(cal.get("day", ""))), "",
                          _emphasis(_esc(cal.get("headline", ""))), _emphasis(_esc(cal.get("detail", ""))))
        entries.append((str(cal.get("_date") or "9999"), _v2_words(f'{cal.get("headline")} {cal.get("detail")}'), row))
    model_days = [(d, w) for d, w, _r in entries]
    for ev in hill or []:
        if not isinstance(ev, dict) or not ev.get("title"):
            continue
        day = str(ev.get("date") or "")[:10]
        words = _v2_words(hill_event_text(ev))
        if any(d == day and len(words & w) >= 2 for d, w in model_days):
            continue
        entries.append((day or "9999", words, _v2_hill_rows([ev], today)))
    if not entries:
        return ""
    entries.sort(key=lambda e: e[0])       # stable: the model's order within a day
    rows = "".join(r for _d, _w, r in entries[:_V2_UP_LIMIT])
    return (f'<!--v2--><div><a name="upcoming" id="upcoming"></a>{_v2_bar("Upcoming")}{rows}</div>')


def _v2_hill_rows(events: list, today) -> str:
    """"Coming up on the Hill" as calendar rows, from the collected committee schedules."""
    rows = ""
    for ev in events:
        try:
            d = datetime.strptime(str(ev["date"])[:10], "%Y-%m-%d").date()
            month, day = d.strftime("%b").upper(), str(d.day)
        except (KeyError, ValueError):
            month, day = "", ""
        raw = str(ev.get("title") or "")
        kind = "Markup" if _re.search(r"markup|mark-up|business meeting", raw, _re.I) else "Hearing"
        if today is not None and day and d == today:
            kind += ", today"
        title = _link_or_text(_esc(hill_event_text(ev)), str(ev.get("url") or ""), style=_V2_LINK)
        rows += _v2_cal_row(month, day, kind, title, "", _esc(str(ev.get("time") or "")))
    return rows


def _v2_analysis(social: list, opeds: list, academic: list, x_posts: list) -> str:
    """Analysis as the reference's research list: bold title, one line, author in grey."""
    out = ""
    posts = ""
    for xp in x_posts:
        if not isinstance(xp, dict):
            continue
        name = _esc(str(xp.get("name") or xp.get("who") or ""))
        handle = str(xp.get("handle") or "").strip()
        if not handle:
            m = _re.search(r"@([A-Za-z0-9_]+)", str(xp.get("handle_context") or ""))
            handle = m.group(1) if m else ""
        post = _esc(str(xp.get("post") or xp.get("quote_text") or ""))
        if not post:
            continue
        note = _esc(str(xp.get("analyst_note") or "").strip())
        url = str(xp.get("url") or "")
        when = _v2_when(xp.get("platform_date"))
        if handle:
            # "Gen. Xavier Brunson / CDRUNCCFCUSFK" before "(@CDRUNCCFCUSFK)" names the account twice.
            name = _re.sub(r"\s*/\s*@?%s$" % _re.escape(handle.lstrip("@")), "", name, flags=_re.I) or name
        who = name +(f" (@{_esc(handle.lstrip('@'))})" if handle else "")
        link = (f' <a href="{_esc(url)}" style="color:{_V2_TEAL};text-decoration:none;font-weight:700;">View on X</a>'
                if url.startswith("http") else "")
        posts += (f'<div class="v2-it" style="padding:10px 0;border-top:1px solid {_V2_HAIR};font-size:14px;'
                  f'line-height:1.5;color:{_V2_BODY};">'
                  + _v2_kicker(who, "", when, outlet=False)
                  + f'<div style="color:{_V2_INK};">&ldquo;{post}&rdquo;</div>'
                  + (f'<div style="font-size:13px;color:{_V2_META};margin-top:3px;">{note}{link}</div>' if note or link else "")
                  + '</div>')
    if posts:
        out += (_v2_subhead("Officials on X") + posts
                + f'<div style="font-size:12px;color:{_V2_META};padding:2px 0 6px;">Direct posts by tracked official '
                  f'accounts, attributed as posted. Not independently verified beyond the post.</div>')
    if social:
        out += _v2_subhead("Statements")
    for s in social:
        if not isinstance(s, dict):
            continue
        quote = _esc(s.get("quote_text", ""))
        note = _esc(s.get("analyst_note", ""))
        h = _re.search(r"@(\w+)", str(s.get("handle_context") or ""))
        url = str(s.get("url") or "")
        link = (f' <a href="{_esc(url)}" style="color:{_V2_TEAL};text-decoration:none;font-weight:700;">Source</a>'
                if url.startswith("http") else "")
        out += (f'<div class="v2-it" style="padding:10px 0;border-top:1px solid {_V2_HAIR};font-size:14px;'
                f'line-height:1.5;color:{_V2_BODY};">'
                + _v2_kicker(_esc(s.get("who", "")) + (f" (@{_esc(h.group(1))})" if h else ""),
                             "", _v2_when(s.get("handle_context")), outlet=False)
                + f'<div style="color:{_V2_INK};">&ldquo;{quote}&rdquo;</div>'
                + (f'<div style="font-size:13px;color:{_V2_META};margin-top:3px;">{note}{link}</div>' if note or link else "")
                + '</div>')

    def research(title, url, summary, byline, extra=""):
        t = _link_or_text(title, url, style=_V2_LINK)
        return (f'<div class="v2-it" style="padding:9px 0;border-top:1px solid {_V2_HAIR};font-size:14px;'
                f'line-height:1.5;color:{_V2_BODY};">'
                + (f'<b style="color:{_V2_INK};">{t}.</b> ' if title else "")
                + summary
                + (f' <span style="font-size:13px;color:{_V2_META};">({byline})</span>' if byline else "")
                + extra + '</div>')
    if opeds:
        out += _v2_subhead("Commentary")
    for op in opeds:
        if not isinstance(op, dict):
            continue
        title = _esc(op.get("headline", op.get("title", op.get("central_argument", "")))).rstrip(".")
        authors = op.get("authors")
        authors = ", ".join(map(str, authors)) if isinstance(authors, list) else str(authors or "")
        source = _v2_outlet(_re.sub(r"\s*\(\s*\)", "", _clean_src(str(op.get("source", "")))).strip())
        byline = ", ".join(_esc(x) for x in (authors.strip(), source) if x)
        out += research(title, op.get("url", ""), _emphasis(_esc(op.get("summary", ""))), byline)
    if academic:
        out += _v2_subhead("Research")
    for a in academic:
        if not isinstance(a, dict):
            continue
        title = _esc(a.get("headline", a.get("title", ""))).rstrip(".")
        byline = ", ".join(_esc(x) for x in (str(a.get("authors") or "").strip(), str(a.get("source", "")).strip(),
                                            str(a.get("journal_tier", "")).strip()) if x)
        imp = _esc(a.get("policy_implication", ""))
        out += research(title, a.get("url", ""), _emphasis(_esc(a.get("summary", ""))), byline,
                        f'<div style="font-size:13px;color:{_V2_META};margin-top:3px;">'
                        f'<b>Implication:</b> {imp}</div>' if imp else "")
    if not out:
        return ""
    return f'<!--v2--><div><a name="analysis" id="analysis"></a>{_v2_bar("Analysis")}{out}</div>'


def _v2_buttons(section: str) -> str:
    """The links to standing pages as outlined buttons, as the reference's "Open the full tracker"."""
    section = _re.sub(
        r'<div style="margin-top:16px;padding-top:14px;border-top:1px solid #E4E7EB;"><a href="([^"]+)"[^>]*>'
        r'<span[^>]*>Full trade reference</span>.*?</a></div>',
        lambda m: _v2_button(m.group(1).replace("&amp;", "&"), "Open the full trade reference"), section, flags=_re.S)
    m = _re.search(r' <a href="([^"]+locations\.html)" style="[^"]*">Full location watch</a>', section)
    if m:
        section = section.replace(m.group(0), "", 1)
        i = section.rfind("</div>")
        section = section[:i] + _v2_button(m.group(1).replace("&amp;", "&"), "View the full location watch") + section[i:]
    return section


def _v2_lists(section: str) -> str:
    """ROK Government, the location watch and the stat as items on the card, not boxes inside it.

    The reference has one box per section and none inside it: items are
    divided by hairlines. Each pattern is classic's own markup; a section
    whose markup has moved is left as it was.
    """
    # The ministry and location cards: the cell loses its padding, the card
    # its fill, frame and coloured top rule, and gains the item hairline.
    item = f'<td class="v2-it" style="border-top:1px solid {_V2_HAIR};padding:11px 0 12px;vertical-align:top;">'
    section = section.replace('<td style="width:50%;padding:8px;vertical-align:top;" height="100%">',
                              '<td style="padding:0;vertical-align:top;">')
    section = section.replace('<td style="width:50%;padding:4px;vertical-align:top;" height="100%">',
                              '<td style="padding:0;vertical-align:top;">')
    section = section.replace('<td style="background:#F5F7FA;border-radius:3px;padding:14px;vertical-align:top;">', item)
    section = _re.sub(r'<td style="background:#FFFFFF;border:1px solid #E4E7EB;border-top:2px solid #[0-9A-Fa-f]{6};'
                      r'padding:13px 15px;vertical-align:top;">', item, section)
    # Personnel and Assembly entries: the hairline, not a coloured rule down the side.
    section = _re.sub(r'<div style="margin-bottom:1[01]px;padding-left:12px;border-left:3px solid #[0-9A-Fa-f]{6};">',
                      f'<div class="v2-it" style="padding:10px 0 11px;border-top:1px solid {_V2_HAIR};">', section)
    section = _re.sub(r'<div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;[^"]*'
                      r'padding-bottom:4px;border-bottom:1px solid #E8E8E8;">([^<]*)</div>',
                      lambda m: _v2_subhead(m.group(1)), section)
    # The location watch's "other monitored sites" line: the house hairline,
    # which dark mode darkens (its #EAEAEA rule showed as a white line there).
    section = section.replace('margin-top:10px;padding-top:9px;border-top:1px solid #EAEAEA;">',
                              f'margin-top:10px;padding-top:9px;border-top:1px solid {_V2_HAIR};" class="v2-rule">')
    # A ministry card's source line: no second rule inside the item.
    section = section.replace('<div style="margin-top:8px;padding-top:7px;border-top:1px solid #E1E6ED;',
                              '<div style="margin-top:6px;')
    # The Gallup spotlight: a ruled note under the figures, not a tinted panel.
    # Teal on the tint measured 4.2:1.
    section = section.replace(f"padding:8px 12px;background:#F0F5FB;border-radius:3px;border-left:3px solid {TAEGUK_BLUE};",
                              f"padding:8px 0 0;border-top:1px solid {_V2_HAIR};")
    # The party tiles' labels: letterspaced capitals set a 250px floor under
    # three nowrap cells, wider than a 320px phone once the stylesheet goes.
    section = section.replace('<div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#6B7280;'
                              'font-family:Arial,sans-serif;white-space:nowrap;">',
                              '<div style="font-size:11px;font-weight:700;color:#6B7280;font-family:Arial,sans-serif;'
                              'white-space:nowrap;">')
    # Ministry name and site status as the reference's category label.
    section = section.replace('<span style="font-size:10px;color:#6B7280;text-transform:uppercase;letter-spacing:0.5px;">',
                              f'<span style="font-size:12px;font-weight:700;color:{_V2_TEAL};">')
    section = _re.sub(r'font-size:10px;(font-weight:700;color:#[0-9A-Fa-f]{6};)letter-spacing:1.5px;'
                      r'(text-transform:uppercase;)margin-bottom:5px;',
                      r'font-size:12px;\1letter-spacing:0.5px;\2margin-bottom:2px;', section)
    # The imagery report: no rule down its side, the kicker in the house form.
    section = section.replace(f'<div style="margin-bottom:20px;padding:16px;border-left:3px solid {TAEGUK_BLUE};">',
                              '<div style="margin:10px 0 12px;">')
    section = section.replace(f'font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:{TAEGUK_BLUE};'
                              'font-weight:600;margin-bottom:6px;',
                              f'font-size:12px;color:{_V2_TEAL};font-weight:700;margin-bottom:2px;')
    section = section.replace("font-size:17px;font-weight:700;", "font-size:15px;font-weight:700;")
    # Stat of the day: the figure on the card, without a tinted panel round it.
    section = _re.sub(r'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#EDF3FB;'
                      r'border-top:2px solid #0047A0;[^"]*">\s*<tr><td style="padding:14px 16px;">',
                      '<table width="100%" cellpadding="0" cellspacing="0" border="0"><tr><td style="padding:10px 0 4px;">',
                      section)
    # Its figure keeps classic's Georgia, in navy: the one large serif number
    # in the brief, as in classic. Set here because the restyle would make it sans.
    section = section.replace(f'font-family:Georgia,serif;font-size:26px;font-weight:700;color:{TAEGUK_BLUE};line-height:1;',
                              f'font-family:{_V2_SERIF};font-size:26px;font-weight:700;color:{_V2_NAVY};line-height:1;')
    return section


def _v2_gap(inner: str, top: int = 0, bottom: int = 12) -> str:
    return f'<div class="v2-gap" style="padding:{top}px 16px {bottom}px;">{inner}</div>'


def _v2_cardbox(inner: str, pad: str = "14px 20px") -> str:
    return ('<table width="100%" cellpadding="0" cellspacing="0" border="0" class="v2-card" '
            f'style="background:#FFFFFF;"><tr><td class="v2-in" style="padding:{pad};font-family:{_V2_SANS};">'
            f'{inner}</td></tr></table>')


_V2_PRE = _re.compile(r'^\s*(?:<!--v2-->)?\s*((?:<a name="[\w-]+" id="[\w-]+"></a>\s*)*)<div\b[^>]*>\s*'
                      r'((?:<a name="[\w-]+" id="[\w-]+"></a>\s*)*)$', _re.S)
_V2_BAR = _re.compile(r'<table width="100%" cellpadding="0" cellspacing="0" border="0" class="sec-bar"[^>]*>'
                      r'<tr><td[^>]*>.*?</td></tr></table>', _re.S)


def _v2_card(section: str, more: dict | None = None) -> str:
    """A section with a bar becomes a white card on the grey ground, the bar across its top.

    Sections arrive as an outer box holding an anchor, the bar and the
    content. The box goes; the bar becomes the card's first row and the
    content its second. A section in any other shape is left as it is.

    `more` maps a section anchor to the web page's copy of that section (a
    section in it was shortened for the email, _v2_shorten). The card no
    longer says so itself: one line under the contents does, for every
    section (_v2_finish). The section's anchor stays, so the web page's links
    to it still land.
    """
    m = _V2_BAR.search(section)
    if not m:
        return section
    pre, rest = section[:m.start()], section[m.end():].rstrip()
    p = _V2_PRE.match(pre)
    if not p or not rest.endswith("</div>"):
        return section
    rest = rest[:-len("</div>")]
    # No rule above the first item in the card, or the first after a group label.
    first = _re.match(r'\s*<(?:div|table)\b[^>]*class="v2-it"', rest)
    if first:
        rest = rest.replace(f"border-top:1px solid {_V2_HAIR};", "", 1)
    rest = _re.sub(r'(class="v2-sub"[^>]*>[^<]*</div>\s*<(?:div|table)\b[^>]*?class="v2-it" style="[^"]*?)'
                   rf'border-top:1px solid {_V2_HAIR};', r"\1", rest)
    head = section.lstrip()[:9] if section.lstrip().startswith("<!--v2-->") else ""
    inner = (f'class="v2-in v2-tint" style="padding:6px 20px 10px 17px;background:{_V2_TINT};'
             f'border-left:3px solid {_V2_ACCENT};font-family:{_V2_SANS};"'
             if 'class="v2-glance"' in rest[:200] else
             f'class="v2-in" style="padding:4px 20px 12px;font-family:{_V2_SANS};"')
    if 'name="kcna"' in p.group(1) + p.group(2):
        rest, inner = _v2_pw_shade(rest)
    bar = m.group(0)
    return (f'{head}<div class="v2-gap" style="padding:0 16px 12px;">{p.group(1)}{p.group(2)}'
            '<table width="100%" cellpadding="0" cellspacing="0" border="0" class="v2-card" style="background:#FFFFFF;">'
            f'<tr><td style="padding:0;">{bar}</td></tr>'
            f'<tr><td {inner}>{rest}</td></tr></table></div>')


# ── Pyongyang Watch shade ───────────────────────────────────────────────────
# The owner asked for Pyongyang Watch to stand apart from every other card:
# its body on a light charcoal ground with light type, under the same navy
# bar. Every colour in the card is swapped for its counterpart on the
# charcoal (contrast on #2B2F36: ink 13.0:1, body 10.0:1, meta 6.5:1, teal
# 7.4:1, navy-light 8.5:1, red 6.4:1). In dark mode the ground lifts to
# #353A42, lighter than the #262A30 cards, with a hairline border, so it
# still reads as distinct. On paper a dark block is a lot of ink: the PDF
# uses a light grey (#E9EBEE) with the usual dark type instead, the red
# deepened and the hairlines darkened to hold on the grey.
_V2_PW_BG = "#2B2F36"
_V2_PW_MAP = {
    _V2_INK: "#F1F2F4", _V2_BODY: "#D5D9DF", _V2_META: "#AEB5BF", _V2_TEAL: "#7FCBEE",
    _V2_NAVY: "#B4CBEA", TAEGUK_RED: "#FF9CA3", _V2_HAIR: "#474D57", _V2_ACCENT: "#7FA9E0",
}
_V2_PW_PRINT_BG = "#E9EBEE"
_V2_PW_PRINT_MAP = {TAEGUK_RED: DOWN_RED, _V2_HAIR: "#CDD2D9", _V2_TINT_RULE: "#C3CAD4"}
_V2_DARK_BG[_V2_PW_BG] = "#353A42"
_V2_DARK_EXEMPT |= {_V2_PW_PRINT_BG} | set(_V2_PW_MAP.values()) | set(_V2_PW_PRINT_MAP.values())


def _v2_pw_shade(rest: str) -> tuple:
    """Pyongyang Watch's body recoloured for its ground; returns (body, inner td attributes)."""
    cmap = _V2_PW_PRINT_MAP if PRINT else _V2_PW_MAP
    bg = _V2_PW_PRINT_BG if PRINT else _V2_PW_BG
    rx = _re.compile("(color:|solid )(" + "|".join(_re.escape(k) for k in cmap) + ")(?![0-9A-Fa-f])")
    rest = rx.sub(lambda m: m.group(1) + cmap[m.group(2)], rest)
    return rest, (f'class="v2-in v2-pw" style="padding:4px 20px 12px;background:{bg};font-family:{_V2_SANS};"')


# ── ROK government cards ────────────────────────────────────────────────────

def _v2_agency(raw) -> str:
    """The agency as its card names it: the president's office under one name, the rest in English."""
    s = _en_label(raw)
    if _re.search(r"blue house|president|presidential|cheong ?wa ?dae|大統領|대통령", s, _re.I):
        return "Presidential Office"
    return s.strip() or "Government"


def _v2_rok_source(item: dict, agency: str) -> str:
    """The card's source line: "Primary" and the document for a government URL, else the outlet.

    Outlets by their publisher names (_v2_outlet). A "Reported" line naming
    the outlet the line above already names is left out ("Yonhap" over
    "Reported Yonhap"), and a bare "X" reads "Post on X".
    """
    url = str(item.get("url") or "")
    label = str(item.get("source_label") or "").strip()
    rows, first = [], ""
    a = f"color:{_V2_INK};font-weight:700;text-decoration:none;"

    def named(n):
        n = _v2_outlet(n)
        return "Post on X" if n.strip().lower() == "x" else n
    if url.startswith("http"):
        if _linkq.is_primary_url(url):
            rows.append(f'<b style="color:{_V2_TEAL};">Primary</b> '
                        f'<a href="{_esc(url)}" style="{a}">{_esc(named(label) if label else agency)}</a>')
        else:
            name = label if label and _linkq.label_matches_url(label, url) else _linkq.publisher_name(url)
            first = named(name)
            rows.append(f'<a href="{_esc(url)}" style="{a}">{_esc(first)}</a>')
    elif label:
        first = named(label)
        rows.append(f'<b>Source</b> {_esc(first)}')
    sec_url, sec_label = str(item.get("secondary_url") or ""), _esc(str(item.get("secondary_label") or ""))
    sec = named(sec_label) if sec_label else ""
    if sec and first and _re.sub(r"<[^>]+>", "", sec).strip().lower() == first.strip().lower():
        pass
    elif sec_url.startswith("http"):
        rows.append(f'<b>Reported</b> <a href="{_esc(sec_url)}" style="{a}">{sec or "coverage"}</a>')
    elif sec:
        rows.append(f'<b>Reported</b> {sec}')
    return "<br>".join(rows)


# Classic's ROK card fill (its gov-grid cells), with a hairline a shade
# darker so the card holds its shape on the white section card. Dark mode:
# classic's own map takes #F5F7FA to #22262C; the edge gets the dark border.
_V2_ROK_FILL = "#F5F7FA"
_V2_ROK_EDGE = "#E1E6ED"
_V2_DARK_BG.setdefault(_V2_ROK_FILL, "#22262C")


def _v2_rok_cards(items: list) -> str:
    """ROK Government as a grid of cards, each headed by the agency that spoke.

    Two columns on a desktop and one on a phone, with or without the
    stylesheet: each card is a block of fixed maximum width that sits beside
    the next where both fit and wraps under it where they do not, so a 320px
    screen gets one card per row. The stylesheet, where it survives, evens the
    heights and widens a card to the phone's full width. Outlook, which cannot
    wrap blocks, gets a two-column table in conditional comments.
    """
    cards = []
    for it in items:
        if not isinstance(it, dict):
            continue
        agency = _v2_agency(it.get("ministry"))
        official = _en_label(it.get("official"))
        official = "" if official.strip().lower() in ("", "none", "null", "n/a") else official
        action = _esc(it.get("action", ""))
        detail = _emphasis(_esc(it.get("detail", "")))
        src = _v2_rok_source(it, agency)
        cards.append(
            '<div class="v2-rc" style="display:inline-block;vertical-align:top;width:100%;max-width:280px;'
            'box-sizing:border-box;padding:0 8px 10px 0;">'
            '<table width="100%" cellpadding="0" cellspacing="0" border="0" class="v2-rct" '
            f'style="background:{_V2_ROK_FILL};border:1px solid {_V2_ROK_EDGE};"><tr>'
            f'<td style="padding:10px 14px 7px;border-bottom:2px solid {TAEGUK_BLUE};font-family:{_V2_SANS};font-size:11px;font-weight:700;'
            f'letter-spacing:0.5px;text-transform:uppercase;line-height:1.35;color:{_V2_NAVY};">{_esc(agency)}</td></tr>'
            f'<tr><td class="v2-rcb" style="padding:9px 14px 0;vertical-align:top;height:100%;font-family:{_V2_SANS};">'
            + (f'<div style="font-size:12px;line-height:1.4;color:{_V2_META};">{_esc(official)}</div>' if official else "")
            + f'<div style="{_V2_HEAD.replace("15px", "14px")}margin-top:3px;">{action}</div>'
            + (f'<div style="font-size:13px;line-height:1.5;color:{_V2_BODY};margin-top:4px;">{detail}</div>' if detail else "")
            + '</td></tr>'
            # The source in a row of its own at the card's foot: where the
            # stylesheet evens a row's heights, the extra space goes to the
            # body above it, so a pair's source lines sit on one line.
            + f'<tr><td valign="bottom" style="padding:7px 14px 11px;vertical-align:bottom;font-family:{_V2_SANS};'
              f'font-size:12px;line-height:1.6;color:{_V2_META};">{src or "&nbsp;"}</td></tr>'
            + '</table></div>')
    if not cards:
        return ""
    out = '<!--[if mso]><table width="100%" cellpadding="0" cellspacing="0" border="0"><tr><td width="50%" valign="top"><![endif]-->'
    for n, c in enumerate(cards):
        if n:
            out += ('<!--[if mso]></td></tr><tr><td width="50%" valign="top"><![endif]-->' if n % 2 == 0
                    else '<!--[if mso]></td><td width="50%" valign="top"><![endif]-->')
        out += c + " "
    out += '<!--[if mso]></td></tr></table><![endif]-->'
    return f'<div class="v2-rg" style="padding-top:8px;">{out}</div>'


# ── Public sentiment ────────────────────────────────────────────────────────

_V2_UP_ON_TINT = "#276B43"
_V2_DARK_TEXT[_V2_UP_ON_TINT] = "#5FBF87"


def _v2_sentiment_card(sentiment: dict, delta, spark: str, stale: str) -> str:
    """Classic's Public Sentiment in a v2 card: the approval figure, the parties in a row of boxes, the trend.

    The owner preferred classic's panel (a large approval figure with its
    change and survey dates, the party standings beside it) to four equal
    blocks. Classic's version left the right half empty under three small
    figures; here the parties are three bordered boxes of the approval
    block's height, centred beside it, and the trend line runs the full
    width under both, so neither side has dead space.

    Two blocks that sit side by side where they fit (a desktop) and stack
    by themselves where they do not (a phone), stylesheet or not; Outlook
    gets a table in conditional comments. The three boxes stay in one row
    down to a 320px phone with the stylesheet; without it, the third wraps.
    """
    ap = sentiment.get("presidential_approval") or {}

    def val(d):
        v = str((d or {}).get("value") or "").strip()
        return _esc(v) if v and v.lower() != "none" else ""

    def party(d, fallback):
        name = str((d or {}).get("party") or "").strip()
        name = _re.sub(r"\s+Party$", "", name)
        return _esc(_en_label(name)) or fallback

    parties = [("Ruling", val(sentiment.get("party_ruling")), party(sentiment.get("party_ruling"), "Democratic")),
               ("Opposition", val(sentiment.get("party_opposition")), party(sentiment.get("party_opposition"), "People Power")),
               ("Independents", val(sentiment.get("party_independent")), "")]
    approval = val(ap)
    if not approval and not any(p[1] for p in parties):
        return ""
    # Sentence case: "INDEPENDENTS" in capitals is 86px at 11px, wider than a
    # box on a 320px phone; "Independents" at 12px is 78px.
    lab = f"font-size:12px;font-weight:700;line-height:1.4;color:{_V2_INK};"
    change = ""
    if delta:
        pts, prior = delta
        # On the tint, classic's green measured 4.49:1; a shade darker holds 5.2:1.
        colour = _V2_UP_ON_TINT if pts > 0 else DOWN_RED if pts < 0 else _V2_META
        sign = "+" if pts > 0 else "&minus;" if pts < 0 else ""
        change = (f'<div style="font-size:12px;line-height:1.45;color:{_V2_META};margin-top:2px;">'
                  f'<span style="color:{colour};font-weight:700;">{sign}{abs(pts):g} pts</span>'
                  + (f" vs {_esc(prior)}" if prior else "") + '</div>')
    # The pollster and the survey dates on lines of their own: as one line
    # ("Gallup Korea, October 13-15, 2026") it broke after the day in
    # Synthèse, wider than the fallback sans.
    survey = "<br>".join(x for x in (_esc(str(ap.get("source") or "")).strip(),
                                     _esc(str(ap.get("last_updated") or "")).strip()) if x)
    # The trend sentence opens with today's figure, which the block shows in
    # large type just above it: "39%, down from 42% on Aug 25-27" reads
    # "Down from 42% on Aug 25-27" here.
    if spark and approval and spark.startswith(approval + ", "):
        spark = spark[len(approval) + 2:]
        spark = spark[:1].upper() + spark[1:]
    hero = (f'<div style="{lab}">Lee approval</div>'
            f'<div style="font-family:{_V2_SERIF};font-size:34px;font-weight:700;line-height:1.05;margin-top:2px;'
            f'color:{_V2_NAVY if approval else _V2_META};">{approval or "--"}</div>'
            + change
            + (f'<div style="font-size:12px;line-height:1.45;color:{_V2_META};">{survey}</div>' if survey else "")
            + (f'<div class="v2-rule" style="font-size:12px;line-height:1.45;color:{_V2_META};margin-top:6px;'
               f'padding-top:6px;border-top:1px solid {_V2_TINT_RULE};"><b style="color:{_V2_BODY};">Trend:</b> '
               f'{spark.rstrip(".")}.</div>' if spark else ""))
    boxes = "".join(
        '<div class="v2-psc" style="display:inline-block;vertical-align:top;width:33.33%;min-width:92px;">'
        f'<div class="v2-psb" style="margin:0 2px;padding:14px 3px 15px;border:1px solid {_V2_TINT_RULE};text-align:center;'
        'font-size:12px;line-height:1.4;">'
        f'<div style="{lab}">{label}</div>'
        f'<div style="font-size:12px;line-height:1.4;color:{_V2_META};">{sub or "&nbsp;"}</div>'
        f'<div style="font-family:{_V2_SERIF};font-size:22px;font-weight:700;line-height:1.1;margin-top:3px;'
        f'color:{_V2_INK if v else _V2_META};">{v or "--"}</div></div></div>'
        for label, v, sub in parties)
    out = ('<div class="v2-psr" style="padding:10px 0 2px;">'
           '<!--[if mso]><table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
           '<td width="236" valign="middle"><![endif]-->'
           '<div class="v2-ps" style="display:inline-block;vertical-align:middle;width:100%;max-width:236px;'
           'box-sizing:border-box;padding:0 0 10px;">'
           f'<div class="v2-pst" style="padding:10px 12px 11px;background:{_V2_TINT};border-left:3px solid {_V2_ACCENT};">'
           f'{hero}</div></div>'
           '<!--[if mso]></td><td valign="middle"><![endif]--> '
           '<div class="v2-pp" style="display:inline-block;vertical-align:middle;width:100%;max-width:326px;padding:0 0 10px;">'
           f'<div style="font-size:0;line-height:0;margin:0 -2px;">{boxes}</div></div>'
           '<!--[if mso]></td></tr></table><![endif]--></div>')
    if stale:
        out += f'<div style="font-size:12px;line-height:1.5;color:{TAEGUK_RED};margin-top:4px;">{stale}</div>'
    spot = sentiment.get("gallup_spotlight")
    if isinstance(spot, dict) and (spot.get("finding") or spot.get("topic")):
        out += (f'<div style="font-size:13px;line-height:1.5;color:{_V2_BODY};margin-top:6px;">'
                f'<b style="color:{_V2_NAVY};">Gallup Korea spotlight</b>'
                + (f' ({_esc(str(spot.get("poll_date")))})' if spot.get("poll_date") else "")
                + f': {_esc(str(spot.get("topic") or ""))}{": " if spot.get("topic") and spot.get("finding") else ""}'
                  f'{_esc(str(spot.get("finding") or ""))}</div>')
    disc = sentiment.get("discourse_flag")
    if disc:
        out += (f'<div style="font-size:13px;line-height:1.5;color:{_V2_BODY};margin-top:6px;">'
                f'<b style="color:{TAEGUK_RED};">Discourse:</b> {_esc(str(disc))}</div>')
    return f'<!--v2--><div><a name="sentiment" id="sentiment"></a>{_v2_bar("Public Sentiment")}{out}</div>'


# ── Stat of the day ─────────────────────────────────────────────────────────

def _v2_stat(key_stat: dict, href: str = "") -> str:
    """The stat as a card like the others, the navy bar over a blue body with white type.

    The bar is every section's (number, hairline, name in capitals), so the
    stat reads as section 04 rather than as a panel with its label inside the
    blue. The body is the one block in the brief set in colour. The card's
    markup is _v2_card's, so the web page folds it like the rest.

    `href` is unused: a shortened stat is covered by the one line under the
    contents, like every other section. Kept so callers need not change.
    """
    num = _esc(str(key_stat.get("number", "")))
    if not num:
        return ""
    label = _esc(key_stat.get("label", ""))
    ctx = _emphasis(_esc(key_stat.get("context", "")))
    src = _esc(key_stat.get("source", ""))
    inner = (f'<div style="font-family:{_V2_SERIF};font-size:26px;font-weight:700;line-height:1.1;color:#FFFFFF;">{num}</div>'
             + (f'<div style="font-size:14px;font-weight:700;line-height:1.4;color:#FFFFFF;margin-top:4px;">{label}</div>' if label else "")
             + (f'<div style="font-size:13px;line-height:1.5;color:{_V2_FOOT};margin-top:4px;">{ctx}</div>' if ctx else "")
             + (f'<div style="font-size:12px;line-height:1.4;color:{_V2_FOOT};margin-top:6px;">{src}</div>' if src else ""))
    return ('<!--v2--><div class="v2-gap" style="padding:0 16px 12px;"><a name="key-stat" id="key-stat"></a>'
            '<table width="100%" cellpadding="0" cellspacing="0" border="0" class="v2-card" style="background:#FFFFFF;">'
            f'<tr><td style="padding:0;">{_v2_bar("Stat of the day")}</td></tr>'
            f'<tr><td class="v2-in v2-stat" style="padding:14px 20px 16px;background:{_V2_STAT_BG};font-family:{_V2_SANS};">'
            f'{inner}</td></tr></table></div>')


# ── US-Korea trade tracker ──────────────────────────────────────────────────

_V2_TARIFF_COLOUR = {"ACTIVE": TAEGUK_RED, "ESCALATION": TAEGUK_RED, "REDUCED": UP_GREEN,
                     "NEGOTIATING": _V2_TEAL}
_V2_AMBER = "#9A5B00"      # pending, not in force: 5.9:1 on white (classic's "elevated" amber)


def _v2_trade(us_korea: dict, digest: dict, base: str) -> str:
    """The trade section as a tracker: tariff status, what changed, the pledge, today's news, the reference link.

    Every figure is read from the digest's tariff_tracker, trade_policy,
    investment_package and deals; a row whose data is missing is left out.
    """
    tt = us_korea.get("tariff_tracker") if isinstance(us_korea.get("tariff_tracker"), dict) else {}
    sectors = [s for s in tt.get("sector_rates") or [] if isinstance(s, dict)]
    policy = [p for p in us_korea.get("trade_policy") or [] if isinstance(p, dict)]
    rows, used = [], set()

    def status_word(st):
        st = str(st or "").strip().upper()
        st = "ACTIVE" if st == "ESCALATION" else st
        return st.title() if st and len(st) <= 12 else ""

    def sector(pattern, name):
        for n, s in enumerate(sectors):
            if _re.search(pattern, str(s.get("sector") or ""), _re.I) and s.get("rate"):
                used.add(n)
                st = str(s.get("status") or "").upper()
                rows.append((name, _esc(str(s.get("authority") or "")), _esc(str(s["rate"])), status_word(st),
                             _V2_TARIFF_COLOUR.get(st, _V2_META)))
                return

    sector(r"auto", "Autos and parts")
    sector(r"steel|alumin", "Steel and aluminum")
    rate = str(tt.get("headline_rate") or "").strip()
    st = str(tt.get("headline_status") or "").strip().upper()
    rm = _re.match(r"\s*(\d{1,3}(?:\.\d+)?\s*%)", rate)
    if rm or st:
        s122 = str(tt.get("section_122_surcharge") or "").strip()
        note = s122 if s122 and not rm else str(tt.get("headline_note") or "").strip()
        word = status_word(st)
        rows.append(("Reciprocal tariff", _esc(note), _esc(rm.group(1)) if rm else (word or "--"),
                     word if rm else "", _V2_TARIFF_COLOUR.get(st, _V2_META)))
    s301 = next((n for n, s in enumerate(sectors) if "301" in str(s.get("authority") or "") + str(s.get("sector") or "")), None)
    p301 = next((p for p in policy if "301" in str(p.get("item") or "")), None)
    if s301 is not None:
        s = sectors[s301]
        used.add(s301)
        rows.append(("Section 301", _esc(str(s.get("note") or s.get("authority") or "")), _esc(str(s.get("rate") or "")),
                     status_word(s.get("status")), _V2_TARIFF_COLOUR.get(str(s.get("status") or "").upper(), _V2_META)))
    elif p301:
        trig = str(tt.get("next_trigger") or "").strip()
        note = ", ".join(x for x in (str(p301.get("agency") or "").strip(),
                                     trig if "301" in trig else "") if x)
        pst = str(p301.get("status") or "").upper()
        rows.append(("Section 301", _esc(note), status_word(pst) or "--", "",
                     _V2_TARIFF_COLOUR.get(pst, _V2_META)))
    out = ""
    if rows:
        trs = ""
        for n, (name, note, value, word, colour) in enumerate(rows):
            line = "" if n == 0 else f"border-top:1px solid {_V2_HAIR};"
            # Red is for a tariff in force: a rate. A status with no rate (a
            # Section 301 investigation, "Active" beside "determination
            # pending") is amber when pending and neutral otherwise.
            if colour == TAEGUK_RED and "%" not in value:
                colour = _V2_AMBER if _re.search(r"pending|under review|investigat", note, _re.I) else _V2_META
            trs += (f'<tr><td class="v2-rule" style="padding:8px 8px 8px 12px;{line}vertical-align:top;font-family:{_V2_SANS};">'
                    f'<div style="font-size:13px;font-weight:700;line-height:1.35;color:{_V2_INK};">{name}</div>'
                    + (f'<div style="font-size:12px;line-height:1.4;color:{_V2_META};margin-top:1px;">{note}</div>' if note else "")
                    + f'</td><td class="v2-rule" align="right" style="padding:8px 12px 8px 4px;{line}vertical-align:top;text-align:right;font-family:{_V2_SANS};">'
                    f'<div style="font-family:{_V2_SERIF};font-size:15px;font-weight:700;line-height:1.3;color:{colour};'
                    f'white-space:nowrap;">{value}</div>'
                    + (f'<div style="font-size:12px;color:{_V2_META};">{word}</div>' if word else "")
                    + '</td></tr>')
        out += (_v2_subhead("Tariff status")
                + '<table width="100%" cellpadding="0" cellspacing="0" border="0" class="v2-trk" '
                  f'style="margin-top:10px;background:#FFFFFF;border:1px solid #D6DFEA;">{trs}</table>')
    changes = digest.get("_tariff_changes")
    others = len(sectors) - len(used)
    if isinstance(changes, list) and changes:
        out += (f'<div style="font-size:13px;line-height:1.5;color:{_V2_BODY};margin-top:8px;">'
                f'<b style="color:{TAEGUK_RED};">Changed since last issue:</b> '
                + ", ".join(_esc(str(c)) for c in changes) + '.</div>')
    if others > 0 or isinstance(changes, list):
        note = []
        if others > 0:
            note.append(f"{others} more sector rate{'s' if others != 1 else ''} on the trade reference page")
        if isinstance(changes, list) and not changes:
            note.append("no rate changed since the last issue")
        if note:
            t = "; ".join(note)
            out += f'<div style="font-size:12px;line-height:1.5;color:{_V2_META};margin-top:6px;">{t[:1].upper() + t[1:]}.</div>'
    sop = _esc(us_korea.get("state_of_play", ""))
    if sop and (FULL_TEXT or not rows):
        out += f'<div style="font-size:14px;line-height:1.55;color:{_V2_BODY};margin-top:8px;">{sop}</div>'
    pkg = us_korea.get("investment_package") if isinstance(us_korea.get("investment_package"), dict) else {}
    if pkg.get("total_pledged"):
        pledged = _esc(str(pkg["total_pledged"]))
        announced = str(pkg.get("announced_to_date") or "").strip()
        try:
            pct = int(pkg.get("pct_fulfilled"))
        except (TypeError, ValueError):
            pct = None
        known = [k for k in pkg.get("known_deals") or [] if isinstance(k, dict)]
        out += _v2_subhead(f"Investment pledge, {pledged}")
        if announced and pct and pct > 0:
            w = max(2, min(pct, 100))
            out += (f'<div style="font-size:13px;line-height:1.5;color:{_V2_BODY};margin-top:8px;">'
                    f'<b style="color:{_V2_NAVY};">{_esc(announced)}</b> announced of {pledged} pledged, {pct}% fulfilled</div>'
                    '<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:5px;"><tr>'
                    f'<td width="{w}%" style="background:{_V2_STAT_BG};height:8px;font-size:0;line-height:0;">&nbsp;</td>'
                    + (f'<td style="background:#D6DFEA;height:8px;font-size:0;line-height:0;">&nbsp;</td>' if w < 100 else "")
                    + '</tr></table>')
        else:
            first = known[0] if known else {}
            sel = (f'{len(known)} project{"s" if len(known) != 1 else ""} selected so far'
                   + (f', led by {_esc(first.get("company", ""))} ({_esc(first.get("value", ""))})'
                      if first.get("company") and first.get("value") else "")) if known else "No projects selected yet"
            out += (f'<div style="font-size:13px;line-height:1.5;color:{_V2_BODY};margin-top:8px;">'
                    f'<span style="font-family:{_V2_SERIF};font-size:20px;font-weight:700;color:{_V2_NAVY};">{pledged}</span>'
                    f'&ensp;pledged; {sel}.</div>')
            note = _esc(str(pkg.get("note") or "").strip())
            if note:
                out += f'<div style="font-size:12px;line-height:1.5;color:{_V2_META};margin-top:3px;">{note}</div>'
        fresh = [k for k in known if _pledge_is_new(k, digest)]
        for k in fresh:
            out += (f'<div style="font-size:13px;line-height:1.5;color:{_V2_BODY};margin-top:4px;">'
                    f'<b style="color:{UP_GREEN};">New project:</b> {_esc(k.get("company", ""))}'
                    + (f' ({_esc(k.get("value", ""))})' if k.get("value") else "") + '</div>')
    news = ""
    for deal in us_korea.get("deals") or []:
        if not isinstance(deal, dict) or not deal.get("headline"):
            continue
        cat = ", ".join(_esc(str(x)) for x in (deal.get("value"),) if x)
        news += _v2_item(cat, _esc(_clean_src(str(deal.get("source", "")))), _emphasis(_esc(deal["headline"])),
                         _emphasis(_esc(deal.get("detail", ""))), deal.get("url", ""), "", "")
    if news:
        out += _v2_subhead("Today&#8217;s trade news") + news
    if base:
        out += _v2_button(base + "trade.html", "Open the full trade reference")
    if not out:
        return ""
    return f'<!--v2--><div><a name="trade" id="trade"></a>{_v2_bar("US-Korea Trade &amp; Investment")}{out}</div>'


# ── Brand assets ────────────────────────────────────────────────────────────
# The official Korea Chair lockup (CSIS | Geopolitics and Foreign Policy
# Department | Korea Chair, white, for the navy footer), the CSIS wordmark
# (the masthead) and the CSIS brand
# typeface, Synthèse, live in assets/ and run.publish_assets copies them to
# public/assets/ each run. That is a static copy of checked-in files, never
# an index built from history, so it is safe under the archive rule.
#
# The email names them by absolute URL (WEB_URL + "/assets/..."): a mail
# client resolves nothing relative. The PDF embeds them as data URIs, so the
# runner needs no network for them. Without a web URL (a local render, the
# tests) the lockup is the HTML text it used to be.
#
# The PNG is the lockup at twice the size it is shown (680 by 80 for 340 by
# 40), cut to 32 colours: 6KB. Images do not count toward Gmail's clip.
_V2_ASSET_DIR = __import__("pathlib").Path(__file__).resolve().parent / "assets"
_V2_LOGO = "korea_chair_lockup_white.png"
_V2_LOGO_RATIO = 80 / 680
_V2_FONTS = ("synthese-400.woff2", "synthese-700.woff2")
_V2_BRAND_ALT = "CSIS Korea Chair"


def _v2_base(digest: dict) -> str:
    """The published site's root, with a trailing slash, or '' when there is none."""
    web_url = str(digest.get("web_url") or "")
    return web_url[:-len("latest.html")] if web_url.endswith("latest.html") else ""


def _v2_data_uri(name: str, mime: str) -> str:
    import base64
    try:
        raw = (_V2_ASSET_DIR / name).read_bytes()
    except OSError:
        return ""
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def _v2_asset(digest: dict, name: str, mime: str = "image/png") -> str:
    """Where the page finds an asset: a data URI on paper, the published copy in the inbox, else ''."""
    if PRINT:
        return _v2_data_uri(name, mime)
    base = _v2_base(digest)
    if not base:
        return ""
    if mime.startswith("image/"):
        # Images come from the repository, not the Pages site: the email goes
        # out minutes before the deploy that would publish a new asset, and a
        # test send deploys nothing, so a Pages URL showed a broken image the
        # first day. assets/ is checked in, so this URL exists as soon as the
        # change is merged. Fonts stay on Pages, which serves them as fonts.
        repo = __import__("os").environ.get("GITHUB_REPOSITORY") or "andysaulim/Daily-Korea-Digest"
        return f"https://raw.githubusercontent.com/{repo}/main/assets/{name}"
    return f"{base}assets/{name}"


def _v2_logo(digest: dict, width: int) -> str:
    """The official lockup as an image, or '' when there is nowhere to load it from.

    Explicit width and height, so the layout holds while it loads and in
    Outlook, which reads the attributes. Fluid below that width, so a 320px
    phone never scrolls. When images are blocked the alt text stands in its
    place, set in white bold on the navy band, so the band still reads
    "CSIS Korea Chair".
    """
    src = _v2_asset(digest, _V2_LOGO)
    if not src:
        return ""
    h = round(width * _V2_LOGO_RATIO)
    return (f'<img src="{_esc(src)}" width="{width}" height="{h}" alt="{_V2_BRAND_ALT}" class="v2-logo" '
            f'style="display:block;margin:0 auto;width:100%;max-width:{width}px;height:auto;border:0;outline:none;'
            f'text-decoration:none;font-family:{_V2_SANS};font-size:18px;font-weight:700;line-height:{h}px;'
            f'letter-spacing:1px;color:#FFFFFF;text-align:center;">')


# The official CSIS wordmark, cropped from the Korea Chair logo and set in
# white: 259 by 97, shown at 134 by 50 (2x for a crisp 1x), 2KB.
_V2_WORDMARK = "csis_wordmark_white.png"


def _v2_wordmark(digest: dict) -> str:
    """The masthead's CSIS wordmark as an image, or '' when there is nowhere to load it from."""
    src = _v2_asset(digest, _V2_WORDMARK)
    if not src:
        return ""
    return (f'<img src="{_esc(src)}" width="134" height="50" alt="CSIS" class="v2-wm" '
            'style="display:block;width:100%;min-width:64px;max-width:134px;height:auto;border:0;outline:none;text-decoration:none;'
            f'font-family:{_V2_SERIF};font-size:34px;line-height:50px;color:#FFFFFF;text-align:center;">')


def _v2_masthead(digest: dict, now, listen_bar: str) -> str:
    """The internal-use strip, the navy band with the CSIS lockup, the Listen card, the date card.

    The wordmark is the official image (_v2_wordmark), its alt text standing
    in when images are blocked; with no web URL to load it from, it is
    Georgia text. The Korea Chair lockup is the footer's. The brief's name stays live text. The date card's
    contents line is resolved in _v2_finish, once it is known which
    sections rendered.
    """
    issue = digest.get("issue_no")
    web_url = digest.get("web_url", "")
    base = web_url[:-len("latest.html")] if web_url.endswith("latest.html") else ""
    link = (lambda href, text: f'<a href="{_esc(href)}" style="color:{_V2_NAVY};font-weight:700;'
                               f'text-decoration:none;white-space:nowrap;">{text}</a>')
    links = []
    if web_url:
        links.append(link(_issue_file(digest, base, "html") or web_url, "Read online"))
        if base:
            links += [link(digest.get("_pdf_url") or _issue_file(digest, base, "pdf"), "PDF"),
                      link(base + "archive.html", "Past issues")]
    links = "&emsp; ".join(links)
    strip = ('<table width="100%" cellpadding="0" cellspacing="0" border="0" class="no-print v2-strip"><tr>'
             f'<td style="padding:9px 16px;font-family:{_V2_SANS};font-size:11px;font-weight:700;color:#3D4149;">'
             'For internal use only</td>'
             f'<td align="right" style="padding:9px 16px 9px 0;font-family:{_V2_SANS};font-size:11px;text-align:right;">'
             f'{links}</td></tr></table>')
    # One row, as in the owner's mockup: the CSIS wordmark on the left, the
    # brief's name in its outlined box on the right, both large enough to
    # fill the band (the one place exempt from the no-larger-type rule), the
    # date line under the row. A two-cell table, so every client keeps the
    # row (no flexbox). It never pushes a phone sideways, even without the
    # stylesheet: the wordmark's width is a percentage, which a table cell
    # may shrink to nothing, and the name wraps inside its box before the
    # row would overflow. On a phone the stylesheet scales both down
    # (wordmark 34px, name 17px), as the mockup does.
    #
    # The wordmark is the official one (_v2_wordmark), 2x for a crisp 1x;
    # blocked, its alt text "CSIS" is set in Georgia at the wordmark's size.
    # With no web URL to load it from it is Georgia text. The full lockup,
    # with the Korea Chair line, is in the footer.
    mark = _v2_wordmark(digest) or (
        f'<span class="v2-csis" style="font-family:{_V2_SERIF};font-size:54px;line-height:50px;color:#FFFFFF;">CSIS</span>')
    band = (f'<div bgcolor="{_V2_NAVY}" class="mast-band" style="background-color:{_V2_NAVY};padding:30px 16px 22px;'
            'text-align:center;">'
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" class="v2-mrow" '
            'style="margin:0 auto;"><tr>'
            f'<td class="v2-mk" valign="middle" style="padding:0 18px 0 0;vertical-align:middle;">{mark}</td>'
            '<td valign="middle" style="vertical-align:middle;">'
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0" class="v2-namebox"><tr>'
            '<td class="v2-nbt" style="border:2px solid #4A90D0;border-radius:6px;padding:10px 22px;">'
            f'<h1 class="v2-name" style="margin:0;font-family:{_V2_SANS};font-size:27px;font-weight:700;'
            'letter-spacing:1.5px;line-height:1.2;color:#FFFFFF;">KOREA DAILY BRIEF</h1></td></tr></table>'
            '</td></tr></table>'
            'td_date</div>')
    if PRINT:
        strip = ""          # links and a notice for the inbox; nothing to click on paper
    listen = ""
    if digest.get("audio_url") and not PRINT:
        mins = digest.get("audio_minutes")
        title = f"Listen, {int(mins)} min" if isinstance(mins, (int, float)) and mins > 0 else "Listen to today&#8217;s brief"
        href = digest.get("listen_url") or digest["audio_url"]
        listen = _v2_gap(
            f'<a href="{_esc(href)}" class="listen-bar" style="display:block;background:#FFFFFF;text-decoration:none;">'
            '<table width="100%" cellpadding="0" cellspacing="0" border="0" role="presentation"><tr>'
            f'<td style="padding:12px 0 12px 20px;vertical-align:middle;font-family:{_V2_SANS};">'
            f'<div class="listen-title" style="font-size:14px;font-weight:700;color:{_V2_INK};">{title}</div>'
            f'<div class="listen-sub" style="font-size:12px;color:{_V2_META};margin-top:1px;">The audio edition, read aloud</div></td>'
            f'<td align="right" style="padding:12px 20px 12px 8px;vertical-align:middle;font-family:{_V2_SANS};">'
            f'<span class="listen-btn" style="display:inline-block;border:1px solid {_V2_NAVY};padding:6px 12px;'
            f'font-size:13px;font-weight:700;color:{_V2_NAVY};white-space:nowrap;">Play</span></td>'
            '</tr></table></a>', top=12, bottom=0)
    # The date, the issue number and the reading time, under the name on the
    # navy band. Each part is nowrap and the space after it is where a phone
    # breaks the line, so it wraps whole parts and never runs off the screen.
    facts = [f"No. {int(issue)}"] if isinstance(issue, (int, float)) and issue > 0 else []
    facts.append("%%READMIN%% min read")
    nw = '<span style="white-space:nowrap;">'
    band = band.replace("td_date", (
        f'<div class="v2-mdate" style="margin-top:16px;font-family:{_V2_SANS};font-size:13px;line-height:1.6;'
        f'color:{_V2_FOOT};"><b style="white-space:nowrap;color:#FFFFFF;">{now:%A, %B} {now.day}, {now.year}</b>'
        '<!--c-->' + "".join(f"&emsp; {nw}{f}</span>" for f in facts) + '<!--/c--></div>'))
    # The contents card: the contents line and the shortened-sections note,
    # nothing else (the Peninsula status line is gone; its facts live in
    # Pyongyang Watch and the location watch). Built in _v2_finish, which
    # leaves it out when it would be empty, as on paper.
    date_card = "%%TOCCARD%%"
    # The band sits in the cards' gap, so its edges are theirs: 16px in from
    # the column (8px on a phone, by the gap's own rule), with or without
    # the stylesheet. It used to run the column's full width, wider than
    # every card under it.
    band = f'<div class="v2-gap" style="padding:0 16px;">{band}</div>'
    return f'<!--v2--><a name="top" id="top"></a>{strip}{band}{listen}{date_card}'


def _v2_numbers(digest: dict) -> str:
    """Peninsula hard numbers on a white card: navy figures, signed changes in green and red.

    Fixed-width blocks that wrap by themselves: one row of six on a desktop,
    two rows of three on a phone, with or without the stylesheet. Outlook,
    which cannot wrap blocks, gets a table of its own in conditional comments.
    A figure the data lacks shows as a muted "No data" rather than dropping
    its box, so the strip has the same six boxes every day.
    """
    m = digest.get("market_indicators") or {}
    cells = []
    missing = []

    def delta(pct, unit="%"):
        try:
            v = float(pct)
        except (TypeError, ValueError):
            return ""
        if v > 0:
            return f'<span style="color:{UP_GREEN};">+{v:.1f}{unit}</span>'
        if v < 0:
            return f'<span style="color:{DOWN_RED};">&minus;{abs(v):.1f}{unit}</span>'
        return f'<span style="color:{_V2_META};">flat</span>'

    def cell(label, value, sub):
        if value in (None, "", "None", "—", "$—", "$"):
            missing.append(label)
            value = f'<span style="font-size:13px;font-weight:400;color:{_V2_META};">No data</span>'
            sub = ""
        # A hairline between cells, on the left of every cell but the first.
        # On a phone the six wrap three to a row and the fourth cell opens the
        # second row, so the stylesheet takes its hairline off (v2-c4).
        n = len(cells)
        rule = "border-left:1px solid #E2E6EC;" if n else ""
        cls = "v2-cell v2-c4" if n == 3 else "v2-cell"
        cells.append(
            '<!--[if mso]><td width="94" valign="top"><![endif]-->'
            f'<div class="{cls}" style="display:inline-block;vertical-align:top;width:94px;box-sizing:border-box;'
            f'padding:10px 0 9px;{rule}text-align:center;font-family:{_V2_SANS};">'
            f'<div style="font-size:11px;font-weight:700;'
            f'text-transform:uppercase;color:{_V2_META};white-space:nowrap;">{label}</div>'
            f'<div style="font-size:16px;font-weight:700;color:{_V2_NAVY};'
            f'margin-top:3px;line-height:1.15;white-space:nowrap;">{value}</div>'
            f'<div style="font-size:11px;line-height:1.35;color:{_V2_META};'
            f'margin-top:2px;">{sub or "&nbsp;"}</div></div>'
            '<!--[if mso]></td><![endif]-->')

    k, w, b, r = (m.get(x) or {} for x in ("kospi", "usd_krw", "brent", "bok_rate"))
    cell("KOSPI", _esc(str(k.get("value", ""))), delta(k.get("change_pct")))
    cell("USD/KRW", _esc(str(w.get("value", ""))), delta(w.get("change_pct")))
    cell("Brent", "$" + _esc(str(b.get("value"))) if b.get("value") else "", delta(b.get("change_pct")))
    ap = ((digest.get("public_sentiment") or {}).get("presidential_approval") or {})
    if not ap.get("value"):
        cell("Lee approval", "", "")
    else:
        sub = ""
        try:
            from poll_history import delta as _poll_delta
            d = _poll_delta()
            if d:
                sub = delta(d[0], unit=" pts").replace(".0 pts", " pts")
        except Exception:                                       # noqa: BLE001
            pass
        when = _re.sub(r",?\s*\d{4}$", "", str(ap.get("last_updated") or "").strip())
        when = _re.sub(r"^([A-Z][a-z]{2})[a-z]*", r"\1", when)
        _iso = _re.search(r"(\d{4})-(\d{2})-(\d{2})", when)
        if _iso:            # "week of 2026-10-16" wrapped to three lines in a 96px cell
            try:
                when = datetime(*map(int, _iso.groups())).strftime("%b %-d")
            except ValueError:
                pass
        # Each part whole on its line: "+2 pts" may sit over "Oct 13-15", but
        # the date never breaks at its hyphen.
        sub = " ".join(f'<span style="white-space:nowrap;">{x}</span>'
                       for x in (sub, _esc(when) if when else "") if x)
        cell("Lee approval", _esc(str(ap["value"])), sub)
    kc = digest.get("kcna_delta") or {}
    days = kc.get("days_since_last_appearance")
    if kc.get("kim_appearance_today"):
        cell("Kim last seen", "Today", "public appearance")
    elif isinstance(days, int) and days > 0:
        seen = ""
        try:
            raw = str(digest.get("digest_date", "")).strip()
            for fmt in ("%A, %B %d, %Y", "%Y-%m-%d", "%B %d, %Y"):
                try:
                    from datetime import timedelta
                    seen = (datetime.strptime(raw, fmt) - timedelta(days=days)).strftime("%b %-d")
                    break
                except ValueError:
                    continue
        except Exception:                                       # noqa: BLE001
            seen = ""
        # The date as the figure, how long ago under it: "Oct 20" over "1 day
        # ago" reads as one fact where "1 day" over "ago, Oct 20" split it.
        # Red from a week.
        ago = f"{days} day{'s' if days != 1 else ''} ago"
        ago = f'<span style="color:{DOWN_RED};">{ago}</span>' if days >= 7 else ago
        cell("Kim last seen", seen or ago, ago if seen else "")
    else:
        cell("Kim last seen", "", "")
    cell("BOK rate", _esc(str(r.get("value", ""))), _esc(str(r.get("last_change", ""))))
    if len(missing) == len(cells):
        return ""
    return ('<!--v2--><!--c--><a name="markets" id="markets"></a>'
            + _v2_gap('<table width="100%" cellpadding="0" cellspacing="0" border="0" class="v2-card v2-hn" '
                      'style="background:#FFFFFF;"><tr><td align="center" style="padding:4px 8px;text-align:center;font-size:12px;">'
                      '<!--[if mso]><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr><![endif]-->'
                      # A space between blocks is the line-break opportunity;
                      # without one the six never wrap.
                      + " ".join(cells)
                      + '<!--[if mso]></tr></table><![endif]--></td></tr></table>')
            + '<!--/c-->')


def _v2_glance(digest: dict, memo_items: list) -> str:
    """Today at a glance as classic sets it: a pale blue ground, a rule down the left, the
    three items numbered in navy circles. _v2_card paints the tint (the class marks it)."""
    rows = ""
    for i, mi in enumerate(memo_items[:3]):
        text = mi if isinstance(mi, str) else (mi.get("text", "") if isinstance(mi, dict) else str(mi or ""))
        rows += (f'<tr><td width="32" valign="top" style="padding:8px 0 6px;vertical-align:top;">'
                 f'<div style="width:24px;height:24px;border-radius:50%;background:{_V2_ACCENT};color:#FFFFFF;'
                 f'text-align:center;line-height:24px;font-size:13px;font-weight:700;font-family:{_V2_SERIF};">{i + 1}</div></td>'
                 f'<td valign="top" style="padding:8px 0 6px;vertical-align:top;font-family:{_V2_SANS};'
                 f'font-size:14px;line-height:1.5;color:{_V2_INK};">{_emphasis(_esc(text))}</td></tr>')
    today = _happening_rows(digest)
    if today:
        rows += (f'<tr><td colspan="2" class="v2-rule" style="padding:9px 0 3px;border-top:1px solid {_V2_TINT_RULE};'
                 f'font-family:{_V2_SANS};font-size:13px;line-height:1.5;color:{_V2_BODY};">'
                 f'<b style="color:{_V2_NAVY};">Happening today</b>&nbsp; '
                 + "; ".join(_esc(r).rstrip(".") for r in today) + '.</td></tr>')
    return (f'<!--v2--><div><a name="memo" id="memo"></a>{_v2_bar("Today at a Glance", numbered=False)}'
            f'<table width="100%" cellpadding="0" cellspacing="0" border="0" class="v2-glance">'
            f'{rows}</table></div>')


# A full stop that ends an abbreviation or an initial, not a sentence.
_V2_ABBR = _re.compile(r"(?:\b(?:[A-Z]\.){1,3}|\b(?:Gen|Lt|Col|Maj|Capt|Adm|Sgt|Dr|Mr|Ms|Mrs|No|St|Jr|Sr|Rep|Sen|"
                       r"Gov|Pres|Amb|Prof|vs|Inc|Corp|Co|Ltd|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.)$")
_V2_QUOTE = _re.compile(r"(?<![A-Za-z])'|'(?![A-Za-z])")
# Abbreviations _V2_ABBR misses, mostly lower case, that are never a
# sentence end before a capital ("at 9 a.m. Seoul time", "e.g. Samsung").
_V2_ABBR_LC = _re.compile(r"\b(?:a\.m|p\.m|e\.g|i\.e|approx|est|Dept|Univ|Mt|Ft|Op|Fig|Vol)\.$")


def _v2_sentence_ends(text: str):
    """Each text up to a real sentence end, shortest first.

    A full stop, question or exclamation mark (with any closing quote or
    bracket) before a space and a capital or a figure. Not one that closes an
    abbreviation or an initial (U.S., Gen.), nor one inside a quotation or
    inside the model's **bold** or *italic* marks.
    """
    for m in _re.finditer(r"[.!?]['\"’”)]?(?=\s+['\"‘“(]?[A-Z0-9*])", text):
        left = text[:m.end()]
        bare = left.rstrip("'\"’”)")
        if _V2_ABBR.search(bare) or _V2_ABBR_LC.search(bare):
            continue
        if (left.count("*") % 2 or left.count('"') % 2 or left.count("“") != left.count("”")
                or len(_V2_QUOTE.findall(left)) % 2 or left.count("‘") != left.count("’")
                and "‘" in left):
            continue
        yield left


def _v2_paragraphs(text: str, limit: int = 60) -> list:
    """A body over `limit` words as two paragraphs, split at the sentence end nearest its middle.

    Nothing is reworded: the two parts are the text, cut at a space. A cut is
    never made after an abbreviation or an initial, inside a quotation or
    inside the model's **bold** marks, nor where either side would be under
    twenty words; with no such sentence end the body stays one paragraph.
    """
    words = len(text.split())
    if words <= limit:
        return [text]
    best = None
    for left in _v2_sentence_ends(text):
        n = len(left.split())
        if n < 20 or words - n < 20:
            continue
        if best is None or abs(n - words / 2) < best[0]:
            best = (abs(n - words / 2), len(left))
    if not best:
        return [text]
    return [text[:best[1]].strip(), text[best[1]:].strip()]


def _v2_top_stories(stories: list) -> str:
    """Each story: its outlets as the kicker, a serif headline, the body (two paragraphs when long)."""
    out = ""
    for st in stories:
        cat = _esc(_str(st.get("category_tag", st.get("category", ""))))
        headline = _emphasis(_esc(st.get("headline", "")))
        paras = _v2_paragraphs(str(st.get("body", "") or ""))
        body = "".join(f'<p style="margin:{"5px" if n == 0 else "8px"} 0 0;font-size:14px;line-height:1.55;'
                       f'color:{_V2_BODY};">{_emphasis(_esc(t))}</p>' for n, t in enumerate(paras) if t)
        # The same source line as classic, each outlet its own link when
        # run.py found one, in the kicker's teal.
        src = _top_story_sources(st).replace(
            "color:#6B7280;text-decoration:underline;text-decoration-color:#C9D1DC;",
            f"color:{_V2_TEAL};text-decoration:none;")
        url = st.get("url", "")
        out += (f'<div class="v2-it" style="padding:12px 0 13px;border-top:1px solid {_V2_HAIR};">'
                f'{_v2_kicker(src, cat)}'
                f'<h3 style="margin:0;{_V2_HEAD.replace("15px", "16px")}">'
                f'{_link_or_text(headline, url, style=_V2_LINK)}</h3>{body}</div>')
    return (f'<!--v2--><div><a name="top-stories" id="top-stories"></a>'
            f'{_sec_label("Top Stories")}{out}</div>')


def _v2_lead(text: str, sentences: int = 2, words: int = 50, min_words: int = 4, min_rest: int = 8) -> str:
    """The text's first `sentences` sentences, or as many of them as fit in `words` words.

    The owner found one sentence per story too short. What is kept is the
    first sentence, then the second as well when the two together are no
    more than `words` words: two sentences or about fifty words, whichever
    comes first. A first sentence longer than that is kept whole, since
    nothing is cut mid-sentence.

    The cut is made at a real sentence end only (_v2_sentence_ends): never
    after an abbreviation or an initial, nor inside a quotation or the
    model's emphasis marks. Nothing is reworded: what is kept is the text up
    to that point. A "sentence" under `min_words` words is taken as a
    mis-split and the next end is tried; when what would be cut is under
    `min_rest` words, the text stays whole, since a link to read a few more
    words costs more than it saves.
    """
    text = str(text or "")
    total = len(text.split())
    keep, count = None, 0
    for left in _v2_sentence_ends(text):
        n = len(left.split())
        if n < min_words or (keep is not None and n - len(keep.split()) < min_words):
            continue
        if keep is not None and n > words:
            break
        keep, count = left, count + 1
        if count >= sentences:
            break
    # The text's own end is a sentence end too, though _v2_sentence_ends
    # never yields it: a text of two sentences within the limit stays whole.
    if keep is None or total - len(keep.split()) < min_rest or (count < sentences and total <= words):
        return text
    return keep.strip()


def _v2_first_sentence(text: str, min_words: int = 4, min_rest: int = 8) -> str:
    """The text's first sentence alone (_v2_lead with one sentence and no word limit)."""
    return _v2_lead(text, 1, 10 ** 6, min_words, min_rest)


# What the email shortens to its lead (_v2_lead), by section anchor: each list
# in the digest and the fields of its items that carry running text.
# Untouched: top stories (full text), the glance, Overnight and The Wire
# (already one line), the calendars, the numbers strip, Pyongyang Watch's
# bottom line, and every quotation, which is never cut short.
_V2_SHORTEN = (
    ("rok-gov", "rok_government", ("detail",)),
    ("rok-gov", "rok_personnel", ("detail",)),
    ("rok-gov", "rok_assembly", ("detail",)),
    ("business", "business_economy", ("body_text",)),
    ("nea", "northeast_asia", ("body_text",)),
    ("world", "korea_world", ("body_text",)),
    ("hill", "capitol_hill", ("body_text",)),
    ("analysis", "opeds_today", ("summary",)),
    ("analysis", "academic_today", ("summary", "policy_implication")),
    ("analysis", "social_statements", ("analyst_note",)),
    ("analysis", "official_x_posts", ("analyst_note",)),
    ("satellite", "bp_locations", ("note",)),
)


def _v2_shorten(digest: dict) -> tuple:
    """A copy of the digest with every item outside the top stories cut to its lead (_v2_lead).

    Returns (copy, {anchor: url}), the url being that section on the issue's
    web page, digest_{date}.html, which carries the full text. Only the
    email is shortened, and only when that page exists: without a web_url
    there is nowhere to read the rest, and the copy is left whole. Nor when
    FULL_TEXT is set: that render is the web page, which is the full text.
    """
    import copy
    web_url = digest.get("web_url", "")
    base = web_url[:-len("latest.html")] if web_url.endswith("latest.html") else ""
    page = _issue_file(digest, base, "html") or web_url
    if FULL_TEXT or not page:
        return digest, {}
    d = copy.deepcopy(digest)
    cut = set()

    def shorten(obj, field, anchor):
        if isinstance(obj, dict) and isinstance(obj.get(field), str):
            # Analysis keeps one sentence: its first is the piece's own
            # summary, and a second was too often the model's commentary on
            # it ("The timing aligns with...").
            short = _v2_lead(obj[field], 1 if anchor == "analysis" else 2)
            if short != obj[field]:
                obj[field] = short
                cut.add(anchor)

    for anchor, key, fields in _V2_SHORTEN:
        for item in d.get(key) or []:
            for f in fields:
                shorten(item, f, anchor)
    kc = d.get("kcna_delta")
    if isinstance(kc, dict):
        shorten(kc, "kim_activity", "kcna")
        for art in kc.get("top_articles") or []:
            shorten(art, "summary", "kcna")
        for off in kc.get("senior_officials") or []:
            shorten(off, "activity", "kcna")
    for f in ("body", "summary"):
        shorten(d.get("imagery_report"), f, "satellite")
    shorten(d.get("us_korea_deals"), "state_of_play", "trade")
    shorten(d.get("key_stat"), "context", "key-stat")
    shorten(d.get("election_tracker"), "summary", "election")
    return d, {a: f"{page}#{a}" for a in cut}


def _v2_status_facts(digest: dict) -> list:
    """The Peninsula status line's facts, in plain words, from tracker data only.

    Kim Jong Un's last appearance and the KCNA watch flag come from
    kcna_delta (the same fields the numbers strip and the glance's tracker
    row read), the flag's change from run.py's _kcna_trend, the provocation
    count from _provocations (the CSIS provocations database), and the
    monitored sites from bp_locations and _bp_changes. A fact whose data is
    missing is left out, never guessed.
    """
    facts = []
    kc = digest.get("kcna_delta") if isinstance(digest.get("kcna_delta"), dict) else {}
    days = kc.get("days_since_last_appearance")
    if kc.get("kim_appearance_today") is True:
        facts.append("Kim seen in public today.")
    elif isinstance(days, int) and not isinstance(days, bool) and days > 0:
        facts.append(f"Kim last seen {days} day{'s' if days != 1 else ''} ago.")
    trend = digest.get("_kcna_trend") if isinstance(digest.get("_kcna_trend"), dict) else {}
    if kc and not kc.get("data_unavailable"):
        if kc.get("silence_today") is True:
            facts.append("KCNA silent today.")
        elif isinstance(kc.get("watch_flag"), bool):
            up, prev = kc["watch_flag"], trend.get("prev_watch_flag")
            if up and prev is False:
                fact = "KCNA watch flag up, from none yesterday."
            elif not up and prev is True:
                fact = "KCNA watch flag down from yesterday."
            elif up and prev is True:
                fact = "KCNA watch flag up for a second day."
            else:
                fact = "KCNA watch flag up." if up else "No KCNA watch flag."
            wk, of = trend.get("watch_days_week"), trend.get("week_days")
            if isinstance(wk, int) and isinstance(of, int) and wk > 1:
                fact = fact[:-1] + f"; {wk} of the last {of} days."
            facts.append(fact)
    prov = digest.get("_provocations") if isinstance(digest.get("_provocations"), dict) else {}
    if isinstance(prov.get("count"), int):
        n, span = prov["count"], prov.get("days", 7)
        # A zero is left unsaid: a day whose database push failed would read
        # as calm, and false reassurance is the worse error.
        if n:
            facts.append(f"{n} provocation{'s' if n != 1 else ''} logged in the last {span} days.")
    locs = [x for x in digest.get("bp_locations") or [] if isinstance(x, dict) and x.get("name")]
    changes = digest.get("_bp_changes")
    if locs and isinstance(changes, list):
        n = len([c for c in changes if c])
        facts.append(f"New reporting at {n} of {len(locs)} monitored sites." if n
                     else f"No new reporting at the {len(locs)} monitored sites.")
    if locs and all(str(x.get("status") or "").strip() for x in locs):
        hot = sum(1 for x in locs if str(x["status"]).strip().lower() in ("elevated", "alert"))
        if hot:
            facts.append(f"Elevated or alert at {hot} site{'s' if hot != 1 else ''}.")
    return facts


def _v2_status(digest: dict) -> str:
    """The tracker facts no other part of the brief states, as one meta line in Pyongyang Watch.

    This was the Peninsula status line at the top, which the owner removed.
    Its other facts are shown where they belong: Kim's last appearance in the
    numbers strip and Pyongyang Watch, the sites with new reporting and the
    elevated count in the location watch, a changed tariff rate in the trade
    tracker. What is left is the KCNA watch flag with its trend and the
    provocations logged; nothing when the trackers hold neither.
    """
    facts = [f for f in _v2_status_facts(digest)
             if f.startswith(("KCNA", "No KCNA")) or "provocation" in f]
    if not facts:
        return ""
    return (f'<!--c--><div class="v2-trk-line" style="font-size:12px;line-height:1.5;color:{_V2_META};margin-top:4px;">'
            + " ".join(facts) + '</div><!--/c-->')


def _v2_tomorrow(digest: dict, limit: int = 3) -> list:
    """What is scheduled for the day after the issue: the model's calendar, the
    fixed observances and the committee schedules, as short lines, at most `limit`.

    An event that merely continues tomorrow (a strike that began last week)
    is not one scheduled for tomorrow and is left out.
    """
    today = _issue_day(digest)
    if today is None:
        return []
    from datetime import timedelta
    tmr = today + timedelta(days=1)
    rows = []
    try:
        import korea_calendar
        for raw in digest.get("calendar_watch") or []:
            n = korea_calendar.normalize(raw, today)
            if n and n.get("_date") == tmr.isoformat() and n.get("headline") and not korea_calendar.off_topic(n):
                rows.append(_str(n["headline"]))
        rows += [_str(c["headline"]) for c in korea_calendar.upcoming(tmr, days=0)]
    except Exception:                                           # noqa: BLE001
        pass
    for ev in digest.get("hill_calendar") or []:
        if isinstance(ev, dict) and ev.get("title") and str(ev.get("date", ""))[:10] == tmr.isoformat():
            rows.append(hill_event_text(ev) + (f" ({ev['time']})" if ev.get("time") else ""))
    out, seen = [], set()
    for r in rows:
        k = _re.sub(r"\W+", " ", r).strip().lower()
        if r and k not in seen:
            seen.add(k)
            out.append(r)
    return out[:limit]


def _v2_reply_address() -> str:
    """The address replies reach: send_email's own Reply-To, so the two cannot drift apart."""
    try:
        from send_email import reply_address
        return reply_address()
    except Exception:                                           # noqa: BLE001
        return ""


def _v2_signoff(digest: dict) -> str:
    """The closing card before the footer: the sign-off with the issue number,
    tomorrow's scheduled items when there are any, and an invitation to write in."""
    issue = digest.get("issue_no")
    no = (f'<span style="font-size:12px;font-weight:400;color:{_V2_ON_BLACK};">&emsp;No. {int(issue)}</span>'
          if isinstance(issue, (int, float)) and issue > 0 else "")
    inner = (f'<div style="font-size:15px;font-weight:700;line-height:1.35;color:#FFFFFF;">'
             f'That&#8217;s today&#8217;s brief.{no}</div>')
    ahead = _v2_tomorrow(digest)
    if ahead:
        inner += (f'<div style="margin-top:10px;font-size:11px;font-weight:700;letter-spacing:0.5px;'
                  f'text-transform:uppercase;color:{_V2_ON_BLACK};">Tomorrow</div>'
                  + "".join(f'<div style="margin-top:3px;font-size:13px;line-height:1.5;color:#FFFFFF;">'
                            f'{_emphasis(_esc(r))}</div>' for r in ahead))
    addr = _v2_reply_address()
    if addr:
        ask = "Write to" if PRINT else "Reply to this email or write to"
        inner += (f'<div class="v2-rule" style="margin-top:12px;padding-top:9px;border-top:1px solid #3A4048;'
                  f'font-size:13px;line-height:1.5;color:{_V2_ON_BLACK};">Feedback and tips are welcome. {ask} '
                  f'<a href="mailto:{_esc(addr)}" style="color:#FFFFFF;font-weight:700;">'
                  f'{_esc(addr)}</a>.</div>')
    # Black in both schemes, so the brief visibly ends before the footer.
    return ('<!--v2--><!--c-->' + _v2_gap(
        '<table width="100%" cellpadding="0" cellspacing="0" border="0" class="v2-card v2-signoff" '
        f'style="background:{_V2_BLACK};"><tr><td class="v2-in" style="padding:16px 20px 14px;font-family:{_V2_SANS};">'
        f'{inner}</td></tr></table>') + '<!--/c-->')


def _v2_kcna(kc: dict, digest: dict | None = None) -> str:
    """Pyongyang Watch: Kim's status, any quotes, the top KCNA articles, the
    senior officials around him and the bottom line.

    The structure is classic's; the type is the house item's. _v2_card sets
    its body on a charcoal ground (_v2_pw_shade), the one card that is not
    white, at the owner's request.
    """
    unavailable = kc.get("data_unavailable", False)
    silence = kc.get("silence_today", False) and not unavailable
    note = ""
    if unavailable:
        note += (f'<div style="font-size:13px;line-height:1.5;color:{_V2_META};margin-bottom:6px;">'
                 'No new KCNA dispatches ingested today; showing last known status.</div>')
    if silence:
        note += (f'<div style="font-size:14px;font-weight:700;color:{TAEGUK_RED};margin-bottom:6px;">'
                 'Complete KCNA silence today</div>')
    days = kc.get("days_since_last_appearance")
    activity = _esc(kc.get("kim_activity") or "")
    if kc.get("kim_appearance_today"):
        status = "Public appearance" + (":" if activity else "")
    else:
        status = "No public appearance today"
        activity = (f"last seen {days} day{'s' if days != 1 else ''} ago"
                    if isinstance(days, int) and days > 0 else "")
        status += "," if activity else ""
    flag = (f', <span style="color:{TAEGUK_RED};">watch flag up</span>'
            if kc.get("watch_flag") and not silence and not unavailable else "")
    out = (f'<div class="v2-it" style="padding:12px 0;border-top:1px solid {_V2_HAIR};">{note}'
           f'<div style="font-size:12px;font-weight:700;line-height:1.35;color:{_V2_TEAL};margin-bottom:2px;">'
           f'Kim Jong Un{flag}</div>'
           f'<div style="font-size:14px;line-height:1.5;color:{_V2_INK};"><b>{status}</b> {activity}</div>'
           f'{_v2_status(digest or {})}</div>')
    for q in (kc.get("key_quotes") or [])[:2]:
        qt = _esc(q.get("quote", ""))
        if not qt:
            continue
        src = _esc(q.get("source_article", ""))
        out += (f'<div class="v2-it" style="padding:10px 0;border-top:1px solid {_V2_HAIR};">'
                f'<div style="padding-left:12px;border-left:3px solid {TAEGUK_RED};font-size:14px;line-height:1.5;'
                f'font-style:italic;color:{_V2_INK};">&ldquo;{qt}&rdquo;</div>'
                f'<div style="font-size:12px;color:{_V2_META};margin-top:4px;padding-left:15px;">'
                f'<b style="color:{_V2_INK};">{_esc(q.get("speaker", "Kim Jong Un"))}</b>'
                + (f", {src}" if src else "") + '</div></div>')
    arts = ""
    for art in (kc.get("top_articles") or [])[:3]:
        headline = _emphasis(_esc(art.get("headline", "")))
        if not headline:
            continue
        summary = _emphasis(_esc(art.get("summary", "")))
        kicker = _v2_kicker(_esc(art.get("source", "")), "", "Kim Jong Un" if art.get("kim_related") else "")
        arts += (f'<div class="v2-it" style="padding:10px 0 11px;border-top:1px solid {_V2_HAIR};">{kicker}'
                 f'<div style="{_V2_HEAD}">{_link_or_text(headline, art.get("url", ""), style=_V2_LINK)}</div>'
                 + (f'<div style="font-size:14px;line-height:1.5;color:{_V2_BODY};margin-top:3px;">{summary}</div>'
                    if summary else "") + '</div>')
    if arts:
        out += _v2_subhead("Top KCNA articles") + arts
    officials = ""
    for off in (kc.get("senior_officials") or [])[:3]:
        name, role, act = (_esc(off.get(k, "")) for k in ("name", "role", "activity"))
        if not name or not act:
            continue
        officials += (f'<div class="v2-it" style="padding:10px 0 11px;border-top:1px solid {_V2_HAIR};">'
                      f'<div style="font-size:14px;font-weight:700;line-height:1.4;color:{_V2_INK};">{name}'
                      + (f'<span style="font-weight:400;color:{_V2_META};">, {role}</span>' if role else "")
                      + f'</div><div style="font-size:14px;line-height:1.5;color:{_V2_BODY};margin-top:2px;">{act}</div></div>')
    if officials:
        out += _v2_subhead("Senior officials") + officials
    bottom = _esc(kc.get("bottom_line", ""))
    if bottom:
        out += _v2_bottom_line(bottom)
    return f'<!--v2--><a name="kcna" id="kcna"></a><div>{_v2_bar("Pyongyang Watch")}{out}</div>'


def _v2_bottom_line(text: str) -> str:
    """Classic's callout: a rule down the left and "Bottom line:" in the accent."""
    return (f'<div class="v2-bl" style="margin:12px 0 6px;padding:1px 0 1px 12px;border-left:3px solid {_V2_ACCENT};'
            f'font-size:14px;line-height:1.55;color:{_V2_BODY};"><b style="color:{_V2_NAVY};">Bottom line:</b> {text}</div>')


def _v2_sentiment(html: str) -> str:
    """Public Sentiment's approval figure and party tiles, side by side only where they fit.

    Two table cells cannot wrap, and stripped of the media query that stacks
    them they held the page at 447px on a 375px phone. Two fixed-width blocks
    sit side by side on a desktop and stack on a phone by themselves; Outlook
    gets its table back in conditional comments. Left as it was if the markup
    has moved.
    """
    pat = _re.compile(
        r'<table width="100%" cellpadding="0" cellspacing="0" border="0" class="sentiment-table">\s*<tr>\s*'
        r'<td width="42%" valign="top" style="[^"]*">(?P<hero>.*?)</td>\s*'
        r'<td valign="top" style="padding:4px 0 4px 18px;">(?P<tiles>\s*<table.*?</table>\s*)</td>\s*</tr>\s*</table>',
        _re.S)
    m = pat.search(html)
    if not m:
        return html
    fluid = ('<!--[if mso]><table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
             '<td width="42%" valign="top"><![endif]-->'
             '<div style="display:inline-block;vertical-align:top;width:100%;max-width:236px;padding:10px 0 12px;">'
             f'{m.group("hero")}</div>'
             '<!--[if mso]></td><td valign="top"><![endif]--> '
             '<div style="display:inline-block;vertical-align:top;width:100%;max-width:300px;padding:10px 0 8px;">'
             f'{m.group("tiles")}</div>'
             '<!--[if mso]></td></tr></table><![endif]-->')
    return html[:m.start()] + fluid + html[m.end():]


def _v2_footer(digest: dict, now) -> str:
    """The navy band at the foot: the disclaimer first, as in the reference, then the links."""
    web_url = digest.get("web_url", "")
    base = web_url[:-len("latest.html")] if web_url.endswith("latest.html") else ""
    a = (lambda href, text: f'<a href="{_esc(href)}" style="color:#FFFFFF;white-space:nowrap;">{text}</a>')
    links = []
    if web_url:
        links.append(a(_issue_file(digest, base, "html") or web_url, "Read online"))
    if digest.get("audio_url"):
        links.append(a(digest["audio_url"], "Listen"))
    links.append(a((base + "archive.html") if base else web_url, "Past issues") if web_url else "")
    if base:
        links.append(a(base + "trade.html", "Trade reference"))
    links.append('<a href="#top" style="color:#FFFFFF;white-space:nowrap;">Back to top</a>')
    otd = ""
    on_this_day = digest.get("on_this_day") or []
    if on_this_day and isinstance(on_this_day[0], dict):
        it = on_this_day[0]
        rel = _esc(it.get("relevance", ""))
        otd = (f'<div style="font-size:13px;line-height:1.6;color:{_V2_FOOT};padding-bottom:14px;margin-bottom:14px;'
               f'border-bottom:1px solid #33497A;"><b style="color:#FFFFFF;">On this day, {_esc(it.get("date", ""))}.</b> '
               f'{_esc(it.get("event", ""))}' + (f" {rel}" if rel else "") + '</div>')
    issue = digest.get("issue_no")
    no = f"No. {int(issue)}&emsp;" if isinstance(issue, (int, float)) and issue > 0 else ""
    # Classic's lockup, in the same words and order, as text (Gmail blocks
    # images). Classic sets it as three cells, which held a phone at 430px
    # once its stylesheet went; here the CSIS letters and the two department
    # cells are two blocks that sit side by side where they fit and stack,
    # centred, where they do not.
    rule = "border-left:1px solid #7F8FB0;"
    cell = (f"font-family:{_V2_SANS};font-size:11px;letter-spacing:1px;text-transform:uppercase;line-height:1.4;color:{_V2_FOOT};"
            "text-align:left;")
    lockup = ('<div class="v2-lockup" style="text-align:center;padding-bottom:16px;margin-bottom:16px;'
              'border-bottom:1px solid #33497A;">'
              f'<div class="v2-lk-csis" style="display:inline-block;vertical-align:middle;padding:4px 14px 4px 0;'
              f'font-family:{_V2_SERIF};font-size:36px;letter-spacing:3px;line-height:1;color:#FFFFFF;">CSIS</div> '
              '<div style="display:inline-block;vertical-align:middle;padding:4px 0;">'
              '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
              f'<td style="{rule}padding:2px 12px;{cell}">Geopolitics and Foreign<br>Policy Department</td>'
              f'<td style="{rule}padding:2px 0 2px 12px;{cell}">Korea<br>Chair</td>'
              '</tr></table></div></div>')
    logo = _v2_logo(digest, 280)
    if logo:
        # The official lockup, as in the masthead, in place of the HTML text.
        lockup = ('<div class="v2-lockup" style="padding-bottom:16px;margin-bottom:16px;'
                  f'border-bottom:1px solid #33497A;">{logo}</div>')
    # In the cards' gap, as the masthead band is: one width, one pair of edges.
    return (f'<!--v2--><div class="v2-gap" style="padding:0 16px 16px;"><div class="v2-foot" style="background:{_V2_NAVY};padding:22px 20px 24px;'
            f'font-family:{_V2_SANS};">{lockup}{otd}'
            f'<div style="font-size:13px;line-height:1.6;color:{_V2_FOOT};">This newsletter is automatically '
            'generated, so it may contain errors. Please check all information and sources before citing. '
            'To report errors or other issues, please contact Andy Lim at '
            '<a href="mailto:alim@csis.org" style="color:#FFFFFF;">alim@csis.org</a>.</div>'
            f'<div style="font-size:12px;line-height:1.9;color:{_V2_FOOT};margin-top:12px;">You are receiving the '
            'Korea Daily Brief as a member of the CSIS Korea Chair distribution list.'
            + ("" if PRINT else "<br>" + "&emsp; ".join(x for x in links if x)) + '</div>'
            f'<div style="font-size:11px;color:{_V2_FOOT};margin-top:12px;">&copy; {now.year} Center for Strategic '
            f'and International Studies&emsp;{no}generated {now:%-I:%M %p} ET</div></div></div>')


def _v2_style(style: str) -> str:
    """Restyle one inline style declaration for v2. v2's own markup is left alone.

    One sans throughout: Georgia, Arial and the monospace figures all become
    it, at their classic sizes. Classic's greys and accent become the CSIS
    palette's. Sizes never grow.
    """
    parts = [p.split(":", 1) for p in style.split(";") if ":" in p]
    decl = {k.strip().lower(): v.strip() for k, v in parts}
    fam = decl.get("font-family", "")
    if fam in (_V2_SANS, _V2_SERIF, _V2_KO):
        return style
    if style.startswith("color:#1B2A4A;text-decoration:underline;text-decoration-color:#AEBBD0"):
        return _V2_LINK
    if "display:inline-block;margin-bottom:12px" in style and "border-bottom:2px solid" in style:
        # A trade pillar's heading: the house group label.
        return (f"font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:{_V2_NAVY};"
                f"padding-bottom:5px;border-bottom:2px solid {_V2_NAVY};margin:6px 0 10px;")
    new = {}
    if fam:
        new["font-family"] = _V2_SANS
    # A headline in classic's markup (a ministry's action, an imagery report,
    # a site name): bold, ink, 14 to 17px. It keeps the serif, at 15px at most.
    size = _re.match(r"(\d+)px$", decl.get("font-size", ""))
    if (size and 14 <= int(size.group(1)) <= 17 and decl.get("font-weight") in ("600", "700")
            and decl.get("color", "").upper() in ("#1A222E", "#1B2A4A", "#14181F")
            and fam in ("", "Georgia,serif")):
        new["font-family"] = _V2_SERIF
        new["font-size"] = f"{min(15, int(size.group(1)))}px"
    if decl.get("font-size") in ("9px", "10px"):
        new["font-size"] = "11px"       # the owner's floor for meta and labels
    if decl.get("margin-top", "").startswith("-"):
        new["margin-top"] = "8px"       # pulled up under classic's bar; under v2's it overlapped
    if decl.get("font-weight") == "600":
        new["font-weight"] = "700"
    color = decl.get("color", "").upper()
    if color in _V2_RECOLOR:
        m = _re.match(r"(\d+)px$", decl.get("font-size", ""))
        big = m and int(m.group(1)) >= 20
        # A large figure in the accent (the stat, the $350B) is a figure: navy.
        new["color"] = _V2_NAVY if big and color == "#0047A0" else _V2_RECOLOR[color]
    if not new:
        return style
    out, seen = [], set()
    for k, v in parts:
        k = k.strip().lower()
        seen.add(k)
        out.append(f"{k}:{new.get(k, v.strip())}")
    out += [f"{k}:{v}" for k, v in new.items() if k not in seen]
    return ";".join(out) + ";"


def _v2_restyle(section: str, more: dict | None = None) -> str:
    """Apply v2's type and palette to a classic section, then make any section with a bar a card."""
    if not section.lstrip().startswith("<!--v2-->"):
        # Classic's stale-imagery flag opens with a space before its comma
        # ("2026-03 , no recent reporting"); classic keeps its bytes.
        section = section.replace(' <span style="color:#9A5B00;">, ', '<span style="color:#9A5B00;">, ')
        section = _v2_buttons(section)
        section = _v2_lists(section)
        section = _re.sub(r'style="([^"]*)"', lambda m: f'style="{_v2_style(m.group(1))}"', section)
        section = _re.sub(r"style='([^']*)'", lambda m: f"style='{_v2_style(m.group(1))}'", section)
    return _v2_card(section, more)


def _v2_order(sections: list) -> list:
    """Put the content sections in _V2_ORDER, leaving everything else where it is.

    Each section carries its own anchor, so a section is identified by that.
    One the order does not name keeps its place relative to the others,
    after the named ones, so a section added later is never dropped.
    """
    def key(s):
        m = _re.search(r'<a name="([\w-]+)"', s)
        return m.group(1) if m else None
    slots = [i for i, s in enumerate(sections) if key(s) in _V2_ORDER or
             (key(s) not in (None, "top", "memo", "markets") and "%%" not in s[:40])]
    rank = {k: n for n, k in enumerate(_V2_ORDER)}
    moved = sorted((sections[i] for i in slots), key=lambda s: rank.get(key(s), len(rank)))
    out = list(sections)
    for i, s in zip(slots, moved):
        out[i] = s
    return out


def _v2_finish(body: str, more_url: str = "") -> str:
    """Name the sections in the order they rendered, then build the contents grid from them.

    `more_url` is the issue's web page when the email shortened anything: one
    line under the contents then says so, once, for every section. It used to
    be a "Shortened for email. Read online" line under nearly every card.
    """
    anchors = [(m.start(), m.group(1)) for m in _re.finditer(r'<a name="([\w-]+)"', body)]
    toc, names, prev = [], {}, -1
    for m in _re.finditer(r"%%V2N:(.*?)%%", body):
        name = ""
        for pos, a in anchors:
            if prev < pos < m.start():
                name = a
        prev = m.start()
        toc.append((_V2_TOC_SHORT.get(name, _v2_label(m.group(1))), name))
        if name:
            names[name] = _v2_label(m.group(1))     # a reference names the section in full
    counter = iter(range(1, len(toc) + 1))
    body = _re.sub(r"%%V2N:.*?%%", lambda m: f"{next(counter):02d}", body)

    def ref(m):
        n = m.group(1)
        # Navy, not teal: the references sit on the glance's tint, where teal measured 4.2:1.
        return (f' (see <a href="#{n}" style="color:{_V2_NAVY};font-weight:700;text-decoration:none;">'
                f'{names[n]}</a>)' if n in names else "")
    body = _re.sub(r"\s?%%V2REF:([\w-]+)%%", ref, body)
    # One wrapping line of short links, no numbers: the owner found the
    # grey Georgia numerals in front of each entry fussy, and a line of
    # three. One face (the sans), regular weight, navy, no underline: the
    # links are a finding aid, quieter than the headlines under them. At
    # 13px the fourteen entries take two lines on a desktop. Each link is
    # nowrap, but none is wider than a phone; the space after each is where
    # the line breaks.
    links = [(f'<a href="#{name}" style="color:{_V2_NAVY};text-decoration:none;white-space:nowrap;">{text}</a>'
              if name else f'<span style="white-space:nowrap;">{text}</span>')
             for text, name in toc]
    toc_html = ""
    if len(links) >= 4:
        toc_html = (f'<!--c--><div class="v2-toc no-print" style="font-size:12px;line-height:1.7;color:{_V2_NAVY};">'
                    f'<span style="font-size:11px;font-weight:700;letter-spacing:0.5px;text-transform:uppercase;'
                    f'color:{_V2_META};">In this issue</span>&emsp;' + "&ensp; ".join(links) + '</div><!--/c-->')
    # No "Some sections are shortened" note: the owner dropped it; "Read
    # online" in the strip above the masthead opens the full text.
    if PRINT:
        toc_html = ""       # links do nothing on paper
    body = body.replace("%%NAV%%", "")
    # v2-tocc: the web page, which has its own menu, hides the whole card.
    card = (f'<div class="v2-gap v2-tocc" style="padding:12px 16px 12px;">'
            f'{_v2_cardbox(toc_html, "12px 20px 11px")}</div>' if toc_html else "")
    return body.replace("%%TOCCARD%%", card)


def _v2_unchrome(body: str) -> str:
    """The body without v2's furniture, so the word count matches what classic counts."""
    return _re.sub(r"<!--c-->.*?<!--/c-->", " ", body, flags=_re.S)


def _v2_dark_css() -> str:
    lines = []
    for light, dark in _V2_DARK_TEXT.items():
        lines.append(f'      .wrapper [style*="color:{light}"] {{ color:{dark} !important; }}')
    for light, dark in _V2_DARK_BG.items():
        lines.append(f'      .wrapper [style*="background:{light}"] {{ background-color:{dark} !important; }}')
    return "\n".join(lines)


_V2_CSS = """
    @media only screen and (max-width: 620px) {
      .wrapper .v2-gap { padding-left:8px !important; padding-right:8px !important; }
      .wrapper .v2-strip td { padding-left:8px !important; padding-right:8px !important; }
      .wrapper .v2-in { padding-left:14px !important; padding-right:14px !important; }
      .wrapper .sec-bar td { padding:9px 14px !important; }
      .wrapper .v2-name { font-size:17px !important; letter-spacing:1px !important; }
      .wrapper .v2-nbt { padding:7px 12px !important; }
      .wrapper .v2-mk { padding-right:14px !important; }
      .wrapper .v2-csis { font-size:37px !important; line-height:34px !important; }
      .wrapper .mast-meta { padding-top:2px !important; }
      .v2-cell div[style*="font-size:16px"] { font-size:15px !important; }
      .wrapper .v2-tint { padding-left:11px !important; }
      .wrapper .mast-band { padding:22px 12px 16px !important; }
      .wrapper .v2-toc { line-height:1.6 !important; }
      .v2-hn > tbody > tr > td { padding:2px 0 !important; }
      .v2-cell { width:32% !important; min-width:96px; }
      .wrapper .v2-c4 { border-left:0 !important; }
      /* The first screen: everything above the first story a little tighter,
         nothing removed. With these and the wrapping contents line, the first
         top story's headline at 375px moved from 1,278/1,327/1,408px to
         1,176/1,178/1,261px (Oct 18/19/20). The rest is the glance itself. */
      .wrapper .v2-wm { max-width:91px !important; }
      .wrapper .listen-bar td { padding-top:9px !important; padding-bottom:9px !important; }
      .wrapper .listen-bar .listen-sub { display:none !important; }
      .v2-cell { padding:7px 0 6px !important; }
      /* Classic sets h3 at 14px on a phone; a top story under an item's 15px read as the lesser of the two. */
      .wrapper .v2-it h3 { font-size:15px !important; }
      .wrapper .v2-rg > .v2-rc { width:100% !important; max-width:none !important; padding-right:0 !important; }
      .wrapper .v2-ps, .wrapper .v2-pp { max-width:none !important; }
      .wrapper .v2-mdate { font-size:12px !important; margin-top:9px !important; }
      .wrapper .v2-lk-csis { font-size:30px !important; }
    }
    /* Where the stylesheet survives, the ROK cards pair up at equal heights. */
    .v2-rg { display:flex !important; flex-wrap:wrap; justify-content:space-between; }
    .v2-rg > .v2-rc { display:flex !important; width:49% !important; max-width:none !important; padding:0 0 10px !important; }
    /* Public Sentiment, where the stylesheet survives: the party boxes as
       tall as the approval block beside them, their figures centred, so the
       row has no empty band above and below the boxes. */
    .v2-psr { display:flex !important; flex-wrap:wrap; justify-content:space-between; align-items:stretch; }
    .v2-ps, .v2-pp { display:flex !important; }
    .v2-pst { flex:1; }
    .v2-pp > div { display:flex !important; width:100%; }
    .v2-psc { display:flex !important; }
    .v2-psb { flex:1; display:flex; flex-direction:column; justify-content:center; }
    .v2-rct { height:100%; }
    .v2-rcb { height:100%; }
    @media only screen and (min-width: 621px) and (max-width: 768px) {
      .wrapper { max-width:640px !important; }
    }
    @media (prefers-color-scheme: dark) {
      body > table { background:#121212 !important; }
      .wrapper .sec-bar, .wrapper .mast-band, .wrapper .v2-foot { background:#001F59 !important; }
      .wrapper .v2-it, .wrapper .v2-rule, .wrapper .v2-rule td { border-color:#3A4048 !important; }
      .wrapper .v2-sub, .wrapper .v2-btn, .wrapper [style*="border-bottom:2px solid #001F59"] { border-color:#8FB6E8 !important; }
      .wrapper .v2-bl, .wrapper .v2-tint, .wrapper .v2-pst { border-left-color:#5C8FD6 !important; }
      .wrapper .v2-pst .v2-rule { border-color:#34465F !important; }
      .wrapper .v2-glance td.v2-rule { border-color:#34465F !important; }
      .wrapper .listen-bar, .wrapper .listen-bar td { background:#262A30 !important; }
      .wrapper .listen-bar .listen-title { color:#E8E6E1 !important; }
      .wrapper .listen-bar .listen-sub { color:#9AA3AE !important; }
      .wrapper .listen-bar .listen-btn { color:#8FB6E8 !important; border-color:#8FB6E8 !important; }
      .wrapper .v2-rct, .wrapper .v2-trk, .wrapper .v2-cell, .wrapper .v2-psb { border-color:#3A4048 !important; }
      .wrapper .v2-signoff { border:1px solid #3A4048 !important; }
      .wrapper .v2-pw { box-shadow:inset 0 0 0 1px #4A515C; }
      .v2-pre { color:#E8E6E1 !important; }
""" + _v2_dark_css() + """
    }
"""

_V2_TAG = _re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)\b((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>")
_V2_FAM = _re.compile(r"font-family:([^;\"']*);?")
_V2_INHERITS = {"div", "span", "p", "a", "b", "strong", "em", "i", "u", "small"}
_V2_BOUNDARY = {"table", "tbody", "thead", "tr", "td", "th"}
_V2_VOID = {"br", "img", "hr", "meta", "link", "input", "col", "area", "base", "wbr", "source"}


def _v2_lean_fonts(body: str) -> str:
    """Drop a font-family that only repeats the one its parent already sets.

    Every text node carried its own font stack, which is most of a kilobyte
    per section once the stack names the platform faces. Inheritance is
    trusted only below a table cell: Outlook does not carry a font into a
    nested table, so a family declared on or inside a table, row or cell
    starts afresh and is always kept, as is any heading's.
    """
    stack: list = []
    out, last = [], 0
    for m in _V2_TAG.finditer(body):
        close, tag, attrs = m.group(1), m.group(2).lower(), m.group(3)
        if close:
            for j in range(len(stack) - 1, -1, -1):
                if stack[j][0] == tag:
                    del stack[j:]
                    break
            continue
        parent = stack[-1][1] if stack else None
        sm = _re.search(r'style="([^"]*)"|style=\'([^\']*)\'', attrs)
        style = (sm.group(1) if sm.group(1) is not None else sm.group(2)) if sm else ""
        fm = _V2_FAM.search(style)
        fam = fm.group(1).strip() if fm else None
        if tag in _V2_BOUNDARY:
            eff = fam
        else:
            eff = fam or parent
            if fam and tag in _V2_INHERITS and fam == parent:
                lean = style[:fm.start()] + style[fm.end():]
                a0 = m.start(3) + sm.start(1 if sm.group(1) is not None else 2)
                out.append(body[last:a0])
                out.append(lean)
                last = a0 + len(style)
        if tag not in _V2_VOID and not attrs.rstrip().endswith("/"):
            stack.append((tag, eff))
    out.append(body[last:])
    return "".join(out).replace(' style=""', "")


_V2_SEL_CLASS = _re.compile(r"\.([A-Za-z][\w-]*)")
_V2_SEL_ATTR = _re.compile(r'\[style\*="([^"]+)"\]')


def _v2_live_selector(sel: str, classes: set, body: str) -> bool:
    """False when the selector names a class, or an inline-style substring, that the body never uses."""
    if any(c not in classes for c in _V2_SEL_CLASS.findall(sel)):
        return False
    return all(a in body for a in _V2_SEL_ATTR.findall(sel))


def _v2_prune_css(css: str, body: str) -> str:
    """The stylesheet without the rules that can match nothing in this issue.

    v2 ships classic's stylesheet with its own appended, and most of classic's
    rules (its flash table, deal cards, the dark panel, a dark mapping for
    every colour classic uses) name a class or a colour v2 never prints. They
    were a tenth of the file, and the file is held under Gmail's clip. A
    selector is dropped only when it names a class absent from every class
    attribute, or an inline-style substring absent from the body; a selector
    on bare elements is always kept. One level of @media nesting, which is
    all the brief has.
    """
    classes = set()
    for c in _re.findall(r'class="([^"]*)"', body):
        classes.update(c.split())
    out, i, n = [], 0, len(css)

    def rules(block: str) -> str:
        kept = []
        for sel, decl in _re.findall(r"([^{}]+)\{([^{}]*)\}", block):
            live = [x for x in sel.split(",") if _v2_live_selector(x.strip(), classes, body)]
            if live:
                kept.append(",".join(live).strip() + " {" + decl + "}")
        return "\n".join(kept)

    while i < n:
        j = css.find("{", i)
        if j < 0:
            out.append(css[i:])
            break
        head = css[i:j]
        if head.strip().startswith("@media") or head.strip().startswith("@supports"):
            depth, k = 1, j + 1
            while k < n and depth:
                depth += {"{": 1, "}": -1}.get(css[k], 0)
                k += 1
            inner = rules(css[j + 1:k - 1])
            if inner:
                out.append(head.strip() + " {\n" + inner + "\n}\n")
            i = k
        else:
            k = css.find("}", j)
            k = n if k < 0 else k + 1
            block = css[i:k]
            if head.strip().startswith("@"):       # @page and the like
                out.append(block)
            else:
                out.append(rules(block) + "\n")
            i = k
    return "".join(out)


def _v2_first_clause(text: str) -> str:
    """Text up to its first comma, semicolon, colon or sentence end, without the model's emphasis marks.

    A cut that would leave under six words ("President Lee Jae-myung," before
    an apposition) is not a clause; the next one is tried.
    """
    t = _re.sub(r"\*+", "", str(text or "")).strip()
    for m in _re.finditer(r"[,;:](?=\s)|[.!?](?=\s+[A-Z])", t):
        if len(t[:m.start()].split()) >= 6 and not _V2_ABBR.search(t[:m.start() + 1]):
            return t[:m.start()].strip().rstrip(".")
    return t.rstrip(".")


def _v2_preheader(digest: dict, low: int = 90, high: int = 110) -> str:
    """The inbox preview line: the glance items' first clauses, then top-story headlines, 90 to 110 characters.

    Parts are joined with full stops and added whole while they fit under
    `high`; one that would pass it is skipped for a shorter one. Text only
    from the digest, never reworded beyond the cut.
    """
    parts = []
    for mi in (digest.get("morning_memo") or [])[:3]:
        parts.append(_v2_first_clause(mi if isinstance(mi, str) else (mi or {}).get("text", "") if isinstance(mi, dict) else ""))
    parts += [_re.sub(r"\*+", "", str(st.get("headline") or "")).strip().rstrip(".")
              for st in digest.get("top_stories") or [] if isinstance(st, dict)]
    out = ""
    for p in parts:
        if not p:
            continue
        cand = f"{out} {p}." if out else f"{p}."
        if len(cand) <= high:
            out = cand
        if len(out) >= low:
            break
    if not out and parts:
        first = next((p for p in parts if p), "")
        out = first[:high].rsplit(" ", 1)[0] if len(first) > high else first
    return out


# ── Paper ───────────────────────────────────────────────────────────────────
# The preview PDF (run.write_preview_pdf) is v2 printed, with PRINT set. It is
# made on a GitHub runner, which has neither Georgia nor the platform sans, so
# Chromium fell back to Liberation Serif and DejaVu Sans. On paper the brief
# is set in the CSIS brand face, Synthèse, embedded from assets/ as data
# URIs (no Google Fonts, no network), with Liberation Sans behind it for the
# few characters it lacks (the minus sign, the won sign). make_pdf waits for
# document.fonts.ready before printing. The lockup is a data URI too.
#
# The layout is for a page, not an inbox: white, no grey ground or tints but
# the glance's, the column the page's full width, each card a navy bar over
# its items. A long section breaks across pages; an item never does, and a
# bar or group label never ends a page without the item under it. The
# running header and footer are make_pdf's. The margins are set here as
# well as passed to it (run.write_preview_pdf passes _V2_PRINT_MARGIN):
# classic's stylesheet carries "@page { margin: 12mm }", which overrides
# the margins Chromium is given, and left the header on top of the first
# bar of every page.
_V2_PRINT_MARGIN = {"top": "15mm", "bottom": "13mm", "left": "13mm", "right": "13mm"}
# Synthèse sets wider and with a taller x-height than the Liberation and
# Source faces it replaced: at the old 0.9 the Oct 21 issue ran to a tenth
# page holding only the sign-off. 0.86 brings it back to the old length.
_V2_PRINT_SCALE = 0.86
_V2_PRINT_SANS = "Synthese,'Liberation Sans',Arial,sans-serif"
# Headlines and figures in Synthèse too, at their own weights: one brand
# family on paper, nothing fetched. The runner has no Georgia, which is why
# the paper layout used to load Source Serif from Google Fonts.
_V2_PRINT_SERIF = _V2_PRINT_SANS


def _v2_print_fonts() -> str:
    """Synthèse 400 and 700 as data URIs: the PDF runner loads nothing from the network for type."""
    out = ""
    for w, name in (("400", _V2_FONTS[0]), ("700", _V2_FONTS[1])):
        uri = _v2_data_uri(name, "font/woff2")
        if uri:
            out += (f'@font-face {{ font-family:Synthese; font-style:normal; font-weight:{w}; '
                    f'src:url({uri}) format("woff2"); }}\n')
    return out


def _v2_print_head() -> str:
    return _V2_PRINT_HEAD.replace("/*FONTS*/", _v2_print_fonts(), 1)


_V2_PRINT_HEAD = (
    """<style type="text/css">
  /*FONTS*/
  @page { size: Letter; margin: %(mt)s %(mr)s %(mb)s %(ml)s; }
  html, body { background:#FFFFFF !important; -webkit-print-color-adjust:exact; print-color-adjust:exact; }
  body, body * { font-family:%(sans)s !important; }
  [style*="font-family:Georgia"], [style*="font-family:Georgia"] * { font-family:%(serif)s !important; }
  body > table, body > table > tbody > tr > td, .wrapper { background:#FFFFFF !important; }
  .wrapper { width:100%% !important; max-width:none !important; }
  .no-print, .v2-pre { display:none !important; }
  .v2-gap { padding:0 0 10px !important; }
  div.v2-it { padding-top:8px !important; padding-bottom:9px !important; }
  .mast-band { padding:16px 16px 15px !important; }
  /* Blocks, not tables, from the body down to each card's rows: Chromium
     honours break-inside:avoid on an item only when no table cell holds it. */
  body > table, body > table > tbody, body > table > tbody > tr, body > table > tbody > tr > td,
  .wrapper, .wrapper > tbody, .wrapper > tbody > tr, .wrapper > tbody > tr > td,
  .v2-card, .v2-card > tbody, .v2-card > tbody > tr, .v2-card > tbody > tr > td { display:block !important; }
  .v2-card[style*="background:#FFFFFF"] > tbody > tr > td.v2-in { padding:2px 2px 4px !important; }
  .v2-card[style*="background:#FFFFFF"] > tbody > tr > td.v2-in.v2-tint { padding:4px 14px 8px 12px !important; }
  .v2-in:not(.v2-tint):not(.v2-stat):not(.v2-pw) { background:transparent !important; }
  .v2-card[style*="background:#FFFFFF"] > tbody > tr > td.v2-in.v2-pw { padding:6px 14px 8px !important; }
  .v2-card[style*="background:#FFFFFF"] > tbody > tr > td.v2-in.v2-stat { padding:10px 14px 12px !important; }
  .sec-bar, .v2-card > tbody > tr:first-child, .v2-sub { break-after:avoid !important; page-break-after:avoid !important; }
  .v2-it, .v2-rc, .v2-bl, .v2-psr, .v2-glance tr, .v2-trk tr, .v2-foot, .v2-hn, .v2-stat {
    break-inside:avoid !important; page-break-inside:avoid !important; }
  /* The stat and sign-off cards, whole. Its own rule: a selector Chromium
     cannot parse would take the rest of the list down with it. */
  .v2-gap:has(> .v2-card:not([style*="background:#FFFFFF"])) { break-inside:avoid !important; page-break-inside:avoid !important; }
  /* The ROK agency cards one to a row, each whole. Two to a row, a pair
     that did not fit left a third of a page empty; a flex row split a card
     from its own heading. */
  /* Public Sentiment across the page's wider column: the approval block
     wide enough for its survey dates on one line, the party boxes a little
     wider, so the row ends nearer the right margin. */
  .v2-ps { max-width:240px !important; }
  .v2-pp { max-width:430px !important; }
  .v2-rg { display:block !important; }
  .v2-rg > .v2-rc { display:block !important; width:auto !important; max-width:none !important; padding:0 0 8px !important; }
  /* What opens a card (a dateline, a group label) stays with what follows. */
  .v2-card > tbody > tr > td.v2-in > :first-child:not(.v2-it) { break-after:avoid !important; page-break-after:avoid !important; }
  /* Restyled classic sections hold their items in one-column tables, where
     break-inside:avoid is ignored; as blocks they behave like v2's own. A
     table with cells side by side (the tariff tracker, a calendar row)
     stays a table. */
  .v2-in table:not(:has(> tbody > tr > td + td)), .v2-in table:not(:has(> tbody > tr > td + td)) > tbody,
  .v2-in table:not(:has(> tbody > tr > td + td)) > tbody > tr,
  .v2-in table:not(:has(> tbody > tr > td + td)) > tbody > tr > td { display:block !important; }
  a {text-decoration:none !important; }
</style>""" % {"sans": _V2_PRINT_SANS, "serif": _V2_PRINT_SERIF, "mt": _V2_PRINT_MARGIN["top"],
                     "mr": _V2_PRINT_MARGIN["right"], "mb": _V2_PRINT_MARGIN["bottom"], "ml": _V2_PRINT_MARGIN["left"]})


def _v2_font_css(base: str) -> str:
    """Synthèse for the email, where the client loads web fonts (Apple Mail, iOS Mail).

    Gmail and Outlook ignore @font-face and keep the system stack and
    Georgia: the rules below name Synthèse first and the face each element
    already had after it, at the same sizes. The overrides sit in the
    stylesheet, not in eighty inline styles, so they cost a few hundred
    bytes, and where the stylesheet is stripped nothing changes.
    """
    if not base:
        return ""
    faces = "".join(
        f'@font-face {{ font-family:Synthese; font-style:normal; font-weight:{w}; font-display:swap; '
        f'src:url({base}assets/{name}) format("woff2"); }}\n'
        for w, name in (("400", _V2_FONTS[0]), ("700", _V2_FONTS[1])))
    return (faces
            + f'    .wrapper, .wrapper [style*="font-family:-apple-system"] {{ font-family:Synthese,{_V2_SANS} !important; }}\n'
            + f'    .wrapper [style*="font-family:Georgia"] {{ font-family:Synthese,{_V2_SERIF} !important; }}\n'
            # The wordmark's alt text stands in for the CSIS letters: Georgia, never the sans.
            + f'    .wrapper .v2-wm {{ font-family:{_V2_SERIF} !important; }}\n')


def _v2_page(html: str, preheader: str = "", base: str = "") -> str:
    """Page-level v2: its stylesheet, the narrower column, and a leaner file.

    Gmail clips a message at about 102KB, and classic already reaches it on a
    long day. Comments and indentation are dropped here (conditional comments
    for Outlook are kept), and repeated font stacks go, which more than pays
    for v2's additions.
    """
    html = html.replace("</style>", _V2_CSS + ("" if PRINT else _v2_font_css(base)) + "  </style>", 1)
    if PRINT:
        html = html.replace("</head>", _v2_print_head() + "</head>", 1)
        preheader = ""
    if preheader:
        # Hidden, first in the body: the line Gmail shows after the subject.
        # The run of joiners after it keeps the client from padding the
        # preview with the masthead's text.
        b = html.find("<body")
        b = html.find(">", b) + 1
        html = (html[:b] + f'<div class="v2-pre" style="display:none;max-height:0;overflow:hidden;mso-hide:all;'
                f'font-family:{_V2_SANS};color:{_V2_INK};">{_esc(preheader)}' + "&zwnj;&nbsp;" * 24 + '</div>' + html[b:])
    # The grey ground the cards sit on.
    html = html.replace('<body style="margin:0;padding:0;background:#F2F3F5;', f'<body style="margin:0;padding:0;background:{_V2_GROUND};', 1)
    # The body's stack is classic's; v2 has one sans, its own.
    html = html.replace("font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;",
                        f"font-family:{_V2_SANS};", 1)
    html = html.replace('border="0" style="margin:0;padding:0;background:#F2F3F5;">', f'border="0" style="margin:0;padding:0;background:{_V2_GROUND};">', 1)
    # The column, fluid to 640px; Outlook's ghost table is fixed at 640.
    html = html.replace('class="wrapper" width="680"', 'class="wrapper" width="640"', 1)
    html = html.replace("width:100%;max-width:680px;margin:0 auto;background:#FFFFFF;"
                        "font-family:Arial,Helvetica,sans-serif;box-shadow:0 2px 20px rgba(0,0,0,0.08);",
                        f"width:100%;max-width:640px;margin:0 auto;background:{_V2_GROUND};font-family:{_V2_KO};", 1)
    html = html.replace('<table width="680" cellpadding', '<table width="640" cellpadding', 1)
    html = _re.sub(r"<!--(?!\[if)(?!<!\[endif\]).*?-->", "", html, flags=_re.S)
    head, sep, rest = html.partition("</head>")
    head = _re.sub(r"/\*.*?\*/", "", head, flags=_re.S)
    rest = _v2_lean_fonts(rest)
    # The first stylesheet only: the Outlook one in conditional comments is left alone.
    sm = _re.search(r"(<style[^>]*>)(.*?)(</style>)", head, _re.S)
    if sm:
        head = head[:sm.start(2)] + _v2_prune_css(sm.group(2), rest) + head[sm.end(2):]
    html = head + sep + rest
    html = _re.sub(r"\n\s+", "\n", html)
    # A line break next to a block or table tag renders as nothing at all.
    return _re.sub(r"\n+(?=</?(?:div|table|tr|td|tbody|p|h[1-6]|a name)[\s>])|(?:(?<=</div>)|(?<=</td>)|(?<=</tr>))\n+", "", html)


if __name__ == "__main__":
    import json
    from pathlib import Path
    digest = json.loads(Path("digest.json").read_text())
    html = render(digest)
    Path("latest.html").write_text(html, encoding="utf-8")
    print(f"Rendered {len(html):,} bytes -> latest.html")
