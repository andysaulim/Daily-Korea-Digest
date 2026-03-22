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
from digest import _count_digest_words


_PRESTIGE_OUTLETS = {"WSJ", "Wall Street Journal", "Washington Post", "WaPo", "NYT",
                      "New York Times", "Bloomberg", "Financial Times", "FT", "Economist", "The Economist"}

_STOP_WORDS = frozenset({"the", "a", "an", "in", "on", "of", "to", "for", "and", "is", "at", "by", "as", "with", "from"})

# All sections that contain items with URLs/headlines
_ALL_ITEM_SECTIONS = ("top_stories", "overnight_items", "also_today",
                       "business_economy", "opeds_today", "academic_today",
                       "social_statements", "northeast_asia")


def validate_digest(digest: dict, payload: dict | None = None) -> list[str]:
    """Pre-send quality gate. Returns list of warnings (empty = all clear)."""
    warnings = []

    # ── Section count checks ──────────────────────────────────────────────
    top_stories = digest.get("top_stories") or []
    if len(top_stories) < 3:
        warnings.append(f"TOP STORIES CRITICAL: only {len(top_stories)} (expected 3-4)")
    elif len(top_stories) > 4:
        warnings.append(f"TOP STORIES: {len(top_stories)} items (expected 3-4)")

    overnight = digest.get("overnight_items") or []
    if len(overnight) < 8:
        warnings.append(f"OVERNIGHT ITEMS CRITICAL: only {len(overnight)} (expected 8-12)")
    elif len(overnight) > 12:
        warnings.append(f"OVERNIGHT ITEMS: {len(overnight)} items (expected 8-12)")

    memo = digest.get("morning_memo") or []
    if len(memo) < 3:
        warnings.append(f"MORNING MEMO CRITICAL: only {len(memo)} items (expected 3)")

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
    seen_headlines = []  # (section, headline_text, keyword_set)
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

            # Duplicate headline check
            headline = (item.get("headline", "") or "").lower().strip()
            if len(headline) > 20:
                words = {w for w in re.split(r'\W+', headline) if len(w) > 2 and w not in _STOP_WORDS}
                for prev_section, prev_headline, prev_words in seen_headlines:
                    if not words or not prev_words:
                        continue
                    overlap = words & prev_words
                    min_len = min(len(words), len(prev_words))
                    if min_len > 1 and len(overlap) >= 2 and len(overlap) / min_len >= 0.5:
                        warnings.append(
                            f"DUPLICATE HEADLINE: similar story in {prev_section} and {section_key}: "
                            f"'{headline[:60]}...' vs '{prev_headline[:60]}...'")
                        break
                seen_headlines.append((section_key, headline, words))

    if bad_urls:
        warnings.append(f"BAD URLS: {bad_urls} placeholder or invalid URLs found")
    if empty_body_count:
        warnings.append(f"EMPTY BODIES: {empty_body_count} items have no substantive body text")

    # Source diversity
    for src, count in source_counts.items():
        if count > 3:
            warnings.append(
                f"SOURCE DIVERSITY: '{src}' appears {count} times across top sections — diversify sources")

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
    if payload:
        prestige_in_input = set()
        for a in (payload.get("tier1") or []):
            src = (a.get("source") or "").strip()
            if any(p.lower() in src.lower() for p in _PRESTIGE_OUTLETS):
                prestige_in_input.add(src)
        digest_sources = set()
        for section_key in ("top_stories", "overnight_items", "also_today"):
            for item in (digest.get(section_key) or []):
                digest_sources.add((item.get("source") or "").strip())
        for src in prestige_in_input:
            if not any(src.lower() in ds.lower() or ds.lower() in src.lower() for ds in digest_sources):
                warnings.append(
                    f"PRESTIGE OUTLET DROPPED: '{src}' had Korea articles in input but none appeared in digest")

    return warnings


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

    # ── Step 2: Generate digest via Claude ───────────────────────────────────
    from digest import generate_digest
    digest_data = generate_digest(payload, db_context=db_context)
    Path("digest.json").write_text(json.dumps(digest_data, ensure_ascii=False, indent=2))

    # ── Step 2+: Update Kim Jong Un appearance tracker ───────────────────────
    from kim_tracker import update_from_digest
    update_from_digest(digest_data)

    # ── Step 2a: Pre-send validation gate ─────────────────────────────────────
    validation_warnings = validate_digest(digest_data, payload=payload)
    critical_warnings = [w for w in validation_warnings if "CRITICAL" in w]
    if validation_warnings:
        print("\n⚠️  PRE-SEND VALIDATION WARNINGS:")
        for w in validation_warnings:
            print(f"    • {w}")
        print()
    else:
        print("\n✅  Validation passed — all checks OK")
    if critical_warnings:
        print("🚫  CRITICAL validation failures — newsletter will NOT be sent.")
        print("    Fix the issues above or re-run. HTML still rendered for review.")

    # ── Step 2b: Push flagged entries to databases ────────────────────────────
    if not args.no_push:
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
