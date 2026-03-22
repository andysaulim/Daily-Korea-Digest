"""
Korea Daily Brief — Collector
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
    # ── Korean broadcast & cable news ────────────────────────────────────
    "JTBC":               _gnews("site:news.jtbc.co.kr"),
    "KBS":                _gnews("site:news.kbs.co.kr"),
    "MBC":                _gnews("site:imnews.imbc.com"),
    "SBS":                _gnews("site:news.sbs.co.kr"),
    "YTN":                _gnews("site:ytn.co.kr"),
    "Channel A":          _gnews("site:ichannela.com"),
    # ── Korean business dailies ──────────────────────────────────────────
    "매일경제":            _gnews("site:mk.co.kr"),
    "한국경제":            _gnews("site:hankyung.com"),
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
    "Kyodo Korea":        _gnews("Korea+site:english.kyodonews.net"),
    "Mainichi Korea":     _gnews("Korea+site:mainichi.jp/english"),
    "Asahi Korea":        _gnews("Korea+site:asahi.com/ajw"),
    "CNA Korea":          _gnews("Korea+site:channelnewsasia.com"),
    # ── ROK/US Government ─────────────────────────────────────────────────
    "White House":        _gnews("Korea+site:whitehouse.gov"),
    "State Dept":         _gnews("Korea+site:state.gov"),
    "Pentagon":           _gnews("Korea+site:defense.gov"),
    "Stars and Stripes":  _gnews("Korea+site:stripes.com"),
    # ── ROK/Japan Government ─────────────────────────────────────────────
    "USFK":               _gnews("site:usfk.mil"),
    "ROK MOFA":           _gnews("site:mofa.go.kr"),
    "ROK MOTIE":          _gnews("Korea+site:motie.go.kr"),
    "Japan MOFA":         _gnews("Korea+site:mofa.go.jp"),
    # ── US Economic agencies ────────────────────────────────────────────
    "Dept of Commerce":   _gnews("Korea+site:commerce.gov"),
    "Dept of Treasury":   _gnews("Korea+site:treasury.gov"),
    "OFAC":               _gnews("Korea+OR+DPRK+site:ofac.treasury.gov"),
    "BIS":                _gnews("Korea+OR+DPRK+site:bis.doc.gov"),
    # ── US Congress ─────────────────────────────────────────────────────
    "Senate Foreign Relations": _gnews("Korea+site:foreign.senate.gov"),
    "Senate Armed Services":    _gnews("Korea+site:armed-services.senate.gov"),
    "House Foreign Affairs":    _gnews("Korea+site:foreignaffairs.house.gov"),
    # ── US Military ─────────────────────────────────────────────────────
    "INDOPACOM":          _gnews("Korea+site:pacom.mil"),
    # ── International organizations ─────────────────────────────────────
    "IAEA":               _gnews("Korea+OR+DPRK+site:iaea.org"),
    "UN Security Council": _gnews("Korea+OR+DPRK+site:un.org/securitycouncil"),
    # ── Cyber/enforcement ───────────────────────────────────────────────
    "CISA":               _gnews("Korea+OR+DPRK+OR+Lazarus+site:cisa.gov"),
    # ── Reaction layer (China/Russia) ─────────────────────────────────────
    "Global Times Korea": _gnews("Korea+site:globaltimes.cn"),
    "Xinhua Korea":       _gnews("Korea+site:xinhuanet.com"),
    "TASS Korea":         _gnews("Korea+site:tass.com"),
    "Caixin Korea":       _gnews("Korea+site:caixinglobal.com"),
    "China Daily Korea":  _gnews("Korea+site:chinadaily.com.cn"),
    "People's Daily Korea": _gnews("Korea+site:en.people.cn"),
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
    # ── Additional think tanks ───────────────────────────────────────────
    "AEI":               (_gnews("Korea+site:aei.org"), "A"),
    "Hudson Institute":  (_gnews("Korea+site:hudson.org"), "B"),
    "Heritage":          (_gnews("Korea+site:heritage.org"), "B"),
    "Atlantic Council":  (_gnews("Korea+site:atlanticcouncil.org"), "B"),
    "KEIA":              (_gnews("Korea+site:keia.org"), "A"),
    "NBR":               (_gnews("Korea+site:nbr.org"), "B"),
    "PIIE":              (_gnews("Korea+site:piie.com"), "B"),
    "USIP":              (_gnews("Korea+site:usip.org"), "B"),
}

# Tier 3: Use Google Scholar RSS and site-specific searches to reduce noise
TIER3_FEEDS = {
    # A+ tier — top IR/security journals
    "Int'l Security":         (_gnews("%22International+Security%22+%22Korea%22+OR+%22DPRK%22+OR+%22Pyongyang%22"), "A+"),
    "Int'l Organization":     (_gnews("%22International+Organization%22+%22Korea%22+OR+%22DPRK%22"), "A+"),
    "World Politics":         (_gnews("%22World+Politics%22+%22Korea%22+OR+%22DPRK%22+OR+%22Korean+Peninsula%22"), "A+"),
    "American Pol. Sci. Review": (_gnews("%22American+Political+Science+Review%22+%22Korea%22+OR+%22DPRK%22"), "A+"),
    # A tier — strong IR/area studies journals
    "J. Conflict Resolution": (_gnews("%22Journal+of+Conflict+Resolution%22+%22Korea%22+OR+%22DPRK%22"), "A"),
    "J. Peace Research":      (_gnews("%22Journal+of+Peace+Research%22+%22Korea%22+OR+%22DPRK%22"), "A"),
    "Security Studies":       (_gnews("%22Security+Studies%22+%22Korea%22+OR+%22DPRK%22+OR+%22North+Korea%22"), "A"),
    "Int'l Studies Quarterly": (_gnews("%22International+Studies+Quarterly%22+%22Korea%22+OR+%22DPRK%22"), "A"),
    "J. Strategic Studies":   (_gnews("%22Journal+of+Strategic+Studies%22+%22Korea%22+OR+%22DPRK%22"), "A"),
    "Asian Survey":           (_gnews("%22Asian+Survey%22+%22Korea%22+OR+%22DPRK%22+OR+%22Korean+Peninsula%22"), "A"),
    "Pacific Review":         (_gnews("%22Pacific+Review%22+%22Korea%22+OR+%22DPRK%22"), "A"),
    "Foreign Affairs":        (_gnews("%22Foreign+Affairs%22+%22Korea%22+OR+%22DPRK%22+OR+%22North+Korea%22"), "A"),
    "Survival":               (_gnews("%22Survival%22+IISS+%22Korea%22+OR+%22DPRK%22"), "A"),
    # B tier — specialized Korea/Asia journals
    "Korean J. Def. Analysis": (_gnews("%22Korean+Journal+of+Defense+Analysis%22"), "B"),
    "North Korean Review":    (_gnews("%22North+Korean+Review%22"), "B"),
    "Asian Security":         (_gnews("%22Asian+Security%22+%22Korea%22+OR+%22DPRK%22"), "B"),
    "Pacific Affairs":        (_gnews("%22Pacific+Affairs%22+%22Korea%22+OR+%22DPRK%22"), "B"),
    "Korean Studies":         (_gnews("%22Korean+Studies%22+journal+%22North+Korea%22+OR+%22DPRK%22+OR+%22Korean+Peninsula%22"), "B"),
    "Nonproliferation Rev.":  (_gnews("%22Nonproliferation+Review%22+%22Korea%22+OR+%22DPRK%22"), "B"),
    "Washington Quarterly":   (_gnews("%22Washington+Quarterly%22+%22Korea%22+OR+%22DPRK%22"), "B"),
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
    "Hyonhee Shin", "Josh Smith", "Joyce Lee",
    "Ankit Panda", "Jeongmin Kim",
    "Jean Lee", "Simon Mundy", "Edward White",
    "Dagyum Ji", "Ifang Bremer", "Chad O'Carroll",
    # FT Seoul
    "Jean Mackenzie", "Daniel Tudor", "Song Jung-a",
    # Additional journalists
    "Victoria Kim", "Jeong-ho Lee", "Kim Tong-hyung",
    "Sotaro Suzuki", "Takashi Umekawa",
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
        lang = "KO" if source in ("조선일보", "한겨레", "동아일보", "MBN",
                                    "JTBC", "KBS", "MBC", "SBS", "YTN", "Channel A",
                                    "매일경제", "한국경제") else "EN"
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

    # ROK economic indicators (BOK rate, monthly exports, GDP estimate)
    # Sourced from BOK ECOS API / MOTIE / KOSTAT — fallback to static latest known
    result["bok_rate"] = _fetch_bok_rate()
    result["monthly_exports"] = _fetch_monthly_exports()
    result["gdp_estimate"] = _fetch_gdp_estimate()

    return result if any(result.get(k, {}).get("value", "—") != "—"
                         for k in ("kospi", "brent", "usd_krw")) else None


def _fetch_bok_rate() -> dict:
    """Fetch BOK base rate. Falls back to last known value."""
    # BOK ECOS open API — base rate series
    try:
        url = "https://ecos.bok.or.kr/api/StatisticSearch/json/en/1/1/722Y001/M/202501/202612/0101000/"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.ok:
            rows = resp.json().get("StatisticSearch", {}).get("row", [])
            if rows:
                val = rows[-1].get("DATA_VALUE", "")
                return {"value": f"{float(val):.2f}%", "last_change": ""}
    except Exception:
        pass
    # Fallback: last known BOK rate (updated manually if API unavailable)
    fallback_date = datetime.now(timezone.utc).strftime("%b %Y")
    return {"value": "2.75%", "last_change": fallback_date}


def _fetch_monthly_exports() -> dict:
    """Fetch latest monthly export figure from multiple sources."""
    # Source 1: BOK ECOS — trade balance series (monthly exports in $M)
    # Requires API key registered at ecos.bok.or.kr — may return empty without one
    try:
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=120)).strftime("%Y%m")
        end = now.strftime("%Y%m")
        url = f"https://ecos.bok.or.kr/api/StatisticSearch/json/en/1/5/403Y014/M/{start}/{end}/000000/"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.ok:
            rows = resp.json().get("StatisticSearch", {}).get("row", [])
            if len(rows) >= 2:
                latest = rows[-1]
                prev = rows[-2]
                val = float(latest.get("DATA_VALUE", 0))
                prev_val = float(prev.get("DATA_VALUE", 0))
                change = ((val - prev_val) / prev_val * 100) if prev_val else 0
                val_b = val / 1000
                return {"value": f"${val_b:.1f}B", "change_pct": round(change, 1)}
            elif rows:
                val = float(rows[-1].get("DATA_VALUE", 0))
                val_b = val / 1000
                return {"value": f"${val_b:.1f}B", "change_pct": 0}
    except Exception as e:
        print(f"    ⚠  BOK exports API error: {e}")

    # Source 2: MOTIE / Korea Customs Service export headlines via Google News
    search_queries = [
        "South+Korea+monthly+exports+billion+MOTIE",
        "South+Korea+exports+billion+customs",
        "한국+수출+억달러+산업통상자원부",
    ]
    for query in search_queries:
        try:
            url = _gnews(query)
            entries = _parse_feed(url)
            for entry in entries[:8]:
                text = f"{entry.get('title', '')} {entry.get('summary', entry.get('description', ''))}"
                # Match "$58.4 billion", "$58.4B", "58.4 billion dollars"
                match = re.search(
                    r'(?:\$(\d+(?:\.\d+)?)\s*(?:billion|B)\b|(\d+(?:\.\d+)?)\s*billion\s*(?:dollars|USD))',
                    text, re.IGNORECASE
                )
                if match:
                    val = float(match.group(1) or match.group(2))
                    if 20 < val < 100:  # sanity: ROK monthly exports are $50-70B range
                        return {"value": f"${val:.1f}B", "change_pct": 0}
                # Korean-language pattern: "XXX억달러" or "XXX억 달러"
                match_kr = re.search(r'(\d+(?:\.\d+)?)\s*억\s*달러', text)
                if match_kr:
                    val_100m = float(match_kr.group(1))
                    val_b = val_100m / 10  # 억 = 100M, so /10 = billions
                    if 20 < val_b < 100:
                        return {"value": f"${val_b:.1f}B", "change_pct": 0}
        except Exception:
            continue

    # Source 3: Trade balance from Yahoo Finance (South Korea Trade Balance)
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/KRW=X?range=1mo&interval=1d"
        # This doesn't give exports directly, so skip if above failed
    except Exception:
        pass

    return {"value": "—", "change_pct": 0}


def _fetch_gdp_estimate() -> dict:
    """Fetch latest GDP growth estimate from BOK."""
    # Try broader date range to catch latest available quarter
    try:
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=730)).strftime("%Y") + "Q1"
        end = now.strftime("%Y") + "Q4"
        url = f"https://ecos.bok.or.kr/api/StatisticSearch/json/en/1/20/200Y002/Q/{start}/{end}/10111/"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.ok:
            rows = resp.json().get("StatisticSearch", {}).get("row", [])
            if rows:
                latest = rows[-1]
                val = latest.get("DATA_VALUE", "")
                period = latest.get("TIME", "")
                # Format period: "2026Q1" -> "Q1 2026"
                if "Q" in str(period):
                    parts = str(period).split("Q")
                    period = f"Q{parts[1]} {parts[0]}"
                return {"value": f"{float(val):.1f}%", "period": period}
    except Exception as e:
        print(f"    ⚠  BOK GDP API error: {e}")

    # Fallback: scrape latest BOK GDP forecast from news
    try:
        url = _gnews("Bank+of+Korea+GDP+growth+forecast+2026")
        entries = _parse_feed(url)
        for entry in entries[:5]:
            text = f"{entry.get('title', '')} {entry.get('summary', entry.get('description', ''))}"
            match = re.search(r'(\d+\.\d+)\s*(?:percent|%|pct)', text, re.IGNORECASE)
            if match:
                val = float(match.group(1))
                if 0 < val < 10:  # sanity check for GDP growth rate
                    return {"value": f"{val:.1f}%", "period": "BOK forecast"}
    except Exception:
        pass

    return {"value": "—", "period": ""}


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC SENTIMENT — Gallup Korea, Realmeter
# ─────────────────────────────────────────────────────────────────────────────

def _collect_sentiment() -> dict:
    """Scrape latest Korean polling data from news headlines.

    Returns structured sentiment data for presidential approval,
    party support ratings (ruling, opposition, independents), and
    weekly spotlight topic. Claude will merge any new poll data
    from articles with these baseline numbers.
    """
    sentiment = {
        "presidential_approval": None,
        "party_ruling": None,
        "party_opposition": None,
        "party_independent": None,
        "gallup_spotlight": None,
        "discourse_flag": None,
    }

    # ── Presidential Approval (Gallup Korea weekly, Realmeter daily) ────
    approval_queries = [
        "Gallup+Korea+presidential+approval+rating",
        "한국갤럽+대통령+지지율",
        "리얼미터+대통령+지지율",
        "Realmeter+presidential+approval+Korea",
    ]
    for query in approval_queries:
        try:
            entries = _parse_feed(_gnews(query))
            for entry in entries[:5]:
                text = f"{entry.get('title', '')} {entry.get('summary', entry.get('description', ''))}"
                # English: "approval rating of 23%", "23% approval"
                match = re.search(
                    r'(?:approval|support|지지율)[^\d]{0,30}(\d{1,2})(?:\.\d)?%|'
                    r'(\d{1,2})(?:\.\d)?%\s*(?:approval|support|지지율)',
                    text, re.IGNORECASE
                )
                if match:
                    val = match.group(1) or match.group(2)
                    # Determine source
                    source = "Gallup Korea" if "gallup" in text.lower() or "갤럽" in text else (
                        "Realmeter" if "realmeter" in text.lower() or "리얼미터" in text else "Poll"
                    )
                    # Extract date from entry
                    pub_date = None
                    for attr in ("published_parsed", "updated_parsed"):
                        parsed = getattr(entry, attr, None)
                        if parsed:
                            pub_date = datetime(*parsed[:6], tzinfo=timezone.utc).strftime("%b %d, %Y")
                            break
                    sentiment["presidential_approval"] = {
                        "value": f"{val}%",
                        "trend": None,  # Claude will infer from context
                        "source": source,
                        "last_updated": pub_date or "recent",
                    }
                    break
            if sentiment["presidential_approval"]:
                break
        except Exception:
            continue

    # ── Party support ratings (Gallup Korea weekly, Realmeter daily) ────
    party_queries = [
        "한국갤럽+정당+지지율",
        "Gallup+Korea+party+approval+rating",
        "리얼미터+정당+지지율",
        "한국갤럽+더불어민주당+국민의힘+지지율",
    ]
    for query in party_queries:
        try:
            entries = _parse_feed(_gnews(query))
            for entry in entries[:5]:
                text = f"{entry.get('title', '')} {entry.get('summary', entry.get('description', ''))}"
                # Match ruling party (Democratic Party / 민주당)
                ruling_match = re.search(
                    r'(?:민주당|Democratic\s*Party)[^\d]{0,30}(\d{1,2})(?:\.\d)?%|'
                    r'(\d{1,2})(?:\.\d)?%\s*(?:민주당|Democratic\s*Party)',
                    text, re.IGNORECASE
                )
                # Match opposition (People Power Party / 국민의힘)
                opp_match = re.search(
                    r'(?:국민의힘|People\s*Power\s*Party)[^\d]{0,30}(\d{1,2})(?:\.\d)?%|'
                    r'(\d{1,2})(?:\.\d)?%\s*(?:국민의힘|People\s*Power\s*Party)',
                    text, re.IGNORECASE
                )
                # Match independents (무당층 / no party preference)
                ind_match = re.search(
                    r'(?:무당층|무당파|no\s*party|independent)[^\d]{0,30}(\d{1,2})(?:\.\d)?%|'
                    r'(\d{1,2})(?:\.\d)?%\s*(?:무당층|무당파|no\s*party|independent)',
                    text, re.IGNORECASE
                )
                if ruling_match or opp_match:
                    source = "Gallup Korea" if "gallup" in text.lower() or "갤럽" in text else (
                        "Realmeter" if "realmeter" in text.lower() or "리얼미터" in text else "Poll"
                    )
                    pub_date = None
                    for attr in ("published_parsed", "updated_parsed"):
                        parsed = getattr(entry, attr, None)
                        if parsed:
                            pub_date = datetime(*parsed[:6], tzinfo=timezone.utc).strftime("%b %d, %Y")
                            break
                    if ruling_match:
                        val = ruling_match.group(1) or ruling_match.group(2)
                        sentiment["party_ruling"] = {
                            "value": f"{val}%",
                            "party": "Democratic Party",
                            "party_kr": "더불어민주당",
                            "source": source,
                            "last_updated": pub_date or "recent",
                        }
                    if opp_match:
                        val = opp_match.group(1) or opp_match.group(2)
                        sentiment["party_opposition"] = {
                            "value": f"{val}%",
                            "party": "People Power Party",
                            "party_kr": "국민의힘",
                            "source": source,
                            "last_updated": pub_date or "recent",
                        }
                    if ind_match:
                        val = ind_match.group(1) or ind_match.group(2)
                        sentiment["party_independent"] = {
                            "value": f"{val}%",
                            "source": source,
                            "last_updated": pub_date or "recent",
                        }
                    break
            if sentiment["party_ruling"] and sentiment["party_opposition"]:
                break
        except Exception:
            continue

    # ── Gallup Korea Spotlight (weekly special-topic finding) ───────────
    # Each weekly poll includes a rotating social/policy topic beyond the
    # standard presidential + party numbers.  Grab the headline finding.
    spotlight_queries = [
        "한국갤럽+여론조사+이번주",
        "한국갤럽+데일리+오피니언",
        "Gallup+Korea+weekly+poll+survey+2026",
        "한국갤럽+조사+결과",
    ]
    for query in spotlight_queries:
        try:
            entries = _parse_feed(_gnews(query))
            for entry in entries[:5]:
                text = f"{entry.get('title', '')} {entry.get('summary', entry.get('description', ''))}"
                # Skip entries that are only about presidential/party ratings
                if re.search(r'(대통령|지지율|presidential|party\s*approval)', text, re.IGNORECASE) and \
                   not re.search(r'(찬반|조사|survey|설문|여론|opinion|응답|percent)', text, re.IGNORECASE):
                    continue
                # Look for poll-result-style content (percentages + survey language)
                if re.search(r'갤럽|gallup', text, re.IGNORECASE) and \
                   re.search(r'\d{1,2}%|찬성|반대|응답|survey|poll', text, re.IGNORECASE):
                    title = entry.get("title", "").strip()
                    pub_date = None
                    for attr in ("published_parsed", "updated_parsed"):
                        parsed = getattr(entry, attr, None)
                        if parsed:
                            pub_date = datetime(*parsed[:6], tzinfo=timezone.utc).strftime("%b %d, %Y")
                            break
                    sentiment["gallup_spotlight"] = {
                        "headline": title[:250],
                        "poll_date": pub_date or "recent",
                    }
                    break
            if sentiment.get("gallup_spotlight"):
                break
        except Exception:
            continue

    # ── Discourse flag (protests, viral hashtags) ───────────────────────
    discourse_queries = [
        "Korea+protest+rally+demonstration",
        "한국+시위+집회",
    ]
    for query in discourse_queries:
        try:
            entries = _parse_feed(_gnews(query))
            for entry in entries[:3]:
                if not _is_recent(entry, hours=24):
                    continue
                text = f"{entry.get('title', '')} {entry.get('summary', entry.get('description', ''))}"
                protest_signals = ("protest", "rally", "demonstration", "시위", "집회",
                                   "candlelight", "march on", "tens of thousands")
                if any(s in text.lower() for s in protest_signals):
                    title = entry.get("title", "").strip()
                    sentiment["discourse_flag"] = title[:200]
                    break
            if sentiment["discourse_flag"]:
                break
        except Exception:
            continue

    has_data = any(v for v in sentiment.values())
    return sentiment if has_data else {}


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

    print("  ── Public sentiment polls")
    sentiment = _collect_sentiment()
    found = sum(1 for v in sentiment.values() if v) if sentiment else 0
    print(f"     {found} metric(s) found" if found else "     no recent polls found")

    total = len(tier1) + len(tier2) + len(tier3) + len(tier4)
    print(f"\n  📊  Total collected: {total} items")

    return {
        "tier1": tier1,
        "tier2": tier2,
        "tier3": tier3,
        "tier4": tier4,
        "market_indicators": markets,
        "sentiment_baseline": sentiment,
    }


if __name__ == "__main__":
    from pathlib import Path
    payload = collect()
    Path("collected.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print("  → Written to collected.json")
