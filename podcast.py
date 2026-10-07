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
    TTS_VOICE        default ash
    TTS_STYLE        how the voice reads; default is a conversational podcast host
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
CHUNK_CHARS = 800           # a short paragraph per request; see _chunks
MIN_COVERAGE = 0.8          # a request whose audio is shorter than this share
                            # of its expected length is redone: a voice speaking
                            # quickly lands near 0.9, a skipped passage well below.
                            # At 0.6 a request that lost a quarter of its words
                            # passed, and 17% of a test episode vanished unremarked.
PUBLISH_COVERAGE = 0.75     # after retries, below this the episode is withheld
FEED_EPISODES = 30          # what the feed advertises; the workflow prunes the rest
DEFAULT_MODEL = "gpt-4o-mini-tts"
DEFAULT_VOICE = "ash"            # softer, conversational; suits the podcast-host delivery
LAST_ERROR = ""              # why the most recent synthesis produced nothing
# How the voice reads, sent with every request to models that take it. The
# default is the conversational public-radio register rather than a newsreader:
# unhurried, warm and curious, the way a host talks to one listener. It is a
# description of a style, deliberately not of any particular person — cloning
# or imitating a real host's voice is outside what the providers permit and
# would let listeners mistake the brief for someone else's programme.
# Override per repo with the TTS_STYLE variable; no code change needed.
DELIVERY = ("You are the host of a daily news podcast, talking to one listener you "
            "respect. Engaged and genuinely curious — you find this interesting and "
            "it shows. Conversational, with momentum: vary your pace, slow down for "
            "the fact that matters, pick up through connective lines. A natural "
            "pause before a key number or quote, a longer one between stories. "
            "Warm, never theatrical, never a newsreader's monotone. Pronounce "
            "Korean names carefully.")

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
    """The whole brief as a spoken script, in the order it is printed.

    Every section is read except US–Korea Trade & Investment, which is a
    standing reference — tariff tables, the pledge ledger — not the day's news,
    and which the editor asked to leave out of the audio. The morning memo is
    replaced by the RE line, because the memo retells the top stories.

    Connective phrases are the only words added, and none carries a fact. A
    story already told in an earlier section is not told again: sections such
    as ROK Government often restate a top story, and a listener, unlike a
    reader, cannot skip the repeat.
    """
    when = _spoken_date(digest)
    out: list[str] = [f"This is the Korea Daily Brief from the CSIS Korea Chair. It's {when}."]
    told: list[set] = []

    def fresh(text: str) -> bool:
        w = _words(text)
        if not w:
            return False
        if any(len(w & t) / len(w) >= 0.6 for t in told):
            return False
        told.append(w)
        return True

    def section(lead: str, items: list[str]) -> None:
        items = [i for i in items if i and fresh(i)]
        if items:
            out.append(f"{lead} {items[0]}")
            out.extend(items[1:])

    parts = [speakable(x).rstrip(".") for x in str(digest.get("re_line") or "").split("·")]
    parts = [x for x in parts if x]
    if len(parts) > 1:
        out.append("In today's brief: " + "; ".join(parts[:-1]) + "; and " + parts[-1] + ".")
    elif parts:
        out.append(f"In today's brief: {parts[0]}.")

    top = _items(digest, "top_stories")
    for n, item in enumerate(top):
        told_text = _story(item)
        fresh(told_text)
        lead = "Our top story:" if n == 0 else ("And finally:" if n == len(top) - 1 else "Also making news:")
        out.append(f"{lead} {told_text}")

    section("Here's what else happened overnight.",
            [_story(i, "body_text") for i in _items(digest, "overnight_items")])

    kcna = digest.get("kcna_delta") or {}
    if isinstance(kcna, dict):
        arts = [_story({"headline": a.get("headline", ""), "body": a.get("summary", "")})
                for a in (kcna.get("top_articles") or []) if isinstance(a, dict)]
        if kcna.get("bottom_line"):
            bl = "The bottom line: " + speakable(kcna["bottom_line"])
            days = kcna.get("days_since_last_appearance")
            if isinstance(days, int) and days > 0 and not kcna.get("kim_appearance_today"):
                bl += f" Kim Jong Un was last seen in public {days} day{'s' if days != 1 else ''} ago."
            arts.append(bl)
        section("Turning to Pyongyang, and what state media is saying.", arts)

    ks = digest.get("key_stat") or {}
    if isinstance(ks, dict) and ks.get("number"):
        stat = speakable(f'{ks["number"]}: {ks.get("label", "")}.').rstrip(".") + "."
        if ks.get("context"):
            stat += " " + speakable(ks["context"])
        out.append(f"The number of the day. {stat}")

    gov = []
    for g in _items(digest, "rok_government"):
        line = speakable(g.get("action", ""))
        if g.get("detail"):
            line += " " + speakable(g["detail"])
        gov.append(line)
    for a in _items(digest, "rok_assembly"):
        gov.append(speakable(f'At the National Assembly, {a.get("committee", "")}: {a.get("action", "")}')
                   + (" " + speakable(a["detail"]) if a.get("detail") else ""))
    for r in _items(digest, "rok_personnel"):
        gov.append(speakable(f'{r.get("name", "")}, {r.get("position", "")}: {r.get("action", "")}')
                   + (" " + speakable(r["detail"]) if r.get("detail") else ""))
    section("From the South Korean government.", gov)

    section("In business news.", [_story(i, "body_text") for i in _items(digest, "business_economy")])
    section("Around the region.", [_story(i, "body_text") for i in _items(digest, "northeast_asia")])

    ps = digest.get("public_sentiment") or {}
    ap = ps.get("presidential_approval") or {}
    if isinstance(ap, dict) and ap.get("value"):
        src = ap.get("source") or "the latest poll"
        dated = f", taken {ap['last_updated']}" if ap.get("last_updated") else ""
        line = (f"In {src}{dated}, the president's approval stands at "
                f"{str(ap['value']).replace('%', ' percent')}")
        if ap.get("trend") in ("up", "down"):
            line += f", {ap['trend']}"
        line += "."
        parties = []
        for key in ("party_ruling", "party_opposition"):
            pt = ps.get(key) or {}
            if isinstance(pt, dict) and pt.get("value") and pt.get("party"):
                parties.append(f"the {pt['party']} at {str(pt['value']).replace('%', ' percent')}")
        ind = ps.get("party_independent") or {}
        if isinstance(ind, dict) and ind.get("value"):
            parties.append(f"independents at {str(ind['value']).replace('%', ' percent')}")
        if parties:
            line += " Party support: " + ", ".join(parties) + "."
        out.append(f"On public opinion. {line}")

    quotes = []
    for q in _items(digest, "social_statements") + _items(digest, "official_x_posts"):
        if q.get("quote_text") and q.get("who"):
            ctx = f", {q['handle_context']}," if q.get("handle_context") else ""
            line = speakable(f'{q["who"]}{ctx} said: "{q["quote_text"]}"')
            if q.get("analyst_note"):
                line += " " + speakable(q["analyst_note"])
            quotes.append(line)
    section("In their own words.", quotes)

    _y = re.search(r"\b(20\d{2})\b", str(digest.get("digest_date") or ""))
    year = _y.group(1) if _y else ""
    ahead = []
    for c in (digest.get("calendar_watch") or []):
        if not isinstance(c, dict):
            continue
        date = str(c.get("date") or "").strip()
        if year:
            date = re.sub(rf",?\s*{year}\b", "", date).strip()
        event = speakable(c.get("event") or c.get("headline") or "")
        if event:
            ahead.append((f"{date}: " if date else "") + event)
    if ahead:
        out.append("Looking ahead. " + " ".join(ahead))

    section("Also on the wire.", [_story(i, "body_text") for i in _items(digest, "also_today")])

    analysis = []
    for o in _items(digest, "opeds_today") + _items(digest, "academic_today"):
        head = speakable(o.get("headline", "")).rstrip(".")
        by = o.get("authors")
        by = ", ".join(by) if isinstance(by, list) else (by or "")
        src = o.get("source") or o.get("journal") or ""
        intro = head + (f", by {by}" if by else "") + (f", in {src}" if src else "") + "."
        arg = speakable(o.get("central_argument") or o.get("summary") or "")
        analysis.append(f"{intro} {arg}".strip())
    section("In analysis and commentary.", analysis)

    im = digest.get("imagery_report") or {}
    if isinstance(im, dict) and (im.get("headline") or im.get("body")):
        section("From satellite imagery.",
                [_story({"headline": im.get("headline", ""), "body": im.get("body", "")})])

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

    out.append(f"That's the Korea Daily Brief for {when}. The full text, with a "
               f"link to every source, is in today's email.")
    return "\n\n".join(x.strip() for x in out if x and x.strip())


