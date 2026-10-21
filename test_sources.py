"""Checks that the prompt's claims about sources match the collector.

Two failures reached readers before this file existed, and both had the same
shape: the prompt told the model something about the feed that was not true.

The mandatory-inclusion rule named MSNBC for months after the feed was pruned
for publishing no Korea coverage, and named The Economist, which never had a
feed. The tiers paragraph listed seven think tanks the collector does not
carry. Naming a source the model never receives is the worst kind of prompt
error: it invites the model to satisfy the instruction from memory, which is
the exact failure SOURCE-OR-SKIP exists to prevent.

The other check guards the relevance filter. `KOREA_KEYWORDS` exists to strip
world news out of general wires. Applied to a ROK ministry feed it deleted
most of it, because a real headline such as "2027년도 예산안 국무회의 의결"
contains none of its Korean tokens. Nine of twelve representative ministry
headlines were being discarded while the prompt asserted the ministries were
in the feed.

Run: python test_sources.py
"""
from __future__ import annotations

import json
import re
import sys

import collect
import digest


def _all_feed_names() -> set[str]:
    names: set[str] = set()
    for attr in dir(collect):
        if attr.endswith("_FEEDS") and isinstance(getattr(collect, attr), dict):
            names |= set(getattr(collect, attr))
    return names


def check_prestige_rule_is_enforceable() -> list[str]:
    """Every outlet the prompt calls mandatory must have a feed behind it."""
    m = re.search(r"PRESTIGE OUTLET RULE.*?from ([^.]+?), it MUST", digest.SYSTEM_PROMPT, re.S)
    if not m:
        return ["PRESTIGE OUTLET RULE not found in the system prompt"]
    named = [o.strip() for o in re.split(r",| or ", m.group(1)) if o.strip()]
    feeds = " ".join(_all_feed_names()).lower()
    aliases = {"washington post": "wapo", "financial times": "ft",
               "the economist": "economist", "ap": "ap "}
    problems = []
    for outlet in named:
        key = aliases.get(outlet.lower(), outlet.lower())
        if key.strip() not in feeds:
            problems.append(f"prestige rule names {outlet!r} but no feed collects it")
    return problems


def check_primary_sources_reach_the_model() -> list[str]:
    """A ROK government feed must be exempt from the relevance filter."""
    problems = []
    for name in _all_feed_names():
        is_primary = name.startswith("ROK ") or name in collect.ROK_GOVERNMENT_FEEDS
        if is_primary and name not in collect.KOREA_NATIVE_FEEDS:
            problems.append(f"{name!r} is a primary ROK source but is filtered "
                            f"by KOREA_KEYWORDS; most of its items will be dropped")
    return problems


def check_korean_headlines_survive() -> list[str]:
    """Representative ministry headlines, none of which carry a filter token."""
    samples = [
        ("ROK MOEF", "2027년도 예산안 국무회의 의결…총지출 820조9천억원"),
        ("ROK MOTIE", "산업부, 반도체 특별법 후속 조치 발표"),
        ("ROK Presidential Office", "대통령실, 한미 정상 통화 결과 브리핑"),
        ("ROK Joint Chiefs", "합참, 북한 단거리 탄도미사일 발사 포착"),
        ("ROK Courts", "대법원, 선거법 위반 상고심 선고기일 지정"),
    ]

    class _Entry(dict):
        def get(self, key, default=None):
            return dict.get(self, key, default)

    problems = []
    for source, title in samples:
        entry = _Entry(title=title, summary="", link="https://example.invalid")
        reaches = (source in collect.KOREA_NATIVE_FEEDS
                   or collect._is_korea_related(entry))
        if not reaches:
            problems.append(f"{source}: {title!r} would be dropped before the model")
    return problems


def check_filter_still_rejects_world_news() -> list[str]:
    """The exemption must not turn the general wires into an open pipe."""
    class _Entry(dict):
        def get(self, key, default=None):
            return dict.get(self, key, default)

    entry = _Entry(title="Brazil central bank holds rate steady",
                   summary="", link="https://example.invalid")
    if "Reuters Korea" in collect.KOREA_NATIVE_FEEDS:
        return ["Reuters is a general wire and must stay behind the filter"]
    if collect._is_korea_related(entry):
        return ["KOREA_KEYWORDS now admits unrelated world news"]
    return []


def check_named_institutions_exist() -> list[str]:
    """Institutions the tiers paragraph claims must be collected."""
    m = re.search(r"SOURCE TIERS:(.*?)\n", digest.SYSTEM_PROMPT, re.S)
    if not m:
        return ["SOURCE TIERS paragraph not found"]
    claimed = re.findall(r"\(([^)]+)\)", m.group(1))
    feeds = " ".join(_all_feed_names()).lower()
    problems = []
    for group in claimed:
        # Parentheticals that are asides rather than source lists.
        if " " in group and not any(c in group for c in ",") and len(group.split()) > 3:
            continue
        for inst in (x.strip() for x in group.split(",")):
            if len(inst.split()) > 3:      # a phrase, not an institution name
                continue
            token = inst.split()[0].lower()
            if len(token) > 2 and token not in feeds and inst.lower() not in feeds:
                problems.append(f"tiers paragraph claims {inst!r} but no feed collects it")
    return problems


def check_mandatory_outlets_reach_the_prompt() -> list[str]:
    """A rule cannot bind on an article the model never receives.

    Tier 1 used to be truncated to the first 60 articles of a list ordered by
    network latency, so on a busy day the WSJ, FT and Joint Chiefs items the
    prompt's mandatory rules depend on simply were not in the prompt.
    """
    import random
    volumes = [("Yonhap English", 34), ("Korea Herald", 22), ("연합뉴스", 28),
               ("조선일보", 19), ("Reuters Korea", 4), ("WSJ Korea", 2),
               ("FT Korea", 1), ("NYT Korea", 2), ("38 North", 1),
               ("ROK Presidential Office", 3), ("ROK MOFA", 4),
               ("ROK Policy Briefing", 9), ("ROK Joint Chiefs", 2),
               ("USTR", 1), ("JTBC", 11), ("KBS", 14), ("매일경제", 17)]
    articles = [{"source": src, "title": f"{src} {i}", "url": f"https://x/{src}/{i}",
                 "summary": "", "lang": "EN"}
                for src, n in volumes for i in range(n)]
    random.Random(11).shuffle(articles)

    ranked = digest.rank_for_prompt(articles)[:140]
    present = {a["source"] for a in ranked}
    must = ["WSJ Korea", "FT Korea", "NYT Korea", "Reuters Korea", "38 North",
            "ROK Presidential Office", "ROK MOFA", "ROK Policy Briefing",
            "ROK Joint Chiefs", "USTR"]
    problems = [f"{m} would not reach the prompt" for m in must if m not in present]

    # The first slots must go to primary documents, not to whichever wire
    # happened to answer first.
    head = [a["source"] for a in ranked[:10]]
    if not any(h.startswith("ROK ") or h == "USTR" for h in head):
        problems.append("no primary source in the first ten articles of the prompt")
    return problems


# Tier-1 feeds carrying a publisher feed of their own, not just a Google News
# search. Raise this number as feeds are converted; never lower it. The point
# is a ratchet: the brief got into trouble by depending on one service for
# almost every source, and that share should only ever improve.
MIN_FEEDS_WITH_NATIVE_PATH = 39


def check_google_news_dependence_not_regressing() -> list[str]:
    """Guard the migration away from a single upstream.

    Nearly the whole feed list was Google News `site:` searches, so one change
    or rate-limit upstream took almost every source at once, with no partial
    degradation — the brief simply arrived thin. Feeds are ordered candidate
    lists now, native first and the search last, so a native path that is
    wrong or has moved costs nothing.

    This does not demand a native feed for every source, which would be a
    fiction: many of these outlets publish no usable RSS. It demands that the
    number already converted does not go backwards.
    """
    have_native = [n for n, v in collect.TIER1_FEEDS.items()
                   if not isinstance(v, str) and any("news.google.com" not in u for u in v)]
    if len(have_native) < MIN_FEEDS_WITH_NATIVE_PATH:
        return [f"only {len(have_native)} tier-1 feeds have a native path, "
                f"down from {MIN_FEEDS_WITH_NATIVE_PATH} — a conversion was reverted"]
    return []


def check_native_feeds_come_first() -> list[str]:
    """A candidate list must not put Google News ahead of a native feed."""
    problems = []
    for name, value in {**collect.TIER1_FEEDS, **collect.CAPITOL_HILL_FEEDS,
                        **collect.KOREA_WORLD_FEEDS}.items():
        if isinstance(value, str):
            continue
        seen_google = False
        for url in value:
            is_google = "news.google.com" in url
            if seen_google and not is_google:
                problems.append(f"{name!r} tries Google News before a native feed")
                break
            seen_google = seen_google or is_google
    return problems


def check_major_feeds_have_native_paths() -> list[str]:
    """The feeds the brief leans on hardest should not rest on one service."""
    problems = []
    for name in collect.MAJOR_FEEDS:
        value = collect.TIER1_FEEDS.get(name)
        if value is None:
            problems.append(f"MAJOR_FEEDS names {name!r} but no such feed exists")
            continue
        urls = [value] if isinstance(value, str) else value
        if not any("news.google.com" not in u for u in urls):
            problems.append(f"major feed {name!r} has no native candidate")
    return problems


def check_length_has_a_ceiling() -> list[str]:
    """The section maximums must not permit far more than the target.

    An issue shipped at 3,518 words against a 2,000 target. The pipeline had a
    floor and no ceiling, and the section maximums permitted about 3,680 words
    between them, so nothing stopped the brief filling them.
    """
    import run
    import length_budget
    from digest import _count_digest_words

    problems = []
    # Roughly how long an item in each section runs, measured from real issues.
    per_item = {"top_stories": 55, "overnight_items": 24, "business_economy": 40,
                "northeast_asia": 40, "also_today": 24, "rok_government": 36,
                "rok_assembly": 30, "rok_personnel": 28, "opeds_today": 44,
                "academic_today": 44, "social_statements": 40, "morning_memo": 26,
                "capitol_hill": 40, "korea_world": 40}
    permitted = sum(hi * per_item.get(name, 25)
                    for name, (_lo, hi) in run.SECTION_CAPS.items())
    permitted += 400          # kcna, trade, key stat, on this day
    if permitted > run.WORD_CEILING + 300:
        problems.append(f"section caps permit about {permitted} words against a "
                        f"{run.WORD_CEILING} ceiling — the caps, not the prompt, "
                        f"are what decides length")

    # And the trim must actually bring an over-long day under, without ever
    # touching the sections that are the brief.
    def _mk(n, words):
        return [{"body_text": " ".join(["w"] * words)} for _ in range(n)]
    over = {"top_stories": _mk(4, 90), "overnight_items": _mk(12, 40),
            "business_economy": _mk(6, 60), "northeast_asia": _mk(6, 60),
            "also_today": _mk(6, 40), "rok_government": _mk(6, 55),
            "rok_assembly": _mk(6, 45), "rok_personnel": _mk(6, 42),
            "opeds_today": _mk(6, 60), "academic_today": _mk(6, 70),
            "social_statements": _mk(6, 55), "capitol_hill": _mk(4, 50),
            "korea_world": _mk(3, 50)}
    length_budget.apply(over, _count_digest_words, run.WORD_CEILING)
    if _count_digest_words(over) > run.WORD_CEILING:
        problems.append("length_budget did not bring an over-long digest under the ceiling")
    if len(over["top_stories"]) != 4:
        problems.append("length_budget trimmed top_stories, which is the brief itself")
    return problems


def check_nav_links_land_where_they_say() -> list[str]:
    """Every jump link points at the section it names.

    "Top Stories" pointed at `#overnight`: the label and the anchor were two
    separate columns of a literal, so a mismatch between them was invisible.
    A menu that lands a section past where it says it will is worse than no
    menu, because a reader who tries it once stops trying.
    """
    import re as _re
    problems = []
    from pathlib import Path
    src = Path("render.py").read_text(encoding="utf-8")
    block = _re.search(r"_NAV = \[(.*?)\]", src, _re.S)
    if not block:
        return ["render._NAV not found; the navigation row has moved"]
    pairs = _re.findall(r'\("([^"]+)",\s*"([^"]+)"\)', block.group(1))
    if not pairs:
        return ["render._NAV parsed to nothing"]
    anchors = set(_re.findall(r'a name="([a-z0-9-]+)"', src))
    for label, anchor in pairs:
        if anchor not in anchors:
            problems.append(f"nav {label!r} points at #{anchor}, which no section emits")
    # Several labels are deliberate synonyms for their section — Seoul for the
    # government round-up, Pyongyang for the KCNA read. So the pairing is
    # stated here rather than inferred, and a label that changes destination
    # has to be changed in both places.
    expected = {
        "Top Stories": "top-stories", "Overnight": "overnight",
        "Pyongyang": "kcna", "Seoul": "rok-gov", "Trade": "trade",
        "Markets": "business", "Polling": "sentiment",
        "Upcoming": "upcoming", "Analysis": "analysis",
        "Satellite": "satellite",
    }
    for label, anchor in pairs:
        want = expected.get(label)
        if want is None:
            problems.append(f"nav {label!r} is new; add its destination to "
                            f"test_sources.check_nav_links_land_where_they_say")
        elif want != anchor:
            problems.append(f"nav {label!r} points at #{anchor}, not #{want}")
    return problems


def check_colours_are_colours() -> list[str]:
    """No malformed hex in the stylesheet.

    `#4A526073D` sat in five dark-mode rules. Nine hex digits is not a colour,
    so every browser dropped the whole declaration and the card borders were
    simply missing in dark mode — silently, because an invalid value in CSS is
    ignored rather than reported.
    """
    import re as _re
    from pathlib import Path
    src = Path("render.py").read_text(encoding="utf-8")
    bad = {m for m in _re.findall(r"#[0-9A-Fa-f]{2,12}\b", src)
           if len(m) - 1 not in (3, 4, 6, 8)}
    return [f"{h} is not a valid hex colour" for h in sorted(bad)]


def check_emphasis_cannot_inject() -> list[str]:
    """The **bold** convention must not become an HTML hole.

    The model cannot emit markup: every field is escaped first, and only then
    are the two exact asterisk shapes converted. This proves both halves —
    that a tag in the model's output stays inert text, and that a malformed
    mark is printed literally rather than opening something.
    """
    import render
    problems = []
    out = render._emphasis(render._esc('<script>x</script> **a** *b* a*b*c **un closed'))
    if "<script" in out:
        problems.append("a tag in model output survived into the page")
    if "<strong" not in out or "<em>" not in out:
        problems.append("the emphasis convention stopped working")
    if "a*b*c" not in out:
        problems.append("asterisks inside a word are being converted")
    if "**un closed" not in out:
        problems.append("an unclosed mark is not left literal")
    # The prompt has to ask for it, or the renderer converts a mark nothing writes.
    from pathlib import Path
    src = Path("digest.py").read_text(encoding="utf-8")
    if "EMPHASIS —" not in src:
        problems.append("digest.py no longer states the emphasis convention")
    return problems


