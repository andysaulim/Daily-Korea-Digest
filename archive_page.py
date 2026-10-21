"""The house archive page: Japan's layout, Korea's search.

One file, shared by every edition. The rows are baked into the HTML rather than
fetched, so the page still lists every issue if archive.json is unreachable,
and the search filters what is already in the DOM, so it answers instantly and
works offline. Korea's page fetched its data and would show nothing when that
failed; Japan's had no search. This has neither problem.

Field names differ across the editions (url/filename, headline_re/re_line,
top_stories_count/top_stories), so every read accepts either.

Headline search: the box also searches the headlines of the articles each
issue ran, from the corpus shards already published (corpus/index_YYYY-MM.json,
rows of date, title, source and `used`). They are fetched only once the reader
starts typing, newest month first, and only rows an issue used are kept.
Nothing is written for it: the page reads files the corpus step already
publishes under its own read-before-write rule, so there is no new index that
could be rebuilt without its history. If the shards cannot be fetched, the box
still filters the issue list.
"""
from __future__ import annotations

import json
from datetime import datetime
from html import escape


def _row(entry: dict, accent: str, prefix: str) -> str:
    d = str(entry.get("date") or "")
    try:
        label = datetime.strptime(d, "%Y-%m-%d").strftime("%A, %B %-d, %Y")
    except ValueError:
        label = d
    url = str(entry.get("url") or entry.get("filename") or f"{prefix}{d}.html")
    re_line = str(entry.get("headline_re") or entry.get("re_line") or "")
    wc = entry.get("word_count") or 0
    words = f"{wc:,}" if isinstance(wc, int) else str(wc)

    # Link the PDF unless the entry says there isn't one. The China edition
    # records pdf: false when the export failed, and linking it anyway hands
    # the reader a 404; the others do not record the field at all and always
    # produce one, so an absent field means present.
    pdf_link = ""
    if entry.get("pdf", True):
        pdf = url.rsplit(".", 1)[0] + ".pdf"
        pdf_link = (f'&emsp;<a href="{escape(pdf)}" '
                    f'style="color:{accent};text-decoration:none;">PDF</a>')

    # data-search carries what the box matches on, lowercased once here rather
    # than on every keystroke.
    hay = escape(f"{d} {label} {re_line}".lower(), quote=True)
    return (
        f'<tr class="issue" data-date="{escape(d, quote=True)}" data-url="{escape(url, quote=True)}" '
        f'data-search="{hay}">'
        f'<td style="padding:11px 8px;border-bottom:1px solid #EBEBEB;white-space:nowrap;'
        f'font-family:Arial,sans-serif;font-size:13px;font-weight:700;color:#14181F;">'
        f'<a href="{escape(url)}" style="color:#14181F;text-decoration:none;">{escape(label)}</a>'
        f'{pdf_link}</td>'
        f'<td style="padding:11px 8px;border-bottom:1px solid #EBEBEB;'
        f'font-family:Georgia,serif;font-size:13px;line-height:1.45;color:#444;">{escape(re_line)}</td>'
        f'<td style="padding:11px 8px;border-bottom:1px solid #EBEBEB;'
        f'font-family:Arial,sans-serif;font-size:11px;color:#767676;'
        f'text-align:right;white-space:nowrap;">{words} words</td>'
        f'</tr>')