# ── The written-for-the-ear script ───────────────────────────────────────────

_SCRIPT_SYSTEM = """You write the script for the audio edition of the Korea Daily Brief, the CSIS Korea Chair's daily briefing on the Korean Peninsula. One host reads it aloud.

Sound like a thoughtful daily news podcast: one host talking to one listener. Warm, curious, conversational, with momentum. Open with a hook: the day's most consequential development in a sentence or two. Then walk through the stories with spoken transitions that connect them, and say plainly why something matters when the brief says why. Short sentences. Contractions. Now and then a question a listener might be asking, answered from the brief. No headline-ese, no strings of fragments, no lists read out.

FACTS. This rule outranks every other:
- Use ONLY facts in the brief JSON you are given. Every name, number, date, place, quote and claim must come from it.
- Add nothing from your own knowledge, even if you are certain it is true: no background, no history, no figures, no context the brief does not contain.
- Say why something matters only where the brief itself says so (body text, analyst notes, bottom lines, "so what" fields). Never speculate.
- Quote only quotes that appear in the brief, word for word, attributed as the brief attributes them.
- Write every number exactly as the brief writes it.
- If something in the brief is unclear, leave it out rather than interpret it.

COVER, in this order: the top stories; overnight; Pyongyang (the top KCNA articles, then the bottom line); the number of the day; the South Korean government, National Assembly and appointments; business and the economy; the region; public opinion (say when the poll was taken); statements and posts from officials; what is coming up; the rest of the wire; analysis and commentary; satellite imagery, only if it is included; the markets, briefly. Leave out US-Korea trade and investment entirely. Never tell the same story twice.

FORMAT: plain spoken text only, paragraphs separated by a blank line. No headings, no stage directions, no sound cues, no markdown, no bullet points. Begin exactly with: "This is the Korea Daily Brief from the CSIS Korea Chair. It's {when}." End exactly with: "That's the Korea Daily Brief for {when}. The full text, with a link to every source, is in today's email." Aim for 1,300 to 1,800 words."""

