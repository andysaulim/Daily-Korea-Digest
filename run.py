"""
Korea Daily Brief — Main Runner
CSIS Korea Chair
Orchestrates: collect → databases → digest → validate → render → push → send
Usage:
  python run.py              # Full pipeline (collect + digest + render + send)
  python run.py --no-send    # Render to file only, no email
  python run.py --from-cache # Skip collection, use existing collected.json
  python run.py --no-push    # Skip pushing new entries to databases
"""
import json
import argparse
import os
import re
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from digest import _count_digest_words


_PRESTIGE_OUTLETS = {"WSJ", "Wall Street Journal", "Washington Post", "WaPo", "NYT",
                      "New York Times", "Bloomberg", "Financial Times", "FT", "Economist", "The Economist"}


def _check_url(url: str, timeout: float = 5.0) -> tuple[str, bool, str]:
    """HEAD-check a URL; returns (url, ok, reason).
    Only flags 404/410 (definitively dead). Treats 403/405/429 as OK
    since paywalled sites and bot-protected servers commonly return these."""
    import requests
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 Korea-Digest-Validator/1.0"})
        # Only flag definitively dead URLs — 403/405/429/451 are normal for
        # paywalled sites (WSJ, FT, Bloomberg) and bot-protected servers
        if resp.status_code in (404, 410):
            return (url, False, f"HTTP {resp.status_code}")
        return (url, True, "")
    except requests.exceptions.Timeout:
        return (url, False, "timeout")
    except requests.exceptions.ConnectionError:
        return (url, False, "connection error")
    except Exception as e:
        return (url, False, str(e)[:50])


def _validate_urls(urls: list[str]) -> list[tuple[str, str]]:
    """Check URLs in parallel; returns list of (url, reason) for broken ones."""
    broken = []
    try:
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(_check_url, u): u for u in urls}
            for f in as_completed(futures, timeout=30):
                try:
                    url, ok, reason = f.result()
                    if not ok:
                        broken.append((url, reason))
                except Exception:
                    broken.append((futures[f], "check failed"))
    except TimeoutError:
        pass  # some URLs still pending — report what we have so far
    return broken

_STOP_WORDS = frozenset({"the", "a", "an", "in", "on", "of", "to", "for", "and", "is", "at", "by", "as", "with", "from",
                         "its", "new", "over", "after", "says", "said", "amid", "that", "has", "will", "may", "could",
                         "been", "are", "was", "were", "this", "but", "not", "all", "more", "than", "also"})

# Topic entities — entity match alone triggers dedup (institution/person/event)
_TOPIC_ENTITIES = {
    "bok": {"bok", "bank of korea", "central bank", "monetary policy", "rate decision", "interest rate", "base rate", "benchmark rate"},
    "kim jong un": {"kim jong un", "kim jongun", "kju", "north korean leader", "dprk leader", "supreme leader"},
    "yoon": {"yoon", "yoon suk yeol", "yoon suk-yeol", "president yoon"},
    "lee jae myung": {"lee jae myung", "lee jae-myung", "lee jaemyung"},
    "usfk": {"usfk", "us forces korea", "united states forces korea"},
    "freedom shield": {"freedom shield", "joint military exercise", "joint drill", "combined exercise"},
}

# Company entities — need keyword overlap too (big conglomerates have many unrelated stories)
_COMPANY_ENTITIES = {
    "samsung": {"samsung", "samsung electronics"},
    "hyundai": {"hyundai", "hyundai motor", "hyundai motors"},
    "sk": {"sk hynix", "sk group", "sk innovation", "sk telecom"},
    "posco": {"posco"},
    "hanwha": {"hanwha"},
    "lg": {"lg energy", "lg electronics", "lg chem"},
}

# All sections that contain items with URLs/headlines
_ALL_ITEM_SECTIONS = ("top_stories", "overnight_items", "also_today",
                       "business_economy", "opeds_today", "academic_today",
                       "social_statements", "northeast_asia")

# Sections where duplicates get auto-stripped (priority order — first wins)
_DEDUP_SECTIONS = ("top_stories", "overnight_items", "business_economy",
                    "northeast_asia", "also_today", "opeds_today",
                    "academic_today", "social_statements")