def check_masthead_is_mobile_safe() -> list[str]:
    """The nameplate must shrink on a phone, and the meta line must stack.

    All four briefs drifted apart here without anyone noticing, because a
    masthead only looks wrong on a device none of the checks used: one never
    shrank at all, one had no mobile rule and kept its desktop columns side by
    side on a 390px screen, and one dropped its nameplate to 16px. The sizes
    are asserted rather than compared so a change has to be deliberate.
    """
    import re, render
    problems = []
    html = render.render({"re_line": "x", "morning_memo": ["a", "b", "c"]})
    desktop = re.search(r"<h1[^>]*font-size:(\d+)px", html)
    if not desktop:
        return ["no <h1> in the masthead"]
    if desktop.group(1) != "26":
        problems.append(f"desktop nameplate is {desktop.group(1)}px, the house size is 26px")
    phone = re.findall(r"max-width:\s*6[0-9]0px[^@]*?h1 \{ font-size:(\d+)px", html, re.S)
    if not phone:
        problems.append("no phone rule shrinks the nameplate")
    elif phone[0] != "22":
        problems.append(f"phone nameplate is {phone[0]}px, the house size is 22px")
    if not re.search(r"max-width:\s*6[0-9]0px[^@]*?mast-meta[^@]*?display:block", html, re.S):
        problems.append("the meta cell does not stack under the nameplate on a phone")
    return problems



def check_subject_is_the_house_format():
    """"<Edition> Daily Brief | <Weekday>, <Month> <D>, <Year>", the same in all
    four editions. A DIGEST_SUBJECT_STYLE variable used to append the day's lead
    story, so the subject differed from its siblings depending on a repo setting
    nobody would think to look at. Returns a list of problems, empty if none."""
    import os
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from send_email import build_subject
    problems = []
    now = datetime.now(ZoneInfo("America/New_York"))
    want = "Korea Daily Brief | " + now.strftime("%A, %B %-d, %Y")
    subj = build_subject(re_line="A | B | C", lead="A lead story")
    if subj != want:
        problems.append(f"subject is {subj!r}, expected {want!r}")
    if not re.fullmatch(r"Korea Daily Brief \| \w+, \w+ \d{1,2}, \d{4}", subj):
        problems.append(f"subject does not match the house pattern: {subj!r}")
    os.environ["DIGEST_SUBJECT_STYLE"] = "lead"
    try:
        if build_subject(lead="A lead story") != want:
            problems.append("DIGEST_SUBJECT_STYLE still changes the subject at runtime")
    finally:
        os.environ.pop("DIGEST_SUBJECT_STYLE", None)
    return problems


def check_no_raw_markdown_reaches_the_reader():
    """Every prose field must have its **bold** converted, not printed.

    The prompt asks for a name in double asterisks and a figure in single ones,
    and the renderer converts them. A field that skips the conversion ships the
    asterisks: the 10 September China brief carried eighteen, among them
    **Ford** and a half-open **Cynthia "Xanthi". Walking every field means a
    newly added one cannot leak quietly.
    """
    import copy
    import preview
    import render as render_mod
    prose = ("body", "body_text", "summary", "detail", "context", "text",
             "note", "analyst_note", "so_what", "headline", "central_argument")
    d = copy.deepcopy(preview.DIGEST)
    marks = {}

    def mark(o):
        if isinstance(o, dict):
            for k, v in list(o.items()):
                if k in prose and isinstance(v, str) and v.strip():
                    tok = f"MARK{len(marks)}"
                    marks[tok] = k
                    o[k] = f"**{tok}** tail."
                else:
                    mark(v)
        elif isinstance(o, list):
            for x in o:
                mark(x)

    mark(d)
    html = render_mod.render(d)
    problems = [f"{f}: ships literal ** to the reader"
                for f in sorted({f for t, f in marks.items() if f"**{t}**" in html})]

    d2 = copy.deepcopy(preview.DIGEST)
    d2["top_stories"][0]["body"] = "**<script>alert(1)</script>** and **A Name**"
    h2 = render_mod.render(d2)
    if "<script>" in h2:
        problems.append("emphasis smuggled markup past the escaper")
    if 'font-weight:700;">A Name</strong>' not in h2:
        problems.append("a genuine name no longer bolds")

    # The fixture does not populate every section, so walking it alone can pass
    # while an unexercised section still leaks. Two backstops: the walk must
    # have marked a meaningful number of fields, and the renderer's source must
    # carry no unwrapped prose site at all.
    if len(marks) < 8:
        problems.append(f"the walk only marked {len(marks)} fields; too few to mean anything")
    import re as _re
    from pathlib import Path as _P
    unwrapped = _re.findall(
        r'(?<!_emphasis\()\b_esc\(\w+\.get\("(detail|context|headline|note|body_text|body|summary)", ""\)\)',
        _P("render.py").read_text(encoding="utf-8"))
    for f in sorted(set(unwrapped)):
        problems.append(f"{f}: rendered without the emphasis conversion")
    return problems


def check_api_cost_is_recorded():
    """Recording spend has three parts, and any one can lapse without a symptom.

    A per-call ledger, a write of it into metrics.jsonl, and a workflow step
    that commits the file. The Japan edition had none of the three for months.
    This edition had the first two while its file lived only in an Actions
    cache that GitHub evicts after seven days, and .gitignore silently defeated
    the commit step that named it. Neither showed up as a failure, because a
    missing cost record looks exactly like a cheap week.
    """
    import inspect
    from pathlib import Path as _P
    import digest as _d
    problems = []
    src = inspect.getsource(_d)
    if "TOKEN_LEDGER" not in src and "_RUN_USAGE" not in src:
        problems.append("digest keeps no per-call token ledger")
    if "def get_run_usage" not in src and "def run_cost" not in src:
        problems.append("digest exposes no per-run usage total")

    run_src = _P("run.py").read_text(encoding="utf-8")
    if "metrics.jsonl" not in run_src:
        problems.append("run.py writes no metrics line")

    wf = _P(".github/workflows/daily-digest.yml")
    if wf.exists() and "metrics.jsonl" not in wf.read_text(encoding="utf-8"):
        problems.append("the workflow never commits metrics.jsonl, so it lives only in a cache")

    gi = _P(".gitignore")
    if gi.exists() and any(l.strip() == "metrics.jsonl" for l in gi.read_text().splitlines()):
        problems.append("metrics.jsonl is gitignored, which silently defeats the commit step")
    return problems


def check_coverage_audit():
    """A story three outlets ran must be flagged when the brief lacks it, and not otherwise.

    The words of a story have to appear together in one item: on 18 October
    "Samsung", "union" and "strike" each appeared in unrelated items, and a
    whole-brief match would have called a missed Samsung strike covered.
    """
    import coverage_audit as ca
    digest = {"top_stories": [{"headline": "North Korea tests AI-guided torpedo",
                               "body": "KCNA said the torpedo test succeeded."}],
              "business_economy": [{"headline": "Samsung shares rise", "body_text": "Chip demand."}],
              "calendar_watch": [{"event": "HD Hyundai union strike widens"}]}
    arts = [{"title": t, "source": s} for t, s in (
        ("North Korea tests AI-guided torpedo - Reuters", "Reuters"),
        ("N. Korea tests new AI torpedo - Yonhap", "Yonhap"),
        ("North Korea claims AI torpedo test - AP", "AP"),
        ("Samsung union launches general strike over bonuses - Reuters", "Reuters"),
        ("Samsung union begins general strike - Bloomberg", "Bloomberg"),
        ("Samsung workers stage general strike over bonus - Korea Herald", "Korea Herald"))]
    found = [m["headline"] for m in ca.missed({"tier1": arts}, digest)]
    problems = []
    if not any("Samsung" in h for h in found):
        problems.append("missed Samsung strike not flagged")
    if any("torpedo" in h.lower() for h in found):
        problems.append("covered torpedo story wrongly flagged")
    return problems


def check_audio_script_is_the_brief():
    """The narration may only say what the brief printed, in a form a voice can read.

    The audio edition is built from the digest rather than rewritten by a model
    precisely so it stays inside SOURCE-OR-SKIP. This guards that: every top
    story is narrated, every narrated story names its source, and nothing that
    a speech engine would mispronounce or read literally survives.
    """
    import re
    import podcast
    digest = {
        "digest_date": "2026-10-07",
        "re_line": "DPRK warns Seoul · ROK $747B plan",
        "morning_memo": ["**DPRK** warned the ROK over DMZ demining (더불어민주당)."],
        "top_stories": [
            {"headline": "DPRK rejects ROK mine investigation", "source": "NK News",
             "body": "ROK soldiers were injured near DPRK territory. https://x.y/z"},
            {"headline": "US-ROK talks resume on $22.3B plan", "source": "Yonhap",
             "body": "FM Cho Hyun met PM Han on Oct 3–5."},
        ],
        "market_indicators": {"usd_krw": {"value": "1,338.38", "change_pct": -0.4}},
        "kcna_delta": {"top_articles": [
            {"headline": "DPRK rejects ROK mine investigation", "summary": "Repeat of a top story."},
            {"headline": "Kim letter to Putin calls war sacred", "summary": "Sent ahead of Oct 10."},
            {"headline": "DPRK backs One China position", "summary": "Statement via KCNA."}],
            "bottom_line": "Alignment with Moscow."},
        "social_statements": [{"who": "Foreign Minister Cho Hyun", "handle_context": "@FMChoHyun",
                               "quote_text": "We will cooperate.", "analyst_note": "Corroborated (AEN20261007005700315)."}],
        "us_korea_deals": {"investment_package": {"known_deals": [
            {"company": "Encinal gas-fired power plant", "value": "$22.3B"}]}},
    }
    s = podcast.build_script(digest)
    problems = []
    for item in digest["top_stories"]:
        told = podcast._story(item)
        if told.split(".")[0] not in s:
            problems.append(f"top story not narrated: {item['headline']!r}")
    if "That's from" in s:
        problems.append("per-story attribution is back (removed at the editor's request)")
    for label, pattern in (("Hangul", r"[\uac00-\ud7a3]"), ("a URL", r"https?://"),
                           ("markdown asterisks", r"\*"), ('a bare "US"', r"\bUS\b"),
                           ("an unexpanded DPRK/ROK", r"\b(DPRK|ROK)\b"),
                           ('"the North Korea"', r"\bthe (North|South) Korea\b(?!n)"),
                           ('"North Korean" used as a noun', r"North Korean rejects")):
        if re.search(pattern, s):
            problems.append(f"narration still contains {label}")
    # The won: USD/KRW falling means the won strengthened. Saying "the won ...
    # down" reverses it, so the figure must be spoken as the dollar in won.
    if "The dollar is at 1,338 won, down about 0.4 percent" not in s:
        problems.append("USD/KRW not spoken as the dollar in won")
    if "Issue " in s:
        problems.append("issue number spoken on air")
    # The editor asked for the top KCNA articles every day, including one a
    # top story already told; the repeat filter used to drop all three.
    for a in digest["kcna_delta"]["top_articles"]:
        if podcast.speakable(a["headline"]).rstrip(".") not in s:
            problems.append(f"top KCNA article not narrated: {a['headline']!r}")
    if re.search(r"@\w|AEN\d|Corroborated", s):
        problems.append("social handle, wire ID or analyst footnote read aloud")
    # Segment breaks become silence: they must never be voiced or transcribed.
    if podcast.SEGMENT not in s:
        problems.append("no segment breaks, so no pauses between sections")
    if any(podcast.SEGMENT in c for c, _ in podcast._chunks(s)) or podcast.SEGMENT in podcast.spoken_text(s):
        problems.append("a segment marker would be read aloud or shown in the transcript")
    return problems


# ── Capitol Hill and Korea and the World ─────────────────────────────────────

def _hill_world_sample() -> dict:
    """A digest with both new sections and a collected hearing schedule."""
    return {
        "digest_date": "2026-10-19",
        "re_line": "Hill keeps USFK floor · Poland K2 deal",
        "morning_memo": ["a", "b", "c"],
        "top_stories": [{"headline": "DPRK fires ballistic missile", "source": "Yonhap",
                         "body": "The Joint Chiefs said the missile flew 300 km.", "url": "https://x/1"}],
        "capitol_hill": [
            {"url": "https://thehill.com/x", "source": "The Hill", "chamber": "Both",
             "category": "Legislation", "bill": "S. 2296",
             "headline": "NDAA keeps 28,500-troop floor for US forces in South Korea",
             "body_text": "The compromise bill bars funds to cut the force below 28,500."},
            {"url": "https://rollcall.com/x", "source": "Roll Call", "chamber": "Senate",
             "category": "Letter", "bill": None,
             "headline": "Senators urge visa fix for Korean workers at Georgia plant",
             "body_text": "Twelve senators asked the State Department to create a visa category."}],
        "korea_world": [
            {"url": "https://notesfrompoland.com/x", "source": "Notes from Poland", "region": "Europe",
             "category": "Defense exports", "headline": "Poland signs second K2 tank contract",
             "body_text": "Warsaw said the contract covers 180 tanks."}],
        "hill_calendar": [
            {"date": "2026-10-19", "time": "10:00 AM", "chamber": "Senate",
             "committee": "Foreign Relations", "title": "Hearings to examine the U.S.-ROK alliance.",
             "url": "https://www.senate.gov/committees/hearings_meetings.htm", "source": "Senate committee schedule"},
            {"date": "2026-10-22", "time": "", "chamber": "House", "committee": "House Foreign Affairs",
             "title": "Hearing: North Korea's Sanctions Evasion - October 22, 2026",
             "url": "https://foreignaffairs.house.gov/x", "source": "HFAC schedule"}],
    }


