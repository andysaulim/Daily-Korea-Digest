"""Everything published around an episode's MP3: chapters, transcript, show
notes, and the player page the email's Listen bar opens.

podcast.py makes the audio and measures where each request's speech lands in
the finished file (see podcast._master). This module turns that timeline into:

    digest_YYYY-MM-DD.chapters.json   Podcasting 2.0 chapters (podcast:chapters)
    digest_YYYY-MM-DD.vtt             WebVTT transcript (podcast:transcript)
    ID3 CHAP frames in the MP3        the same chapters, for apps that read tags
    listen/YYYY-MM-DD.html            the player page for that issue
    listen/index.html                 the same page for the latest issue

Every file is per day, so none accumulates across runs; the one list that
does (recent episodes on the player page) is taken from podcast.json after
update_feed has read the published copy, and is simply left off when that
read was not trustworthy. Nothing here may stop an episode or an email:
produce() calls each step inside its own try, and a failure costs that file.
"""
from __future__ import annotations

import html as _html
import json
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

DEFAULT_WEB_BASE = "https://andysaulim.github.io/Daily-Korea-Digest"
LISTEN_DIR = "listen"

# Chapter titles for the segment cues (podcast.LEAD_CUES and podcast.CUE_*),
# which both the written and the assembled script open segments with. A lead
# story ("First, ...") is titled from the top story it tells instead. A lead
# not listed here — a section added later — is titled from its own opening
# words, so a new section degrades to a plain title, never an error. The
# older cues stay listed so a re-made old episode still gets its titles.
_LEAD_TITLES = (
    ("Now to Pyongyang", "Pyongyang"), ("The number of the day", "Number of the day"),
    ("The rest of the news", "The round-up"),
    ("In Seoul", "Seoul: government and Assembly"), ("On the economy", "Economy"),
    ("On Capitol Hill", "Capitol Hill"), ("Elsewhere in the region", "The region"),
    ("Beyond the region", "Korea and the World"), ("In the polls", "Polling"),
    ("In their own words", "In their own words"), ("Coming up", "Coming up"),
    ("A few more things", "Also today"), ("From the analysts", "Analysis"),
    ("From satellite imagery", "Satellite imagery"),
    ("Finally, the markets", "Markets"),
    ("That's the Korea Daily Brief", "Close"),
    # Cues of the assembled script before 19 October.
    ("Our top story", "Top stories"), ("Here's what else", "Overnight"),
    ("How is the public", "Polling"), ("What's coming up", "Coming up"),
    ("And from the analysts", "Analysis"),
)
_ORDINAL_CUE = re.compile(r"^(First|Second|Third|Fourth|Fifth),\s")


# ── Show notes ───────────────────────────────────────────────────────────────

