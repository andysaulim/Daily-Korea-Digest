"""
CSIS Korea Digest — Collector
Scrapes RSS feeds across four tiers + market data.
Uses threaded fetching for performance (~15s vs ~60s sequential).
"""
import feedparser
import requests
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

# ─────────────────────────────────────────────────────────────────────────────
# FEED CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

def _gnews(query: str) -> str:
    """Build a Google News RSS search URL."""
    return f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


TIER1_FEEDS = {
    # ── Korean English-language dailies ────────────────────────────────────
    "Korea Herald":       "http://www.koreaherald.com/common/rss_xml.php?ct=102",
    "Korea Times":        "https://www.koreatimes.co.kr/www/rss/nation.xml",
    "Yonhap English":     "https://en.yna.co.kr/RSS/news.xml",
    "JoongAng Daily":     "https://koreajoongangdaily.joins.com/section/rss",
    "Chosun English":     _gnews("Korea+site:english.chosun.com"),
    "Hankyoreh English":  _gnews("Korea+site:english.hani.co.kr"),
    "Dong-A English":     _gnews("Korea+site:donga.com/en"),
    "NK News":            "https://www.nknews.org/feed/",
    # ── Korean-language feeds (Claude translates during analysis) ──────────
    "조선일보":            _gnews("site:chosun.com+-english"),
    "한겨레":              _gnews("site:hani.co.kr+-english"),
    "동아일보":            _gnews("site:donga.com+-en"),
    "MBN":                _gnews("Korea+site:mbn.co.kr"),
    # ── Major international — Korea correspondents ────────────────────────
    "WSJ Korea":          _gnews("Korea+site:wsj.com"),
    "NYT Korea":          _gnews("Korea+site:nytimes.com"),
    "WaPo Korea":         _gnews("Korea+site:washingtonpost.com"),
    "FT Korea":           _gnews("Korea+site:ft.com"),
    "Reuters Korea":      _gnews("Korea+site:reuters.com"),
    "AP Korea":           _gnews("Korea+site:apnews.com"),
    "Bloomberg Korea":    _gnews("Korea+site:bloomberg.com"),
    "BBC Korea":          _gnews("Korea+site:bbc.com"),
    "CNN Korea":          _gnews("Korea+site:cnn.com"),
    "Guardian Korea":     _gnews("Korea+site:theguardian.com"),
    "Al Jazeera Korea":   _gnews("Korea+site:aljazeera.com"),
    # ── Regional Asia ─────────────────────────────────────────────────────
    "Nikkei Korea":       _gnews("Korea+site:asia.nikkei.com"),
    "Japan Times Korea":  _gnews("Korea+site:japantimes.co.jp"),
    "SCMP Korea":         _gnews("Korea+site:scmp.com"),
    # ── ROK/US Government ─────────────────────────────────────────────────
    "White House":        _gnews("Korea+site:whitehouse.gov"),
    "State Dept":         _gnews("Korea+site:state.gov"),
    "Pentagon":           _gnews("Korea+site:defense.gov"),
    "Stars and Stripes":  _gnews("Korea+site:stripes.com"),
    # ── Reaction layer (China/Russia) ─────────────────────────────────────
    "Global Times Korea": _gnews("Korea+site:globaltimes.cn"),
    "Xinhua Korea":       _gnews("Korea+site:xinhuanet.com"),
    "TASS Korea":         _gnews("Korea+site:tass.com"),
}

TIER2_FEEDS = {
    "CSIS":              (_gnews("Korea+site:csis.org"), "A"),
    "Brookings":         ("https://www.brookings.edu/feed/", "A"),
    "Carnegie":          ("https://carnegieendowment.org/rss/solr?query=korea", "A"),
    "RAND":              ("https://www.rand.org/topics/north-korea.xml", "A"),
    "CFR":               (_gnews("Korea+site:cfr.org"), "A"),
    "38 North":          (_gnews("site:38north.org"), "A"),
    "Stimson":           ("https://www.stimson.org/feed/", "B"),
    "IISS":              (_gnews("Korea+site:iiss.org"), "B"),
    "ASAN Institute":    (_gnews("Korea+site:asaninst.org"), "B"),
    "EAI":               ("https://www.eai.or.kr/new/en/etc/rss.asp", "B"),
    "Sejong Institute":  (_gnews("Korea+site:sejong.org"), "B"),
    "SIPRI":             (_gnews("Korea+site:sipri.org"), "B"),
    "War on the Rocks":  ("https://warontherocks.com/feed/", "B"),
    "Foreign Affairs":   ("https://www.foreignaffairs.com/rss.xml", "A"),
    "Foreign Policy":    ("https://foreignpolicy.com/feed/", "B"),
    "Diplomat":          ("https://thediplomat.com/feed/", "C"),
    "NKPro":             ("https://www.nknews.org/pro/feed/", "A"),
}