def check_new_sections_are_wired() -> list[str]:
    """Both sections reach every stage: caps, trim, validation, prompt, count, corpus.

    A section added to the prompt but not to the validator's list is never
    checked against the input feed, which is how an invented item ships.
    """
    import run
    import length_budget
    import corpus
    import podcast
    import weekly
    from digest import _count_digest_words
    problems = []
    text = _prompt_text()
    if run.SECTION_CAPS.get("capitol_hill") != (0, 4):
        problems.append(f"capitol_hill cap is {run.SECTION_CAPS.get('capitol_hill')}, expected (0, 4)")
    if run.SECTION_CAPS.get("korea_world") != (0, 3):
        problems.append(f"korea_world cap is {run.SECTION_CAPS.get('korea_world')}, expected (0, 3)")
    trimmed = {name for name, _floor in length_budget.TRIM_ORDER}
    for sec in ("capitol_hill", "korea_world"):
        if sec not in trimmed:
            problems.append(f"{sec} is not in length_budget.TRIM_ORDER")
        if sec not in run._ALL_ITEM_SECTIONS:
            problems.append(f"{sec} is not validated against the input feed (run._ALL_ITEM_SECTIONS)")
        if sec not in run._DEDUP_SECTIONS:
            problems.append(f"{sec} is not deduplicated (run._DEDUP_SECTIONS)")
        if sec not in corpus._DIGEST_ITEM_SECTIONS:
            problems.append(f"{sec} is not recorded in the corpus")
        if sec not in podcast._SCRIPT_KEYS:
            problems.append(f"{sec} is not given to the written audio script or its check")
        if f"- {sec}: array of 0-" not in text:
            problems.append(f"the prompt has no {sec} schema entry")
        if not weekly._summarize_digest({sec: [{"headline": "h"}]}).get(sec):
            problems.append(f"the weekly review does not read {sec}")
    if "hill_calendar" not in podcast._SCRIPT_KEYS:
        problems.append("hill_calendar is not visible to the audio script check")
    floor = dict(length_budget.TRIM_ORDER).get("rok_government")
    if floor != 5:
        problems.append(f"rok_government trim floor is {floor}, expected 5")
    d = _hill_world_sample()
    if _count_digest_words(d) <= _count_digest_words({k: v for k, v in d.items()
                                                     if k not in ("capitol_hill", "korea_world")}):
        problems.append("the word count does not see the new sections")
    for sec in ("capitol_hill", "korea_world"):
        block = text.split(f"- {sec}:", 1)[-1][:2500]
        if "empty" not in block.lower() or "memory" not in block.lower():
            problems.append(f"{sec}'s instructions do not say empty is fine and never to fill from memory")
    if "FM Cho Tae-yul" in text:
        problems.append("the rok_government example still names the previous foreign minister")
    return problems


def _prompt_text() -> str:
    """The user prompt with a small payload, built without any network call."""
    from digest import build_user_prompt
    payload = {"tier1": [], "tier2": [], "tier3": [], "tier4": []}
    return build_user_prompt(payload, "Monday, October 19, 2026")


def check_new_streams_reach_the_model() -> list[str]:
    """A Hill or world article must be in the prompt even on a 300-article day.

    The tier-1 block is cut at 140 by rank; an item from a feed that is mostly
    about something else would lose that cut every time. The streams have
    their own blocks, and the tier-1 block leaves them out so nothing is
    shown twice.
    """
    from digest import build_user_prompt
    problems = []
    filler = [{"source": "Yonhap English", "title": f"Seoul item {i}", "url": f"https://y/{i}",
               "summary": "", "lang": "EN"} for i in range(300)]
    hill = {"source": "Roll Call", "title": "House passes Korea visa bill", "lang": "EN",
            "url": "https://rollcall.com/hill-korea-visa", "summary": "", "stream": "capitol_hill"}
    world = {"source": "Korea-Poland", "title": "Poland signs K2 deal with Hyundai Rotem", "lang": "EN",
             "url": "https://example.org/poland-k2", "summary": "", "stream": "korea_world"}
    payload = {"tier1": filler + [hill, world], "tier2": [], "tier3": [], "tier4": [],
               "capitol_hill_articles": [hill], "korea_world_articles": [world]}
    text = build_user_prompt(payload, "Monday, October 19, 2026")
    for a in (hill, world):
        n = text.count(a["url"])
        if n == 0:
            problems.append(f"{a['source']} article never reaches the prompt")
        elif n > 1:
            problems.append(f"{a['source']} article is shown to the model {n} times")
    if digest._prompt_band({"source": "CRS Reports"}) != 0 or \
            digest._prompt_band({"source": "Congress.gov Bills"}) != 0:
        problems.append("Congress's own documents are not ranked as primary sources")
    return problems


def check_new_streams_sourcing() -> list[str]:
    """The Hill and world feeds follow the sourcing rules in CLAUDE.md.

    Not exempt from the relevance filter (none is Korea-relevant by
    construction), filtered so a National Assembly story or a Japan story does
    not leak in, and every outlet the prompt names for them is collected.
    """
    class _E(dict):
        def get(self, key, default=None):
            return dict.get(self, key, default)

    problems = []
    for name in list(collect.CAPITOL_HILL_FEEDS) + list(collect.KOREA_WORLD_FEEDS):
        if name in collect.KOREA_NATIVE_FEEDS:
            problems.append(f"{name!r} is exempt from the Korea filter but is not Korea-only")
    cases = [
        (collect._is_hill_relevant(_E(title="NDAA keeps troop floor in South Korea", summary=""),
                                   "The Hill Defense"), True, "an NDAA Korea item"),
        (collect._is_hill_relevant(_E(title="Pentagon budget fight continues", summary=""),
                                   "The Hill Defense"), False, "a non-Korea defense item"),
        (collect._is_hill_relevant(_E(title="Korean lawmakers clash at National Assembly audit",
                                      summary="lawmakers"), "US Congress Korea"), False,
         "a National Assembly item from a search feed"),
        (collect._is_hill_relevant(_E(title="Senators introduce bill on South Korea deterrence",
                                      summary=""), "US Congress Korea"), True, "a Senate bill on Korea"),
        (collect._is_world_relevant(_E(title="Poland signs K2 tank deal with South Korea", summary="")),
         True, "a Poland arms deal"),
        (collect._is_world_relevant(_E(title="South Korea and Japan extend currency swap", summary="")),
         False, "a Japan-Korea item (northeast_asia's)"),
    ]
    for got, want, label in cases:
        if got != want:
            problems.append(f"filter {'drops' if want else 'admits'} {label}")
    # Every outlet the Hill block names must be collected.
    import inspect
    src = inspect.getsource(digest.build_user_prompt)
    m = re.search(r"Collected from ([^)]+)\)", src)
    if not m:
        problems.append("the CAPITOL HILL block no longer says what it is collected from")
    else:
        feeds = " ".join(_all_feed_names()).lower()
        for outlet in (o.strip() for o in m.group(1).split(",")):
            token = outlet.lower().replace("committee sites", "hfac")
            if token not in feeds:
                problems.append(f"the Hill block names {outlet!r} but no feed collects it")
    # The calendar: dated by the schedule, filtered by title, empty on failure.
    from datetime import date
    xml = (b'<?xml version="1.0"?><css_meetings_scheduled><meetings>'
           b'<meeting><committee>Foreign Relations</committee><date>21-OCT-2026 10:00 AM</date>'
           b'<matter>Hearings to examine the U.S.-Republic of Korea alliance.</matter></meeting>'
           b'<meeting><committee>Agriculture</committee><date>21-OCT-2026 10:00 AM</date>'
           b'<matter>Hearings to examine the farm bill.</matter></meeting>'
           b'<meeting><committee>Armed Services</committee><date>02-DEC-2026 09:30 AM</date>'
           b'<matter>Hearings to examine USFK posture.</matter></meeting></meetings></css_meetings_scheduled>')
    ev = collect.filter_hill_events(collect._parse_hill_schedule(xml, "Senate committee schedule"),
                                    date(2026, 10, 19), date(2026, 10, 26))
    if [e["date"] for e in ev] != ["2026-10-21"]:
        problems.append(f"calendar filter kept {[e['title'] for e in ev]}, expected only the Korea hearing")
    if collect._parse_hill_schedule(b"<html>not a schedule", "Senate committee schedule"):
        problems.append("an unreadable schedule produced events")
    return problems


def check_new_sections_render() -> list[str]:
    """Placed after US-Korea and Northeast Asia, hidden when empty, dark-mode safe."""
    import copy
    import preview
    import render as r
    problems = []
    d = copy.deepcopy(preview.DIGEST)
    d.update(copy.deepcopy(_hill_world_sample()))
    html = r.render(copy.deepcopy(d))
    pos = {a: html.find(f'name="{a}"') for a in ("trade", "hill", "business", "nea", "world")}
    if pos["hill"] < 0 or pos["world"] < 0:
        problems.append("a new section did not render with items present")
    else:
        if pos["trade"] >= 0 and not pos["trade"] < pos["hill"]:
            problems.append("Capitol Hill renders before the US-Korea material")
        if pos["business"] >= 0 and not pos["hill"] < pos["business"]:
            problems.append("Capitol Hill is not directly after the US-Korea material")
        if pos["nea"] >= 0 and not pos["nea"] < pos["world"]:
            problems.append("Korea and the World renders before Northeast Asia")
    if "Coming up on the Hill" not in html:
        problems.append("no Coming up on the Hill line with a hearing in the week")
    head = html[:html.find('name="top-stories"')]
    if "Senate Foreign Relations hearing" not in head:
        problems.append("today's hearing is missing from the Happening today strip")
    missing = r._check_dark_coverage(html)
    if missing:
        problems.append("dark mode: " + "; ".join(missing))
    # Empty: no bar, no anchor.
    e = copy.deepcopy(d)
    e["capitol_hill"], e["korea_world"], e["hill_calendar"] = [], [], []
    h2 = r.render(e)
    for a in ("hill", "world"):
        if f'name="{a}"' in h2:
            problems.append(f"#{a} renders with nothing in it")
    # Calendar feeds failed: the items still render, with no calendar line.
    f = copy.deepcopy(d)
    f.pop("hill_calendar")
    h3 = r.render(f)
    if 'name="hill"' not in h3 or "Coming up on the Hill" in h3:
        problems.append("Capitol Hill does not render cleanly without the calendar")
    return problems


def check_new_sections_audio() -> list[str]:
    """Narrated when present, silent when empty, and no false alarms from the check."""
    import copy
    import podcast
    problems = []
    d = _hill_world_sample()
    s = podcast.build_script(d)
    for lead in ("On Capitol Hill.", "Beyond the region.", "Coming up on the Hill"):
        if lead not in s:
            problems.append(f"audio script has no {lead!r} segment")
    if "Senate Foreign Relations hearing" not in s.split("\nFirst, ")[0]:
        problems.append("today's hearing is not in the audio's Happening today line")
    e = copy.deepcopy(d)
    e["capitol_hill"], e["korea_world"], e["hill_calendar"] = [], [], []
    s2 = podcast.build_script(e)
    if "Capitol Hill" in s2 or "Beyond the region" in s2:
        problems.append("audio reads an empty new section")
    # A written script that says only what the brief says must pass the check.
    when = podcast._spoken_date(d)
    written = (f"This is the Korea Daily Brief from the CSIS Korea Chair. It's {when}.\n\n"
               "On Capitol Hill, the NDAA keeps a 28,500-troop floor for U.S. forces in South Korea. "
               "Senate Foreign Relations holds a hearing today on the alliance. On Thursday, House "
               "Foreign Affairs looks at North Korea's sanctions evasion.\n\n"
               "Beyond the region, Poland signed a second K2 tank contract, covering 180 tanks.\n\n"
               f"That's the Korea Daily Brief for {when}. The full text, with a link to every "
               "source, is in today's email.")
    alarms = podcast.check_script(written, d, when)
    if alarms:
        problems.append("check_script flags facts the brief carries: " + "; ".join(alarms[:4]))
    return problems


