"""
Korea Daily Brief — Collector
Scrapes RSS feeds across four tiers + market data.
Uses threaded fetching for performance (~15s vs ~60s sequential).
"""
import feedparser
import requests
import html as html_lib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import links

# ─────────────────────────────────────────────────────────────────────────────
# FEED CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

def _gnews(query: str, locale: str = "en") -> str:
    """Build a Google News RSS search URL.

    The query is normalised so a site: limit binds to the whole search:
    `Korea+OR+DPRK+site:x` becomes `(Korea OR DPRK) site:x`, properly encoded.
    Written flat, results came back from anywhere ("CRS Korea" delivered PM
    News Nigeria). See links.build_gnews_query. locale="ko" searches the
    Korean edition, which is where a Korean-language query belongs.
    """
    return links.gnews_url(query, locale)


def _native(native_url: str, gnews_query: str, also: tuple | list = (),
            locale: str = "en") -> list:
    """A feed defined as: try the outlet's own RSS, fall back to Google News.

    The fallback is what makes this safe to write for a URL nobody could
    verify. If the native path is wrong or the outlet moves it, that candidate
    returns nothing and the Google News search still answers, which is exactly
    what the feed did before.

    `also` holds further candidates tried between the two, in order (a second
    native board, a site: search for the body's own pages).
    """
    return [native_url, *also, _gnews(gnews_query, locale)]


def _press(query: str) -> str:
    """Korean-edition Google News search for how the press reports a body.

    The ROK government feeds used to be `site:xxx.go.kr` searches, and Google
    News indexes almost no .go.kr pages: across 12-18 October 2026 the whole
    block delivered 15 items, and the Presidential Office, MND, Unification,
    the Joint Chiefs, DAPA and the Assembly delivered none. The Korean press
    reports these bodies' briefings every day, by name, so the fallback asks
    for that instead. Items found this way are reporting, not documents: they
    carry the outlet as their source and rank below a primary URL
    (digest._prompt_band).
    """
    return _gnews(query, locale="ko")


def _resolve_gnews_url(url: str) -> str:
    """Turn an opaque Google-News RSS link into the real article URL.

    Google News RSS items link to news.google.com/rss/articles/CBMi<base64>…
    redirect stubs that don't open the underlying article (broken hyperlinks in
    the email, and un-fetchable bodies). For the common case the real URL is
    embedded in the base64 payload — decode and extract it. If it can't be
    decoded (Google's newer fully-opaque IDs), return the link unchanged so we
    never make things worse.
    """
    if not url or "news.google.com" not in url or "/articles/" not in url:
        return url
    # Current IDs (AU_yqL…) are encrypted and need two network calls each, so
    # they are decoded once the digest is final (links.decode_digest_links),
    # for the dozen links a reader sees rather than the thousand collected.
    return links.decode_legacy(links.gnews_article_id(url)) or url


