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


CHECKS = [
    ("prestige rule is enforceable", check_prestige_rule_is_enforceable),
    ("primary ROK sources reach the model", check_primary_sources_reach_the_model),
    ("Korean ministry headlines survive", check_korean_headlines_survive),
    ("filter still rejects world news", check_filter_still_rejects_world_news),
    ("named institutions have feeds", check_named_institutions_exist),
    ("mandatory outlets reach the prompt", check_mandatory_outlets_reach_the_prompt),
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