# Headline search over the published corpus shards. Plain ES5; loaded on first
# use (focus or typing), so a reader who only browses the list fetches nothing.
# Rows are kept only when the article ran in an issue (`used`), the issue is
# listed on this page, and the title is English: the brief is English-only and
# the corpus also holds Korean-language headlines the brief translated.
_SEARCH_JS = r"""<script>
(function () {
  var CORPUS = %%CORPUS%%;
  var q = document.getElementById('q');
  var box = document.getElementById('hits'), list = document.getElementById('hit-list');
  var hitsN = document.getElementById('hits-n'), note = document.getElementById('hits-note');
  if (!q || !box || !window.fetch) return;
  var issues = {};
  [].forEach.call(document.querySelectorAll('tr.issue'), function (r) {
    issues[r.getAttribute('data-date')] = r.getAttribute('data-url');
  });
  var heads = [], seen = {}, pending = 0, failed = 0, shardCount = 0, started = false;
  var HANGUL = /[ㄱ-ㆎ가-힣]/;
  var MONTHS = ['January','February','March','April','May','June','July','August',
                'September','October','November','December'];

  function months() {
    var m = {};
    Object.keys(issues).forEach(function (d) { if (/^\d{4}-\d{2}/.test(d)) m[d.slice(0, 7)] = 1; });
    return Object.keys(m).sort().reverse().map(function (k) { return 'index_' + k + '.json'; });
  }
  function getJSON(url) {
    return fetch(url).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }
  function take(rows) {
    if (!rows || !rows.length) return;
    rows.forEach(function (a) {
      if (!a || !(a.used || a.used_in_digest) || !issues[a.date]) return;
      // Google News titles end " - Publisher"; the source is shown separately.
      var t = String(a.title || '').replace(/\s+-\s+[^-]{2,40}$/, '').trim();
      if (!t || HANGUL.test(t)) return;
      var k = a.date + '|' + t.toLowerCase();
      if (seen[k]) return;
      seen[k] = 1;
      var src = String(a.source || '').replace(/ Korea$/, '');
      if (HANGUL.test(src)) src = '';
      heads.push({ d: a.date, t: t, s: src, l: (t + ' ' + src).toLowerCase() });
    });
  }
  function load() {
    if (started) return;
    started = true;
    // The manifest lists recent days only, so its shards are joined with one
    // per month that has an issue; a month with no shard is a quiet 404.
    getJSON(CORPUS + 'manifest.json').then(function (m) {
      var s = {}, out = [];
      ((m && m.days) || []).concat(months().map(function (x) { return { shard: x }; })).forEach(function (d) {
        if (d && /^index_\d{4}-\d{2}\.json$/.test(d.shard || '') && !s[d.shard]) { s[d.shard] = 1; out.push(d.shard); }
      });
      return out.sort().reverse();
    }, months).then(function (shards) {
      pending = shardCount = shards.length;
      render();
      shards.forEach(function (sh) {
        getJSON(CORPUS + sh).then(take, function () { failed++; }).then(function () {
          pending--;
          heads.sort(function (a, b) { return a.d < b.d ? 1 : a.d > b.d ? -1 : 0; });
          render();
        });
      });
    });
  }
  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function mark(t, words) {
    var h = esc(t);
    words.forEach(function (w) {
      var re = new RegExp('(' + esc(w).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'ig');
      h = h.replace(re, '<mark>$1</mark>');
    });
    return h;
  }
  function label(d) {
    var p = d.split('-');
    return MONTHS[+p[1] - 1] + ' ' + (+p[2]) + ', ' + p[0];
  }
  function render() {
    var s = q.value.trim().toLowerCase();
    if (s.length < 3) { box.hidden = true; return; }
    load();
    var words = s.split(/\s+/), out = [], total = 0;
    for (var i = 0; i < heads.length; i++) {
      var h = heads[i], ok = true;
      for (var j = 0; j < words.length; j++) if (h.l.indexOf(words[j]) === -1) { ok = false; break; }
      if (!ok) continue;
      total++;
      if (out.length < 60) {
        out.push('<li><a href="' + esc(issues[h.d]) + '">' + mark(h.t, words) + '</a>' +
                 '<span class="hit-meta">' + label(h.d) + (h.s ? '&emsp;' + esc(h.s) : '') + '</span></li>');
      }
    }
    box.hidden = false;
    list.innerHTML = out.join('');
    hitsN.textContent = total ? '(' + total + ')' : '';
    note.textContent =
      pending ? 'Loading past headlines (' + (shardCount - pending) + ' of ' + shardCount + ' months)' :
      (failed && failed === shardCount) ? 'Headline search is unavailable right now; the issue list still filters.' :
      !total ? 'No headlines match.' :
      total > out.length ? 'Showing the newest ' + out.length + '.' : '';
  }
  q.addEventListener('focus', load);
  q.addEventListener('input', render);
  render();
})();
</script>"""


def build(entries: list, *, title: str, chair: str, accent: str,
          latest_href: str = "index.html", prefix: str = "",
          corpus_dir: str | None = "corpus/") -> str:
    """The archive page. corpus_dir is where the published corpus shards sit,
    relative to the page; None turns the headline search off."""
    entries = sorted([e for e in (entries or []) if isinstance(e, dict)],
                     key=lambda e: str(e.get("date") or ""), reverse=True)
    rows = "".join(_row(e, accent, prefix) for e in entries)
    search_js = (_SEARCH_JS.replace("%%CORPUS%%", json.dumps(corpus_dir).replace("</", "<\\/"))
                 if corpus_dir else "")
    if not rows:
        rows = ('<tr><td colspan="3" style="padding:16px;font-family:Arial,sans-serif;'
                'color:#767676;">No issues archived yet.</td></tr>')
    n = len(entries)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>{escape(title)}, Archive</title>