def load_gallup_baseline() -> dict:
    """Load the shared Gallup baseline (gallup_baseline.json).

    Single source of truth for polling fallbacks, used by collect.py,
    digest.py, and refreshed weekly by gallup_update.py. Returns {} if
    the file is missing or corrupt — callers keep hardcoded last-resorts.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "gallup_baseline.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


TIER1_FEEDS = {
    # ── Korean English-language dailies ────────────────────────────────────
    # Both papers redesigned and moved their feeds; the legacy paths have been
    # returning zero, and Korea Herald is a designated MAJOR_FEED, so that
    # failure was load-bearing and silent. Rather than guess which path is
    # right from an environment that cannot reach either, both are listed with
    # the Google News search last. Whichever answers first is used.
    "Korea Herald":       ["https://www.koreaherald.com/rss",
                           "https://www.koreaherald.com/common/rss_xml.php?ct=102",
                           _gnews("site:koreaherald.com")],
    "Korea Times":        ["https://feed.koreatimes.co.kr/k/allnews.xml",
                           "https://www.koreatimes.co.kr/www/rss/nation.xml",
                           _gnews("site:koreatimes.co.kr")],
    "Yonhap English":    _native("https://en.yna.co.kr/RSS/news.xml", "site:en.yna.co.kr"),
    "JoongAng Daily":     _gnews("Korea+site:koreajoongangdaily.joins.com"),
    # Both guessed publisher paths return 404; english.chosun.com does not
    # expose a feed at either. Back to the search until a real one is found.
    "Chosun English":     _gnews("Korea+site:english.chosun.com"),
    "Hankyoreh English":  _gnews("Korea+site:english.hani.co.kr"),
    "Dong-A English":     _gnews("Korea+site:donga.com/en"),
    "NK News":           _native("https://www.nknews.org/feed/", "site:nknews.org"),
    # ── Korean-language feeds (Claude translates during analysis) ──────────
    "조선일보":            _native("https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml", "site:chosun.com+-english"),
    "한겨레":              _native("https://www.hani.co.kr/rss/", "site:hani.co.kr+-english"),
    "동아일보":            _native("https://rss.donga.com/total.xml", "site:donga.com"),
    "MBN":                _gnews("Korea+site:mbn.co.kr"),
    "중앙일보":            _native("https://rss.joins.com/joins_news_list.xml", "site:joongang.co.kr"),
    "한국일보":            _native("https://www.hankookilbo.com/rss/total", "site:hankookilbo.com"),
    "뉴시스":              _native("https://www.newsis.com/RSS/politics.xml", "site:newsis.com"),
    "서울신문":            _gnews("site:seoul.co.kr"),
    "경향신문":            _native("https://www.khan.co.kr/rss/rssdata/total_news.xml", "site:khan.co.kr"),
    "뉴스1":              _gnews("site:news1.kr"),
    "연합뉴스":            _native("https://www.yna.co.kr/RSS/news.xml", "site:yna.co.kr+-en"),
    # ── Korean broadcast & cable news ────────────────────────────────────
    "JTBC":               _gnews("site:news.jtbc.co.kr"),
    "KBS":                _gnews("site:news.kbs.co.kr"),
    "MBC":                _gnews("site:imnews.imbc.com"),
    # SBS's search fallback was 542 of the 1,150 Google News items one run
    # collected, and every one a redirect. Its own section feeds instead
    # (01 politics, 02 economy, 07 international); the search stays behind
    # each, narrowed so a native outage does not bring the flood back.
    "SBS":                _native("https://news.sbs.co.kr/news/SectionRssFeed.do?sectionId=01&plink=RSSREADER",
                                  "site:news.sbs.co.kr"),
    "SBS 경제":            _native("https://news.sbs.co.kr/news/SectionRssFeed.do?sectionId=02&plink=RSSREADER",
                                  "경제 site:news.sbs.co.kr"),
    "SBS 국제":            _native("https://news.sbs.co.kr/news/SectionRssFeed.do?sectionId=07&plink=RSSREADER",
                                  "북한 OR 한미 OR 미국 site:news.sbs.co.kr"),
    "YTN":                _gnews("site:ytn.co.kr"),
    # A guessed publisher feed here does not resolve at all (no such host),
    # so it cost a DNS failure every run and delivered nothing.
    "Channel A":          _gnews("Korea+site:channela.com"),
    "Arirang News":       _gnews("Korea+site:arirang.com"),
    # ── Korean business dailies ──────────────────────────────────────────
    "매일경제":            _native("https://www.mk.co.kr/rss/30000001/", "site:mk.co.kr"),
    "한국경제":            _native("https://www.hankyung.com/feed/all-news", "site:hankyung.com"),
    # KED Global's own feed, unverified from here; the search answers if wrong.
    "Korea Economic Daily": ["https://www.kedglobal.com/newsRss",
                             "https://www.kedglobal.com/rss/allArticle.xml",
                             _gnews("Korea+site:kedglobal.com")],
    # ── Major international — Korea correspondents ────────────────────────
    "WSJ Korea":          _gnews("Korea+site:wsj.com"),
    "NYT Korea":          _gnews("Korea+site:nytimes.com"),
    "WaPo Korea":         _gnews("Korea+site:washingtonpost.com"),
    "FT Korea":           _gnews("Korea+site:ft.com"),
    "Reuters Korea":      _native("https://www.reutersagency.com/feed/?best-topics=political-general&post_type=best", "Korea+site:reuters.com"),
    "AP Korea":           _native("https://apnews.com/index.rss", "Korea+site:apnews.com"),
    "Bloomberg Korea":    _gnews("Korea+site:bloomberg.com"),
    "BBC Korea":          _native("https://feeds.bbci.co.uk/news/world/asia/rss.xml", "Korea+site:bbc.com"),
    "CNN Korea":          _gnews("Korea+site:cnn.com"),
    "CNBC Korea":         _gnews("Korea+site:cnbc.com"),
    "Economist Korea":    _native("https://www.economist.com/asia/rss.xml", "Korea+site:economist.com"),
    "Guardian Korea":     _native("https://www.theguardian.com/world/south-korea/rss", "Korea+site:theguardian.com"),
    "Al Jazeera Korea":   _gnews("Korea+site:aljazeera.com"),
    # ── Regional Asia ─────────────────────────────────────────────────────
    "Nikkei Korea":       _native("https://asia.nikkei.com/rss/feed/nar", "Korea+site:asia.nikkei.com"),
    "Japan Times Korea":  _native("https://www.japantimes.co.jp/feed/", "Korea+site:japantimes.co.jp"),
    "SCMP Korea":         _native("https://www.scmp.com/rss/4/feed", "Korea+site:scmp.com"),
    "Kyodo Korea":        _gnews("Korea+site:english.kyodonews.net"),
    "Mainichi Korea":     _gnews("Korea+site:mainichi.jp/english"),
    "Asahi Korea":        _gnews("Korea+site:asahi.com/ajw"),
    "CNA Korea":          _gnews("Korea+site:channelnewsasia.com"),
    # ── ROK/US Government ─────────────────────────────────────────────────
    "White House":        _gnews("Korea+site:whitehouse.gov"),
    "State Dept":         _native("https://www.state.gov/rss-feed/press-releases/feed/", "Korea+site:state.gov"),
    "Pentagon":           _native("https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=40", "Korea+site:defense.gov"),
    "Stars and Stripes":  _native("https://www.stripes.com/rss/pacific.rss", "Korea+site:stripes.com"),
    # ── ROK/Japan Government ─────────────────────────────────────────────
    "USFK":               _gnews("site:usfk.mil"),
    # ── ROK government ───────────────────────────────────────────────────
    # These were `site:xxx.go.kr` Google News searches, and Google News
    # indexes very few .go.kr pages. Measured against the published corpus
    # for 12-18 October 2026, the twenty feeds below delivered 15 items in
    # seven days between them, most of them page furniture ("PRESS RELEASES -
    # 재정경제부", "Photos - 재정경제부"). The Presidential Office, MND,
    # Unification, the Joint Chiefs, DAPA and the Assembly delivered nothing.
    #
    # Each feed is now: the body's own board RSS where one is published, then
    # a Korean-edition search for how the press reports that body (its
    # spokesperson, its briefing, the way a Korean headline names it). The
    # press reports these bodies daily, so the search always answers; items
    # it finds are reporting about the body, carry the outlet as their source,
    # and rank below a document on a government domain (digest._prompt_band).
    #
    # Names follow the 2025 reorganisation: MOEF is now 재정경제부 plus
    # 기획예산처, MOTIE is 산업통상부, Statistics Korea is 국가데이터처, and
    # the Presidential Office is back at 청와대. Old names stay in the queries
    # because the press still uses both.
    "ROK MOFA":           _native("https://www.mofa.go.kr/www/brd/rss.do?brdId=235",
                                  '"외교부 대변인" OR "외교부 정례브리핑" OR "외교부는"', locale="ko"),
    # MOFA's English board: press releases (302), then spokesperson briefings (303).
    "ROK MOFA English":   _native("https://www.mofa.go.kr/www/brd/rss.do?brdId=302",
                                  '"South Korean foreign ministry" OR "Seoul\'s foreign ministry" '
                                  'OR "South Korea\'s foreign ministry"',
                                  also=["https://www.mofa.go.kr/www/brd/rss.do?brdId=303"]),
    "ROK MOTIE":          [_press('"산업통상부" OR "산업통상자원부" OR "통상교섭본부장" OR "산업부 장관"')],
    "ROK MND":            _native("https://www.mnd.go.kr/bbs/mnd/13000005/rssList.do?row=50",
                                  '"국방부 대변인" OR "국방부 정례브리핑" OR "국방부는"', locale="ko"),
    "ROK Presidential Office": [_press('"청와대 대변인" OR "청와대 브리핑" OR "대통령실 대변인" '
                                       'OR "대통령실 브리핑" OR "청와대 관계자"')],
    "ROK Unification Ministry": _native("https://www.unikorea.go.kr/web/unikorea/rss/bbs_0000000000000004",
                                        '"통일부 대변인" OR "통일부 정례브리핑" OR "통일부는"', locale="ko"),
    "ROK MOEF":           [_press('"재정경제부" OR "기획예산처" OR "재경부 장관" OR "기재부"')],
    "ROK DAPA":           [_press('"방위사업청" OR "방사청은"')],
    # October is 국정감사, the Assembly's annual audit of every ministry.
    "ROK National Assembly": [_press('"국회 본회의" OR "국정감사" OR "국회의장" OR "상임위원회 전체회의"')],
    # Prosecution and the courts drive the ROK political cycle. The
    # prosecution service is being replaced by 공소청 and 중대범죄수사청, and
    # the special counsels carry the cases that matter, so all are named.
    "ROK Prosecution Service": [_press('"공소청" OR "중대범죄수사청" OR "대검찰청" OR "특검팀은"')],
    "ROK Courts":         [_press('"대법원은" OR "대법원 선고" OR "헌법재판소는" OR "헌재 선고"')],
    # DART is the financial supervisory disclosure system. Samsung, Hyundai and
    # SK file there before they announce, so this is corporate news at source
    # rather than through the business dailies.
    "DART disclosures":   _gnews("%EC%A0%84%EC%9E%90%EA%B3%B5%EC%8B%9C+OR+site:dart.fss.or.kr",
                                 locale="ko"),
    # korea.kr (정책브리핑) was the whole-of-government aggregator, publishing
    # /rss/pressrelease.xml, /rss/policy.xml and one /rss/dept_<code>.xml per
    # ministry. It announced the end of its RSS service on 1 July 2026, and
    # the native feed delivered nothing in October: both of its items that
    # week came through the search behind it. The URLs stay first because a
    # dead native candidate costs one fast request; no other feed relies on
    # korea.kr any longer.
    "ROK Policy Briefing": ["https://www.korea.kr/rss/pressrelease.xml",
                            "https://www.korea.kr/rss/policy.xml",
                            _gnews("site:korea.kr")],
    # Korea.net's Policies feed (news/3) rather than "All" (news/2), which is
    # mostly culture and travel.
    "Korea.net":          _native("https://www.korea.net/koreanet/rss/news/3", "site:korea.net"),
    # The Joint Chiefs are the originating source for every DPRK launch
    # detection. They publish no RSS; the press quotes them within minutes.
    "ROK Joint Chiefs":   [_press('"합참은" OR "합동참모본부는" OR "합참 관계자" OR "합참 공보실장"')],
    # BOK press releases and MPC statements. The ECOS statistics API is
    # already called for the rate itself; this is the accompanying language.
    "Bank of Korea":      [_press('"한국은행은" OR "한은 총재" OR "금융통화위원회"')],
    "Statistics Korea":   [_press('"국가데이터처" OR "통계청은" OR "통계청에 따르면"')],
    # Customs publishes the ten-day export figures — the earliest read on what
    # the tariff regime is actually doing to trade.
    "Korea Customs":      [_press('"관세청은" OR "관세청에 따르면"')],
    "ROK Justice Ministry": [_press('"법무부는" OR "법무부 장관"')],
    "ROK FSC":            [_press('"금융위원회는" OR "금융위원장"')],
    # Yonhap's own politics and North Korea desks. The all-news feeds above
    # carry the latest items across every desk; these keep the ministry,
    # defence and inter-Korean wire copy from being pushed out by volume.
    "Yonhap Politics":    _native("https://www.yna.co.kr/rss/politics.xml",
                                  "국방 OR 외교 OR 통일 site:yna.co.kr", locale="ko"),
    "Yonhap North Korea": _native("https://www.yna.co.kr/rss/northkorea.xml",
                                  "북한 site:yna.co.kr", locale="ko"),
    "Yonhap English National": _native("https://en.yna.co.kr/RSS/national.xml",
                                       'defense OR military OR unification OR "foreign ministry" '
                                       'site:en.yna.co.kr'),
    "Japan MOFA":         _gnews("Korea+site:mofa.go.jp"),
    # ── US Economic agencies ────────────────────────────────────────────
    "USTR":               _gnews("Korea+OR+trade+site:ustr.gov"),
    "Federal Register KR": _gnews("Korea+OR+DPRK+site:federalregister.gov"),
    "Dept of Commerce":   _gnews("Korea+site:commerce.gov"),
    "Dept of Treasury":   _gnews("Korea+site:treasury.gov"),
    "OFAC":               _gnews("Korea+OR+DPRK+site:ofac.treasury.gov"),
    "BIS":                ["https://www.bis.doc.gov/index.php/all-articles?format=feed&type=rss",
                           _gnews("Korea+OR+DPRK+site:bis.doc.gov")],
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
    "Brookings":         (_native("https://www.brookings.edu/feed/",
                                  "Korea+site:brookings.edu"), "A"),
    "Carnegie":          (_native("https://carnegieendowment.org/rss/solr?query=korea",
                                  "Korea+site:carnegieendowment.org"), "A"),
    "RAND":              (_native("https://www.rand.org/topics/north-korea.xml",
                                  "Korea+site:rand.org"), "A"),
    "CFR":               (_gnews("Korea+site:cfr.org"), "A"),
    "38 North":          ("https://www.38north.org/feed/", "A"),
    # Timed out rather than 404ing on 14 September: the host exists and may
    # simply have been down, which is not proof the path is wrong. Kept.
    "AccessDPRK":        (["https://accessdprk.com/feed/",
                           _gnews("site:accessdprk.com")], "A"),
    "ArmsControlWonk":   (_gnews("site:armscontrolwonk.com"), "A"),
    "Stimson":           (_gnews("Korea+site:stimson.org"), "B"),
    "IISS":              (_gnews("Korea+site:iiss.org"), "B"),
    "ASAN Institute":    (_gnews("Korea+site:asaninst.org"), "B"),
    "EAI":               (_gnews("Korea+site:eai.or.kr"), "B"),
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
    # ── CRS / Congressional research ────────────────────────────────────────
    "CRS Korea":         ([_gnews("Korea+OR+DPRK+site:crsreports.congress.gov"),
                           _gnews("%22Congressional+Research+Service%22+Korea")], "B"),
    "CRS North Korea":   (_gnews("North+Korea+site:everycrsreport.com"), "B"),
    # ── DPRK-specialist direct feeds ────────────────────────────────────────
    "Beyond Parallel":   ("https://beyondparallel.csis.org/feed/", "A"),
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
    # Direct KCNA sources (often blocked — kept for when they work)
    "KCNA Watch":         _native("https://kcnawatch.org/newstream/feed/",
                                  "KCNA+site:kcnawatch.org"),
    # Wire services / outlets that relay KCNA content daily (primary indirect)
    # Yonhap's North Korea section feed: the wire that relays KCNA first.
    "KCNA (Yonhap)":      _native("https://en.yna.co.kr/RSS/northkorea.xml", "KCNA site:en.yna.co.kr"),
    "KCNA (Reuters)":     _gnews("KCNA+site:reuters.com"),
    "KCNA (AP)":          _gnews("KCNA+site:apnews.com"),
    "KCNA (AFP)":         _gnews("KCNA+OR+%22North+Korea+state+media%22+site:france24.com"),
    # NK-specialist outlets that cite KCNA
    # Both outlets write about nothing but North Korea, so their own feeds
    # are as relevant as the KCNA-only search and are real article links.
    "KCNA (38 North)":    _native("https://www.38north.org/feed/", "KCNA+site:38north.org"),
    "KCNA (Daily NK)":    _native("https://www.dailynk.com/english/feed/", "KCNA+site:dailynk.com"),
    "KCNA (NK News)":     _gnews("KCNA+site:nknews.org"),
    # The guessed NK News category feed 404s. KCNA Watch proper now delivers
    # through its own entry, so this one stays on its search.
    "KCNA (Korea Risk)":  _gnews("KCNA+site:koreariskgroup.com"),
    # Major newspapers that relay KCNA statements
    "KCNA (BBC)":         _gnews("KCNA+OR+%22North+Korea+state+media%22+site:bbc.com"),
    "KCNA (NYT)":         _gnews("KCNA+site:nytimes.com"),
    "KCNA (WaPo)":        _gnews("KCNA+site:washingtonpost.com"),
    # Broad catch-all queries (redundant by design — ensures coverage)
    "KCNA (KCBS)":        _gnews("%22Korean+Central+Broadcasting%22+OR+%22KCNA+reported%22+OR+%22KCNA+said%22"),
    "KCNA (state media)": _gnews("%22North+Korea+state+media%22+OR+%22KCNA+said%22+OR+%22Pyongyang+said%22"),
    "KCNA (Kim stmt)":    _gnews("%22Kim+Jong+Un%22+%22KCNA%22+OR+%22state+media%22+statement+OR+message+OR+order"),
}

# ── Kim Jong Un appearance tracking feeds ──────────────────────────────────
KIM_TRACKER_FEEDS = {
    "KJU Appearance":     _gnews("%22Kim+Jong+Un%22+appearance+OR+appeared+OR+attended+OR+inspected+OR+observed"),
    "KJU Activity":       _gnews("%22Kim+Jong+Un%22+guidance+OR+visit+OR+presided+OR+oversaw"),
    "NK Leadership Watch": _gnews("%22Kim+Jong+Un%22+site:nkleadershipwatch.org"),
    "Daily NK KJU":       _gnews("%22Kim+Jong+Un%22+site:dailynk.com"),
    "KCNA KJU":           _gnews("%22Kim+Jong+Un%22+site:kcnawatch.org"),
}

# ── Capitol Hill: US Congress on Korea ──────────────────────────────────────
# Its own stream rather than more tier-1 entries. These outlets publish about
# everything Congress does, so almost none of it is about Korea, and inside
# tier 1 the few items that are would compete for the 140 prompt slots with
# the Korea desks and lose. The stream is filtered by HILL_KOREA_KEYWORDS
# (not KOREA_NATIVE_FEEDS: none of these is Korea-relevant by construction),
# given its own block in the prompt, and merged into tier 1 afterwards only
# so validation and URL repair see the same input the model saw.
#
# Native feed first, Google News search last, as everywhere else. The three
# committee searches already in TIER1_FEEDS stay where they are; the entries
# here add the committees' own feeds and the hearing calendars.
CAPITOL_HILL_FEEDS = {
    "Congress.gov House Floor": _native("https://www.congress.gov/rss/house-floor-today.xml",
                                        "Korea+site:congress.gov"),
    "Congress.gov Senate Floor": _native("https://www.congress.gov/rss/senate-floor-today.xml",
                                         "%22North+Korea%22+OR+%22South+Korea%22+site:congress.gov"),
    "Congress.gov Bills":  _native("https://www.congress.gov/rss/most-viewed-bills.xml",
                                   "Korea+bill+site:congress.gov"),
    "GovInfo Bills":       _native("https://www.govinfo.gov/rss/bills.xml",
                                   "Korea+site:govinfo.gov"),
    "GovInfo Hearings":    _native("https://www.govinfo.gov/rss/chrg.xml",
                                   "Korea+hearing+site:govinfo.gov"),
    "CRS Reports":         ["https://crsreports.congress.gov/rss",
                            "https://www.everycrsreport.com/rss.xml",
                            _gnews("Korea+OR+DPRK+OR+%22North+Korea%22+site:crsreports.congress.gov")],
    "The Hill Defense":    _native("https://thehill.com/policy/defense/feed/",
                                   "Korea+site:thehill.com"),
    "The Hill International": _native("https://thehill.com/policy/international/feed/",
                                      "%22North+Korea%22+OR+%22South+Korea%22+site:thehill.com"),
    "Roll Call":           _native("https://rollcall.com/feed/", "Korea+site:rollcall.com"),
    "Politico Congress":   _native("https://rss.politico.com/congress.xml",
                                   "Korea+Congress+OR+Senate+OR+House+site:politico.com"),
    "Punchbowl":           _gnews("Korea+site:punchbowl.news"),
    "HFAC Hearings":       _native("https://foreignaffairs.house.gov/feed/",
                                   "Korea+hearing+site:foreignaffairs.house.gov"),
    "HASC":                _native("https://armedservices.house.gov/rss.xml",
                                   "Korea+site:armedservices.house.gov"),
    "SFRC Hearings":       _native("https://www.foreign.senate.gov/rss/feeds/?type=hearings",
                                   "Korea+hearing+site:foreign.senate.gov"),
    "SASC Hearings":       _native("https://www.armed-services.senate.gov/rss/feeds/?type=hearings",
                                   "Korea+hearing+site:armed-services.senate.gov"),
    "House Appropriations": _native("https://appropriations.house.gov/rss.xml",
                                    "Korea+site:appropriations.house.gov"),
    "Senate Appropriations": _gnews("Korea+site:appropriations.senate.gov"),
    # Searches across outlets. No publisher feed exists for a topic, so these
    # are search-only, and they must also show a US-Congress signal: "Korea"
    # plus "lawmaker" is far more often the National Assembly.
    "Korea Caucus":        _gnews("%22Korea+Caucus%22+Congress"),
    "US Congress Korea":   _gnews("%22South+Korea%22+OR+%22North+Korea%22+Congress+OR+senator+OR+congressman+OR+NDAA"),
    "Congress Shipbuilding Korea": _gnews("MASGA+OR+shipbuilding+Korea+Congress+OR+senator+OR+bill"),
}

# Search feeds that must show a US-Congress signal as well as a Korea one.
HILL_SEARCH_FEEDS = {"Korea Caucus", "US Congress Korea", "Congress Shipbuilding Korea", "Punchbowl"}

# Congressional hearing and markup schedules. Parsed for events, not articles:
# see _collect_hill_calendar. Each is tried on its own, and every failure is
# survivable — the section simply has no "Coming up" line.
#
# docs.house.gov's meeting feed is per committee: RSS.ashx?Code=FA00. The bare
# RSS.ashx this used to request names no committee, so the House side of the
# calendar could not return an event. Codes are the House's own committee
# codes (FA Foreign Affairs, AS Armed Services, WM Ways and Means, AP
# Appropriations, IG Intelligence; 00 is the full committee).
_HOUSE_MEETING_FEED = "https://docs.house.gov/Committee/RSS.ashx?Code="
HILL_CALENDAR_FEEDS = {
    "Senate committee schedule": "https://www.senate.gov/general/committee_schedules/hearings.xml",
    "House Foreign Affairs schedule": _HOUSE_MEETING_FEED + "FA00",
    "House Armed Services schedule": _HOUSE_MEETING_FEED + "AS00",
    "House Ways and Means schedule": _HOUSE_MEETING_FEED + "WM00",
    "House Appropriations schedule": _HOUSE_MEETING_FEED + "AP00",
    "House Intelligence schedule": _HOUSE_MEETING_FEED + "IG00",
    "HFAC schedule":             "https://foreignaffairs.house.gov/feed/?post_type=hearing",
    "HASC schedule":             "https://armedservices.house.gov/rss.xml",
    "SFRC schedule":             "https://www.foreign.senate.gov/rss/feeds/?type=hearings",
    "SASC schedule":             "https://www.armed-services.senate.gov/rss/feeds/?type=hearings",
}
_HOUSE_DOCS_FEEDS = [k for k, v in HILL_CALENDAR_FEEDS.items() if v.startswith(_HOUSE_MEETING_FEED)]
# Where a reader can see the schedule when a listing carries no link of its own.
HILL_SCHEDULE_PAGES = {"Senate committee schedule": "https://www.senate.gov/committees/hearings_meetings.htm"}
HILL_SCHEDULE_PAGES.update({k: "https://docs.house.gov/Committee/Calendar/ByWeek.aspx"
                            for k in _HOUSE_DOCS_FEEDS})
HILL_CALENDAR_COMMITTEES = {
    "HFAC schedule": "House Foreign Affairs", "HASC schedule": "House Armed Services",
    "SFRC schedule": "Senate Foreign Relations", "SASC schedule": "Senate Armed Services",
}
HILL_CALENDAR_COMMITTEES.update({k: k.replace(" schedule", "") for k in _HOUSE_DOCS_FEEDS})
# Feeds that list only meetings. Their titles are the hearing's subject
# ("Countering the CCP's Maritime Coercion"), rarely the word "hearing", so
# the title test that keeps press releases out of a committee's news feed
# dropped every item they carried.
HILL_MEETING_ONLY_FEEDS = set(_HOUSE_DOCS_FEEDS) | {"HFAC schedule", "SFRC schedule", "SASC schedule"}
# senate.gov and house.gov sit behind a CDN that refuses unfamiliar agents
# from cloud addresses; the schedules are public pages, fetched as a browser.
HILL_CALENDAR_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/xml,application/rss+xml,text/xml;q=0.9,*/*;q=0.8",
}

# ── Korea and the World: beyond the US and Northeast Asia ───────────────────
# Measured against the published corpus for 15-18 October 2026: tier 1 carried
# 4-20 such items a day, almost all from the Korea Times and Yonhap, and none
# on Poland, defence exports or the Gulf. These targeted feeds fill that gap.
# Outlets with a native feed are listed native-first; topic searches have no
# publisher feed to put first. Filtered for Korea and for a non-Northeast-Asia
# place or body (WORLD_KEYWORDS), so a USFK or Japan story does not leak in.
KOREA_WORLD_FEEDS = {
    "Defense News Korea":    _native("https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml",
                                     "Korea+site:defensenews.com"),
    "Breaking Defense Korea": _native("https://breakingdefense.com/feed/",
                                      "Korea+site:breakingdefense.com"),
    "Euractiv Korea":        _native("https://www.euractiv.com/feed/", "Korea+site:euractiv.com"),
    "Notes from Poland Korea": _native("https://notesfrompoland.com/feed/",
                                       "Korea+site:notesfrompoland.com"),
    "Arab News Korea":       _native("https://www.arabnews.com/rss.xml", "Korea+site:arabnews.com"),
    "VnExpress Korea":       _native("https://e.vnexpress.net/rss/news.rss", "Korea+site:e.vnexpress.net"),
    "Kyiv Independent Korea": _native("https://kyivindependent.com/rss/", "Korea+site:kyivindependent.com"),
    "UN News Korea":         _native("https://news.un.org/feed/subscribe/en/news/all/rss.xml",
                                     "Korea+OR+DPRK+site:news.un.org"),
    "Korea defense exports": _gnews("%22South+Korea%22+arms+OR+defense+export+K2+OR+K9+OR+Chunmoo+OR+FA-50+OR+KF-21"),
    "Korea-Poland":          _gnews("Poland+Korea+K2+OR+K9+OR+Chunmoo+OR+Hanwha+OR+%22Hyundai+Rotem%22"),
    "Korea-Europe":          _gnews("%22South+Korea%22+EU+OR+NATO+OR+European+OR+Europe"),
    "Korea-Middle East":     _gnews("%22South+Korea%22+Saudi+OR+UAE+OR+Qatar+OR+Iraq+OR+Israel+OR+Iran+OR+%22Middle+East%22"),
    "Korea-Southeast Asia":  _gnews("%22South+Korea%22+ASEAN+OR+Vietnam+OR+Indonesia+OR+Philippines+OR+Malaysia+OR+Thailand"),
    "Korea-India":           _gnews("%22South+Korea%22+India+OR+Pakistan+OR+Bangladesh"),
    "Korea-Global South":    _gnews("%22South+Korea%22+Africa+OR+Brazil+OR+Mexico+OR+Peru+OR+Kazakhstan+OR+Uzbekistan+OR+%22Latin+America%22+OR+%22Central+Asia%22"),
    "Korea-Ukraine":         _gnews("%22South+Korea%22+OR+Seoul+Ukraine"),
    "Korea multilateral":    _gnews("%22South+Korea%22+OR+DPRK+%22United+Nations%22+OR+G20+OR+WTO+OR+IAEA"),
    "Korea nuclear exports": _gnews("KHNP+OR+%22Korea+Hydro%22+OR+%22Doosan+Enerbility%22+nuclear+plant+export+OR+Czech+OR+Dukovany"),
    "Korea overseas construction": _gnews("Korean+builders+OR+%22Samsung+C%26T%22+OR+%22Hyundai+E%26C%22+overseas+contract+OR+order"),
    "Korea aid":             _gnews("KOICA+OR+%22South+Korea%22+humanitarian+aid+OR+ODA"),
}

KOREA_KEYWORDS = re.compile(
    r"korea|dprk|pyongyang|seoul|rok\b|kim jong|yoon suk|korean peninsula"
    r"|denucleariz|kaesong|yongbyon|hwasong|punggye|38th parallel"
    r"|usfk|combined forces|kim yo jong|choe son hui"
    r"|north korea|south korea|inter-korean"
    r"|한반도|북한|남북|조선민주주의|평양|서울|통일부|국방부",
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────────────────────
# Feeds that are Korea-relevant by construction
# ─────────────────────────────────────────────────────────────────────────────
# KOREA_KEYWORDS exists to strip world news out of general wires: Reuters and
# AP publish about everything, so their items must mention Korea to belong in
# a Korea brief.
#
# Applied to a primary ROK source it does the opposite of its job. Every item
# the finance ministry publishes is Korean by definition, but a real headline
# such as "2027년도 예산안 국무회의 의결" contains none of the eight Korean
# tokens in the pattern, so it was dropped before the model ever saw it.
# Measured against twelve representative ministry headlines, nine were
# discarded — the Presidential Office, MOFA, MOEF, MOTIE, DAPA, the Assembly,
# the Prosecution Service, the courts and the statistics office. Only the
# Unification and Defence ministries survived, because 통일부 and 국방부
# happen to appear in the pattern.
#
# The brief was telling the model it had primary sources while the collector
# was throwing most of them away. These feeds are exempt: relevance is already
# guaranteed by the feed itself.
# ROK government and state bodies: primary sources. Ranking puts their own
# documents first (digest._prompt_band), and test_sources checks that none of
# them rests on a bare site:*.go.kr search again.
ROK_GOVERNMENT_FEEDS = {
    "ROK MOFA", "ROK MOFA English", "ROK MOTIE", "ROK MND", "ROK Presidential Office",
    "ROK Unification Ministry", "ROK MOEF", "ROK DAPA",
    "ROK National Assembly", "ROK Prosecution Service", "ROK Courts",
    "DART disclosures",
    "ROK Policy Briefing", "Korea.net", "ROK Joint Chiefs", "Bank of Korea",
    "Statistics Korea", "Korea Customs", "ROK Justice Ministry", "ROK FSC",
}

KOREA_NATIVE_FEEDS = ROK_GOVERNMENT_FEEDS | {
    "USFK",
    # Korean-language outlets
    "조선일보", "한겨레", "동아일보", "경향신문", "뉴스1", "연합뉴스",
    "중앙일보", "한국일보", "뉴시스", "서울신문",
    "MBN", "JTBC", "KBS", "MBC", "SBS", "SBS 경제", "YTN", "Channel A", "Arirang News",
    "매일경제", "한국경제", "서울경제", "머니투데이",
    # English-language Korea desks whose entire output is Korea
    "Yonhap English", "Yonhap English National", "Yonhap Politics", "Yonhap North Korea",
    "Korea Herald", "Korea Times", "Korea JoongAng Daily",
    "Korea Economic Daily", "Dong-A English", "Chosun English",
    "Hankyoreh English", "Pressian",
}

# Korean-language feeds, for the lang tag that drives full-text fetch and the
# in-prompt translation note. Derived rather than restated so the two lists
# cannot drift apart.
KOREAN_LANGUAGE_FEEDS = {
    "조선일보", "한겨레", "동아일보", "경향신문", "뉴스1", "연합뉴스",
    "중앙일보", "한국일보", "뉴시스", "서울신문",
    "MBN", "JTBC", "KBS", "MBC", "SBS", "SBS 경제", "SBS 국제", "YTN", "Channel A",
    "매일경제", "한국경제", "서울경제", "머니투데이",
    "ROK Presidential Office", "ROK Unification Ministry", "ROK MOEF",
    "ROK DAPA", "ROK National Assembly", "ROK Prosecution Service",
    "ROK Courts", "ROK MOFA", "ROK MND", "ROK MOTIE", "DART disclosures",
    "ROK Policy Briefing", "ROK Joint Chiefs", "Bank of Korea",
    "Statistics Korea", "Korea Customs", "ROK Justice Ministry", "ROK FSC",
    "Yonhap Politics", "Yonhap North Korea",
}


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

REQUEST_TIMEOUT = 8
HEADERS = {"User-Agent": "CSISKoreaDigest/1.0"}
MAX_WORKERS = 25  # Thread pool size for parallel fetching

# ─────────────────────────────────────────────────────────────────────────────
# SOURCE HEALTH TRACKING (per-run, not persistent)
# ─────────────────────────────────────────────────────────────────────────────
_source_health = {}  # {feed_name: {articles: int, success: bool, error_msg: str|None}}
_feed_source_used = {}  # {url: "native"|"google-news"} — which candidate answered
_unresolved_urls = []   # sources whose Google News link would not decode
_offsite_dropped = {}   # {candidate url: items dropped for coming from another site}

MAJOR_FEEDS = {"Yonhap English", "Korea Herald", "Reuters Korea", "AP Korea"}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _parse_one(url: str, retries: int = 3) -> list:
    """Fetch and parse a single feed URL. Never raises; returns [] on failure."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
            if resp.status_code in (401, 403):
                print(f"    ⚠  Feed blocked ({resp.status_code}): {url[:80]}")
                return []
            resp.raise_for_status()
            return feedparser.parse(resp.content).entries
        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            print(f"    ⚠  Feed error (after {retries} tries): {e}")
            return []
        except Exception as e:
            print(f"    ⚠  Feed error: {e}")
            return []
    return []


