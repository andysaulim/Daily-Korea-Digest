"""Did the brief miss a story the press widely covered?

The pipeline collects several hundred tier-1 articles a day and the model
writes perhaps thirty items from them. Nothing checked whether a story that
three or more separate outlets ran made it in at all, so a missed story was
invisible: the brief read complete, it was just missing the thing everyone
else led with.

This clusters the day's English-language headlines by shared content words,
keeps the clusters carried by at least MIN_OUTLETS distinct outlets, and
reports any whose key words do not appear in the brief. It also counts what
each feed delivered, so a thin feed can be told from a quiet day, and lists
the notable analysis pieces (tier 2 and 3) that the Analysis section left out.

Sports, entertainment and human-interest clusters (golf tours, a shark in a
Busan canal, K-pop) are not reported: they are widely covered and correctly
left out, and warning about them every day buried the real misses.

The same clustering ranks the prompt: digest.rank_for_prompt moves one article
of each widely covered, non-noise story into the band the model always sees
(widely_covered below), because on 21 October 2026 both real misses were
Yonhap items ranked 149th and 248th against a 140-article cut.

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
korea korean south north seoul pyongyang lead update news""".split())
_HANGUL = re.compile(r"[가-힣]")

# Stories the brief is right to leave out however many outlets ran them.
NOISE = re.compile(
    r"\b(?:golf|golfer|pga|lpga|kpga|klpga|liv golf|baseball|kbo|mlb|football|soccer|k league"
    r"|premier league|world cup|olympic|paralympic|tennis|badminton|volleyball|basketball"
    r"|marathon|e-?sports|figure skat|athlete|shark|whale|dolphin|zoo|panda|puppy|cat cafe"
    r"|celebrit|actor|actress|singer|rapper|k-?pop|bts|blackpink|newjeans|aespa|idol|k-?drama"
    r"|drama series|box office|film festival|concert|fashion week|recipe|restaurant|michelin"
    r"|cafe industry|coffee|lottery|horoscope|beauty pageant)\b",
    re.IGNORECASE,
)

# One name per outlet, however the feed and Google News spell it: "Korea
# Times", "The Korea Times" and "Korea Times (Opinion)" are one outlet, and
# "Yonhap English", "Yonhap Politics" and "Yonhap News Agency" are one wire.
# The old rule took the first word of the source, so "The Korea Herald" and
# "The Korea Times" were one outlet ("the") and three Korea desks were one
# ("korea").
_OUTLET_STEMS = ("yonhap", "korea times", "korea herald", "joongang", "chosun", "dong-a", "donga",
                 "hankyoreh", "kyunghyang", "nk news", "nk pro", "daily nk", "reuters", "bloomberg",
                 "associated press", "wall street journal", "new york times", "washington post",
                 "financial times", "nikkei", "kyodo", "korea economic daily", "arirang", "kbs",
                 "sbs", "mbc", "jtbc", "newsis", "news1", "stripes", "38 north")
_ALIASES = {"wsj": "wall street journal", "nyt": "new york times", "wapo": "washington post",
            "ft": "financial times", "ap": "associated press", "연합뉴스": "yonhap",
            "stars and stripes": "stripes", "nkpro": "nk pro", "38north": "38 north"}


def outlet_name(article: dict) -> str:
    """The outlet behind an article, normalised so one outlet counts once."""
    title = str(article.get("title", ""))
    name = str(article.get("publisher") or article.get("source") or article.get("feed") or "")
    if not name and " - " in title:
        name = title.rsplit(" - ", 1)[1]
    n = name.lower().strip()
    n = re.sub(r"\(.*?\)", " ", n)
    n = re.sub(r"^the\s+", "", n)
    n = re.sub(r"\s*:\s*english edition$|\.com$|\.co\.kr$", "", n).strip()
    if n in _ALIASES:
        return _ALIASES[n]
    for stem in _OUTLET_STEMS:
        if stem in n:
            return "dong-a" if stem == "donga" else stem
    # Feed names: "WSJ Korea", "Japan Times Korea", "KCNA (Reuters)".
    first = re.sub(r"\s+korea$", "", n).strip()
    return _ALIASES.get(first, first) or "?"


def is_noise(title: str) -> bool:
    return bool(NOISE.search(str(title or "")))


def _outlet(article: dict) -> str:  # kept for callers of the old name
    return outlet_name(article)


def _words(title: str) -> set[str]:
    title = title.rsplit(" - ", 1)[0] if " - " in title else title
    title = re.sub(r"^\s*\((?:lead|2nd lead|update|news focus|yonhap interview)\)\s*", "", title, flags=re.I)
    return {w for w in re.findall(r"[a-z][a-z'-]{2,}", title.lower()) if w not in _STOP}


