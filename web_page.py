"""The web edition: the page "Read online" opens, as the full reference.

The email has to stay lean, because Gmail clips a message at about 102KB and a
mail client runs no script. The published page has neither limit, so it is
built separately here, from the same digest, rather than being a copy of the
email:

  * It starts from the v2 render, with render.FULL_TEXT set so nothing the
    email shortens is shortened here.
  * Each section card becomes <details open>, its navy bar the <summary>, so
    a reader can fold what they have read.
  * A sticky menu links every section and marks the one being read (a few
    lines of script; the links work without it).
  * Previous and next issue, the Listen page, the archive search and Back to
    top. Prev/next come from archive.json: the copy run.py read, then the
    published copy fetched by the page itself, so an old issue gains its
    "Next issue" link once the next one exists. Nothing here writes
    archive.json; if it cannot be read, the links are simply left out.
  * A print stylesheet, a description and noindex (the listen pages already
    carry it; the brief is for internal use only).

Inline CSS and script only: no libraries, no web fonts. `build` never raises:
if anything fails it returns the email HTML it was given, which is what the
page used to be, and prints a warning annotation.
"""
from __future__ import annotations

import copy
import re
from datetime import datetime
from html import escape

_SANS = "system-ui,Segoe UI,Arial,sans-serif"
_NAVY = "#001F59"

# The card _v2_card builds: a white table whose first row holds the navy bar.
_CARD = re.compile(
    r'<table width="100%" cellpadding="0" cellspacing="0" border="0" class="v2-card" '
    r'style="background:#FFFFFF;"><tr><td style="padding:0;">'
    r'(<table[^>]*class="sec-bar"[^>]*><tr><td[^>]*>(.*?)</td></tr></table>)'
    r'</td></tr><tr><td([^>]*)>', re.S)
_TABLE_TAG = re.compile(r"<table\b|</table>")
_ANCHOR = re.compile(r'<a name="([\w-]+)" id="[\w-]+"></a>')

# Menu labels for sections the email's contents line does not name.
_EXTRA_SHORT = {"memo": "Glance", "markets": "Numbers"}


def _warn(title: str, message) -> None:
    msg = str(message).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    t = title.replace(":", "%3A").replace(",", "%2C")
    print(f"::warning title={t}::{msg}", flush=True)


def _render_v2(digest: dict) -> str:
    """The v2 render with full text, leaving render's module state as it was."""
    import render
    saved = (render.DESIGN, getattr(render, "FULL_TEXT", False))
    try:
        render.DESIGN = "v2"
        render.FULL_TEXT = True
        return render.render(copy.deepcopy(digest))
    finally:
        render.DESIGN, render.FULL_TEXT = saved


def _short_labels() -> dict:
    try:
        import render
        return dict(getattr(render, "_V2_TOC_SHORT", {}))
    except Exception:                                           # noqa: BLE001
        return {}


def _fold_sections(html: str) -> tuple[str, list]:
    """Turn every barred card into <details open>; return the page and its (anchor, label) list."""
    out, sections, last = [], [], 0
    pos = 0
    while True:
        m = _CARD.search(html, pos)
        if not m:
            break
        # The card ends at the </table> that balances its opening tag.
        depth, end = 1, None
        for t in _TABLE_TAG.finditer(html, m.end()):
            depth += 1 if t.group(0) == "<table" else -1
            if depth == 0:
                end = t.start()
                break
        if end is None:
            break
        inner = html[m.end():end]
        if not inner.endswith("</td></tr>"):
            pos = m.end()
            continue
        inner = inner[:-len("</td></tr>")]
        gap = html.rfind('<div class="v2-gap"', 0, m.start())
        anchors = _ANCHOR.findall(html[gap:m.start()]) if gap != -1 else []
        name = anchors[-1] if anchors else ""
        # The bar's section number is the email's; the menu names the section only.
        label = re.sub(r"^\d{2}\s*", "", re.sub(r"<[^>]+>", "", m.group(2)).strip())
        if name:
            sections.append((name, label))
        td_attrs = m.group(3)
        out.append(html[last:m.start()])
        out.append(
            f'<details open class="wsec" data-sec="{escape(name)}" style="background:#FFFFFF;">'
            f'<summary class="sec-bar wsum"><span>{m.group(2)}</span></summary>'
            f'<div{td_attrs}>{inner}</div></details>')
        last = pos = end + len("</table>")
    out.append(html[last:])
    return "".join(out), sections