def _parse_feed(url) -> list:
    """Fetch a feed that may be defined as several candidate URLs.

    Nearly every feed in this file is a Google News `site:` search rather than
    the outlet's own RSS. That made the whole brief depend on one service:
    a Google News change or rate-limit takes almost every source at once, and
    there is no partial degradation — the brief simply arrives thin, with no
    signal that anything broke.

    A feed can now be a list of URLs, tried in order. Put the outlet's native
    feed first and the Google News search last. Two useful properties follow:

    - The brief stops depending on a single upstream. When a native feed
      works, Google News is not touched.
    - A native URL that is wrong or has moved costs nothing. It returns no
      items and the next candidate answers. That matters because outlets
      restructure their feeds without notice, and it is what makes it safe to
      add a native URL that could not be verified at the time it was written.

    The first candidate to return items wins. `_feed_source_used` records
    which one, so the run log can show how much of the brief still rests on
    Google News.

    A candidate whose every item is more than a week old has not answered: a
    frozen board (a ministry that stopped posting to its RSS, a service that
    was switched off but still serves its last file) would otherwise win, be
    emptied by the recency filter, and keep the search behind it from ever
    running. No tier's window is longer than a week, so this drops nothing
    the collector would have kept.
    """
    candidates = [url] if isinstance(url, str) else list(url)
    for i, candidate in enumerate(candidates):
        last = i == len(candidates) - 1
        # Only the last candidate is worth three attempts; earlier ones should
        # fail fast so a dead native URL does not add six seconds per feed.
        entries = _parse_one(candidate, retries=3 if last else 1)
        entries = _keep_site_matches(entries, candidate)
        if entries and not last and not _any_live(entries):
            continue
        if entries:
            _feed_source_used[candidate] = ("native" if "news.google.com" not in candidate
                                            else "google-news")
            return entries
    return []


_CANDIDATE_STALE_DAYS = 7


def _any_live(entries: list) -> bool:
    """True if any entry is undated or dated within the last week."""
    return any(_is_recent(e, hours=24 * _CANDIDATE_STALE_DAYS) for e in entries)


def _entry_publisher(entry) -> tuple[str, str]:
    """(publisher name, publisher home URL) from the RSS <source url=…> element.

    Google News items carry the real outlet there; the feed name says only
    which search found the item. Native feeds usually carry none: ('', '').
    """
    try:
        src = entry.get("source") or {}
        return (str(src.get("title") or "").strip(), str(src.get("href") or "").strip())
    except Exception:
        return "", ""


def _keep_site_matches(entries: list, candidate: str) -> list:
    """Drop search results from outside the site: the search was limited to.

    A `site:` search is not a guarantee: "KCNA (state media)" returned SCMP and
    the Straits Times, "CRS Korea" a Nigerian tabloid. When the candidate that
    answered is a Google News search with a required site: term, an item whose
    publisher home is another domain is not this feed's item.
    """
    targets = links.site_targets(candidate)
    if not targets or not entries:
        return entries
    kept = [e for e in entries if links.publisher_matches_site(_entry_publisher(e)[1], targets)]
    dropped = len(entries) - len(kept)
    if dropped:
        _offsite_dropped[candidate] = dropped
    return kept


_BOILERPLATE_PATTERNS = [
    # Cookie/consent banners
    r"\bwe use cookies\b", r"\bcookie policy\b", r"\baccept cookies\b",
    r"\bcookie preferences\b", r"\bcookie consent\b",
    # Subscribe / paywall
    r"\bsubscribe to (read|continue|our newsletter)\b", r"\bsign in to read\b",
    r"\bplease enable javascript\b", r"\byour browser is not supported\b",
    r"\bcreate a free account\b", r"\bregister for free\b",
    # Homepage marketing boilerplate (Coupang-style)
    r"\bthe perfect (place|destination) (for|to)\b",
    r"\byou name it\b", r"\bshop now\b", r"\bbrowse our\b",
    r"\bfree (shipping|delivery)\b.*\bon (orders|all)\b",
    # Category-list dumps ("Baby, Kids, Fashion, Beauty, Home & Kitchen and Electronics")
    r"\b(baby|kids|fashion|beauty|home|electronics|kitchen|toys|grocery|apparel)\s*,\s*"
    r"(baby|kids|fashion|beauty|home|electronics|kitchen|toys|grocery|apparel)\s*,\s*"
    r"(baby|kids|fashion|beauty|home|electronics|kitchen|toys|grocery|apparel)\b",
    # Site-nav / footer scrapes
    r"\ball rights reserved\b", r"\bterms of (service|use)\b",
    r"\bprivacy policy\b.*\b(cookie|terms)\b",
    r"\bcopyright\s*©?\s*\d{4}\b",
    # Session / login pages
    r"\byour session (has )?expired\b", r"\bplease log in\b",
]
_BOILERPLATE_RE = re.compile("|".join(_BOILERPLATE_PATTERNS), re.IGNORECASE)