def check_audio_extras():
    """Chapters, transcript, feed tags, player page and AI disclosure, offline.

    Built from a made-up timeline, no voice or network needed. Also proves the
    rule that matters most: when every new step fails, the episode is still
    produced exactly as before.
    """
    import os
    import tempfile
    import xml.etree.ElementTree as ET
    from pathlib import Path
    import listen
    import podcast
    problems = []
    when = "Sunday, October 18"
    digest = {"digest_date": "Sunday, October 18, 2026", "re_line": "DPRK torpedo · ROK surplus",
              "top_stories": [
                  {"headline": "North Korea tests AI torpedo — sixth event", "source": "Reuters",
                   "url": "https://example.com/a", "body": "KCNA reported a torpedo test."},
                  {"headline": "ROK trade surplus nears record", "source": "Yonhap",
                   "url": "https://example.com/b", "body": "The surplus grew."}]}
    script = (f"{podcast.opening_line(when)}\n\nThree things today: a torpedo and trade.\n\n---\n\n"
              "First, North Korea tests an AI torpedo. KCNA reported a torpedo test.\n\n---\n\n"
              "Second, South Korea's trade surplus nears a record. The surplus grew.\n\n---\n\n"
              "Finally, the markets. That's the Korea Daily Brief for Sunday, October 18.")
    # Disclosure: spoken in the opening, printed in feed and page, never flagged.
    if podcast.SPOKEN_DISCLOSURE not in podcast.opening_line(when):
        problems.append("the opening line no longer carries the AI disclosure")
    if podcast.SPOKEN_DISCLOSURE not in podcast.build_script(digest).split("\n")[0]:
        problems.append("the assembled script does not open with the disclosure")
    flagged = podcast.check_script(podcast.opening_line(when) + " The surplus grew.", digest, when)
    if flagged:
        problems.append(f"check_script flags the disclosure line: {flagged}")
    for needle in ("{opening}", '"First, ..."', "ten minutes", "email for the sources"):
        if needle not in podcast._SCRIPT_SYSTEM:
            problems.append(f"script prompt lost its signposting: {needle!r}")
    # A timeline as _master reports it: 4 segments, one split over two requests.
    chunks = [{"start": 2.4, "end": 9.0, "segment": 0, "text": podcast.segments(script)[0]},
              {"start": 10.5, "end": 14.0, "segment": 1, "text": "First, North Korea tests an AI torpedo."},
              {"start": 14.7, "end": 18.0, "segment": 1, "text": "KCNA reported a torpedo test."},
              {"start": 19.5, "end": 25.0, "segment": 2, "text": podcast.segments(script)[2]},
              {"start": 26.5, "end": 30.0, "segment": 3, "text": podcast.segments(script)[3]}]
    if [n for _, _, n in podcast._chunks_indexed(script)] != [0, 1, 2, 3]:
        problems.append("requests are not tagged with their segment")
    ch = listen.build_chapters(chunks, script, digest, "written", 33.0)
    if [c["startTime"] for c in ch] != [0.0, 10.5, 19.5, 26.5] or ch[-1]["endTime"] != 33.0:
        problems.append(f"chapter times wrong: {[c['startTime'] for c in ch]}")
    if not ch[1]["title"].startswith("North Korea tests AI torpedo") or ch[1].get("url") != "https://example.com/a":
        problems.append(f"a lead story chapter is not titled and linked from its story: {ch[1]}")
    v = listen.vtt(chunks)
    if not v.startswith("WEBVTT\n") or "00:00:10.500 --> " not in v or "\n\n\n" in v:
        problems.append("VTT is malformed or mistimed")
    # The feed: well-formed, namespaced, still blocked, OP3 switchable.
    ep = {"date": "2026-10-18", "title": "Korea Daily Brief | Sunday, October 18", "summary": "S",
          "file": "digest_2026-10-18.mp3", "bytes": 1, "seconds": 600,
          "chapters": "digest_2026-10-18.chapters.json", "transcript": "digest_2026-10-18.vtt",
          "transcript_text": "digest_2026-10-18.txt", "page": "listen/2026-10-18.html",
          "notes": listen.show_notes(digest)}
    old = os.environ.pop("PODCAST_OP3", None)
    try:
        root = ET.fromstring(podcast._feed_xml([ep], "https://h.example/x"))
        ns = "{https://podcastindex.org/namespace/1.0}"
        item = root.find("channel/item")
        if item.find(f"{ns}chapters") is None or len(item.findall(f"{ns}transcript")) != 2:
            problems.append("podcast:chapters / podcast:transcript missing or not namespaced")
        if root.find("channel/{http://www.itunes.com/dtds/podcast-1.0.dtd}block") is None:
            problems.append("itunes:block was dropped from the feed")
        if not item.find("enclosure").get("url").startswith("https://op3.dev/e/h.example/"):
            problems.append("OP3 prefix not on by default")
        desc = item.find("description").text
        from html import escape
        if "https://example.com/a" not in desc or escape(podcast.DISCLOSURE) not in desc or "digest_2026-10-18.html" not in desc:
            problems.append("show notes lack source links, the brief link, or the disclosure")
        os.environ["PODCAST_OP3"] = "0"
        if podcast.measured("https://h.example/x.mp3") != "https://h.example/x.mp3":
            problems.append("PODCAST_OP3=0 does not turn the prefix off")
    except ET.ParseError as e:
        problems.append(f"podcast.xml is not well-formed: {e}")
    finally:
        os.environ.pop("PODCAST_OP3", None)
        if old is not None:
            os.environ["PODCAST_OP3"] = old
    page = listen.render_page(date_slug="2026-10-18", digest=digest, web_base="https://h.example/x",
                              minutes=10, chapters=ch, chunks=chunks, script=script,
                              notes=listen.show_notes(digest), episodes=None)
    for needle, what in (("<audio", "an audio player"), ('data-t="10.5"', "seekable chapters"),
                         ("Transcript", "the transcript"), ("../digest_2026-10-18.html", "a link to the brief"),
                         ("podcast://h.example/x/podcast.xml", "Apple Podcasts"), ("overcast://", "Overcast"),
                         ("pktc://subscribe/", "Pocket Casts"), ("Copy feed URL", "copy feed"),
                         (podcast.DISCLOSURE.replace("'", "&#x27;"), "the AI disclosure"),
                         ("prefers-color-scheme:dark", "dark mode")):
        if needle not in page:
            problems.append(f"player page lacks {what}")
    if "spotify" in page.lower():
        problems.append("player page offers Spotify, which cannot take a private feed")
    # Failure never blocks: every new step raising still yields the episode.
    saved = (podcast.synthesize, podcast._previous_issue, listen.build_chapters,
             listen.write_pages, listen.show_notes, listen.vtt)

    def boom(*a, **k):
        raise RuntimeError("injected")

    def fake_synth(s, path):
        path.write_bytes(b"\x00" * 100)
        return {"tts_model": "m", "tts_voice": "v", "audio_bytes": 100, "audio_seconds": 600,
                "_chunks": chunks}
    import contextlib
    import io
    # produce() reports these injected failures as GitHub annotations, which is
    # right in a real run and wrong here: printed straight through, every daily
    # run showed "Player page skipped: injected" beside the real warnings.
    # Captured instead, and checked, so the warning path is still proven.
    captured = io.StringIO()
    try:
        podcast.synthesize, podcast._previous_issue = fake_synth, (lambda s: None)
        listen.build_chapters = listen.write_pages = listen.show_notes = listen.vtt = boom
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(captured):
            rec = podcast.produce(digest, Path(tmp), "", "2026-10-18")
            if not rec or "listen_page" in rec or "_chunks" in rec:
                problems.append("a failing chapter/page step changed or blocked the episode")
            if not (Path(tmp) / "latest.mp3").exists():
                problems.append("a failing chapter/page step stopped latest.mp3")
        if "::warning title=Player page skipped::injected" not in captured.getvalue():
            problems.append("a failing player page no longer raises an annotation for the operator")
    except Exception as e:                                      # noqa: BLE001
        problems.append(f"a failing new audio step raised out of produce(): {e}")
    finally:
        (podcast.synthesize, podcast._previous_issue, listen.build_chapters,
         listen.write_pages, listen.show_notes, listen.vtt) = saved
    return problems


def check_korean_units_are_scaled() -> list[str]:
    """847억 달러 is $84.7B. Printed as $847B, and as "$1 trillion" in the memo.

    The prompt states the rule; magnitude_warnings must catch a figure ten
    times its cited Korean source even when it is not a trade balance, and
    must not flag the correct figure or the $350B pledge.
    """
    import run
    problems = []
    if "847억 달러 is $84.7 billion" not in digest.SYSTEM_PROMPT:
        problems.append("the prompt has no 억/조 conversion rule")
    src = "뉴시스 — 대미 무역흑자 847억 달러…美 1000억弗 돌파 목전"
    bad = {"key_stat": {"number": "$847B", "label": "Exports to the US, Jan-Sep",
                        "context": "Shipments reached $847B.", "source": src},
           "morning_memo": ["Exports to the US hit $847B through September."]}
    found = " ".join(run.magnitude_warnings(bad))
    if "$847B" not in found:
        problems.append("a $847B figure from an 847억 달러 source is not flagged")
    if "morning memo" not in found:
        problems.append("the same wrong figure in the morning memo is not flagged")
    good = {"key_stat": {"number": "$84.7B", "label": "Exports to the US",
                         "context": "Shipments reached $84.7B; the $350B pledge is unchanged.",
                         "source": src}}
    if run.magnitude_warnings(good):
        problems.append(f"a correct $84.7B is flagged: {run.magnitude_warnings(good)}")
    return problems


def check_process_notes_never_reach_readers() -> list[str]:
    """'See source article for name', '(implied)', 'per scope rules' all shipped."""
    import run
    problems = []
    if "Never describe your own process" not in digest.SYSTEM_PROMPT.splitlines()[-1]:
        problems.append("the process-note rule is not the last line of the system prompt")
    d = {
        "rok_personnel": [{"name": "See source article for name", "position": "Vice minister",
                           "action": "appointed"},
                          {"name": "Kim Ji-yong", "position": "SCIA director", "action": "nominated"}],
        "rok_assembly": [{"committee": "National Assembly (unspecified committee)",
                          "action": "Audit of KEPCO breach", "detail": "Members pressed KEPCO."},
                         {"committee": "Intelligence Committee (implied)", "action": "NIS briefing",
                          "detail": "The NIS briefed members on the DPRK."}],
        "us_korea_deals": {"deals": [{"headline": "Hyundai $15.5B India investment",
                                      "parties": "Hyundai Motor Group — India",
                                      "detail": "A Korea-India deal; excluded per scope rules."}]},
        "top_stories": [{"headline": "Seoul demands apology", "url": "https://x/1",
                         "body": "Seoul recalled its envoy. It continues to demand an apology as of today's reporting."}],
    }
    run._strip_process_notes(d)
    run._drop_nameless_personnel(d)
    text = json.dumps(d, ensure_ascii=False)
    for phrase in ("See source", "(implied)", "unspecified", "scope rules", "today's reporting"):
        if phrase.lower() in text.lower():
            problems.append(f"{phrase!r} survived the validators")
    if [p["name"] for p in d["rok_personnel"]] != ["Kim Ji-yong"]:
        problems.append("the nameless personnel entry was not dropped, or a real one was")
    if d["us_korea_deals"]["deals"]:
        problems.append("a deal whose detail was only a process note was kept")
    if d["top_stories"][0]["body"] != "Seoul recalled its envoy.":
        problems.append(f"the note sentence was not cut cleanly: {d['top_stories'][0]['body']!r}")
    if not run._PLACEHOLDER_NAME_RE.search("See source article for name"):
        problems.append("_PLACEHOLDER_NAME_RE does not catch 'see source'")
    return problems


def check_non_us_deals_are_filtered() -> list[str]:
    """Match the US on the headline and parties, never on the detail or note."""
    import run
    problems = []
    deals = [
        {"headline": "Hyundai Motor Group announces $15.5B investment in India",
         "parties": "Hyundai Motor Group — India operations",
         "detail": "Not a us-korea deal.", "note": "us-korea scope", "sector": "Business"},
        {"headline": "Samsung Heavy wins Oceania LNG carrier order", "parties": ["Samsung Heavy"],
         "detail": "Industry analysts expect more business."},
        {"headline": "LS Electric wins transformer order in US", "parties": ["LS Electric"]},
        {"headline": "Hanwha Ocean expands Philly Shipyard",
         "parties": ["Hanwha Ocean", "Philly Shipyard"], "detail": ""},
        {"headline": "Trump touts Hyundai's Georgia plant", "parties": "Hyundai Motor Group"},
    ]
    d = {"us_korea_deals": {"deals": deals}}
    run._filter_non_us_deals(d)
    kept = [x["headline"] for x in d["us_korea_deals"]["deals"]]
    if any("India" in h or "Oceania" in h for h in kept):
        problems.append(f"a non-US deal passed: {kept}")
    if len(kept) != 3:
        problems.append(f"a US deal was dropped: {kept}")
    return problems


def check_calendar_items_render() -> list[str]:
    """26 model items over ten days rendered as 0: the shapes did not match.

    The model returned {date, event}; merge and render read {month, day,
    headline}. Both must now render, in Upcoming and in Happening today, and
    in the audio edition; past, undated and off-topic items must not.
    """
    import korea_calendar
    import podcast
    import render
    import run
    from datetime import date
    problems = []
    text = _prompt_text()
    block = text.split("- calendar_watch:", 1)[-1][:1200]
    for field in ('month ("Oct")', "day (integer", "headline (under 12 words)", "detail", "source"):
        if field not in block:
            problems.append(f"the calendar_watch schema does not name {field!r}")
    today = date(2026, 10, 18)
    items = [
        {"date": "Oct 19-23, 2026", "event": "HD Hyundai Heavy union widens partial strike",
         "detail": "Shipbuilding output at risk.", "source": "경향신문"},
        {"month": "Oct", "day": 20, "headline": "Hoguk field exercise begins",
         "detail": "Annual ROK exercise.", "source": "Yonhap"},
        {"date": "Oct 18, 2026", "event": "Telemedicine rules published", "source": "동아일보"},
        {"date": "Oct 20, 2026", "event": "KBO semi-playoff Game 3 — KIA vs LG", "source": "동아일보"},
        {"date": "November 2026 (no fixed date)", "event": "SCM after the midterms", "source": "Yonhap"},
        {"date": "Oct 12, 2026", "event": "Audit hearing", "source": "Newsis"},
    ]
    merged = korea_calendar.merge(items, today)
    heads = [m["headline"] for m in merged]
    for want in ("HD Hyundai Heavy union widens partial strike", "Hoguk field exercise begins"):
        if want not in heads:
            problems.append(f"{want!r} did not survive merge")
    for unwanted in ("KBO", "SCM", "Audit hearing"):
        if any(unwanted in h for h in heads):
            problems.append(f"{unwanted!r} should have been dropped from the calendar")
    d = {"digest_date": "Sunday, October 18, 2026", "calendar_watch": items}
    if "Telemedicine rules published" not in render._happening_today(d):
        problems.append("Happening today does not read a {date, event} item")
    if "Telemedicine rules published" not in podcast.happening_today(d):
        problems.append("the audio's happening_today does not read a {date, event} item")
    norm = {"calendar_watch": [dict(i) for i in items]}
    run._normalize_calendar(norm, today=today)
    if not all({"month", "day", "headline"} <= set(i) for i in norm["calendar_watch"]):
        problems.append("postprocessing leaves calendar items without month/day/headline")
    html = render.render({"digest_date": "Sunday, October 18, 2026", "calendar_watch": items,
                          "top_stories": [], "morning_memo": []})
    if "Hoguk field exercise begins" not in html or 'id="upcoming"' not in html:
        problems.append("Upcoming does not render the model's items")
    return problems


def check_email_fits_gmail() -> list[str]:
    """Gmail clips past 102,400 bytes. The byte guard must trim until it fits.

    Trims only from length_budget's TRIM_ORDER, so top stories survive, and
    stops at the floors rather than looping.
    """
    import run
    problems = []
    if run.EMAIL_BYTE_BUDGET >= run.GMAIL_CLIP_BYTES:
        problems.append("the byte budget is not under Gmail's clip")

    def fake_render(d):
        n = sum(len(d.get(k) or []) for k in ("also_today", "overnight_items", "business_economy",
                                              "top_stories", "social_statements"))
        return "<html><body>" + ("x" * 5_000 + "\n") * n + "</body></html>"
    d = {"top_stories": [{}] * 4, "overnight_items": [{}] * 8, "business_economy": [{}] * 6,
         "also_today": [{"headline": f"wire {i}"} for i in range(6)],
         "social_statements": [{}] * 3}
    html, log = run.fit_email_bytes(d, fake_render, budget=100_000)
    if len(html.encode()) > 100_000:
        problems.append(f"fit_email_bytes left {len(html.encode()):,} bytes over a 100,000 budget")
    if len(d["top_stories"]) != 4:
        problems.append("fit_email_bytes trimmed top_stories")
    if len(d["also_today"]) >= 6 or not log:
        problems.append("fit_email_bytes did not trim from the TRIM_ORDER tail first")
    # A brief that cannot fit stops at the floors instead of looping.
    huge = {"top_stories": [{}] * 40}
    html, log = run.fit_email_bytes(huge, fake_render, budget=1_000)
    if not log or "floor" not in log[-1]:
        problems.append("fit_email_bytes does not report when nothing more may be trimmed")
    if "1,700-2,000 WORDS" not in _prompt_text():
        problems.append("the prompt's length band is not the one the ceiling enforces")
    return problems


