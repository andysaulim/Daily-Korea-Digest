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
    ELEVENLABS_API_KEY   enables synthesis (voice: DEFAULT_ELEVEN_VOICE, or ELEVENLABS_VOICE_ID)
    OPENAI_API_KEY       not used unless TTS_PROVIDER=openai is set deliberately
    PODCAST_OP3          download counting via op3.dev on enclosures; on unless 0/false/off

Around each MP3, listen.py publishes chapters (JSON and ID3), a VTT
transcript, show notes and the player page the email's Listen bar opens.
    TTS_MODEL        default gpt-4o-mini-tts
    TTS_VOICE        default ash
    TTS_STYLE        how the voice reads; default is a conversational podcast host
"""
from __future__ import annotations

import html as _html
import json
import unicodedata
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
# Pauses are exact: each request's own leading and trailing silence is
# trimmed in _master before these are put in. Before that trim, a voice's
# ~0.3 s of padding at each end turned a 1.5 s segment break into about two
# seconds of dead air, fifteen times an episode. Radio leaves about a second
# between stories when there is no music to fill it.
PAUSE_PARAGRAPH = 0.6            # seconds of silence between requests within a segment
PAUSE_SEGMENT = 1.2              # ... and between segments
EDGE_SILENCE = 0.08              # kept at each end of a request when trimming
SILENCE_LEVEL = 330              # |sample| below this (about -40 dBFS) counts as silence
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
# ElevenLabs is the only voice in normal use (see synthesize). Models are tried
# in order until one is accepted.
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
# The AI disclosure. Printed in the feed and on the player page; the spoken
# form is a short phrase inside the fixed opening line, so a listener hears it
# in the first five seconds without a disclaimer read at them.
DISCLOSURE = ("This is an AI-narrated edition of today's Korea Daily Brief "
              "from the CSIS Korea Chair.")
SPOKEN_DISCLOSURE = "read by an AI voice"


def opening_line(when: str) -> str:
    """The fixed first line of every script: the show, the disclosure, the date."""
    return f"This is the Korea Daily Brief from the CSIS Korea Chair, {SPOKEN_DISCLOSURE}. It's {when}."


def _legacy_opening(when: str) -> str:
    """The opening before the disclosure was added; a writer may still produce it."""
    return f"This is the Korea Daily Brief from the CSIS Korea Chair. It's {when}."

# ── Making text speakable ────────────────────────────────────────────────────
#
# The house rules for what a voice is sent. Everything here changes how a
# sentence is written, never what it says; check_script compares a script
# against the brief passed through the same rules, so a figure written "$84.7B"
# in print and "84.7 billion dollars" on air is the same figure to the check.
#
#   Numbers      digits, as printed; "%" is "percent"; "-7.6%" is "down 7.6 percent"
#   Money        "$84.7B" and "$84.7 billion" are "84.7 billion dollars"; "₩" and
#                KRW are "won"; "~" is "about"
#   Dates        month names in full ("Oct 3" is "October 3"); ranges with "to"
#                ("Oct 13-15" is "October 13 to 15"); "Q3" is "the third quarter"
#   Acronyms     a listener decodes country and institution acronyms worse than
#                a reader, so they are expanded (DPRK, ROK, USFK, UNC, IAEA, NDAA,
#                CRS, OPCON, BOK...). Those said as a word or as letters by
#                everyone in the field stay: KCNA, DMZ, KOSPI, MASGA, CSIS, AI.
#                "US" and "UN" gain their dots so no voice says "us" or "un".
#   Characters   no em dash, middle dot, arrow, bracket, slash, asterisk, URL,
#                handle or Korean script reaches the voice or the transcript.
#
# Pronunciation is handled by respelling in for_voice(), never by markup: the
# eleven_v3 family ignores SSML <phoneme> tags, and an unsupported tag is read
# aloud or dropped unpredictably. The transcript keeps the standard spelling.

_HANGUL = re.compile(r"[ᄀ-ᇿ㄰-㆏가-힣]+")
_URL = re.compile(r"https?://\S+|\bwww\.\S+")
_MONEY = re.compile(r"(?:US)?\$\s?(\d[\d,]*(?:\.\d+)?)\s?(tn|T|bn|B|mn|M|K|k|trillion|billion|million)\b")
_DOLLARS = re.compile(r"(?:US)?\$\s?(\d[\d,]*(?:\.\d+)?)(?![\d.,]*\s?(?:tn|T|bn|B|mn|M|K|k|trillion|billion|million)\b)")
_UNITS = {"tn": "trillion", "t": "trillion", "bn": "billion", "b": "billion",
          "mn": "million", "m": "million", "k": "thousand",
          "trillion": "trillion", "billion": "billion", "million": "million"}
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
    # Added after reading five issues aloud: "South Korea sovereignty",
    # "the sixth North Korea weapons event", "North Korea soldier".
    "sovereignty", "territorial", "weapon", "weapons", "soldier", "testing",
    "provocation", "provocations",
    "response", "position", "policy", "officer", "officers", "diplomat",
    "diplomats", "lawmakers", "voters", "public", "nationals", "ambassador",
    "artillery", "submarine", "submarines", "torpedo", "cyber", "hacking",
    "laborers", "labourers", "restaurant", "refugees", "multilateral",
    "microsatellite", "satellite", "satellites", "economic", "business",
    "businesses", "industry", "industries", "shipbuilders", "shipyards",
    "chipmakers", "automakers", "investors", "investment", "stocks",
    "currency", "trade", "steel", "auto", "autos", "semiconductor",
}


_NOUN_NEXT = {"and", "or", "but", "has", "is", "was", "will", "would", "can", "could", "may",
              "must", "should", "did", "does", "do", "had", "have", "are", "were", "itself",
              "ties", "relations", "alone", "also", "first", "now", "again", "still", "says",
              "said", "say", "agree", "agreed", "sign", "signed", "hold", "held", "plans"}


def _country(text: str, abbr: str, noun: str, adjective: str) -> str:
    """ROK -> "South Korea" or "South Korean", by the word that follows.

    The adjective before a noun ("ROK sovereignty", "ROK Finance Minister"),
    the noun before a verb, a preposition or punctuation ("DPRK rejects",
    "ties with the ROK."). A third-person verb ends in -s or -ed; a plural
    noun that also does is listed in _ADJ_BEFORE.
    """
    def repl(m: re.Match) -> str:
        nxt = (m.group(1) or "").strip()
        w = nxt.lower().split("'")[0].split("’")[0]
        if not w:
            adj = False
        elif w in _ADJ_BEFORE:
            adj = True
        elif nxt[:1].isupper():
            adj = True                                          # "ROK Defense Ministry"
        elif w in _NOT_A_NOUN or w in _NOUN_NEXT or w.endswith("ed") or w.isdigit() \
                or (w.endswith("s") and not w.endswith("ss")):
            adj = False
        else:
            adj = True                                          # "ROK democratization movements"
        return (adjective if adj else noun) + (m.group(1) or "")
    return re.sub(rf"\b{abbr}\b(\s+[\w'’]+|(?=[^\w]|$))", repl, text)


_NOT_A_NOUN = {"in", "to", "of", "for", "and", "or", "a", "an", "the", "on",
               "over", "by", "from", "with", "per", "at", "as", "this", "last",
               "next", "is", "was", "will", "would", "through", "since", "into",
               "annually", "a", "each", "this", "that", "until", "by", "between"}
_DETERMINERS = {"a", "an", "the", "its", "their", "his", "her", "our", "this", "that",
                "each", "every", "another", "seoul's", "korea's", "washington's",
                "tokyo's", "beijing's", "pyongyang's"}


_MONTH_NAMES = {"Jan": "January", "Feb": "February", "Mar": "March", "Apr": "April",
           "Jun": "June", "Jul": "July", "Aug": "August", "Sep": "September",
           "Oct": "October", "Nov": "November", "Dec": "December"}
_MONTH_ABBR = r"(Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)"
_ORDINAL = {"1": "first", "2": "second", "3": "third", "4": "fourth"}
# Acronyms a reader decodes and a listener can't: (pattern, singular, plural).
# Applied after the country and institution expansions, longest first where
# one is a prefix of another (NK Pro before NK).
_SPOKEN_NAMES = (("MOFA", "Foreign Ministry", None), ("MOTIE", "Industry Ministry", None),
                 ("MND", "Defense Ministry", None), ("MOEF", "Finance Ministry", None),
                 ("MDL", "military demarcation line", None),
                 ("NK Pro", "N.K. Pro", None), ("NK News", "N.K. News", None),
                 ("Daily NK", "Daily N.K.", None),
                 ("IRBM", "intermediate-range missile", "intermediate-range missiles"),
                 ("ICBM", "intercontinental ballistic missile", "intercontinental ballistic missiles"),
                 ("SLBM", "submarine-launched ballistic missile", "submarine-launched ballistic missiles"),
                 ("SLCM", "submarine-launched cruise missile", "submarine-launched cruise missiles"),
                 ("SRBM", "short-range ballistic missile", "short-range ballistic missiles"),
                 ("HGV", "hypersonic glide vehicle", "hypersonic glide vehicles"),
                 ("LNG", "liquefied natural gas", None),
                 ("POW", "prisoner of war", "prisoners of war"),
                 ("KBO", "Korean baseball", None), ("IPs", "internet addresses", None),
                 ("OPCON", "wartime operational control", None),
                 ("FT", "the Financial Times", None), ("WSJ", "the Wall Street Journal", None),
                 ("NYT", "the New York Times", None), ("WaPo", "the Washington Post", None),
                 ("DP", "Democratic Party", None), ("PPP", "People Power Party", None),
                 ("LDP", "Liberal Democratic Party", None), ("CCP", "Chinese Communist Party", None),
                 ("WPK", "Workers' Party", None), ("CoS", "chief of staff", None),
                 ("WB", "World Bank", None), ("IT", "I.T.", None),
                 ("LOI", "letter of intent", "letters of intent"),
                 ("MOU", "memorandum of understanding", "memorandums of understanding"),
                 ("FY", "fiscal", None), ("YoY", "year on year", None), ("yoy", "year on year", None))
# Institutions: the expansion takes "the" where English needs it ("UNC said"
# is "the U.N. Command said"; "UNC authority" stays "U.N. Command authority").
_INSTITUTIONS = (("USFK", "U.S. Forces Korea", False), ("UNC", "U.N. Command", True),
                 ("UNSC", "U.N. Security Council", True), ("CFC", "Combined Forces Command", True),
                 ("JCS", "Joint Chiefs of Staff", True), ("IAEA", "International Atomic Energy Agency", True),
                 ("NDAA", "National Defense Authorization Act", True),
                 ("CRS", "Congressional Research Service", True),
                 ("BOK", "Bank of Korea", True), ("KRX", "Korea Exchange", True),
                 ("DOJ", "Justice Department", True), ("NIS", "National Intelligence Service", True),
                 ("FSS", "Financial Supervisory Service", True), ("FSC", "Financial Services Commission", True),
                 ("DAPA", "Defense Acquisition Program Administration", True),
                 ("JSA", "Joint Security Area", True), ("NLL", "Northern Limit Line", True),
                 ("NSC", "National Security Council", True), ("KDI", "Korea Development Institute", True),
                 ("USTR", "U.S. Trade Representative", True), ("OFAC", "Treasury's sanctions office", False))
_ARTICLE_BEFORE = re.compile(r"\b(?:the|a|an|its|their|his|her)\s+$", re.I)
_PREP_BEFORE = re.compile(r"\b(?:by|of|from|to|at|with|for|in|on|and|or|under|between|against|told|"
                          r"says|said|urged|asked|warned|that|as|via|before|after|toward|towards|"
                          r"within|across|without)\s+$", re.I)
_VERB_AFTER = re.compile(r"^(?:'s\s+)?\s*(?:[a-z]+ly\s+)?(?:is|was|has|had|have|are|were|will|would|said|says|could|can|"
                         r"may|must|should|did|does|[a-z]+ed)\b")
_TITLES = (("Lt. Gen.", "Lieutenant General"), ("Maj. Gen.", "Major General"),
           ("Brig. Gen.", "Brigadier General"), ("Gen.", "General"), ("Adm.", "Admiral"),
           ("Rep.", "Representative"), ("Sen.", "Senator"), ("Gov.", "Governor"),
           ("Amb.", "Ambassador"), ("Col.", "Colonel"), ("Lt.", "Lieutenant"))
_DAY_ABBR = {"Tue": "Tuesday", "Tues": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday",
             "Thur": "Thursday", "Thurs": "Thursday"}


def _institution(text: str, abbr: str, name: str, article: bool) -> str:
    def repl(m: re.Match) -> str:
        before, after = m.string[:m.start()], m.string[m.end():]
        if not article or _ARTICLE_BEFORE.search(before):
            return name
        if not before.strip() or before.rstrip()[-1] in ".!?\"“":
            return "The " + name
        if before.rstrip()[-1] in ":;":
            return "the " + name
        if _PREP_BEFORE.search(before) or _VERB_AFTER.match(after):
            return "the " + name
        return name
    return re.sub(rf"\b{abbr}\b", repl, text)


def _money(m: re.Match) -> str:
    """$22.3B -> "22.3 billion dollars", or "dollar" when it modifies a noun.

    It modifies a noun when a noun follows it: "a $350B
    pledge", "the $150B shipbuilding component", "extend $10B currency swap".
    Before a verb or a preposition it is an amount ("totaling $49.9B announced
    in October"), which the first version read as "49.9 billion dollar announced".
    """
    amount = m.group(1)
    unit = _UNITS[m.group(2).lower()] if m.lastindex and m.lastindex >= 2 and m.group(2) else ""
    before = [w.lower().strip(",") for w in m.string[:m.start()].split()[-3:]]
    nxt = re.match(r"\s+([A-Za-z][\w-]*)", m.string[m.end():])
    det = -1
    for i, w in enumerate(before):
        if w in _DETERMINERS or w.endswith(("'s", "’s")):
            det = i
    np_ok = det >= 0 and not any(w in _NOT_A_NOUN or w.endswith("ed") for w in before[det + 1:])
    word = nxt.group(1) if nxt else ""
    noun_next = (bool(word) and word.lower() not in _NOT_A_NOUN | {"up", "down", "last", "more", "less"}
                 and not word.endswith(("ed", "ing", "ly")))
    # A lower-case noun straight after the amount is what it modifies
    # ("extend $10B currency swap"); after a determiner a capitalised one too.
    as_adjective = noun_next and (word[:1].islower() or np_ok)
    if not unit and amount.replace(",", "") in ("1", "1.0", "1.00"):
        return "1 dollar"
    return f"{amount} {unit + ' ' if unit else ''}dollar{'' if as_adjective else 's'}"


_SENT_ABBR = re.compile(r"(?:\b(?:U\.S|U\.N|U\.K|N\.K|I\.T|a\.m|p\.m|Gen|Lt|Col|Adm|Rep|Sen|Gov|Amb|Dr|Mr|"
                        r"Ms|Mrs|St|No|Jr|Sr|vs|etc|Inc|Corp|Co|e\.g|i\.e|Jan|Feb|Mar|Apr|Jun|Jul|"
                        r"Aug|Sept?|Oct|Nov|Dec)\.|\b[A-Z]\.)$")


def _sentences(text: str) -> list[str]:
    """Split prose into sentences without breaking at "U.S." or "Gen."."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“‘])|(?<=[.!?][\"'”’])\s+", str(text or "").strip())
    out: list[str] = []
    for p in parts:
        if not p:
            continue
        if out and _SENT_ABBR.search(out[-1]):
            out[-1] += " " + p
        else:
            out.append(p)
    return out