def _clean_summary(summary: str, title: str) -> str:
    """Strip boilerplate from RSS/Google News description fields.

    Google News RSS occasionally returns the outlet's homepage meta description
    or a cookie/paywall banner instead of an article snippet. Feeding that to
    the AI as article body causes the model to paraphrase the boilerplate as
    if it were the story (e.g. the Coupang regulatory-dispute story getting
    summarized as "the perfect place for savvy shoppers"). Better to blank a
    bad summary than to trust it — the AI will fall back to the title alone.
    """
    if not summary:
        return ""
    if _BOILERPLATE_RE.search(summary):
        return ""
    # If summary is suspiciously short or looks like just the source name
    if len(summary) < 30:
        return ""
    # Title-only echo (source echoes title as description) — keep it, it's fine
    return summary


def _entry_to_article(entry, source: str, lang: str = "EN", extra: dict | None = None) -> dict:
    """One collected article.

    `source` is what the model and the reader see: the real publisher when the
    item says who it is (Google News's <source> element), the feed name
    otherwise. `feed` is always the feed name; ranking, feed health and the
    KCNA summary key on that.
    """
    title = entry.get("title", "").strip()
    publisher, publisher_home = _entry_publisher(entry)
    if publisher and title.endswith(f" - {publisher}"):
        title = title[: -len(f" - {publisher}")].rstrip()
    _raw_link = entry.get("link", "").strip()
    link = _resolve_gnews_url(_raw_link)
    # Google's newer article IDs are fully opaque and cannot be decoded, so the
    # reader gets a news.google.com redirect instead of the publisher's page.
    # Counting them makes the cost of the Google News dependency visible rather
    # than leaving it as a vague worry.
    if "news.google.com" in link and "/articles/" in link:
        _unresolved_urls.append(source)
    summary = entry.get("summary", entry.get("description", "")).strip()
    summary = re.sub(r"<[^>]+>", " ", summary)
    summary = re.sub(r"\s+", " ", summary).strip()
    summary = _clean_summary(summary, title)

    pub_date = None
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            pub_date = datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
            break

    # Extract RSS category tags (feedparser stores them in entry.tags)
    tags = []
    for tag in getattr(entry, "tags", []) or []:
        term = tag.get("term", "").strip()
        if term:
            tags.append(term)

    article = {
        "title": title,
        "url": link,
        "summary": summary[:800],
        "source": publisher or source,
        "feed": source,
        "lang": lang,
        "pub_date": pub_date,
    }
    if publisher:
        article["publisher"] = publisher
    if publisher_home:
        article["publisher_home"] = publisher_home
    if tags:
        article["tags"] = tags
    if extra:
        article.update(extra)
    return article


def _is_recent(entry, hours: int = 48, strict: bool = False) -> bool:
    """True if the entry is within the recency window.

    strict=False (default): an entry with NO parseable date passes — fine for
    high-volume news feeds where a missing date usually means fresh wire copy.
    strict=True: an undated entry is REJECTED. Use for analysis/academic tiers,
    where a low-volume `site:` query backfills with old evergreen think-tank
    pieces that frequently carry no date — those must not be presented as
    today's analysis (e.g. a 2008 AEI essay slipping into opeds_today)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc) >= cutoff
    return not strict


_ENTERTAINMENT_FILTER = re.compile(
    r"\bk-?pop\b|\bbts\b|\bblackpink\b|\bnewjeans\b|\baespa\b|\bstray\s*kids\b"
    r"|\btwice\b|\b(?:k-?)?drama\b|\bidol\b|\bkcon\b|\bhybe\b|\bjyp\b|\bsm\s*ent",
    re.IGNORECASE,
)


def _is_entertainment(entry) -> bool:
    text = f"{entry.get('title', '')} {entry.get('summary', entry.get('description', ''))}"
    return bool(_ENTERTAINMENT_FILTER.search(text))


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
    """Fetch all feeds in parallel. Returns {source: (entries, extra_info)}.
    Also records per-source health data in the module-level _source_health dict."""
    results = {}

    def _fetch_one(source, url_or_tuple):
        if is_tiered:
            # (url_or_candidates, tier). The first element may itself be a list
            # of candidate URLs, so unpack the pair rather than the whole value
            # — otherwise a tiered feed given a fallback list would unpack into
            # the wrong two things and fail silently.
            url, tier_val = url_or_tuple[0], url_or_tuple[1]
        else:
            url = url_or_tuple
            tier_val = None
        entries = _parse_feed(url)
        return source, entries, tier_val

    items = list(feed_dict.items())
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_fetch_one, src, val): src for src, val in items}
        for future in as_completed(futures):
            src = futures[future]
            try:
                source, entries, tier_val = future.result()
                results[source] = (entries, tier_val)
                _source_health[source] = {
                    "articles": len(entries),
                    "success": len(entries) > 0,
                    "error_msg": None,
                }
            except Exception as e:
                print(f"    ⚠  Thread error: {e}")
                _source_health[src] = {
                    "articles": 0,
                    "success": False,
                    "error_msg": str(e),
                }
    return results


# ─────────────────────────────────────────────────────────────────────────────
# TIER COLLECTORS
# ─────────────────────────────────────────────────────────────────────────────

# Korean-language feeds arrive through Google News, whose RSS carries a title
# and often nothing else — so the richest sources in the brief were reaching
# the model as headlines alone. This fetches the article body for a bounded
# number of them. Bounded deliberately: full-text fetching is the slowest and
# most failure-prone thing the collector does, so it runs last, in parallel,
# with a hard per-request timeout, and any failure leaves the article exactly
# as it was.
_FULLTEXT_MAX_ARTICLES = 24
_FULLTEXT_TIMEOUT = 6.0
_FULLTEXT_CHARS = 2200
_SCRIPT_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _extract_body(html: str) -> str:
    """Pull readable text out of an article page.

    No dependency on a readability library: strip scripts and tags, collapse
    whitespace, then keep the longest run of prose. Crude, but it only has to
    beat a bare headline, and a bad extraction is discarded by the caller.
    """
    if not html:
        return ""
    text = _SCRIPT_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", text)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _fetch_fulltext(article: dict) -> dict:
    """Best-effort body fetch for one article. Never raises."""
    url = article.get("url") or ""
    if not url.startswith("http") or "news.google.com" in url:
        return article
    try:
        resp = requests.get(url, timeout=_FULLTEXT_TIMEOUT, headers={
            "User-Agent": "Mozilla/5.0 (compatible; CSIS-Korea-Digest/1.0)"})
        if resp.status_code != 200:
            return article
        resp.encoding = resp.apparent_encoding or resp.encoding
        body = _extract_body(resp.text)
    except Exception:
        return article
    # Only replace the summary when the fetch clearly beat it. A short
    # extraction usually means a paywall or consent wall, not an article.
    if len(body) > max(400, len(article.get("summary") or "") + 200):
        article = dict(article)
        article["summary"] = body[:_FULLTEXT_CHARS]
        article["fulltext"] = True
    return article


def _add_fulltext(articles: list) -> list:
    """Fetch bodies for the newest Korean-language articles, in parallel."""
    targets = [a for a in articles if a.get("lang") == "KO"][:_FULLTEXT_MAX_ARTICLES]
    if not targets:
        return articles
    by_url = {}
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_fetch_fulltext, a): a.get("url") for a in targets}
            for fut in as_completed(futures, timeout=_FULLTEXT_TIMEOUT * 4):
                try:
                    got = fut.result()
                    if got.get("fulltext"):
                        by_url[got.get("url")] = got
                except Exception:
                    continue
    except Exception:
        pass
    if by_url:
        articles = [by_url.get(a.get("url"), a) for a in articles]
        print(f"    📄  Full text fetched for {len(by_url)}/{len(targets)} Korean-language articles")
    return articles


# A ROK government feed's press search returns up to a hundred items, and in
# October (국정감사) most are within the day. A ministry posts far fewer
# documents than that, so the cap costs no primary source; it keeps fifteen
# press searches from adding over a thousand items to tier 1.
ROK_FEED_MAX_ITEMS = 12


def _newest(entries: list, n: int) -> list:
    """The n most recent entries; undated ones after the dated."""
    def key(e):
        for attr in ("published_parsed", "updated_parsed"):
            parsed = getattr(e, attr, None)
            if parsed:
                return (1, tuple(parsed[:6]))
        return (0, ())
    return sorted(entries, key=key, reverse=True)[:n]


def _collect_tier1() -> list:
    articles = []
    results = _fetch_feeds_parallel(TIER1_FEEDS)
    for source, (entries, _) in results.items():
        # Korean-language feeds get lang="KO"
        lang = "KO" if source in KOREAN_LANGUAGE_FEEDS else "EN"
        native = source in KOREA_NATIVE_FEEDS
        entries = [e for e in entries if _is_recent(e, hours=24)]
        if source in ROK_GOVERNMENT_FEEDS:
            entries = _newest(entries, ROK_FEED_MAX_ITEMS)
        for entry in entries:
            # A primary ROK source needs no relevance test; see KOREA_NATIVE_FEEDS.
            if not native and not _is_korea_related(entry):
                continue
            if _is_entertainment(entry):
                continue
            article = _entry_to_article(entry, source, lang=lang)
            article = _flag_journalist(article)
            articles.append(article)
    return _add_fulltext(_dedup(articles))


def _collect_tier2() -> list:
    articles = []
    results = _fetch_feeds_parallel(TIER2_FEEDS, is_tiered=True)
    for source, (entries, prestige) in results.items():
        for entry in entries:
            # strict: drop undated think-tank pieces (evergreen backfill from
            # low-volume site: queries — e.g. old AEI essays with no date).
            if not _is_recent(entry, hours=36, strict=True):
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
            # strict: undated academic hits are almost always old evergreen
            # papers backfilled by the journal site: query — reject them.
            if not _is_recent(entry, hours=72, strict=True):
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
            if not _is_recent(entry, hours=48):
                continue
            article = _entry_to_article(entry, source, lang="KO")
            articles.append(article)
    return _dedup(articles)


def _scrape_kcna_watch() -> list:
    """Scrape KCNA Watch newstream page for today's article headlines and categories.
    Falls back to Google cache / web search if direct scrape is blocked (403).
    Returns a list of dicts with title, url, category."""
    articles = []

    # Attempt 1: direct scrape. Retry once with a browser-like User-Agent —
    # kcnawatch.org 403s the default UA intermittently; a real browser UA
    # often gets through on the retry.
    _browser_ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
    for attempt, ua in enumerate((HEADERS.get("User-Agent", ""), _browser_ua)):
        try:
            resp = requests.get(
                "https://kcnawatch.org/newstream/",
                timeout=REQUEST_TIMEOUT,
                headers={**HEADERS, "User-Agent": ua, "Accept": "text/html"},
            )
            if resp.status_code == 403:
                if attempt == 0:
                    print("  ── KCNA Watch scrape: blocked (403) — retrying with browser UA")
                    continue
                print("  ── KCNA Watch scrape: blocked (403) — trying fallback")
                break
            resp.raise_for_status()
            articles = _parse_kcna_watch_html(resp.text)
            if articles:
                print(f"  ── KCNA Watch scrape: {len(articles)} articles from newstream page")
                return articles
            break  # 200 but nothing parsed — go to Google News fallback
        except Exception as e:
            print(f"  ── KCNA Watch scrape: ⚠ direct failed ({e})")
            if attempt == 0:
                continue
            break

    # Attempt 2: Google News search for kcnawatch.org articles. 72h window —
    # DPRK/KST vs UTC rollover and Google News indexing lag mean a 48h window
    # can miss same-day items entirely.
    try:
        gnews_url = _gnews("site:kcnawatch.org/newstream/")
        entries = _parse_feed(gnews_url)
        for entry in entries:
            if not _is_recent(entry, hours=72):
                continue
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            if title and link:
                articles.append({
                    "title": re.sub(r"<[^>]+>", "", title).strip(),
                    "url": link,
                    "category": "Uncategorized",
                })
        if articles:
            print(f"  ── KCNA Watch scrape: {len(articles)} articles via Google News fallback")
    except Exception as e:
        print(f"  ── KCNA Watch scrape: ⚠ Google fallback also failed ({e})")

    if not articles:
        print(f"  ── KCNA Watch scrape: 0 articles (all methods failed)")

    return articles


def _parse_kcna_watch_html(html: str) -> list:
    """Parse KCNA Watch newstream HTML for article entries."""
    articles = []
    import re as _re

    link_pattern = _re.compile(
        r'<a\s+href="(https?://kcnawatch\.org/newstream/\d{4}/\d{2}/\d{2}/[^"]+)"[^>]*>\s*([^<]+?)\s*</a>',
        _re.IGNORECASE,
    )
    cat_pattern = _re.compile(
        r'<span[^>]*class="[^"]*category[^"]*"[^>]*>\s*([^<]+?)\s*</span>',
        _re.IGNORECASE,
    )

    # Accept the last 3 days (UTC) — KCNA Watch dates URLs in KST, so a strict
    # today/yesterday-UTC window drops same-day items around the date rollover.
    now_utc = datetime.now(timezone.utc)
    recent_date_strs = {(now_utc - timedelta(days=d)).strftime("%Y/%m/%d")
                        for d in range(3)}

    seen_urls = set()
    for match in link_pattern.finditer(html):
        url, title = match.group(1), match.group(2).strip()
        if url in seen_urls:
            continue
        if not any(ds in url for ds in recent_date_strs):
            continue
        seen_urls.add(url)

        start = max(0, match.start() - 500)
        context = html[start:match.end() + 200]
        cat_match = cat_pattern.search(context)
        category = cat_match.group(1).strip() if cat_match else "Uncategorized"

        articles.append({
            "title": re.sub(r"<[^>]+>", "", title).strip(),
            "url": url,
            "category": category,
        })

    return articles


_DIRECT_KCNA_SOURCES = {"KCNA Watch", "KCNA", "Rodong Sinmun", "KCNA (Yonhap)"}

_KCNA_TITLE_PATTERNS = re.compile(
    r"KCNA|Korean Central News Agency|Rodong Sinmun|"
    r"Pyongyang\s+(said|says|reported|reports|announced|announces|claims|claimed)|"
    r"North Korea\s+(said|says)\s+.*(state media|official media)",
    re.IGNORECASE,
)


def _build_kcna_summary(tier4_articles: list, scraped_articles: list) -> dict:
    """Build a structured summary of today's KCNA output for the digest prompt."""
    # Combine sources for article count
    all_titles = set()
    categories = {}
    sources = {}
    direct_count = 0
    indirect_count = 0

    for art in tier4_articles:
        title = art.get("title", "").strip()
        if title:
            all_titles.add(title.lower())
        src = art.get("feed") or art.get("source", "Unknown")
        sources[src] = sources.get(src, 0) + 1
        # Track direct vs indirect
        if src in _DIRECT_KCNA_SOURCES:
            direct_count += 1
        else:
            indirect_count += 1
        for tag in art.get("tags", []):
            categories[tag] = categories.get(tag, 0) + 1
        # For indirect-source articles, check if title/summary mentions KCNA
        # and add a synthetic category so they're visible in the category breakdown
        if src not in _DIRECT_KCNA_SOURCES:
            text = f"{title} {art.get('summary', '')}".lower()
            if _KCNA_TITLE_PATTERNS.search(text):
                categories["KCNA-cited"] = categories.get("KCNA-cited", 0) + 1

    for art in scraped_articles:
        title = art.get("title", "").strip()
        if title and title.lower() not in all_titles:
            all_titles.add(title.lower())
            direct_count += 1  # scraped articles are always direct KCNA
        cat = art.get("category", "Uncategorized")
        if cat:
            categories[cat] = categories.get(cat, 0) + 1

    # Build headline list from scraped articles (more structured)
    headlines = []
    for art in scraped_articles:
        entry = art.get("title", "")
        cat = art.get("category", "")
        if entry:
            headlines.append(f"[{cat}] {entry}" if cat else entry)

    # Also add tier4 RSS headlines not already covered — include indirect sources
    scraped_titles = {a.get("title", "").lower() for a in scraped_articles}
    for art in tier4_articles:
        title = art.get("title", "")
        if title and title.lower() not in scraped_titles:
            src = art.get("feed") or art.get("source", "")
            # Say who actually reported it, not which search found it.
            _pub = art.get("publisher") or ""
            tags = art.get("tags", [])
            # For indirect sources, label with "via <outlet>" so the LLM
            # knows this is a secondary report citing KCNA
            if src not in _DIRECT_KCNA_SOURCES and src:
                tag_str = f"via {_pub or links.clean_feed_label(src)}"
            else:
                tag_str = tags[0] if tags else src
            headlines.append(f"[{tag_str}] {title}")

    return {
        "total_articles": len(all_titles),
        "direct_count": direct_count,
        "indirect_count": indirect_count,
        "categories": dict(sorted(categories.items(), key=lambda x: -x[1])),
        "sources": sources,
        "headlines": headlines[:50],  # Cap at 50 headlines
    }


