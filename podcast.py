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
    OPENAI_API_KEY   enables synthesis (and is the fallback voice)
    ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID   use an ElevenLabs voice instead
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
DEFAULT_VOICE = "marin"          # OpenAI's recommended voice for quality narration
FALLBACK_VOICE = "ash"           # if the model ever refuses the default
SEGMENT = "---"                  # a line on its own: a segment break, voiced as a pause
PAUSE_PARAGRAPH = 0.7            # seconds of silence between requests within a segment
PAUSE_SEGMENT = 1.5              # ... and between segments
PCM_RATE = 24000                 # OpenAI's native speech rate; everything is mixed at it
LAST_ERROR = ""              # why the most recent synthesis produced nothing
# How the voice reads, sent with every request to models that take it. The
# default is the conversational public-radio register rather than a newsreader:
# unhurried, warm and curious, the way a host talks to one listener. It is a
# description of a style, deliberately not of any particular person — cloning
# or imitating a real host's voice is outside what the providers permit and
# would let listeners mistake the brief for someone else's programme.
# Override per repo with the TTS_STYLE variable; no code change needed.
DELIVERY = ("You are the host of a daily news podcast for senior policymakers, talking "
            "to one listener you respect. Calm, warm and unhurried: a measured pace, "
            "slower than conversation, so every sentence lands. Take a breath between "
            "sentences. Slow down for names, numbers and quotes, and pause briefly "
            "before them. Never rush a list or the end of a sentence. Engaged and "
            "curious, never theatrical, never a newsreader's monotone. Pronounce "
            "Korean names carefully.")
# ElevenLabs, when ELEVENLABS_API_KEY and a voice are set; OpenAI otherwise,
# and as the fallback if ElevenLabs fails, so a problem there never costs the
# day's episode. Models are tried in order until one is accepted.
ELEVEN_MODELS = ("eleven_v4", "eleven_v3", "eleven_multilingual_v2")
# Rafaga, chosen by the editor on 8 October from the voice audition: a calm,
# mature narrator with precise articulation, picked for a listener used to
# audiobooks. The ELEVENLABS_VOICE_ID variable overrides it.
DEFAULT_ELEVEN_VOICE = "68sMPAsdt7bCNPLgaEmA"
ELEVEN_CHUNK_CHARS = 2400        # stitched requests, so fewer, longer ones sound better
ELEVEN_SPEED = 0.95              # the voice's own pace setting; 1.0 is its natural pace
# The voice model's own pace is a suggestion it does not always take; this is
# applied after, pitch unchanged. 1.0 leaves it alone; TTS_PACE overrides.
DEFAULT_PACE = 0.92

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


_MONTH_NAMES = {"Jan": "January", "Feb": "February", "Mar": "March", "Apr": "April",
           "Jun": "June", "Jul": "July", "Aug": "August", "Sep": "September",
           "Oct": "October", "Nov": "November", "Dec": "December"}
