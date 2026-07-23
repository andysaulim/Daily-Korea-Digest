"""
Gallup Korea weekly-poll fetcher — resilient, multi-source, complete.

Replaces the brittle Korean-Wikipedia table scrape. Two ideas make it robust:

  1. LABELED extraction — every number is pulled by the party NAME sitting next
     to it (민주당 40%, 국민의힘 26%, 무당층 28%), never by column position. This
     kills the old "biggest % must be the ruling party" heuristic, which breaks
     exactly when the independent share passes the opposition party (as it has).

  2. MERGE ACROSS ARTICLES — a single headline usually carries only the approval
     number. But Korean outlets report the same weekly poll in a fixed style, and
     the party breakdown + survey dates live in the article body / fuller snippets.
     We parse many articles about the SAME poll (keyed by survey dates) and merge
     their fields, so partial pieces assemble into one complete record. Anything
     still missing is carried forward from the prior baseline rather than reverting.

Fetching reuses the pipeline's existing Google-News + feedparser path; the parser
(the part most likely to need tuning) is fully unit-testable on plain text.
"""
import re
from datetime import datetime, timezone

_MONTHS = ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"]

# ── Labeled number patterns (name adjacent to the percentage) ────────────────
# Approval: a % near 대통령/이재명/국정 AND 긍정/지지/수행, but NOT immediately
# preceded by a party name (so we never grab a party rating as approval).
_RE_APPROVAL = re.compile(
    r'(?:대통령|이재명|국정)[^%나-힣]{0,25}(?:긍정|지지|수행)[^%]{0,15}?(\d{1,2}(?:\.\d)?)\s*%'
    r'|(?:긍정\s*평가|국정\s*수행\s*지지)[^%]{0,15}?(\d{1,2}(?:\.\d)?)\s*%',
)
# Label-first, with a single bounded gap ([^%\d]{0,10}) that absorbs Korean
# particles/labels between the party name and its number ("무당층은 28%", "민주당
# 지지도 40%"). The gap contains no digit or %, so it stops at the FIRST number
# after the label and never reaches a different party's figure. Korean poll
# reporting is virtually always "PARTY 40%" (label-first); a reverse "40% 민주당"
# form is deliberately NOT matched because in a sequential list ("민주당 40%,
# 국민의힘 26%") it would grab the preceding party's number.
_RE_DP = re.compile(r'(?:더불어민주당|민주당)[^%\d]{0,10}(\d{1,2}(?:\.\d)?)\s*%')
_RE_PPP = re.compile(r'국민의힘[^%\d]{0,10}(\d{1,2}(?:\.\d)?)\s*%')
_RE_IND = re.compile(r'무당층?[^%\d]{0,10}(\d{1,2}(?:\.\d)?)\s*%')
_RE_POLLNO = re.compile(r'제?\s*(\d{3})\s*호|데일리\s*오피니언\s*(?:제)?\s*(\d{3})')


def _first_group(m):
    if not m:
        return None
    for g in m.groups():
        if g:
            try:
                return float(g)
            except ValueError:
                return None
    return None


def _parse_survey_dates(text: str, year: int | None = None):
    """Return (english_label, sort_key 'YYYY-MM-DD' for the START date) or ("","").

    Handles: '7월 14~16일' (same-month range), '6월 30일~7월 2일' (cross-month),
    '7월 14일' (single). Year is inferred (current UTC year) unless a 4-digit year
    appears in the text.
    """
    if year is None:
        yr_m = re.search(r'(20\d{2})\s*년', text) or re.search(r'(20\d{2})', text)
        try:
            year = int(yr_m.group(1)) if yr_m else datetime.now(timezone.utc).year
        except Exception:
            year = datetime.now(timezone.utc).year
    # cross-month range: M월 D일 ~ M월 D일
    m = re.search(r'(\d{1,2})\s*월\s*(\d{1,2})\s*일?\s*[~\-–]\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일', text)
    if m:
        m1, d1, m2, d2 = (int(x) for x in m.groups())
        if 1 <= m1 <= 12 and 1 <= m2 <= 12:
            label = f"{_MONTHS[m1-1]} {d1}-{_MONTHS[m2-1]} {d2}, {year}"
            return label, f"{year}-{m1:02d}-{d1:02d}"
    # same-month range: M월 D~D일
    m = re.search(r'(\d{1,2})\s*월\s*(\d{1,2})\s*[~\-–]\s*(\d{1,2})\s*일', text)
    if m:
        mo, d1, d2 = (int(x) for x in m.groups())
        if 1 <= mo <= 12:
            label = f"{_MONTHS[mo-1]} {d1}-{d2}, {year}"
            return label, f"{year}-{mo:02d}-{d1:02d}"
    # single date: M월 D일
    m = re.search(r'(\d{1,2})\s*월\s*(\d{1,2})\s*일', text)
    if m:
        mo, d1 = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            label = f"{_MONTHS[mo-1]} {d1}, {year}"
            return label, f"{year}-{mo:02d}-{d1:02d}"
    return "", ""


def parse_gallup_text(text: str) -> dict:
    """Extract whatever Gallup fields appear in a text blob. Missing → None.

    Returns: {approval, dp, ppp, ind, survey_label, sort_key, poll_no} (floats/strs).
    """
    if not text:
        return {}
    text = re.sub(r"\s+", " ", text)
    label, sort_key = _parse_survey_dates(text)
    pollno_m = _RE_POLLNO.search(text)
    poll_no = None
    if pollno_m:
        poll_no = next((g for g in pollno_m.groups() if g), None)
    return {
        "approval": _first_group(_RE_APPROVAL.search(text)),
        "dp": _first_group(_RE_DP.search(text)),
        "ppp": _first_group(_RE_PPP.search(text)),
        "ind": _first_group(_RE_IND.search(text)),
        "survey_label": label,
        "sort_key": sort_key,
        "poll_no": poll_no,
    }