def _extract_entities(text: str) -> tuple[set[str], set[str]]:
    """Extract topic and company entity tags from a headline.
    Returns (topic_entities, company_entities)."""
    text_lower = text.lower()
    topics = set()
    companies = set()
    for tag, aliases in _TOPIC_ENTITIES.items():
        if any(alias in text_lower for alias in aliases):
            topics.add(tag)
    for tag, aliases in _COMPANY_ENTITIES.items():
        if any(alias in text_lower for alias in aliases):
            companies.add(tag)
    return topics, companies


def _headline_key(item: dict) -> tuple[str, set, set, set]:
    """Return (headline, keywords, topic_entities, company_entities) for an item."""
    headline = (item.get("headline", "") or "").lower().strip()
    words = {w for w in re.split(r'\W+', headline) if len(w) > 2 and w not in _STOP_WORDS}
    topics, companies = _extract_entities(headline)
    return headline, words, topics, companies


def _is_dup(words_a, topics_a, companies_a, words_b, topics_b, companies_b) -> str | None:
    """Check if two items are duplicates. Returns reason string or None."""
    if not words_a or not words_b:
        return None
    # Keyword overlap
    overlap = words_a & words_b
    min_len = min(len(words_a), len(words_b))
    keyword_dup = min_len > 1 and len(overlap) >= 2 and len(overlap) / min_len >= 0.5
    if keyword_dup:
        return "keyword overlap"
    # Topic entity match — require keyword overlap too (just like companies).
    # On heavy news days a single figure (e.g. KJU) dominates many *distinct*
    # stories; entity-only matching was wiping them all out.
    shared_topics = topics_a & topics_b
    if shared_topics:
        # Strip entity alias words from overlap to avoid self-matching
        entity_words = set()
        for tag in shared_topics:
            for alias in _TOPIC_ENTITIES.get(tag, set()):
                entity_words.update(w for w in alias.split() if len(w) > 2)
        non_entity_overlap = overlap - entity_words
        if len(non_entity_overlap) >= 2:
            return f"shared topic + keywords: {shared_topics}, {non_entity_overlap}"
    # Company entity match — need 2+ non-entity keyword overlaps
    # (company names alone aren't enough — Samsung has many unrelated stories)
    shared_companies = companies_a & companies_b
    if shared_companies:
        # Strip out company name words from overlap to avoid self-matching
        company_words = set()
        for tag in shared_companies:
            for alias in _COMPANY_ENTITIES.get(tag, set()):
                company_words.update(w for w in alias.split() if len(w) > 2)
        non_entity_overlap = overlap - company_words
        if len(non_entity_overlap) >= 2:
            return f"shared company + keywords: {shared_companies}, {non_entity_overlap}"
    return None


def _dedup_digest(digest: dict) -> tuple[dict, list[str]]:
    """Auto-strip duplicate topics from digest. Returns (cleaned_digest, log_messages).

    Walks sections in priority order. For each item, checks against all items
    already seen. If duplicate, removes it from the lower-priority section.
    Respects section minimums — won't strip a section below its floor.
    """
    _SECTION_FLOORS = {"top_stories": 3, "overnight_items": 3}
    log = []
    seen = []  # (section, headline, words, topics, companies)
    seen_urls_global = {}  # url -> section_key (track across ALL sections)

    for section_key in _DEDUP_SECTIONS:
        items = digest.get(section_key)
        if not items or not isinstance(items, list):
            continue

        floor = _SECTION_FLOORS.get(section_key, 0)
        kept = []
        deferred_removals = []  # (index, log_msg) — removals that may be restored

        for item in items:
            url = (item.get("url") or "").strip()

            # URL dedup — across all sections
            if url and url.startswith("http"):
                if url in seen_urls_global:
                    msg = f"  Removed duplicate URL in {section_key} (already in {seen_urls_global[url]}): {url[:80]}"
                    deferred_removals.append((item, msg))
                    continue
                seen_urls_global[url] = section_key

            headline, words, topics, companies = _headline_key(item)
            if len(headline) < 15:
                kept.append(item)
                continue

            is_duplicate = False
            for prev_section, prev_headline, prev_words, prev_topics, prev_companies in seen:
                reason = _is_dup(words, topics, companies, prev_words, prev_topics, prev_companies)
                if reason:
                    msg = (
                        f"  Removed from {section_key} ({reason}): "
                        f"'{headline[:60]}' — kept in {prev_section}: '{prev_headline[:60]}'")
                    deferred_removals.append((item, msg))
                    is_duplicate = True
                    break

            if not is_duplicate:
                kept.append(item)
                seen.append((section_key, headline, words, topics, companies))

        # Restore items if removals would breach section floor
        if len(kept) < floor and deferred_removals:
            need = floor - len(kept)
            restored = deferred_removals[-need:]
            deferred_removals = deferred_removals[:-need]
            for item, _msg in restored:
                kept.append(item)
                headline, words, topics, companies = _headline_key(item)
                seen.append((section_key, headline, words, topics, companies))

        for _item, msg in deferred_removals:
            log.append(msg)

        digest[section_key] = kept

    return digest, log


