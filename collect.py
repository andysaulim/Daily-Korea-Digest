"""
Korea Intelligence Digest — Collector
Beyond Parallel × CSIS Korea Chair
Scrapes RSS feeds and returns articles across four tiers:
  tier1: News articles (last 24h)
  tier2: Op-eds & prestige commentary
  tier3: Academic journals
  tier4: KCNA / Rodong Sinmun
"""
import feedparser
import requests
from datetime import datetime, timezone, timedelta
from time import mktime
import re

# ─────────────────────────────────────────────────────────────────────────────
# FEED CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

TIER1_FEEDS = {
    # Major English-language Korea coverage
    "Korea Herald":       "http://www.koreaherald.com/common/rss_xml.php?ct=102",
    "Korea Times":        "https://www.koreatimes.co.kr/www/rss/nation.xml",
    "Yonhap English":     "https://en.yna.co.kr/RSS/news.xml",
    "NK News":            "https://www.nknews.org/feed/",
    "Reuters Korea":      "https://news.google.com/rss/search?q=Korea+site:reuters.com&hl=en-US&gl=US&ceid=US:en",
    "AP Korea":           "https://news.google.com/rss/search?q=Korea+site:apnews.com&hl=en-US&gl=US&ceid=US:en",
    "WSJ Korea":          "https://news.google.com/rss/search?q=Korea+site:wsj.com&hl=en-US&gl=US&ceid=US:en",
    "NYT Korea":          "https://news.google.com/rss/search?q=Korea+site:nytimes.com&hl=en-US&gl=US&ceid=US:en",
    "WaPo Korea":         "https://news.google.com/rss/search?q=Korea+site:washingtonpost.com&hl=en-US&gl=US&ceid=US:en",
    "FT Korea":           "https://news.google.com/rss/search?q=Korea+site:ft.com&hl=en-US&gl=US&ceid=US:en",
    "Nikkei Korea":       "https://news.google.com/rss/search?q=Korea+site:asia.nikkei.com&hl=en-US&gl=US&ceid=US:en",
    "SCMP Korea":         "https://news.google.com/rss/search?q=Korea+site:scmp.com&hl=en-US&gl=US&ceid=US:en",
    "Chosun English":     "https://www.chosun.com/nsearch/?query=korea&rss=y",
    "JoongAng Daily":     "https://koreajoongangdaily.joins.com/section/rss",
    # ROK/US Government
    "White House":        "https://news.google.com/rss/search?q=Korea+site:whitehouse.gov&hl=en-US&gl=US&ceid=US:en",
    "State Dept":         "https://news.google.com/rss/search?q=Korea+site:state.gov&hl=en-US&gl=US&ceid=US:en",
    "Pentagon":           "https://news.google.com/rss/search?q=Korea+site:defense.gov&hl=en-US&gl=US&ceid=US:en",
    "Stars and Stripes":  "https://news.google.com/rss/search?q=Korea+site:stripes.com&hl=en-US&gl=US&ceid=US:en",
    # Reaction layer
    "Global Times Korea": "https://news.google.com/rss/search?q=Korea+site:globaltimes.cn&hl=en-US&gl=US&ceid=US:en",
    "Xinhua Korea":       "https://news.google.com/rss/search?q=Korea+site:xinhuanet.com&hl=en-US&gl=US&ceid=US:en",
    "TASS Korea":         "https://news.google.com/rss/search?q=Korea+site:tass.com&hl=en-US&gl=US&ceid=US:en",
}