def clusters(articles: list[dict]) -> list[dict]:
    """Greedy clustering of English headlines that share at least three content words.

    Each group keeps its member articles (`members`, in input order) so a
    caller can act on them, not only count them.
    """
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
            groups.append({"core": set(w), "titles": [title], "outlets": {outlet_name(a)},
                           "words": Counter(w), "members": [a]})
        else:
            best["titles"].append(title)
            best["outlets"].add(outlet_name(a))
            best["words"].update(w)
            # The core stays the first headline's words. Grown with every
            # member, it snowballed: one cluster absorbed 44 headlines about
            # Ukraine, the PPP and embassy staff because each shared three
            # words with some earlier member.
            best["members"].append(a)
    return groups


def _noise_group(g: dict) -> bool:
    """Most of the group's headlines are sports, entertainment or human interest."""
    hits = sum(1 for t in g["titles"] if is_noise(t))
    return hits * 2 >= len(g["titles"])


def widely_covered(articles: list[dict], min_outlets: int = MIN_OUTLETS) -> list[tuple[int, list[dict]]]:
    """(outlet count, member articles) for each policy story at least min_outlets ran."""
    out = []
    for g in clusters(articles):
        if len(g["outlets"]) >= min_outlets and not _noise_group(g):
            out.append((len(g["outlets"]), g["members"]))
    return out


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
    """Widely covered policy stories whose key words are mostly absent from the brief."""
    arts = [a for a in (payload.get("tier1") or []) if isinstance(a, dict)]
    items = _brief_items(digest)
    out = []
    for g in clusters(arts):
        if len(g["outlets"]) < MIN_OUTLETS or _noise_group(g):
            continue
        key = [w for w, n in g["words"].most_common(6) if n >= 2] or [w for w, _ in g["words"].most_common(4)]
        best = max((sum(1 for w in key if re.search(rf"\b{re.escape(w)}", t)) for t in items), default=0)
        if best / len(key) < 0.6:
            out.append({"headline": re.sub(r"^\s*\((?:lead|2nd lead|update)\)\s*", "",
                                           g["titles"][0].rsplit(" - ", 1)[0], flags=re.I),
                        "outlets": len(g["outlets"]),
                        "sample_outlets": sorted(g["outlets"])[:5], "key_words": key,
                        "articles": len(g["titles"])})
    out.sort(key=lambda m: (-m["outlets"], -m["articles"]))
    return out[:15]


def _digest_urls(digest: dict) -> set[str]:
    urls: set[str] = set()

    def walk(v):
        if isinstance(v, dict):
            for k, x in v.items():
                if k in ("url", "secondary_url", "source_url") and isinstance(x, str):
                    urls.add(x.strip())
                else:
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(digest)
    return urls


def unused_analysis(payload: dict, digest: dict, limit: int = 8) -> list[dict]:
    """Notable tier-2/3 pieces the brief did not use.

    Notable: a think-tank report or journal article, or any piece from an
    A-rated outlet; reporting (kind "news") is not analysis and is skipped.
    The Analysis section takes three to five pieces, so a long list here on a
    day it ran short says the model, not the feeds, left them out.
    """
    used = _digest_urls(digest)
    out = []
    for tier in ("tier2", "tier3"):
        for a in payload.get(tier) or []:
            if not isinstance(a, dict) or (a.get("url") or "").strip() in used:
                continue
            kind = a.get("kind") or ("journal" if tier == "tier3" else "report")
            rating = str(a.get("prestige") or a.get("journal_tier") or "")
            if kind == "news" or not (kind in ("report", "journal") or rating.startswith("A")):
                continue
            out.append({"title": str(a.get("title", ""))[:140], "source": a.get("feed") or a.get("source"),
                        "kind": kind, "rating": rating, "url": a.get("url")})
    rank = {"A+": 0, "A": 1, "B": 2, "C": 3}
    out.sort(key=lambda r: (rank.get(r["rating"], 4), r["kind"] != "report"))
    return out[:limit]


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
        unused = unused_analysis(payload, digest)
        analysis_n = len(digest.get("opeds_today") or []) + len(digest.get("academic_today") or [])
        report = {"date": date_slug, "possibly_missed": miss,
                  "analysis_used": analysis_n, "analysis_unused": unused,
                  "feed_counts": feed_counts(payload), "silent_feeds": silent_feeds or []}
        public.mkdir(parents=True, exist_ok=True)
        (public / "coverage.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
        if miss:
            shown = "; ".join(f'{m["headline"][:70]} ({m["outlets"]} outlets)' for m in miss[:4])
            print(f"::warning title=Possibly missed stories::{len(miss)} widely covered "
                  f"stor{'y' if len(miss) == 1 else 'ies'} not found in the brief: {shown}")
        if unused and analysis_n < 3:
            shown = "; ".join(f'{u["source"]}: {u["title"][:60]}' for u in unused[:4])
            print(f"::warning title=Analysis left out::the Analysis section ran {analysis_n} "
                  f"piece(s) while {len(unused)} notable tier-2/3 piece(s) went unused: {shown}")
        return {"possibly_missed": len(miss), "analysis_unused": len(unused)}
    except Exception as e:                                      # noqa: BLE001
        print(f"  ⚠  Coverage audit skipped (non-fatal): {e}")
        return {}