def check_english_only():
    """No Korean script on the page except a translated quote."""
    import english
    problems = []
    d = {"top_stories": [{"headline": "x", "source": "뉴시스 / 경향신문",
                          "src_line": "뉴시스 — '대중·대미 무역수지 4년만에' ", "body": "A 경향신문 editorial said so."}],
         "rok_government": [{"ministry": "MND", "ministry_korean": "국방부", "source_label": "뉴시스"}],
         "public_sentiment": {"party_ruling": {"party": "Democratic Party", "party_kr": "더불어민주당"}},
         "social_statements": [{"quote_text": 'Lee said "국민이 주인" ("the people are the owners").'}],
         "overnight_items": [{"headline": "y", "body": "Officials said 비상 without explanation."}]}
    warns = english.apply(d)
    if d["top_stories"][0]["source"] != "Newsis / Kyunghyang Shinmun":
        problems.append(f"outlet names not mapped: {d['top_stories'][0]['source']!r}")
    if english.HANGUL.search(d["top_stories"][0]["src_line"]):
        problems.append("Korean headline left in a source line")
    if "ministry_korean" in d["rok_government"][0] or "party_kr" in d["public_sentiment"]["party_ruling"]:
        problems.append("Korean-only label fields kept")
    if "Kyunghyang Shinmun editorial" not in d["top_stories"][0]["body"]:
        problems.append("outlet name in prose not mapped")
    if any("social_statements" in w for w in warns):
        problems.append("a translated quote was flagged")
    if not any("overnight_items" in w for w in warns):
        problems.append("untranslated Korean in prose was not reported")
    return problems


def check_audio_formatting() -> list[str]:
    """The house rules for what the voice is sent, and the shape of the episode.

    Numbers, money, dates and acronyms are written for the ear; no character
    a voice reads literally or skips reaches it; the cues that open each
    segment are the same in the prompt, the assembled script and the chapter
    titles; the assembled script holds to about ten minutes; and the fact
    check still catches an invented figure, name or quotation after the
    brief is compared in its spoken form.
    """
    import re
    from array import array
    import listen
    import podcast
    problems = []
    sp = podcast.speakable
    for raw, want in (
            ("Exports hit $84.7B", "84.7 billion dollars"),
            ("a first-ever annual $1 trillion surplus", "1 trillion dollar surplus"),
            ("totaling $49.9B announced in Oct 2025", "49.9 billion dollars announced in October 2025"),
            ("KOSPI -7.6%; won +0.4%", "KOSPI down 7.6 percent; won up 0.4 percent"),
            ("polled Oct 13-15", "polled October 13 to 15"),
            ("Q3 revenue; in Q3 2026", "third-quarter revenue; in the third quarter of 2026"),
            ("₩1.2 trillion", "1.2 trillion won"),
            ("~28,500 USFK troops", "about 28,500 U.S. Forces Korea troops"),
            ("UNC clarified; the armistice grants UNC authority", "The U.N. Command clarified; the armistice grants U.N. Command authority"),
            ("from UNC's perspective", "from the U.N. Command's perspective"),
            ("IAEA said", "The International Atomic Energy Agency said"),
            ("the NDAA keeps the floor", "the National Defense Authorization Act keeps"),
            ("a CRS report", "a Congressional Research Service report"),
            ("the BOK held", "the Bank of Korea held"),
            ("wartime operational control (OPCON) transfer", "wartime operational control transfer"),
            ("an SLBM and a ICBM", "a submarine-launched ballistic missile and an intercontinental"),
            ("DPRK rejects ROK sovereignty claim", "North Korea rejects South Korean sovereignty claim"),
            ("NK-Russia ties; Daily NK", "North Korea-Russia ties; Daily N.K."),
            ("Gen. Xavier Brunson at 6:14 pm", "General Xavier Brunson at 6:14 p.m."),
            ("US and UN officials", "U.S. and U.N. officials"),
            ("Agency (중대범죄수사청 / SCIA) said", "Agency said"),
            ("Lee said \"고인의 희생을 잊지 않겠습니다. ['I will not forget.']\"", "I will not forget."),
            ("North Korea SLCM test (5th in month)", "test, 5th in month."),
            ("Bank of Korea · rate → 2.50% ▲", "Bank of Korea, rate to 2.50 percent up.")):
        got = sp(raw)
        if want.lower() not in got.lower():
            problems.append(f"speakable({raw!r}) gave {got!r}, wanted {want!r}")
    bad_chars = re.compile(r"[\u2014\u2015\u2013·→←↑↓▲▼•()\[\]{}/*%$&#@~\uac00-\ud7a3]|https?://")
    bad_abbr = re.compile(r"\b(?:DPRK|ROK|USFK|UNC|BOK|NDAA|CRS|IAEA|OPCON|SLCMs?|ICBMs?|MOFA|NK|US|UN|Q[1-4])\b")
    long = ("The ministry said the measure, first floated in the spring, would be reviewed again "
            "by the end of the year after consultations with lawmakers and industry. ") * 4
    d = {"digest_date": "2026-10-19", "re_line": "DPRK SLCM test · USFK sovereignty row · KOSPI -7.6%",
         "top_stories": [{"headline": f"Lead {n} headline", "source": "Yonhap",
                          "body": f"Story {n}: DPRK fired an SLCM (5th in month) — per KCNA — and "
                                  f"USFK said ~28,500 troops stay; IAEA cited Q3 data. " + long}
                         for n in range(4)],
         "kcna_delta": {"top_articles": [
             {"headline": "North Korea tests AI torpedo — KCNA", "source": "KCNA", "summary": "A test."},
             {"headline": "North Korea tests AI torpedo, KCNA says — Reuters", "source": "Reuters",
              "summary": "Reuters on the same test."}],
             "bottom_line": "The surge goes on.", "days_since_last_appearance": 1},
         "overnight_items": [{"headline": f"Wire item {n} on topic {chr(65 + n)}{n}x",
                              "body_text": f"Item {n} about subject{n} and matter{n}: " + long} for n in range(8)],
         "also_today": [{"headline": f"Also {n} zeta{n}", "body_text": f"Extra{n} detail{n}. " + long} for n in range(5)],
         "social_statements": [{"who": "FM Cho Hyun", "quote_text": "고인의 희생을 잊지 않겠습니다. ['US ties are firm.']"}],
         "public_sentiment": {"presidential_approval": {"value": "39%", "source": "Gallup Korea (Oct 13-15)",
                                                        "last_updated": "October 13-15, 2026", "trend": "up"}},
         "calendar_watch": [{"date": "Oct 20", "event": "ROK Hoguk exercise begins"},
                            {"date": "Nov", "event": "NDAA conference (CRS brief)"}],
         "market_indicators": {"kospi": {"value": "5,668.12", "change_pct": 2.03},
                               "bok_rate": {"value": "2.50%"}}}
    s = podcast.build_script(d)
    spoken = podcast.spoken_text(s)
    if bad_chars.search(spoken):
        problems.append(f"a character the voice would read reaches it: {bad_chars.search(spoken).group(0)!r}")
    if bad_abbr.search(spoken):
        problems.append(f"an acronym a listener can't decode reaches the voice: {bad_abbr.search(spoken).group(0)!r}")
    words = len(spoken.split())
    if words > podcast.AUDIO_WORDS + 60:
        problems.append(f"assembled script runs {words} words, over the ten-minute budget")
    for cue in (*podcast.LEAD_CUES[:4], podcast.CUE_PYONGYANG, podcast.CUE_MARKETS):
        if f"\n{cue} " not in "\n" + s:
            problems.append(f"assembled script lost a segment it must keep: {cue!r}")
    if "last seen in public yesterday" not in s or s.count("tests AI torpedo") > 1:
        problems.append("Pyongyang segment repeats an article or misstates Kim's absence")
    if "The Bank of Korea's base rate is 2.5 percent" not in s or "October 13 to 15" not in s:
        problems.append("markets or poll date not spoken as a presenter says them")
    # Cues: the same words in the prompt, the assembled script and the chapters.
    for cue in (*podcast.LEAD_CUES[:3], podcast.CUE_PYONGYANG, podcast.CUE_ROUNDUP,
                podcast.CUE_HILL, podcast.CUE_WORLD, podcast.CUE_MARKETS):
        if cue not in podcast._SCRIPT_SYSTEM:
            problems.append(f"the script prompt does not use the cue {cue!r}")
    titled = [lead for lead, _ in listen._LEAD_TITLES]
    for cue in podcast._SECTION_LEADS:
        if cue in podcast.LEAD_CUES:
            if not listen._ORDINAL_CUE.match(cue + " "):
                problems.append(f"a lead cue gets no lead-story chapter: {cue!r}")
        elif not any(cue.startswith(t) for t in titled):
            problems.append(f"a segment cue has no chapter title: {cue!r}")
    # The check compares against the brief in spoken form, and still catches inventions.
    when = podcast._spoken_date(d)
    if podcast.check_script(s, d, when):
        problems.append(f"check_script flags the assembled script: {podcast.check_script(s, d, when)[:3]}")
    for invented in ("U.S. Forces Korea said 29,500 troops stay.", "Senator Wexley said so.",
                     'The minister said: "We will never accept the new conditions at all."'):
        if not podcast.check_script(f"{podcast.opening_line(when)}\n\n{invented}", d, when):
            problems.append(f"check_script no longer catches an invention: {invented!r}")
    # Respellings reach the voice only.
    if podcast.for_voice("KOSPI and Choe Son Hui") != "Kospi and Chweh Son-hee" or "Kospi" in spoken:
        problems.append("pronunciation respellings leak into the script or do not reach the voice")
    # Pauses are exact: a request's padding is trimmed before they are added.
    pad = array("h", [0] * 2400 + [8000, -8000] * 1200 + [0] * 2400).tobytes()
    trimmed = len(podcast._trim_silence(pad)) // 2
    if not 2400 <= trimmed <= 2400 + 2 * int(podcast.EDGE_SILENCE * podcast.PCM_RATE) + 2:
        problems.append(f"silence trim left {trimmed} samples of a 2,400-sample sound")
    return problems


def check_design_preview_goes_only_to_preview_list():
    """The candidate design reaches DESIGN_PREVIEW_TO alone, with the same issue."""
    import json, os, run, render
    problems, sent = [], []
    d = {"digest_date": "2026-10-19", "re_line": "Test line for the subject",
         "top_stories": [{"headline": "Lead story", "body": "Body text.", "category_tag": "DPRK"}],
         "morning_memo": ["One.", "Two.", "Three."]}
    before = json.dumps(d, sort_keys=True)
    saved_env, saved_design = os.environ.get("DESIGN_PREVIEW_TO"), render.DESIGN
    try:
        os.environ.pop("DESIGN_PREVIEW_TO", None)
        if run.send_design_preview(d, lambda *a, **k: sent.append(k)):
            problems.append("a preview went out with DESIGN_PREVIEW_TO unset")
        os.environ["DESIGN_PREVIEW_TO"] = "preview@example.org"
        to = run.send_design_preview(d, lambda html, **k: sent.append((html, k)), "Lead story")
        if to != ["preview@example.org"] or len(sent) != 1:
            problems.append(f"preview recipients wrong: {to}")
        else:
            html, k = sent[0]
            if k.get("recipients") != ["preview@example.org"]:
                problems.append("preview not limited to the preview list")
            if not str(k.get("subject", "")).startswith("[Design preview]"):
                problems.append("preview subject not marked")
            if "%%V2N" in html or "Lead story" not in html:
                problems.append("preview did not render the candidate design")
        if render.DESIGN != saved_design:
            problems.append("preview left render.DESIGN changed for the live send")
        if json.dumps(d, sort_keys=True) != before:
            problems.append("preview mutated the digest")
        render.DESIGN = run.PREVIEW_DESIGN
        if run.send_design_preview(d, lambda *a, **k: sent.append(k)):
            problems.append("preview sent although the candidate is already live")
    finally:
        render.DESIGN = saved_design
        if saved_env is None:
            os.environ.pop("DESIGN_PREVIEW_TO", None)
        else:
            os.environ["DESIGN_PREVIEW_TO"] = saved_env
    return problems

def check_v2_status_line():
    """The Peninsula status line states only what the trackers hold; a missing fact drops out."""
    import render
    problems = []
    full = {"kcna_delta": {"kim_appearance_today": False, "days_since_last_appearance": 2,
                           "watch_flag": True, "silence_today": False},
            "bp_locations": [{"name": "A", "status": "alert"}, {"name": "B", "status": "elevated"},
                             {"name": "C", "status": "normal"}],
            "_bp_changes": ["A", "C"]}
    want = ["Kim last seen 2 days ago.", "KCNA watch flag up.",
            "New reporting at 2 of 3 monitored sites.", "Elevated or alert at 2 sites."]
    if render._v2_status_facts(full) != want:
        problems.append(f"full data gave {render._v2_status_facts(full)}")
    cases = [
        ("no kcna_delta", {k: v for k, v in full.items() if k != "kcna_delta"},
         lambda f: not any("Kim" in x or "KCNA" in x for x in f)),
        ("Kim days unknown", {**full, "kcna_delta": {"days_since_last_appearance": None, "watch_flag": False}},
         lambda f: not any("Kim" in x for x in f) and "No KCNA watch flag." in f),
        ("KCNA data unavailable", {**full, "kcna_delta": {"data_unavailable": True, "watch_flag": False}},
         lambda f: not any("KCNA" in x for x in f)),
        ("previous issue unread", {**full, "_bp_changes": None},
         lambda f: not any("reporting" in x for x in f)),
        ("a site without status", {**full, "bp_locations": full["bp_locations"] + [{"name": "D"}]},
         lambda f: not any("alert" in x for x in f)),
        ("seen today", {**full, "kcna_delta": {"kim_appearance_today": True, "days_since_last_appearance": 0}},
         lambda f: f[0] == "Kim seen in public today."),
    ]
    for label, d, ok in cases:
        if not ok(render._v2_status_facts(d)):
            problems.append(f"{label}: {render._v2_status_facts(d)}")
    if render._v2_status({}) != "":
        problems.append("an empty digest still drew a status line")
    line = render._v2_status(full)
    if any(x in line for x in ("·", "&middot;", "→", "&rarr;", "—", "&mdash;")):
        problems.append("status line uses a dot, arrow or em dash as a separator")
    return problems