def _date_label(slug: str, fmt: str = "%B %-d") -> str:
    try:
        return datetime.strptime(slug, "%Y-%m-%d").strftime(fmt)
    except ValueError:
        return slug


def _neighbours(entries, date_slug: str) -> tuple[str | None, str | None]:
    if entries is None:
        return None, None
    dates = sorted({str(e.get("date")) for e in entries
                    if isinstance(e, dict) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(e.get("date") or ""))})
    prev = max((d for d in dates if d < date_slug), default=None)
    nxt = min((d for d in dates if d > date_slug), default=None)
    return prev, nxt


def _issue_link(kind: str, d: str | None) -> str:
    word = "Previous issue" if kind == "prev" else "Next issue"
    attr = f'data-w{kind}=""'
    if d:
        return (f'<a {attr} href="digest_{escape(d)}.html">{word}, '
                f'<span class="wdate">{escape(_date_label(d))}</span></a>')
    return f'<a {attr} href="#" hidden>{word}, <span class="wdate"></span></a>'


def _nav(digest: dict, date_slug: str, prev: str | None, nxt: str | None, bottom: bool) -> str:
    links = [_issue_link("prev", prev), _issue_link("next", nxt)]
    if digest.get("listen_url"):
        links.append(f'<a href="listen/{escape(date_slug)}.html">Listen</a>')
    elif digest.get("audio_url"):
        links.append(f'<a href="{escape(str(digest["audio_url"]))}">Listen</a>')
    links.append('<a href="archive.html#search">Search past issues</a>')
    if bottom:
        links.append('<a href="#top">Back to top</a>')
    return (f'<div class="v2-gap wnav no-print" style="padding:0 16px 12px;">'
            f'<div class="wnav-in">{"".join(links)}</div></div>')


def _menu(sections: list) -> str:
    short = _short_labels()
    links = "".join(
        f'<a href="#{escape(n)}" data-sec="{escape(n)}">'
        f'{escape(short.get(n) or _EXTRA_SHORT.get(n) or label)}</a>'
        for n, label in sections)
    return ('<nav class="wmenu no-print" id="wmenu" aria-label="Sections"><div class="wmenu-in">'
            '<a class="wmenu-brand" href="#top">Korea Daily Brief</a>'
            f'<div class="wmenu-row">{links}</div></div></nav>')


_CSS = """
<style>
html { scroll-padding-top:60px; }
body { background:#E6E9EE; }
.wmenu { position:sticky; top:0; z-index:20; background:#FFFFFF; border-bottom:1px solid #CBD2DC;
  font-family:%(sans)s; }
.wmenu-in { max-width:1080px; margin:0 auto; display:flex; align-items:center; gap:14px; padding:0 16px; }
.wmenu-brand { flex:none; font-size:13px; font-weight:700; color:%(navy)s; text-decoration:none;
  white-space:nowrap; padding:10px 0; }
.wmenu-row { position:relative; flex:1; min-width:0; display:flex; flex-wrap:wrap; gap:2px; padding:6px 0; }
.wmenu-row a { display:inline-block; padding:5px 8px; font-size:13px; font-weight:700; line-height:1.3;
  color:%(navy)s; text-decoration:none; border-radius:3px; white-space:nowrap; }
.wmenu-row a:hover { text-decoration:underline; }
.wmenu-row a.on { background:%(navy)s; color:#FFFFFF; text-decoration:none; }
.wmenu a:focus-visible, .wnav-in a:focus-visible { outline:2px solid #007DAD; outline-offset:1px; }
details.wsec > summary { list-style:none; cursor:pointer; display:flex; align-items:center;
  justify-content:space-between; gap:12px; padding:9px 20px; background:%(navy)s; color:#FFFFFF;
  font-family:%(sans)s; font-size:13px; font-weight:700; letter-spacing:1px; text-transform:uppercase;
  line-height:1.35; }
details.wsec > summary::-webkit-details-marker { display:none; }
details.wsec > summary::after { content:"Hide"; flex:none; font-size:12px; font-weight:700; color:#DCE4EC;
  letter-spacing:0; text-transform:none; }
details.wsec:not([open]) > summary::after { content:"Show"; }
details.wsec > summary:focus-visible { outline:2px solid #5CBDE6; outline-offset:-2px; }
.wrapper .v2-toc { display:none !important; }
.wnav-in { display:flex; flex-wrap:wrap; gap:6px 18px; background:#FFFFFF; padding:10px 20px;
  font-family:%(sans)s; font-size:13px; line-height:1.4; }
.wnav-in a { color:%(navy)s; font-weight:700; text-decoration:underline;
  text-decoration-color:#B8C4D6; text-underline-offset:3px; }
.wnav-in a[hidden] { display:none; }
@media (max-width:760px) {
  html { scroll-padding-top:52px; }
  .wmenu-in { padding:0; gap:0; }
  .wmenu-brand { display:none; }
  .wmenu-row { flex-wrap:nowrap; overflow-x:auto; -webkit-overflow-scrolling:touch;
    scrollbar-width:none; padding:6px 8px; }
  .wmenu-row::-webkit-scrollbar { display:none; }
}
@media (max-width:620px) {
  details.wsec > summary { padding:9px 14px; }
  .wnav-in { padding:10px 14px; }
}
@media (prefers-color-scheme: dark) {
  body { background:#121212 !important; }
  .wmenu { background:#1C1F23; border-color:#3A4048; }
  .wmenu-brand, .wmenu-row a { color:#8FB6E8; }
  .wmenu-row a.on { background:#8FB6E8; color:#111418; }
  details.wsec > summary { background:%(navy)s !important; }
  .wnav-in { background:#262A30; }
  .wnav-in a { color:#8FB6E8; text-decoration-color:#4A5A72; }
}
@media print {
  .wmenu, .wnav { display:none !important; }
  details.wsec > summary { cursor:auto; }
  details.wsec > summary::after { content:none; }
  html { scroll-padding-top:0; }
}
</style>
""" % {"sans": _SANS, "navy": _NAVY}

