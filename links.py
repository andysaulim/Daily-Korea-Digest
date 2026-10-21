"""Link quality for the brief: every URL a reader can click.

An audit of ten issues (502 links) found a quarter of them were Google News
redirects that break or land on a consent wall, 25 pointed at pages no feed
had collected, 32 repeated a URL already used higher up the same issue, and
anchor text routinely named an outlet the link did not go to ("Reuters Korea"
opening Yonhap). URL repair and the HEAD check looked at eight item sections
and nothing else, and a dead link only produced a warning.

This module looks at every URL in the digest, wherever it sits, by walking it
for url-like keys rather than listing sections that drift as the schema grows.
It runs in two places:

``repair_all``  after generation, with the rest of the cleanup. A URL that is
                not in the corpus is repaired by headline or removed. The item
                stays; only its link goes, so nothing the model wrote against
                a source is lost, and no link ships that we cannot stand behind.
``finalize``    once the digest is final, just before rendering. Fixes anchor
                text, gives multi-outlet top stories a link per outlet or names
                only the one linked, strips trade-policy links to unrelated
                stories, removes duplicate URLs, decodes the handful of Google
                News redirects left, and HEAD-checks what remains. A 404 or 410
                loses its link.

Nothing here raises into the caller. Network work is bounded by short
timeouts and an overall deadline, and on any failure the link is left as it was.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as _FutTimeout
from urllib.parse import parse_qs, quote, unquote_plus, urlparse, urlencode

# ─────────────────────────────────────────────────────────────────────────────
# Domains and publishers
# ─────────────────────────────────────────────────────────────────────────────

# Second-level suffixes under which the registrable domain is three labels.
_SL_SUFFIXES = {
    "co.kr", "go.kr", "or.kr", "ac.kr", "re.kr", "mil.kr", "ne.kr", "pe.kr", "kr.co",
    "co.jp", "ne.jp", "or.jp", "go.jp", "ac.jp",
    "com.cn", "gov.cn", "org.cn", "net.cn", "edu.cn",
    "co.uk", "org.uk", "gov.uk", "ac.uk",
    "com.au", "gov.au", "org.au", "com.sg", "gov.sg", "edu.sg", "com.hk", "gov.hk",
    "co.in", "gov.in", "com.tw", "gov.tw", "org.tw", "co.nz", "com.br", "com.vn",
    "com.my", "com.ph", "co.id", "or.id", "co.za", "com.tr", "com.pk", "com.sa", "com.qa",
}


def host(url: str) -> str:
    """Lower-cased host without a leading www."""
    try:
        h = urlparse(url if "//" in str(url) else "//" + str(url)).hostname or ""
    except Exception:
        return ""
    h = h.lower().strip(".")
    return h[4:] if h.startswith("www.") else h


def base_domain(url_or_host: str) -> str:
    """Registrable domain: en.yna.co.kr -> yna.co.kr, edition.cnn.com -> cnn.com."""
    h = host(url_or_host) if ("/" in str(url_or_host) or ":" in str(url_or_host)) \
        else str(url_or_host).lower().strip(".")
    if h.startswith("www."):
        h = h[4:]
    parts = [p for p in h.split(".") if p]
    if len(parts) <= 2:
        return ".".join(parts)
    if ".".join(parts[-2:]) in _SL_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def is_google_news(url: str) -> bool:
    return "news.google.com" in str(url or "") and "/articles/" in str(url or "")


# Display names for outlets the brief links to most. Used when the corpus has
# no publisher for a URL (a native feed carries none) and to judge whether
# anchor text names the outlet a link actually opens.
DOMAIN_NAMES = {
    "yna.co.kr": "Yonhap", "koreaherald.com": "Korea Herald", "koreatimes.co.kr": "Korea Times",
    "joins.com": "JoongAng Daily", "joongang.co.kr": "JoongAng Ilbo",
    "chosun.com": "Chosun Ilbo", "hani.co.kr": "Hankyoreh", "donga.com": "Dong-A Ilbo",
    "khan.co.kr": "Kyunghyang Shinmun", "hankookilbo.com": "Hankook Ilbo",
    "newsis.com": "Newsis", "news1.kr": "News1", "seoul.co.kr": "Seoul Shinmun",
    "mk.co.kr": "Maeil Business", "hankyung.com": "Korea Economic Daily",
    "kedglobal.com": "Korea Economic Daily", "mbn.co.kr": "MBN",
    "jtbc.co.kr": "JTBC", "kbs.co.kr": "KBS", "imbc.com": "MBC", "sbs.co.kr": "SBS",
    "ytn.co.kr": "YTN", "ichannela.com": "Channel A", "channela.com": "Channel A",
    "arirang.com": "Arirang", "nknews.org": "NK News", "dailynk.com": "Daily NK",
    "38north.org": "38 North", "kcnawatch.org": "KCNA Watch", "korea.kr": "Korea.kr",
    "korea.net": "Korea.net", "reuters.com": "Reuters", "apnews.com": "AP",
    "nytimes.com": "New York Times", "wsj.com": "Wall Street Journal",
    "washingtonpost.com": "Washington Post", "ft.com": "Financial Times",
    "bloomberg.com": "Bloomberg", "bbc.com": "BBC", "bbc.co.uk": "BBC", "cnn.com": "CNN",
    "cnbc.com": "CNBC", "economist.com": "The Economist", "theguardian.com": "The Guardian",
    "aljazeera.com": "Al Jazeera", "nikkei.com": "Nikkei Asia", "japantimes.co.jp": "Japan Times",
    "scmp.com": "SCMP", "kyodonews.net": "Kyodo", "mainichi.jp": "Mainichi",
    "asahi.com": "Asahi Shimbun", "channelnewsasia.com": "CNA", "straitstimes.com": "Straits Times",
    "globaltimes.cn": "Global Times", "xinhuanet.com": "Xinhua", "news.cn": "Xinhua",
    "tass.com": "TASS", "chinadaily.com.cn": "China Daily", "people.cn": "People's Daily",
    "stripes.com": "Stars and Stripes", "defense.gov": "Pentagon", "state.gov": "State Department",
    "whitehouse.gov": "White House", "ustr.gov": "USTR", "treasury.gov": "Treasury",
    "commerce.gov": "Commerce", "federalregister.gov": "Federal Register",
    "congress.gov": "Congress.gov", "govinfo.gov": "GovInfo", "csis.org": "CSIS",
    "brookings.edu": "Brookings", "rand.org": "RAND", "cfr.org": "CFR", "stimson.org": "Stimson",
    "carnegieendowment.org": "Carnegie", "foreignaffairs.com": "Foreign Affairs",
    "thediplomat.com": "The Diplomat", "armscontrolwonk.com": "ArmsControlWonk",
    "x.com": "X", "twitter.com": "X", "france24.com": "France 24", "politico.com": "Politico",
    "thehill.com": "The Hill", "defensenews.com": "Defense News",
    "breakingdefense.com": "Breaking Defense", "un.org": "United Nations", "iaea.org": "IAEA",
    "mofa.go.kr": "MOFA", "mnd.go.kr": "MND", "unikorea.go.kr": "Unification Ministry",
    "president.go.kr": "Presidential Office", "moef.go.kr": "MOEF", "motie.go.kr": "MOTIE",
    "dapa.go.kr": "DAPA", "assembly.go.kr": "National Assembly", "jcs.mil.kr": "Joint Chiefs",
    "bok.or.kr": "Bank of Korea", "kostat.go.kr": "Statistics Korea",
    "customs.go.kr": "Korea Customs", "usfk.mil": "USFK",
}

# What anchor text may call each outlet. Short aliases match as whole words.
_ALIASES = {
    "yna.co.kr": ("yonhap", "yna", "연합"),
    "nytimes.com": ("nyt", "new york times", "ny times"),
    "wsj.com": ("wsj", "wall street journal"),
    "washingtonpost.com": ("wapo", "washington post"),
    "ft.com": ("ft", "financial times"),
    "apnews.com": ("ap", "associated press"),
    "koreaherald.com": ("korea herald", "herald"),
    "koreatimes.co.kr": ("korea times",),
    "joins.com": ("joongang", "중앙"),
    "joongang.co.kr": ("joongang", "중앙"),
    "chosun.com": ("chosun", "조선"),
    "hani.co.kr": ("hankyoreh", "hani", "한겨레"),
    "donga.com": ("dong-a", "donga", "동아"),
    "khan.co.kr": ("kyunghyang", "경향"),
    "hankookilbo.com": ("hankook", "한국일보"),
    "newsis.com": ("newsis", "뉴시스"),
    "news1.kr": ("news1", "news 1", "뉴스1"),
    "mk.co.kr": ("maeil", "매일경제", "mk"),
    "hankyung.com": ("hankyung", "korea economic daily", "ked", "한국경제"),
    "kedglobal.com": ("hankyung", "korea economic daily", "ked", "한국경제"),
    "imbc.com": ("mbc",), "kbs.co.kr": ("kbs",), "sbs.co.kr": ("sbs",),
    "nknews.org": ("nk news", "nk pro", "nknews"),
    "dailynk.com": ("daily nk", "dailynk"),
    "38north.org": ("38 north", "38north"),
    "kcnawatch.org": ("kcna watch", "kcna"),
    "korea.kr": ("korea.kr", "policy briefing", "정책브리핑"),
    "bbc.com": ("bbc",), "bbc.co.uk": ("bbc",),
    "nikkei.com": ("nikkei",), "scmp.com": ("scmp", "south china morning post"),
    "kyodonews.net": ("kyodo",), "asahi.com": ("asahi",),
    "channelnewsasia.com": ("cna", "channel newsasia", "channelnewsasia"),
    "xinhuanet.com": ("xinhua",), "news.cn": ("xinhua",),
    "theguardian.com": ("guardian",), "economist.com": ("economist",),
    "stripes.com": ("stars and stripes", "stripes"),
    "defense.gov": ("pentagon", "defense department", "dod"),
    "state.gov": ("state department", "state dept"),
    "president.go.kr": ("presidential office", "president.go.kr", "청와대", "대통령실", "blue house"),
    "mofa.go.kr": ("mofa", "foreign ministry", "외교부"),
    "mnd.go.kr": ("mnd", "defense ministry", "defence ministry", "국방부"),
    "unikorea.go.kr": ("unification", "mou", "통일부"),
    "jcs.mil.kr": ("jcs", "joint chiefs", "합참"),
    "bok.or.kr": ("bank of korea", "bok", "한국은행"),
    "x.com": ("x", "twitter"), "twitter.com": ("x", "twitter"),
}

_LABEL_STOP = {"the", "news", "korea", "korean", "daily", "ilbo", "online", "english", "en",
               "media", "agency", "service", "group", "com", "co", "kr", "org", "net", "www",
               "times", "post", "journal", "and", "of", "via", "report", "reports"}

# Domains a ROK Government card may call a primary document.
_PRIMARY_SUFFIXES = (".go.kr", ".mil.kr", ".assembly.go.kr")
_PRIMARY_DOMAINS = {"korea.kr", "bok.or.kr", "assembly.go.kr", "president.go.kr",
                    "korea.net", "na.go.kr", "fss.or.kr"}


def is_primary_url(url: str) -> bool:
    """A ROK government document: .go.kr, .mil.kr, korea.kr, the Assembly, the BOK."""
    h = host(url)
    if not h:
        return False
    if h.endswith(_PRIMARY_SUFFIXES) or h in ("go.kr", "mil.kr"):
        return True
    return base_domain(h) in _PRIMARY_DOMAINS or ("assembly" in h and h.endswith(".kr"))


def _english_outlet(name: str) -> str:
    """A Korean outlet name in English ('조선일보' -> 'Chosun Ilbo'); others unchanged.

    Google News gives a Korean-edition item's publisher in Korean, and the
    label pass used it as anchor text: 'Chosun Ilbo' became '조선일보' on
    21 October 2026, to be mapped back later by english.apply.
    """
    s = str(name or "").strip()
    if not _HANGUL.search(s):
        return s
    try:
        import english
        return english.outlet(s) or s
    except Exception:                                           # noqa: BLE001
        return s


_HANGUL = re.compile(r"[ㄱ-ㆎ가-힣]")


def publisher_name(url: str, publisher: str | None = None) -> str:
    """The outlet a URL opens, for anchor text, in English."""
    if publisher:
        return _english_outlet(publisher)
    bd = base_domain(url)
    if bd in DOMAIN_NAMES:
        return DOMAIN_NAMES[bd]
    h = host(url)
    for d, name in DOMAIN_NAMES.items():
        if h == d or h.endswith("." + d):
            return name
    return bd


def _squash(s: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", str(s).lower())


def label_matches_url(label: str, url: str, publisher: str | None = None) -> bool:
    """Does anchor text name the outlet this URL opens?

    Lenient by design: a false 'no' rewrites a label the model got right, so
    any reasonable signal (alias, domain stem, a shared distinctive word with
    the publisher's name) counts as a match.
    """
    lab = str(label or "").strip().lower()
    if not lab or not url:
        return True
    if is_google_news(url) and not publisher:
        return True                    # cannot tell where it goes
    bd = base_domain(url)
    sq = _squash(lab)
    for alias in _ALIASES.get(bd, ()):
        if len(alias) <= 3:
            if re.search(rf"(?<![0-9a-z]){re.escape(alias)}(?![0-9a-z])", lab):
                return True
        elif alias in lab or _squash(alias) in sq:
            return True
    stem = bd.split(".")[0]
    if len(stem) >= 3 and (stem in sq or (len(sq) >= 3 and sq in _squash(host(url)))):
        return True
    names = [publisher or "", _english_outlet(publisher or ""), DOMAIN_NAMES.get(bd, "")]
    lab_words = {w for w in re.split(r"[^0-9a-z가-힣]+", lab) if w and w not in _LABEL_STOP}
    for name in names:
        words = {w for w in re.split(r"[^0-9a-z가-힣]+", name.lower()) if w and w not in _LABEL_STOP}
        if words & lab_words:
            return True
        if name and _squash(name) and _squash(name) in sq:
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Google News search URLs and site: targets (used by collect.py)
# ─────────────────────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r'-?"[^"]*"|\(|\)|[^\s()]+')


def build_gnews_query(query: str) -> str:
    """Normalise a Google News query so a site: limit binds to all of it.

    `Korea+OR+DPRK+site:x` was meant as (Korea OR DPRK) AND site:x. Written
    flat, OR groups loosely enough that results came back from anywhere, which
    is how a "site:" feed delivered PM News Nigeria. Site and exclusion terms
    are pulled out; whatever remains is parenthesised when it contains an OR.
    A site: term joined by OR to something else stays where it is, because
    there the site is optional by design.
    """
    q = unquote_plus(str(query or ""))
    toks = _TOKEN_RE.findall(q)
    if "(" in toks or ")" in toks:
        return q.strip()                  # already explicit
    # A `when:3d` window is a filter on the whole search, like site:, and is
    # pulled out and bound the same way: left inside an OR chain it would
    # attach to the last alternative only.
    site_terms, window_terms, topic = [], [], []
    for i, t in enumerate(toks):
        prev_or = i > 0 and toks[i - 1] == "OR"
        next_or = i + 1 < len(toks) and toks[i + 1] == "OR"
        bare = t.lstrip("-")
        if bare.startswith("site:") and not prev_or and not next_or:
            site_terms.append(t)
        elif t.startswith("when:") and not prev_or and not next_or:
            window_terms.append(t)
        else:
            topic.append(t)
    if not site_terms and not window_terms:
        return " ".join(toks)
    head = " ".join(topic)
    if " OR " in f" {head} " and len(topic) > 1:
        head = f"({head})"
    return " ".join([p for p in (head, *site_terms, *window_terms) if p])


_GNEWS_LOCALES = {
    "en": "&hl=en-US&gl=US&ceid=US:en",
    # Korean edition. A Korean-language query against the US edition returns
    # a thin slice of the Korean press; the Korean edition indexes it fully.
    "ko": "&hl=ko&gl=KR&ceid=KR:ko",
}


def gnews_url(query: str, locale: str = "en") -> str:
    q = build_gnews_query(query)
    return ("https://news.google.com/rss/search?q=" + quote(q, safe="")
            + _GNEWS_LOCALES.get(locale, _GNEWS_LOCALES["en"]))


def site_targets(feed_url: str) -> list[str]:
    """Hosts a Google News search is limited to (required site: terms only).

    Returns [] for a native feed, for a search with no site:, and for a
    site: joined by OR (optional by design, e.g. the DART query).
    """
    if "news.google.com" not in str(feed_url or ""):
        return []
    try:
        q = parse_qs(urlparse(feed_url).query).get("q", [""])[0]
    except Exception:
        return []
    toks = _TOKEN_RE.findall(q)
    out = []
    for i, t in enumerate(toks):
        if not t.startswith("site:"):
            continue
        prev_or = i > 0 and toks[i - 1] == "OR"
        next_or = i + 1 < len(toks) and toks[i + 1] == "OR"
        if prev_or or next_or:
            return []
        out.append(t[5:].split("/")[0].lower())
    return out


def publisher_matches_site(publisher_home: str, targets: list[str]) -> bool:
    """True when the publisher's home is one of the searched sites (or unknown)."""
    if not targets:
        return True
    if not publisher_home:
        return True
    pb = base_domain(publisher_home)
    return any(base_domain(t) == pb for t in targets)


# ─────────────────────────────────────────────────────────────────────────────
# Walking the digest
# ─────────────────────────────────────────────────────────────────────────────

URL_KEYS = ("url", "secondary_url", "source_url")

# Not reader-facing article links: self-links, audio, machine lists, data the
# collector attached rather than the model wrote.
_SKIP_TOP = {"web_url", "audio_url", "listen_url", "timeline_candidates",
             "_trade_standing_html", "_locations_standing_html", "hill_calendar",
             "market_indicators", "_bp_changes", "_tariff_changes"}

# Render order, so "the later one" in dedup means later on the page.
RENDER_ORDER = ("morning_memo", "top_stories", "overnight_items", "key_stat", "kcna_delta",
                "rok_government", "rok_personnel", "rok_assembly", "election_tracker",
                "us_korea_deals", "capitol_hill", "business_economy", "northeast_asia",
                "korea_world", "public_sentiment", "calendar_watch", "also_today",
                "official_x_posts", "social_statements", "opeds_today", "academic_today",
                "imagery_report", "bp_locations", "on_this_day")


def _ordered_keys(digest: dict) -> list:
    keys = [k for k in RENDER_ORDER if k in digest]
    keys += [k for k in digest if k not in keys]
    return [k for k in keys if k not in _SKIP_TOP and not str(k).startswith("_")]


def iter_links(digest: dict):
    """Yield (path, container, key) for every reader-facing URL, in page order."""
    def walk(obj, path):
        if isinstance(obj, dict):
            for k in URL_KEYS:
                v = obj.get(k)
                if isinstance(v, str) and v.strip().startswith("http"):
                    yield path, obj, k
            for k, v in obj.items():
                if k in URL_KEYS:
                    continue
                if isinstance(v, (dict, list)):
                    yield from walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                if isinstance(v, (dict, list)):
                    yield from walk(v, f"{path}[{i}]")
    if not isinstance(digest, dict):
        return
    for top in _ordered_keys(digest):
        yield from walk(digest[top], top)


def section_of(path: str) -> str:
    return re.split(r"[.\[]", path, 1)[0]


def owner_of(path: str) -> str:
    """The item a link belongs to: a top story and its own source_links are one owner."""
    return re.sub(r"\.source_links\[\d+\]$", "", path)


def _item_text(container: dict) -> str:
    for k in ("headline", "translated_title", "title", "action", "item", "label",
              "event", "who", "quote_text"):
        v = container.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _item_body(container: dict) -> str:
    for k in ("body", "body_text", "summary", "detail", "quote_text", "activity"):
        v = container.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# The corpus: every URL the model was shown
# ─────────────────────────────────────────────────────────────────────────────

_TRACKING_PARAMS = re.compile(r"^(utm_|fbclid|gclid|ocid|cmpid|ref$|rss$|from$|oc$)")


def norm_url(url: str) -> str:
    """Matching key: scheme-less, no www, no tracking params, no fragment or trailing slash."""
    u = str(url or "").strip()
    if not u:
        return ""
    try:
        p = urlparse(u)
        q = [(k, v) for k, v in parse_qs(p.query, keep_blank_values=True).items()
             if not _TRACKING_PARAMS.match(k.lower())]
        query = urlencode(sorted((k, v[0] if v else "") for k, v in q))
        h = (p.hostname or "").lower()
        h = h[4:] if h.startswith("www.") else h
        path = p.path.rstrip("/")
        return f"{h}{path}" + (f"?{query}" if query else "")
    except Exception:
        return u


class Corpus(dict):
    """{norm_url: article}, with a token cache that never touches the articles."""

    def __init__(self):
        super().__init__()
        self._tok: dict = {}

    def tok(self, a: dict) -> set:
        k = id(a)
        if k not in self._tok:
            self._tok[k] = tokens(a.get("title") or a.get("headline") or "")
        return self._tok[k]


_PAYLOAD_SKIP = {"source_health", "feed_source_used", "market_indicators",
                 "sentiment_baseline", "hill_calendar"}


def corpus_index(payload) -> dict:
    """{norm_url: article} for every article anywhere in the payload.

    Accepts the collector's payload or a published corpus file (a list of
    records). Walks generically so a new stream is covered without a change
    here.
    """
    index = Corpus()

    def add(a):
        u = a.get("url")
        if isinstance(u, str) and u.startswith("http"):
            index.setdefault(norm_url(u), a)

    def walk(obj, depth=0):
        if depth > 4:
            return
        if isinstance(obj, dict):
            if isinstance(obj.get("url"), str):
                add(obj)
            for k, v in obj.items():
                if depth == 0 and k in _PAYLOAD_SKIP:
                    continue
                if isinstance(v, (dict, list)):
                    walk(v, depth + 1)
        elif isinstance(obj, list):
            for v in obj:
                walk(v, depth + 1)
    walk(payload or {})
    return index


_STOP = frozenset({"the", "a", "an", "in", "on", "of", "to", "for", "and", "is", "at", "by", "as",
                   "with", "from", "its", "new", "over", "after", "says", "said", "amid", "that",
                   "has", "will", "may", "could", "been", "are", "was", "were", "this", "but",
                   "not", "all", "more", "than", "also", "into", "about", "his", "her", "their"})


def tokens(text: str) -> set:
    return {w for w in re.split(r"\W+", str(text or "").lower()) if len(w) > 2 and w not in _STOP}


def _best_match(text: str, index: dict, min_overlap: int = 3, min_share: float = 0.5):
    tk = tokens(text)
    if len(tk) < min_overlap:
        return None, 0
    best, best_n = None, 0
    for a in index.values():
        at = index.tok(a) if isinstance(index, Corpus) else tokens(a.get("title") or "")
        if not at:
            continue
        n = len(tk & at)
        if n >= min_overlap and n / min(len(tk), len(at)) >= min_share and n > best_n:
            best, best_n = a, n
    return best, best_n


def lookup(url: str, index: dict):
    return index.get(norm_url(url)) if url else None


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: repair (after generation)
# ─────────────────────────────────────────────────────────────────────────────

def repair_all(digest: dict, payload) -> list[str]:
    """Every URL must be one the model was shown. Repair by headline, else unlink.

    run._repair_digest_urls already drops fabricated items from the main item
    sections (with floors). This covers everything else, and the items floor
    protection kept: their text stays, their invented link does not.
    """
    log: list[str] = []
    index = corpus_index(payload)
    if not index:
        return log
    for path, item, key in list(iter_links(digest)):
        url = item[key].strip()
        if lookup(url, index):
            art = lookup(url, index)
            if art.get("url") and art["url"] != url:
                item[key] = art["url"]       # canonical spelling
            continue
        text = _item_text(item) if key == "url" else ""
        best, n = _best_match(text, index) if text else (None, 0)
        if best:
            item[key] = best["url"]
            log.append(f"  repaired {path}.{key} by headline ({n} words): {text[:60]!r}")
        else:
            item[key] = ""
            log.append(f"  unlinked {path}.{key} (not in corpus): {url[:90]}")
    return log


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: finalize (digest is final)
# ─────────────────────────────────────────────────────────────────────────────

_LABEL_KEYS = ("source_label", "source", "label")
_MULTI_SPLIT = re.compile(r"\s*(?:/|,|;|·| & | \+ )\s*")
_DATE_TAIL = re.compile(r"\s+[—–-]\s+(?=[A-Z][a-z]{2}\b|\d)")


def split_outlets(label: str) -> tuple[list[str], str]:
    """'WaPo / AP / Reuters — Oct 17, 2026' -> (['WaPo','AP','Reuters'], 'Oct 17, 2026')."""
    s = str(label or "").strip()
    if ";" in s:
        # "뉴시스 — Oct 18; 경향신문 editorial — Oct 18": one outlet per segment.
        outs, first_tail = [], ""
        for seg in s.split(";"):
            o, t = split_outlets(seg)
            outs += [x for x in o if x not in outs]
            first_tail = first_tail or t
        return outs, first_tail
    tail = ""
    m = _DATE_TAIL.search(s)
    if m:
        s, tail = s[:m.start()], s[m.end():]
    # "Newsis (Oct 12)", "KCNA (Oct 13, 2026)": a dated parenthesis is the tail.
    paren = re.search(r"\s*\(([^)]*\d[^)]*)\)\s*$", s)
    if paren:
        s = s[:paren.start()]
        tail = tail or paren.group(1)
    s = re.sub(r"\s*\(([^)]*\d[^)]*)\)", "", s)
    outlets = [o.strip() for o in _MULTI_SPLIT.split(s) if o.strip()]
    return outlets, tail.strip()


_KCNA_FEED_LABEL = re.compile(r"^KCNA \(([^)]+)\)\s*(?:via|/)?\s*(.*)$")
_GENERIC_KCNA = {"state media", "kim stmt", "kcbs"}


def _known_outlet(name: str) -> bool:
    n = name.strip().lower()
    if not n:
        return False
    if n in {v.lower() for v in DOMAIN_NAMES.values()}:
        return True
    return any(n == a for al in _ALIASES.values() for a in al)


def clean_feed_label(label: str) -> str:
    """A collector feed name is not an outlet: 'KCNA (Reuters)' -> 'Reuters',
    'WSJ Korea' -> 'WSJ'. Anything else is returned unchanged."""
    lab = str(label or "").strip()
    m = _KCNA_FEED_LABEL.match(lab)
    if m:
        inner, rest = m.group(1).strip(), m.group(2).strip()
        if rest:
            return rest
        return "KCNA" if inner.lower() in _GENERIC_KCNA else inner
    if lab.endswith(" Korea") and _known_outlet(lab[:-len(" Korea")]):
        return lab[:-len(" Korea")]
    return lab


def fix_labels(digest: dict, index: dict) -> list[str]:
    """Anchor text must name the outlet the link opens.

    Single-outlet labels that name a different outlet are replaced with the
    URL's publisher. Multi-outlet labels are left to fix_multi_outlet. ROK
    Government cards keep a ministry label only when the link is that
    ministry's own document.
    """
    log = []
    for path, item, key in iter_links(digest):
        if key != "url":
            if key == "secondary_url":
                url = item[key]
                art = lookup(url, index) or {}
                pub = publisher_name(url, art.get("publisher"))
                lab = item.get("secondary_label", "")
                if not lab or not label_matches_url(lab, url, art.get("publisher")):
                    item["secondary_label"] = pub
            continue
        url = item[key]
        art = lookup(url, index) or {}
        pub_raw = art.get("publisher")
        sec = section_of(path)
        if sec == "top_stories":
            continue
        for lk in _LABEL_KEYS:
            lab = item.get(lk)
            if not isinstance(lab, str) or not lab.strip():
                continue
            cleaned = clean_feed_label(lab)
            if cleaned != lab:
                log.append(f"  label {path}.{lk}: {lab!r} -> {cleaned!r} (feed name)")
                item[lk] = lab = cleaned
            outlets, _tail = split_outlets(lab)
            if len(outlets) > 1:
                break
            new = _better_label(lab, url, pub_raw, art, sec)
            if new and new != lab:
                log.append(f"  label {path}.{lk}: {lab!r} -> {new!r} ({host(url)})")
                item[lk] = new
            break
    return log


# Hosts that publish journals for many societies. The anchor text for an
# article there is the journal ("Asian Security"), which no host name says:
# on 21 October 2026 the label pass replaced 'Asian Security' with
# 'tandfonline.com'.
JOURNAL_PLATFORMS = {
    "tandfonline.com", "mit.edu", "ucpress.edu", "jhu.edu", "oup.com", "cambridge.org",
    "springer.com", "sagepub.com", "wiley.com", "jstor.org", "sciencedirect.com",
    "brill.com", "degruyter.com", "muse.jhu.edu", "kci.go.kr", "dbpia.co.kr", "nbr.org",
}
_X_HOSTS = {"x.com", "twitter.com"}


def x_owner_label(label: str, url: str, art: dict | None = None) -> str:
    """'<account owner> on X' for a post: 'MOF Minister on X', not 'X'.

    The owner is the collected account's name (x_signals carry it), else the
    label the model wrote when it names someone, else the handle in the URL.
    """
    art = art or {}
    lab = re.sub(r"\s+on\s+(?:x|twitter)\s*$", "", str(label or "").strip(), flags=re.I).strip()
    owner = str(art.get("name") or "").strip()
    if not owner and lab.lower() not in ("", "x", "twitter", "x.com", "twitter.com"):
        owner = lab
    if not owner:
        m = re.match(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})(?:/|$)",
                     str(url or ""))
        owner = f"@{m.group(1)}" if m and m.group(1).lower() not in ("i", "home", "search") else ""
    return f"{owner} on X" if owner else "X"