def merge_poll_records(records: list[dict], newest_sort_key: str = "") -> dict:
    """Merge parsed records that belong to the SAME (newest) poll.

    Groups by sort_key (survey-date identity), picks the most recent group that
    has an approval number, and fills each field from the first record that has
    it. Optionally ignores anything not newer than newest_sort_key.
    """
    dated = [r for r in records if r.get("sort_key") and r.get("approval") is not None]
    if not dated:
        return {}
    # newest survey-date group
    latest_key = max(r["sort_key"] for r in dated)
    if newest_sort_key and latest_key <= newest_sort_key:
        return {}
    group = [r for r in records if r.get("sort_key") == latest_key]
    merged = {"sort_key": latest_key}
    for field in ("approval", "dp", "ppp", "ind", "survey_label", "poll_no"):
        for r in group:
            if r.get(field) not in (None, ""):
                merged[field] = r[field]
                break
    return merged


# ── Fetching (best-effort; reuses the pipeline's Google-News + feed path) ─────

def _gnews_ko(query: str) -> str:
    """Google News RSS search in the KOREAN locale. The pipeline's default
    _gnews() uses hl=en-US/gl=US, which returns almost no Korean-language
    articles for a Korean query — so Gallup poll text (which is Korean) needs
    the ko-KR locale to surface the outlets that carry the full breakdown."""
    from urllib.parse import quote
    return (f"https://news.google.com/rss/search?q={quote(query)}"
            f"&hl=ko&gl=KR&ceid=KR:ko")


def _gather_texts(max_articles: int = 12, fetch_bodies: bool = True) -> list[str]:
    """Collect text blobs about the latest Gallup weekly poll: RSS title+summary
    for every hit, plus fetched article bodies for the top few (where the full
    party breakdown lives). All best-effort — failures are skipped."""
    texts: list[str] = []
    try:
        from collect import _parse_feed
    except Exception:
        return texts
    queries = [
        "한국갤럽 데일리 오피니언 지지율",
        "갤럽 이재명 대통령 지지율 정당 지지도",
    ]
    seen_links = set()
    entries = []
    for q in queries:
        try:
            hits = _parse_feed(_gnews_ko(q))
            print(f"    gallup_fetch: query {q!r} -> {len(hits)} entries")
            for e in hits:
                link = (e.get("link") or "").strip()
                if link and link in seen_links:
                    continue
                seen_links.add(link)
                entries.append(e)
        except Exception as e:
            print(f"    gallup_fetch: query {q!r} failed: {e}")
            continue
    for e in entries[:max_articles]:
        title = re.sub(r"<[^>]+>", " ", e.get("title", "") or "")
        summary = re.sub(r"<[^>]+>", " ", e.get("summary", e.get("description", "")) or "")
        blob = f"{title} {summary}".strip()
        if blob:
            texts.append(blob)
    if fetch_bodies:
        import requests
        for e in entries[:5]:
            link = (e.get("link") or "").strip()
            if not link.startswith("http"):
                continue
            try:
                r = requests.get(link, timeout=8,
                                 headers={"User-Agent": "Mozilla/5.0 (compatible; KoreaDailyBrief/1.0)"})
                if r.status_code == 200 and r.text:
                    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", r.text,
                                  flags=re.DOTALL | re.IGNORECASE)
                    body = re.sub(r"<[^>]+>", " ", body)
                    # keep only the region around Gallup mentions to reduce noise
                    idx = body.find("갤럽")
                    if idx != -1:
                        texts.append(body[max(0, idx - 200): idx + 800])
            except Exception:
                continue
    return texts


def fetch_latest_gallup(newest_sort_key: str = "", verbose: bool = True) -> dict:
    """Fetch + parse + merge the latest Gallup weekly poll from news.

    Returns a merged record ({approval, dp, ppp, ind, survey_label, sort_key,
    poll_no}) for the newest poll found, or {} if nothing newer/parseable.
    Never raises. When verbose, prints what it gathered and parsed so a CI run
    is self-diagnosing (a silent empty result is otherwise indistinguishable
    from a broken fetch).
    """
    try:
        texts = _gather_texts()
    except Exception as e:
        if verbose:
            print(f"    gallup_fetch: article gathering failed: {e}")
        texts = []
    records = [parse_gallup_text(t) for t in texts]
    records = [r for r in records if r]
    with_appr = [r for r in records if r.get("approval") is not None and r.get("sort_key")]
    if verbose:
        print(f"    gallup_fetch: {len(texts)} text blobs, "
              f"{len(with_appr)} carried an approval# + survey date")
        # Show the newest poll actually seen (even if not newer than baseline),
        # so 'no update' vs 'fetch broken' is distinguishable from the log.
        seen = merge_poll_records(records, newest_sort_key="")
        if seen:
            print(f"    gallup_fetch: newest poll seen = {seen.get('survey_label') or seen.get('sort_key')} "
                  f"(approval {seen.get('approval')}, DP {seen.get('dp')}, "
                  f"PPP {seen.get('ppp')}, ind {seen.get('ind')}, #{seen.get('poll_no')})")
        else:
            print("    gallup_fetch: no parseable Gallup poll found in fetched text")
    return merge_poll_records(records, newest_sort_key=newest_sort_key)