def check_v2_first_sentence():
    """Shortening cuts at a real sentence end only: not after U.S. or Gen., never inside a quotation."""
    import render
    f = render._v2_first_sentence
    problems = []
    tail = " The second sentence carries on for long enough to be worth a link."
    cases = [
        ("U.S. officials met Gen. Kim Myung-soo in Seoul on Monday." + tail,
         "U.S. officials met Gen. Kim Myung-soo in Seoul on Monday."),
        ("The ministry said it was 'gravely concerned.' Officials added nothing on the record today." + tail,
         "The ministry said it was 'gravely concerned.'"),
        ('He said "We will respond. Firmly and soon." before the meeting ended in Seoul.' + tail,
         'He said "We will respond. Firmly and soon." before the meeting ended in Seoul.'),
        ("Talks resumed at 9 a.m. Seoul time with both delegations present in full." + tail,
         "Talks resumed at 9 a.m. Seoul time with both delegations present in full."),
        ("KOSPI fell 3.7% on Monday as chip stocks slid across the board." + tail,
         "KOSPI fell 3.7% on Monday as chip stocks slid across the board."),
        ("One sentence only, with nothing after it to cut.", "One sentence only, with nothing after it to cut."),
        ("A first sentence that is long enough. Short tail here.", "A first sentence that is long enough. Short tail here."),
    ]
    for text, want in cases:
        got = f(text)
        if got != want:
            problems.append(f"{text[:40]!r} -> {got!r}")
        if not text.startswith(got):
            problems.append(f"shortening reworded {text[:40]!r}")
    return problems


def check_v2_shortened_email():
    """In v2 only top stories run in full; other items keep their first sentence and link to the web page."""
    import copy, render
    problems = []
    long_body = ("Seoul announced a new measure on Monday. The second sentence is detail that the web "
                 "page carries in full for anyone who wants it.")
    d = {"digest_date": "Monday, October 19, 2026", "date_slug": "2026-10-19", "issue_no": 12,
         "web_url": "https://example.org/brief/latest.html",
         "top_stories": [{"headline": "Lead story", "body": long_body, "category_tag": "DPRK"}],
         "business_economy": [{"headline": "Chip exports rise", "body_text": long_body, "source": "Yonhap"}],
         "calendar_watch": [{"month": "Oct", "day": 20, "headline": "Assembly votes on the budget"}],
         "morning_memo": ["One.", "Two.", "Three."]}
    before = copy.deepcopy(d)
    saved = render.DESIGN
    try:
        render.DESIGN = "v2"
        html = render.render(d)
        render.DESIGN = "classic"
        classic = render.render(copy.deepcopy(before))
    finally:
        render.DESIGN = saved
    if html.count("The second sentence is detail") != 1:
        problems.append("v2: expected the long body in full exactly once (the top story)")
    if 'digest_2026-10-19.html#business' not in html:
        problems.append("v2: no Read online link to the business section of the issue page")
    if "That&#8217;s today&#8217;s brief." not in html or "Assembly votes on the budget" not in html:
        problems.append("v2: sign-off missing, or without tomorrow's calendar item")
    if f"border-left:5px solid {render.TAEGUK_BLUE};" not in html:
        problems.append("v2: Business bar lacks the South Korea edge")
    if classic.count("The second sentence is detail") != 2:
        problems.append("classic was shortened")
    if d != {**before, "_word_count": d.get("_word_count")}:
        problems.append("v2 shortening changed the caller's digest")
    saved_full = render.FULL_TEXT
    try:
        render.DESIGN, render.FULL_TEXT = "v2", True
        web = render.render(copy.deepcopy(before))
    finally:
        render.DESIGN, render.FULL_TEXT = saved, saved_full
    if web.count("The second sentence is detail") != 2 or "Shortened for email" in web:
        problems.append("v2 with FULL_TEXT set still shortened the bodies")
    return problems


# ── ROK government feeds ────────────────────────────────────────────────────

def _candidates(value) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


def _gov_site_search(url: str) -> bool:
    """A Google News search limited to a .go.kr or .mil.kr site."""
    return any(t.endswith((".go.kr", ".mil.kr")) or t in ("go.kr", "mil.kr")
               for t in __import__("links").site_targets(url))


def check_rok_feeds_do_not_rest_on_site_search() -> list[str]:
    """No ROK government feed may lead with, or consist of, a site:*.go.kr search.

    Google News indexes very few .go.kr pages. Across 12-18 October 2026 the
    twenty ROK government feeds, nearly all `site:xxx.go.kr` searches,
    delivered 15 items between them, and six delivered none. Each feed must
    try something that answers first: the body's own RSS, or a search for how
    the press reports it.
    """
    problems = []
    gov = collect.ROK_GOVERNMENT_FEEDS
    for name in sorted(gov):
        value = collect.TIER1_FEEDS.get(name)
        if value is None:
            problems.append(f"ROK_GOVERNMENT_FEEDS names {name!r} but TIER1_FEEDS has no such feed")
            continue
        urls = _candidates(value)
        if _gov_site_search(urls[0]):
            problems.append(f"{name!r} leads with a bare site:*.go.kr search")
        if all(links_site(u) for u in urls):
            problems.append(f"{name!r} has only site: searches; it needs a native feed or a press search")
        if name not in collect.KOREA_NATIVE_FEEDS:
            problems.append(f"{name!r} is not in KOREA_NATIVE_FEEDS")
        for u in urls:
            # A Korean-language query belongs in the Korean edition.
            if "news.google.com" in u and re.search(r"%E[A-D]", u) and "ceid=KR:ko" not in u \
                    and name in collect.KOREAN_LANGUAGE_FEEDS and not links_site(u):
                problems.append(f"{name!r} runs a Korean press search in the US edition")
    # Every feed that looks like a ROK government body is in the set.
    for name in collect.TIER1_FEEDS:
        if name.startswith("ROK ") and name not in gov:
            problems.append(f"{name!r} looks like a ROK government feed but is not in ROK_GOVERNMENT_FEEDS")
    # And nothing anywhere in tier 1 leads with a site:*.go.kr search.
    for name, value in collect.TIER1_FEEDS.items():
        if _gov_site_search(_candidates(value)[0]):
            problems.append(f"{name!r} leads with a site:*.go.kr search")
    return problems


def links_site(url: str) -> bool:
    import links
    return bool(links.site_targets(url))


def check_rok_primary_documents_rank_first() -> list[str]:
    """A ministry's own document is in the first band; a press account of it is not.

    The ROK feeds now fall back to press searches, so one feed carries both.
    Ranking by feed name alone would put a newspaper's report in the band the
    prompt calls primary documents.
    """
    doc = {"feed": "ROK MND", "source": "ROK MND", "title": "국방부 정례브리핑",
           "url": "https://www.mnd.go.kr/bbs/mnd/13000005/DPIM_1/artclView.do", "lang": "KO"}
    gn_doc = {"feed": "ROK MOFA", "source": "외교부", "title": "외교부 보도자료",
              "url": "https://news.google.com/rss/articles/CBMiAAA", "lang": "KO",
              "publisher": "외교부", "publisher_home": "https://www.mofa.go.kr"}
    press = {"feed": "ROK MND", "source": "연합뉴스", "title": "국방부 대변인 \"북 미사일\"",
             "url": "https://news.google.com/rss/articles/CBMiBBB", "lang": "KO",
             "publisher": "연합뉴스", "publisher_home": "https://www.yna.co.kr"}
    native_press = {"feed": "ROK Joint Chiefs", "source": "뉴시스", "title": "합참은",
                    "url": "https://www.newsis.com/view/NISX1", "lang": "KO"}
    daily = {"feed": "매일경제", "source": "매일경제", "title": "x",
             "url": "https://www.mk.co.kr/news/1", "lang": "KO"}
    problems = []
    for art, want in ((doc, 0), (gn_doc, 0), (press, 2), (native_press, 2), (daily, 4)):
        got = digest._prompt_band(art)
        if got != want:
            problems.append(f"{art['source']} via {art['feed']} is in band {got}, expected {want}")
    order = [a["title"] for a in digest.rank_for_prompt([daily, press, native_press, gn_doc, doc])]
    if order[:2] != [gn_doc["title"], doc["title"]] and order[:2] != [doc["title"], gn_doc["title"]]:
        problems.append(f"primary documents are not first: {order}")
    # Press searches must not fill the tier-1 cut on their own.
    flood = [{"feed": f, "source": "연합뉴스", "title": f"{f} {i}", "lang": "KO",
              "url": f"https://www.yna.co.kr/view/{abs(hash(f))}{i}",
              "publisher_home": "https://www.yna.co.kr"}
             for f in sorted(collect.ROK_GOVERNMENT_FEEDS) for i in range(collect.ROK_FEED_MAX_ITEMS)]
    wires = [{"feed": "Korea Herald", "source": "Korea Herald", "title": f"KH {i}", "lang": "EN",
              "url": f"https://www.koreaherald.com/{i}"} for i in range(5)]
    cut = digest.rank_for_prompt(flood + wires)[:140]
    if not any(a["feed"] == "Korea Herald" for a in cut):
        problems.append("ROK press searches crowd the general press out of the tier-1 cut")
    # The prompt: primary URL first, the press report as secondary_url.
    import inspect
    src = inspect.getsource(digest)
    m = re.search(r"- rok_government:(.*?)\n", src)
    if not m:
        problems.append("rok_government spec not found in the prompt")
    else:
        spec = m.group(1)
        if "secondary_url" not in spec or "own document" not in spec:
            problems.append("rok_government spec does not ask for the primary document with "
                            "the press report as secondary_url")
    if "newspaper reports of their briefings" not in digest.SYSTEM_PROMPT:
        problems.append("PRIMARY ROK SOURCES no longer tells documents from press reports")
    return problems


def check_stale_native_candidate_falls_through() -> list[str]:
    """A native feed whose items are all old must not block the search behind it.

    korea.kr ended its RSS service in July 2026; a board that still serves
    its last file would otherwise win, be emptied by the recency filter, and
    keep the press search from ever running.
    """
    import feedparser
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    def entry(days_old: int, title: str):
        # Dated from the same clock the collector reads (datetime.now), not
        # time.time(): run under timetravel.py the two disagree, and a "1 day
        # old" item became a year old and lost to the fallback.
        e = feedparser.FeedParserDict()
        e["title"] = title
        e["link"] = f"https://example.invalid/{title}"
        e["published_parsed"] = (_dt.now(_tz.utc) - _td(days=days_old)).utctimetuple()
        return e

    pages = {"https://native.invalid/rss": [entry(40, "old1"), entry(30, "old2")],
             "https://native.invalid/fresh": [entry(1, "fresh")],
             "https://news.google.com/rss/search?q=x": [entry(0, "press")]}
    saved = collect._parse_one
    collect._parse_one = lambda url, retries=3: list(pages.get(url, []))
    problems = []
    try:
        got = collect._parse_feed(["https://native.invalid/rss", "https://news.google.com/rss/search?q=x"])
        if [e["title"] for e in got] != ["press"]:
            problems.append(f"a stale native feed blocked the fallback: {[e['title'] for e in got]}")
        got = collect._parse_feed(["https://native.invalid/fresh", "https://news.google.com/rss/search?q=x"])
        if [e["title"] for e in got] != ["fresh"]:
            problems.append("a live native feed did not win")
        got = collect._parse_feed(["https://native.invalid/rss"])
        if len(got) != 2:
            problems.append("the last candidate's items were discarded for being old")
    finally:
        collect._parse_one = saved
    return problems


# ── Capitol Hill stream: what gets through ──────────────────────────────────

# Headlines as the outlets write them. Each is (title, summary, feed, kept?).
_HILL_HEADLINES = [
    # Should pass: what Congress does on Korea.
    ("Senators introduce bill to keep 28,500 US troops in South Korea", "", "US Congress Korea", True),
    ("House passes NDAA with USFK troop floor and Korea shipbuilding provisions", "", "Congress USFK troops", True),
    ("House panel advances North Korea sanctions bill targeting crypto laundering", "", "Congress Korea sanctions", True),
    ("Bipartisan lawmakers urge visas for Korean workers after Georgia plant raid", "", "Korean worker visa bill", True),
    ("Rep. Young Kim introduces North Korean Human Rights Reauthorization Act", "", "US Congress Korea", True),
    ("US lawmakers press Pentagon on OPCON transfer to South Korea", "", "Congress Korea letter", True),
    ("MASGA: shipbuilding provisions added to Senate defense bill", "Hanwha Philly Shipyard", "Congress Shipbuilding Korea", True),
    ("Korea Caucus co-chairs welcome South Korean foreign minister to Capitol Hill", "", "Korea Caucus", True),
    ("CRS: U.S.-South Korea Relations", "Congressional Research Service report", "CRS Reports", True),
    ("Senate Foreign Relations hearing examines North Korea policy", "", "Congress Korea hearing", True),
    ("S. 2296, Partner with Korea Act, referred to committee", "", "Congress.gov Bills", True),
    # Should not: the National Assembly, the Party Congress, trade shows,
    # entertainment, and Hill feeds' items that are not about Korea.
    ("Korean lawmakers clash at National Assembly audit", "lawmakers", "US Congress Korea", False),
    ("Ruling party lawmaker says U.S. intelligence 'not omniscient'", "DP lawmaker", "US Congress Korea", False),
    ("North Korea sets date for Ninth Party Congress", "Workers' Party congress", "US Congress Korea", False),
    ("Ettifos showcases V2X platform at South Korea ITS congress", "", "US Congress Korea", False),
    ("PPP lawmakers demand Lee explain tariff deal with Washington", "senators in Seoul", "Congress Korea letter", False),
    ("Senate confirms new Fed governor", "", "The Hill Defense", False),
    ("Pentagon budget fight continues", "", "The Hill Defense", False),
    ("BTS member meets senators on Capitol Hill", "K-pop", "US Congress Korea", False),
]


def check_hill_relevance_headlines() -> list[str]:
    """Real Korea-on-the-Hill headlines pass; the look-alikes do not."""
    class _E(dict):
        def get(self, key, default=None):
            return dict.get(self, key, default)

    problems = []
    for title, summary, feed, want in _HILL_HEADLINES:
        if feed not in collect.CAPITOL_HILL_FEEDS:
            problems.append(f"test names {feed!r}, which is not a Capitol Hill feed")
            continue
        got = collect._is_hill_relevant(_E(title=title, summary=summary), feed)
        if got != want:
            problems.append(f"{'drops' if want else 'admits'} {title!r} ({feed})")
    return problems


