"""Checks for link quality (links.py and the collector/render code it serves).

The audit behind these: of 502 links in ten issues, 26% were Google News
redirects, 25 were not in any corpus, 32 repeated a URL already used in the
issue, ROK Government cards said "Primary" over news links, and "Read online"
opened whatever issue was latest. No network: Google News decoding is tested
against recorded-shape fixtures in fixtures/gnews/.

Run: python test_links.py   (also run from test_sources.py)
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import feedparser

import collect
import links

FIX = Path(__file__).resolve().parent / "fixtures" / "gnews"
NEW_ID = ("CBMiR0FVX3lxTE5VVkdKekwxSVBhVVhaVFRvOUZHUGRxOC1RSHVoTGViNzJ6bnVKMk1y"
          "NVI0X0JUbFBESUhGV2dnc3hMaUxtVEow")
GN_URL = f"https://news.google.com/rss/articles/{NEW_ID}?oc=5"


# ── 1. The real publisher ────────────────────────────────────────────────

def check_publisher_is_read() -> list[str]:
    problems = []
    feed_url = collect._gnews("KCNA+site:reuters.com")
    entries = feedparser.parse((FIX / "search_rss.xml").read_bytes()).entries
    kept = collect._keep_site_matches(entries, feed_url)
    if len(kept) != 1:
        problems.append(f"site filter kept {len(kept)} of 2 items; the Straits Times one is off-site")
    a = collect._entry_to_article(entries[0], "KCNA (Reuters)", lang="KO")
    if a.get("source") != "Reuters" or a.get("feed") != "KCNA (Reuters)":
        problems.append(f"source/feed are {a.get('source')!r}/{a.get('feed')!r}, want Reuters/KCNA (Reuters)")
    if a.get("title", "").endswith("- Reuters"):
        problems.append("the ' - Reuters' suffix was left on the title")
    if a.get("publisher_home") != "https://www.reuters.com":
        problems.append("publisher_home not stored")
    # A native feed carries no <source>: the feed name is the label.
    nat = collect._entry_to_article(feedparser.FeedParserDict(title="x", link="https://en.yna.co.kr/a"),
                                    "Yonhap English")
    if nat.get("source") != "Yonhap English" or "publisher" in nat:
        problems.append("a native item without <source> lost its feed label")
    # The model is shown the publisher.
    import digest
    p = digest.build_user_prompt({"tier1": [a]}, "Monday, October 19, 2026")
    if '"source": "Reuters"' not in p:
        problems.append("the prompt does not show the model the publisher")
    # Ranking still keys on the feed: a KCNA wire item from a prestige outlet.
    if digest._prompt_band({"feed": "WSJ Korea", "source": "The Wall Street Journal"}) != 1:
        problems.append("a WSJ item fell out of the mandatory band once source became the publisher")
    return problems


def check_site_binds() -> list[str]:
    from urllib.parse import parse_qs, urlparse
    q = lambda u: parse_qs(urlparse(u).query)["q"][0]
    problems = []
    cases = {
        "Korea+OR+DPRK+site:crsreports.congress.gov": "(Korea OR DPRK) site:crsreports.congress.gov",
        "%22North+Korea%22+OR+%22South+Korea%22+site:congress.gov":
            '("North Korea" OR "South Korea") site:congress.gov',
        "Korea+site:wsj.com": "Korea site:wsj.com",
        "site:chosun.com+-english": "-english site:chosun.com",
        "%EC%A0%84%EC%9E%90%EA%B3%B5%EC%8B%9C+OR+site:dart.fss.or.kr": "전자공시 OR site:dart.fss.or.kr",
    }
    for raw, want in cases.items():
        got = q(collect._gnews(raw))
        if got != want:
            problems.append(f"query {raw!r} built as {got!r}, want {want!r}")
    if links.site_targets(collect._gnews("Korea+OR+DPRK+site:x.org")) != ["x.org"]:
        problems.append("site target not read from a search URL")
    if links.site_targets(collect._gnews("%EC%A0%84%EC%9E%90%EA%B3%B5%EC%8B%9C+OR+site:dart.fss.or.kr")):
        problems.append("an OR'd site: (optional by design) is being enforced")
    if not links.publisher_matches_site("https://www.yna.co.kr", ["en.yna.co.kr"]):
        problems.append("en.yna.co.kr and yna.co.kr are one publisher")
    if links.publisher_matches_site("https://pmnewsnigeria.com", ["crsreports.congress.gov"]):
        problems.append("PM News Nigeria passed a CRS site: filter")
    return problems


# ── 2. Google News decoding (fixtures) ───────────────────────────────────

class _Resp:
    def __init__(self, status, text):
        self.status_code, self.text = status, text


class _FakeSession:
    def __init__(self, page=None, batch=None):
        self.page = page if page is not None else (FIX / "article_page.html").read_text()
        self.batch = batch if batch is not None else (FIX / "batchexecute_response.txt").read_text()
        self.posts = []

    def get(self, url, **kw):
        return _Resp(200, self.page)

    def post(self, url, data=None, **kw):
        self.posts.append((url, data))
        return _Resp(200, self.batch)


def check_gnews_decoding() -> list[str]:
    problems = []
    want = "https://www.washingtonpost.com/world/2026/10/18/north-korea-torpedo-test-ai/"
    if links.decode_legacy(NEW_ID):
        problems.append("an encrypted AU_yqL id 'decoded' by the legacy path")
    sig = links.parse_signature((FIX / "article_page.html").read_text())
    if sig != ("AZ5r3eQx8_Fh1fMkeM2tYV7c9JpL0Zq3", "1760774400"):
        problems.append(f"signature/timestamp parsed as {sig}")
    if links.parse_batch_response((FIX / "batchexecute_response.txt").read_text()) != want:
        problems.append("batchexecute reply not parsed")
    s = _FakeSession()
    got = links.decode_gnews(GN_URL, session=s)
    if got != want:
        problems.append(f"decode_gnews returned {got!r}")
    elif not s.posts or "Fbv4je" not in __import__("urllib.parse").parse.unquote(s.posts[0][1]) \
            or NEW_ID not in __import__("urllib.parse").parse.unquote(s.posts[0][1]):
        problems.append("the batchexecute request does not carry the rpc id and article id")
    # Defensive: a consent wall, an empty reply, garbage — all give ''.
    for page, batch in (("<html>consent</html>", ""), (None, ")]}'\n\n[]"), (None, "garbage")):
        if links.decode_gnews(GN_URL, session=_FakeSession(page, batch)):
            problems.append("a failed decode returned a URL")
    # Legacy ids still decode with no network at all.
    import base64
    legacy_id = base64.urlsafe_b64encode(b"\x08\x13\x22\x2ehttps://www.koreaherald.com/article/123\xd2\x01\x00").decode().rstrip("=")
    if links.decode_legacy(legacy_id) != "https://www.koreaherald.com/article/123":
        problems.append("legacy base64 id no longer decodes")
    # Digest pass: replaces, caches, and keeps the link on failure.
    with tempfile.TemporaryDirectory() as td:
        cache = os.path.join(td, "gnews_cache.json")
        d = {"top_stories": [{"headline": "h", "url": GN_URL, "source": "Washington Post"}],
             "kcna_delta": {"top_articles": [{"headline": "k",
                                              "url": "https://news.google.com/rss/articles/CBMiFAILS?oc=5"}]}}
        calls = []

        def fake(u, session=None):
            calls.append(u)
            return want if NEW_ID in u else ""
        links.decode_digest_links(d, cache_path=cache, decoder=fake)
        if d["top_stories"][0]["url"] != want:
            problems.append("a decoded link was not written back")
        if d["kcna_delta"]["top_articles"][0]["url"] != "https://news.google.com/rss/articles/CBMiFAILS?oc=5":
            problems.append("a link that failed to decode was dropped instead of kept")
        d2 = {"top_stories": [{"headline": "h", "url": GN_URL}]}
        calls.clear()
        links.decode_digest_links(d2, cache_path=cache, decoder=fake)
        if calls or d2["top_stories"][0]["url"] != want:
            problems.append("the decode cache was not used on the second run")
        # Never blocks: a hanging decoder is cut off by the deadline.
        import time as _t
        d3 = {"top_stories": [{"headline": "h", "url": "https://news.google.com/rss/articles/CBMiSLOW"}]}
        t0 = _t.time()
        links.decode_digest_links(d3, cache_path=cache, deadline=1.0,
                                  decoder=lambda u, session=None: _t.sleep(5) or "")
        if _t.time() - t0 > 3:
            problems.append("decoding did not respect its deadline")
    return problems


# ── 4. Repair and HEAD check cover every URL field ────────────────────────

def _payload():
    return {
        "tier1": [
            {"url": "https://en.yna.co.kr/view/A1", "title": "Korean won strengthens on robust exports",
             "source": "Yonhap News Agency"},
            {"url": "https://www.nknews.org/2026/10/torpedo/", "title": "North Korea tests AI torpedo guided underwater",
             "source": "NK News"},
            {"url": "https://www.mofa.go.kr/eng/brd/m_5676/view.do?seq=1", "title": "FM Cho meets US envoy on alliance",
             "source": "ROK MOFA"},
            {"url": "https://en.yna.co.kr/view/A2", "title": "USTR Section 301 investigation hearing on Korea set",
             "source": "Yonhap News Agency"},
        ],
        "x_signals": [{"url": "https://x.com/FMChoHyun/status/1", "text": "post"}],
    }


def check_repair_covers_every_field() -> list[str]:
    problems = []
    d = {
        "kcna_delta": {"top_articles": [
            {"headline": "North Korea tests AI torpedo guided underwater, KCNA", "url": "https://fake.example/k"},
            {"headline": "Unknown", "url": "https://fake.example/k2"}]},
        "imagery_report": {"source_links": [{"label": "38 North", "url": "https://fake.example/img"}]},
        "rok_government": [{"action": "FM Cho meets US envoy", "url": "https://www.mofa.go.kr/eng/brd/m_5676/view.do?seq=1",
                            "secondary_url": "https://fake.example/sec", "source_label": "MOFA"}],
        "official_x_posts": [{"who": "FM", "url": "https://x.com/FMChoHyun/status/1"}],
        "us_korea_deals": {"trade_policy": [{"item": "Section 301", "url": "https://fake.example/t"}],
                           "deals": [{"title": "deal", "url": "https://fake.example/d"}]},
        "capitol_hill": [{"headline": "x", "url": "https://fake.example/c"}],
    }
    links.repair_all(d, _payload())
    if d["kcna_delta"]["top_articles"][0]["url"] != "https://www.nknews.org/2026/10/torpedo/":
        problems.append("a KCNA top article was not repaired by headline")
    if d["kcna_delta"]["top_articles"][1]["url"]:
        problems.append("an unrepairable KCNA link shipped")
    for path, v in (("imagery source_links", d["imagery_report"]["source_links"][0]["url"]),
                    ("rok_government secondary_url", d["rok_government"][0]["secondary_url"]),
                    ("trade_policy", d["us_korea_deals"]["trade_policy"][0]["url"]),
                    ("deals", d["us_korea_deals"]["deals"][0]["url"]),
                    ("capitol_hill", d["capitol_hill"][0]["url"])):
        if v:
            problems.append(f"a fabricated {path} link shipped")
    if d["official_x_posts"][0]["url"] != "https://x.com/FMChoHyun/status/1":
        problems.append("an X post from the signals was unlinked")
    if d["rok_government"][0]["url"] != "https://www.mofa.go.kr/eng/brd/m_5676/view.do?seq=1":
        problems.append("a corpus link was removed")
    # Floor protection keeps the text, never the invented link.
    import run
    dd = {"top_stories": [{"headline": "Totally invented story about nothing at all", "body": "b" * 40,
                           "url": "https://fake.example/1"},
                          {"headline": "Another invented headline with words", "body": "b" * 40,
                           "url": "https://fake.example/2"}]}
    run._repair_digest_urls(dd, _payload())
    if len(dd["top_stories"]) != 2 or any(s.get("url") for s in dd["top_stories"]):
        problems.append("floor-protected items kept their fabricated links")
    # HEAD: a confirmed 404 loses its link everywhere; a 403 paywall does not.
    d = {"top_stories": [{"headline": "a", "url": "https://dead.example/x"}],
         "kcna_delta": {"top_articles": [{"headline": "b", "url": "https://paywall.example/y"}]},
         "rok_government": [{"action": "c", "secondary_url": "https://dead.example/x"}]}
    verdict = {"https://dead.example/x": ("dead", "HTTP 404"), "https://paywall.example/y": ("ok", "403")}
    links.head_check(d, checker=lambda u: verdict[u])
    if d["top_stories"][0]["url"] or d["rok_government"][0]["secondary_url"]:
        problems.append("a 404 link survived the HEAD check")
    if not d["kcna_delta"]["top_articles"][0]["url"]:
        problems.append("a paywalled (403) link was removed")
    if links.check_url(GN_URL)[0] == "ok":
        problems.append("a Google News redirect counted as a verified link")
    return problems


# ── 5. Dedup ─────────────────────────────────────────────────────────────

def check_dedup_links() -> list[str]:
    problems = []
    u = "https://en.yna.co.kr/view/A1"
    d = {"top_stories": [{"headline": "a", "url": u,
                          "source_links": [{"label": "Yonhap", "url": u},
                                           {"label": "NK News", "url": "https://www.nknews.org/x"}]}],
         "kcna_delta": {"top_articles": [{"headline": "b", "url": u + "?utm_source=rss"}]},
         "rok_government": [{"action": "c", "url": "https://www.mofa.go.kr/a",
                             "secondary_url": "https://www.mofa.go.kr/a"}],
         "social_statements": [{"who": "d", "url": "https://www.nknews.org/x"}]}
    links.dedup_links(d)
    if d["top_stories"][0]["url"] != u or d["top_stories"][0]["source_links"][0]["url"] != u:
        problems.append("a top story's own outlet list was treated as a duplicate")
    if d["kcna_delta"]["top_articles"][0]["url"]:
        problems.append("a repeat (differing only by utm) kept its link")
    if d["rok_government"][0]["secondary_url"]:
        problems.append("a secondary link identical to the primary was kept")
    if d["social_statements"][0]["url"]:
        problems.append("a later repeat of a top story's outlet link kept its link")
    if d["kcna_delta"]["top_articles"][0].get("headline") != "b":
        problems.append("dedup removed the item, not just the link")
    return problems


# ── 6. Primary label; 7. multi-outlet; 9. trade ──────────────────────────

def _render(d: dict) -> str:
    import render
    base = {"digest_date": "Sunday, October 18, 2026", "re_line": "x",
            "web_url": "https://example.github.io/Daily-Korea-Digest/latest.html",
            "date_slug": "2026-10-18"}
    base.update(d)
    return render.render(base)


def check_primary_label() -> list[str]:
    problems = []
    for u, want in (("https://www.mofa.go.kr/eng/view.do?seq=1", True),
                    ("https://www.jcs.mil.kr/bbs/1", True),
                    ("https://www.korea.kr/news/policyNewsView.do?newsId=1", True),
                    ("https://www.bok.or.kr/eng/bbs/1", True),
                    ("https://en.yna.co.kr/view/AEN1", False),
                    ("https://www.koreaherald.com/article/1", False)):
        if links.is_primary_url(u) != want:
            problems.append(f"is_primary_url({u}) != {want}")
    html = _render({"rok_government": [
        {"ministry": "Ministry of Foreign Affairs", "action": "FM meets envoy", "detail": "d" * 30,
         "url": "https://www.mofa.go.kr/eng/view.do?seq=1", "source_label": "MOFA"},
        {"ministry": "Ministry of National Defense", "action": "MND statement", "detail": "d" * 30,
         "url": "https://en.yna.co.kr/view/AEN1", "source_label": "MND"}]})
    if html.count(">Primary</span>") != 1:
        problems.append(f"'Primary' shown {html.count('>Primary</span>')} times for one government link")
    if ">Yonhap</a>" not in html:
        problems.append("a news link on a ROK Government card is not labelled with its publisher")
    return problems


def check_multi_outlet_and_trade() -> list[str]:
    problems = []
    payload = {"tier1": [
        {"url": "https://www.nknews.org/2026/10/torpedo/", "title": "North Korea tests AI-guided torpedo underwater",
         "source": "NK News"},
        {"url": "https://en.yna.co.kr/view/A9", "title": "N. Korea tests AI-guided torpedo underwater: KCNA",
         "source": "Yonhap News Agency"},
        {"url": "https://en.yna.co.kr/view/A1", "title": "Korean won strengthens on robust exports",
         "source": "Yonhap News Agency"},
        {"url": "https://en.yna.co.kr/view/A2", "title": "USTR Section 301 investigation hearing on Korea set",
         "source": "Yonhap News Agency"}]}
    d = {"top_stories": [{"headline": "North Korea tests AI-guided torpedo underwater", "body": "b",
                          "url": "https://www.nknews.org/2026/10/torpedo/",
                          "src_line": "NK News / Reuters / Yonhap — Oct 18, 2026"}],
         "us_korea_deals": {"trade_policy": [
             {"item": "Section 301 Investigation — South Korea", "agency": "USTR", "detail": "Launched Mar 11",
              "url": "https://en.yna.co.kr/view/A1"},
             {"item": "Section 301 investigation", "agency": "USTR", "detail": "hearing set",
              "url": "https://en.yna.co.kr/view/A2"}]}}
    links.finalize(d, payload, network=False)
    s = d["top_stories"][0]
    if s["src_line"] != "NK News / Yonhap — Oct 18, 2026":
        problems.append(f"src_line is {s['src_line']!r}; Reuters has no link and must not be named")
    if [l["url"] for l in s.get("source_links", [])] != ["https://www.nknews.org/2026/10/torpedo/",
                                                          "https://en.yna.co.kr/view/A9"]:
        problems.append(f"source_links are {s.get('source_links')}")
    html = _render({"top_stories": [s]})
    if 'href="https://en.yna.co.kr/view/A9"' not in html:
        problems.append("the second outlet is not rendered as a link")
    tp = d["us_korea_deals"]["trade_policy"]
    if tp[0]["url"]:
        problems.append("a trade measure still links to an unrelated currency story")
    if tp[1]["url"] != "https://en.yna.co.kr/view/A2":
        problems.append("a trade measure lost a link to a story about it")
    # Anchor text names the outlet the link opens.
    d = {"business_economy": [{"headline": "h", "url": "https://en.yna.co.kr/view/A1", "source": "Reuters Korea"}],
         "kcna_delta": {"top_articles": [{"headline": "k", "url": GN_URL, "source": "KCNA (Reuters)"}]}}
    links.fix_labels(d, links.corpus_index(payload))
    if d["business_economy"][0]["source"] != "Yonhap":
        problems.append(f"'Reuters Korea' on a Yonhap link became {d['business_economy'][0]['source']!r}")
    if d["kcna_delta"]["top_articles"][0]["source"] != "Reuters":
        problems.append("a feed name ('KCNA (Reuters)') was left as the label")
    return problems


def check_label_rules() -> list[str]:
    """The three labels the 21 October 2026 link pass made worse.

    'Asian Security' -> 'tandfonline.com', 'Chosun Ilbo' -> '조선일보' and
    'MOF' -> 'X'. A journal keeps its name, a Korean publisher is named in
    English, and a post on X names its account.
    """
    problems = []
    gn = "https://news.google.com/rss/articles/CBMiChosunTestId?oc=5"
    post = "https://x.com/mof_minister/status/1849000000000000000"
    payload = {
        "tier1": [{"url": gn, "title": "Seoul weighs tariff talks", "source": "조선일보",
                   "publisher": "조선일보"}],
        "tier3": [{"url": "https://www.tandfonline.com/doi/full/10.1080/14799855.2026.1",
                   "title": "Alliance management on the peninsula", "source": "Asian Security"}],
        "x_signals": [{"url": post, "handle": "mof_minister", "name": "MOF Minister",
                       "text": "Port investment package"}],
    }
    d = {
        "academic_today": [{"headline": "Alliance management", "source": "Asian Security",
                            "url": "https://www.tandfonline.com/doi/full/10.1080/14799855.2026.1"}],
        # A journal on a platform outside the academic section keeps its name too.
        "also_today": [{"headline": "Survival essay", "source": "Survival",
                        "url": "https://www.tandfonline.com/doi/full/10.1080/00396338.2026.2"}],
        "korea_world": [{"headline": "Seoul weighs tariff talks", "source": "Chosun Ilbo", "url": gn},
                        {"headline": "Seoul weighs tariff talks", "source": "Reuters", "url": gn}],
        "rok_government": [{"headline": "Port package", "source_label": "MOF", "url": post},
                           {"headline": "Unknown post", "source_label": "X",
                            "url": "https://x.com/SomeAgency/status/1"}],
    }
    links.fix_labels(d, links.corpus_index(payload))
    if d["academic_today"][0]["source"] != "Asian Security":
        problems.append(f"journal name became {d['academic_today'][0]['source']!r}")
    if d["also_today"][0]["source"] != "Survival":
        problems.append(f"journal on tandfonline outside academic became {d['also_today'][0]['source']!r}")
    if d["korea_world"][0]["source"] != "Chosun Ilbo":
        problems.append(f"'Chosun Ilbo' became {d['korea_world'][0]['source']!r}")
    if d["korea_world"][1]["source"] != "Chosun Ilbo":
        problems.append(f"a wrong label on a Chosun link became {d['korea_world'][1]['source']!r}, "
                        f"not the English name")
    if d["rok_government"][0]["source_label"] != "MOF Minister on X":
        problems.append(f"'MOF' on an X post became {d['rok_government'][0]['source_label']!r}")
    if d["rok_government"][1]["source_label"] != "@SomeAgency on X":
        problems.append(f"bare 'X' became {d['rok_government'][1]['source_label']!r}")
    if links.publisher_name(gn, "연합뉴스") != "Yonhap":
        problems.append("a Korean publisher name is not given in English")
    # A label that already says it is idempotent.
    d2 = {"rok_government": [{"headline": "p", "source_label": "MOF Minister on X", "url": post}]}
    if links.fix_labels(d2, links.corpus_index(payload)):
        problems.append("a correct '... on X' label was rewritten")
    return problems


# ── 8. Self-links ─────────────────────────────────────────────────────────

def check_self_links_are_dated() -> list[str]:
    import re
    html = _render({})
    hrefs = re.findall(r'<a class="pill" href="([^"]+)"[^>]*>(Read online|Download PDF)</a>', html)
    problems = []
    if not hrefs:
        return ["no Read online / Download PDF links rendered"]
    for href, label in hrefs:
        ext = "html" if label == "Read online" else "pdf"
        if not href.endswith(f"/digest_2026-10-18.{ext}"):
            problems.append(f"{label} points at {href}, not that day's digest_2026-10-18.{ext}")
    # Without run.py's date_slug, the masthead date is used.
    import render
    if render._issue_file({"digest_date": "Sunday, October 18, 2026"}, "https://x/", "pdf") \
            != "https://x/digest_2026-10-18.pdf":
        problems.append("the issue date is not recovered from digest_date")
    return problems


CHECKS = [
    ("links: publisher read, labelled, shown to the model", check_publisher_is_read),
    ("links: site: binds and off-site results are dropped", check_site_binds),
    ("links: Google News decoding (fixtures)", check_gnews_decoding),
    ("links: repair and HEAD check cover every URL field", check_repair_covers_every_field),
    ("links: one URL, one link per issue", check_dedup_links),
    ("links: Primary only on government documents", check_primary_label),
    ("links: multi-outlet top stories, trade links, anchor text", check_multi_outlet_and_trade),
    ("links: journals, Korean publishers and X posts keep the right label", check_label_rules),
    ("links: Read online and PDF are that day's files", check_self_links_are_dated),
]


def main() -> int:
    failed = 0
    for label, fn in CHECKS:
        try:
            problems = fn()
        except Exception as e:                                  # noqa: BLE001
            problems = [f"raised {type(e).__name__}: {e}"]
        print(f"  {'FAIL' if problems else 'OK  '}  {label}")
        for p in problems:
            print(f"          {p}")
        failed += bool(problems)
    print(f"\n{len(CHECKS) - failed}/{len(CHECKS)} link checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