# ES5, so an old phone browser runs it. Everything it does is an enhancement:
# without it the menu links, the folding and the baked prev/next all work.
_JS = """
<script>
(function () {
  var DATE = %(date)s;
  var menu = document.getElementById('wmenu');
  var links = menu ? [].slice.call(menu.querySelectorAll('a[data-sec]')) : [];
  var targets = links.map(function (a) { return document.getElementById(a.getAttribute('data-sec')); });
  var row = menu ? menu.querySelector('.wmenu-row') : null;
  var cur = null, ticking = false;
  function section(t) {
    var n = t && t.nextElementSibling;
    while (n && n.tagName === 'A') n = n.nextElementSibling;
    return n && n.tagName === 'DETAILS' ? n : null;
  }
  function update() {
    ticking = false;
    if (!menu) return;
    var off = menu.offsetHeight + 16, idx = -1;
    document.documentElement.style.scrollPaddingTop = (menu.offsetHeight + 8) + 'px';
    for (var i = 0; i < targets.length; i++) {
      if (targets[i] && targets[i].getBoundingClientRect().top - off <= 0) idx = i;
    }
    var a = idx >= 0 ? links[idx] : null;
    if (a === cur) return;
    if (cur) { cur.className = ''; cur.removeAttribute('aria-current'); }
    cur = a;
    if (!a && row) row.scrollLeft = 0;
    if (a) {
      a.className = 'on';
      a.setAttribute('aria-current', 'location');
      if (row && row.scrollWidth > row.clientWidth) {
        row.scrollLeft = a.offsetLeft - (row.clientWidth - a.offsetWidth) / 2;
      }
    }
  }
  window.addEventListener('scroll', function () {
    if (!ticking) { ticking = true; (window.requestAnimationFrame || setTimeout)(update); }
  }, { passive: true });
  window.addEventListener('resize', update);
  links.forEach(function (a, i) {
    a.addEventListener('click', function () { var d = section(targets[i]); if (d) d.open = true; });
  });
  update();

  var folded = [];
  window.addEventListener('beforeprint', function () {
    folded = [].slice.call(document.querySelectorAll('details.wsec:not([open])'));
    folded.forEach(function (d) { d.open = true; });
  });
  window.addEventListener('afterprint', function () {
    folded.forEach(function (d) { d.open = false; });
    folded = [];
  });

  function label(d) {
    var p = d.split('-');
    var m = ['January','February','March','April','May','June','July','August',
             'September','October','November','December'][+p[1] - 1];
    return m + ' ' + (+p[2]);
  }
  function set(kind, d) {
    [].forEach.call(document.querySelectorAll('[data-w' + kind + ']'), function (a) {
      if (d) {
        a.href = 'digest_' + d + '.html';
        a.querySelector('.wdate').textContent = label(d);
        a.hidden = false;
      } else {
        a.hidden = true;
      }
    });
  }
  if (!window.fetch || !DATE) return;
  fetch('archive.json', { cache: 'no-cache' }).then(function (r) {
    return r.ok ? r.json() : null;
  }).then(function (list) {
    if (!list || !list.length) return;
    var seen = {}, dates = [];
    list.forEach(function (e) {
      var d = e && e.date;
      if (d && /^\\d{4}-\\d{2}-\\d{2}$/.test(d) && !seen[d]) { seen[d] = 1; dates.push(d); }
    });
    dates.sort();
    var prev = null, next = null;
    for (var i = 0; i < dates.length; i++) {
      if (dates[i] < DATE) prev = dates[i];
      else if (dates[i] > DATE && !next) next = dates[i];
    }
    set('prev', prev);
    set('next', next);
  })['catch'](function () {});
})();
</script>
"""