_SCRIPT_KEYS = ("re_line", "top_stories", "overnight_items", "kcna_delta", "key_stat",
                "rok_government", "rok_assembly", "rok_personnel", "business_economy",
                "northeast_asia", "public_sentiment", "social_statements",
                "official_x_posts", "calendar_watch", "also_today", "opeds_today",
                "academic_today", "imagery_report", "market_indicators")

# Capitalised words a script may use that need not appear in the brief: the
# show's own frame, calendar words, and generic titles.
_ALLOWED_CAPS = set("""
I The This That These Those It It's Its In On At For From With And But Or So Yet
Now Here Today Tomorrow Meanwhile Also First Next Finally Still Then And Why What
How Who Where When Which Let Lets Let's We We're You You're Our Your Their There
Korea Korean Daily Brief CSIS Chair South North Peninsula Seoul Pyongyang
Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March
April May June July August September October November December
President Minister Ministry Prime Defense Foreign Unification National Assembly
Party Government Committee Chairman Secretary General Commander Command State
U.S. US KCNA DPRK ROK Mr Ms Dr
""".split())


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(text).lower().replace(",", ""))


_NUMBER_WORDS = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
_NUMBER_WORDS.update({"thirty": "30", "forty": "40", "fifty": "50", "sixty": "60",
                      "seventy": "70", "eighty": "80", "ninety": "90", "hundred": "100"})


def _tokens(text: str) -> list[str]:
    """Lower-case word tokens, spelled-out numbers turned into digits."""
    toks = re.findall(r"\d+(?:\.\d+)?|[a-z]+", str(text).lower().replace(",", ""))
    return [_NUMBER_WORDS.get(t, t) for t in toks]