def _better_label(lab: str, url: str, pub_raw, art: dict, sec: str) -> str | None:
    """The anchor text a link should carry, or None to keep `lab`."""
    bd = base_domain(url)
    if bd in _X_HOSTS:
        return x_owner_label(lab, url, art)
    if label_matches_url(lab, url, pub_raw):
        return None
    # A journal keeps its name: the host is a publishing platform.
    if sec == "academic_today" or bd in JOURNAL_PLATFORMS or host(url) in JOURNAL_PLATFORMS:
        return None
    new = publisher_name(url, pub_raw)
    # Never trade an English label for a Korean one.
    if _HANGUL.search(new) and not _HANGUL.search(lab):
        return None
    return new


def fix_multi_outlet(digest: dict, index: dict, used_elsewhere: set) -> list[str]:
    """A top story that names several outlets links each one, or names one.

    For every outlet named in src_line/source, find a corpus article from that
    outlet about the same story (shared headline words). Those become
    source_links. Outlets with no such article are dropped from the text, so it
    never names an outlet a reader cannot open.
    """
    log = []
    for i, story in enumerate(digest.get("top_stories") or []):
        if not isinstance(story, dict):
            continue
        url = str(story.get("url") or "")
        label_key = "src_line" if story.get("src_line") else "source"
        label = str(story.get(label_key) or "")
        outlets, tail = split_outlets(label)
        outlets = [clean_feed_label(o) for o in outlets]
        art = lookup(url, index) or {}
        pub_raw = art.get("publisher")
        main_known = url.startswith("http") and not (is_google_news(url) and not pub_raw)
        if len(outlets) <= 1:
            new = outlets[0] if outlets else ""
            if main_known and outlets and not label_matches_url(outlets[0], url, pub_raw):
                new = publisher_name(url, pub_raw)
            if outlets and (new != split_outlets(label)[0][0]
                            or (label_key == "src_line" and story.get("source")
                                and clean_feed_label(story["source"]) != story["source"])):
                story[label_key] = new + (f" — {tail}" if tail else "")
                if label_key == "src_line" and story.get("source"):
                    story["source"] = new
                log.append(f"  top_stories[{i}] label {label!r} -> {story[label_key]!r}")
            continue
        text = f"{story.get('headline', '')} {story.get('body', '')}"
        tk = tokens(text)
        links, taken = [], {norm_url(url)} | used_elsewhere
        for o in outlets:
            if main_known and label_matches_url(o, url, pub_raw) and not any(
                    l["url"] == url for l in links):
                links.append({"label": o, "url": url})
                continue
            best, best_n = None, 1
            for a in index.values():
                au = a.get("url") or ""
                if norm_url(au) in taken or not au.startswith("http"):
                    continue
                if is_google_news(au) and not a.get("publisher"):
                    continue
                if not label_matches_url(o, au, a.get("publisher")):
                    continue
                n = len(tk & index.tok(a))
                if n > best_n and n >= 3:
                    best, best_n = a, n
            if best:
                links.append({"label": o, "url": best["url"]})
                taken.add(norm_url(best["url"]))
        if not main_known:
            # We cannot tell which outlet the main link opens. Keep the text if
            # nothing else is known; otherwise the found links speak for it.
            if not links:
                continue
        if main_known and not any(l["url"] == url for l in links):
            links.insert(0, {"label": publisher_name(url, pub_raw), "url": url})
        named = [l["label"] for l in links]
        story["source_links"] = links
        story[label_key] = " / ".join(named) + (f" — {tail}" if tail else "")
        if label_key == "src_line" and story.get("source"):
            story["source"] = " / ".join(named)
        log.append(f"  top_stories[{i}] outlets {outlets} -> linked {named}")
    return log


