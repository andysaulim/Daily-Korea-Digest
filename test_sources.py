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
        is_primary = name.startswith("ROK ") or name in {
            "Bank of Korea", "Statistics Korea", "Korea Customs", "Korea.net"}
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
MIN_FEEDS_WITH_NATIVE_PATH = 26


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
    if "Senate Foreign Relations hearing" not in s.split("Our top story")[0]:
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


CHECKS = [
    ("API cost is recorded and kept", check_api_cost_is_recorded),
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
]


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