TIER2_FEEDS = {
    # Think tanks & op-ed sources
    "CSIS":              ("https://www.csis.org/analysis/feed", "A"),
    "Brookings":         ("https://www.brookings.edu/feed/", "A"),
    "Carnegie":          ("https://carnegieendowment.org/rss/solr?query=korea", "A"),
    "RAND":              ("https://www.rand.org/topics/north-korea.xml", "A"),
    "CFR":               ("https://www.cfr.org/rss.xml", "A"),
    "38 North":          ("https://www.38north.org/feed/", "A"),
    "Stimson":           ("https://www.stimson.org/feed/", "B"),
    "IISS":              ("https://www.iiss.org/rss", "B"),
    "ASAN Institute":    ("https://en.asaninst.org/contents/feed/", "B"),
    "EAI":               ("https://www.eai.or.kr/new/en/etc/rss.asp", "B"),
    "Sejong Institute":  ("https://news.google.com/rss/search?q=Korea+site:sejong.org&hl=en-US&gl=US&ceid=US:en", "B"),
    "SIPRI":             ("https://www.sipri.org/rss.xml", "B"),
    "War on the Rocks":  ("https://warontherocks.com/feed/", "B"),
    "Foreign Affairs":   ("https://www.foreignaffairs.com/rss.xml", "A"),
    "Foreign Policy":    ("https://foreignpolicy.com/feed/", "B"),
    "Diplomat":          ("https://thediplomat.com/feed/", "C"),
    "NKPro":             ("https://www.nknews.org/pro/feed/", "A"),
}

TIER3_FEEDS = {
    # Academic journals
    "International Security":    ("https://news.google.com/rss/search?q=%22International+Security%22+Korea&hl=en-US&gl=US&ceid=US:en", "A+"),
    "Journal of Conflict Resolution": ("https://news.google.com/rss/search?q=%22Journal+of+Conflict+Resolution%22+Korea&hl=en-US&gl=US&ceid=US:en", "A"),
    "Asian Survey":              ("https://news.google.com/rss/search?q=%22Asian+Survey%22+Korea&hl=en-US&gl=US&ceid=US:en", "A"),
    "Pacific Review":            ("https://news.google.com/rss/search?q=%22Pacific+Review%22+Korea&hl=en-US&gl=US&ceid=US:en", "A"),
    "Korean Journal of Defense Analysis": ("https://news.google.com/rss/search?q=%22Korean+Journal+of+Defense+Analysis%22&hl=en-US&gl=US&ceid=US:en", "B"),
    "North Korean Review":       ("https://news.google.com/rss/search?q=%22North+Korean+Review%22&hl=en-US&gl=US&ceid=US:en", "B"),
    "KINU":                      ("https://news.google.com/rss/search?q=Korea+site:kinu.or.kr&hl=en-US&gl=US&ceid=US:en", "B"),
}

TIER4_FEEDS = {
    # DPRK official media
    "KCNA Watch":        "https://kcnawatch.org/newstream/feed/",
    "KCNA":              "https://news.google.com/rss/search?q=site:kcna.kp&hl=en-US&gl=US&ceid=US:en",
    "Rodong Sinmun":     "https://news.google.com/rss/search?q=site:rodong.rep.kp&hl=en-US&gl=US&ceid=US:en",
    "KCNA (Yonhap)":    "https://news.google.com/rss/search?q=KCNA+Yonhap&hl=en-US&gl=US&ceid=US:en",
}

# Korea-related keywords for filtering non-Korea-specific feeds
KOREA_KEYWORDS = re.compile(
    r"korea|dprk|pyongyang|seoul|rok\b|kim jong|yoon suk|korean peninsula"
    r"|denucleariz|kaesong|yongbyon|hwasong|punggye|38th parallel"
    r"|usfk|combined forces|kim yo jong|choe son hui"
    r"|north korea|south korea|inter-korean",
    re.IGNORECASE,
)

PRESTIGE_JOURNALISTS = {
    "Timothy Martin", "Dasl Yoon", "Choe Sang-Hun", "Michelle Ye Hee Lee",
    "Christian Davies", "Hyonhee Shin", "Josh Smith", "Joyce Lee",
    "Ankit Panda", "Jenny Town", "Andrei Lankov", "Rachel Minyoung Lee",
}

REQUEST_TIMEOUT = 15
HEADERS = {"User-Agent": "KoreaDigestBot/1.0 (Beyond Parallel / CSIS)"}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _parse_feed(url: str) -> list:
    """Fetch and parse a single RSS feed, returning entries."""
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
        return feedparser.parse(resp.content).entries
    except Exception as e:
        print(f"    ⚠  Feed error: {e}")
        return []