def check_hill_stream_delivers() -> list[str]:
    """A firehose native feed with no Korea item must give way to its search.

    On 19-21 October 2026 every Capitol Hill feed answered and the stream
    delivered nothing: The Hill, Roll Call, Politico and congress.gov publish
    daily, so their native feeds won, the Korea filter removed every item, and
    the `Korea site:` search behind each never ran. The searches are also
    date-limited first, because a relevance-ranked search returns last
    month's items and a 48-hour window keeps none of them.
    """
    import feedparser
    import links
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    def entry(title: str, link: str, hours: int = 3):
        e = feedparser.FeedParserDict()
        e["title"] = title
        e["link"] = link
        e["summary"] = ""
        e["published_parsed"] = (_dt.now(_tz.utc) - _td(hours=hours)).utctimetuple()
        return e

    problems = []
    for name, cands in collect.CAPITOL_HILL_FEEDS.items():
        cands = [cands] if isinstance(cands, str) else list(cands)
        searches = [c for c in cands if "news.google.com" in c]
        if not searches or "news.google.com" not in cands[-1]:
            problems.append(f"{name}: no search behind the native feed")
            continue
        if not any("when%3A" in c for c in searches):
            problems.append(f"{name}: no date-limited search")
        if "when%3A" in cands[-1]:
            problems.append(f"{name}: the last candidate is date-limited, so nothing backs it up")
    q = links.build_gnews_query('"South Korea" OR "North Korea" Congress OR senator when:3d')
    if not q.endswith(") when:3d"):
        problems.append(f"when: does not bind to the whole search: {q!r}")

    def fake(url, retries=3):
        if "news.google.com" in url:
            return [entry("Senators introduce bill to keep US troops in South Korea - The Hill",
                          "https://news.google.com/rss/articles/CBMi-hill-" + str(abs(hash(url)) % 10**6))]
        return [entry("Senate confirms new Fed governor", url + "#fed"),
                entry("House GOP unveils farm bill", url + "#farm")]

    saved = collect._parse_one
    collect._parse_one = fake
    try:
        got = collect._collect_capitol_hill()
    finally:
        collect._parse_one = saved
    feeds = {a["feed"] for a in got}
    for name in ("The Hill Defense", "Roll Call", "Congress.gov House Floor"):
        if name not in feeds:
            problems.append(f"{name}: a native feed with no Korea item still blocked its search")
    if any("Fed governor" in a["title"] or "farm bill" in a["title"] for a in got):
        problems.append("non-Korea Hill items reached the stream")
    # And a native feed that does carry a Korea item still wins.
    pages = {"https://native.invalid/hill": [entry("NDAA keeps USFK troop floor in South Korea",
                                                   "https://native.invalid/a")],
             "https://news.google.com/rss/search?q=x": [entry("search hit", "https://news.google.com/x")]}
    collect._parse_one = lambda url, retries=3: list(pages.get(url, []))
    try:
        won = collect._parse_feed(list(pages), accept=lambda e: collect._is_hill_relevant(e, "The Hill Defense"))
    finally:
        collect._parse_one = saved
    if [e["title"] for e in won] != ["NDAA keeps USFK troop floor in South Korea"]:
        problems.append("a native feed with a Korea item did not win")
    return problems


def check_rok_press_searches_are_windowed() -> list[str]:
    """Each ROK press search asks for the last two days first, then the plain search."""
    problems = []
    for name in collect.ROK_GOVERNMENT_FEEDS:
        cands = collect.TIER1_FEEDS.get(name)
        cands = [cands] if isinstance(cands, str) else list(cands or [])
        searches = [c for c in cands if "news.google.com" in c and "site%3A" not in c]
        if not searches:
            continue
        if not any("when%3A" in c for c in searches) or "when%3A" in cands[-1]:
            problems.append(f"{name}: press search is not windowed-then-plain")
    if "vietnam.vn" not in " ".join(collect.TIER1_FEEDS["ROK MOTIE"]):
        problems.append("ROK MOTIE no longer excludes vietnam.vn's machine-translated ministry")
    return problems
# ── Congressional calendar parsers ──────────────────────────────────────────

# senate.gov/general/committee_schedules/hearings.xml, in its documented shape:
# one <meeting> per scheduled meeting, with committee, sub_cmte, date (DD-MON-
# YYYY HH:MM AM), room and matter children.
_SENATE_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<css_meetings_scheduled>
 <last_updated>20-OCT-2026 05:12 PM</last_updated>
 <meetings>
  <meeting>
   <cmte_code>SSAS00</cmte_code>
   <committee>Armed Services</committee>
   <sub_cmte></sub_cmte>
   <date>21-OCT-2026 09:30 AM</date>
   <room>SD-G50</room>
   <matter>Hearings to examine the posture of United States Indo-Pacific Command and United States Forces Korea.</matter>
   <identifier>339201</identifier>
  </meeting>
  <meeting>
   <cmte_code>SSFR09</cmte_code>
   <committee>Foreign Relations</committee>
   <sub_cmte>East Asia, the Pacific, and International Cybersecurity Policy</sub_cmte>
   <date>22-OCT-2026 02:30 PM</date>
   <room>SD-419</room>
   <matter>Hearings to examine Chinese coercion of United States partners.</matter>
  </meeting>
  <meeting>
   <committee>Agriculture, Nutrition, and Forestry</committee>
   <date>21-OCT-2026 10:00 AM</date>
   <matter>Hearings to examine the farm economy and trade.</matter>
  </meeting>
  <meeting>
   <committee>Finance</committee>
   <date>23-OCT-2026 10:00 AM</date>
   <matter>Hearings to examine trade with Asian allies, including autos and steel.</matter>
  </meeting>
  <meeting>
   <committee>Commerce, Science, and Transportation</committee>
   <date>23-OCT-2026 10:00 AM</date>
   <matter>*** POSTPONED *** Hearings to examine shipbuilding and the maritime industrial base.</matter>
  </meeting>
  <meeting>
   <committee>Armed Services</committee>
   <date>04-NOV-2026 09:30 AM</date>
   <matter>Hearings to examine the nomination of a Commander, United States Forces Korea.</matter>
  </meeting>
 </meetings>
</css_meetings_scheduled>"""

# docs.house.gov/Committee/RSS.ashx?Code=FA00: one item per meeting, the
# meeting date and status in the description, pubDate the posting time.
_HOUSE_FIXTURE = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
 <title>U.S. House of Representatives - Committee on Foreign Affairs Meeting Feed</title>
 <item>
  <title>Hearing: Shipbuilding Cooperation with the Republic of Korea</title>
  <link>https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=118901</link>
  <description>Meeting Date: Wednesday, October 21, 2026 10:00 AM (Scheduled) Location: 2172 RHOB. Posted October 14, 2026.</description>
  <pubDate>Wed, 14 Oct 2026 15:00:00 GMT</pubDate>
 </item>
 <item>
  <title>Countering North Korea's Cyber Theft</title>
  <link>https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=118902</link>
  <description>Subcommittee on East Asia and the Pacific. Date: 10/22/2026 2:00 PM</description>
  <pubDate>Thu, 15 Oct 2026 15:00:00 GMT</pubDate>
 </item>
 <item>
  <title>Markup of H.R. 9001, the Indo-Pacific Partners Act</title>
  <link>https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=118903</link>
  <description>Meeting Date: Thursday, October 22, 2026 (Postponed)</description>
 </item>
 <item>
  <title>Hearing on the Korea alliance</title>
  <link>https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=118904</link>
  <description>Announced October 15, 2026 for October 23, 2026.</description>
 </item>
</channel></rss>"""


def check_hill_calendar_parsers() -> list[str]:
    """The schedule parsers read the documented formats and never guess a date."""
    from datetime import date
    problems = []
    today, horizon = date(2026, 10, 20), date(2026, 10, 27)

    senate = collect._parse_hill_schedule(_SENATE_FIXTURE, "Senate committee schedule")
    kept = collect.filter_hill_events(senate, today, horizon)
    titles = [e["title"][:40] for e in kept]
    want = ["Hearings to examine the posture of Unite",
            "Hearings to examine Chinese coercion of ",
            "Hearings to examine trade with Asian all"]
    if titles != want:
        problems.append(f"Senate fixture kept {titles}, expected {want}")
    if kept and (kept[0]["date"], kept[0]["time"]) != ("2026-10-21", "09:30 AM"):
        problems.append(f"Senate date/time read as {kept[0]['date']} {kept[0]['time']}")
    if kept and len(kept) > 1 and "East Asia" not in kept[1]["committee"]:
        problems.append("the subcommittee is missing from the committee label")
    if any("POSTPONED" in e["title"] for e in senate):
        problems.append("a postponed meeting was listed")

    # One stray HTML entity must not cost the whole Senate schedule.
    broken = _SENATE_FIXTURE.replace(b"SD-G50", b"SD&nbsp;G50")
    if len(collect._parse_hill_schedule(broken, "Senate committee schedule")) != len(senate):
        problems.append("an unparseable entity dropped the Senate schedule")

    house = collect._parse_hill_schedule(_HOUSE_FIXTURE, "House Foreign Affairs schedule")
    got = [(e["date"], e["title"][:30]) for e in house]
    want_h = [("2026-10-21", "Hearing: Shipbuilding Cooperat"),
              ("2026-10-22", "Countering North Korea's Cyber")]
    if got != want_h:
        problems.append(f"House fixture read {got}, expected {want_h} "
                        f"(meeting-only feed, labelled dates, no postponed, no two-date guess)")
    if house and house[0]["time"] != "10:00 AM":
        problems.append(f"House time read as {house[0]['time']!r}")
    if house and house[0]["committee"] != "House Foreign Affairs":
        problems.append(f"House committee read as {house[0]['committee']!r}")

    # Date reading.
    cases = [("September 30, 2026", date(2026, 9, 30)), ("Sept. 30, 2026", date(2026, 9, 30)),
             ("30-SEP-2026 10:00 AM", date(2026, 9, 30)), ("2026-10-21T10:00:00-04:00", date(2026, 10, 21)),
             ("Tuesday, October 21, 2026 10:00 AM", date(2026, 10, 21)), ("next Tuesday", None)]
    for text, want_d in cases:
        if collect._parse_event_date(text) != want_d:
            problems.append(f"{text!r} read as {collect._parse_event_date(text)}, expected {want_d}")
    if collect._event_date_in_notice("Posted October 15, 2026. Hearing October 23, 2026.") is not None:
        problems.append("a notice with two dates and no label was given one of them")

    # Relevance.
    for text, want_r in (("Hearings to examine the farm bill and trade", False),
                         ("Hearings to examine NATO alliance burden-sharing", False),
                         ("Hearings to examine U.S. alliances in the Indo-Pacific", True),
                         ("Business meeting on KORUS implementation", True)):
        if collect.hill_event_relevant(text) != want_r:
            problems.append(f"relevance of {text!r} is {not want_r}")

    # The run log line.
    import run
    line = run.hill_calendar_log_line({"hill_calendar": [{}], "hill_calendar_stats": {
        "fetched": 9, "kept": 1, "answered": 9, "feeds": 10,
        "per_source": {"Senate committee schedule": "error", "HFAC schedule": 3}}})
    if "9 event(s) fetched" not in line or "1 kept" not in line or "Senate committee schedule" not in line:
        problems.append(f"run log line does not report fetched and kept: {line!r}")
    if not collect.HILL_CALENDAR_FEEDS.get("House Foreign Affairs schedule", "").endswith("Code=FA00"):
        problems.append("the House meeting feed has no committee code")
    return problems


def check_corpus_records_feed() -> list[str]:
    """The published corpus says which feed found each item, compactly."""
    import corpus
    gn = corpus.slim_article({"url": "https://x.example/a", "title": "t", "source": "연합뉴스",
                              "feed": "ROK MND"}, 1, False, None, False)
    native = corpus.slim_article({"url": "https://x.example/b", "title": "t", "source": "조선일보",
                                  "feed": "조선일보"}, 1, False, None, False)
    problems = []
    if gn.get("feed") != "ROK MND":
        problems.append("a Google News record does not carry its feed")
    if "feed" in native:
        problems.append("a record repeats the feed when it equals the source")
    return problems


def check_tracker_state_survives_a_cache_miss() -> list[str]:
    """A cache miss or an older cached copy must not reset a tracker.

    The trackers used to live only in the Actions cache, and each one treats a
    missing file as "start empty" and saves. restore_state.py picks the newer
    of cache and repository; the workflow commits the trackers so there is a
    repository copy to pick.
    """
    import json
    import tempfile
    from pathlib import Path
    import restore_state
    problems = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        repo_kim = {"appearances": [{"date": "2026-10-19"}], "last_updated": "2026-10-20T11:05:00"}
        (root / "kim_tracker.json").write_text(json.dumps(repo_kim))
        (root / "feed_health.json").write_text(json.dumps({"total_runs": 40, "feeds": {"A": {}}}))
        (root / "kcna_tracker.json").write_text(json.dumps({"days": [1], "last_updated": "2026-10-20"}))
        (root / "metrics.jsonl").write_text('{"date": "2026-10-19"}\n{"date": "2026-10-20"}\n')
        restore_state.stash(root)
        # The cache restore: Kim missing (a miss), feed health older, KCNA
        # corrupt, metrics a day short.
        (root / "kim_tracker.json").unlink()
        (root / "feed_health.json").write_text(json.dumps({"total_runs": 12, "feeds": {}}))
        (root / "kcna_tracker.json").write_text("{not json")
        (root / "metrics.jsonl").write_text('{"date": "2026-10-19"}\n')
        notes = restore_state.reconcile(root)
        if json.loads((root / "kim_tracker.json").read_text()) != repo_kim:
            problems.append("a tracker missing from the cache was not restored from the repository")
        if json.loads((root / "feed_health.json").read_text()).get("total_runs") != 40:
            problems.append("an older cached feed_health.json beat the newer committed one")
        if json.loads((root / "kcna_tracker.json").read_text()).get("days") != [1]:
            problems.append("a corrupt cached tracker was kept over a readable committed one")
        if (root / "metrics.jsonl").read_text().count("\n") != 2:
            problems.append("metrics.jsonl rows in the repository were lost to the cache copy")
        if not any("bp_tracker.json" in n and "starts empty" in n for n in notes):
            problems.append("a tracker in neither copy is not annotated as a cold start")
    gi = Path(__file__).parent / ".gitignore"
    ignored = {l.strip() for l in gi.read_text().splitlines()} if gi.exists() else set()
    for name in restore_state.TRACKERS:
        if name in ignored:
            problems.append(f"{name} is gitignored, so the commit step can never add it")
    wf = Path(__file__).parent / ".github/workflows/daily-digest.yml"
    if wf.exists():
        text = wf.read_text(encoding="utf-8")
        for name in restore_state.TRACKERS:
            if name not in text.split("Commit updated README", 1)[-1].split("Save tracker data", 1)[0]:
                problems.append(f"the workflow does not commit {name}")
        if "restore_state.py stash" not in text or "restore_state.py reconcile" not in text:
            problems.append("the workflow does not reconcile cached and committed trackers")
    return problems