def _plain(text: str) -> str:
    """A printed headline without markdown emphasis."""
    return re.sub(r"\s+", " ", re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", str(text or ""))).strip()


def show_notes(digest: dict, limit: int = 4) -> list[dict]:
    """The lead stories as the brief printed them: headline, source, link."""
    out = []
    for item in digest.get("top_stories") or []:
        if not isinstance(item, dict) or item.get("stand_in") or not item.get("headline"):
            continue
        url = str(item.get("url") or "").strip()
        out.append({"headline": _plain(item["headline"]),
                    "source": _plain(item.get("source") or ""),
                    "url": url if url.startswith(("http://", "https://")) else ""})
    return out[:limit]


# ── Chapters ─────────────────────────────────────────────────────────────────

def _short(headline: str, limit: int = 70) -> str:
    h = re.split(r"\s+[—–]\s+|;\s+", _plain(headline))[0].strip()
    if len(h) <= limit:
        return h
    return h[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _segment_title(text: str, n: int, total: int, digest: dict, source: str,
                   used: set) -> tuple[str, str]:
    """(title, link) for one segment of the script."""
    import podcast
    head = text.strip()
    numbered = _ORDINAL_CUE.match(head)
    if not numbered:
        for lead, title in _LEAD_TITLES:
            if head.startswith(lead):
                return title, ""
    if n == 0:
        return "Today's headlines", ""
    # A lead story: the top story whose headline the segment's opening shares
    # most of. Compared in spoken form, since the script says "North Korea"
    # where the headline prints "DPRK".
    opening = podcast._words(" ".join(head.split()[:90]))
    best, score = None, 0.0
    for i, item in enumerate(podcast._items(digest, "top_stories")):
        if i in used:
            continue
        hw = podcast._words(podcast.speakable(item.get("headline", "")))
        if hw:
            s = len(hw & opening) / len(hw)
            if s > score:
                best, score = (i, item), s
    if numbered and not (best and score >= 0.3):
        # A numbered lead whose words don't match a headline (the assembled
        # script tells the body alone): the next top story not yet titled.
        rest = [(i, it) for i, it in enumerate(podcast._items(digest, "top_stories")) if i not in used]
        best, score = (rest[0], 1.0) if rest else (None, 0.0)
        if not best:
            return f"Lead story: {numbered.group(1).lower()}", ""
    if best and score >= 0.3:
        used.add(best[0])
        url = str(best[1].get("url") or "")
        return _short(best[1].get("headline", "")), url if url.startswith("http") else ""
    first30 = " ".join(head.split()[:30]).lower()
    if "pyongyang" in first30 or "state media" in first30 or "kcna" in first30:
        return "Pyongyang", ""
    if n == total - 1:
        return ("Markets and close" if "market" in head.lower() else "Close"), ""
    if source == "written":
        return "The round-up", ""
    words = re.sub(r"^[^:]{0,40}:\s*", "", head).split()[:6]
    return (" ".join(words).rstrip(",.;:") + "…") if words else f"Part {n + 1}", ""


def build_chapters(chunks: list[dict], script: str, digest: dict, source: str,
                   duration: float) -> list[dict]:
    """Chapters from the measured timeline: one per script segment.

    The first chapter starts at zero, so it includes the opening sting; every
    other starts where its segment's first words do. Lead stories link to the
    article the brief cited. Titles that repeat get a part number.
    """
    import podcast
    segs = podcast.segments(script)
    starts: dict[int, float] = {}
    for c in chunks:
        starts.setdefault(int(c["segment"]), float(c["start"]))
    out, used, seen = [], set(), {}
    for n, text in enumerate(segs):
        if n not in starts:
            continue
        title, url = _segment_title(text, n, len(segs), digest, source, used)
        seen[title] = seen.get(title, 0) + 1
        if seen[title] > 1:
            title = f"{title} ({seen[title]})"
        ch = {"startTime": 0.0 if not out else round(starts[n], 2), "title": title}
        if url:
            ch["url"] = url
        out.append(ch)
    for i, ch in enumerate(out):
        ch["endTime"] = out[i + 1]["startTime"] if i + 1 < len(out) else round(float(duration), 2)
    return out


def chapters_json(chapters: list[dict]) -> str:
    """The Podcasting 2.0 JSON chapters format, version 1.2.0."""
    return json.dumps({"version": "1.2.0", "chapters": chapters}, ensure_ascii=False, indent=1)


def _ffmeta_escape(text: str) -> str:
    return re.sub(r"([=;#\\\n])", r"\\\1", str(text))


def embed_chapters(mp3: Path, chapters: list[dict], title: str) -> bool:
    """Write the chapters into the MP3 as ID3v2 CHAP/CTOC frames, with ffmpeg.

    A stream copy: the audio is not re-encoded. The tagged file replaces the
    original only if ffmpeg succeeded and the result is the same length, so a
    failure leaves the episode exactly as mastered.
    """
    import podcast
    ff = podcast._ffmpeg()
    if not ff or not chapters:
        return False
    lines = [";FFMETADATA1", f"title={_ffmeta_escape(title)}",
             "artist=CSIS Korea Chair", "album=Korea Daily Brief", "genre=Podcast"]
    for ch in chapters:
        lines += ["[CHAPTER]", "TIMEBASE=1/1000",
                  f"START={int(round(ch['startTime'] * 1000))}",
                  f"END={int(round(ch['endTime'] * 1000))}",
                  f"title={_ffmeta_escape(ch['title'])}"]
    with tempfile.TemporaryDirectory() as tmp:
        meta = Path(tmp) / "chapters.txt"
        meta.write_text("\n".join(lines) + "\n", encoding="utf-8")
        out = Path(tmp) / "tagged.mp3"
        r = subprocess.run([ff, "-loglevel", "error", "-y", "-i", str(mp3), "-i", str(meta),
                            "-map", "0:a", "-map_metadata", "1", "-map_chapters", "1",
                            "-c", "copy", "-id3v2_version", "3", str(out)],
                           capture_output=True, timeout=120)
        if r.returncode or not out.exists():
            print(f"  ⚠  ID3 chapters not written: {r.stderr.decode(errors='replace')[:200]}")
            return False
        before = podcast.mp3_seconds(mp3.read_bytes())
        after = podcast.mp3_seconds(out.read_bytes())
        if abs(before - after) > 0.5:
            print(f"  ⚠  ID3 chapters not written: length changed {before:.1f}s -> {after:.1f}s")
            return False
        mp3.write_bytes(out.read_bytes())
    return True


# ── Transcript ───────────────────────────────────────────────────────────────

def _ts(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def cues(chunks: list[dict], max_chars: int = 220) -> list[dict]:
    """Caption-sized cues: each request's span split by sentence.

    A request's start and end are measured; the sentences inside it are timed
    by their share of its characters, which is close for one steady voice and
    never strays outside the request it belongs to.
    """
    out = []
    for c in chunks:
        text = " ".join(str(c["text"]).split())
        sentences = [x for x in re.split(r"(?<=[.!?])\s+|(?<=[.!?][\"”’])\s+", text) if x]
        groups, cur = [], ""
        for snt in sentences:
            if cur and len(cur) + len(snt) + 1 > max_chars:
                groups.append(cur)
                cur = snt
            else:
                cur = f"{cur} {snt}".strip()
        if cur:
            groups.append(cur)
        total = sum(len(g) for g in groups) or 1
        t, span = float(c["start"]), float(c["end"]) - float(c["start"])
        for g in groups:
            d = span * len(g) / total
            out.append({"start": t, "end": t + d, "text": g, "segment": c["segment"]})
            t += d
    return out


def vtt(chunks: list[dict]) -> str:
    """WebVTT for the whole episode."""
    lines = ["WEBVTT", ""]
    for i, c in enumerate(cues(chunks), 1):
        text = c["text"].replace("-->", "to")
        lines += [str(i), f"{_ts(c['start'])} --> {_ts(c['end'])}", text, ""]
    return "\n".join(lines)


# ── The player page ──────────────────────────────────────────────────────────

def subscribe_links(feed_url: str) -> list[tuple[str, str]]:
    """(label, href) for one-tap subscribe.

    UNVERIFIED: these URL schemes are the ones each app has documented or been
    observed to register, but none has been tested against this feed on a
    device. Apple Podcasts: podcast:// in place of https://. Overcast: its
    x-callback-url add action. Pocket Casts: pktc://subscribe/ plus the feed
    without its scheme. Spotify is left out on purpose: it does not accept
    private RSS feeds. The feed carries itunes:block, so it is in no directory
    and subscribing by URL is the only way in; "Copy feed URL" always works.
    """
    bare = re.sub(r"^https?://", "", feed_url)
    return [("Apple Podcasts", f"podcast://{bare}"),
            ("Overcast", f"overcast://x-callback-url/add?url={quote(feed_url, safe='')}"),
            ("Pocket Casts", f"pktc://subscribe/{bare}")]


def _e(text) -> str:
    return _html.escape(str(text or ""), quote=True)


def _long_date(date_slug: str) -> str:
    d = datetime.strptime(date_slug, "%Y-%m-%d")
    return d.strftime("%A, %B ") + f"{d.day}, {d.year}"


_CSS = """
:root{--bg:#FFFFFF;--ink:#14181F;--muted:#5A6472;--navy:#072B52;--accent:#0047A0;
--line:#E3E6EA;--card:#F6F7F9;--chip:#EEF2F8;--active:#E8EEF8;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#0F1318;--ink:#E7EAEE;--muted:#9AA4B1;
--navy:#C9D8F0;--accent:#8DB0FF;--line:#262D37;--card:#161B22;--chip:#1C2430;--active:#1B2638}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:var(--accent)}
.flag{height:3px;background:#CD2E3A}.flag+.flag{background:#0047A0}
.wrap{max-width:720px;margin:0 auto;padding:0 16px}
header{padding:22px 0 16px;border-bottom:1px solid var(--line)}
.kicker{font-size:11px;font-weight:700;letter-spacing:1.6px;text-transform:uppercase;color:var(--muted)}
h1{margin:4px 0 2px;font-size:28px;line-height:1.15;letter-spacing:-.3px;color:var(--navy)}
.date{font-size:15px;color:var(--muted)}
.re{margin:10px 0 0;font-size:15px;line-height:1.5}
.card{margin:18px 0 0;padding:16px;border:1px solid var(--line);border-radius:10px;background:var(--card)}
.card-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:10px}
.card-head strong{font-size:17px;color:var(--navy)}
.card-head span{font-size:13px;color:var(--muted);white-space:nowrap}
audio{display:block;width:100%;height:44px}
.controls{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
button,.btn{font:inherit;font-size:14px;line-height:1;cursor:pointer;border-radius:8px;
border:1px solid var(--line);background:var(--bg);color:var(--ink);padding:9px 12px;text-decoration:none;
display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:38px}
button:hover,.btn:hover{border-color:var(--accent)}
button[aria-pressed=true]{background:var(--navy);border-color:var(--navy);color:var(--bg)}
.spacer{flex:1}
.rates{display:flex;gap:6px}
.rates button{padding:9px 10px}
.disclosure{margin:12px 0 0;font-size:13px;color:var(--muted)}
.brief{display:flex;margin-top:14px;padding:12px 14px;border-radius:8px;background:var(--navy);
color:var(--bg);text-decoration:none;font-weight:600;justify-content:space-between;align-items:center}
section{margin-top:30px}
h2{font-size:13px;font-weight:700;letter-spacing:1.4px;text-transform:uppercase;color:var(--muted);
margin:0 0 10px;padding-bottom:8px;border-bottom:2px solid var(--navy)}
ol.chapters{list-style:none;margin:0;padding:0}
ol.chapters li{border-bottom:1px solid var(--line)}
ol.chapters a{display:flex;gap:14px;padding:11px 8px;text-decoration:none;color:var(--ink);border-radius:6px}
ol.chapters a:hover{background:var(--card)}
ol.chapters li.on a{background:var(--active);box-shadow:inset 3px 0 0 var(--accent)}
.t{font-variant-numeric:tabular-nums;color:var(--muted);min-width:42px;font-size:14px;padding-top:1px}
.subs{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.subs .btn,.subs button{width:100%;font-weight:600}
.note{font-size:13px;color:var(--muted);margin:10px 0 0}
ul.notes{margin:0;padding:0;list-style:none}
ul.notes li{padding:10px 0;border-bottom:1px solid var(--line)}
ul.notes .src{display:block;font-size:13px;color:var(--muted);margin-top:2px}
.transcript{font-family:Georgia,"Times New Roman",serif;font-size:17px;line-height:1.65}
.transcript h3{font:700 15px/1.3 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
margin:24px 0 6px;color:var(--navy);display:flex;gap:10px;align-items:baseline}
.transcript h3 a{font-weight:400;font-size:13px;text-decoration:none;font-variant-numeric:tabular-nums}
.transcript p{margin:0 0 12px}
ul.recent{margin:0;padding:0;list-style:none}
ul.recent li{padding:8px 0;border-bottom:1px solid var(--line);font-size:15px}
footer{margin:36px 0 0;padding:18px 0 40px;border-top:1px solid var(--line);font-size:13px;color:var(--muted)}
@media (max-width:560px){h1{font-size:24px}.controls button{padding:9px 8px;font-size:13px}.rates{gap:4px}.subs{grid-template-columns:1fr 1fr}.transcript{font-size:16px}}
"""

_JS = """
(function(){
var a=document.getElementById('a');if(!a)return;
function seek(t){a.currentTime=t;var p=a.play();if(p&&p.catch)p.catch(function(){});}
document.querySelectorAll('[data-t]').forEach(function(el){
 el.addEventListener('click',function(e){e.preventDefault();seek(parseFloat(el.dataset.t)||0);});});
document.querySelectorAll('[data-skip]').forEach(function(el){
 el.addEventListener('click',function(){a.currentTime=Math.max(0,a.currentTime+parseFloat(el.dataset.skip));});});
var rates=document.querySelectorAll('[data-rate]');
rates.forEach(function(el){el.addEventListener('click',function(){
 a.playbackRate=parseFloat(el.dataset.rate);
 rates.forEach(function(r){r.setAttribute('aria-pressed',r===el?'true':'false');});});});
var rows=[].slice.call(document.querySelectorAll('ol.chapters li'));
a.addEventListener('timeupdate',function(){var t=a.currentTime,on=-1;
 rows.forEach(function(r,i){if(parseFloat(r.dataset.start)<=t+0.25)on=i;});
 rows.forEach(function(r,i){r.classList.toggle('on',i===on);});});
var m=location.hash.match(/t=(\\d+(?:\\.\\d+)?)/);
if(m){a.addEventListener('loadedmetadata',function(){a.currentTime=parseFloat(m[1]);},{once:true});}
var c=document.getElementById('copy');
if(c)c.addEventListener('click',function(){var u=c.dataset.feed;
 function done(){c.textContent='Copied';setTimeout(function(){c.textContent='Copy feed URL';},2000);}
 if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(u).then(done,function(){prompt('Feed URL',u);});}
 else{prompt('Feed URL',u);}});
})();
"""


def render_page(*, date_slug: str, digest: dict, web_base: str, minutes: int,
                chapters: list[dict] | None, chunks: list[dict] | None, script: str,
                notes: list[dict], episodes: list[dict] | None, is_index: bool = False) -> str:
    """The player page for one issue. Paths are relative to listen/."""
    import podcast
    base = (web_base or DEFAULT_WEB_BASE).rstrip("/")
    feed = f"{base}/podcast.xml"
    mp3 = f"digest_{date_slug}.mp3"
    long_date = _long_date(date_slug)
    re_line = _plain(digest.get("re_line") or "")
    page_url = f"{base}/{LISTEN_DIR}/{date_slug}.html"

    # Two sources: the measured URL first and the file itself second, so the
    # page still plays if the analytics prefix is ever unreachable.
    srcs = [podcast.measured(f"{base}/{mp3}"), f"../{mp3}"]
    sources = "".join(f'<source src="{_e(s)}" type="audio/mpeg">' for s in dict.fromkeys(srcs))

    rates = "".join(f'<button type="button" data-rate="{r}" aria-pressed="{"true" if r == "1" else "false"}">{r}×</button>'
                    for r in ("1", "1.25", "1.5", "2"))

    if chapters:
        ch_items = "".join(
            f'<li data-start="{c["startTime"]}"><a href="#t={c["startTime"]:g}" data-t="{c["startTime"]}">'
            f'<span class="t">{_clock(c["startTime"])}</span><span>{_e(c["title"])}</span></a></li>'
            for c in chapters)
        ch_html = f'<section aria-labelledby="h-ch"><h2 id="h-ch">Chapters</h2><ol class="chapters">{ch_items}</ol></section>'
    else:
        ch_html = ""

    subs = "".join(f'<a class="btn" href="{_e(h)}">{_e(lbl)}</a>' for lbl, h in subscribe_links(feed))
    subs += f'<button type="button" id="copy" data-feed="{_e(feed)}">Copy feed URL</button>'

    if notes:
        items = "".join(
            "<li>" + (f'<a href="{_e(n["url"])}">{_e(n["headline"])}</a>' if n.get("url") else _e(n["headline"]))
            + (f'<span class="src">{_e(n["source"])}</span>' if n.get("source") else "") + "</li>"
            for n in notes)
        notes_html = (f'<section aria-labelledby="h-notes"><h2 id="h-notes">Lead stories</h2>'
                      f'<ul class="notes">{items}</ul>'
                      f'<p class="note">Every item in the episode is from the printed brief, which links all its sources.</p></section>')
    else:
        notes_html = ""

    # Transcript: by segment, each headed by its chapter (time and title,
    # clickable) when the timeline is known; plain paragraphs otherwise.
    segs = podcast.segments(script)
    titles = {i: c for i, c in enumerate(chapters or [])}
    seg_start: dict[int, float] = {}
    for c in chunks or []:
        seg_start.setdefault(int(c["segment"]), float(c["start"]))
    ordered = sorted(seg_start) if seg_start else list(range(len(segs)))
    blocks = []
    for k, n in enumerate(ordered):
        if n >= len(segs):
            continue
        ch = titles.get(k) if chapters and len(chapters) == len(ordered) else None
        head = ""
        if ch:
            head = (f'<h3><a href="#t={ch["startTime"]:g}" data-t="{ch["startTime"]}">{_clock(ch["startTime"])}</a>'
                    f'<span>{_e(ch["title"])}</span></h3>')
        paras = []
        for p in segs[n].split("\n\n"):
            p = p.strip()
            if not p:
                continue
            paras.append(f"<p>{_e(p)}</p>")
        blocks.append(head + "".join(paras))
    transcript = (f'<section aria-labelledby="h-tr"><h2 id="h-tr">Transcript</h2>'
                  f'<div class="transcript">{"".join(blocks)}</div></section>') if blocks else ""

    recent = ""
    if episodes:
        rows = []
        for e in sorted(episodes, key=lambda x: x.get("date", ""), reverse=True)[:10]:
            d = e.get("date", "")
            if not d or d == date_slug:
                continue
            href = f"{d}.html" if e.get("page") else f"../{e.get('file', '')}"
            rows.append(f'<li><a href="{_e(href)}">{_e(_long_date(d))}</a></li>')
        if rows:
            recent = (f'<section aria-labelledby="h-rec"><h2 id="h-rec">Recent episodes</h2>'
                      f'<ul class="recent">{"".join(rows)}</ul></section>')

    mins = f"{minutes} min" if minutes else ""
    canonical = f'<link rel="canonical" href="{_e(page_url)}">' if is_index else ""
    title = f"Korea Daily Brief audio | {long_date}"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<meta name="color-scheme" content="light dark">
<title>{_e(title)}</title>
<meta name="description" content="{_e(podcast.DISCLOSURE + ' ' + re_line)}">
<meta property="og:title" content="{_e(title)}">
<meta property="og:audio" content="{_e(base + '/' + mp3)}">
<link rel="alternate" type="application/rss+xml" title="Korea Daily Brief" href="{_e(feed)}">
{canonical}
<style>{_CSS}</style>
</head>
<body>
<div class="flag"></div><div class="flag"></div>
<div class="wrap">
<header>
<div class="kicker">CSIS Korea Chair &middot; Audio edition</div>
<h1>Korea Daily Brief</h1>
<div class="date">{_e(long_date)}</div>
{f'<p class="re">{_e(re_line)}</p>' if re_line else ''}
</header>
<div class="card">
<div class="card-head"><strong>Listen{(' &middot; ' + mins) if mins else ''}</strong><span>AI-narrated</span></div>
<audio id="a" controls preload="metadata">{sources}Your browser cannot play this audio. <a href="../{_e(mp3)}">Download the MP3</a>.</audio>
<div class="controls">
<button type="button" data-skip="-15" aria-label="Back 15 seconds">&#8634; 15s</button>
<button type="button" data-skip="30" aria-label="Forward 30 seconds">30s &#8635;</button>
<span class="spacer"></span><span class="rates" role="group" aria-label="Playback speed">{rates}</span>
</div>
<p class="disclosure">{_e(podcast.DISCLOSURE)}</p>
</div>
<a class="brief" href="../digest_{_e(date_slug)}.html"><span>Read today&#8217;s brief, with every source</span><span aria-hidden="true">&rarr;</span></a>
{ch_html}
<section aria-labelledby="h-sub"><h2 id="h-sub">Subscribe</h2>
<div class="subs">{subs}</div>
<p class="note">A private feed: it is not listed in podcast directories. If a button does nothing on your device, copy the feed URL and add it in your app under &ldquo;Follow a show by URL&rdquo; or &ldquo;Add podcast by URL&rdquo;.</p>
</section>
{notes_html}
{transcript}
{recent}
<footer>
<p>{_e(podcast.DISCLOSURE)} The narration is written from the brief and checked against it; the printed brief is the authoritative text. For internal use only.</p>
<p><a href="../digest_{_e(date_slug)}.html">Today&#8217;s brief</a> &middot; <a href="../archive.html">Past issues</a> &middot; <a href="{_e(feed)}">Feed</a></p>
</footer>
</div>
<script>{_JS}</script>
</body>
</html>
"""


def write_pages(public: Path, **kw) -> str:
    """Write listen/DATE.html and listen/index.html. Returns the dated page's path."""
    out = public / LISTEN_DIR
    out.mkdir(parents=True, exist_ok=True)
    date_slug = kw["date_slug"]
    (out / f"{date_slug}.html").write_text(render_page(**kw), encoding="utf-8")
    # index.html carries the recent-episodes list, taken from the feed's
    # episode list. episodes is None when update_feed could not read the
    # published podcast.json; writing the index then would replace the
    # published page with one that has lost its history, which is the
    # archive.json defect again. The dated page has no history and is safe.
    # Without a web base nothing is published, so a local run still gets one.
    if kw.get("episodes") is not None or not kw.get("web_base"):
        (out / "index.html").write_text(render_page(**kw, is_index=True), encoding="utf-8")
    else:
        print("  ⚠  listen/index.html not rewritten — the published episode list was unreadable")
    return f"{LISTEN_DIR}/{date_slug}.html"


def listen_url(web_base: str, page: str, content: str = "listen-bar") -> str:
    """The player page as linked from the email, tagged for counting."""
    return (f"{web_base.rstrip('/')}/{page}?utm_source=email&utm_medium=email"
            f"&utm_campaign=korea-daily-brief&utm_content={content}")