_ORDINAL = {"1": "first", "2": "second", "3": "third", "4": "fourth"}
# Ministry acronyms a reader decodes and a listener can't.
_SPOKEN_NAMES = (("MOFA", "Foreign Ministry"), ("MOTIE", "Industry Ministry"),
                 ("MND", "Defense Ministry"), ("MOEF", "Finance Ministry"),
                 ("MDL", "military demarcation line"),
                 ("NK Pro", "N.K. Pro"), ("NK News", "N.K. News"),
                 ("IRBMs?", "intermediate-range missile"), ("ICBMs?", "intercontinental ballistic missile"),
                 ("SLBMs?", "submarine-launched ballistic missile"), ("LNG", "liquefied natural gas"),
                 ("POWs", "prisoners of war"), ("POW", "prisoner of war"),
                 ("KBO", "Korean baseball"), ("IPs", "internet addresses"))


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
    t = re.sub(r"\(?\b[A-Z]{3}\d{8,}\b\)?", "", t)                  # wire story IDs
    t = re.sub(r",?\s*@\w+\s*,?", "", t)                               # social handles
    t = re.sub(r"\b(Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)\.?\s+(?=\d)",
               lambda m: _MONTH_NAMES[m.group(1)[:3]] + " ", t)
    t = re.sub(r"\bQ([1-4])\s+(20\d\d)\b",
               lambda m: f"the {_ORDINAL[m.group(1)]} quarter of {m.group(2)}", t)
    t = re.sub(r"(\d)\s?km\b", r"\1 kilometers", t)
    for short, full in _SPOKEN_NAMES:
        t = re.sub(rf"\b{short}\b", full, t)
    t = re.sub(r"\b([A-Za-z]+)/([A-Za-z]+)\b", r"\1 and \2", t)          # "Taiwan/Russia"
    t = re.sub(r"\s*\(([^()]{1,60})\)", r", \1,", t)                    # asides, not brackets
    t = re.sub(r",\s*([,.;:!?])", r"\1", t)
    t = re.sub(r",\s*—", " —", t)
    # "..., per KCNA via Reuters and the Kyiv Post." — a chain of sources read
    # after the claim; the listener needs the first one, said plainly.
    t = re.sub(r",?\s+per ([A-Z][\w.'&-]*(?: [A-Z][\w.'&-]*)*)(?: via [^.;]+)?(?=[.;])",
               r", according to \1", t)
    t = re.sub(r",(['’\"]),", r"\1,", t)                  # "'sacred,'," -> "'sacred',"
    # An expanded ministry acronym at the start of a clause needs its article.
    t = re.sub(r"(^|[.:;]\s+)((?:Foreign|Industry|Defense|Finance) Ministry)", r"\1The \2", t)
    # "South Korea 747 billion dollar energy transition" (from "ROK $747B ...")
    t = re.sub(r"\b((?:North|South) Korea) (\d[\d.,]* (?:thousand|million|billion|trillion) dollar)\b",
               r"\1's \2", t)
    t = re.sub(r"\s+([,.;:])", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    if t and (t[-1] not in ".?!\"'”’" or (t[-1] in "\"'”’" and t[-2:-1] not in ".?!,")):
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


_COMMON_NAMES = {"north", "south", "korea", "korean", "koreas", "seoul", "pyongyang", "kim",
                 "jong", "president", "lee", "jae", "myung", "minister", "foreign", "defense",
                 "ministry", "the", "dmz", "kcna", "u.s", "united", "states", "russia",
                 "russian", "china", "chinese", "japan", "japanese", "washington", "party"}


def _names(text: str) -> set[str]:
    """Distinct capitalised words that are not the brief's everyday names."""
    return {w.lower().strip(".'") for w in re.findall(r"(?<![.!?]\s)\b[A-Z][a-zA-Z.'-]{2,}", text)
            if w.lower().strip(".'") not in _COMMON_NAMES}


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


_SECTION_LEADS = ("Our top story", "Here's what else", "Now to Pyongyang", "The number of the day",
                  "In Seoul,", "On the economy", "Elsewhere in the region", "How is the public",
                  "In their own words", "What's coming up", "A few more things",
                  "And from the analysts", "From satellite imagery", "Finally, the markets",
                  "That's the Korea Daily Brief")


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
    told_names: list[tuple[set, set]] = []

    def fresh(text: str) -> bool:
        # The whole item and its opening are both compared: a paraphrase of
        # the same story shares its lead (who, with whom, about what) even
        # when its second sentence goes somewhere else.
        # Four shared uncommon names (Cho, Hyun, Anita, Anand) are the same
        # story however differently the two items word it.
        w, lead = _words(text), _words(" ".join(text.split()[:25]))
        names = _names(text)
        if not w:
            return False
        for t, tn in told_names:
            if len(w & t) / min(len(w), len(t)) >= 0.5 or len(names & tn) >= 4 or \
                    (len(lead) >= 5 and len(lead & t) / len(lead) >= 0.6):
                return False
        told.append(w)
        told_names.append((w, names))
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
        lead = "Our top story:" if n == 0 else ("And one more top story:" if n == len(top) - 1 else "Also making news:")
        out.append(f"{lead} {told_text}")

    section("Here's what else moved overnight.",
            [_story(i, "body_text") for i in _items(digest, "overnight_items")])

    kcna = digest.get("kcna_delta") or {}
    if isinstance(kcna, dict):
        # Always the top state-media articles, even when a top story already
        # covered one: then just its headline, as how Pyongyang played it.
        top_arts = [a for a in (kcna.get("top_articles") or []) if isinstance(a, dict)][:3]
        arts = []
        for a in top_arts:
            full = _story({"headline": a.get("headline", ""), "body": a.get("summary", "")})
            w = _words(full)
            if w and any(len(w & t) / min(len(w), len(t)) >= 0.5 for t in told):
                arts.append(speakable(a.get("headline", "")))
            else:
                told.append(w)
                arts.append(full)
        if arts:
            lead = ("State media's top stories today. " if len(arts) > 1 else "State media's top story today. ")
            arts = [lead + " ".join(arts)]
        if kcna.get("bottom_line"):
            bl = "The bottom line: " + speakable(kcna["bottom_line"])
            days = kcna.get("days_since_last_appearance")
            if isinstance(days, int) and days > 0 and not kcna.get("kim_appearance_today"):
                bl += f" Kim Jong Un was last seen in public {days} day{'s' if days != 1 else ''} ago."
            arts.append(bl)
        if arts:
            out.append("Now to Pyongyang. " + " ".join(arts))

    ks = digest.get("key_stat") or {}
    if isinstance(ks, dict) and ks.get("number"):
        stat = speakable(f'{ks["number"]}: {ks.get("label", "")}.').rstrip(".") + "."
        if ks.get("context"):
            stat += " " + speakable(ks["context"])
        out.append(f"The number of the day. {stat}")

    gov = []
    for g in _items(digest, "rok_government"):
        gov.append(_story({"headline": g.get("action", ""), "body": g.get("detail", "")}))
    for a in _items(digest, "rok_assembly"):
        committee = re.sub(r"^\s*National Assembly\s*[—:-]+\s*", "", str(a.get("committee") or ""))
        story = _story({"headline": a.get("action", ""), "body": a.get("detail", "")})
        gov.append((f"At the National Assembly's {speakable(committee).rstrip('.')}: " if committee else
                    "At the National Assembly: ") + story)
    for r in _items(digest, "rok_personnel"):
        gov.append(_story({"headline": f'{r.get("name", "")}, {r.get("position", "")}: {r.get("action", "")}',
                           "body": r.get("detail", "")}))
    section("In Seoul, the government side.", gov)

    section("On the economy.", [_story(i, "body_text") for i in _items(digest, "business_economy")])
    section("Elsewhere in the region.", [_story(i, "body_text") for i in _items(digest, "northeast_asia")])

    ps = digest.get("public_sentiment") or {}
    ap = ps.get("presidential_approval") or {}
    if isinstance(ap, dict) and ap.get("value"):
        src = ap.get("source") or "the latest"
        polled = re.sub(r",?\s*20\d\d", "", str(ap.get("last_updated") or ""))
        dated = f", from {polled}" if polled else ""
        line = (f"In the latest {src} poll{dated}, President Lee's approval is "
                f"{str(ap['value']).replace('%', ' percent')}")
        if ap.get("trend") in ("up", "down"):
            line += f", {ap['trend']} from the poll before"
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
            line += " By party: " + ", ".join(parties[:-1]) + ", and " + parties[-1] + "." \
                if len(parties) > 1 else " By party: " + parties[0] + "."
        out.append(f"How is the public reading all this? {line}")

    quotes = []
    for q in _items(digest, "social_statements") + _items(digest, "official_x_posts"):
        if q.get("quote_text") and q.get("who"):
            quotes.append(speakable(f'{q["who"]} said: "{q["quote_text"]}"'))
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
        date = re.sub(r"\s*\(.*?\)", "", date).strip()
        event = speakable(c.get("event") or c.get("headline") or "")
        if event:
            ahead.append((f"{date}: " if date else "") + event)
    if ahead:
        out.append("What's coming up? " + " ".join(ahead))

    section("A few more things worth knowing.", [_story(i, "body_text") for i in _items(digest, "also_today")])

    analysis = []
    for o in _items(digest, "opeds_today") + _items(digest, "academic_today"):
        head = speakable(o.get("headline", "")).rstrip(".")
        by = o.get("authors")
        by = ", ".join(by) if isinstance(by, list) else (by or "")
        src = speakable(o.get("source") or o.get("journal") or "").rstrip(".")
        arg = speakable(o.get("central_argument") or o.get("summary") or "")
        if arg and src:
            # What the piece argues and who published it; a title read aloud
            # ("Brewing Korea Crisis? Mines, Missiles, & POWs") is noise.
            analysis.append(f"From {src}" + (f", {by}" if by else "") + f": {arg}")
        else:
            intro = head + (f", by {by}" if by else "") + (f", in {src}" if src else "") + "."
            analysis.append(f"{intro} {arg}".strip())
    section("And from the analysts.", analysis)

    im = digest.get("imagery_report") or {}
    if isinstance(im, dict) and (im.get("headline") or im.get("body")):
        section("From satellite imagery.",
                [_story({"headline": im.get("headline", ""), "body": im.get("body", "")})])

    # usd_krw is dollars-to-won, so a fall means the won strengthened. Say
    # what the number is — "the dollar is at 1,338 won" — rather than "the won
    # is at 1,338, down", which reverses the direction for a listener.
    mk = digest.get("market_indicators") or {}
    spoken_mk = []
    # Figures are rounded as a presenter would say them: seven figures to two
    # decimals in fifteen seconds is noise to a listener.
    for key, fmt, places in (("kospi", "Seoul's main stock index, the KOSPI, is at {v}", 0),
                             ("usd_krw", "The dollar is at {v} won", 0),
                             ("brent", "Brent crude is at {v} dollars a barrel", 1),
                             ("bok_rate", "The Bank of Korea's base rate is {v}", None)):
        v = mk.get(key)
        if not isinstance(v, dict) or not v.get("value"):
            continue
        val = str(v["value"])
        if places is not None:
            try:
                num = float(val.replace(",", ""))
                val = f"{num:,.{places}f}"
            except ValueError:
                pass
        phrase = fmt.format(v=val.replace("%", " percent"))
        chg = v.get("change_pct")
        if isinstance(chg, (int, float)) and chg:
            phrase += f", {'up' if chg > 0 else 'down'} about {abs(round(chg, 1)):g} percent"
        spoken_mk.append(phrase + ".")
    if spoken_mk:
        out.append("Finally, the markets. " + " ".join(spoken_mk))

    out.append(f"That's the Korea Daily Brief for {when}. The full text, with a "
               f"link to every source, is in today's email.")
    # A pause before each section, as the written script has between segments.
    marked: list[str] = []
    for x in (x.strip() for x in out if x and x.strip()):
        if marked and x.startswith(_SECTION_LEADS):
            marked.append(SEGMENT)
        marked.append(x)
    return "\n\n".join(marked)


# ── The written-for-the-ear script ───────────────────────────────────────────

_SCRIPT_SYSTEM = """You write the script for the audio edition of the Korea Daily Brief, the CSIS Korea Chair's daily briefing on the Korean Peninsula for senior policymakers. One host reads it aloud. It should sound like a well-made daily news podcast (think of the shape of NPR's Up First or Axios Today), not a newsletter read out.

FACTS. This rule outranks every other:
- Use ONLY facts in the brief JSON you are given. Every name, number, date, place, quote and claim must come from it.
- Add nothing from your own knowledge, even if you are certain it is true: no background, no history, no figures, no context the brief does not contain.
- Say why something matters only where the brief itself says so (body text, analyst notes, bottom lines, "so what" fields). Never speculate.
- Quote only quotes that appear in the brief, word for word, attributed as the brief attributes them.
- Write every number as the brief writes it, with no more than two numbers per story. Market figures may be rounded the way a presenter says them ("1,338.38 won" as "about 1,338 won", "down 1.98 percent" as "down about 2 percent").
- If something in the brief is unclear, leave it out rather than interpret it.

SHAPE. Five segments, in this order. Put a line containing only --- between segments (the producer puts a pause there).
1. COLD OPEN (about 60 words). After the fixed opening line, go straight into the single most consequential development, told as a tension or a stakes question, not a summary. No throat-clearing. Then one menu line: "Three things today: ..." naming the three lead stories in a few words each.
2. THE THREE LEAD STORIES (about 250 words each), one after another, with --- between them. Usually the top stories. For each: what happened, why it matters to someone who works on Korea policy (from the brief), and what to watch next. Fold in related items from other sections (government reactions, the National Assembly, statements, analysis, imagery) so each lead is one connected story, not a list. Keep one strand per story: if several items are about the same military situation (a warning, missile launches, satellite imagery, a weapons analysis), they belong in one lead together.
3. PYONGYANG. Name every one of the top KCNA articles in kcna_delta.top_articles, even one a lead story already told (then one sentence on how state media framed it is enough), then the bottom line.
4. THE ROUND-UP. Everything else worth a listener's time, one or two sentences each, linked by quick spoken transitions: overnight items, government and appointments, the economy, the region, the poll (say when it was taken), what is coming up, the rest of the wire, analysis. Never tell a story the leads already told. Leave out US-Korea trade and investment entirely. Satellite imagery only if it is included.
5. CLOSE. The markets in two or three short sentences, then the fixed closing line.

WRITE FOR THE EAR. These are broadcast writing rules:
- One idea per sentence. Most sentences under 20 words, none over 25. Vary the rhythm: a short sentence after a long one.
- Attribution before the claim: "South Korea's Defense Ministry says...", not "..., the ministry said."
- Full name and title once, then a short form ("Unification Minister Chung Dong-young", then "Chung").
- Say "you" to the listener now and then. Contractions.
- Join stories by cause, contrast or consequence ("That warning lands the same day Seoul..."). Never "Next," "Also," "In other news," "Moving on."
- End each lead story by restating its key fact in a few words, because the listener can't re-read it.
- No acronyms a listener can't decode: say "the Foreign Ministry" not "MOFA", "intermediate-range missile" not "IRBM", "Seoul's main stock index" not "KOSPI", "prisoners of war" not "POWs", "liquefied natural gas" not "LNG". DMZ, KCNA, U.S. and UN are fine.
- Give a quote its context: who said it, and when or why, before the words themselves.
- Never title-read: say what an analysis argues and who published it, not its headline.
- No headline-ese, no strings of fragments, no lists read out, no parentheses.
- Never use these phrases: "let's dive in", "dive into", "delve", "in today's rapidly evolving", "it's worth noting", "notably", "a stark reminder", "only time will tell", "remains to be seen", "buckle up", "game-changer", "in a world where", "at the end of the day". Don't end sentences on a list of three for effect. Don't open with a rhetorical question.

FORMAT: plain spoken text only, paragraphs separated by a blank line, segments separated by a line containing only ---. No headings, no stage directions, no sound cues, no markdown, no bullet points. Begin exactly with: "This is the Korea Daily Brief from the CSIS Korea Chair. It's {when}." End exactly with: "That's the Korea Daily Brief for {when}. The full text, with a link to every source, is in today's email." Aim for 1,300 to 1,600 words."""

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
Washington Beijing Moscow Tokyo United States Bank Second Third
""".split())
_COUNTED_FACTS = {"soldier", "people", "troop", "missile", "satellite", "killed", "injured",
                  "dead", "wounded", "launche", "launch", "rocket", "ship", "vessel", "day",
                  "week", "month", "year", "time", "percent", "billion", "million",
                  "trillion", "won", "dollar", "seat", "vote", "citizen", "prisoner", "pow",
                  "defector", "worker", "casualtie", "death", "warhead", "test", "drill",
                  "minister", "official", "aircraft", "plane", "drone", "shell", "round",
                  "mile", "kilometer", "hour", "point", "satellites", "civilian", "sailor",
                  "fisherman", "fishermen", "person", "men", "women", "children", "member"}
# Counting what the brief itself lists ("two countries", "three major items")
# is arithmetic on the brief, not a new fact; a small count before one of
# these nouns is not checked. Counts of people, days or weapons still are.
_COUNT_NOUNS = {"countrie", "side", "message", "statement", "item", "storie", "thing",
                "branche", "capital", "leader", "government", "signal", "track",
                "partner", "allie", "development", "headline", "article", "piece",
                "part", "way", "reason", "question", "front", "story", "country", "audience"}
# "the two agreed", "presenting the two as" — "two" standing for people or
# things already named, not a count.
_PRONOUN_NEXT = {"as", "agreed", "of", "have", "are", "were", "had", "met", "said", "will",
                 "would", "to", "in", "on", "at", "and", "also", "both", "spoke", "discussed"}
_MARKET_WORDS = {"kospi", "won", "dollar", "dollars", "brent", "crude", "barrel", "percent",
                 "rate", "index", "points"}
_MONTH_TOKENS = {"jan": "january", "feb": "february", "mar": "march", "apr": "april",
                 "jun": "june", "jul": "july", "aug": "august", "sep": "september",
                 "sept": "september", "oct": "october", "nov": "november", "dec": "december"}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(text).lower().replace(",", ""))


_NUMBER_WORDS = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
_NUMBER_WORDS.update({"thirty": "30", "forty": "40", "fifty": "50", "sixty": "60",
                      "seventy": "70", "eighty": "80", "ninety": "90", "hundred": "100"})


_SCALES = {"hundred": 100, "thousand": 1000}


def _tokens(text: str) -> list[str]:
    """Lower-case word tokens, spelled-out numbers turned into digits.

    Compounds are joined, so "one thousand trillion" matches "1,000 trillion"
    and "twenty five" matches "25". A bare "one" stays a word: it is a pronoun
    ("the one overseen by", "the big one") far more often than a count.
    """
    raw = re.findall(r"\d+(?:\.\d+)?|[a-z]+", str(text).lower().replace(",", ""))
    out: list[str] = []
    tens = {"twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"}
    last = ""
    for t in raw:
        prev = out[-1] if out else ""
        if t == "one" and last not in tens:
            out.append(t)
        elif t in _SCALES and (prev.isdigit() or prev == "one"):
            out[-1] = str(int(float(prev if prev != "one" else 1) * _SCALES[t]))
        elif last in tens and t in _NUMBER_WORDS and 1 <= int(_NUMBER_WORDS[t]) <= 9:
            out[-1] = str(int(prev) + int(_NUMBER_WORDS[t]))
        else:
            out.append(_MONTH_TOKENS.get(t) or _NUMBER_WORDS.get(t, t))
        last = t
    return out


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w


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
    near = {_stem(w) for w in content(script_toks[max(0, at - 6):at])[-2:]
            + content(script_toks[at + 1:at + 6])[:2]}
    places = src_pos.get(n, [])
    if not near:
        return bool(places)
    return any(near & {_stem(w) for w in src_toks[max(0, i - 5):i + 6]} for i in places)


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
            # Spoken figures are rounded: 1,338.38 is "1,338 won", 1.98 is
            # "almost 2 percent". The rounded forms still need their context.
            if "." in t:
                v = float(t)
                for r in {str(int(v)), str(round(v))}:
                    src_pos.setdefault(r, []).append(i)
    # The opening and closing lines carry the date and are fixed text, checked
    # separately. They are removed here rather than exempting the date's
    # numbers everywhere: a global exemption for "7" let "seven soldiers"
    # through on 7 October against a brief that says three.
    body = re.sub(r"^\s*---\s*$", " ", script, flags=re.M)
    for fixed in (f"This is the Korea Daily Brief from the CSIS Korea Chair. It's {when}.",
                  f"That's the Korea Daily Brief for {when}."):
        body = body.replace(fixed, " ")
    # "the last 24 hours" is the brief's own window, not a claim from it.
    body = re.sub(r"\b(?:24|twenty-? ?four)[- ]hours?\b", " ", body, flags=re.I)
    # The menu line the prompt asks for ("Three things today") counts stories, not facts.
    body = re.sub(r"\b(?:two|three|four|five|\d) (?:things|stories|big stories)\b", " ", body, flags=re.I)
    s_toks = _tokens(body)
    # Market figures sit in the brief as bare fields ({"value": "1,338.38"}),
    # with no words around them to match, so they are matched by value,
    # rounded as a voice says them, and only beside a market word.
    market = set()
    for v in (digest.get("market_indicators") or {}).values():
        if isinstance(v, dict):
            for x in (v.get("value"), v.get("change_pct")):
                try:
                    f = abs(float(str(x).replace(",", "").rstrip("%")))
                except (TypeError, ValueError):
                    continue
                market |= {str(int(f)), str(round(f)), f"{f:g}", f"{f:.2f}", f"{f:.1f}"}
    for i, t in enumerate(s_toks):
        if t in market and _MARKET_WORDS & set(s_toks[max(0, i - 4):i + 4]):
            continue
        # Small counts ("the two", "two escalatory moves", "three things")
        # are how speech refers back to what it just said. They are checked
        # only when they count something a misstatement would matter for.
        if t in {"2", "3", "4", "5"} and not any(_stem(w) in _COUNTED_FACTS for w in s_toks[i + 1:i + 4]):
            continue
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
            # "U.S.-ROK": a compound of names each allowed or in the brief.
            if "-" in core and all(x in _ALLOWED_CAPS or not x[:1].isupper()
                                   or f" {_norm(x).strip()} " in f" {' '.join(blob.split())} "
                                   for x in core.split("-") if x):
                continue
            # Hyphens and dots are spaces in the normalised brief: "Dong-young"
            # is "dong young" there, "U.S" is "u s".
            if f" {_norm(core).strip()} " not in f" {' '.join(blob.split())} ":
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
        client = anthropic.Anthropic(api_key=key)
        convo = [{"role": "user", "content":
                  "Here is today's brief as JSON. Write the audio script.\n\n"
                  + json.dumps(payload, ensure_ascii=False)}]

        def _ask() -> str:
            msg = client.messages.create(model=model, max_tokens=4000,
                                         system=_SCRIPT_SYSTEM.replace("{when}", when),
                                         messages=convo)
            return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()

        text = _ask()
        # One revision round. A single misquote or misread figure used to
        # cost the whole script; now the writer is shown exactly what the
        # check found and fixes only that, and the result is checked again
        # from scratch — the revision earns no trust the first draft lacked.
        first = check_script(text, digest, when)
        if first:
            convo += [{"role": "assistant", "content": text},
                      {"role": "user", "content":
                       "A fact check against the brief found these problems:\n- "
                       + "\n- ".join(first[:30])
                       + "\n\nFix only those lines: use the brief's exact figure, quote the "
                         "brief word for word or paraphrase without quotation marks, or "
                         "drop the claim. Keep everything else as it is. Return the whole "
                         "script and nothing else."}]
            text = _ask()
    except Exception as e:                                      # noqa: BLE001
        return None, [f"script call failed: {e}"]
    opening = f"This is the Korea Daily Brief from the CSIS Korea Chair. It's {when}."
    if not text.startswith(opening[:40]):
        return None, ["the script did not open with the show's opening line"]
    problems = check_script(text, digest, when)
    if problems:
        return None, problems
    text = re.sub(r"^\s*-{3,}\s*$", f"\n{SEGMENT}\n", text, flags=re.M)
    paras = [x.strip() if x.strip() == SEGMENT else speakable(x)
             for x in re.split(r"\n\s*\n", text) if x.strip()]
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


def _chunks(script: str, limit: int = CHUNK_CHARS) -> list[tuple[str, float]]:
    """Pack paragraphs into requests, kept small on purpose, each with the pause after it.

    The first live episode sent three requests of up to 3,500 characters and
    came back a third short: the voice model can stop early on a long passage
    and still return a well-formed file. Requests of about a paragraph each
    make a skip both less likely and, when it happens, cheap to redo.

    Breaks on paragraph boundaries first, then sentence boundaries for a
    paragraph too long alone, so no request ends mid-sentence. A request never
    spans a segment break (a line holding only ---): the pause there is
    silence the producer inserts, longer than the one between paragraphs.
    """
    out: list[tuple[str, float]] = []
    for segment in re.split(rf"\n\s*{re.escape(SEGMENT)}\s*\n", "\n" + script.strip() + "\n"):
        cur = ""
        for para in [x.strip() for x in segment.split("\n\n") if x.strip() and x.strip() != SEGMENT]:
            pieces = [para] if len(para) <= limit else re.split(r"(?<=[.!?])\s+", para)
            for piece in pieces:
                if len(cur) + len(piece) + 2 > limit and cur:
                    out.append((cur, PAUSE_PARAGRAPH))
                    cur = piece
                else:
                    cur = f"{cur}\n\n{piece}" if cur else piece
        if cur:
            out.append((cur, PAUSE_SEGMENT))
    return out


def spoken_text(script: str) -> str:
    """The script without segment markers: what the transcript shows."""
    return re.sub(rf"\n*^\s*{re.escape(SEGMENT)}\s*$\n*", "\n\n", script, flags=re.M).strip()


def _eleven_tts(text: str, key: str, voice_id: str, model: str,
                previous: list[str]) -> tuple[bytes, str]:
    """One ElevenLabs request. Returns (mp3, request id).

    previous_request_ids stitches this request to the audio of the ones before
    it, so tone and energy carry on instead of resetting every paragraph —
    the main thing OpenAI's stateless requests could not do.
    """
    import requests
    body = {"text": text, "model_id": model,
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.2,
                               "use_speaker_boost": True, "speed": ELEVEN_SPEED}}
    if previous:
        body["previous_request_ids"] = previous[-3:]
    r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                      params={"output_format": "mp3_44100_128"},
                      headers={"xi-api-key": key, "Content-Type": "application/json"},
                      json=body, timeout=300)
    if r.status_code >= 400:
        try:
            d = r.json().get("detail")
            detail = d.get("message", str(d)) if isinstance(d, dict) else str(d)
        except ValueError:
            detail = r.text[:300]
        raise RuntimeError(f"ElevenLabs returned {r.status_code}: {detail}".strip())
    return r.content, r.headers.get("request-id", "")


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


def _sting(rate: int = PCM_RATE) -> "array":
    """A short, quiet signature for the open and close, synthesised here.

    Generated rather than downloaded so there is no licence to track: a soft
    D-major pad under two bell notes, about three and a half seconds. A file
    at assets/sting.mp3 (or STING_FILE) replaces it — a licensed track, if the
    show ever wants one.
    """
    import math
    from array import array
    n = int(3.6 * rate)
    pad = (146.83, 220.0, 293.66, 369.99, 329.63)        # D3 A3 D4 F#4 E4
    bells = ((0.00, 587.33), (0.32, 880.0))              # D5, then A5
    out = array("h", bytes(2 * n))
    for i in range(n):
        t = i / rate
        env = min(1.0, t / 0.5) * (1.0 if t < 2.2 else max(0.0, 1 - (t - 2.2) / 1.4))
        v = env * sum(math.sin(2 * math.pi * f * t) for f in pad) / len(pad) * 0.55
        for start, f in bells:
            if t >= start:
                d = t - start
                v += 0.35 * math.exp(-d * 2.2) * (math.sin(2 * math.pi * f * d)
                                                 + 0.3 * math.sin(4 * math.pi * f * d))
        out[i] = int(max(-1.0, min(1.0, v * 0.42)) * 32767)
    return out


def _ffmpeg() -> str | None:
    """ffmpeg on PATH, else the static build the imageio-ffmpeg wheel carries.

    The workflows install it from PyPI, not apt: apt-get on the runner hung
    for the job's whole 15 minutes on 7 October, twice. A wheel is one
    download from a cache that does not stall.
    """
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:                                           # noqa: BLE001
        return None


def _pcm(data: bytes | Path) -> bytes:
    """Any audio ffmpeg reads, as 16-bit mono PCM at PCM_RATE."""
    src = ["-i", str(data)] if isinstance(data, Path) else ["-i", "pipe:0"]
    r = subprocess.run([_ffmpeg(), "-loglevel", "error", *src, "-f", "s16le", "-ac", "1",
                        "-ar", str(PCM_RATE), "pipe:1"],
                       input=None if isinstance(data, Path) else data, capture_output=True)
    if r.returncode:
        raise RuntimeError(f"ffmpeg could not decode audio: {r.stderr.decode()[:200]}")
    return r.stdout


def _pace(default: float) -> float:
    """TTS_PACE if set, else the voice's default, kept to a range that sounds natural."""
    try:
        pace = float((os.environ.get("TTS_PACE") or "").strip() or default)
    except ValueError:
        pace = default
    return min(1.2, max(0.75, pace))


def _pace_filter(pace: float = 1.0) -> str:
    """atempo for the pace: slower speech at the same pitch."""
    return "" if abs(pace - 1.0) < 0.005 else f"atempo={pace:g},"


def _master(parts: list[tuple[bytes, float]], out_path: Path, pace: float = 1.0) -> None:
    """The finished episode: sting, voice with real pauses, sting, at podcast loudness.

    Pauses are silence put in here, not asked of the voice: break tags are
    unreliable across voice models, and a request that ends a segment and the
    one that starts the next are separate calls anyway. The voice comes in
    over the tail of the opening sting. The whole mix is normalised to
    -16 LUFS, the level Apple Podcasts and most players expect, so the
    episode is neither quiet beside other shows nor uneven within itself.

    Without ffmpeg (a local run) the chunks are simply concatenated: MP3 is a
    stream of independent frames, so that plays everywhere.
    """
    if not _ffmpeg():
        out_path.write_bytes(b"".join(p for p, _ in parts))
        return
    from array import array
    voice = array("h")
    for i, (part, pause) in enumerate(parts):
        voice.frombytes(_pcm(part))
        if i < len(parts) - 1:
            voice.frombytes(bytes(2 * int(pause * PCM_RATE)))
    custom = Path(os.environ.get("STING_FILE") or Path(__file__).with_name("assets") / "sting.mp3")
    sting = array("h", _pcm(custom)) if custom.exists() else _sting()
    # The voice enters as the sting fades: 1.2 s of overlap, mixed with clipping.
    overlap = min(int(1.2 * PCM_RATE), len(sting), len(voice))
    mix = array("h", sting[:len(sting) - overlap])
    for a, b in zip(sting[len(sting) - overlap:], voice[:overlap]):
        mix.append(max(-32768, min(32767, int(a * 0.6) + b)))
    mix.extend(voice[overlap:])
    mix.frombytes(bytes(2 * int(0.7 * PCM_RATE)))
    mix.extend(sting)
    r = subprocess.run(
        [_ffmpeg(), "-loglevel", "error", "-y", "-f", "s16le", "-ar", str(PCM_RATE), "-ac", "1",
         "-i", "pipe:0", "-af", _pace_filter(pace) + "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", "-ac", "1",
         "-b:a", "64k", str(out_path)],
        input=mix.tobytes(), capture_output=True)
    if r.returncode or not out_path.exists() or not out_path.stat().st_size:
        raise RuntimeError(f"ffmpeg could not master the episode: {r.stderr.decode()[:200]}")


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
    if not script.strip():
        return None
    eleven_key = (os.environ.get("ELEVENLABS_API_KEY") or "").strip()
    eleven_voice = (os.environ.get("ELEVENLABS_VOICE_ID") or "").strip() or DEFAULT_ELEVEN_VOICE
    if eleven_key and eleven_voice:
        rec = _synthesize_eleven(script, out_path, eleven_key, eleven_voice)
        if rec:
            return rec
        if not (os.environ.get("OPENAI_API_KEY") or "").strip():
            return None
        print(f"::warning title=ElevenLabs failed, used OpenAI::{LAST_ERROR}")
    elif eleven_key:
        print("::warning title=No ElevenLabs voice set::add the repository variable "
              "ELEVENLABS_VOICE_ID (run Voice audition to choose one); using OpenAI")
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        return None
    model = (os.environ.get("TTS_MODEL") or "").strip() or DEFAULT_MODEL
    voice = (os.environ.get("TTS_VOICE") or "").strip() or DEFAULT_VOICE

    def _tts(text: str) -> bytes:
        nonlocal voice
        try:
            return _openai_tts(text, key, model, voice)
        except RuntimeError as e:
            # A model that does not offer the default voice says so with a
            # 400; better the previous voice than no episode.
            if voice == DEFAULT_VOICE and "400" in str(e) and "voice" in str(e).lower():
                print(f"::warning title=Voice unavailable::{voice} refused; using {FALLBACK_VOICE}")
                voice = FALLBACK_VOICE
                return _openai_tts(text, key, model, voice)
            raise

    def _voiced(text: str) -> bytes:
        """One request, checked. Retried once, then sentence by sentence, if short."""
        want = _expected_seconds(text)
        audio = _tts(text)
        if want < 4 or mp3_seconds(audio) >= MIN_COVERAGE * want:
            return audio
        audio = _tts(text)
        if mp3_seconds(audio) >= MIN_COVERAGE * want:
            return audio
        sentences = [x for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()]
        if len(sentences) < 2:
            return audio
        return b"".join(_tts(x) for x in sentences)

    try:
        parts = [(_voiced(c), pause) for c, pause in _chunks(script)]
        return _finish(parts, script, out_path,
                       {"tts_provider": "openai", "tts_model": model, "tts_voice": voice},
                       pace=_pace(default=DEFAULT_PACE))
    except Exception as e:                                      # noqa: BLE001
        LAST_ERROR = str(e)
        # An annotation, not only a log line: GitHub serves job logs from a
        # separate host, while annotations are readable through the API, so
        # the reason a run produced no audio can be read back without the log.
        print(f"::warning title=Audio skipped::{e}")
        print(f"  ⚠  Audio skipped (non-fatal): {e}")
        return None


def _finish(parts: list[tuple[bytes, float]], script: str, out_path: Path,
            who: dict, pace: float) -> dict | None:
    """Master the voiced parts and check nothing went missing. Shared by both voices."""
    global LAST_ERROR
    voiced_seconds = sum(mp3_seconds(p) for p, _ in parts)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _master(parts, out_path, pace)
    got = mp3_seconds(out_path.read_bytes())
    want = _expected_seconds(spoken_text(script))
    # Coverage is judged on the voice alone: the stings and pauses would
    # otherwise hide a quarter of the brief gone missing.
    if voiced_seconds < PUBLISH_COVERAGE * want:
        # A short episode is worse than none: it reads as the day's brief and
        # silently leaves part of it out. Not published, and the reason is
        # said where it can be read.
        LAST_ERROR = (f"the voice is {voiced_seconds:.0f} s but the script needs about "
                      f"{want:.0f} s — the voice skipped part of the brief, so "
                      f"the episode was not published")
        print(f"::warning title=Audio incomplete::{LAST_ERROR}")
        out_path.unlink(missing_ok=True)
        return None
    return {**who, "tts_chars": len(script), "audio_bytes": out_path.stat().st_size,
            "audio_seconds": int(got), "audio_expected_seconds": int(want)}


def _synthesize_eleven(script: str, out_path: Path, key: str, voice_id: str) -> dict | None:
    """The episode in an ElevenLabs voice, stitched request to request."""
    global LAST_ERROR
    wanted = (os.environ.get("ELEVENLABS_MODEL") or "").strip()
    models = [wanted] if wanted else list(ELEVEN_MODELS)
    previous: list[str] = []

    def _tts(text: str) -> bytes:
        nonlocal previous
        while True:
            try:
                audio, rid = _eleven_tts(text, key, voice_id, models[0], previous)
            except RuntimeError as e:
                msg = str(e).lower()
                # A model this account or voice can't use: try the next one.
                if len(models) > 1 and ("model" in msg) and ("400" in msg or "404" in msg or "422" in msg):
                    print(f"  ⚠  {models[0]} unavailable; trying {models[1]}")
                    models.pop(0)
                    previous = []
                    continue
                # A model that can't stitch: carry on without it.
                if previous and "previous" in msg:
                    previous = []
                    continue
                raise
            if rid:
                previous.append(rid)
            return audio

    def _voiced(text: str) -> bytes:
        want = _expected_seconds(text)
        audio = _tts(text)
        if want < 4 or mp3_seconds(audio) >= MIN_COVERAGE * want:
            return audio
        return _tts(text)

    try:
        parts = [(_voiced(c), pause) for c, pause in _chunks(script, ELEVEN_CHUNK_CHARS)]
        return _finish(parts, script, out_path,
                       {"tts_provider": "elevenlabs", "tts_model": models[0], "tts_voice": voice_id},
                       pace=_pace(default=1.0))
    except Exception as e:                                      # noqa: BLE001
        LAST_ERROR = str(e)
        print(f"::warning title=ElevenLabs audio failed::{e}")
        return None


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
    (public / f"digest_{date_slug}.txt").write_text(spoken_text(script), encoding="utf-8")
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
            "script": source,
            # Every reason, not the four an annotation shows, so a rejected
            # rewrite can be diagnosed without the run log.
            **({"script_rejected": why[:40]} if source == "assembled" and why else {}),
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
        if LAST_ERROR and "ElevenLabs" in LAST_ERROR:
            why = LAST_ERROR + (" — check the ELEVENLABS_API_KEY secret and the "
                                "ELEVENLABS_VOICE_ID variable")
        elif not (os.environ.get("OPENAI_API_KEY") or "").strip():
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