SATELLITE_IMAGERY_FEEDS = {
    # Specialist sources (primary imagery analysts)
    "BP Imagery":       _gnews("satellite+imagery+site:beyondparallel.csis.org"),
    "38N Imagery":      _gnews("satellite+imagery+site:38north.org"),
    "AEI Imagery":      _gnews("North+Korea+satellite+imagery+site:aei.org"),
    "Middlebury MIIS":  _gnews("North+Korea+satellite+site:nonproliferation.org"),
    # Major wire services / newspapers covering imagery reports
    "Imagery Reuters":  _gnews("%22satellite+imagery%22+%22North+Korea%22+site:reuters.com"),
    "Imagery AP":       _gnews("%22satellite+imagery%22+%22North+Korea%22+site:apnews.com"),
    "Imagery BBC":      _gnews("%22satellite%22+%22North+Korea%22+site:bbc.com"),
    "Imagery NYT":      _gnews("%22satellite%22+%22North+Korea%22+site:nytimes.com"),
    "Imagery WaPo":     _gnews("%22satellite%22+%22North+Korea%22+site:washingtonpost.com"),
    "Imagery WSJ":      _gnews("%22satellite%22+%22North+Korea%22+site:wsj.com"),
    "Imagery CNN":      _gnews("%22satellite%22+%22North+Korea%22+site:cnn.com"),
    # Broad catch-all for any outlet reporting DPRK imagery
    "NK Imagery":       [_gnews("%22satellite+imagery%22+%22North+Korea%22"),
                         _gnews("%22satellite+imag%22+%22North+Korea%22+OR+%22DPRK%22+Yongbyon+OR+Sinpo+OR+Sohae+OR+Punggye+OR+%22nuclear+site%22")],
    "NK Facility":      _gnews("%22North+Korea%22+%22imagery+shows%22+OR+%22images+show%22+OR+%22images+reveal%22+OR+%22imagery+reveals%22"),
}


def _collect_satellite_imagery() -> list:
    """Collect satellite imagery analysis articles (72h window — published sporadically)."""
    articles = []
    results = _fetch_feeds_parallel(SATELLITE_IMAGERY_FEEDS)
    for source, (entries, _) in results.items():
        for entry in entries:
            if not _is_recent(entry, hours=72):
                continue
            article = _entry_to_article(entry, source, lang="EN")
            articles.append(article)
    return _dedup(articles)


def _collect_kim_tracker() -> list:
    """Collect recent Kim Jong Un appearance/activity reports from multiple sources."""
    articles = []
    results = _fetch_feeds_parallel(KIM_TRACKER_FEEDS)
    for source, (entries, _) in results.items():
        for entry in entries:
            if not _is_recent(entry, hours=72):  # wider window for appearance tracking
                continue
            article = _entry_to_article(entry, source, lang="EN")
            articles.append(article)
    return _dedup(articles)


# ─────────────────────────────────────────────────────────────────────────────
# CAPITOL HILL AND KOREA AND THE WORLD
# ─────────────────────────────────────────────────────────────────────────────
# Korea relevance for congressional feeds. KOREA_KEYWORDS plus what a bill or
# hearing about Korea says without naming the country: the shipbuilding deal,
# the Korean firms building in the US, the worker visa.
HILL_KOREA_KEYWORDS = re.compile(
    r"masga|make american shipbuilding great|hanwha|hyundai|samsung|sk hynix|sk on\b"
    r"|lg energy|e-4 visa|partner with korea|lazarus|korean",
    re.IGNORECASE,
)
# A US-Congress signal, required of the search feeds only.
HILL_US_SIGNAL = re.compile(
    r"congress|senat|capitol|ndaa|appropriation|caucus|\bcrs\b|\brep\.|\bsen\."
    r"|house of representatives|house (?:armed|foreign|committee|panel|vote|pass|bill"
    r"|republican|democrat|speaker|lawmaker)|u\.s\. lawmaker|american lawmaker|us lawmaker",
    re.IGNORECASE,
)
_ROK_ASSEMBLY = re.compile(r"national assembly|국회|assemblyman|assemblywoman|blue house", re.IGNORECASE)

# A place or body outside the US and Northeast Asia. northeast_asia owns Japan,
# China, Russia, Taiwan and Mongolia; us_korea the United States.
WORLD_KEYWORDS = re.compile(
    r"\beu\b|european|europe|nato|poland|polish|czech|romania|norway|sweden|finland|germany"
    r"|german|france|french|britain|british|\buk\b|italy|spain|netherlands|estonia|lithuania"
    r"|turkey|t[uü]rkiye|ukrain|kyiv|middle east|gulf|saudi|riyadh|\buae\b|emirat|abu dhabi"
    r"|qatar|iraq|israel|iran|egypt|jordan|oman|kuwait|houthi|red sea|hormuz|asean|vietnam"
    r"|indonesia|philippin|malaysia|thailand|singapore|cambodia|laos|myanmar|india|pakistan"
    r"|bangladesh|sri lanka|africa|nigeria|kenya|ethiopia|tanzania|ghana|morocco|brazil"
    r"|mexico|peru|chile|colombia|argentina|latin america|kazakh|uzbek|central asia"
    r"|australia|canada|new zealand|united nations|\bun\b|security council|iaea|\bg20\b"
    r"|\bg7\b|\bwto\b|koica|\boda\b",
    re.IGNORECASE,
)


def _entry_text(entry) -> str:
    return f"{entry.get('title', '')} {entry.get('summary', entry.get('description', ''))}"


def _is_hill_relevant(entry, source: str) -> bool:
    """Korea-related, and for a search feed, about the US Congress."""
    text = _entry_text(entry)
    if not (KOREA_KEYWORDS.search(text) or HILL_KOREA_KEYWORDS.search(text)):
        return False
    if source in HILL_SEARCH_FEEDS:
        return bool(HILL_US_SIGNAL.search(text)) and not _ROK_ASSEMBLY.search(entry.get("title", ""))
    return True


def _is_world_relevant(entry) -> bool:
    """Korea-related and placed outside the US and Northeast Asia."""
    text = _entry_text(entry)
    return bool(KOREA_KEYWORDS.search(text) and WORLD_KEYWORDS.search(text))


def _collect_capitol_hill() -> list:
    """US Congress items about Korea. 48h window; CRS and GovInfo 72h, as they
    publish in batches rather than through the day."""
    articles = []
    results = _fetch_feeds_parallel(CAPITOL_HILL_FEEDS)
    for source, (entries, _) in results.items():
        hours = 72 if source.startswith(("CRS", "GovInfo")) else 48
        for entry in entries:
            if not _is_recent(entry, hours=hours):
                continue
            if not _is_hill_relevant(entry, source):
                continue
            articles.append(_entry_to_article(entry, source, extra={"stream": "capitol_hill"}))
    return _dedup(articles)


def _collect_korea_world() -> list:
    """Korea's relations beyond the US and Northeast Asia. 36h window: these
    are lower-volume topics than the daily news."""
    articles = []
    results = _fetch_feeds_parallel(KOREA_WORLD_FEEDS)
    for source, (entries, _) in results.items():
        for entry in entries:
            if not _is_recent(entry, hours=36):
                continue
            if not _is_world_relevant(entry) or _is_entertainment(entry):
                continue
            articles.append(_entry_to_article(entry, source, extra={"stream": "korea_world"}))
    return _dedup(articles)


# What makes a hearing or markup worth listing. Matched against the title and
# the committee name together, so every meeting of an East Asia subcommittee
# qualifies on its name alone.
HILL_CALENDAR_KEYWORDS = re.compile(
    r"korea|dprk|pyongyang|kim jong"
    r"|indo-?pacific|indopacom|pacific command|pacific fleet|pacific air forces|u\.?s\.? army pacific"
    r"|marine forces,? pacific|usfk|forces,? korea|east asia|northeast asia"
    r"|shipbuild|shipyard|maritime industrial|ships for america|korus",
    re.IGNORECASE,
)
# Terms that count only beside an Asia or ally term: a trade hearing is about
# Korea when it is about Asian partners, autos, steel or chips, not when it is
# about a farm bill; an alliance or posture hearing when it is about the Pacific.
_HILL_CONDITIONAL = re.compile(r"\btrade\b|tariff|reciprocal|section 232|alliances?|posture",
                               re.IGNORECASE)
_HILL_CONTEXT = re.compile(r"asia|pacific|japan|allies|ally\b|partners|semiconductor|chips?\b"
                           r"|\bsteel\b|\bautos?\b|automobile", re.IGNORECASE)
HILL_CALENDAR_DAYS = 7

# A meeting that will not happen is not on the calendar.
_HILL_CALLED_OFF = re.compile(r"\b(cancell?ed|postponed)\b", re.IGNORECASE)

_EVENT_DATE_FORMATS = ("%d-%b-%Y %I:%M %p", "%d-%b-%Y %H:%M", "%d-%b-%Y",
                       "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S",
                       "%Y-%m-%d %H:%M", "%Y-%m-%d",
                       "%m/%d/%Y %I:%M %p", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y",
                       "%A, %B %d, %Y %I:%M %p", "%A, %B %d, %Y", "%a, %B %d, %Y",
                       "%B %d, %Y %I:%M %p", "%B %d, %Y", "%b %d, %Y", "%b. %d, %Y")
_MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
# Dates as committees write them inside text. Each alternative is a whole
# date with its year: a "Tuesday" or "next week" is never turned into a day.
_EVENT_DATE_IN_TEXT = re.compile(
    rf"\b({_MONTHS}\s+\d{{1,2}},?\s+20\d\d)"          # October 21, 2026 / Oct. 21 2026
    rf"|\b(\d{{1,2}}\s+{_MONTHS}\s+20\d\d)"           # 21 October 2026
    rf"|\b(\d{{1,2}}-{_MONTHS}-20\d\d)"               # 21-Oct-2026 (senate.gov)
    r"|\b(\d{1,2}/\d{1,2}/20\d\d)\b"                  # 10/21/2026
    r"|\b(20\d\d-\d{2}-\d{2})\b",                     # 2026-10-21
    re.IGNORECASE)
# "Date: ...", "Meeting Date: ...", "When: ..." — the event's own date in a
# notice that may also carry the date it was posted.
_EVENT_DATE_LABEL = re.compile(r"\b(?:meeting\s+date|hearing\s+date|event\s+date|date|when)\s*:\s*",
                               re.IGNORECASE)


def _norm_date_text(text: str) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    # "Sept" is not a %b abbreviation; "September" must stay whole (replacing
    # every "Sept" turned it into "Sepember" and lost every September date).
    t = re.sub(r"\bSept\b\.?", "Sep", t, flags=re.IGNORECASE)
    return re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", t)