_TRADE_GENERIC = {"korea", "korean", "south", "trade", "united", "states", "policy", "government",
                  "measure", "measures", "rules", "rule", "active", "status", "agency", "department",
                  "seoul", "washington", "2025", "2026", "2027", "percent", "ministry", "officials"}


def _content_words(text: str) -> set:
    return {w for w in tokens(text) if w not in _TRADE_GENERIC}


def fix_trade_links(digest: dict, index: dict) -> list[str]:
    """A trade-policy measure links only to a story about that measure."""
    log = []
    uk = digest.get("us_korea_deals")
    if not isinstance(uk, dict):
        return log
    for sub in ("trade_policy", "deals"):
        for j, m in enumerate(uk.get(sub) or []):
            if not isinstance(m, dict):
                continue
            url = str(m.get("url") or "")
            if not url.startswith("http"):
                continue
            art = lookup(url, index)
            title = (art or {}).get("title") or ""
            if not title:
                continue          # cannot judge; leave it to repair/HEAD
            measure = " ".join(str(m.get(k) or "") for k in ("item", "title", "name", "deal",
                                                             "headline", "detail", "agency"))
            shared = _content_words(measure) & _content_words(title)
            if len(shared) < 2:
                m["url"] = ""
                log.append(f"  unlinked us_korea_deals.{sub}[{j}] "
                           f"({str(m.get('item') or m.get('title') or '')[:50]!r} vs "
                           f"headline {title[:50]!r})")
    return log