def _clip(text: str, max_words: int) -> str:
    """Whole sentences from the start, up to max_words; always at least one.

    Nothing is reworded: a long item loses its later sentences, so whatever is
    read is still the brief's own text.
    """
    out, n = [], 0
    for s in _sentences(text):
        w = len(s.split())
        if out and n + w > max_words:
            break
        out.append(s)
        n += w
    return " ".join(out)


def speakable(text: str) -> str:
    """Rewrite a printed sentence so a speech engine says it the way a reader means it.

    Only presentation changes — never wording or facts. See the house rules
    above. Markdown emphasis goes, because the engine would read the
    asterisks; Hangul goes, because an English voice mangles it and every
    Korean term in the brief is already given in English beside it.
    """
    if not text:
        return ""
    t = _html.unescape(str(text))
    t = _URL.sub("", t)
    t = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", t)
    t = _HANGUL.sub("", t)
    # A translated quote prints as "<Korean> ['<English>']": keep the English.
    t = re.sub(r"\[\s*['\"‘“]?([^\[\]]*?)['\"’”]?\s*\]", r"\1", t)
    t = re.sub(r"\(\s*[,;/·]+\s*", "(", t)            # "(중대범죄수사청 / SCIA)" -> "(SCIA)"
    t = re.sub(r"\s*[,;/·]+\s*\)", ")", t)
    t = re.sub(r"\(\s*[,;/·.]*\s*\)", "", t)          # parentheses Hangul left empty
    t = re.sub(r"^[\s.,;:]+", "", t)                    # punctuation Hangul left leading
    t = re.sub(r"\s*·\s*", ", ", t)
    t = re.sub(r"\b(20\d\d)-(\d\d)-(\d\d)\b",                         # ISO dates
               lambda m: (f"{datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))):%B} "
                          f"{int(m.group(3))}, {m.group(1)}") if 1 <= int(m.group(2)) <= 12
               and 1 <= int(m.group(3)) <= 31 else m.group(0), t)
    t = re.sub(r"\b(\d)\+(\d)\b", r"\1-plus-\2", t)                   # "2+2 talks"
    t = re.sub(r"\b(\d[\d,.]*)\+(?=\s|$|[,.;])", r"more than \1", t)       # "268+ events"
    # Dashes: an em dash or a spaced en dash between words is a comma to the
    # ear; an unspaced en dash between numbers is a range ("Oct 3–5").
    t = re.sub(r"\s*[—―]\s*|\s+–\s+|\s+--\s+", ", ", t)
    t = re.sub(rf"\b{_MONTH_ABBR}\.?\s*[–-]\s*(?=[A-Z])",
               lambda m: _MONTH_NAMES[m.group(1)[:3]] + " to ", t)                   # "Sep–October"
    t = re.sub(r"(\d)\s*[–−-]\s*(\d)", r"\1 to \2", t)                       # "Oct 3–5"
    t = t.replace("–", "-")
    # Symbols a voice reads literally, or skips.
    t = re.sub(r"\s*(?:→|->|⇒|➔)\s*", " to ", t)
    t = re.sub(r"[▲↑]\s*", "up ", t)
    t = re.sub(r"[▼↓]\s*", "down ", t)
    t = re.sub(r"(\d)\s?MWe\b", r"\1-megawatt", t)
    t = re.sub(r"\s?°\s?C\b", " degrees Celsius", t)
    t = t.replace("°", " degrees").replace("²", "-squared").replace("³", "-cubed")
    t = re.sub(r"[•►▶◆■□●○✓✔#]", " ", t)
    t = re.sub(r"\s*&\s*", " and ", t)
    t = re.sub(r"[~≈]\s*(?=\$?\d)", "about ", t)
    t = re.sub(r"(?<![\w.])\+\s?(\d[\d.,]*)\s?%", r"up \1 percent", t)
    t = re.sub(r"(?<![\w.])[-−]\s?(\d[\d.,]*)\s?%", r"down \1 percent", t)
    t = re.sub(r"(\d)\s?%", r"\1 percent", t)
    t = re.sub(r"(\d)\s?(?:pp|ppt|%p)\b", r"\1 percentage points", t)
    t = re.sub(r"(\d)\s?bps?\b", r"\1 basis points", t)
    t = _MONEY.sub(_money, t)
    t = _DOLLARS.sub(_money, t)
    t = re.sub(r"(?:₩|\bKRW)\s?(\d[\d,.]*(?:\s(?:thousand|million|billion|trillion))?)", r"\1 won", t)
    t = re.sub(r"(\d[\d,.]*(?:\s(?:thousand|million|billion|trillion))?)\s?KRW\b", r"\1 won", t)
    t = re.sub(r"(\d)\s?(am|pm|a\.m\.|p\.m\.)(?=[\s,.;]|$)",
               lambda m: f"{m.group(1)} {m.group(2)[0]}.m.", t)
    for short, full in _TITLES:
        t = re.sub(rf"(?<![\w.]){re.escape(short)}\s+(?=[A-Z])", full + " ", t)
    # A gloss in brackets that only repeats the acronym: "operational control
    # (OPCON)", "Korea Electric Power Corporation (KEPCO)". Read aloud it is
    # the same name twice.
    t = re.sub(r"\s*\((?:[A-Z]{2,7}s?|[A-Z][a-z]?[A-Z]{1,6})\)", "", t)
    t = re.sub(r"\bUS\b", "U.S.", t)
    t = re.sub(r"\bUN\b", "U.N.", t)
    t = re.sub(r"\bU\.S\.(?=[A-Za-z])", "U.S. ", t)
    t = re.sub(r"\bCommander,?\s+UNC/CFC/USFK\b", "The commander of U.S. Forces Korea", t)
    t = _country(t, "DPRK", "North Korea", "North Korean")
    t = _country(t, "ROK", "South Korea", "South Korean")
    for abbr, name, article in _INSTITUTIONS:
        t = _institution(t, abbr, name, article)
    # "the DPRK said" is English; "the North Korea said" is not. Drop the
    # article before the noun form only — "the North Korean side" keeps it.
    t = re.sub(r"\b[Tt]he ((?:North|South) Korea)\b(?!n)", r"\1", t)
    t = re.sub(r"\bFMs\b", "foreign ministers", t)
    t = re.sub(r"\bFM\b", "Foreign Minister", t)
    t = re.sub(r"\bPM\b", "Prime Minister", t)
    t = re.sub(r"\s+/\s+", " and ", t)                            # "NK News / NK Pro"
    t = re.sub(r"\bvs\.?(?=\s)", "versus", t)
    t = re.sub(r"\(?\b[A-Z]{3}\d{8,}\b\)?", "", t)                  # wire story IDs
    t = re.sub(r",?\s*@\w+\s*,?", " ", t)                              # social handles
    t = re.sub(rf"\b{_MONTH_ABBR}\.(?=\s+[A-Z])", lambda m: _MONTH_NAMES[m.group(1)[:3]] + ".", t)
    t = re.sub(rf"\b{_MONTH_ABBR}\.?(?=\s+\d|\s*[:;,]|\s*$|\s+20\d\d)",
               lambda m: _MONTH_NAMES[m.group(1)[:3]], t)
    t = re.sub(r"\b(Tues|Tue|Wed|Thurs|Thur|Thu)\b\.?", lambda m: _DAY_ABBR[m.group(1)], t)
    t = re.sub(r"\bQ([1-4])\s+(20\d\d)\b",
               lambda m: f"the {_ORDINAL[m.group(1)]} quarter of {m.group(2)}", t)
    def _quarter(m: re.Match) -> str:
        prev = (m.string[:m.start()].split() or [""])[-1].lower()
        nxt = re.match(r"\s([a-z]+)", m.string[m.end():])
        if nxt and nxt.group(1) not in _NOT_A_NOUN | {"up", "down", "when", "after", "before"}:
            return f"{_ORDINAL[m.group(1)]}-quarter"                 # "Q3 revenue"
        return ("" if prev == "the" else "the ") + f"{_ORDINAL[m.group(1)]} quarter"
    t = re.sub(r"\bQ([1-4])\b", _quarter, t)
    t = re.sub(r"\bthe the\b", "the", t)
    t = re.sub(r"\bFY\s?(20\d\d)\b", r"fiscal \1", t)
    t = re.sub(r"(\d)\s?km\b", r"\1 kilometers", t)
    t = re.sub(r"\b(\d+(?:\.\d+)?)x\b", r"\1 times", t)
    t = re.sub(r"(?<!Daily )\bNK\b(?! (?:News|Pro)\b)", "NK_", t)            # NK alone, after the names
    for short, full, plural in _SPOKEN_NAMES:
        if plural:
            t = re.sub(rf"\b{short}s\b", plural, t)
        t = re.sub(rf"\b{short}\b", full, t)
    t = _country(t.replace("NK_", "NK"), "NK", "North Korea", "North Korean")
    t = re.sub(r"(?<!\w)the the\b", "the", t, flags=re.I)
    t = re.sub(r"\b(of|from|to|by|at|in|with) [Tt]he (the Financial|the Wall|the New York|the Washington)", r"\1 \2", t)
    t = re.sub(r"\b([A-Za-z]+)/([A-Za-z]+)\b", r"\1 and \2", t)          # "Taiwan/Russia"
    t = t.replace("/", " ")
    t = re.sub(r"\s*\(([^()]{1,60})\)", r", \1,", t)                    # asides, not brackets
    t = re.sub(r"[()\[\]{}]", "", t)
    # Any symbol left (™, †, ★, emoji...) is dropped: a voice either names it
    # or stumbles. Currency signs were turned into words above.
    t = "".join(ch for ch in t if not unicodedata.category(ch).startswith("S") or ch in "'`^")
    t = re.sub(r",\s*([,.;:!?])", r"\1", t)
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
    # "an submarine-launched", "a intercontinental": articles fixed after expansion.
    t = re.sub(r"\b([Aa])n (?=(?:submarine|short-range|hypersonic|wartime|liquefied|prisoner|"
               r"military|Korean|Democratic|People|National|Joint|Bank|Combined|Justice)\b)", r"\1 ", t)
    t = re.sub(r"\b([Aa]) (?=(?:intermediate|intercontinental|internet|International|I\.T\.)\b)", r"\1n ", t)
    t = re.sub(r"\b(up|down) \1\b", r"\1", t)
    t = re.sub(r"(^|[.!?]\s+)(the|an?) ", lambda m: m.group(1) + m.group(2).capitalize() + " ", t)
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    t = re.sub(r"([,;:])(?=[A-Za-z])", r"\1 ", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    t = t.rstrip(",;: ")
    if t and (t[-1] not in ".?!\"'”’" or (t[-1] in "\"'”’" and t[-2:-1] not in ".?!,")):
        t += "."
    return t


# What only the voice hears. Respellings for names a voice is known to get
# wrong, applied to each request and never to the script, the transcript or
# the captions, which keep the standard romanization. Plain respelling rather
# than <phoneme> or alias tags, because eleven_v3 ignores those tags.
# All-caps words that are said as words, not letters, go in title case.
_SAY_AS = (("KOSPI", "Kospi"), ("KOSDAQ", "Kosdaq"), ("MASGA", "Masga"), ("KEPCO", "Kepco"),
           ("THAAD", "Thaad"), ("Choe", "Chweh"), ("Son Hui", "Son-hee"), ("Juche", "Joo-cheh"))


def for_voice(text: str) -> str:
    """A request's text as the voice should receive it: respellings applied."""
    t = text
    for word, said in _SAY_AS:
        t = re.sub(rf"\b{re.escape(word)}\b", said, t)
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


def _story(item: dict, body_key: str = "body", words: int | None = None) -> str:
    """One item as spoken: the body alone when it already tells the headline.

    In print a headline then a body is how a page is scanned. Read aloud it is
    the same story twice in a row, because the body's first sentence usually
    restates the headline in full. Measured, not assumed: when most of the
    headline's content words recur in the body's opening sentence, the
    headline is dropped. Otherwise — short wire items whose body is a fragment
    that leans on its headline — both are kept.
    """
    head = _drop_outlet_suffix(speakable(item.get("headline", "")), item.get("source", ""))
    body = speakable(item.get(body_key) or item.get("body_text") or item.get("body") or "")
    if not body:
        return head
    if not head:
        return body
    if words:
        # Room for the headline and the body's opening, or the body alone:
        # a print headline is no sentence to end on.
        both = _clip(f"{head} {body}", words)
        if len(both) <= len(head) + 1:
            return _clip(body, words)
    # The opening forty words, not the first "sentence": abbreviations such as
    # "Sept. 21" end a sentence for a splitter and not for a reader, and cut
    # the comparison short enough that every headline looked new.
    first = " ".join(body.split()[:40])
    hw = _words(head)
    if hw and len(hw & _words(first)) / len(hw) >= 0.4:
        return _clip(body, words) if words else body
    return _clip(f"{head} {body}", words) if words else f"{head} {body}"


def happening_today(digest: dict) -> list[str]:
    """Scheduled events falling on the issue date, as the email's strip shows them."""
    try:
        import korea_calendar
    except Exception:                                           # noqa: BLE001
        return []
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
    # The same normalized shape the email's strip reads.
    out = [c["headline"] for c in korea_calendar.happening_on(digest.get("calendar_watch"), today)]
    # Hearings from the committee schedules, the same ones the email's strip shows.
    try:
        from render import hill_events, hill_event_text
        out += [hill_event_text(ev, spoken=True) for ev in hill_events(digest)[0]]
    except Exception:                                           # noqa: BLE001
        pass
    return out[:3]


# The spoken cues that open each segment, shared by both scripts and by
# listen.py's chapter titles. A lead story opens with its number; every other
# segment with a short fixed phrase, so a listener always knows where they are.
LEAD_CUES = ("First,", "Second,", "Third,", "Fourth,", "Fifth,")
CUE_PYONGYANG = "Now to Pyongyang."
CUE_NUMBER = "The number of the day."
CUE_ROUNDUP = "The rest of the news, quickly."
CUE_SEOUL = "In Seoul."
CUE_HILL = "On Capitol Hill."
CUE_ECONOMY = "On the economy."
CUE_REGION = "Elsewhere in the region."
CUE_WORLD = "Beyond the region."
CUE_POLL = "In the polls."
CUE_QUOTES = "In their own words."
CUE_AHEAD = "Coming up."
CUE_ALSO = "A few more things worth knowing."
CUE_ANALYSTS = "From the analysts."
CUE_IMAGERY = "From satellite imagery."
CUE_MARKETS = "Finally, the markets."
CLOSE_LEAD = "That's the Korea Daily Brief"
_SECTION_LEADS = (*LEAD_CUES, CUE_PYONGYANG, CUE_NUMBER, CUE_ROUNDUP, CUE_SEOUL, CUE_HILL,
                  CUE_ECONOMY, CUE_REGION, CUE_WORLD, CUE_POLL, CUE_QUOTES, CUE_AHEAD,
                  CUE_ALSO, CUE_ANALYSTS, CUE_IMAGERY, CUE_MARKETS, CLOSE_LEAD)

# The fallback's length. About ten minutes at the voice's pace: the leading
# daily briefs run about that, and past it a listener on a commute stops.
# Lead stories are told in full up to LEAD_WORDS; round-up items are cut to
# their opening sentences; then whole round-up items are dropped, weakest
# section first (ROUNDUP_TRIM), until the script fits AUDIO_WORDS.
AUDIO_WORDS = 1550
LEAD_WORDS = 170
ITEM_WORDS = 55
# (section, keep at least): trimmed in this order, one item at a time.
ROUNDUP_TRIM = (("also", 0), ("analysts", 1), ("quotes", 1), ("ahead", 2), ("imagery", 0),
                ("overnight", 3), ("region", 1), ("economy", 1), ("seoul", 2), ("analysts", 0),
                ("quotes", 0), ("ahead", 1), ("overnight", 2), ("world", 1), ("hill", 1),
                ("economy", 0), ("region", 0), ("seoul", 1))
_LOWER_FIRST = {"The", "A", "An", "This", "That", "These", "Those", "Its", "Their", "Any",
                "Each", "Both", "Despite", "While", "Without", "With", "Amid", "As", "After"}
_VERB_FIRST = re.compile(r"^(?:[A-Z][a-z]+s|Is|Was|Has|Calls|Says)\b(?! of\b)")
_PIECE = re.compile(r"^(?:The|This) (piece|article|essay|report|paper|analysis|study|commentary) ")


def _lower_first(text: str) -> str:
    """"The test..." -> "the test..." after a spoken cue; names keep their capital."""
    first = text.split(" ", 1)[0]
    return text[0].lower() + text[1:] if first in _LOWER_FIRST else text


def _drop_outlet_suffix(headline: str, source: str) -> str:
    """"North Korea tests torpedo, Reuters" -> "North Korea tests torpedo"."""
    m = re.search(r"[,:]\s*(?:the )?([A-Z][\w.'&]*(?:\s+[A-Z][\w.'&]*){0,3})\.?$", headline)
    if not m or not source:
        return headline
    name = m.group(1).lower().replace(".", "")
    known = f"{source} {speakable(source)}".lower().replace(".", "")
    return headline[:m.start()].rstrip(" ,:") + "." if name in known else headline


def _quote_text(raw: str) -> str:
    """The English of a quote: a translated Korean quote keeps only its translation."""
    s = str(raw or "")
    if _HANGUL.search(s):
        english = re.findall(r"\[\s*['\"‘“]([^\]]+?)['\"’”]\s*\]", s)
        rest = re.sub(r"[^\[\]]*\[[^\]]*\]", "", s).strip()
        s = " ".join(english + ([rest] if rest and not _HANGUL.search(rest) else []))
    return _clip(s.strip(), 40)


def build_script(digest: dict) -> str:
    """The brief as a spoken script, about ten minutes, in broadcast order.

    The shape is the one the written script follows: the open and the menu,
    the lead stories by number, Pyongyang, the round-up (Seoul, the wire,
    Capitol Hill, the economy, the region, Korea and the wider world, the
    polls, what's coming), then the markets and the close. US–Korea Trade &
    Investment is left out: a standing reference — tariff tables, the pledge
    ledger — not the day's news, which the editor asked to keep off the air.
    The morning memo is replaced by the RE line, because the memo retells the
    top stories.

    Connective cues are the only words added, and none carries a fact. Long
    items lose their later sentences, never their wording. A story already
    told in an earlier section is not told again: a listener, unlike a
    reader, cannot skip the repeat.
    """
    when = _spoken_date(digest)
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

    # ── Open: the show, the disclosure, the date, then the menu at once.
    open_lines = [opening_line(when)]
    parts = [speakable(x).rstrip(".,;: ") for x in str(digest.get("re_line") or "").split("·")]
    parts = [x if i == 0 else _lower_first(x) for i, x in enumerate(p for p in parts if p)]
    if len(parts) > 1:
        open_lines.append("In today's brief: " + "; ".join(parts[:-1]) + "; and " + parts[-1] + ".")
    elif parts:
        open_lines.append(f"In today's brief: {parts[0]}.")
    today_events = happening_today(digest)
    if today_events:
        open_lines.append("Happening today: " + "; ".join(speakable(e).rstrip(".") for e in today_events) + ".")
    segs: list[list[str]] = [[" ".join(open_lines)]]

    # ── The lead stories, by number. The menu has just named them, so the
    # body is told alone when it stands on its own; a print headline read
    # straight after it is the same story twice.
    top = _items(digest, "top_stories")
    for n, item in enumerate(top[:len(LEAD_CUES)]):
        body = speakable(item.get("body") or item.get("body_text") or "")
        told_text = body if len(body.split()) >= 30 else _story(item)
        told_text = _clip(told_text, LEAD_WORDS)
        fresh(told_text)
        segs.append([f"{LEAD_CUES[n]} {_lower_first(told_text)}"])

    # ── Pyongyang: the top state-media articles, always, even one a lead
    # story covered (then only its headline, as how Pyongyang played it).
    kcna = digest.get("kcna_delta") or {}
    if isinstance(kcna, dict):
        arts, mine = [], []
        for a in [a for a in (kcna.get("top_articles") or []) if isinstance(a, dict)][:3]:
            head = _drop_outlet_suffix(speakable(a.get("headline", "")), a.get("source", ""))
            full = _story({"headline": head, "body": a.get("summary", "")})
            w = _words(full)
            # Three outlets' headlines on one KCNA report are one article.
            if not w or any(len(w & m) / min(len(w), len(m)) >= 0.5 for m in mine):
                continue
            mine.append(w)
            if any(len(w & t) / min(len(w), len(t)) >= 0.5 for t in told):
                arts.append(head)
            else:
                told.append(w)
                arts.append(_clip(full, ITEM_WORDS))
        lines = []
        if arts:
            lines.append(("State media's top stories today. " if len(arts) > 1 else
                          "State media's top story today. ") + " ".join(arts))
        if kcna.get("bottom_line"):
            bl = "The bottom line: " + _lower_first(_clip(speakable(kcna["bottom_line"]), 70))
            days = kcna.get("days_since_last_appearance")
            # Said once: a bottom line that already counts Kim's absence
            # would otherwise be followed by the same fact as a number.
            if isinstance(days, int) and days > 0 and not kcna.get("kim_appearance_today") \
                    and not re.search(r"appearance|seen in public|absence", bl, re.I):
                bl += (" Kim Jong Un was last seen in public yesterday." if days == 1 else
                       f" Kim Jong Un was last seen in public {days} days ago.")
            lines.append(bl)
        if lines:
            segs.append([CUE_PYONGYANG + " " + " ".join(lines)])

    # ── The number of the day, unless it is a lead story's figure again.
    ks = digest.get("key_stat") or {}
    if isinstance(ks, dict) and ks.get("number"):
        stat = speakable(f'{ks["number"]}: {ks.get("label", "")}.').rstrip(".") + "."
        if ks.get("context"):
            stat += " " + _clip(speakable(ks["context"]), 45)
        if fresh(stat):
            segs.append([f"{CUE_NUMBER} {stat}"])

    # ── The round-up. Each section: its cue, then its items, trimmed below.
    roundup: list[tuple[str, str, list[str]]] = []

    def section(key: str, cue: str, items: list[str], words: int = ITEM_WORDS) -> None:
        kept = [_clip(i, words) for i in items if i and fresh(i)]
        if kept:
            roundup.append((key, cue, kept))

    section("overnight", CUE_ROUNDUP, [_story(i, "body_text", ITEM_WORDS) for i in _items(digest, "overnight_items")])

    gov = []
    for g in _items(digest, "rok_government"):
        gov.append(_story({"headline": g.get("action", ""), "body": g.get("detail", "")}, words=ITEM_WORDS))
    for a in _items(digest, "rok_assembly"):
        committee = re.sub(r"^\s*National Assembly\b[\s,:(—-]*", "", str(a.get("committee") or "")).strip(" )")
        story = _story({"headline": a.get("action", ""), "body": a.get("detail", "")}, words=ITEM_WORDS)
        named = "committee" in committee.lower() and "unspecified" not in committee.lower()
        gov.append((f"At the National Assembly's {speakable(committee).rstrip('.')}: " if named else
                    "At the National Assembly: ") + story)
    for r in _items(digest, "rok_personnel"):
        gov.append(_story({"headline": f'{r.get("name", "")}, {r.get("position", "")}: {r.get("action", "")}',
                           "body": r.get("detail", "")}, words=ITEM_WORDS))
    section("seoul", CUE_SEOUL, gov)

    # Capitol Hill: the day's items, then the week's collected hearings (today's
    # were already read in "Happening today"). Silent when there are neither.
    hill = [_story(i, "body_text", ITEM_WORDS) for i in _items(digest, "capitol_hill")]
    try:
        from render import hill_events, hill_event_text, _issue_day
        _day = _issue_day(digest)
        ahead = [ev for ev in hill_events(digest)[1]
                 if _day is None or str(ev.get("date", ""))[:10] != _day.isoformat()]
        spoken = []
        for ev in ahead[:3]:
            try:
                wd = datetime.strptime(str(ev["date"])[:10], "%Y-%m-%d").strftime("%A")
            except (KeyError, ValueError):
                continue
            spoken.append(f"{wd}, {speakable(hill_event_text(ev, spoken=True)).rstrip('.')}")
        if spoken:
            hill.append("Coming up on the Hill: " + "; ".join(spoken) + ".")
    except Exception:                                           # noqa: BLE001
        pass
    section("hill", CUE_HILL, hill, words=70)

    section("economy", CUE_ECONOMY, [_story(i, "body_text", ITEM_WORDS) for i in _items(digest, "business_economy")])
    section("region", CUE_REGION, [_story(i, "body_text", ITEM_WORDS) for i in _items(digest, "northeast_asia")])
    section("world", CUE_WORLD, [_story(i, "body_text", ITEM_WORDS) for i in _items(digest, "korea_world")])

    ps = digest.get("public_sentiment") or {}
    ap = ps.get("presidential_approval") or {}
    if isinstance(ap, dict) and ap.get("value"):
        src = re.sub(r"\s*\(.*?\)", "", str(ap.get("source") or "")).strip() or "the latest"
        polled = re.sub(r",?\s*20\d\d", "", speakable(str(ap.get("last_updated") or ""))).rstrip(".")
        dated = f", taken {polled}," if polled else ""
        line = (f"In the latest {src} poll{dated} President Lee's approval is "
                f"{str(ap['value']).replace('%', ' percent')}")
        if ap.get("trend") in ("up", "down"):
            line += f", {ap['trend']} from the previous poll"
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
        roundup.append(("poll", CUE_POLL, [line]))

    quotes = []
    for q in _items(digest, "social_statements") + _items(digest, "official_x_posts"):
        text = _quote_text(q.get("quote_text"))
        if text and q.get("who"):
            quotes.append(speakable(f'{q["who"]} said: "{text}"'))
    section("quotes", CUE_QUOTES, quotes[:2], words=60)

    _y = re.search(r"\b(20\d{2})\b", str(digest.get("digest_date") or ""))
    year = _y.group(1) if _y else ""
    ahead_items = []
    try:
        import korea_calendar
        _cal = [korea_calendar.normalize(c) or c for c in (digest.get("calendar_watch") or [])]
    except Exception:                                           # noqa: BLE001
        _cal = digest.get("calendar_watch") or []
    for c in _cal:
        if not isinstance(c, dict):
            continue
        date = str(c.get("date") or (f'{c["month"]} {c["day"]}' if c.get("month") and c.get("day") else "")).strip()
        if year:
            date = re.sub(rf",?\s*{year}\b", "", date).strip()
        date = speakable(re.sub(r"\s*\(.*?\)", "", date)).rstrip(".")
        event = _clip(speakable(c.get("event") or c.get("headline") or ""), 30)
        if event:
            ahead_items.append((f"{date}: " if date else "") + event)
    if ahead_items:
        roundup.append(("ahead", CUE_AHEAD, ahead_items[:4]))

    section("also", CUE_ALSO, [_story(i, "body_text", ITEM_WORDS) for i in _items(digest, "also_today")])

    analysis = []
    for o in _items(digest, "opeds_today") + _items(digest, "academic_today"):
        head = speakable(o.get("headline", "")).rstrip(".")
        by = o.get("authors")
        by = [str(x) for x in by if x] if isinstance(by, list) else [x.strip() for x in str(by or "").split(",") if x.strip()]
        names = (" and ".join(by) if len(by) <= 2 else ", ".join(by[:-1]) + ", and " + by[-1]) if by else ""
        src = speakable(o.get("source") or o.get("journal") or "").rstrip(".")
        arg = _clip(speakable(o.get("central_argument") or o.get("summary") or ""), ITEM_WORDS)
        piece = _PIECE.match(arg)
        if arg and src and piece:
            # "The piece examines..." -> "A piece in World Politics Review examines..."
            analysis.append(f"A {piece.group(1)} in {src}" + (f" by {names}" if names else "")
                            + " " + arg[piece.end():])
        elif arg and src and not _VERB_FIRST.match(arg):
            # "Kendall-Taylor and Fontaine, writing in Foreign Affairs, argue that..."
            who = f"{names}, writing in {src}," if names else src
            plural = len(by) > 1
            analysis.append(f"{who} argue{'' if plural else 's'} that {_lower_first(arg)}")
        elif arg and src:
            # What the piece argues and who published it; a title read aloud
            # ("Brewing Korea Crisis? Mines, Missiles, & POWs") is noise.
            analysis.append(f"From {src}" + (f", {names}" if names else "") + f": {arg}")
        else:
            intro = head + (f", by {names}" if names else "") + (f", in {src}" if src else "") + "."
            analysis.append(f"{intro} {arg}".strip())
    section("analysts", CUE_ANALYSTS, analysis, words=ITEM_WORDS + 15)

    im = digest.get("imagery_report") or {}
    if isinstance(im, dict) and (im.get("headline") or im.get("body")):
        section("imagery", CUE_IMAGERY, [_story({"headline": im.get("headline", ""), "body": im.get("body", "")}, words=ITEM_WORDS)])

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
        try:
            num = float(val.replace(",", "").rstrip("%"))
            val = (f"{num:,.{places}f}" if places is not None else f"{num:g}") + ("%" if val.endswith("%") else "")
        except ValueError:
            pass
        phrase = fmt.format(v=val.replace("%", " percent"))
        chg = v.get("change_pct")
        if isinstance(chg, (int, float)) and chg:
            phrase += f", {'up' if chg > 0 else 'down'} about {abs(round(chg, 1)):g} percent"
        spoken_mk.append(phrase + ".")
    close = [f"{CLOSE_LEAD} for {when}. The full text, with a "
             f"link to every source, is in today's email."]

    # ── Fit the budget: drop whole round-up items, weakest section first.
    def total() -> int:
        n = sum(len(" ".join(s).split()) for s in segs) + len(" ".join(spoken_mk).split()) + 25
        return n + sum(len(c.split()) + len(" ".join(i).split()) for _, c, i in roundup)

    for key, floor in ROUNDUP_TRIM:
        for k, _, items in roundup:
            while k == key and len(items) > floor and total() > AUDIO_WORDS:
                items.pop()
    roundup = [r for r in roundup if r[2]]
    for _, cue, items in roundup:
        segs.append([f"{cue} {items[0]}", *items[1:]])
    if spoken_mk:
        segs.append([f"{CUE_MARKETS} " + " ".join(spoken_mk)])
    segs.append(close)
    # A pause between segments; paragraphs within a segment run on.
    return f"\n\n{SEGMENT}\n\n".join("\n\n".join(x.strip() for x in s if x and x.strip())
                                     for s in segs if any(x and x.strip() for x in s))


# ── The written-for-the-ear script ───────────────────────────────────────────

_SCRIPT_SYSTEM = """You write the script for the audio edition of the Korea Daily Brief, the CSIS Korea Chair's daily briefing on the Korean Peninsula for senior policymakers. One host reads it aloud. It should sound like a well-made daily news podcast (think of the shape of NPR's Up First or Axios Today), not a newsletter read out.

FACTS. This rule outranks every other:
- Use ONLY facts in the brief JSON you are given. Every name, number, date, place, quote and claim must come from it.
- Add nothing from your own knowledge, even if you are certain it is true: no background, no history, no figures, no context the brief does not contain.
- Say why something matters only where the brief itself says so (body text, analyst notes, bottom lines, "so what" fields). Never speculate.
- Quote only quotes that appear in the brief, word for word, attributed as the brief attributes them.
- Write every number as the brief writes it, with no more than two numbers per story. Market figures may be rounded the way a presenter says them ("1,338.38 won" as "about 1,338 won", "down 1.98 percent" as "down about 2 percent").
- If something in the brief is unclear, leave it out rather than interpret it.

SHAPE. Up to seven segments, in this order. Put a line containing only --- between segments (the producer puts a pause there, and each segment becomes a chapter). Every segment opens with its fixed cue, word for word, so a listener always knows where they are.
1. OPEN (about 50 words). The listener must have the date and all three headlines inside the first 20 seconds. The fixed opening line gives the date; follow it at once with one menu line, "Three things today: ...", naming the three lead stories in a few words each. Then one sentence on why the first story matters, told as a tension, not a summary. If calendar_watch or hill_calendar has events dated today, add one short line saying what is happening today. No throat-clearing, nothing before the menu.
2. THE THREE LEAD STORIES (about 250 words each), one after another, with --- between them. Cues: "First, ...", "Second, ...", "Third, ...". Usually the top stories. For each: what happened, why it matters to someone who works on Korea policy (from the brief), and what to watch next. Fold in related items from other sections (government reactions, the National Assembly, statements, analysis, imagery) so each lead is one connected story, not a list. Keep one strand per story: if several items are about the same military situation (a warning, missile launches, satellite imagery, a weapons analysis), they belong in one lead together.
3. PYONGYANG (about 120 words). Cue: "Now to Pyongyang." Name every one of the top KCNA articles in kcna_delta.top_articles, even one a lead story already told (then one sentence on how state media framed it is enough), then the bottom line.
4. THE ROUND-UP (about 350 words). Cue: "The rest of the news, quickly." Everything else worth a listener's time, one or two sentences each, linked by quick spoken transitions: overnight items, government and appointments, the economy, the region, the poll (say when it was taken), what is coming up, the rest of the wire, analysis. Never tell a story the leads already told. Leave out US-Korea trade and investment entirely. Satellite imagery only if it is included.
5. CAPITOL HILL (about 60 words; only when capitol_hill has items or hill_calendar has hearings). Cue: "On Capitol Hill." Hearings named only as hill_calendar lists them.
6. KOREA AND THE WORLD (about 60 words; only when korea_world has items). Cue: "Beyond the region."
7. CLOSE. Cue: "Finally, the markets." Two or three short sentences, then the fixed closing line, which sends the listener to the email for the sources.

WRITE FOR THE EAR. These are broadcast writing rules:
- One idea per sentence. Most sentences under 20 words, none over 25. Vary the rhythm: a short sentence after a long one.
- Attribution before the claim: "South Korea's Defense Ministry says...", not "..., the ministry said."
- Full name and title once, then a short form ("Unification Minister Chung Dong-young", then "Chung"). Korean names exactly as the brief romanizes them, family name first.
- Say "you" to the listener now and then. Contractions.
- Join stories by cause, contrast or consequence ("That warning lands the same day Seoul..."). Never "Next," "Also," "In other news," "Moving on."
- End each lead story by restating its key fact in a few words, because the listener can't re-read it.
- Give a quote its context: who said it, and when or why, before the words themselves.
- Never title-read: say what an analysis argues and who published it, not its headline.
- No headline-ese, no strings of fragments, no lists read out.
- Never use these phrases: "let's dive in", "dive into", "delve", "in today's rapidly evolving", "it's worth noting", "notably", "a stark reminder", "only time will tell", "remains to be seen", "buckle up", "game-changer", "in a world where", "at the end of the day". Don't end sentences on a list of three for effect. Don't open with a rhetorical question.

WRITE FOR THE VOICE. A speech engine reads exactly what you write:
- Numbers as words around digits: "84.7 billion dollars", not "$84.7B"; "28,500 troops"; "1.2 trillion won"; "7.6 percent", never "%"; "down 7.6 percent", not "-7.6%".
- Dates in full: "October 13 to 15", not "Oct 13-15"; "the third quarter", not "Q3"; no weekday or month abbreviations.
- Acronyms a listener can't decode are said in full: "North Korea" and "South Korea", never DPRK or ROK; "U.S. Forces Korea" (USFK); "the U.N. Command" (UNC); "the Bank of Korea" (BOK); "the National Defense Authorization Act" (NDAA); "the Congressional Research Service" (CRS); "the International Atomic Energy Agency" (IAEA); "wartime operational control" (OPCON); "the Foreign Ministry" (MOFA); "intermediate-range missile" (IRBM); "prisoners of war" (POWs); "liquefied natural gas" (LNG). Say "Seoul's main stock index, the KOSPI" the first time. KCNA, DMZ, MASGA, U.S. and U.N. are fine as they are; always write U.S. and U.N. with their dots.
- Only words and plain punctuation: commas, full stops, question marks, colons, quotation marks for quotes. No em dashes, slashes, parentheses, brackets, arrows, middle dots, ampersands, asterisks, URLs, social handles or Korean script.

FORMAT: plain spoken text only, paragraphs separated by a blank line, segments separated by a line containing only ---. No headings, no stage directions, no sound cues, no markdown, no bullet points. Begin exactly with: "{opening}" End exactly with: "That's the Korea Daily Brief for {when}. The full text, with a link to every source, is in today's email." The episode runs about ten minutes: aim for 1,350 to 1,550 words, and never more than 1,650."""

_SCRIPT_KEYS = ("re_line", "top_stories", "overnight_items", "kcna_delta", "key_stat",
                "rok_government", "rok_assembly", "rok_personnel", "capitol_hill",
                "hill_calendar", "business_economy", "northeast_asia", "korea_world",
                "public_sentiment", "social_statements",
                "official_x_posts", "calendar_watch", "also_today", "opeds_today",
                "academic_today", "imagery_report", "market_indicators")

# Capitalised words a script may use that need not appear in the brief: the
# show's own frame, calendar words, generic titles, and the two leaders the
# assembled script names in its own words ("Kim Jong Un was last seen...",
# "President Lee's approval"), whether or not that day's brief spells them.
_ALLOWED_CAPS = set("""
U.S U.S. US UN Military Demarcation Line Joint Chiefs Staff Workers Central News Agency
Intermediate-range Intercontinental Submarine-launched Liquefied Natural Gas Industry Finance
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
Capitol Hill Congress Senate House Fourth Fifth
Kim Jong Un Lee Jae-myung
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
# Units a voice spells out and a brief abbreviates ("900 km" / "900 kilometers").
_UNIT_TOKENS = {"km": "kilometers", "kilometres": "kilometers", "kilometer": "kilometers",
                "mi": "miles", "mile": "miles", "kg": "kilograms", "bn": "billion",
                "mn": "million", "tn": "trillion", "pct": "percent"}
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
            out.append(_UNIT_TOKENS.get(t) or _MONTH_TOKENS.get(t) or _NUMBER_WORDS.get(t, t))
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
    data = {k: digest.get(k) for k in _SCRIPT_KEYS}
    src = json.dumps(data, ensure_ascii=False)
    src += " " + str(digest.get("digest_date") or "") + " " + when
    # The brief also as it is spoken: every script, written or assembled, is
    # passed through speakable(), so "$84.7B" is "84.7 billion dollars", "UNC"
    # is "the U.N. Command" and "US" is "U.S." on air. Comparing against the
    # same rules applied to the brief is the brief's own text, reformatted —
    # it lets no new figure, name or quotation through.
    strings: list[str] = []

    def _walk(v) -> None:
        if isinstance(v, dict):
            for k, x in v.items():
                if k not in ("url", "source_links", "secondary_url"):
                    _walk(x)
        elif isinstance(v, list):
            for x in v:
                _walk(x)
        elif isinstance(v, str) and v.strip():
            strings.append(v)
    _walk(data)
    src += " " + " ".join(speakable(x) for x in strings)
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
    for fixed in (opening_line(when), _legacy_opening(when),
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
    # Quotes are paired within a paragraph, and a "quote" that begins or ends
    # with a space is the gap between a closing mark and the next opening one,
    # not a quotation; on 14 October that pairing flagged half of one sentence
    # and the start of the next as an invented quote.
    quotes = []
    for para in script.split("\n"):
        for q in re.findall(r"[\"“]([^\"”]{12,})[\"”]", para):
            if q[:1].isspace() or q[-1:].isspace():
                continue
            quotes.append(q)
    for q in quotes:
        if _norm(q).strip() and " ".join(_norm(q).split()) not in " ".join(blob.split()):
            problems.append(f"quotation not in the brief: {q[:60]!r}")
    for sentence in re.split(r"(?<=[.!?:;])\s+|(?<=[.!?,][\"”’])\s+|\n+", script):
        words = re.findall(r"[A-Za-z][A-Za-z'.-]*", sentence)
        for w in words[1:]:
            core = w.strip(".'-").replace("'s", "")
            if not core or not core[0].isupper() or core in _ALLOWED_CAPS or len(core) < 3:
                continue
            # "U.S.-ROK": a compound of names each allowed or in the brief.
            if "-" in core and all(x in _ALLOWED_CAPS or not x[:1].isupper() or len(x) < 2
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
    global LAST_REPAIR
    LAST_REPAIR = []
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
                                         system=_SCRIPT_SYSTEM.replace("{opening}", opening_line(when))
                                                         .replace("{when}", when),
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
    opening = opening_line(when)
    if not text.startswith(opening[:40]):
        return None, ["the script did not open with the show's opening line"]
    # The disclosure is part of the fixed line. A writer that drops it gets it
    # back here, before the check, so every written episode says it.
    if text.startswith(_legacy_opening(when)):
        text = opening + text[len(_legacy_opening(when)):]
    problems = check_script(text, digest, when)
    if problems:
        repaired, dropped = _repair_script(text, problems, digest, when)
        if repaired is None:
            return None, problems
        LAST_REPAIR = dropped
        print(f"::notice title=Podcast script repaired::dropped {len(dropped)} sentence(s) "
              f"the fact check could not match to the brief")
        text = repaired
    text = re.sub(r"^\s*-{3,}\s*$", f"\n{SEGMENT}\n", text, flags=re.M)
    paras = [x.strip() if x.strip() == SEGMENT else speakable(x)
             for x in re.split(r"\n\s*\n", text) if x.strip()]
    return "\n\n".join(paras), []


LAST_REPAIR: list[str] = []
REPAIR_MAX_SHARE = 0.12          # drop at most this share of the script's words


def _repair_script(text: str, problems: list[str], digest: dict, when: str,
                   rounds: int = 2) -> tuple[str | None, list[str]]:
    """Drop only the sentences the check objects to; None if that would cut too much.

    A script that fails its revision used to be thrown away whole, so one
    unmatched figure or name cost the listener the written episode. This cuts
    the sentences holding a flagged number, quotation or name, re-checks the
    whole script from scratch, and keeps it if the cuts stay small. Nothing is
    added or reworded, so whatever survives is what the writer wrote and the
    check has passed.
    """
    total = len(text.split()) or 1
    dropped: list[str] = []
    opening = opening_line(when)
    closing = f"That's the Korea Daily Brief for {when}."
    for _ in range(rounds):
        nums = {m.group(1) for p in problems
                for m in [re.match(r"number not in the brief here: (\S+)", p)] if m}
        names = {m.group(1) for p in problems
                 for m in [re.match(r"name not in the brief: (\S+)", p)] if m}
        quotes = {m.group(1) for p in problems
                  for m in [re.match(r"quotation not in the brief: '(.+)'$", p)] if m}
        if not (nums or names or quotes):
            return None, dropped
        out_paras = []
        for para in re.split(r"\n\s*\n", text):
            if not para.strip() or para.strip().startswith(SEGMENT) or \
                    para.strip().startswith((opening[:40], closing[:30])):
                out_paras.append(para)
                continue
            keep = []
            for sent in re.split(r"(?<=[.!?][\"”’])\s+|(?<=[.!?])\s+", para.strip()):
                toks = set(_tokens(sent))
                bad = (nums & toks) or any(re.search(rf"\b{re.escape(n)}\b", sent) for n in names) \
                    or any(q[:40] in sent for q in quotes)
                if bad:
                    dropped.append(sent)
                else:
                    keep.append(sent)
            if keep:
                out_paras.append(" ".join(keep))
        text = "\n\n".join(out_paras)
        if sum(len(x.split()) for x in dropped) > REPAIR_MAX_SHARE * total:
            return None, dropped
        problems = check_script(text, digest, when)
        if not problems:
            return text, dropped
    return None, dropped


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
    return [(text, pause) for text, pause, _ in _chunks_indexed(script, limit)]


def segments(script: str) -> list[str]:
    """The script's non-empty segments, split exactly as _chunks splits them."""
    out = []
    for segment in re.split(rf"\n\s*{re.escape(SEGMENT)}\s*\n", "\n" + script.strip() + "\n"):
        paras = [x.strip() for x in segment.split("\n\n") if x.strip() and x.strip() != SEGMENT]
        if paras:
            out.append("\n\n".join(paras))
    return out


def _chunks_indexed(script: str, limit: int = CHUNK_CHARS) -> list[tuple[str, float, int]]:
    """_chunks, with the index (into segments()) of the segment each request belongs to.

    The index is what lets chapter times be measured rather than estimated:
    each request's audio is decoded and its exact length known, so a
    segment's start is the sum of everything voiced and paused before it.
    """
    out: list[tuple[str, float, int]] = []
    for n, segment in enumerate(segments(script)):
        cur = ""
        for para in segment.split("\n\n"):
            pieces = [para] if len(para) <= limit else re.split(r"(?<=[.!?])\s+", para)
            for piece in pieces:
                if len(cur) + len(piece) + 2 > limit and cur:
                    out.append((cur, PAUSE_PARAGRAPH, n))
                    cur = piece
                else:
                    cur = f"{cur}\n\n{piece}" if cur else piece
        if cur:
            out.append((cur, PAUSE_SEGMENT, n))
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
    body = {"text": for_voice(text), "model_id": model,
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
    body = {"model": model, "voice": voice, "input": for_voice(text), "response_format": "mp3"}
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


def _trim_silence(pcm: bytes, level: int = SILENCE_LEVEL, keep: float = EDGE_SILENCE) -> bytes:
    """16-bit mono PCM without the silence a voice pads each request with.

    Only the ends are touched, and EDGE_SILENCE is kept so no consonant is
    clipped. Audio that is all silence is returned unchanged: an empty
    request is a problem for the coverage check to report, not to hide.
    """
    from array import array
    a = array("h")
    a.frombytes(pcm[:len(pcm) - len(pcm) % 2])
    n = len(a)
    start = next((i for i in range(n) if abs(a[i]) >= level), None)
    if start is None:
        return pcm
    end = next(i for i in range(n - 1, -1, -1) if abs(a[i]) >= level) + 1
    pad = int(keep * PCM_RATE)
    return a[max(0, start - pad):min(n, end + pad)].tobytes()


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


def _master(parts: list[tuple[bytes, float]], out_path: Path,
            pace: float = 1.0) -> list[tuple[float, float]]:
    """The finished episode: sting, voice with real pauses, sting, at podcast loudness.

    Pauses are silence put in here, not asked of the voice: break tags are
    unreliable across voice models, and a request that ends a segment and the
    one that starts the next are separate calls anyway. The voice comes in
    over the tail of the opening sting. The whole mix is normalised to
    -16 LUFS, the level Apple Podcasts and most players expect, so the
    episode is neither quiet beside other shows nor uneven within itself.

    Without ffmpeg (a local run) the chunks are simply concatenated: MP3 is a
    stream of independent frames, so that plays everywhere.

    Returns where each part's speech starts and ends in the finished file, in
    seconds. Measured from the decoded samples, not estimated: the sting
    before the voice, every pause, and the pace change are all accounted for.
    These are the chapter and transcript times.
    """
    if not _ffmpeg():
        out_path.write_bytes(b"".join(p for p, _ in parts))
        spans, t = [], 0.0
        for p, _ in parts:
            d = mp3_seconds(p)
            spans.append((t, t + d))
            t += d
        return spans
    from array import array
    voice = array("h")
    at: list[tuple[int, int]] = []
    for i, (part, pause) in enumerate(parts):
        start = len(voice)
        voice.frombytes(_trim_silence(_pcm(part)))
        at.append((start, len(voice)))
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
    # The voice starts where the sting's un-overlapped part ends; atempo then
    # stretches the whole mix by 1/pace.
    lead = len(sting) - overlap
    return [((lead + a) / PCM_RATE / pace, (lead + b) / PCM_RATE / pace) for a, b in at]


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
    # ElevenLabs only. The editor asked on 8 October that OpenAI never be
    # charged again: there is no automatic fallback, and the workflows no
    # longer pass OPENAI_API_KEY. If ElevenLabs fails, that day has no
    # episode and the email shows the RE line instead of the Listen bar.
    # OpenAI runs only if someone deliberately sets TTS_PROVIDER=openai.
    if (os.environ.get("TTS_PROVIDER") or "").strip().lower() != "openai":
        if not eleven_key:
            LAST_ERROR = "ELEVENLABS_API_KEY is empty in this run"
            print(f"::warning title=No audio::{LAST_ERROR}")
            return None
        return _synthesize_eleven(script, out_path, eleven_key, eleven_voice)
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
        chunks = _chunks_indexed(script)
        parts = [(_voiced(c), pause) for c, pause, _ in chunks]
        return _finish(parts, script, out_path,
                       {"tts_provider": "openai", "tts_model": model, "tts_voice": voice},
                       pace=_pace(default=DEFAULT_PACE), index=[(c, n) for c, _, n in chunks])
    except Exception as e:                                      # noqa: BLE001
        LAST_ERROR = str(e)
        # An annotation, not only a log line: GitHub serves job logs from a
        # separate host, while annotations are readable through the API, so
        # the reason a run produced no audio can be read back without the log.
        print(f"::warning title=Audio skipped::{e}")
        print(f"  ⚠  Audio skipped (non-fatal): {e}")
        return None


def _finish(parts: list[tuple[bytes, float]], script: str, out_path: Path,
            who: dict, pace: float, index: list[tuple[str, int]] | None = None) -> dict | None:
    """Master the voiced parts and check nothing went missing. Shared by both voices.

    index gives each part's text and segment number; with it the record
    carries "_chunks", the measured timeline produce() turns into chapters and
    a transcript. It is popped there, so it never reaches the metrics log.
    """
    global LAST_ERROR
    voiced_seconds = sum(mp3_seconds(p) for p, _ in parts)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    spans = _master(parts, out_path, pace)
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
    rec = {**who, "tts_chars": len(script), "audio_bytes": out_path.stat().st_size,
           "audio_seconds": int(got), "audio_expected_seconds": int(want)}
    if index and spans and len(index) == len(spans):
        rec["_chunks"] = [{"start": round(a, 2), "end": round(b, 2), "segment": seg, "text": text}
                          for (a, b), (text, seg) in zip(spans, index)]
    return rec


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
        chunks = _chunks_indexed(script, ELEVEN_CHUNK_CHARS)
        parts = [(_voiced(c), pause) for c, pause, _ in chunks]
        return _finish(parts, script, out_path,
                       {"tts_provider": "elevenlabs", "tts_model": models[0], "tts_voice": voice_id},
                       pace=_pace(default=1.0), index=[(c, n) for c, _, n in chunks])
    except Exception as e:                                      # noqa: BLE001
        LAST_ERROR = str(e)
        print(f"::warning title=ElevenLabs audio failed::{e}")
        return None


# ── The feed ─────────────────────────────────────────────────────────────────

def update_feed(public: Path, web_base: str, episode: dict) -> list[dict] | None:
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
        print("::warning title=Podcast feed not updated::the published podcast.json could not "
              "be read, so today's episode is not in the feed (the MP3 is still published)")
        return None
    episodes = [e for e in episodes if e.get("date") != episode["date"]] + [episode]
    episodes.sort(key=lambda e: e.get("date", ""))
    episodes = episodes[-FEED_EPISODES:]
    if not write_if_safe(manifest, episodes, ok):
        return None
    (public / "podcast.xml").write_text(_feed_xml(episodes, web_base), encoding="utf-8")
    return episodes


# OP3 (op3.dev) is an open podcast-download counter: the enclosure URL is
# prefixed, OP3 logs the request and redirects to the file. On by default;
# PODCAST_OP3=0 (or false/off/no) turns it off for the whole feed at the next
# run, since every item's enclosure is rebuilt from its file name each time.
OP3_PREFIX = "https://op3.dev/e/"


def op3_enabled() -> bool:
    return (os.environ.get("PODCAST_OP3") or "1").strip().lower() not in ("0", "false", "off", "no")


def measured(url: str) -> str:
    """An episode URL with the download-counting prefix, when it is on.

    OP3 takes the target with its https:// scheme dropped; a plain http://
    target is kept whole, as OP3 documents.
    """
    if not op3_enabled() or not url.startswith(("http://", "https://")) or url.startswith(OP3_PREFIX):
        return url
    return OP3_PREFIX + (url[len("https://"):] if url.startswith("https://") else url)


def _item_description(e: dict, base: str) -> str:
    """Show notes for one episode, as the HTML podcast apps render.

    The day's summary, the lead stories linked to the articles the brief
    cited, a link to the brief itself, and the AI disclosure. Episodes from
    before show notes existed have no "notes" and get the rest.
    """
    from html import escape as h
    parts = [f"<p>{h(e.get('summary', ''))}</p>"] if e.get("summary") else []
    notes = [n for n in (e.get("notes") or []) if isinstance(n, dict) and n.get("headline")]
    if notes:
        lis = "".join(
            "<li>" + (f'<a href="{h(n["url"])}">{h(n["headline"])}</a>' if n.get("url") else h(n["headline"]))
            + (f" ({h(n['source'])})" if n.get("source") else "") + "</li>" for n in notes)
        parts.append(f"<p>Lead stories:</p><ul>{lis}</ul>")
    links = [f'<a href="{h(base + "/digest_" + e["date"] + ".html")}">Read the full brief, with every source</a>']
    if e.get("page"):
        links.append(f'<a href="{h(base + "/" + e["page"])}">Chapters and transcript</a>')
    parts.append("<p>" + " · ".join(links) + "</p>")
    parts.append(f"<p>{h(DISCLOSURE)}</p>")
    return "".join(parts)


def _feed_xml(episodes: list[dict], web_base: str) -> str:
    base = web_base.rstrip("/")
    items = []
    for e in reversed(episodes):
        when = datetime.strptime(e["date"], "%Y-%m-%d").replace(hour=11, tzinfo=timezone.utc)
        secs = int(e.get("seconds") or 0)
        desc = _item_description(e, base)
        extra = ""
        if e.get("chapters"):
            extra += f'\n      <podcast:chapters url="{_xml(base + "/" + e["chapters"])}" type="application/json+chapters"/>'
        if e.get("transcript"):
            extra += f'\n      <podcast:transcript url="{_xml(base + "/" + e["transcript"])}" type="text/vtt" language="en"/>'
        if e.get("transcript_text"):
            extra += f'\n      <podcast:transcript url="{_xml(base + "/" + e["transcript_text"])}" type="text/plain" language="en"/>'
        items.append(f"""    <item>
      <title>{_xml(e["title"])}</title>
      <description>{_xml(desc)}</description>
      <content:encoded><![CDATA[{desc.replace("]]>", "]]&gt;")}]]></content:encoded>
      <enclosure url="{_xml(measured(base + "/" + e["file"]))}" length="{int(e.get("bytes") or 0)}" type="audio/mpeg"/>
      <guid isPermaLink="false">korea-daily-brief-{e["date"]}</guid>
      <pubDate>{format_datetime(when)}</pubDate>
      <itunes:duration>{secs // 60}:{secs % 60:02d}</itunes:duration>
      <link>{_xml(base + "/" + (e.get("page") or "digest_" + e["date"] + ".html"))}</link>{extra}
    </item>""")
    # itunes:block keeps the feed out of podcast directories. The brief is
    # marked For Internal Use Only; the feed is for subscribing by URL, the same
    # audience that already reads the archive, and not for public discovery.
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:podcast="https://podcastindex.org/namespace/1.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Korea Daily Brief</title>
    <link>{_xml(base + "/listen/index.html")}</link>
    <atom:link href="{_xml(base + "/podcast.xml")}" rel="self" type="application/rss+xml"/>
    <description>The CSIS Korea Chair's daily brief on the Korean Peninsula, read aloud by an AI voice. Every item is from the printed brief, which links its sources.</description>
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
    chunks = rec.pop("_chunks", None)
    extras = _episode_extras(digest, script, chunks, rec, public, date_slug, source)
    shutil.copyfile(mp3, public / "latest.mp3")
    episodes = None
    if web_base:
        episodes = update_feed(public, web_base, {
            "date": date_slug,
            "title": f"Korea Daily Brief | {_spoken_date(digest)}",
            "summary": speakable(digest.get("re_line", "")),
            "file": mp3.name, "bytes": rec["audio_bytes"],
            "seconds": rec["audio_seconds"],
            "script": source,
            # Every reason, not the four an annotation shows, so a rejected
            # rewrite can be diagnosed without the run log.
            **({"script_rejected": why[:40]} if source == "assembled" and why else {}),
            **({"script_repaired": LAST_REPAIR[:20]} if source == "written" and LAST_REPAIR else {}),
            **{k: v for k, v in extras.items() if not k.startswith("_")},
        })
    # The player page the email links to. Written last, from the feed's
    # episode list when update_feed read it; a failure leaves the email's
    # Listen bar on the MP3, as before.
    try:
        import listen
        rec["listen_page"] = listen.write_pages(
            public, date_slug=date_slug, digest=digest, web_base=web_base,
            minutes=max(1, round(rec["audio_seconds"] / 60)),
            chapters=extras.get("_chapter_list"), chunks=chunks, script=script,
            notes=extras.get("notes") or [], episodes=episodes)
        print(f"  🎧  Player page: {rec['listen_page']}")
        # Only now is it safe for the feed to point at the page. The list
        # is the one update_feed just read and wrote, so nothing is lost.
        if episodes:
            for e in episodes:
                if e.get("date") == date_slug:
                    e["page"] = rec["listen_page"]
            from shared.published import write_if_safe
            if write_if_safe(public / "podcast.json", episodes, True):
                (public / "podcast.xml").write_text(_feed_xml(episodes, web_base), encoding="utf-8")
    except Exception as e:                                      # noqa: BLE001
        print(f"::warning title=Player page skipped::{e}")
    return rec


def _episode_extras(digest: dict, script: str, chunks: list[dict] | None, rec: dict,
                    public: Path, date_slug: str, source: str) -> dict:
    """Chapters (JSON and ID3), transcript and show notes, each independently optional.

    Returns the fields update_feed records for the episode. Each file is
    written only when its step succeeds, and none of them can stop the
    episode: a failure is a warning and that field is left out.
    """
    out: dict = {"transcript_text": f"digest_{date_slug}.txt"}
    try:
        import listen
    except Exception as e:                                      # noqa: BLE001
        print(f"::warning title=Episode extras skipped::{e}")
        return out
    try:
        out["notes"] = listen.show_notes(digest)
    except Exception as e:                                      # noqa: BLE001
        print(f"  ⚠  Show notes skipped: {e}")
    if not chunks:
        print("  ⚠  No measured timeline (unmastered audio?); no chapters or VTT this episode")
        return out
    try:
        (public / f"digest_{date_slug}.vtt").write_text(listen.vtt(chunks), encoding="utf-8")
        out["transcript"] = f"digest_{date_slug}.vtt"
    except Exception as e:                                      # noqa: BLE001
        print(f"  ⚠  VTT transcript skipped: {e}")
    try:
        mp3 = public / f"digest_{date_slug}.mp3"
        chapters = listen.build_chapters(chunks, script, digest, source,
                                         mp3_seconds(mp3.read_bytes()) or rec["audio_seconds"])
        (public / f"digest_{date_slug}.chapters.json").write_text(
            listen.chapters_json(chapters), encoding="utf-8")
        out["chapters"] = f"digest_{date_slug}.chapters.json"
        out["_chapter_list"] = chapters
        if listen.embed_chapters(mp3, chapters, f"Korea Daily Brief | {_spoken_date(digest)}"):
            rec["audio_bytes"] = mp3.stat().st_size
        print(f"  🎧  Chapters: {len(chapters)}")
    except Exception as e:                                      # noqa: BLE001
        print(f"  ⚠  Chapters skipped: {e}")
    return out


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
        if (os.environ.get("TTS_PROVIDER") or "").strip().lower() != "openai":
            why = LAST_ERROR or "ElevenLabs returned no audio."
            if "empty" in why:
                why += (". Add it as a REPOSITORY secret: Settings > Secrets and "
                        "variables > Actions > Repository secrets.")
            elif "401" in why:
                why += " — the ElevenLabs key is wrong or revoked; create a new one and replace the secret."
            elif "quota" in why.lower() or "credit" in why.lower():
                why += " — the ElevenLabs plan is out of credits: elevenlabs.io > Subscription."
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
