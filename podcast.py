"""The Korea Daily Brief, read aloud.

Turns a day's digest into a spoken script and, when a voice provider is
configured, into an MP3 published beside the issue with a podcast feed.

The script is assembled from the digest itself. No second model pass rewrites
it, and that is a deliberate constraint rather than a shortcut: every sentence
a listener hears is a sentence the brief printed, reordered and cleaned up for
the ear. The audio therefore cannot assert anything the text did not, which is
what SOURCE-OR-SKIP requires and what a "rewrite it as a podcast" prompt would
quietly give up.

Nothing here can stop a send. Every entry point returns None or an empty
result on failure, and run.py treats the audio as a convenience: a missing
episode costs one day of listening, never the brief.

Configuration (all optional; with none set, the script is built and no audio
is made):
    OPENAI_API_KEY   enables synthesis
    TTS_MODEL        default gpt-4o-mini-tts
    TTS_VOICE        default onyx
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape as _xml

SPOKEN_WPM = 155            # measured pace of the default voice, for estimates
CHUNK_CHARS = 3500          # under every supported model's per-request limit
FEED_EPISODES = 30          # what the feed advertises; the workflow prunes the rest
DEFAULT_MODEL = "gpt-4o-mini-tts"
DEFAULT_VOICE = "onyx"
LAST_ERROR = ""              # why the most recent synthesis produced nothing
DELIVERY = ("Calm, measured, authoritative news-briefing delivery. Even pace, "
            "clear diction, no dramatisation. Pause briefly between items.")

# ── Making text speakable ────────────────────────────────────────────────────

_HANGUL = re.compile(r"[ᄀ-ᇿ㄰-㆏가-힣]+")
_URL = re.compile(r"https?://\S+")
_MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s?(tn|T|bn|B|mn|M|K|k)\b")
_UNITS = {"tn": "trillion", "t": "trillion", "bn": "billion", "b": "billion",
          "mn": "million", "m": "million", "k": "thousand"}
# ROK / DPRK become the adjective form only before a noun known to follow them
# in this brief ("ROK soldiers", "DPRK territory"). Everything else gets the
# noun. The first version guessed the other way — adjective unless the next
# word was a known verb — and headlines are full of verbs no list anticipates:
# "DPRK rejects ROK mine investigation" came out as "North Korean rejects".
# Wrong in this direction is ungrammatical; wrong in the other is merely terse.
_ADJ_BEFORE = {
    "soldiers", "troops", "forces", "military", "army", "navy", "air",
    "territory", "waters", "border", "side", "statement", "statements",
    "officials", "official", "government", "authorities", "leader",
    "leadership", "delegation", "defense", "defence", "embassy", "envoy",
    "nationals", "citizens", "people", "regime", "media", "missile",
    "missiles", "nuclear", "economy", "president", "prime", "pm", "foreign",
    "unification", "intelligence", "coast", "state", "special", "joint",
    "national", "constitutional", "supreme", "ministry", "ministries",
    "counterpart", "counterparts", "workers", "companies", "firms", "exports",
    "imports", "warships", "drones", "hackers", "spy", "agents", "defector",
    "defectors", "fishing", "vessel", "vessels", "ship", "ships", "warplanes",
}


def _country(text: str, abbr: str, noun: str, adjective: str) -> str:
    def repl(m: re.Match) -> str:
        nxt = (m.group(1) or "").strip().lower()
        return (adjective if nxt in _ADJ_BEFORE else noun) + (m.group(1) or "")
    return re.sub(rf"\b{abbr}\b(\s+\w+|(?=[^\w]|$))", repl, text)


_NOT_A_NOUN = {"in", "to", "of", "for", "and", "or", "a", "an", "the", "on",
               "over", "by", "from", "with", "per", "at", "as", "this", "last",
               "next", "is", "was", "will", "would"}


def _money(m: re.Match) -> str:
    """$22.3B -> "22.3 billion dollars", or "dollar" when it modifies a noun."""
    amount, unit = m.group(1), _UNITS[m.group(2).lower()]
    nxt = re.match(r"\s+([A-Za-z]+)", m.string[m.end():])
    as_adjective = bool(nxt) and nxt.group(1).lower() not in _NOT_A_NOUN
    return f"{amount} {unit} dollar{'' if as_adjective else 's'}"


def speakable(text: str) -> str:
    """Rewrite a printed sentence so a speech engine says it the way a reader means it.

    Only presentation changes — never wording or facts. Markdown emphasis goes,
    because the engine would read the asterisks; Hangul goes, because an English
    voice mangles it and every Korean term in the brief is already given in
    English beside it; "US" becomes "U.S." because engines otherwise say "us";
    "$22.3B" becomes "22.3 billion dollars"; ROK and DPRK are expanded, as noun
    or adjective by what follows them.
    """
    if not text:
        return ""
    t = _html.unescape(str(text))
    t = _URL.sub("", t)
    t = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", t)
    t = _HANGUL.sub("", t)
    t = re.sub(r"\(\s*[,;/·]*\s*\)", "", t)          # parentheses Hangul left empty
    t = re.sub(r"\s*·\s*", ", ", t)
    t = _MONEY.sub(_money, t)
    t = re.sub(r"\bUS\b", "U.S.", t)
    t = _country(t, "DPRK", "North Korea", "North Korean")
    t = _country(t, "ROK", "South Korea", "South Korean")
    # "the DPRK said" is English; "the North Korea said" is not. Drop the
    # article before the noun form only — "the North Korean side" keeps it.
    t = re.sub(r"\b[Tt]he ((?:North|South) Korea)\b(?!n)", r"\1", t)
    t = re.sub(r"\bBOK\b", "Bank of Korea", t)
    t = re.sub(r"\bFMs\b", "foreign ministers", t)
    t = re.sub(r"\bFM\b", "Foreign Minister", t)
    t = re.sub(r"\bPM\b", "Prime Minister", t)
    t = re.sub(r"(\d)\s*[–-]\s*(\d)", r"\1 to \2", t)          # "Oct 3–5"
    t = re.sub(r"\s+/\s+", " and ", t)                            # "NK News / NK Pro"
    t = re.sub(r"\bvs\.?\b", "versus", t)
    t = re.sub(r"\s+([,.;:])", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    if t and t[-1] not in ".?!\"'”’":
        t += "."
    return t


# ── The script ───────────────────────────────────────────────────────────────

def _items(digest: dict, key: str) -> list[dict]:
    return [i for i in (digest.get(key) or []) if isinstance(i, dict) and not i.get("stand_in")]


def _spoken_date(digest: dict) -> str:
    raw = str(digest.get("digest_date") or "")
    for fmt in ("%Y-%m-%d", "%A, %B %d, %Y", "%B %d, %Y"):
        try:
            d = datetime.strptime(raw[:len(datetime.now().strftime(fmt)) + 12].strip(), fmt)
            return d.strftime("%A, %B ") + str(d.day)
        except ValueError:
            continue
    return raw


_STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "over",
         "after", "amid", "will", "would", "its", "their", "about", "says", "said"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 3 and w not in _STOP}


def _story(item: dict, body_key: str = "body") -> str:
    """One item as spoken: the body alone when it already tells the headline.

    In print a headline then a body is how a page is scanned. Read aloud it is
    the same story twice in a row, because the body's first sentence usually
    restates the headline in full. Measured, not assumed: when most of the
    headline's content words recur in the body's opening sentence, the
    headline is dropped. Otherwise — short wire items whose body is a fragment
    that leans on its headline — both are kept.
    """
    head = speakable(item.get("headline", ""))
    body = speakable(item.get(body_key) or item.get("body_text") or item.get("body") or "")
    if not body:
        return head
    if not head:
        return body
    # The opening forty words, not the first "sentence": abbreviations such as
    # "Sept. 21" end a sentence for a splitter and not for a reader, and cut
    # the comparison short enough that every headline looked new.
    first = " ".join(body.split()[:40])
    hw = _words(head)
    if hw and len(hw & _words(first)) / len(hw) >= 0.4:
        return body
    return f"{head} {body}"


def build_script(digest: dict) -> str:
    """The day's brief as a spoken script: paragraphs separated by blank lines.

    Follows the printed brief's order and says only what it says. Leaves out
    what does not survive being read aloud — tariff tables, the ledger, link
    lists, sparklines. The connective phrases ("Our top story", "Looking
    ahead") are the only words added, and none of them carries a fact.

    The opening summary is read only when the top stories will not repeat it:
    the morning memo is usually those same stories in a sentence each, and in
    audio, unlike print, a listener cannot skip the second telling.
    """
    when = _spoken_date(digest)
    out: list[str] = [f"This is the Korea Daily Brief from the CSIS Korea Chair. "
                      f"It's {when}."]

    # The RE line is the brief's own one-line rundown, which is exactly what a
    # spoken bulletin opens with. The morning memo is not used: it is the top
    # stories again, a sentence each, and every item in it is told in full
    # further down — in audio a listener cannot skip the second telling.
    top = _items(digest, "top_stories")
    parts = [speakable(p).rstrip(".") for p in str(digest.get("re_line") or "").split("·")]
    parts = [p for p in parts if p]
    if len(parts) > 1:
        out.append("In today's brief: " + "; ".join(parts[:-1]) + "; and " + parts[-1] + ".")
    elif parts:
        out.append(f"In today's brief: {parts[0]}.")

    leads = ["Our top story:", "Also making news:", "And:"]
    for n, item in enumerate(top):
        lead = leads[0] if n == 0 else ("And finally:" if n == len(top) - 1 else leads[1])
        out.append(f"{lead} {_story(item)}")

    overnight = _items(digest, "overnight_items")
    if overnight:
        first, *rest = [_story(i, "body_text") for i in overnight]
        out.append(f"Here's what else happened overnight. {first}")
        out.extend(rest)

    kcna = digest.get("kcna_delta") or {}
    if isinstance(kcna, dict) and kcna.get("bottom_line"):
        k = ["Turning to Pyongyang.", speakable(kcna["bottom_line"])]
        days = kcna.get("days_since_last_appearance")
        if isinstance(days, int) and days > 0 and not kcna.get("kim_appearance_today"):
            k.append(f"Kim Jong Un was last seen in public {days} "
                     f"day{'s' if days != 1 else ''} ago.")
        out.append(" ".join(k))

    trade = digest.get("us_korea_deals") or {}
    if isinstance(trade, dict):
        t = []
        if trade.get("state_of_play"):
            t.append(speakable(trade["state_of_play"]))
        pkg = trade.get("investment_package") or {}
        deals = [d for d in (pkg.get("known_deals") or []) if isinstance(d, dict) and d.get("company")]
        if deals:
            names = "; ".join(
                speakable(f'{d["company"]}, {d.get("value") or "value not reported"}').rstrip(".")
                for d in deals)
            t.append(f"Selected so far under the 350 billion dollar investment pledge: {names}.")
        if pkg.get("latest_update"):
            t.append(speakable(pkg["latest_update"]))
        if t:
            out.append("On U.S.–Korea trade. " + " ".join(t))

    biz = _items(digest, "business_economy")
    if biz:
        first, *rest = [_story(i, "body_text") for i in biz]
        out.append(f"In business news. {first}")
        out.extend(rest)

    region = _items(digest, "northeast_asia")
    if region:
        first, *rest = [_story(i, "body_text") for i in region]
        out.append(f"Around the region. {first}")
        out.extend(rest)

    # usd_krw is dollars-to-won, so a fall means the won strengthened. Say
    # what the number is — "the dollar is at 1,338 won" — rather than "the won
    # is at 1,338, down", which reverses the direction for a listener.
    mk = digest.get("market_indicators") or {}
    spoken_mk = []
    for key, fmt in (("kospi", "The KOSPI is at {v}"),
                     ("usd_krw", "The dollar is at {v} won"),
                     ("brent", "Brent crude is at {v} dollars a barrel"),
                     ("bok_rate", "The Bank of Korea's base rate is {v}")):
        v = mk.get(key)
        if not isinstance(v, dict) or not v.get("value"):
            continue
        phrase = fmt.format(v=str(v["value"]).replace("%", " percent"))
        chg = v.get("change_pct")
        if isinstance(chg, (int, float)) and chg:
            phrase += f", {'up' if chg > 0 else 'down'} {abs(chg):g} percent"
        spoken_mk.append(phrase + ".")
    if spoken_mk:
        out.append("In the markets. " + " ".join(spoken_mk))

    _y = re.search(r"\b(20\d{2})\b", str(digest.get("digest_date") or ""))
    year = _y.group(1) if _y else ""          # digest_date is not always ISO
    cal = [c for c in (digest.get("calendar_watch") or []) if isinstance(c, dict)]
    ahead = []
    for c in cal:
        date = str(c.get("date") or "").strip()
        if year:
            date = re.sub(rf",?\s*{year}\b", "", date).strip()
        event = speakable(c.get("event") or c.get("headline") or "")
        if event:
            ahead.append((f"{date}: " if date else "") + event)
    if ahead:
        out.append("Looking ahead. " + " ".join(ahead))

    out.append(f"That's the Korea Daily Brief for {when}. The full text, with a "
               f"link to every source, is in today's email.")
    return "\n\n".join(p.strip() for p in out if p and p.strip())


def estimate_minutes(script: str) -> float:
    return len(script.split()) / SPOKEN_WPM


# ── Synthesis ────────────────────────────────────────────────────────────────

def _chunks(script: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Pack paragraphs into requests under the provider's input limit.

    Breaks on paragraph boundaries first, then sentence boundaries for a
    paragraph too long alone, so no request ends mid-sentence — a cut there is
    audible as an unnatural pause and a reset in intonation.
    """
    out, cur = [], ""
    for para in script.split("\n\n"):
        pieces = [para] if len(para) <= limit else re.split(r"(?<=[.!?])\s+", para)
        for piece in pieces:
            if len(cur) + len(piece) + 2 > limit and cur:
                out.append(cur)
                cur = piece
            else:
                cur = f"{cur}\n\n{piece}" if cur else piece
    if cur:
        out.append(cur)
    return out


def _openai_tts(text: str, key: str, model: str, voice: str) -> bytes:
    import requests
    body = {"model": model, "voice": voice, "input": text, "response_format": "mp3"}
    if model.startswith("gpt-4o"):
        body["instructions"] = DELIVERY        # tts-1 does not take instructions
    r = requests.post("https://api.openai.com/v1/audio/speech",
                      headers={"Authorization": f"Bearer {key}"},
                      json=body, timeout=180)
    if r.status_code >= 400:
        # raise_for_status() gives "429 Client Error: Too Many Requests" and no
        # more; the body says which 429 — rate limit or an account with no
        # credit — and that is the difference between waiting and paying.
        try:
            detail = (r.json().get("error") or {}).get("message", "")
        except ValueError:
            detail = r.text[:300]
        raise RuntimeError(f"OpenAI returned {r.status_code}: {detail}".strip())
    return r.content


def _join_mp3(parts: list[bytes], out_path: Path) -> None:
    """Concatenate chunk MP3s; re-encode to 48 kbps mono when ffmpeg is present.

    Raw concatenation plays in every common player, because MP3 is a stream of
    independent frames. ffmpeg, when available (it is on GitHub's Ubuntu
    runners), produces a clean single file and brings a 15-minute episode down
    to about 5 MB — speech needs nothing more, and it is the difference between
    a site that fits in GitHub Pages' 1 GB and one that does not.
    """
    if shutil.which("ffmpeg"):
        with tempfile.TemporaryDirectory() as tmp:
            listing = Path(tmp) / "parts.txt"
            names = []
            for i, part in enumerate(parts):
                p = Path(tmp) / f"part{i:03d}.mp3"
                p.write_bytes(part)
                names.append(f"file '{p}'")
            listing.write_text("\n".join(names))
            done = subprocess.run(
                ["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                 "-i", str(listing), "-ac", "1", "-b:a", "48k", str(out_path)],
                capture_output=True, text=True)
            if done.returncode == 0 and out_path.exists() and out_path.stat().st_size:
                return
    out_path.write_bytes(b"".join(parts))


def _duration_seconds(path: Path, script: str) -> int:
    if shutil.which("ffprobe"):
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1", str(path)],
                           capture_output=True, text=True)
        try:
            return int(float(r.stdout.strip()))
        except ValueError:
            pass
    return int(estimate_minutes(script) * 60)


def synthesize(script: str, out_path: Path) -> dict | None:
    """Render the script to MP3. Returns a small record, or None if no audio was made."""
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key or not script.strip():
        return None
    model = (os.environ.get("TTS_MODEL") or "").strip() or DEFAULT_MODEL
    voice = (os.environ.get("TTS_VOICE") or "").strip() or DEFAULT_VOICE
    try:
        parts = [_openai_tts(c, key, model, voice) for c in _chunks(script)]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _join_mp3(parts, out_path)
    except Exception as e:                                      # noqa: BLE001
        global LAST_ERROR
        LAST_ERROR = str(e)
        # An annotation, not only a log line: GitHub serves job logs from a
        # separate host, while annotations are readable through the API, so
        # the reason a run produced no audio can be read back without the log.
        print(f"::warning title=Audio skipped::{e}")
        print(f"  ⚠  Audio skipped (non-fatal): {e}")
        return None
    return {"tts_provider": "openai", "tts_model": model, "tts_voice": voice,
            "tts_chars": len(script), "audio_bytes": out_path.stat().st_size,
            "audio_seconds": _duration_seconds(out_path, script)}


# ── The feed ─────────────────────────────────────────────────────────────────

def update_feed(public: Path, web_base: str, episode: dict) -> bool:
    """Add today's episode to podcast.json and regenerate podcast.xml.

    The episode list accumulates across runs and public/ starts empty on every
    runner, so this is the archive.json problem again and is handled the same
    way: read the published copy first, and write nothing at all if that read
    fails. A feed rebuilt without its history would drop every earlier episode
    from subscribers' apps.
    """
    from shared.published import load_list, write_if_safe
    manifest = public / "podcast.json"
    # Branch first, live site second — the same reason as the archive: a feed
    # whose history is read over HTTP would stop updating whenever Pages is off.
    episodes, ok = load_list(manifest, web_base)
    if not ok:
        print("  ⚠  Podcast feed not updated — published episode list unreadable")
        return False
    episodes = [e for e in episodes if e.get("date") != episode["date"]] + [episode]
    episodes.sort(key=lambda e: e.get("date", ""))
    episodes = episodes[-FEED_EPISODES:]
    if not write_if_safe(manifest, episodes, ok):
        return False
    (public / "podcast.xml").write_text(_feed_xml(episodes, web_base), encoding="utf-8")
    return True


def _feed_xml(episodes: list[dict], web_base: str) -> str:
    base = web_base.rstrip("/")
    items = []
    for e in reversed(episodes):
        when = datetime.strptime(e["date"], "%Y-%m-%d").replace(hour=11, tzinfo=timezone.utc)
        secs = int(e.get("seconds") or 0)
        items.append(f"""    <item>
      <title>{_xml(e["title"])}</title>
      <description>{_xml(e.get("summary", ""))}</description>
      <enclosure url="{_xml(base + "/" + e["file"])}" length="{int(e.get("bytes") or 0)}" type="audio/mpeg"/>
      <guid isPermaLink="false">korea-daily-brief-{e["date"]}</guid>
      <pubDate>{format_datetime(when)}</pubDate>
      <itunes:duration>{secs // 60}:{secs % 60:02d}</itunes:duration>
      <link>{_xml(base + "/digest_" + e["date"] + ".html")}</link>
    </item>""")
    # itunes:block keeps the feed out of podcast directories. The brief is
    # marked For Internal Use Only; the feed is for subscribing by URL, the same
    # audience that already reads the archive, and not for public discovery.
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>Korea Daily Brief</title>
    <link>{_xml(base + "/archive.html")}</link>
    <description>The CSIS Korea Chair's daily brief on the Korean Peninsula, read aloud. Every item is from the printed brief, which links its sources.</description>
    <language>en-us</language>
    <itunes:author>CSIS Korea Chair</itunes:author>
    <itunes:explicit>false</itunes:explicit>
    <itunes:block>Yes</itunes:block>
{chr(10).join(items)}
  </channel>
</rss>
"""


def produce(digest: dict, public: Path, web_base: str, date_slug: str) -> dict | None:
    """Script, audio and feed for one issue. Returns the metrics record, or None."""
    script = build_script(digest)
    (public / f"digest_{date_slug}.txt").write_text(script, encoding="utf-8")
    mp3 = public / f"digest_{date_slug}.mp3"
    rec = synthesize(script, mp3)
    if not rec:
        return None
    shutil.copyfile(mp3, public / "latest.mp3")
    if web_base:
        update_feed(public, web_base, {
            "date": date_slug,
            "title": f"Korea Daily Brief | {_spoken_date(digest)}",
            "summary": speakable(digest.get("re_line", "")),
            "file": mp3.name, "bytes": rec["audio_bytes"],
            "seconds": rec["audio_seconds"],
        })
    return rec


def produce_for_published_issue(date_slug: str, public: Path, web_base: str) -> int:
    """Make the audio for an issue that has already gone out. Sends nothing.

    Reads that day's digest JSON from the gh-pages branch — the issue exactly
    as published — so an episode can be made after the fact without running
    the pipeline again, which would collect fresh news, write a different
    brief, and mail the list a second time.

    Exits non-zero when no audio is produced, because this is run by hand to
    find out whether audio works, and a green run with no MP3 would say it did.
    """
    from shared.published import read_from_branch
    text, reachable = read_from_branch(f"digest_{date_slug}.json")
    if text is None:
        print(f"✗ No published digest for {date_slug} on gh-pages"
              + ("" if reachable else " (branch unreachable)"))
        return 2
    digest = json.loads(text)
    try:
        # Issues published before the 7 October fix carry the pledge project
        # twice; tidy it the same way the pipeline now does before narrating.
        from run import _ensure_pledge_projects
        _ensure_pledge_projects(digest)
    except Exception:                                           # noqa: BLE001
        pass
    public.mkdir(parents=True, exist_ok=True)
    rec = produce(digest, public, web_base, date_slug)
    if not rec:
        if not (os.environ.get("OPENAI_API_KEY") or "").strip():
            why = ("OPENAI_API_KEY is empty in this run. Add it as a REPOSITORY "
                   "secret: Settings > Secrets and variables > Actions > "
                   "Repository secrets. Variables and Environment secrets are "
                   "not visible to this workflow.")
        else:
            why = LAST_ERROR or "OpenAI returned no audio."
            if "quota" in why.lower() or "billing" in why.lower():
                why += (" — the OpenAI account needs credit: "
                        "platform.openai.com/settings/organization/billing")
            elif "401" in why or "incorrect api key" in why.lower():
                why += " — the key is wrong or revoked; create a new one and replace the secret."
        print(f"::error title=No audio produced::{why}")
        print(f"✗ No audio produced: {why}")
        return 1
    url = f"{web_base.rstrip('/')}/digest_{date_slug}.mp3" if web_base else str(public)
    print(f"✓ {date_slug}: {rec['audio_bytes']:,} bytes, ~{rec['audio_seconds'] // 60} min "
          f"({rec['tts_model']}, {rec['tts_voice']}) -> {url}")
    return 0


if __name__ == "__main__":
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="Korea Daily Brief audio edition.")
    ap.add_argument("digest_json", nargs="?",
                    help="Print the spoken script for a local digest JSON file.")
    ap.add_argument("--issue", metavar="YYYY-MM-DD",
                    help="Make audio for an already-published issue (sends nothing). "
                         "Use 'today' for today's issue.")
    ap.add_argument("--out", default="public", help="Output directory (default: public)")
    a = ap.parse_args()
    if a.issue:
        from zoneinfo import ZoneInfo
        day = (datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
               if a.issue == "today" else a.issue)
        sys.exit(produce_for_published_issue(day, Path(a.out),
                                             os.environ.get("WEB_URL", "")))
    if not a.digest_json:
        ap.error("give a digest JSON file, or --issue")
    d = json.load(open(a.digest_json, encoding="utf-8"))
    s = build_script(d)
    print(s)
    print(f"\n— {len(s.split()):,} words, ~{estimate_minutes(s):.1f} min, {len(s):,} chars")