def _description(digest: dict) -> str:
    text = str(digest.get("re_line") or "")
    if not text:
        memo = digest.get("morning_memo") or []
        first = memo[0] if memo else ""
        text = first.get("text", "") if isinstance(first, dict) else str(first or "")
    text = re.sub(r"\s*[·•|]\s*", "; ", text)
    text = re.sub(r"\s*[—–]\s*", ", ", text)
    text = re.sub(r"\*+", "", text).strip()
    return ("Korea Daily Brief from the CSIS Korea Chair. " + text)[:300].rstrip()


def _page(digest: dict, date_slug: str, archive_entries) -> str:
    import json
    html = _render_v2(digest)
    html, sections = _fold_sections(html)
    if not sections:
        raise ValueError("no section cards found in the v2 render")

    # The email's own "Read online" points at this page; here it would be a self-link.
    html = re.sub(r'<a href="[^"#]*digest_' + re.escape(date_slug) + r'\.html"[^>]*>Read online</a>(?:&emsp;\s?)?',
                  "", html)

    prev, nxt = _neighbours(archive_entries, date_slug)
    first = html.find("<details")
    gap = html.rfind('<div class="v2-gap"', 0, first)
    if gap != -1:
        html = html[:gap] + _nav(digest, date_slug, prev, nxt, bottom=False) + html[gap:]
    foot = html.find('<div class="v2-foot"')
    nav_bottom = _nav(digest, date_slug, prev, nxt, bottom=True)
    if foot != -1:
        html = html[:foot] + nav_bottom + html[foot:]
    else:
        html = html.replace("</body>", nav_bottom + "</body>", 1)

    body = re.search(r"<body\b[^>]*>", html)
    if not body:
        raise ValueError("no <body> in the v2 render")
    html = html[:body.end()] + _menu(sections) + html[body.end():]

    head = (f'<meta name="description" content="{escape(_description(digest), quote=True)}">\n'
            '<meta name="robots" content="noindex">\n' + _CSS)
    html = html.replace("</head>", head + "</head>", 1)
    html = html.replace("</body>", _JS % {"date": json.dumps(date_slug)} + "</body>", 1)
    return html


def build(digest: dict, email_html: str, date_slug: str, *, archive_entries=None) -> str:
    """The published page for digest_{date_slug}.html; the email HTML if anything fails.

    archive_entries is the manifest run.py read, or None when it could not be
    read (prev/next are then left to the page's own fetch, or omitted).
    """
    try:
        return _page(digest, date_slug, archive_entries)
    except Exception as e:                                      # noqa: BLE001
        _warn("Web page fell back to the email",
              f"digest_{date_slug}.html is the email HTML today: {type(e).__name__}: {e}")
        return email_html


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "digest.json")
    d = json.loads(src.read_text(encoding="utf-8"))
    slug = d.get("date_slug") or datetime.now().strftime("%Y-%m-%d")
    out = Path(sys.argv[2] if len(sys.argv) > 2 else f"web_{slug}.html")
    out.write_text(build(d, "", slug), encoding="utf-8")
    print(f"Wrote {out}")
