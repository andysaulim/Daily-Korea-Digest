"""Did the brief miss a story the press widely covered?

The pipeline collects several hundred tier-1 articles a day and the model
writes perhaps thirty items from them. Nothing checked whether a story that
three or more separate outlets ran made it in at all, so a missed story was
invisible: the brief read complete, it was just missing the thing everyone
else led with.

This clusters the day's English-language headlines by shared content words,
keeps the clusters carried by at least MIN_OUTLETS distinct outlets, and
reports any whose key words do not appear in the brief. It also counts what
each feed delivered, so a thin feed can be told from a quiet day.

The result is published as coverage.json next to the archive and summarised
as an annotation on the run. It changes nothing in the brief; it is a report.
Korean-language headlines are left out of the clustering, because the brief
is written in English and their words cannot be matched against it.
Nothing here raises.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

MIN_OUTLETS = 3
_STOP = set("""the a an and or of to in on for with from at by as is are was were be been
after amid over into about says said say new its their his her than that this these those
will would could may might not no yes more most up down out off has have had amid against
korea korean south north seoul pyongyang""".split())
_HANGUL = re.compile(r"[가-힣]")


def _outlet(article: dict) -> str:
    """Publisher, from a Google News ' - Publisher' suffix, else the feed's first word."""
    title = str(article.get("title", ""))
    if " - " in title:
        return title.rsplit(" - ", 1)[1].strip().lower()
    return str(article.get("source", "")).split(" ")[0].split("(")[0].strip().lower()


def _words(title: str) -> set[str]:
    title = title.rsplit(" - ", 1)[0] if " - " in title else title
    return {w for w in re.findall(r"[a-z][a-z'-]{2,}", title.lower()) if w not in _STOP}


def clusters(articles: list[dict]) -> list[dict]:
    """Greedy clustering of English headlines that share at least three content words."""
    groups: list[dict] = []
    for a in articles:
        title = str(a.get("title", ""))
        if not title or _HANGUL.search(title):
            continue
        w = _words(title)
        if len(w) < 3:
            continue
        best = None
        for g in groups:
            shared = len(w & g["core"])
            if shared >= 3 or (shared >= 2 and shared / max(1, min(len(w), len(g["core"]))) >= 0.5):
                best = g
                break
        if best is None:
            groups.append({"core": set(w), "titles": [title], "outlets": {_outlet(a)}, "words": Counter(w)})
        else:
            best["titles"].append(title)
            best["outlets"].add(_outlet(a))
            best["words"].update(w)
            best["core"] |= w
    return groups


def _brief_items(digest: dict) -> list[str]:
    """Each item of the brief as its own lowercased text, so a story's words must co-occur."""
    items: list[str] = []

    def flat(v) -> str:
        if isinstance(v, str):
            return v
        if isinstance(v, dict):
            return " ".join(flat(x) for k, x in v.items()
                            if k not in ("url", "source_links") and not str(k).startswith("_"))
        if isinstance(v, list):
            return " ".join(flat(x) for x in v)
        return ""

    def walk(v):
        if isinstance(v, dict):
            if any(k in v for k in ("headline", "body", "body_text", "action", "event", "quote_text", "note")):
                items.append(flat(v).lower())
                return
            for k, x in v.items():
                if not str(k).startswith("_"):
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, str):
                    items.append(x.lower())
                else:
                    walk(x)
    walk(digest)
    return items


def missed(payload: dict, digest: dict) -> list[dict]:
    """Widely covered stories whose key words are mostly absent from the brief."""
    arts = [a for a in (payload.get("tier1") or []) if isinstance(a, dict)]
    items = _brief_items(digest)
    out = []
    for g in clusters(arts):
        if len(g["outlets"]) < MIN_OUTLETS:
            continue
        key = [w for w, n in g["words"].most_common(6) if n >= 2] or [w for w, _ in g["words"].most_common(4)]
        best = max((sum(1 for w in key if re.search(rf"\b{re.escape(w)}", t)) for t in items), default=0)
        if best / len(key) < 0.6:
            out.append({"headline": g["titles"][0].rsplit(" - ", 1)[0], "outlets": len(g["outlets"]),
                        "sample_outlets": sorted(g["outlets"])[:5], "key_words": key,
                        "articles": len(g["titles"])})
    out.sort(key=lambda m: (-m["outlets"], -m["articles"]))
    return out[:15]


def feed_counts(payload: dict) -> dict:
    counts: dict = {}
    for tier in ("tier1", "tier2", "tier3", "tier4"):
        c = Counter(str(a.get("source", "?")) for a in (payload.get(tier) or []) if isinstance(a, dict))
        counts[tier] = dict(c.most_common())
    return counts


def run(payload: dict, digest: dict, public: Path, date_slug: str,
        silent_feeds: list[str] | None = None) -> dict:
    """Write coverage.json and return a short summary. Never raises."""
    try:
        miss = missed(payload, digest)
        report = {"date": date_slug, "possibly_missed": miss,
                  "feed_counts": feed_counts(payload), "silent_feeds": silent_feeds or []}
        public.mkdir(parents=True, exist_ok=True)
        (public / "coverage.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
        if miss:
            shown = "; ".join(f'{m["headline"][:70]} ({m["outlets"]} outlets)' for m in miss[:4])
            print(f"::warning title=Possibly missed stories::{len(miss)} widely covered "
                  f"stor{'y' if len(miss) == 1 else 'ies'} not found in the brief: {shown}")
        return {"possibly_missed": len(miss)}
    except Exception as e:                                      # noqa: BLE001
        print(f"  ⚠  Coverage audit skipped (non-fatal): {e}")
        return {}