_US_KEYWORDS = frozenset({
    "us", "u.s.", "united states", "america", "american", "washington",
    "ustr", "commerce department", "white house", "pentagon", "congress",
    "treasury", "biden", "trump", "section 232", "section 301", "section 122",
    "ieepa", "cfius", "ita", "itc",
})


def _filter_non_us_deals(digest: dict) -> list[str]:
    """Remove deals from us_korea_deals.deals that don't involve the US.

    Returns log messages for any removed items.
    """
    log = []
    us_korea = digest.get("us_korea_deals")
    if not us_korea or not isinstance(us_korea, dict):
        return log

    deals = us_korea.get("deals")
    if not deals or not isinstance(deals, list):
        return log

    kept = []
    for deal in deals:
        # Check headline, detail, and parties for US connection
        text = " ".join(str(deal.get(f, "")) for f in
                        ("headline", "detail", "parties", "sector")).lower()
        has_us = any(kw in text for kw in _US_KEYWORDS)
        if has_us:
            kept.append(deal)
        else:
            headline = deal.get("headline", "")[:80]
            log.append(f"  Removed non-US deal from us_korea_deals: '{headline}'")

    us_korea["deals"] = kept
    return log


# Max times a single source can appear in overnight_items / also_today.
# Yonhap (연합뉴스) is Korea's dominant wire service — like AP for the US.
# Cap of 2 was too aggressive, removing 5-7 items per run and crashing word count.
_SOURCE_CAP = 3

_SOURCE_PREFIX_MAP = {
    "yonhap": "yonhap", "연합뉴스": "yonhap",
    "reuters": "reuters",
    "nikkei": "nikkei",
    "kyodo": "kyodo",
    "associated press": "ap", "ap news": "ap",
    "agence france": "afp", "afp": "afp",
    "korea herald": "korea herald",
    "korea times": "korea times",
    "joongang": "joongang", "중앙일보": "joongang",
    "chosun": "chosun", "조선일보": "chosun",
    "hankyoreh": "hankyoreh", "한겨레": "hankyoreh",
    "dong-a": "dong-a", "동아일보": "dong-a",
    "maeil": "maeil", "매일경제": "maeil",
    "hankook": "hankook", "한국경제": "hankook",
    "jtbc": "jtbc", "kbs": "kbs", "mbc": "mbc", "sbs": "sbs", "ytn": "ytn",
    "nk news": "nk news", "nk pro": "nk news",
    "daily nk": "daily nk",
    "scmp": "scmp", "south china morning": "scmp",
    "global times": "global times",
    "tass": "tass", "xinhua": "xinhua",
    "japan times": "japan times",
}

def _normalize_source(src: str) -> str:
    """Collapse source name variants to a canonical key."""
    s = src.lower().strip()
    for prefix, canonical in _SOURCE_PREFIX_MAP.items():
        if s.startswith(prefix):
            return canonical
    return s

def _enforce_source_diversity(digest: dict) -> list[str]:
    """Cap any single source to _SOURCE_CAP appearances per section.

    Skips top_stories (curated 3-4 item section where story importance
    outweighs source diversity). Excess items from over-represented sources
    are dropped, but the section is never reduced below its floor.
    Returns log messages for removed items.
    """
    _SECTION_MINIMUMS = {"overnight_items": 3}
    log = []
    for section_key in ("overnight_items", "also_today"):
        items = digest.get(section_key)
        if not items or not isinstance(items, list):
            continue

        floor = _SECTION_MINIMUMS.get(section_key, 0)

        source_counts: dict[str, int] = {}
        kept = []
        dropped = []
        for item in items:
            src = _normalize_source(item.get("source", "Unknown"))
            source_counts[src] = source_counts.get(src, 0) + 1
            if source_counts[src] <= _SOURCE_CAP:
                kept.append(item)
            else:
                headline = item.get("headline", "")[:60]
                dropped.append((item, src, headline))

        # If removing all excess items would breach the section minimum,
        # keep enough excess items (from the end) to stay at the floor.
        if len(kept) < floor and dropped:
            need = floor - len(kept)
            # Re-add the last N dropped items (least egregious duplicates)
            restored = dropped[-need:]
            dropped = dropped[:-need]
            for item, src, headline in restored:
                kept.append(item)

        if dropped:
            digest[section_key] = kept
            for _item, src, headline in dropped:
                log.append(f"  Removed excess {src} from {section_key}: '{headline}'")

    return log