def dedup_links(digest: dict) -> list[str]:
    """One URL, one link per issue: a later repeat keeps its text, loses its link."""
    log, seen = [], {}
    for path, item, key in iter_links(digest):
        u = norm_url(item[key])
        if not u:
            continue
        if key == "secondary_url" and norm_url(item.get("url")) == u:
            item[key] = ""
            log.append(f"  duplicate {path}.secondary_url (same as its primary link)")
            continue
        first = seen.get(u)
        if first is None:
            seen[u] = path
        elif owner_of(first) != owner_of(path):
            item[key] = ""
            log.append(f"  duplicate {path}.{key} (first used in {first})")
    return log


# ─────────────────────────────────────────────────────────────────────────────
# Google News decoding
# ─────────────────────────────────────────────────────────────────────────────

GNEWS_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gnews_cache.json")
_CACHE_DAYS = 45
_BATCH_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def gnews_article_id(url: str) -> str:
    try:
        seg = urlparse(url).path.split("/articles/", 1)[1]
    except (IndexError, Exception):
        return ""
    return seg.split("?", 1)[0].split("/", 1)[0]


def decode_legacy(article_id: str) -> str:
    """The old format embedded the URL in base64 protobuf. '' when it does not."""
    try:
        enc = article_id + "=" * (-len(article_id) % 4)
        raw = base64.urlsafe_b64decode(enc)
    except Exception:
        return ""
    s = raw.decode("latin-1", errors="ignore")
    if "AU_yqL" in s[:12]:
        return ""
    m = re.search(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%\-]+", s)
    if m and "news.google.com" not in m.group(0):
        return m.group(0)
    return ""