def _number_in_context(n: str, at: int, script_toks: list[str], src_toks: list[str],
                       src_pos: dict[str, list[int]]) -> bool:
    """Is n in the brief beside the same words it sits beside in the script?

    Whether a number appears anywhere in the brief proves nothing: "18" and
    "7" are in its dates, so "18 satellites" passed against a brief that says
    15. The number must appear within a few words of a content word that also
    flanks it in the script.
    """
    def content(seq):
        return [t for t in seq if len(t) > 3 and not t[0].isdigit() and t not in _STOP]
    near = set(content(script_toks[max(0, at - 6):at])[-2:] + content(script_toks[at + 1:at + 6])[:2])
    places = src_pos.get(n, [])
    if not near:
        return bool(places)
    return any(near & set(src_toks[max(0, i - 5):i + 6]) for i in places)


def check_script(script: str, digest: dict, when: str = "") -> list[str]:
    """Problems that mean the script says something the brief does not.

    Three checks, each aimed at the way a rewrite most often invents: a number
    not in the brief, a quotation not in the brief, and a proper name not in
    the brief. Deliberately strict — a false alarm costs one day of the plain
    assembled script, and a missed invention costs the brief its credibility.
    """
    src = json.dumps({k: digest.get(k) for k in _SCRIPT_KEYS}, ensure_ascii=False)
    src += " " + str(digest.get("digest_date") or "") + " " + when
    blob = _norm(src)
    problems = []
    src_toks = _tokens(src)
    src_pos: dict[str, list[int]] = {}
    for i, t in enumerate(src_toks):
        if t[0].isdigit():
            src_pos.setdefault(t, []).append(i)
    # The opening and closing lines carry the date and are fixed text, checked
    # separately. They are removed here rather than exempting the date's
    # numbers everywhere: a global exemption for "7" let "seven soldiers"
    # through on 7 October against a brief that says three.
    body = script
    for fixed in (f"This is the Korea Daily Brief from the CSIS Korea Chair. It's {when}.",
                  f"That's the Korea Daily Brief for {when}."):
        body = body.replace(fixed, " ")
    s_toks = _tokens(body)
    for i, t in enumerate(s_toks):
        if t[0].isdigit() and not _number_in_context(t, i, s_toks, src_toks, src_pos):
            ctx = " ".join(s_toks[max(0, i - 2):i + 3])
            problems.append(f"number not in the brief here: {t} ({ctx})")
    for q in re.findall(r"[\"“]([^\"”]{12,})[\"”]", script):
        if _norm(q).strip() and " ".join(_norm(q).split()) not in " ".join(blob.split()):
            problems.append(f"quotation not in the brief: {q[:60]!r}")
    for sentence in re.split(r"(?<=[.!?:;])\s+|\n+", script):
        words = re.findall(r"[A-Za-z][A-Za-z'.-]*", sentence)
        for w in words[1:]:
            core = w.strip(".'-").replace("'s", "")
            if not core or not core[0].isupper() or core in _ALLOWED_CAPS or len(core) < 3:
                continue
            if core.lower() not in blob:
                problems.append(f"name not in the brief: {core}")
    seen, out = set(), []
    for p in problems:
        if p not in seen:
            seen.add(p); out.append(p)
    return out