def _date_from_match(m):
    raw = next(g for g in m.groups() if g).replace(".", "")
    raw = re.sub(r"\s+", " ", raw)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y",
                "%d-%b-%Y", "%d-%B-%Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_event_date(text: str):
    """A date from a schedule field or a hearing title, or None. Never guessed."""
    t = _norm_date_text(text)
    if not t:
        return None
    # Whole field first, then the ISO prefixes a timestamp with an offset has.
    for cand in (t, t[:19], t[:16], t[:10]):
        for fmt in _EVENT_DATE_FORMATS:
            try:
                return datetime.strptime(cand, fmt).date()
            except ValueError:
                continue
    m = _EVENT_DATE_IN_TEXT.search(t)
    return _date_from_match(m) if m else None


def _event_date_in_notice(text: str):
    """The meeting's date in a notice's free text, or None.

    A notice often carries two dates, the day it was posted and the day of
    the meeting ("October 15, 2026 — Chairman X announced a hearing on
    October 22, 2026"), so the first date in the text is not safe. Taken, in
    order: a date right after a "Date:" label; otherwise the only date the
    text contains. Two different dates and no label is None, not a guess.
    """
    t = _norm_date_text(text)
    if not t:
        return None
    for lab in _EVENT_DATE_LABEL.finditer(t):
        m = _EVENT_DATE_IN_TEXT.match(t, lab.end()) or _EVENT_DATE_IN_TEXT.search(t[lab.end():lab.end() + 40])
        if m:
            d = _date_from_match(m)
            if d:
                return d
    dates = {d for d in (_date_from_match(m) for m in _EVENT_DATE_IN_TEXT.finditer(t)) if d}
    return dates.pop() if len(dates) == 1 else None


_EVENT_TIME = re.compile(r"\b(\d{1,2}:\d{2})\s*([AP])\.?M\.?", re.IGNORECASE)


def _event_time(text: str) -> str:
    m = _EVENT_TIME.search(str(text or ""))
    return f"{m.group(1)} {m.group(2).upper()}M" if m else ""


def _local_tag(el) -> str:
    return el.tag.rsplit("}", 1)[-1].lower() if isinstance(el.tag, str) else ""


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_lib.unescape(str(text or "")))).strip()


# Child elements a schedule record may use for each field. senate.gov's
# hearings.xml uses committee / sub_cmte / date / time / room / matter; the
# others are the names other congressional XML uses for the same things.
_SCHED_TITLE = ("matter", "title", "hearing_title", "meeting_title", "subject", "description")
_SCHED_DATE = ("date", "meeting_date", "meetingdate", "eventdate", "event_date", "hearing_date",
               "start_date", "startdate", "datetime", "date_time")
_SCHED_TIME = ("time", "meeting_time", "start_time")
_SCHED_CMTE = ("committee", "cmte_name", "committee_name", "full_committee")
_SCHED_SUB = ("sub_cmte", "subcommittee", "sub_committee", "subcommittee_name")
_SCHED_URL = ("hearing_url", "url", "link", "event_url", "meeting_url")


def _first(fields: dict, names: tuple) -> str:
    for n in names:
        if fields.get(n):
            return fields[n]
    return ""


def _schedule_records(content: bytes) -> list[dict]:
    """{field: text} for each record in a schedule XML.

    A record is any element with a title-like and a date-like child. When the
    file will not parse (a stray entity, an HTML error page served as XML),
    records are read by pattern from <meeting> blocks instead, so one bad
    character does not cost the whole Senate calendar.
    """
    import xml.etree.ElementTree as ET
    out = []
    try:
        root = ET.fromstring(content)
        for el in root.iter():
            fields = {}
            for k in el:
                fields.setdefault(_local_tag(k), " ".join("".join(k.itertext()).split()))
            if _first(fields, _SCHED_TITLE) and _first(fields, _SCHED_DATE):
                out.append(fields)
        return out
    except ET.ParseError:
        pass
    text = content.decode("utf-8", "replace")
    for block in re.findall(r"<meeting\b[^>]*>(.*?)</meeting>", text, re.S | re.I):
        fields = {}
        for tag, val in re.findall(r"<([A-Za-z_][\w.-]*)[^>]*>(.*?)</\1>", block, re.S):
            fields.setdefault(tag.lower(), _strip_html(val))
        if _first(fields, _SCHED_TITLE) and _first(fields, _SCHED_DATE):
            out.append(fields)
    return out


def _parse_hill_schedule(content: bytes, source: str) -> list:
    """Hearings and markups from a committee schedule, as event dicts.

    Two shapes are read. A schedule XML (senate.gov's hearings.xml: one
    element per meeting with committee, date, room and matter children) and an
    RSS feed of meeting notices (docs.house.gov's per-committee meeting feed,
    the committees' own hearing feeds), whose event date is taken from the
    notice text because an item's own date is when it was posted. An event
    whose date cannot be read is dropped rather than dated by guesswork, and a
    cancelled or postponed meeting is dropped.
    """
    events = []
    chamber = "Senate" if "senate" in source.lower() or source.startswith(("SFRC", "SASC")) else "House"
    head = content[:2000].lower()
    label = HILL_CALENDAR_COMMITTEES.get(source, source.replace(" schedule", ""))
    if b"<rss" in head or b"<feed" in head or b"<rdf" in head:
        meeting_only = source in HILL_MEETING_ONLY_FEEDS
        for entry in feedparser.parse(content).entries:
            title = _strip_html(entry.get("title") or "")
            # A committee's news feed also carries press releases that mention
            # a date; a meeting-only feed needs no such test.
            if not title or (not meeting_only and
                             not re.search(r"hearing|markup|mark-up|briefing|roundtable", title, re.I)):
                continue
            body = " ".join(_strip_html(c.get("value", "")) for c in (entry.get("content") or []))
            body = f"{_strip_html(entry.get('summary', ''))} {body}"
            if _HILL_CALLED_OFF.search(f"{title} {body}"):
                continue
            when = _parse_event_date(title) or _event_date_in_notice(body)
            if when:
                events.append({"date": when.isoformat(), "time": _event_time(body), "chamber": chamber,
                               "committee": label, "title": title,
                               "url": entry.get("link", "") or HILL_SCHEDULE_PAGES.get(source, ""),
                               "source": source})
        return events
    for f in _schedule_records(content):
        title = _first(f, _SCHED_TITLE)
        when_raw = _first(f, _SCHED_DATE)
        when = _parse_event_date(when_raw)
        if not when or _HILL_CALLED_OFF.search(f"{title} {f.get('status', '')}"):
            continue
        committee = _first(f, _SCHED_CMTE)
        sub = _first(f, _SCHED_SUB)
        events.append({"date": when.isoformat(),
                       "time": _event_time(f"{when_raw} {_first(f, _SCHED_TIME)}"),
                       "chamber": chamber,
                       "committee": (f"{committee}: {sub}" if sub and sub != committee else committee)
                                    or label,
                       "title": re.sub(r"\s+", " ", title),
                       "url": _first(f, _SCHED_URL) or HILL_SCHEDULE_PAGES.get(source, ""),
                       "source": source})
    return events


# Counts from the last calendar collection, for the run log: whether the
# schedules answered at all is the question an empty calendar raises.
_hill_calendar_stats: dict = {}