# Tier 3: Use Google Scholar RSS and site-specific searches to reduce noise
TIER3_FEEDS = {
    "Int'l Security":     (_gnews("%22International+Security%22+%22Korea%22+OR+%22DPRK%22+OR+%22Pyongyang%22"), "A+"),
    "J. Conflict Resolution": (_gnews("%22Journal+of+Conflict+Resolution%22+%22Korea%22+OR+%22DPRK%22"), "A"),
    "Asian Survey":       (_gnews("%22Asian+Survey%22+%22Korea%22+OR+%22DPRK%22+OR+%22Korean+Peninsula%22"), "A"),
    "Pacific Review":     (_gnews("%22Pacific+Review%22+%22Korea%22+OR+%22DPRK%22"), "A"),
    "Korean J. Def. Analysis": (_gnews("%22Korean+Journal+of+Defense+Analysis%22"), "B"),
    "North Korean Review": (_gnews("%22North+Korean+Review%22"), "B"),
    "KINU":               (_gnews("Korea+site:kinu.or.kr"), "B"),
}

TIER4_FEEDS = {
    "KCNA Watch":        "https://kcnawatch.org/newstream/feed/",
    "KCNA":              _gnews("site:kcna.kp"),
    "Rodong Sinmun":     _gnews("site:rodong.rep.kp"),
    "KCNA (Yonhap)":     _gnews("KCNA+Yonhap"),
}

KOREA_KEYWORDS = re.compile(
    r"korea|dprk|pyongyang|seoul|rok\b|kim jong|yoon suk|korean peninsula"
    r"|denucleariz|kaesong|yongbyon|hwasong|punggye|38th parallel"
    r"|usfk|combined forces|kim yo jong|choe son hui"
    r"|north korea|south korea|inter-korean"
    r"|한반도|북한|남북|조선민주주의|평양|서울|통일부|국방부",
    re.IGNORECASE,
)

PRESTIGE_JOURNALISTS = {
    "Timothy Martin", "Dasl Yoon", "Choe Sang-Hun", "Michelle Ye Hee Lee",
    "Christian Davies", "Hyonhee Shin", "Josh Smith", "Joyce Lee",
    "Ankit Panda", "Jenny Town", "Andrei Lankov", "Rachel Minyoung Lee",
    "Jean Lee", "Laura Bicker", "Simon Mundy", "Edward White",
    "Dagyum Ji", "Ifang Bremer", "Chad O'Carroll",
}

REQUEST_TIMEOUT = 12
HEADERS = {"User-Agent": "CSISKoreaDigest/1.0"}
MAX_WORKERS = 20  # Thread pool size for parallel fetching


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _parse_feed(url: str) -> list:
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
        return feedparser.parse(resp.content).entries
    except Exception as e:
        print(f"    ⚠  Feed error: {e}")
        return []


def _entry_to_article(entry, source: str, lang: str = "EN", extra: dict | None = None) -> dict:
    title = entry.get("title", "").strip()
    link = entry.get("link", "").strip()
    summary = entry.get("summary", entry.get("description", "")).strip()
    summary = re.sub(r"<[^>]+>", " ", summary)
    summary = re.sub(r"\s+", " ", summary).strip()

    pub_date = None
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            pub_date = datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
            break

    article = {
        "title": title,
        "url": link,
        "summary": summary[:800],
        "source": source,
        "lang": lang,
        "pub_date": pub_date,
    }
    if extra:
        article.update(extra)
    return article


def _is_recent(entry, hours: int = 48) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc) >= cutoff
    return True


def _is_korea_related(entry) -> bool:
    text = f"{entry.get('title', '')} {entry.get('summary', entry.get('description', ''))}"
    return bool(KOREA_KEYWORDS.search(text))


def _flag_journalist(article: dict) -> dict:
    text = f"{article['title']} {article['summary']}".lower()
    for name in PRESTIGE_JOURNALISTS:
        if name.lower() in text:
            article["flagged_journalist"] = name
            break
    return article


def _dedup(articles: list) -> list:
    seen = set()
    out = []
    for a in articles:
        if a["url"] and a["url"] not in seen:
            seen.add(a["url"])
            out.append(a)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# PARALLEL FEED FETCHER
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_feeds_parallel(feed_dict: dict, is_tiered: bool = False) -> dict:
    """Fetch all feeds in parallel. Returns {source: (entries, extra_info)}."""
    results = {}

    def _fetch_one(source, url_or_tuple):
        if is_tiered:
            url, tier_val = url_or_tuple
        else:
            url = url_or_tuple
            tier_val = None
        entries = _parse_feed(url)
        return source, entries, tier_val

    items = list(feed_dict.items())
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_fetch_one, src, val): src for src, val in items}
        for future in as_completed(futures):
            try:
                source, entries, tier_val = future.result()
                results[source] = (entries, tier_val)
            except Exception as e:
                print(f"    ⚠  Thread error: {e}")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# TIER COLLECTORS