def write_script(digest: dict) -> tuple[str | None, list[str]]:
    """A script written for listening, or (None, reasons) to fall back.

    Uses the brief's own model. Falls back — never fails — when there is no
    key, the call errors, the framing lines are missing, or check_script finds
    anything the brief does not say.
    """
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        return None, ["no ANTHROPIC_API_KEY"]
    try:
        from digest import FAST_MODEL as _default_model
    except Exception:                                           # noqa: BLE001
        _default_model = "claude-sonnet-4-6"
    model = (os.environ.get("PODCAST_SCRIPT_MODEL") or "").strip() or _default_model
    when = _spoken_date(digest)
    def _no_urls(v):
        # Links cost tokens and give the writer nothing to say; dropped
        # structurally — a regex over the JSON left a trailing comma when the
        # link was the last field, and the payload failed to parse.
        if isinstance(v, dict):
            return {k: _no_urls(x) for k, x in v.items() if k not in ("url", "source_links")}
        if isinstance(v, list):
            return [_no_urls(x) for x in v]
        return v

    try:
        payload = {k: _no_urls(digest[k]) for k in _SCRIPT_KEYS if digest.get(k)}
        import anthropic
        msg = anthropic.Anthropic(api_key=key).messages.create(
            model=model, max_tokens=4000,
            system=_SCRIPT_SYSTEM.replace("{when}", when),
            messages=[{"role": "user", "content":
                       "Here is today's brief as JSON. Write the audio script.\n\n"
                       + json.dumps(payload, ensure_ascii=False)}])
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    except Exception as e:                                      # noqa: BLE001
        return None, [f"script call failed: {e}"]
    opening = f"This is the Korea Daily Brief from the CSIS Korea Chair. It's {when}."
    if not text.startswith(opening[:40]):
        return None, ["the script did not open with the show's opening line"]
    problems = check_script(text, digest, when)
    if problems:
        return None, problems
    paras = [speakable(x) for x in text.split("\n\n") if x.strip()]
    return "\n\n".join(paras), []


def estimate_minutes(script: str) -> float:
    return len(script.split()) / SPOKEN_WPM


# ── Synthesis ────────────────────────────────────────────────────────────────

_MP3_BITRATES = {True: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
                 False: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]}
_MP3_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def mp3_seconds(data: bytes) -> float:
    """Length of an MP3 in seconds, by walking its frames.

    The first episode was published as 5:36 when it held 3:31 of audio: the
    length came from a word-count estimate, because ffprobe was not on the
    runner. Counting frames needs nothing installed and cannot be fooled by a
    short file — which is the one thing this number is for.
    """
    i, secs, n = 0, 0.0, len(data)
    while i < n - 4:
        h = int.from_bytes(data[i:i + 4], "big")
        if (h >> 21) & 0x7FF == 0x7FF:
            ver, layer = (h >> 19) & 3, (h >> 17) & 3
            bri, sri, pad = (h >> 12) & 15, (h >> 10) & 3, (h >> 9) & 1
            if layer == 1 and ver != 1 and 0 < bri < 15 and sri < 3:
                mpeg1 = ver == 3
                sr = _MP3_RATES[ver][sri]
                br = _MP3_BITRATES[mpeg1][bri] * 1000
                secs += (1152 if mpeg1 else 576) / sr
                i += (144 if mpeg1 else 72) * br // sr + pad
                continue
        i += 1
    return secs


def _expected_seconds(text: str) -> float:
    return len(text.split()) / SPOKEN_WPM * 60