def check_send_guard_counts_sends_not_runs() -> list[str]:
    """The fallback crons skip only when a send step succeeded today.

    Counting successful runs counted the guard's own skips (a run that skips
    concludes success), so after DST an hour-floor skip of the 7:30 fallback
    stopped the 9:00 one. A test send must not count either.
    """
    import re
    from pathlib import Path
    problems = []
    wf = Path(__file__).parent / ".github/workflows/daily-digest.yml"
    if not wf.exists():
        return problems
    text = wf.read_text(encoding="utf-8")
    # Step blocks by name; PyYAML is not a dependency of the pipeline.
    blocks = {m.group(1).strip(): m.group(2) for m in re.finditer(
        r"^      - name: ([^\n]+)\n(.*?)(?=^      - |\Z)", text, re.M | re.S)}
    guard = blocks.get("Check if already sent today", "")
    if '.name == "Generate and send digest"' not in guard:
        problems.append("the send guard no longer keys on the send step")
    if "--status success" in guard:
        problems.append("the send guard counts successful runs again, which includes skipped ones")
    send = blocks.get("Generate and send digest", "")
    if "inputs.send_to == ''" not in send or "--send-to" in send:
        problems.append("a test send can run under the step name the guard counts as a real send")
    for name in ("Deploy to GitHub Pages", "Commit updated README + Gallup baseline"):
        if "inputs.send_to == ''" not in blocks.get(name, ""):
            problems.append(f"{name} runs on a test send, publishing the test as the issue")
    if not re.search(r"^concurrency:", text, re.M):
        problems.append("runs are not serialised, so two guards can decide at once")
    return problems


def _web_sample() -> dict:
    """A small digest with one long top story, for the web edition checks."""
    long_body = " ".join(f"Sentence {i} carries word{i} for the record." for i in range(70))
    return {
        "re_line": "DPRK test · Seoul responds",
        "web_url": "https://example.org/kdb/latest.html", "date_slug": "2026-10-20",
        "issue_no": 12, "listen_url": "https://example.org/kdb/listen/2026-10-20.html?utm_source=email",
        "audio_url": "https://example.org/kdb/digest_2026-10-20.mp3",
        "morning_memo": ["North Korea tested a missile.", "Seoul convened the NSC.", "KOSPI fell."],
        "top_stories": [{"headline": "North Korea fires a missile", "body": long_body,
                         "source": "Yonhap", "url": "https://example.org/a"},
                        {"headline": "Seoul convenes NSC", "body": "Short body.", "source": "Korea Herald",
                         "url": "https://example.org/b"}],
        "overnight_items": [{"headline": f"Overnight {i}", "body": "One line.", "source": "Reuters",
                             "url": f"https://example.org/o{i}"} for i in range(3)],
        "business_economy": [{"headline": "KOSPI falls", "body": "Chips led.", "source": "Bloomberg",
                              "url": "https://example.org/c"}],
    }


def check_web_edition() -> list[str]:
    """The published page is the web edition: folding sections, a menu, every word, a fallback."""
    import re
    import render
    import web_page
    problems = []
    d = _web_sample()
    saved = (render.DESIGN, render.FULL_TEXT)
    archive = [{"date": "2026-10-19"}, {"date": "2026-10-20"}, {"date": "2026-10-21"}]
    page = web_page.build(d, "<html>EMAIL</html>", "2026-10-20", archive_entries=archive)
    if (render.DESIGN, render.FULL_TEXT) != saved:
        problems.append("web_page.build left render.DESIGN or render.FULL_TEXT changed")
    if page == "<html>EMAIL</html>":
        return problems + ["web_page.build fell back to the email on a valid digest"]
    n_details = page.count('<details open class="wsec"')
    if n_details < 3 or page.count("<summary") != n_details:
        problems.append(f"sections are not <details open> with a <summary> bar ({n_details} found)")
    menu = re.search(r'<nav class="wmenu[^"]*" id="wmenu".*?</nav>', page, re.S)
    if not menu:
        problems.append("no section menu")
    else:
        for anchor in ("top-stories", "overnight", "business"):
            if f'href="#{anchor}"' not in menu.group(0):
                problems.append(f"the menu does not link #{anchor}")
            if f'id="{anchor}"' not in page:
                problems.append(f"the menu links #{anchor}, which the page does not have")
    if "position:sticky" not in page:
        problems.append("the menu is not sticky")
    text = re.sub(r"<[^>]+>", " ", page)
    if not all(f"word{i}" in text for i in range(70)):
        problems.append("a long body is not shown in full")
    if 'href="digest_2026-10-19.html"' not in page or 'href="digest_2026-10-21.html"' not in page:
        problems.append("previous/next issue links missing")
    if 'href="listen/2026-10-20.html"' not in page or 'href="archive.html#search"' not in page:
        problems.append("Listen or archive search link missing")
    if 'href="#top"' not in page or '<meta name="robots" content="noindex">' not in page:
        problems.append("Back to top or noindex missing")
    if "@media print" not in page or "prefers-color-scheme: dark" not in page:
        problems.append("print or dark-mode stylesheet missing")
    if not re.search(r'<meta name="description" content="[^"]+">', page):
        problems.append("no meta description")
    if re.search(r"<(?:script|link)[^>]+(?:src|href)=\"https?://", page):
        problems.append("the web edition loads an external script or stylesheet")
    chrome = page.split("</head>", 1)[0] + "".join(re.findall(r'<nav class="wmenu.*?</nav>|<div class="wnav-in">.*?</div>', page, re.S))
    if re.search("[·—▲▼←-⇿]|&middot;|&rarr;|&larr;", chrome.split("<style", 1)[0] + chrome.split("</style>")[-1]):
        problems.append("middle dot, em dash, arrow or triangle in the web chrome")
    sizes = [int(s) for s in re.findall(r"font-size:(\d+)px", web_page._CSS)]
    if max(sizes) > 16:
        problems.append(f"the web stylesheet sets a {max(sizes)}px font")
    # Without the manifest, prev/next are left to the page and start hidden.
    bare = web_page.build(d, "<html>EMAIL</html>", "2026-10-20", archive_entries=None)
    if re.search(r'<a data-wprev="" href="digest_', bare):
        problems.append("a previous-issue link was baked in without an archive")
    # Anything failing inside returns the email HTML.
    import contextlib
    import io
    real = web_page._render_v2
    try:
        web_page._render_v2 = lambda _d: (_ for _ in ()).throw(RuntimeError("boom"))
        with contextlib.redirect_stdout(io.StringIO()):
            fell_back = web_page.build(d, "<html>EMAIL</html>", "2026-10-20")
        if fell_back != "<html>EMAIL</html>":
            problems.append("web_page.build does not fall back to the email HTML when it fails")
    finally:
        web_page._render_v2 = real
    return problems


def check_run_falls_back_to_the_email_page() -> list[str]:
    """run.build_web_html never raises: if web_page raises, the page is the email, with a warning."""
    import contextlib
    import io
    from pathlib import Path
    import run
    import web_page
    problems = []
    real = web_page.build
    out = io.StringIO()
    try:
        def boom(*a, **k):
            raise RuntimeError("web edition broke")
        web_page.build = boom
        with contextlib.redirect_stdout(out):
            got = run.build_web_html({}, "<html>EMAIL</html>", "2026-10-20", None)
        if got != "<html>EMAIL</html>":
            problems.append("run.build_web_html did not fall back to the email HTML")
        if "::warning" not in out.getvalue():
            problems.append("the fallback printed no ::warning annotation")
    finally:
        web_page.build = real
    src = (Path(__file__).parent / "run.py").read_text(encoding="utf-8")
    if 'write_text(web_html' not in src or 'html_from_input(Path("latest.html"))' not in src:
        problems.append("run.py does not publish the web edition, or the PDF is not from the email")
    return problems


def check_archive_search() -> list[str]:
    """The archive page searches past headlines from the published corpus shards, and writes nothing."""
    from pathlib import Path
    import archive_page
    problems = []
    page = archive_page.build([{"date": "2026-10-20", "headline_re": "x", "url": "digest_2026-10-20.html"}],
                              title="Korea Daily Brief", chair="CSIS Korea Chair", accent="#167EFF",
                              latest_href="latest.html", prefix="digest_")
    for needle in ('id="q"', 'id="hits"', 'id="hit-list"', '"corpus/"', "manifest.json", "index_",
                   'data-date="2026-10-20"', "used"):
        if needle not in page:
            problems.append(f"archive search markup missing {needle!r}")
    off = archive_page.build([], title="t", chair="c", accent="#167EFF", corpus_dir=None)
    if "manifest.json" in off:
        problems.append("corpus_dir=None still loads the corpus")
    src = (Path(__file__).parent / "archive_page.py").read_text(encoding="utf-8")
    if "write_text" in src or "open(" in src:
        problems.append("archive_page writes a file; the search must only read published indexes")
    return problems


def check_status_line_kcna_trend_and_provocations():
    """The status line's KCNA trend and provocation count come from data, and drop out without it."""
    import run, render
    problems = []
    today = {"date_slug": "2026-10-28", "kcna_delta": {"watch_flag": True}}
    prev = {"kcna_delta": {"watch_flag": False}}
    hist = [{"date": "2026-10-28", "watch_flag": True}] + [
        {"date": f"2026-10-{d}", "watch_flag": d in (25, 26)} for d in range(27, 21, -1)]
    t = run.kcna_trend(today, prev, hist)
    if not t or t.get("prev_watch_flag") is not False or t.get("watch_days_week") != 3 or t.get("week_days") != 7:
        problems.append(f"kcna_trend wrong: {t}")
    if run.kcna_trend({"kcna_delta": {"data_unavailable": True}}, prev, hist) is not None:
        problems.append("kcna_trend invented a trend without KCNA data")
    recs = [{"date": "2026-10-27"}, {"date": "2026-10-20"}, {"date": "2026-10-28"}]
    w = run.provocation_window(recs, "2026-10-28")
    if not w or w["count"] != 2 or w["latest"] != "2026-10-28":
        problems.append(f"provocation_window wrong: {w}")
    if run.provocation_window(recs, "2026-10-21") is not None:
        problems.append("provocation_window counted across the database's gap")
    facts = render._v2_status_facts({**today, "_kcna_trend": t, "_provocations": w})
    joined = " ".join(facts)
    if "from none yesterday" not in joined or "3 of the last 7 days" not in joined:
        problems.append(f"status line lacks the KCNA trend: {facts}")
    if "2 provocations logged in the last 7 days" not in joined:
        problems.append(f"status line lacks the provocation count: {facts}")
    if "provocation" in " ".join(render._v2_status_facts({**today, "_provocations": {"count": 0, "days": 7}})):
        problems.append("status line claimed a quiet week from a zero count")
    return problems


CHECKS = [
    ("status line: KCNA trend and provocations", check_status_line_kcna_trend_and_provocations),
    ("web edition: folding sections, menu, full text, fallback", check_web_edition),
    ("run.py falls back to the email page", check_run_falls_back_to_the_email_page),
    ("archive page searches past headlines", check_archive_search),
    ("tracker state survives a cache miss", check_tracker_state_survives_a_cache_miss),
    ("send guard counts sends, not runs", check_send_guard_counts_sends_not_runs),
    ("design preview goes only to the preview list", check_design_preview_goes_only_to_preview_list),
    ("v2 status line drops missing facts", check_v2_status_line),
    ("v2 shortening cuts at real sentence ends", check_v2_first_sentence),
    ("v2 email runs top stories in full, the rest shortened", check_v2_shortened_email),
    ("audio is formatted for the ear", check_audio_formatting),
    ("no Korean script on the page", check_english_only),
    ("API cost is recorded and kept", check_api_cost_is_recorded),
    ("audio chapters, transcript, feed and player page", check_audio_extras),
    ("no raw markdown reaches the reader", check_no_raw_markdown_reaches_the_reader),
    ("subject line is the house format", check_subject_is_the_house_format),
    ("prestige rule is enforceable", check_prestige_rule_is_enforceable),
    ("masthead is mobile-safe", check_masthead_is_mobile_safe),
    ("emphasis cannot inject markup", check_emphasis_cannot_inject),
    ("nav links land where they say", check_nav_links_land_where_they_say),
    ("hex colours are well formed", check_colours_are_colours),
    ("primary ROK sources reach the model", check_primary_sources_reach_the_model),
    ("Korean ministry headlines survive", check_korean_headlines_survive),
    ("filter still rejects world news", check_filter_still_rejects_world_news),
    ("named institutions have feeds", check_named_institutions_exist),
    ("mandatory outlets reach the prompt", check_mandatory_outlets_reach_the_prompt),
    ("Google News dependence not regressing", check_google_news_dependence_not_regressing),
    ("native feeds are tried first", check_native_feeds_come_first),
    ("major feeds have native paths", check_major_feeds_have_native_paths),
    ("length has a ceiling", check_length_has_a_ceiling),
    ("audio narrates only the brief", check_audio_script_is_the_brief),
    ("coverage audit flags missed stories", check_coverage_audit),
    ("Capitol Hill and Korea and the World are wired", check_new_sections_are_wired),
    ("Hill and world streams reach the model", check_new_streams_reach_the_model),
    ("Hill and world feeds follow the sourcing rules", check_new_streams_sourcing),
    ("new sections render in place", check_new_sections_render),
    ("new sections are narrated", check_new_sections_audio),
    ("Korean 억 figures are scaled", check_korean_units_are_scaled),
    ("process notes never reach readers", check_process_notes_never_reach_readers),
    ("non-US deals are filtered on headline and parties", check_non_us_deals_are_filtered),
    ("calendar items render in every reader", check_calendar_items_render),
    ("the email fits under Gmail's clip", check_email_fits_gmail),
    ("ROK feeds do not rest on site:*.go.kr searches", check_rok_feeds_do_not_rest_on_site_search),
    ("ROK primary documents rank first", check_rok_primary_documents_rank_first),
    ("a stale native feed falls through to its fallback", check_stale_native_candidate_falls_through),
    ("Hill calendar parsers read the documented formats", check_hill_calendar_parsers),
    ("corpus records carry their feed", check_corpus_records_feed),
    ("Hill relevance passes Congress on Korea, not look-alikes", check_hill_relevance_headlines),
    ("Hill native feeds give way to their searches", check_hill_stream_delivers),
    ("ROK press searches are date-limited first", check_rok_press_searches_are_windowed),
]


def check_link_quality() -> list[str]:
    """Every link a reader can click: see test_links.py."""
    import test_links
    problems = []
    for label, fn in test_links.CHECKS:
        try:
            problems += [f"{label}: {p}" for p in fn()]
        except Exception as e:                                  # noqa: BLE001
            problems.append(f"{label}: raised {type(e).__name__}: {e}")
    return problems


CHECKS.append(("link quality (publisher, decoding, repair, dedup, labels)", check_link_quality))


def main() -> int:
    failed = 0
    for label, fn in CHECKS:
        problems = fn()
        print(f"  {'FAIL' if problems else 'OK  '}  {label}")
        for p in problems:
            print(f"          {p}")
        failed += bool(problems)
    print(f"\n{len(CHECKS) - failed}/{len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