def validate_digest(digest: dict, payload: dict | None = None) -> list[str]:
    """Pre-send quality gate. Returns list of warnings (empty = all clear)."""
    warnings = []

    # ── Section count checks (hard caps) ─────────────────────────────────
    SECTION_CAPS = {
        "top_stories":       (3, 4),
        "overnight_items":   (3, 6),
        "business_economy":  (0, 6),
        "calendar_watch":    (4, 5),
        "also_today":        (0, 6),
        "northeast_asia":    (0, 6),
        "social_statements": (0, 6),
        "rok_government":    (0, 6),
        "rok_assembly":      (0, 6),
        "opeds_today":       (0, 6),
        "academic_today":    (0, 6),
        "rok_personnel":     (0, 6),
        "morning_memo":      (3, 3),
        "on_this_day":       (0, 1),
    }
    for section_key, (min_ct, max_ct) in SECTION_CAPS.items():
        items = digest.get(section_key) or []
        label = section_key.upper().replace("_", " ")
        if min_ct and len(items) < min_ct:
            warnings.append(f"{label} CRITICAL: only {len(items)} (min {min_ct})")
        elif len(items) > max_ct:
            warnings.append(f"{label} CRITICAL: {len(items)} items (max {max_ct})")

    # ── RE: line must be present and substantive ─────────────────────────
    re_line = digest.get("re_line")
    if not re_line or len(str(re_line).strip()) < 10:
        warnings.append("RE: LINE CRITICAL: missing or too short")

    # ── Word count check (hard minimum 1000, target 1200-1400) ──────────
    word_count = _count_digest_words(digest)
    if word_count < 1000:
        warnings.append(f"WORD COUNT CRITICAL: ~{word_count} words (HARD MINIMUM 1000 — newsletter is too short)")
    elif word_count < 1200:
        warnings.append(f"WORD COUNT: ~{word_count} words (target 1200-1400 for 5-min read)")

    # ── KCNA delta must exist ─────────────────────────────────────────────
    kcna = digest.get("kcna_delta")
    if not kcna or not isinstance(kcna, dict):
        warnings.append("KCNA DELTA CRITICAL: missing kcna_delta section")

    # ── Single pass over all items: URLs, headlines, sources, body checks ─
    seen_urls = {}
    seen_headlines = []  # (section, headline, keywords, topic_entities, company_entities)
    source_counts = {}
    bad_urls = 0
    dup_url_count = 0
    empty_body_count = 0

    for section_key in _ALL_ITEM_SECTIONS:
        for item in (digest.get(section_key) or []):
            url = item.get("url", "")

            # Bad URL check
            if url and (url == "#" or not url.startswith("http")):
                bad_urls += 1

            # Duplicate URL check
            if url and url.startswith("http"):
                if url in seen_urls:
                    dup_url_count += 1
                    if dup_url_count <= 3:
                        warnings.append(
                            f"DUPLICATE: URL appears in both {seen_urls[url]} and {section_key}")
                else:
                    seen_urls[url] = section_key

            # Empty body check — items should have substantive content
            body = (item.get("body") or item.get("body_text") or
                    item.get("summary") or item.get("detail") or "").strip()
            if not body or len(body) < 20:
                empty_body_count += 1

            # Source diversity (top_stories + overnight + also_today)
            if section_key in ("top_stories", "overnight_items", "also_today"):
                src = (item.get("source", "") or "").strip()
                if src:
                    source_counts[src] = source_counts.get(src, 0) + 1

            # Duplicate topic check (keyword overlap + entity matching)
            headline, words, topics, companies = _headline_key(item)
            if len(headline) > 15:
                for prev_section, prev_headline, prev_words, prev_topics, prev_companies in seen_headlines:
                    reason = _is_dup(words, topics, companies, prev_words, prev_topics, prev_companies)
                    if reason:
                        warnings.append(
                            f"DUPLICATE TOPIC CRITICAL: same topic in {prev_section} and {section_key} ({reason}): "
                            f"'{headline[:60]}...' vs '{prev_headline[:60]}...'")
                        break
                seen_headlines.append((section_key, headline, words, topics, companies))

    if bad_urls:
        warnings.append(f"BAD URLS: {bad_urls} placeholder or invalid URLs found")

    # Live URL accessibility check (HEAD requests in parallel)
    all_urls = [u for u in seen_urls if u.startswith("http")]
    if all_urls:
        broken = _validate_urls(all_urls)
        for url, reason in broken:
            section = seen_urls.get(url, "unknown")
            warnings.append(f"BROKEN LINK ({reason}): {url} in {section}")

    if empty_body_count:
        warnings.append(f"EMPTY BODIES: {empty_body_count} items have no substantive body text")

    # Source diversity (normalize source names to catch variants like "Yonhap" / "Yonhap News")
    normalized_counts: dict[str, int] = {}
    for src, count in source_counts.items():
        key = _normalize_source(src)
        normalized_counts[key] = normalized_counts.get(key, 0) + count
    for src, count in normalized_counts.items():
        if count > 10:
            warnings.append(
                f"SOURCE DIVERSITY CRITICAL: '{src}' appears {count} times across top sections — diversify sources")
        elif count > 7:
            warnings.append(
                f"SOURCE DIVERSITY: '{src}' appears {count} times across top sections — consider diversifying")

    # ── Check for "None" strings in critical fields ──────────────────────
    for field in ("re_line", "digest_date"):
        val = digest.get(field)
        if str(val).strip() == "None":
            warnings.append(f'NONE STRING: "{field}" field contains literal "None"')

    # ── Digest date matches today ────────────────────────────────────────
    digest_date = digest.get("digest_date", "")
    today_str = datetime.now(ZoneInfo("America/New_York")).strftime("%A, %B %-d, %Y")
    if digest_date and digest_date != today_str:
        warnings.append(f"DATE MISMATCH: digest says '{digest_date}', today is '{today_str}'")

    # ── Public sentiment must have all 4 metrics ─────────────────────────
    sentiment = digest.get("public_sentiment") or {}
    missing_sentiment = [k for k in ("presidential_approval", "party_ruling",
                                      "party_opposition", "party_independent")
                         if not (sentiment.get(k) or {}).get("value")]
    if missing_sentiment:
        warnings.append(f"SENTIMENT: missing values for {', '.join(missing_sentiment)}")

    # ── Prestige outlet cross-reference ───────────────────────────────
    # Use canonical name matching so "WSJ" matches "Wall Street Journal" etc.
    _PRESTIGE_CANONICAL = {
        "wsj": "wsj", "wall street journal": "wsj",
        "washington post": "wapo", "wapo": "wapo",
        "nyt": "nyt", "new york times": "nyt",
        "bloomberg": "bloomberg",
        "financial times": "ft", "ft": "ft",
        "economist": "economist", "the economist": "economist",
    }
    def _prestige_key(source_name: str) -> str | None:
        s = source_name.lower().strip()
        for prefix, key in _PRESTIGE_CANONICAL.items():
            if prefix in s:
                return key
        return None

    if payload:
        prestige_in_input: dict[str, str] = {}  # canonical_key -> original source name
        for a in (payload.get("tier1") or []):
            src = (a.get("source") or "").strip()
            pk = _prestige_key(src)
            if pk and pk not in prestige_in_input:
                prestige_in_input[pk] = src
        digest_prestige_keys: set[str] = set()
        for section_key in _ALL_ITEM_SECTIONS:
            for item in (digest.get(section_key) or []):
                pk = _prestige_key(item.get("source", ""))
                if pk:
                    digest_prestige_keys.add(pk)
        for pk, src in prestige_in_input.items():
            if pk not in digest_prestige_keys:
                warnings.append(
                    f"PRESTIGE OUTLET DROPPED: '{src}' had Korea articles in input but none appeared in digest")

    # ── Cross-reference: every digest URL must exist in input feed ────────
    if payload:
        input_urls: set[str] = set()
        for tier_key in ("tier1", "tier2", "tier3", "tier4"):
            for a in (payload.get(tier_key) or []):
                u = (a.get("url") or "").strip()
                if u and u.startswith("http"):
                    input_urls.add(u)
        fabricated_count = 0
        for section_key in _ALL_ITEM_SECTIONS:
            for item in (digest.get(section_key) or []):
                url = (item.get("url") or "").strip()
                if url and url.startswith("http") and url not in input_urls:
                    headline = (item.get("headline") or item.get("translated_title")
                                or item.get("title") or "")[:80]
                    fabricated_count += 1
                    if fabricated_count <= 5:
                        warnings.append(
                            f"FABRICATED ARTICLE CRITICAL: URL not in input feed — {section_key}: "
                            f"'{headline}' ({url})")
        if fabricated_count:
            warnings.append(
                f"FABRICATED ARTICLES CRITICAL: {fabricated_count} article(s) have URLs not found "
                f"in today's input feed — likely hallucinated")

    return warnings