# ─────────────────────────────────────────────────────────────────────────────

def _collect_tier1() -> list:
    articles = []
    results = _fetch_feeds_parallel(TIER1_FEEDS)
    for source, (entries, _) in results.items():
        # Korean-language feeds get lang="KO"
        lang = "KO" if source in ("조선일보", "한겨레", "동아일보", "MBN") else "EN"
        for entry in entries:
            if not _is_recent(entry, hours=24):
                continue
            if not _is_korea_related(entry):
                continue
            article = _entry_to_article(entry, source, lang=lang)
            article = _flag_journalist(article)
            articles.append(article)
    return _dedup(articles)


def _collect_tier2() -> list:
    articles = []
    results = _fetch_feeds_parallel(TIER2_FEEDS, is_tiered=True)
    for source, (entries, prestige) in results.items():
        for entry in entries:
            if not _is_recent(entry, hours=36):
                continue
            if not _is_korea_related(entry):
                continue
            article = _entry_to_article(entry, source, extra={"prestige": prestige})
            articles.append(article)
    return _dedup(articles)


def _collect_tier3() -> list:
    articles = []
    results = _fetch_feeds_parallel(TIER3_FEEDS, is_tiered=True)
    for source, (entries, tier) in results.items():
        for entry in entries:
            if not _is_recent(entry, hours=72):
                continue
            if not _is_korea_related(entry):
                continue
            # Extra filter: must mention academic-like terms or the journal name
            text = f"{entry.get('title', '')} {entry.get('summary', entry.get('description', ''))}".lower()
            academic_signals = ("journal", "paper", "study", "research", "analysis",
                                "findings", "abstract", "doi", "vol.", "issue",
                                source.lower())
            if not any(s in text for s in academic_signals):
                continue
            article = _entry_to_article(entry, source, extra={"journal_tier": tier})
            articles.append(article)
    return _dedup(articles)


def _collect_tier4() -> list:
    articles = []
    results = _fetch_feeds_parallel(TIER4_FEEDS)
    for source, (entries, _) in results.items():
        for entry in entries:
            if not _is_recent(entry, hours=24):
                continue
            article = _entry_to_article(entry, source, lang="KO")
            articles.append(article)
    return _dedup(articles)


# ─────────────────────────────────────────────────────────────────────────────
# MARKET DATA
# ─────────────────────────────────────────────────────────────────────────────

def _collect_markets() -> dict | None:
    """Fetch KOSPI, Brent Crude, USD/KRW from Yahoo Finance API."""
    symbols = {
        "kospi": "^KS11",
        "brent": "BZ=F",
        "usd_krw": "KRW=X",
    }
    result = {}
    for key, symbol in symbols.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=2d&interval=1d"
            resp = requests.get(url, timeout=10, headers={
                "User-Agent": "Mozilla/5.0"
            })
            resp.raise_for_status()
            data = resp.json()
            meta = data["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice", 0)
            prev_close = meta.get("chartPreviousClose", meta.get("previousClose", price))
            change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0
            # Format value
            if key == "usd_krw":
                value = f"{price:,.2f}"
            elif key == "kospi":
                value = f"{price:,.2f}"
            else:
                value = f"{price:.2f}"
            result[key] = {"value": value, "change_pct": round(change_pct, 2)}
        except Exception as e:
            print(f"    ⚠  Market data error ({key}): {e}")
            result[key] = {"value": "—", "change_pct": 0}
    return result if any(r["value"] != "—" for r in result.values()) else None


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def collect() -> dict:
    """Run all tier collectors + market data and return combined payload."""
    print("\n📡  Collecting Korea news from 100+ sources (parallel)...")

    print("  ── Tier 1: News articles")
    tier1 = _collect_tier1()
    print(f"     {len(tier1)} articles")

    print("  ── Tier 2: Op-eds & commentary")
    tier2 = _collect_tier2()
    print(f"     {len(tier2)} pieces")

    print("  ── Tier 3: Academic journals")
    tier3 = _collect_tier3()
    print(f"     {len(tier3)} papers")

    print("  ── Tier 4: KCNA / Rodong Sinmun")
    tier4 = _collect_tier4()
    print(f"     {len(tier4)} items")

    print("  ── Market data")
    markets = _collect_markets()
    print(f"     {'OK' if markets else 'unavailable'}")

    total = len(tier1) + len(tier2) + len(tier3) + len(tier4)
    print(f"\n  📊  Total collected: {total} items")

    return {
        "tier1": tier1,
        "tier2": tier2,
        "tier3": tier3,
        "tier4": tier4,
        "market_indicators": markets,
    }


if __name__ == "__main__":
    from pathlib import Path
    payload = collect()
    Path("collected.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print("  → Written to collected.json")
