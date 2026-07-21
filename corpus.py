"""
Persistent article corpus.

Every run, collect.py gathers 200-350 articles but only the ~15-30 that make
the newsletter survive; the rest were discarded when collected.json was
overwritten. This module keeps the full set as a permanent record, serving
three uses:

  1. Records / audit — trace any digest claim back to its source article, and
     see what was considered but not used, weeks later.
  2. AI grounding — feed recently-covered stories back into the digest prompt
     so Claude can cite precedent and avoid re-reporting yesterday's news.
  3. Analytics — trends over time (see corpus_stats.py).

Storage lives under public/corpus/ and rides the existing GitHub Pages deploy
(keep_files: true), so dated files persist forever at
https://<pages-host>/corpus/{file}. Read-back reuses the same HTTP-fetch
pattern the weekly summary uses — no database.

Layout:
  public/corpus/{date}.json          — full daily audit record (all articles)
  public/corpus/index_{YYYY-MM}.json — compact monthly shard (fast search/grounding)
  public/corpus/manifest.json        — list of shards + per-day counts (drives UI)

NOTE: The past is not backfillable — raw collected data before this module's
first run was already discarded. The corpus accumulates from deployment forward.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# Article-bearing digest sections (mirror of run.py:_ALL_ITEM_SECTIONS).
# Duplicated rather than imported to avoid a circular import (run imports us).
_DIGEST_ITEM_SECTIONS = (
    "top_stories", "overnight_items", "also_today", "business_economy",
    "opeds_today", "academic_today", "social_statements", "northeast_asia",
)

# Summary cap — matches collect.py's _entry_to_article (summary[:800]).
_SUMMARY_CAP = 800

# GitHub Pages base for corpus read-back. Overridable via WEB_URL env at the
# call site; this is the production default.
PAGES_CORPUS_BASE = "https://andysaulim.github.io/Daily-Korea-Digest/corpus"


def _norm_url(url) -> str:
    """Normalize a URL for matching — strip only, matching run.py's dedup/
    repair convention (URLs are compared case-sensitively there)."""
    return (str(url) if url else "").strip()


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — build & persist
# ─────────────────────────────────────────────────────────────────────────────

def collect_digest_urls(digest_data: dict) -> dict:
    """Return {normalized_url: section_key} for every article that made the
    newsletter. Walks the standard item sections plus us_korea_deals.deals."""
    used = {}
    for section in _DIGEST_ITEM_SECTIONS:
        for item in (digest_data.get(section) or []):
            if not isinstance(item, dict):
                continue
            url = _norm_url(item.get("url"))
            if url.startswith("http") and url not in used:
                used[url] = section
    # US-Korea deals live nested under us_korea_deals.deals
    uk = digest_data.get("us_korea_deals")
    deals = uk.get("deals") if isinstance(uk, dict) else (uk if isinstance(uk, list) else [])
    for deal in (deals or []):
        if not isinstance(deal, dict):
            continue
        url = _norm_url(deal.get("url"))
        if url.startswith("http") and url not in used:
            used[url] = "us_korea_deals"
    return used


def slim_article(article: dict, tier: int, used_in_digest: bool,
                 section, dup_of_recent: bool) -> dict:
    """Flatten a collect.py article into the compact audit-record shape."""
    summary = (article.get("summary") or "").strip()
    return {
        "url": _norm_url(article.get("url")),
        "title": (article.get("title") or article.get("headline") or "").strip(),
        "source": (article.get("source") or "").strip(),
        "tier": tier,
        "lang": article.get("lang", "EN"),
        "pub_date": article.get("pub_date"),
        "topics": article.get("tags") or [],
        "summary": summary[:_SUMMARY_CAP],
        "used_in_digest": used_in_digest,
        "section": section,
        "dup_of_recent": dup_of_recent,
    }


def _tier_num(bucket_key: str) -> int:
    """Map a payload bucket name ('tier1'..'tier4') to its tier number, else 0."""
    m = re.match(r"tier(\d)$", bucket_key)
    return int(m.group(1)) if m else 0


def build_corpus_records(payload: dict, digest_data: dict,
                         recent_urls=None) -> list:
    """Build the day's slim records from the raw collected payload.

    Iterates every list-valued tierN bucket in the payload, tags each article
    with tier, used_in_digest (+ section) from the final digest, and
    dup_of_recent (url seen in the last N days). Dedups by URL within the day.
    """
    recent_urls = recent_urls or set()
    used = collect_digest_urls(digest_data)
    records = []
    seen = set()
    for bucket_key, items in payload.items():
        if not isinstance(items, list):
            continue
        tier = _tier_num(bucket_key)
        if tier == 0:
            continue  # not an article tier (e.g. market_indicators is a dict)
        for article in items:
            if not isinstance(article, dict):
                continue
            url = _norm_url(article.get("url"))
            if not url.startswith("http") or url in seen:
                continue
            seen.add(url)
            records.append(slim_article(
                article, tier,
                used_in_digest=url in used,
                section=used.get(url),
                dup_of_recent=url in recent_urls,
            ))
    return records


def _index_row(rec: dict, date_slug: str) -> dict:
    """Compact one-row-per-article projection for the monthly index shard."""
    return {
        "date": date_slug,
        "url": rec["url"],
        "title": rec["title"],
        "source": rec["source"],
        "tier": rec["tier"],
        "topics": rec["topics"],
        "used": rec["used_in_digest"],
    }


def write_daily_corpus(records: list, date_slug: str, corpus_dir: Path) -> Path:
    """Write public/corpus/{date}.json (idempotent overwrite on re-run)."""
    path = corpus_dir / f"{date_slug}.json"
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return path


def update_month_index(records: list, date_slug: str, corpus_dir: Path) -> Path:
    """Upsert the day's compact rows into index_{YYYY-MM}.json (idempotent:
    drops any existing rows for date_slug first)."""
    month = date_slug[:7]  # YYYY-MM
    path = corpus_dir / f"index_{month}.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            rows = []
    except (FileNotFoundError, json.JSONDecodeError):
        rows = []
    rows = [r for r in rows if r.get("date") != date_slug]
    rows.extend(_index_row(r, date_slug) for r in records)
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return path


def update_manifest(date_slug: str, records: list, corpus_dir: Path,
                    has_vectors: bool = False) -> Path:
    """Maintain corpus/manifest.json — a thin index of available days and
    shards for the search UI. Mirrors run.py's archive.json upsert logic.
    When has_vectors, records the day's vector sidecar so the UI can lazy-load
    it for the semantic 'more like this' feature."""
    month = date_slug[:7]
    path = corpus_dir / "manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    days = [d for d in data.get("days", []) if d.get("date") != date_slug]
    days.append({
        "date": date_slug,
        "total": len(records),
        "used_in_digest": sum(1 for r in records if r["used_in_digest"]),
        "shard": f"index_{month}.json",
        "daily": f"{date_slug}.json",
        "vectors": f"vectors_{month}.json" if has_vectors else None,
    })
    days.sort(key=lambda d: d["date"], reverse=True)
    shards = sorted({d["shard"] for d in days}, reverse=True)
    data["days"] = days
    data["shards"] = shards
    data["updated"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def build_vectors(records: list) -> dict:
    """Embed each record's title+summary; return {url: base64_int8_vector}.

    Best-effort: returns {} if the embedding backend is unavailable, so the
    corpus still saves (just without a vector sidecar this run). Vectors are
    stored ONLY here — never in the daily audit records or the digest prompt.
    """
    if not records:
        return {}
    try:
        from embeddings import embed, quantize
    except Exception:
        return {}
    texts = [f"{r.get('title', '')} {r.get('summary', '')}".strip() for r in records]
    vecs = embed(texts)
    if vecs is None:
        return {}
    out = {}
    for r, v in zip(records, vecs):
        url = r.get("url")
        if url:
            out[url] = quantize(v)
    return out


def update_vectors_shard(vectors: dict, date_slug: str, corpus_dir: Path) -> Path | None:
    """Upsert {url: emb} into vectors_{YYYY-MM}.json (keyed by URL; today's urls
    overwrite). Powers corpus_search.py and the UI's 'more like this'. Returns
    the path, or None if there were no vectors to write."""
    if not vectors:
        return None
    path = corpus_dir / f"vectors_{date_slug[:7]}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data.update(vectors)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def save_corpus(payload: dict, digest_data: dict, date_slug: str,
                archive_dir: Path, recent_urls=None) -> dict:
    """Top-level entry point called from run.py. Writes the daily record,
    monthly index, and manifest. Returns counts for logging."""
    corpus_dir = Path(archive_dir) / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    records = build_corpus_records(payload, digest_data, recent_urls)
    write_daily_corpus(records, date_slug, corpus_dir)
    update_month_index(records, date_slug, corpus_dir)

    # Semantic vectors for search / related-articles (best-effort: a failure
    # here leaves the corpus fully intact, just without vectors this run).
    vec_count = 0
    try:
        vectors = build_vectors(records)
        if vectors:
            update_vectors_shard(vectors, date_slug, corpus_dir)
            vec_count = len(vectors)
    except Exception:
        vec_count = 0

    update_manifest(date_slug, records, corpus_dir, has_vectors=vec_count > 0)
    return {
        "total": len(records),
        "used_in_digest": sum(1 for r in records if r["used_in_digest"]),
        "dup_of_recent": sum(1 for r in records if r["dup_of_recent"]),
        "vectors": vec_count,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — read-back & AI grounding (best-effort; never raises)
# ─────────────────────────────────────────────────────────────────────────────

def _month_shard_names(today: datetime, n_days: int) -> list:
    """Which monthly shards cover the last n_days: always the current month,
    plus the previous month if the window reaches back into it."""
    months = {today.strftime("%Y-%m")}
    window_start = today - timedelta(days=n_days)
    months.add(window_start.strftime("%Y-%m"))
    return sorted(months, reverse=True)


def fetch_recent_index(base_url: str = PAGES_CORPUS_BASE, n_days: int = 14,
                       timeout: int = 8, local_dir: Path | None = None) -> list:
    """Fetch the 1-2 monthly index shards covering the last n_days.

    Prefers a local file (local_dir) when present — lets the workflow pre-
    download shards — otherwise HTTP GETs from GitHub Pages. Best-effort: any
    failure yields [] and never raises, so the daily send is never blocked.
    Returns compact index rows filtered to the last n_days.
    """
    try:
        today = datetime.now(timezone.utc)
    except Exception:
        return []
    cutoff = (today - timedelta(days=n_days)).strftime("%Y-%m-%d")
    rows = []
    for shard in _month_shard_names(today, n_days):
        fname = f"index_{shard}.json"
        data = None
        if local_dir:
            lp = Path(local_dir) / fname
            if lp.exists():
                try:
                    data = json.loads(lp.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    data = None
        if data is None:
            try:
                resp = requests.get(f"{base_url.rstrip('/')}/{fname}", timeout=timeout)
                if resp.status_code == 200:
                    data = resp.json()
            except (requests.RequestException, ValueError):
                data = None
        if isinstance(data, list):
            rows.extend(r for r in data if str(r.get("date", "")) >= cutoff)
    return rows


def fetch_recent_corpus_urls(base_url: str = PAGES_CORPUS_BASE, n_days: int = 7,
                             timeout: int = 8, local_dir: Path | None = None) -> set:
    """Set of normalized URLs seen in the last n_days — for dup_of_recent
    flagging. Best-effort: {} on any failure."""
    return {_norm_url(r.get("url")) for r in
            fetch_recent_index(base_url, n_days, timeout, local_dir)
            if r.get("url")}


def build_recent_coverage_block(index_rows: list, n_days: int = 7,
                                max_items: int = 40) -> str:
    """Compact, deduplicated prompt block of recently-*published* stories.

    Only rows that made a newsletter (used=True), deduped by title, most
    recent first, capped at max_items. One line each — deliberately no
    summaries or URLs, to keep the prompt small.
    """
    if not index_rows:
        return ""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=n_days)).strftime("%Y-%m-%d")
    except Exception:
        return ""
    published = [r for r in index_rows
                 if r.get("used") and str(r.get("date", "")) >= cutoff]
    published.sort(key=lambda r: str(r.get("date", "")), reverse=True)
    lines, seen_titles = [], set()
    for r in published:
        title = (r.get("title") or "").strip()
        key = title.lower()
        if not title or key in seen_titles:
            continue
        seen_titles.add(key)
        src = (r.get("source") or "").strip()
        lines.append(f"- {r.get('date')} · {src}: {title}")
        if len(lines) >= max_items:
            break
    return "\n".join(lines)