def _postprocess_digest(digest_data: dict) -> tuple[dict, list[str]]:
    """Run dedup, deal filter, and source diversity on digest. Returns (digest, all_log_messages)."""
    log = []
    digest_data, dedup_log = _dedup_digest(digest_data)
    if dedup_log:
        log.append(f"\n🧹  Auto-dedup removed {len(dedup_log)} duplicate(s):")
        log.extend(dedup_log)

    deal_log = _filter_non_us_deals(digest_data)
    if deal_log:
        log.append(f"\n🧹  Filtered {len(deal_log)} non-US deal(s) from trade section:")
        log.extend(deal_log)

    diversity_log = _enforce_source_diversity(digest_data)
    if diversity_log:
        log.append(f"\n🧹  Source diversity: removed {len(diversity_log)} over-represented item(s):")
        log.extend(diversity_log)

    return digest_data, log


def main():
    parser = argparse.ArgumentParser(description="Korea Daily Brief pipeline")
    parser.add_argument("--no-send",    action="store_true", help="Render to file only, do not send email")
    parser.add_argument("--from-cache", action="store_true", help="Skip collection, use existing collected.json")
    parser.add_argument("--dry-run",    action="store_true", help="Collect only, don't call Claude")
    parser.add_argument("--no-push",    action="store_true", help="Skip pushing new entries to NK-Russia/provocations databases")
    args = parser.parse_args()

    print("=" * 60)
    print("  Korea Daily Brief")
    print("  CSIS Korea Chair")
    from zoneinfo import ZoneInfo
    print(f"  {datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d %-I:%M %p ET')}")
    print("=" * 60)

    # ── Step 1: Collect ───────────────────────────────────────────────────────
    if args.from_cache and Path("collected.json").exists():
        print("\n📦  Using cached collection (collected.json)")
        payload = json.loads(Path("collected.json").read_text())
        total = sum(len(v) for v in payload.values() if isinstance(v, list))
        print(f"  {total} articles loaded from cache")
    else:
        from collect import collect
        payload = collect()
        Path("collected.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.dry_run:
        print("\n  --dry-run: stopping after collection. See collected.json")
        return

    # ── Step 1b: Fetch CSIS databases for context ─────────────────────────────
    from databases import fetch_all, build_context_block, process_digest_entries
    print("\n📚  Loading CSIS databases...")
    databases = fetch_all()
    db_context = build_context_block(databases)

    # ── Step 2: Generate digest via Claude (with validation retry) ──────────
    from digest import generate_digest, regenerate_digest
    MAX_VALIDATION_RETRIES = 2
    digest_data = generate_digest(payload, db_context=db_context)

    # Auto-strip duplicates, filter deals, enforce source diversity
    digest_data, pp_log = _postprocess_digest(digest_data)
    for msg in pp_log:
        print(msg)

    Path("digest.json").write_text(json.dumps(digest_data, ensure_ascii=False, indent=2))

    # ── Step 2+: Update Kim Jong Un appearance tracker + KCNA rhetoric tracker
    from kim_tracker import update_from_digest
    from kcna_tracker import update_from_digest as kcna_update_from_digest
    from bp_tracker import update_from_digest as bp_update_from_digest

    for validation_attempt in range(1 + MAX_VALIDATION_RETRIES):
        # ── Step 2a: Pre-send validation gate ─────────────────────────────────
        validation_warnings = validate_digest(digest_data, payload=payload)
        critical_warnings = [w for w in validation_warnings if "CRITICAL" in w]

        # Don't retry for DUPLICATE TOPIC issues — dedup already handled them,
        # and retrying just causes dedup to fight the retry loop
        retryable_warnings = [w for w in critical_warnings if "DUPLICATE TOPIC" not in w]

        if not critical_warnings:
            # Passed — print any non-critical warnings and move on
            if validation_warnings:
                print("\n⚠️  PRE-SEND VALIDATION WARNINGS (non-critical):")
                for w in validation_warnings:
                    print(f"    • {w}")
                print()
            else:
                print("\n✅  Validation passed — all checks OK")
            break

        if not retryable_warnings:
            # Only duplicate topic warnings remain — dedup handled what it could
            print("\n⚠️  Remaining warnings are duplicate-topic only (auto-dedup applied):")
            for w in critical_warnings:
                print(f"    • {w}")
            # Downgrade these so they don't block sending
            critical_warnings = []
            break

        # Critical failures found
        print(f"\n⚠️  VALIDATION ATTEMPT {validation_attempt + 1}/{1 + MAX_VALIDATION_RETRIES} — CRITICAL WARNINGS:")
        for w in validation_warnings:
            print(f"    • {w}")

        if validation_attempt < MAX_VALIDATION_RETRIES:
            # Retry only the digest generation, passing validation feedback
            print("\n🔄  Re-generating digest with validation feedback (reusing collected articles)...")
            digest_data = regenerate_digest(
                payload, digest_data, retryable_warnings, db_context=db_context,
                attempt=validation_attempt
            )
            # Post-process again after regeneration
            digest_data, pp_log = _postprocess_digest(digest_data)
            for msg in pp_log:
                print(f"  {msg}")
            Path("digest.json").write_text(json.dumps(digest_data, ensure_ascii=False, indent=2))
        else:
            print("\n🚫  CRITICAL validation failures after all retries — newsletter will NOT be sent.")
            print("    Fix the issues above or re-run. HTML still rendered for review.")

    # Only update trackers if digest passed validation (avoid corrupting state)
    if not critical_warnings:
        update_from_digest(digest_data)
        kcna_update_from_digest(digest_data)
        bp_update_from_digest(digest_data)
    else:
        print("  ⚠  Skipping tracker updates due to critical validation failures")

    # ── Step 2b: Push flagged entries to databases ────────────────────────────
    if not args.no_push and not critical_warnings:
        push_summary = process_digest_entries(digest_data)
        if push_summary.get("nk_russia_added") or push_summary.get("provocations_added"):
            print(f"    NK-Russia: {push_summary.get('nk_russia_added', 0)} added, "
                  f"Provocations: {push_summary.get('provocations_added', 0)} added")
    else:
        print("\n  --no-push: skipping database updates")

    # ── Step 3: Render HTML ──────────────────────────────────────────────────
    from render import render

    # Inject web URL for "Read Online" link (set via env or GitHub Pages)
    web_base = os.environ.get("WEB_URL", "")
    if web_base:
        digest_data["web_url"] = web_base.rstrip("/") + "/latest.html"

    html = render(digest_data)

    date_slug = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    out_path  = Path(f"digest_{date_slug}.html")
    out_path.write_text(html, encoding="utf-8")
    print(f"\n📄  HTML rendered: {out_path} ({len(html):,} bytes)")

    # Also write latest.html for convenience
    Path("latest.html").write_text(html, encoding="utf-8")

    # Archive copy for GitHub Pages
    archive_dir = Path("public")
    archive_dir.mkdir(exist_ok=True)
    (archive_dir / "latest.html").write_text(html, encoding="utf-8")
    (archive_dir / f"digest_{date_slug}.html").write_text(html, encoding="utf-8")
    # Index redirect so Pages root doesn't 404
    (archive_dir / "index.html").write_text(
        '<!DOCTYPE html><html><head><meta http-equiv="refresh" content="0;url=latest.html"></head></html>',
        encoding="utf-8",
    )

    # ── Step 4: Send email ───────────────────────────────────────────────────
    if critical_warnings:
        print("\n🚫  Skipping email due to critical validation failures. Review latest.html.")
        import sys
        sys.exit(1)
    elif args.no_send:
        print("\n  --no-send: skipping email. Open latest.html to review.")
    else:
        if not os.environ.get("DIGEST_TO"):
            print("\n⚠️  DIGEST_TO not set — email will only go to sender's own address")
        from send_email import send
        re_line = digest_data.get("re_line")
        send(html, re_line=re_line)

    print("\n✅  Done.\n")


if __name__ == "__main__":
    main()