def _entry_to_article(entry, source: str, lang: str = "EN", extra: dict | None = None) -> dict:
    """Convert a feedparser entry to a normalized article dict."""
    title = entry.get("title", "").strip()
    link = entry.get("link", "").strip()
    summary = entry.get("summary", entry.get("description", "")).strip()
    # Strip HTML tags from summary
    summary = re.sub(r"<[^>]+>", " ", summary)
    summary = re.sub(r"\s+", " ", summary).strip()

    pub_date = None
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
    elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
        pub_date = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc).isoformat()

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
    """Check if a feed entry was published within the last N hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            entry_dt = datetime(*parsed[:6], tzinfo=timezone.utc)
            return entry_dt >= cutoff
    # If no date, include it (better to over-include)
    return True


def _is_korea_related(entry) -> bool:
    """Check if an entry is Korea-related by title/summary."""
    text = f"{entry.get('title', '')} {entry.get('summary', entry.get('description', ''))}"
    return bool(KOREA_KEYWORDS.search(text))


def _flag_journalist(article: dict) -> dict:
    """Flag articles by prestige journalists."""
    text = f"{article['title']} {article['summary']}"
    for name in PRESTIGE_JOURNALISTS:
        if name.lower() in text.lower():
            article["flagged_journalist"] = name
            break
    return article


# ─────────────────────────────────────────────────────────────────────────────
# TIER COLLECTORS
# ─────────────────────────────────────────────────────────────────────────────

def _collect_tier1() -> list:
    """Collect Tier 1: News articles."""
    articles = []
    for source, url in TIER1_FEEDS.items():
        entries = _parse_feed(url)
        for entry in entries:
            if not _is_recent(entry, hours=36):
                continue
            if not _is_korea_related(entry):
                continue
            article = _entry_to_article(entry, source)
            article = _flag_journalist(article)
            articles.append(article)
    # Deduplicate by URL
    seen = set()
    deduped = []
    for a in articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            deduped.append(a)
    return deduped


def _collect_tier2() -> list:
    """Collect Tier 2: Op-eds & prestige commentary."""
    articles = []
    for source, (url, prestige) in TIER2_FEEDS.items():
        entries = _parse_feed(url)
        for entry in entries:
            if not _is_recent(entry, hours=72):
                continue
            if not _is_korea_related(entry):
                continue
            article = _entry_to_article(entry, source, extra={"prestige": prestige})
            articles.append(article)
    seen = set()
    deduped = []
    for a in articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            deduped.append(a)
    return deduped


def _collect_tier3() -> list:
    """Collect Tier 3: Academic journals."""
    articles = []
    for source, (url, tier) in TIER3_FEEDS.items():
        entries = _parse_feed(url)
        for entry in entries:
            if not _is_korea_related(entry):
                continue
            article = _entry_to_article(entry, source, extra={"journal_tier": tier})
            articles.append(article)
    seen = set()
    deduped = []
    for a in articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            deduped.append(a)
    return deduped


def _collect_tier4() -> list:
    """Collect Tier 4: KCNA / Rodong Sinmun."""
    articles = []
    for source, url in TIER4_FEEDS.items():
        entries = _parse_feed(url)
        for entry in entries:
            if not _is_recent(entry, hours=48):
                continue
            article = _entry_to_article(entry, source, lang="KO")
            articles.append(article)
    seen = set()
    deduped = []
    for a in articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            deduped.append(a)
    return deduped


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def collect() -> dict:
    """Run all four tier collectors and return combined payload."""
    print("\n📡  Collecting Korea news from 100+ sources...")

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

    total = len(tier1) + len(tier2) + len(tier3) + len(tier4)
    print(f"\n  📊  Total collected: {total} items")

    return {
        "tier1": tier1,
        "tier2": tier2,
        "tier3": tier3,
        "tier4": tier4,
    }


if __name__ == "__main__":
    import json
    from pathlib import Path
    payload = collect()
    Path("collected.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print("  → Written to collected.json")