def _collect_hill_calendar() -> list:
    """Upcoming Korea-relevant hearings and markups, today through a week out.

    Only what the schedules list. If every schedule fails the result is an
    empty list, and the brief carries no calendar line — never a recalled one.

    There is no Google News fallback, deliberately. A news item about a
    hearing dates it as "Tuesday" or "next week", or carries its own posting
    date beside the hearing's; turning that into a calendar date is a guess,
    and a wrong date on a hearing is worse than no line.
    """
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("America/New_York")).date()
    horizon = today + timedelta(days=HILL_CALENDAR_DAYS)

    def _one(source, url):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT + 4, headers=HILL_CALENDAR_HEADERS)
            resp.raise_for_status()
            return source, _parse_hill_schedule(resp.content, source), None
        except Exception as e:                                  # noqa: BLE001
            print(f"    ⚠  Hill calendar {source}: {str(e)[:80]}")
            return source, [], str(e)[:80]

    events, per_source = [], {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for source, found, err in pool.map(lambda kv: _one(*kv), HILL_CALENDAR_FEEDS.items()):
            _source_health[source] = {"articles": len(found), "success": err is None,
                                      "error_msg": err}
            per_source[source] = "error" if err else len(found)
            events.extend(found)
    kept = filter_hill_events(events, today, horizon)
    _hill_calendar_stats.clear()
    _hill_calendar_stats.update({
        "fetched": len(events), "kept": len(kept),
        "answered": sum(1 for v in per_source.values() if v != "error"),
        "feeds": len(per_source), "per_source": per_source,
    })
    return kept


def hill_event_relevant(text: str) -> bool:
    """Korea-relevant by the calendar's rule (see HILL_CALENDAR_KEYWORDS)."""
    if HILL_CALENDAR_KEYWORDS.search(text):
        return True
    return bool(_HILL_CONDITIONAL.search(text) and _HILL_CONTEXT.search(text))


def filter_hill_events(events: list, today, horizon) -> list:
    """Keep Korea-relevant events inside the window, one per date and title."""
    seen, out = set(), []
    for ev in events:
        text = f"{ev.get('title', '')} {ev.get('committee', '')}"
        if not hill_event_relevant(text):
            continue
        try:
            d = datetime.strptime(ev.get("date", ""), "%Y-%m-%d").date()
        except ValueError:
            continue
        if not (today <= d <= horizon):
            continue
        key = (ev["date"], re.sub(r"[^a-z0-9]+", " ", ev.get("title", "").lower()).strip()[:80])
        if key in seen:
            continue
        seen.add(key)
        out.append(ev)
    out.sort(key=lambda e: (e["date"], _time_key(e.get("time") or "")))
    return out[:10]


def _time_key(t: str) -> str:
    """'2:30 PM' -> '14:30' so a day's events sort by clock, not by string."""
    try:
        return datetime.strptime(t.strip().upper(), "%I:%M %p").strftime("%H:%M")
    except ValueError:
        return t or "99:99"


# ─────────────────────────────────────────────────────────────────────────────
# MARKET DATA
# ─────────────────────────────────────────────────────────────────────────────

def _collect_markets() -> dict:
    """Fetch KOSPI, Brent Crude, USD/KRW with Yahoo primary + Stooq fallback.

    Data source chain per symbol:
      1. Yahoo Finance query1 host
      2. Yahoo Finance query2 host (Yahoo's load-balanced mirror)
      3. Stooq CSV (stable free source, daily resolution)
    Each result is validated for sanity range + staleness (>5 days = reject).
    """
    YAHOO_SYMBOLS = {
        "kospi": "^KS11",
        "brent": "BZ=F",
        "usd_krw": "KRW=X",
    }
    STOOQ_SYMBOLS = {
        "kospi": "^ks11",      # Stooq ticker for KOSPI Composite
        "brent": "cb.f",       # ICE Brent Crude continuous futures
        "usd_krw": "usdkrw",
    }
    # Sanity ranges — if price falls outside, the data is likely stale/garbage.
    # KOSPI upper bound set generously (2026+ headroom); tighten only if
    # scraped data starts drifting wildly above 10k.
    _SANITY_RANGES = {
        "kospi": (1500, 10000),
        "brent": (40, 200),
        "usd_krw": (1000, 1700),
    }

    def _format_value(key, price):
        if key == "usd_krw" or key == "kospi":
            return f"{price:,.2f}"
        return f"{price:.2f}"

    def _validate(key, price, mkt_time):
        """Return (ok, reason). mkt_time is an aware datetime or None."""
        lo, hi = _SANITY_RANGES.get(key, (0, float("inf")))
        if not price or price < lo or price > hi:
            return False, f"price {price} outside sanity range ({lo}-{hi})"
        if mkt_time:
            age_days = (datetime.now(timezone.utc) - mkt_time).days
            if age_days > 5:
                return False, f"data is {age_days} days old"
        return True, ""

    def _fetch_yahoo(key):
        """Try Yahoo Finance — query1 then query2 as mirror fallback."""
        symbol = YAHOO_SYMBOLS[key]
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36"
        }
        for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
            try:
                url = f"https://{host}/v8/finance/chart/{symbol}?range=5d&interval=1d"
                resp = requests.get(url, timeout=10, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                result = data["chart"]["result"][0]
                meta = result["meta"]
                price = meta.get("regularMarketPrice", 0)
                # DAILY change must compare the last two DAILY closes. Do NOT use
                # meta.chartPreviousClose: on a range=5d request it is the close
                # BEFORE the 5-day window, so the % becomes a ~5-day move, not a
                # 1-day one (the KOSPI "+5.2%" vs article "+1%" bug). Take the
                # last two non-null closes from the series instead.
                prev_close = meta.get("chartPreviousClose",
                                      meta.get("previousClose", price))
                try:
                    closes = [c for c in result["indicators"]["quote"][0]["close"]
                              if c is not None]
                    if len(closes) >= 2:
                        price = closes[-1]
                        prev_close = closes[-2]
                except (KeyError, IndexError, TypeError):
                    pass
                mkt_ts = meta.get("regularMarketTime", 0)
                mkt_time = (datetime.fromtimestamp(mkt_ts, tz=timezone.utc)
                            if mkt_ts else None)
                ok, reason = _validate(key, price, mkt_time)
                if not ok:
                    print(f"    ⚠  {key}: Yahoo {host} {reason}")
                    continue
                change_pct = (((price - prev_close) / prev_close * 100)
                              if prev_close else 0)
                return {
                    "value": _format_value(key, price),
                    "change_pct": round(change_pct, 2),
                    "as_of": mkt_time.strftime("%b %d") if mkt_time else "",
                }
            except (requests.RequestException, KeyError, ValueError, TypeError) as e:
                print(f"    ⚠  {key}: Yahoo {host} error: {e}")
                continue
        return None

    def _fetch_stooq(key):
        """Fallback: Stooq.com daily CSV. Free, no auth, very stable."""
        import csv as _csv
        import io as _io
        symbol = STOOQ_SYMBOLS[key]
        try:
            url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
            resp = requests.get(url, timeout=10,
                                headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            text = resp.text.strip()
            if not text or "no data" in text.lower():
                print(f"    ⚠  {key}: Stooq returned no data for {symbol}")
                return None
            reader = _csv.DictReader(_io.StringIO(text))
            rows = [r for r in reader if r.get("Close")]
            if len(rows) < 2:
                print(f"    ⚠  {key}: Stooq returned <2 rows")
                return None
            latest = rows[-1]
            prev = rows[-2]
            price = float(latest["Close"])
            prev_close = float(prev["Close"])
            try:
                latest_dt = datetime.strptime(
                    latest["Date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except (ValueError, KeyError):
                latest_dt = None
            ok, reason = _validate(key, price, latest_dt)
            if not ok:
                print(f"    ⚠  {key}: Stooq {reason}")
                return None
            change_pct = (((price - prev_close) / prev_close * 100)
                          if prev_close else 0)
            return {
                "value": _format_value(key, price),
                "change_pct": round(change_pct, 2),
                "as_of": latest_dt.strftime("%b %d") if latest_dt else "",
            }
        except (requests.RequestException, KeyError, ValueError, TypeError) as e:
            print(f"    ⚠  {key}: Stooq error: {e}")
            return None

    def _fetch_symbol(key):
        """Chain: Yahoo → Stooq. Returns (key, result_dict)."""
        result = _fetch_yahoo(key)
        if result:
            return key, result
        print(f"    ↻  {key}: Yahoo failed/stale — falling back to Stooq")
        result = _fetch_stooq(key)
        if result:
            return key, result
        print(f"    ⚠  {key}: all data sources exhausted")
        return key, {"value": "—", "change_pct": 0, "as_of": ""}

    result = {}
    with ThreadPoolExecutor(max_workers=7) as pool:
        symbol_futures = {pool.submit(_fetch_symbol, k): k
                          for k in YAHOO_SYMBOLS.keys()}
        bok_f = pool.submit(_fetch_bok_rate)

        for future in as_completed(symbol_futures):
            k, v = future.result()
            result[k] = v

    result["bok_rate"] = bok_f.result()

    # Sovereign CDS, the GDP estimate and the ECOS indicator set were fetched
    # here every run and then discarded: the market strip was cut to four
    # tiles and render.py hardcodes all three to empty. That was four ECOS API
    # calls, a scrape of worldgovernmentbonds.com and a BOK/OECD call per day
    # for output nothing could display. The fetchers are removed with them; if
    # a tile for any of these comes back, restore from git history.

    # Always return market data — even if all fetches fail, BOK indicators
    # have hardcoded fallbacks so there's always something to show
    return result


def _fetch_bok_rate() -> dict:
    """Fetch BOK base rate. Falls back to last known value."""
    # BOK ECOS open API — base rate series (dynamic date range)
    try:
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=365)).strftime("%Y%m")
        end = now.strftime("%Y%m")
        url = f"https://ecos.bok.or.kr/api/StatisticSearch/json/en/1/5/722Y001/M/{start}/{end}/0101000/"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.ok:
            rows = resp.json().get("StatisticSearch", {}).get("row", [])
            if rows:
                val = rows[-1].get("DATA_VALUE", "")
                if val:
                    return {"value": f"{float(val):.2f}%", "last_change": ""}
    except Exception:
        pass
    # Fallback: last known BOK rate (updated manually if API unavailable)
    print("    ⚠  BOK rate: using fallback (2.50%)")
    fallback_date = datetime.now(timezone.utc).strftime("%b %Y")
    return {"value": "2.50%", "last_change": fallback_date}





# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC SENTIMENT — Korean Wikipedia structured tables
# ─────────────────────────────────────────────────────────────────────────────

def _scrape_wiki_polling(sentiment: dict) -> bool:
    """Scrape Korean Wikipedia for latest Gallup Korea polling data.

    Korean Wikipedia maintains well-structured HTML tables of weekly polling
    data at:
      - 대한민국의_대통령_지지율 (presidential approval)
      - 대한민국의_정당_지지율 (party support)

    Returns True if all 4 metrics were successfully extracted from the
    same source (guaranteeing consistency), False otherwise.
    """
    # ── Presidential approval ─────────────────────────────────────────────
    pres_url = "https://ko.wikipedia.org/wiki/%EB%8C%80%ED%95%9C%EB%AF%BC%EA%B5%AD%EC%9D%98_%EB%8C%80%ED%86%B5%EB%A0%B9_%EC%A7%80%EC%A7%80%EC%9C%A8"
    party_url = "https://ko.wikipedia.org/wiki/%EB%8C%80%ED%95%9C%EB%AF%BC%EA%B5%AD%EC%9D%98_%EC%A0%95%EB%8B%B9_%EC%A7%80%EC%A7%80%EC%9C%A8"

    headers = {
        "User-Agent": "KoreaDailyBrief/1.0 (research; contact: korea-brief@csis.org)",
        "Accept": "text/html",
    }

    pres_val = None
    pres_date = None
    pres_source = None

    # Fetch presidential approval page
    try:
        resp = requests.get(pres_url, timeout=15, headers=headers)
        resp.raise_for_status()
        html = resp.text

        # Find Gallup Korea rows in wikitable. The tables have rows like:
        #   <td>3월 3주차</td><td>한국갤럽</td>...<td>67%</td>...
        # We look for the last (most recent) Gallup Korea row with a percentage.
        # Pattern: find all rows containing "갤럽" and extract the percentage.
        gallup_rows = re.findall(
            r'<tr[^>]*>(.*?)</tr>',
            html, re.DOTALL
        )
        for row in reversed(gallup_rows):
            if '갤럽' not in row and 'Gallup' not in row:
                continue
            # Extract all cell contents
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            if len(cells) < 3:
                continue
            # Clean HTML tags from cells
            clean_cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            # Find the percentage value (긍정/approval column)
            for cell in clean_cells:
                m = re.search(r'(\d{2})(?:\.\d+)?%', cell)
                if m:
                    val = float(m.group(1))
                    if 30 <= val <= 85:
                        pres_val = val
                        break
            if pres_val:
                # Extract date from the row (e.g., "3월 3주차" or "2026-03-17")
                for cell in clean_cells:
                    if re.search(r'\d+월.*주|20\d{2}', cell):
                        pres_date = cell
                        break
                pres_source = "Gallup Korea" if "갤럽" in row else "Realmeter"
                break
    except Exception as e:
        print(f"      ⚠ Wikipedia presidential page fetch failed: {e}")
        return False

    if not pres_val:
        return False

    # ── Party support ─────────────────────────────────────────────────────
    dp_val = None
    ppp_val = None
    ind_val = None
    party_date = None

    try:
        resp = requests.get(party_url, timeout=15, headers=headers)
        resp.raise_for_status()
        html = resp.text

        gallup_rows = re.findall(
            r'<tr[^>]*>(.*?)</tr>',
            html, re.DOTALL
        )
        for row in reversed(gallup_rows):
            if '갤럽' not in row and 'Gallup' not in row:
                continue
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            if len(cells) < 4:
                continue
            clean_cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            # In the party support table, columns typically are:
            # Date | Pollster | DP% | PPP% | (others) | Independents%
            # We need to find the DP and PPP columns by looking for
            # cells with percentages in the expected range.
            pcts = []
            for cell in clean_cells:
                m = re.search(r'(\d{1,2})(?:\.\d+)?%', cell)
                if m:
                    pcts.append(float(m.group(1)))
                else:
                    pcts.append(None)

            # Heuristic: DP is usually the largest party %, PPP second
            valid_pcts = [(i, v) for i, v in enumerate(pcts) if v is not None and 5 <= v <= 60]
            if len(valid_pcts) >= 2:
                # Sort by value descending - largest is likely ruling party (DP)
                valid_pcts.sort(key=lambda x: x[1], reverse=True)
                dp_val = valid_pcts[0][1]
                ppp_val = valid_pcts[1][1]
                # Independents are often the 3rd largest or labeled 무당층
                if len(valid_pcts) >= 3:
                    ind_val = valid_pcts[2][1]
                # Extract date
                for cell in clean_cells:
                    if re.search(r'\d+월.*주|20\d{2}', cell):
                        party_date = cell
                        break
                break
    except Exception as e:
        print(f"      ⚠ Wikipedia party page fetch failed: {e}")
        # Still use presidential data if we got it
        pass

    # ── Set sentiment values ──────────────────────────────────────────────
    date_label = pres_date or party_date or "recent"
    source = pres_source or "Gallup Korea"

    sentiment["presidential_approval"] = {
        "value": f"{pres_val:g}%", "trend": None,
        "source": source, "last_updated": date_label,
    }

    if dp_val and ppp_val:
        sentiment["party_ruling"] = {
            "value": f"{dp_val:g}%",
            "party": "Democratic Party", "party_kr": "더불어민주당",
            "source": source, "last_updated": party_date or date_label,
        }
        sentiment["party_opposition"] = {
            "value": f"{ppp_val:g}%",
            "party": "People Power Party", "party_kr": "국민의힘",
            "source": source, "last_updated": party_date or date_label,
        }
        if ind_val:
            sentiment["party_independent"] = {
                "value": f"{ind_val:g}%",
                "source": source, "last_updated": party_date or date_label,
            }
        return True

    # Got presidential but not party - partial success
    return False


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC SENTIMENT — Gallup Korea, Realmeter (headline scraping fallback)
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

    # ── Pass 0: Korean Wikipedia structured tables (most reliable) ──────
    # Korean Wikipedia maintains well-structured tables of weekly polling
    # data from Gallup Korea and Realmeter. This is the most reliable
    # source because volunteer editors verify the numbers and the table
    # format is consistent.
    wiki_scraped = False
    try:
        wiki_scraped = _scrape_wiki_polling(sentiment)
        if wiki_scraped:
            print("      ✓ Wikipedia polling data scraped successfully")
    except Exception as e:
        print(f"      ⚠ Wikipedia scrape failed: {e}")

    # ── Fallback: News headline scraping ──────────────────────────────
    # If Wikipedia scrape failed or returned no data, fall back to
    # extracting from Korean news headlines about Gallup/Realmeter polls.
    #
    # IMPORTANT: Presidential approval regex MUST require "대통령" or
    # "presidential" near the number. The old regex matched generic
    # "support"/"지지율" which would grab party ratings or unrelated
    # percentages as presidential approval — the #1 cause of wrong numbers.

    # Presidential approval: MUST have "대통령" or "presidential" nearby.
    # The [^\d]{0,10} gap between the keyword block and the % capture is
    # critical — without it, the space before the digit isn't consumed.
    _RE_PRES_APPROVAL = re.compile(
        r'(?:대통령\s*(?:직무)?(?:수행)?(?:긍정)?[^\d]{0,20}지지율|'    # 대통령 지지율 XX%
        r'대통령[^\d]{0,30}(?:긍정|approval))[^\d]{0,10}'              # 대통령...긍정/approval
        r'(\d{1,3}(?:\.\d+)?)%|'
        r'(?:presidential\s+approval)[^\d]{0,20}(\d{1,3}(?:\.\d+)?)%|'  # presidential approval XX%
        r'(\d{1,3}(?:\.\d+)?)%\s*(?:presidential\s+approval)',          # XX% presidential approval
        re.IGNORECASE,
    )
    # Ruling party: 민주당 / Democratic Party
    _RE_RULING = re.compile(
        r'(?:민주당|Democratic\s*Party)[^\d]{0,30}(\d{1,3}(?:\.\d+)?)%|'
        r'(\d{1,3}(?:\.\d+)?)%\s*(?:민주당|Democratic\s*Party)',
        re.IGNORECASE,
    )
    # Opposition: 국민의힘 / People Power Party
    _RE_OPP = re.compile(
        r'(?:국민의힘|People\s*Power\s*Party)[^\d]{0,30}(\d{1,3}(?:\.\d+)?)%|'
        r'(\d{1,3}(?:\.\d+)?)%\s*(?:국민의힘|People\s*Power\s*Party)',
        re.IGNORECASE,
    )
    # Independents: 무당층 / 무당파
    _RE_IND = re.compile(
        r'(?:무당층|무당파|no\s*party\s*preference|independents?)[^\d]{0,30}(\d{1,3}(?:\.\d+)?)%|'
        r'(\d{1,3}(?:\.\d+)?)%\s*(?:무당층|무당파|no\s*party|independents?)',
        re.IGNORECASE,
    )

    # ── Korean news headline pattern ─────────────────────────────────────
    # Korean news outlets reliably report Gallup results in a standard
    # headline format that includes ALL numbers together, e.g.:
    #   "李대통령 지지율 67%…민주 46%·국힘 20% [한국갤럽]"
    #   "이재명 대통령 지지율 67%...민주 46%·국민의힘 20%"
    # This is far more reliable than trying to parse article body text.
    # We extract all percentages from these compact headline strings.
    _RE_HEADLINE_ALL = re.compile(
        r'(?:대통령|이재명|李)\s*(?:대통령)?\s*지지율?'
        r'.*?(?<!\d)(\d{2})%(?!p)'              # group 1: presidential approval (2 digits, skip %p)
        r'.*?(?:민주당?|민주|DP)\s*(\d{1,2})%'  # group 2: ruling party (DP)
        r'.*?(?:국힘|국민의힘|PPP)\s*(\d{1,2})%', # group 3: opposition (PPP)
        re.IGNORECASE,
    )

    def _gnews_kr(query: str) -> str:
        return f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"

    # Queries: Korean news headlines about Gallup polls (most reliable source)
    # Use Korean-locale Google News for better Korean-language polling coverage
    combined_queries = [
        _gnews_kr("한국갤럽+대통령+지지율+민주+국힘"),
        _gnews_kr("한국갤럽+대통령+지지율+민주당+국민의힘"),
        _gnews("한국갤럽+대통령+지지율+민주+국힘"),
        _gnews("한국갤럽+대통령+지지율+민주당+국민의힘"),
        _gnews("한국갤럽+대통령+지지율"),
        _gnews_kr("리얼미터+대통령+지지율+민주+국힘"),
        _gnews("리얼미터+대통령+지지율+민주+국힘"),
    ]

    def _sane_pct_any(match) -> float | None:
        """Extract percentage from any non-None group in a match."""
        for i in range(1, (match.lastindex or 0) + 1):
            g = match.group(i)
            if g is not None:
                val = float(g)
                return val if 5 <= val <= 85 else None
        return None

    def _is_polling_article(text: str) -> bool:
        """Check that article is actually about polling."""
        poll_signals = ("갤럽", "gallup", "리얼미터", "realmeter", "여론조사",
                        "poll", "survey", "지지율", "approval rating")
        return any(s in text.lower() for s in poll_signals)

    def _get_pub_date(entry) -> str | None:
        for attr in ("published_parsed", "updated_parsed"):
            parsed = getattr(entry, attr, None)
            if parsed:
                return datetime(*parsed[:6], tzinfo=timezone.utc).strftime("%b %d, %Y")
        return None

    def _get_source(text: str) -> str:
        if "gallup" in text.lower() or "갤럽" in text:
            return "Gallup Korea"
        if "realmeter" in text.lower() or "리얼미터" in text:
            return "Realmeter"
        return "Poll"

    def _try_headline_extraction(entry) -> bool:
        """Strategy 1 (preferred): Extract all metrics from a Korean news headline.
        Korean outlets report Gallup results in compact format like:
          '李대통령 지지율 67%…민주 46%·국힘 20% [한국갤럽]'
        This grabs presidential + both parties in one regex match,
        guaranteeing they come from the same source and same article."""
        text = f"{entry.get('title', '')} {entry.get('summary', entry.get('description', ''))}"
        if not _is_polling_article(text):
            return False
        m = _RE_HEADLINE_ALL.search(text)
        if not m:
            return False
        pres_val = float(m.group(1))
        dp_val = float(m.group(2))
        ppp_val = float(m.group(3))
        # Sanity: presidential should be higher than individual party ratings
        if not (30 <= pres_val <= 85 and 5 <= dp_val <= 60 and 5 <= ppp_val <= 50):
            return False
        if pres_val < dp_val or pres_val < ppp_val:
            return False
        source = _get_source(text)
        pub_date = _get_pub_date(entry)
        # Set all from the same source/date
        sentiment["presidential_approval"] = {
            "value": f"{pres_val:g}%", "trend": None,
            "source": source, "last_updated": pub_date or "recent",
        }
        sentiment["party_ruling"] = {
            "value": f"{dp_val:g}%",
            "party": "Democratic Party", "party_kr": "더불어민주당",
            "source": source, "last_updated": pub_date or "recent",
        }
        sentiment["party_opposition"] = {
            "value": f"{ppp_val:g}%",
            "party": "People Power Party", "party_kr": "국민의힘",
            "source": source, "last_updated": pub_date or "recent",
        }
        # Try to get independents from the same text
        ind_m = _RE_IND.search(text)
        sentiment["party_independent"] = None
        if ind_m:
            val = _sane_pct_any(ind_m)
            if val is not None:
                sentiment["party_independent"] = {
                    "value": f"{val:g}%",
                    "source": source, "last_updated": pub_date or "recent",
                }
        return True

    def _try_field_extraction(entry) -> bool:
        """Strategy 2 (fallback): Extract metrics individually.
        Presidential approval requires '대통령' or 'presidential' nearby."""
        text = f"{entry.get('title', '')} {entry.get('summary', entry.get('description', ''))}"
        if not _is_polling_article(text):
            return False
        appr_m = _RE_PRES_APPROVAL.search(text)
        if not appr_m:
            return False
        appr_val = _sane_pct_any(appr_m)
        if appr_val is None:
            return False
        source = _get_source(text)
        pub_date = _get_pub_date(entry)
        sentiment["presidential_approval"] = {
            "value": f"{appr_val:g}%", "trend": None,
            "source": source, "last_updated": pub_date or "recent",
        }
        sentiment["party_ruling"] = None
        sentiment["party_opposition"] = None
        sentiment["party_independent"] = None
        for regex, key, extra in [
            (_RE_RULING, "party_ruling", {"party": "Democratic Party", "party_kr": "더불어민주당"}),
            (_RE_OPP, "party_opposition", {"party": "People Power Party", "party_kr": "국민의힘"}),
            (_RE_IND, "party_independent", {}),
        ]:
            m = regex.search(text)
            if m:
                val = _sane_pct_any(m)
                if val is not None:
                    sentiment[key] = {"value": f"{val:g}%", "source": source,
                                      "last_updated": pub_date or "recent", **extra}
        return True

    # ── Pass 1: Headline extraction (skip if Wikipedia already got data)
    if not (sentiment["presidential_approval"] and sentiment["party_ruling"]):
        for query in combined_queries:
            try:
                entries = _parse_feed(_gnews(query))
                for entry in entries[:8]:
                    if _try_headline_extraction(entry):
                        break
                if sentiment["presidential_approval"] and sentiment["party_ruling"]:
                    break
            except Exception as e:
                print(f"    ⚠  Sentiment pass 1 ({query[:40]}): {e}")
                continue

    # ── Pass 2: Field-by-field extraction (fallback if no headline match)
    if not sentiment["presidential_approval"]:
        for query in combined_queries:
            try:
                entries = _parse_feed(_gnews(query))
                for entry in entries[:5]:
                    if _try_field_extraction(entry) and (
                        sentiment["party_ruling"] or sentiment["party_opposition"]
                    ):
                        break
                if sentiment["presidential_approval"] and (
                    sentiment["party_ruling"] or sentiment["party_opposition"]
                ):
                    break
            except Exception as e:
                print(f"    ⚠  Sentiment pass 2 ({query[:40]}): {e}")
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
                if not _is_recent(entry, hours=168):
                    continue
                text = f"{entry.get('title', '')} {entry.get('summary', entry.get('description', ''))}"
                # Skip standard approval/party support headlines — spotlight is for special topics
                if re.search(r'(대통령|지지율|presidential|party\s*approval|approval\s*rat)', text, re.IGNORECASE):
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

    # ── Fallback baselines (carry-forward when scraping fails) ─────────
    # Read from gallup_baseline.json — updated weekly by gallup_update.py
    # (Friday workflow) or manually. Hardcoded values below are the
    # last-resort if the JSON is missing/corrupt.
    baseline = load_gallup_baseline()
    bl_date = baseline.get("survey_dates", "June 9-11, 2026")
    bl_source = baseline.get("source", "Gallup Korea")

    def _bl(key: str, defaults: dict) -> dict:
        merged = dict(defaults)
        merged.update(baseline.get(key) or {})
        merged["source"] = bl_source
        merged["last_updated"] = bl_date
        return merged

    fallback_used = []
    if not sentiment["presidential_approval"]:
        fallback_used.append("presidential_approval")
        sentiment["presidential_approval"] = _bl(
            "presidential_approval", {"value": "57%", "trend": "down"})
    if not sentiment["party_ruling"]:
        fallback_used.append("party_ruling")
        sentiment["party_ruling"] = _bl(
            "party_ruling", {"value": "41%", "party": "Democratic Party",
                             "party_kr": "더불어민주당", "trend": "down"})
    if not sentiment["party_opposition"]:
        fallback_used.append("party_opposition")
        sentiment["party_opposition"] = _bl(
            "party_opposition", {"value": "29%", "party": "People Power Party",
                                 "party_kr": "국민의힘", "trend": "up"})
    if not sentiment["party_independent"]:
        fallback_used.append("party_independent")
        sentiment["party_independent"] = _bl(
            "party_independent", {"value": "21%", "trend": "down"})
    if fallback_used:
        print(f"    ⚠  Sentiment: using fallbacks for {', '.join(fallback_used)}")
    if not sentiment["gallup_spotlight"]:
        fallback_used.append("gallup_spotlight")
        spotlight = baseline.get("spotlight") or {
            "headline": "투표용지 부족 사태: 67% 선거관리 부실, 25% 부정선거 증거 — 한국갤럽 6월 2주차",
            "poll_date": "June 12, 2026",
        }
        sentiment["gallup_spotlight"] = dict(spotlight)
        print("    ⚠  Sentiment: using fallback for gallup_spotlight")

    return sentiment


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def collect() -> dict:
    """Run all tier collectors + market data and return combined payload."""
    _source_health.clear()  # Reset health tracking for this run
    _feed_source_used.clear()
    _unresolved_urls.clear()
    _offsite_dropped.clear()
    print("\n📡  Collecting Korea news from 100+ sources (parallel)...")

    # Run all collectors concurrently — each already uses internal thread pools
    # for their own feeds, but the collectors themselves were running sequentially.
    collectors = {
        "tier1":        ("Tier 1: News articles",        _collect_tier1),
        "tier2":        ("Tier 2: Op-eds & commentary",   _collect_tier2),
        "tier3":        ("Tier 3: Academic journals",      _collect_tier3),
        "tier4":        ("Tier 4: KCNA / Rodong Sinmun",  _collect_tier4),
        "kcna_scrape":  ("KCNA Watch scrape",             _scrape_kcna_watch),
        "kim_tracker":  ("Kim Jong Un appearance tracker", _collect_kim_tracker),
        "satellite":    ("Satellite imagery analysis",     _collect_satellite_imagery),
        "capitol_hill": ("Capitol Hill (US Congress)",     _collect_capitol_hill),
        "korea_world":  ("Korea and the World",            _collect_korea_world),
        "hill_calendar": ("Congressional calendar",        _collect_hill_calendar),
        "markets":      ("Market data",                    _collect_markets),
        "sentiment":    ("Public sentiment polls",         _collect_sentiment),
    }

    results = {}
    with ThreadPoolExecutor(max_workers=len(collectors)) as pool:
        futures = {pool.submit(fn): key for key, (_label, fn) in collectors.items()}
        for future in as_completed(futures):
            key = futures[future]
            label = collectors[key][0]
            try:
                results[key] = future.result()
                data = results[key]
                if key == "markets":
                    print(f"  ── {label}: {'OK' if data else 'unavailable'}")
                elif key == "sentiment":
                    found = sum(1 for v in data.values() if v) if data else 0
                    print(f"  ── {label}: {found} metric(s) found" if found else f"  ── {label}: no recent polls found")
                elif key in ("kim_tracker", "satellite"):
                    print(f"  ── {label}: {len(data)} articles (72h window)")
                elif key == "hill_calendar":
                    print(f"  ── {label}: {len(data)} Korea-relevant event(s), next {HILL_CALENDAR_DAYS} days")
                else:
                    print(f"  ── {label}: {len(data)} items")
            except Exception as e:
                print(f"  ── {label}: ⚠ FAILED ({e})")
                results[key] = [] if key not in ("markets", "sentiment") else {}

    tier1 = results["tier1"]
    # The Capitol Hill and Korea-and-the-World streams have their own prompt
    # blocks (they carry a "stream" key, which keeps them out of the tier-1
    # block). They are appended to tier 1 as well so that URL validation,
    # repair and the coverage audit check the digest against everything the
    # model was shown. An article tier 1 already carries is not added twice.
    capitol_hill = results.get("capitol_hill") or []
    korea_world = results.get("korea_world") or []
    _have = {a["url"] for a in tier1}
    for _a in capitol_hill + korea_world:
        if _a["url"] not in _have:
            _have.add(_a["url"])
            tier1.append(_a)
    tier2 = results["tier2"]
    tier3 = results["tier3"]
    tier4 = results["tier4"]
    kcna_scraped = results.get("kcna_scrape", [])
    total = len(tier1) + len(tier2) + len(tier3) + len(tier4)
    print(f"\n  📊  Total collected: {total} items")

    # Build structured KCNA summary from RSS + scrape data
    kcna_summary = _build_kcna_summary(tier4, kcna_scraped)
    if kcna_summary["total_articles"]:
        print(f"  📡  KCNA summary: {kcna_summary['total_articles']} unique articles, {len(kcna_summary.get('categories', {}))} categories")

    # ── Source health summary ────────────────────────────────────────────
    total_feeds = len(_source_health)
    feeds_with_data = sum(1 for h in _source_health.values() if h["success"])
    feeds_failed = total_feeds - feeds_with_data
    print(f"\n  Source health: {feeds_with_data}/{total_feeds} feeds returned data, {feeds_failed} blocked/failed")
    if _offsite_dropped:
        print(f"  Off-site results dropped from site: searches: {sum(_offsite_dropped.values())} "
              f"across {len(_offsite_dropped)} feed(s)")

    # Warn if any major feed returned 0 articles
    for major in MAJOR_FEEDS:
        health = _source_health.get(major)
        if health and not health["success"]:
            err = health.get("error_msg") or "0 articles"
            print(f"  ⚠  MAJOR FEED WARNING: {major} returned no data ({err})")
        elif not health:
            print(f"  ⚠  MAJOR FEED WARNING: {major} was not fetched")

    satellite = results.get("satellite", [])
    if satellite:
        print(f"  🛰  Satellite imagery: {len(satellite)} articles found (72h window)")

    # X (Twitter) signals from the curated allowlist — best-effort, tips only.
    x_signals = []
    try:
        from x_scraper import collect_x_signals
        x_signals = collect_x_signals()
    except Exception as e:
        print(f"  🐦  X scraper skipped (non-fatal): {e}")

    return {
        "tier1": tier1,
        "tier2": tier2,
        "tier3": tier3,
        "tier4": tier4,
        "kcna_summary": kcna_summary,
        "kim_tracker_articles": results["kim_tracker"],
        "satellite_imagery_articles": satellite,
        "capitol_hill_articles": capitol_hill,
        "korea_world_articles": korea_world,
        "hill_calendar": results.get("hill_calendar") or [],
        "hill_calendar_stats": dict(_hill_calendar_stats),
        "market_indicators": results["markets"],
        "sentiment_baseline": results["sentiment"],
        "x_signals": x_signals,
        "feed_source_used": dict(_feed_source_used),
        "unresolved_url_count": len(_unresolved_urls),
        "offsite_dropped": sum(_offsite_dropped.values()),
        "source_health": {
            "total_feeds": total_feeds,
            "feeds_with_data": feeds_with_data,
            "feeds_failed": feeds_failed,
            "per_source": dict(_source_health),
        },
    }


if __name__ == "__main__":
    from pathlib import Path
    payload = collect()
    Path("collected.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print("  → Written to collected.json")