_SG_RE = re.compile(r'data-n-a-sg="([^"]+)"')
_TS_RE = re.compile(r'data-n-a-ts="(\d+)"')
_AU_RE = re.compile(r'data-n-au="(https?://[^"]+)"')


def parse_direct_url(html: str) -> str:
    """Some article pages carry the target outright in data-n-au."""
    m = _AU_RE.search(html or "")
    if not m:
        return ""
    import html as _html
    u = _html.unescape(m.group(1))
    return "" if "news.google.com" in u else u


def parse_signature(html: str) -> tuple[str, str] | None:
    """(signature, timestamp) from a Google News article page, else None."""
    sg, ts = _SG_RE.search(html or ""), _TS_RE.search(html or "")
    if not sg or not ts:
        return None
    return sg.group(1), ts.group(1)


def batch_request_body(article_id: str, ts: str, sg: str) -> str:
    inner = ('["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,'
             'null,null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],'
             f'"{article_id}",{int(ts)},"{sg}"]')
    freq = [[["Fbv4je", inner, None, "generic"]]]
    return "f.req=" + quote(json.dumps(freq, separators=(",", ":")), safe="")


def parse_batch_response(text: str) -> str:
    """The article URL from a batchexecute reply, or ''.

    The reply is `)]}'`, then length-prefixed JSON chunks. The one we want is
    ["wrb.fr","Fbv4je","[\\"garturlres\\",\\"<url>\\",1]",...]. Parsed
    structurally first, with a regex fallback for format drift.
    """
    if not text:
        return ""
    body = text[4:] if text.startswith(")]}'") else text
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("["):
            continue
        try:
            data = json.loads(line)
        except Exception:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                if (len(node) > 2 and node[0] == "wrb.fr" and isinstance(node[2], str)
                        and "garturlres" in node[2]):
                    try:
                        inner = json.loads(node[2])
                        u = inner[1]
                        if isinstance(u, str) and u.startswith("http") and "news.google.com" not in u:
                            return u
                    except Exception:
                        pass
                stack.extend(node)
    m = re.search(r'garturlres\\+",\\+"(https?://[^"\\]+)', body)
    if m and "news.google.com" not in m.group(1):
        return m.group(1)
    return ""