<style>
  body {{ margin:0; background:#F4F4F1; }}
  .wrap {{ max-width:1000px; margin:0 auto; background:#fff; }}
  .mast {{ background:#14181F; color:#fff; padding:22px 40px 18px; }}
  .chair {{ font-family:Arial,sans-serif; font-size:11px; font-weight:700;
           text-transform:uppercase; letter-spacing:2px; color:{accent}; margin-bottom:8px; }}
  .mast h1 {{ margin:0 0 6px 0; font-size:34px; font-weight:700; font-family:Georgia,serif; }}
  .meta {{ font-size:15px; color:rgba(255,255,255,0.85); font-family:Georgia,serif; }}
  .meta a {{ color:{accent}; text-decoration:none; }}
  .searchbar {{ padding:16px 40px 4px; }}
  .searchbar input {{ width:100%; box-sizing:border-box; padding:10px 12px;
      font-family:Georgia,serif; font-size:15px; color:#14181F;
      border:1px solid #D8D8D8; border-radius:3px; background:#fff; }}
  .searchbar input:focus {{ outline:2px solid {accent}; outline-offset:-1px; }}
  .count {{ padding:6px 40px 0; font-family:Arial,sans-serif; font-size:11px;
            color:#767676; text-transform:uppercase; letter-spacing:1px; }}
  table {{ width:100%; border-collapse:collapse; padding:8px 32px 32px; }}
  .hits {{ margin:10px 40px 4px; border:1px solid #E3E6EA; border-radius:3px; }}
  .hits-head {{ padding:9px 12px; font-family:Arial,sans-serif; font-size:11px; font-weight:700;
               text-transform:uppercase; letter-spacing:1px; color:#5F6670;
               border-bottom:1px solid #E3E6EA; }}
  .hits ol {{ list-style:none; margin:0; padding:0; max-height:420px; overflow-y:auto; }}
  .hits li {{ padding:9px 12px; border-bottom:1px solid #EBEBEB; }}
  .hits li a {{ font-family:Georgia,serif; font-size:14px; line-height:1.4; color:#14181F;
               text-decoration:none; }}
  .hits li a:hover {{ text-decoration:underline; }}
  .hits .hit-meta {{ display:block; margin-top:2px; font-family:Arial,sans-serif; font-size:11px;
                     color:#5F6670; }}
  .hits mark {{ background:#FFF1A8; color:inherit; }}
  .hits-note {{ padding:8px 12px; font-family:Arial,sans-serif; font-size:11px; color:#5F6670; }}
  .hits-note:empty {{ display:none; }}
  .foot {{ padding:18px 40px 28px; font-family:Arial,sans-serif; font-size:11px;
           color:#767676; text-align:center; }}
  @media (max-width:620px) {{
    .mast, .searchbar, .count, .foot {{ padding-left:18px; padding-right:18px; }}
    .hits {{ margin-left:18px; margin-right:18px; }}
    .mast h1 {{ font-size:26px; }}
    td {{ font-size:12px !important; }}
  }}
  @media (prefers-color-scheme: dark) {{
    body {{ background:#101215; }}
    .wrap {{ background:#15181C; }}
    td {{ border-color:#2A2F36 !important; }}
    td a {{ color:#E8E6E1 !important; }}
    td, .count, .foot {{ color:#B9BDC4 !important; }}
    .searchbar input {{ background:#1D2126; color:#E8E6E1; border-color:#2A2F36; }}
    .hits, .hits-head, .hits li {{ border-color:#2A2F36; }}
    .hits li a {{ color:#E8E6E1; }}
    .hits-head, .hits .hit-meta, .hits-note {{ color:#B9BDC4; }}
    .hits mark {{ background:#5A4E12; color:#FFFFFF; }}
  }}
</style></head>
<body>
<div class="wrap">
  <div class="mast">
    <div class="chair">{escape(chair)}</div>
    <h1>{escape(title)}</h1>
    <div class="meta">Archive&emsp;<span id="n">{n}</span> issues&emsp;
      <a href="{escape(latest_href)}">Latest issue</a></div>
  </div>
  <div class="searchbar" id="search">
    <input id="q" type="search" autocomplete="off"
           placeholder="Search by date or headline, e.g. Yongbyon or September 8" aria-label="Search the archive">
  </div>
  <div class="count" id="count" aria-live="polite">{n} issues</div>
  <div class="hits" id="hits" hidden>
    <div class="hits-head">Headlines in past issues <span id="hits-n"></span></div>
    <ol id="hit-list"></ol>
    <div class="hits-note" id="hits-note"></div>
  </div>
  <table><tbody id="rows">{rows}</tbody></table>
  <div class="foot">Generated automatically; every issue links its own sources.</div>
</div>
<script>
(function () {{
  var q = document.getElementById('q');
  var rows = [].slice.call(document.querySelectorAll('tr.issue'));
  var count = document.getElementById('count');
  if (!q) return;
  function apply() {{
    var s = q.value.trim().toLowerCase();
    var shown = 0;
    for (var i = 0; i < rows.length; i++) {{
      var hit = !s || rows[i].getAttribute('data-search').indexOf(s) !== -1;
      rows[i].style.display = hit ? '' : 'none';
      if (hit) shown++;
    }}
    count.textContent = s ? (shown + (shown === 1 ? ' issue matches' : ' issues match'))
                          : (shown + (shown === 1 ? ' issue' : ' issues'));
  }}
  q.addEventListener('input', apply);
  var pre = /[?&]q=([^&]*)/.exec(location.search);
  if (pre) {{ try {{ q.value = decodeURIComponent(pre[1].replace(/[+]/g, ' ')); }} catch (e) {{}} }}
  if (pre || location.hash === '#search') q.focus();
  apply();
}})();
</script>
{search_js}
</body></html>"""
