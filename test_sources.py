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
    for name, value in collect.TIER1_FEEDS.items():
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
                "academic_today": 44, "social_statements": 40, "morning_memo": 26}
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
            "social_statements": _mk(6, 55)}
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


CHECKS = [
    ("prestige rule is enforceable", check_prestige_rule_is_enforceable),
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