def decode_gnews(url: str, session=None, timeout: float = 5.0) -> str:
    """Resolve a news.google.com article link to the publisher URL, or ''."""
    aid = gnews_article_id(url)
    if not aid:
        return ""
    legacy = decode_legacy(aid)
    if legacy:
        return legacy
    import requests
    s = session or requests.Session()
    headers = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}
    sig = None
    for page in (f"https://news.google.com/articles/{aid}?hl=en-US&gl=US&ceid=US:en",
                 f"https://news.google.com/rss/articles/{aid}?hl=en-US&gl=US&ceid=US:en"):
        try:
            r = s.get(page, headers=headers, timeout=timeout)
            if r.status_code == 200:
                direct = parse_direct_url(r.text)
                if direct:
                    return direct
                sig = parse_signature(r.text)
                if sig:
                    break
        except Exception:
            continue
    if not sig:
        return ""
    sg, ts = sig
    try:
        r = s.post(_BATCH_URL, data=batch_request_body(aid, ts, sg), timeout=timeout,
                   headers={**headers,
                            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        if r.status_code != 200:
            return ""
        return parse_batch_response(r.text)
    except Exception:
        return ""


def _load_cache(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(path: str, cache: dict) -> None:
    cutoff = time.time() - _CACHE_DAYS * 86400
    pruned = {k: v for k, v in cache.items()
              if isinstance(v, dict) and v.get("t", 0) >= cutoff}
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(pruned, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass


def decode_digest_links(digest: dict, cache_path: str = GNEWS_CACHE,
                        deadline: float = 20.0, decoder=None) -> list[str]:
    """Replace Google News redirects in the final digest with publisher URLs.

    About a dozen a day, so cost is trivial; results are cached across runs.
    Bounded by `deadline` seconds in all. A link that cannot be decoded stays
    as it is (fix_labels has already named its publisher).
    """
    decoder = decoder or decode_gnews
    log = []
    targets = {}
    for path, item, key in iter_links(digest):
        if is_google_news(item[key]):
            targets.setdefault(item[key], []).append((path, item, key))
    if not targets:
        return log
    cache = _load_cache(cache_path)
    resolved = {}
    todo = []
    for u in targets:
        hit = cache.get(gnews_article_id(u))
        if hit and hit.get("url"):
            resolved[u] = hit["url"]
        else:
            todo.append(u)
    if todo:
        start = time.time()
        try:
            import requests
            session = requests.Session()
        except Exception:
            session = None
        pool = ThreadPoolExecutor(max_workers=4)
        futs = {pool.submit(decoder, u, session): u for u in todo}
        try:
            for f in as_completed(futs, timeout=max(1.0, deadline - (time.time() - start))):
                u = futs[f]
                try:
                    out = f.result()
                except Exception:
                    out = ""
                if out:
                    resolved[u] = out
                    cache[gnews_article_id(u)] = {"url": out, "t": time.time()}
        except _FutTimeout:
            log.append(f"  decode deadline ({deadline:.0f}s) reached; "
                       f"{len(todo) - len([u for u in todo if u in resolved])} left as redirects")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        _save_cache(cache_path, cache)
    for u, places in targets.items():
        if u in resolved:
            for path, item, key in places:
                item[key] = resolved[u]
                if key == "url":
                    # Keeps the corpus's used_in_digest match, which is by URL.
                    item["gnews_url"] = u
    n_ok = len(resolved)
    log.insert(0, f"  Google News links: {len(targets)} found, {n_ok} decoded, "
                  f"{len(targets) - n_ok} kept as redirects")
    return log


# ─────────────────────────────────────────────────────────────────────────────
# HEAD check
# ─────────────────────────────────────────────────────────────────────────────

def check_url(url: str, timeout: float = 5.0) -> tuple[str, str]:
    """('dead'|'ok'|'unknown', reason). Only 404/410, confirmed by GET, is dead.

    Paywalls and bot walls answer 401/403/405/429/451; that is not a dead
    link. A Google News redirect answers 200 whatever is behind it, so it is
    'unknown', never 'ok'.
    """
    if is_google_news(url):
        return "unknown", "google news redirect"
    try:
        import requests
        h = {"User-Agent": _UA}
        r = requests.head(url, timeout=timeout, allow_redirects=True, headers=h)
        if r.status_code not in (404, 410):
            return "ok", str(r.status_code)
        # Some servers answer HEAD with 404 and GET with the page.
        g = requests.get(url, timeout=timeout, allow_redirects=True, headers=h, stream=True)
        g.close()
        if g.status_code in (404, 410):
            return "dead", f"HTTP {g.status_code}"
        return "ok", str(g.status_code)
    except Exception as e:
        return "unknown", type(e).__name__


def head_check(digest: dict, deadline: float = 30.0, checker=None) -> list[str]:
    """HEAD every link; a confirmed 404/410 loses its link everywhere it appears."""
    checker = checker or check_url
    places = {}
    for path, item, key in iter_links(digest):
        places.setdefault(item[key], []).append((path, item, key))
    if not places:
        return []
    log, results = [], {}
    pool = ThreadPoolExecutor(max_workers=10)
    futs = {pool.submit(checker, u): u for u in places}
    try:
        for f in as_completed(futs, timeout=deadline):
            try:
                results[futs[f]] = f.result()
            except Exception:
                results[futs[f]] = ("unknown", "check failed")
    except _FutTimeout:
        log.append(f"  HEAD check deadline ({deadline:.0f}s) reached; "
                   f"{len(places) - len(results)} unchecked")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    dead = [(u, r) for u, (s, r) in results.items() if s == "dead"]
    for u, reason in dead:
        for path, item, key in places[u]:
            item[key] = ""
        log.append(f"  dead link removed ({reason}): {u[:100]}")
    ok = sum(1 for s, _ in results.values() if s == "ok")
    unk = sum(1 for s, _ in results.values() if s == "unknown")
    log.insert(0, f"  HEAD check: {len(places)} links, {ok} ok, {len(dead)} dead, {unk} unverified")
    return log


def _prune_source_links(digest: dict) -> None:
    for story in digest.get("top_stories") or []:
        if not isinstance(story, dict) or not isinstance(story.get("source_links"), list):
            continue
        kept = [l for l in story["source_links"]
                if isinstance(l, dict) and str(l.get("url", "")).startswith("http")]
        story["source_links"] = kept
        if story.get("url") and not str(story["url"]).startswith("http"):
            story["url"] = ""
        if kept and not str(story.get("url") or "").startswith("http"):
            story["url"] = kept[0]["url"]


def used_urls(digest: dict, exclude_section: str | None = None) -> set:
    return {norm_url(item[key]) for path, item, key in iter_links(digest)
            if section_of(path) != exclude_section}


def finalize(digest: dict, payload, network: bool = True,
             cache_path: str = GNEWS_CACHE) -> list[str]:
    """Final link pass. Mutates digest; returns log lines. Never raises."""
    log: list[str] = []
    try:
        index = corpus_index(payload)
        for title, fn in (
                ("labels", lambda: fix_labels(digest, index)),
                ("multi-outlet top stories",
                 lambda: fix_multi_outlet(digest, index, used_urls(digest, "top_stories"))),
                ("trade links", lambda: fix_trade_links(digest, index)),
                ("duplicate links", lambda: dedup_links(digest))):
            lines = fn()
            if lines:
                log.append(f"🔗  Links, {title}: {len(lines)}")
                log.extend(lines)
        if network:
            lines = decode_digest_links(digest, cache_path=cache_path)
            if lines:
                log.append("🔗  Links, Google News decoding:")
                log.extend(lines)
            lines = dedup_links(digest)       # decoding can reveal a repeat
            if lines:
                log.append(f"🔗  Links, duplicates after decoding: {len(lines)}")
                log.extend(lines)
            lines = head_check(digest)
            if lines:
                log.append("🔗  Links, HEAD check:")
                log.extend(lines)
        _prune_source_links(digest)
    except Exception as e:                                  # noqa: BLE001
        log.append(f"🔗  Link pass failed (non-fatal): {e}")
    return log


# ─────────────────────────────────────────────────────────────────────────────
# Audit (offline measurement)
# ─────────────────────────────────────────────────────────────────────────────

def audit(digest: dict, payload) -> dict:
    """Counts for the run log and for before/after comparison."""
    index = corpus_index(payload)
    total = gnews = not_in = dup = wrong = feed_labels = 0
    seen: dict = {}
    for path, item, key in iter_links(digest):
        u = item[key]
        n = norm_url(u)
        if n in seen and owner_of(seen[n]) == owner_of(path):
            continue                       # a top story's own outlet list
        total += 1
        gnews += is_google_news(u)
        if index and not lookup(u, index):
            not_in += 1
        if n in seen:
            dup += 1
        else:
            seen[n] = path
        if key != "url":
            continue
        art = lookup(u, index) or {}
        for lk in _LABEL_KEYS:
            lab = item.get(lk)
            if isinstance(lab, str) and lab.strip():
                outlets, _ = split_outlets(lab)
                if any(clean_feed_label(o) != o for o in outlets):
                    feed_labels += 1
                if section_of(path) == "top_stories":
                    if re.fullmatch(r"top_stories\[\d+\]", path) and story_label_wrong(item, index):
                        wrong += 1
                elif len(outlets) == 1 \
                        and not label_matches_url(lab, u, art.get("publisher")):
                    wrong += 1
                break
    return {"links": total, "google_news": gnews, "not_in_corpus": not_in,
            "duplicates": dup, "wrong_labels": wrong, "feed_name_labels": feed_labels}


def story_label_wrong(story: dict, index: dict) -> bool:
    """A top story's source text names an outlet it does not link."""
    label = str(story.get("src_line") or story.get("source") or "")
    outlets, _ = split_outlets(label)
    linked = [l for l in (story.get("source_links") or []) if isinstance(l, dict)
              and str(l.get("url", "")).startswith("http")]
    url = str(story.get("url") or "")
    if not linked and url.startswith("http"):
        linked = [{"label": outlets[0] if outlets else "", "url": url}]
    if len(outlets) > len(linked):
        return True
    for o, l in zip(outlets, linked):
        art = lookup(l["url"], index) or {}
        if not label_matches_url(o, l["url"], art.get("publisher")):
            return True
    return False