def _chunks(script: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Pack paragraphs into requests, kept small on purpose.

    The first live episode sent three requests of up to 3,500 characters and
    came back a third short: the voice model can stop early on a long passage
    and still return a well-formed file. Requests of about a paragraph each
    make a skip both less likely and, when it happens, cheap to redo.

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
        body["instructions"] = (os.environ.get("TTS_STYLE") or "").strip() or DELIVERY
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
    global LAST_ERROR
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key or not script.strip():
        return None
    model = (os.environ.get("TTS_MODEL") or "").strip() or DEFAULT_MODEL
    voice = (os.environ.get("TTS_VOICE") or "").strip() or DEFAULT_VOICE
    def _voiced(text: str) -> bytes:
        """One request, checked. Retried once, then sentence by sentence, if short."""
        want = _expected_seconds(text)
        audio = _openai_tts(text, key, model, voice)
        if want < 4 or mp3_seconds(audio) >= MIN_COVERAGE * want:
            return audio
        audio = _openai_tts(text, key, model, voice)
        if mp3_seconds(audio) >= MIN_COVERAGE * want:
            return audio
        sentences = [x for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()]
        if len(sentences) < 2:
            return audio
        return b"".join(_openai_tts(x, key, model, voice) for x in sentences)

    try:
        parts = [_voiced(c) for c in _chunks(script)]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _join_mp3(parts, out_path)
    except Exception as e:                                      # noqa: BLE001
        LAST_ERROR = str(e)
        # An annotation, not only a log line: GitHub serves job logs from a
        # separate host, while annotations are readable through the API, so
        # the reason a run produced no audio can be read back without the log.
        print(f"::warning title=Audio skipped::{e}")
        print(f"  ⚠  Audio skipped (non-fatal): {e}")
        return None
    got = mp3_seconds(out_path.read_bytes())
    want = _expected_seconds(script)
    if got < PUBLISH_COVERAGE * want:
        # A short episode is worse than none: it reads as the day's brief and
        # silently leaves part of it out. Not published, and the reason is
        # said where it can be read.
        LAST_ERROR = (f"the audio is {got:.0f} s but the script needs about "
                      f"{want:.0f} s — the voice skipped part of the brief, so "
                      f"the episode was not published")
        print(f"::warning title=Audio incomplete::{LAST_ERROR}")
        out_path.unlink(missing_ok=True)
        return None
    return {"tts_provider": "openai", "tts_model": model, "tts_voice": voice,
            "tts_chars": len(script), "audio_bytes": out_path.stat().st_size,
            "audio_seconds": int(got), "audio_expected_seconds": int(want)}


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


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _last_date(text: str) -> datetime | None:
    """The last day a date string names: "Oct 5–6, 2026" -> 6 October 2026."""
    m = re.search(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:\s*[–-]\s*(\d{1,2}))?,?\s+(20\d{2})", str(text or ""))
    if not m or m.group(1).lower() not in _MONTHS:
        return None
    try:
        return datetime(int(m.group(4)), _MONTHS[m.group(1).lower()], int(m.group(3) or m.group(2)))
    except ValueError:
        return None


def imagery_is_new(digest: dict, previous: dict | None) -> bool:
    """Read the satellite item only when it is a new story.

    The imagery slot is filled every day, often with the same report: the
    Sangum-ri upgrade led on 6 October and again on the 7th under a different
    date, and one 3 October naval-construction report ran on two consecutive
    issues. New means dated today or yesterday — a report with no day at all
    ("Oct 2026") cannot be shown to be new — and not the story the previous
    issue already carried.
    """
    im = digest.get("imagery_report") or {}
    if not isinstance(im, dict) or not (im.get("headline") or im.get("body")):
        return False
    when, today = _last_date(im.get("date")), _last_date(digest.get("digest_date"))
    if not when or not today or not (0 <= (today - when).days <= 1):
        return False
    prev = (previous or {}).get("imagery_report") or {}
    if isinstance(prev, dict) and prev.get("headline"):
        a, b = _words(im.get("headline", "")), _words(prev["headline"])
        if a and len(a & b) / len(a) >= 0.5:
            return False
    return True


def _previous_issue(date_slug: str) -> dict | None:
    """The last issue published before date_slug, from the gh-pages branch."""
    from datetime import timedelta
    from shared.published import read_from_branch
    try:
        day = datetime.strptime(date_slug, "%Y-%m-%d")
    except ValueError:
        return None
    for back in range(1, 5):
        text, _ = read_from_branch(f"digest_{(day - timedelta(days=back)):%Y-%m-%d}.json")
        if text:
            try:
                return json.loads(text)
            except ValueError:
                return None
    return None


def produce(digest: dict, public: Path, web_base: str, date_slug: str) -> dict | None:
    """Script, audio and feed for one issue. Returns the metrics record, or None."""
    digest = dict(digest)
    if not imagery_is_new(digest, _previous_issue(date_slug)):
        digest.pop("imagery_report", None)
    script, why = write_script(digest)
    source = "written"
    if not script:
        script, source = build_script(digest), "assembled"
        if why and why != ["no ANTHROPIC_API_KEY"]:
            shown = "; ".join(why[:4]) + (f" (+{len(why) - 4} more)" if len(why) > 4 else "")
            print(f"::warning title=Podcast script fell back to the assembled version::{shown}")
    print(f"  🎙  Script: {source}, {len(script.split()):,} words")
    public.mkdir(parents=True, exist_ok=True)
    (public / f"digest_{date_slug}.txt").write_text(script, encoding="utf-8")
    mp3 = public / f"digest_{date_slug}.mp3"
    rec = synthesize(script, mp3)
    if not rec:
        return None
    rec["script_source"] = source
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
