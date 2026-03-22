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
from pathlib import Path
from datetime import datetime, timezone


def validate_digest(digest: dict) -> list[str]:
    """Pre-send quality gate. Returns list of warnings (empty = all clear)."""
    warnings = []

    # ── Top stories must have 2-4 items ──────────────────────────────────
    top_stories = digest.get("top_stories") or []
    if len(top_stories) < 2:
        warnings.append(f"TOP STORIES: only {len(top_stories)} (expected 2-4)")
    elif len(top_stories) > 4:
        warnings.append(f"TOP STORIES: {len(top_stories)} items (expected 2-4)")

    # ── RE: line must be present and substantive ─────────────────────────
    re_line = digest.get("re_line")
    if not re_line or len(str(re_line).strip()) < 10:
        warnings.append("RE: LINE: missing or too short")

    # ── Morning memo must have 3 items ───────────────────────────────────
    memo = digest.get("morning_memo") or []
    if len(memo) < 3:
        warnings.append(f"MORNING MEMO: only {len(memo)} items (expected 3)")

    # ── Word count check (~800 words target) ─────────────────────────────
    word_count = 0
    for section_key in ("top_stories", "overnight_items", "also_today",
                         "business_economy", "social_statements", "northeast_asia"):
        for item in (digest.get(section_key) or []):
            for field in ("body", "body_text", "summary", "detail", "quote_text",
                          "so_what", "pattern_note"):
                word_count += len(str(item.get(field, "")).split())
    for mi in (digest.get("morning_memo") or []):
        word_count += len(str(mi).split())
    kcna = digest.get("kcna_delta") or {}
    for field in ("bottom_line", "doctrinal_shift"):
        word_count += len(str(kcna.get(field, "")).split())
    if word_count < 700:
        warnings.append(f"WORD COUNT CRITICAL: ~{word_count} words (hard minimum 800)")
    elif word_count < 800:
        warnings.append(f"WORD COUNT: ~{word_count} words (hard minimum 800)")

    # ── Check for placeholder URLs ("#", empty, non-http) ────────────────
    bad_urls = 0
    for section_key in ("top_stories", "overnight_items", "also_today",
                         "business_economy", "opeds_today", "academic_today",
                         "social_statements", "northeast_asia"):
        for item in (digest.get(section_key) or []):
            url = item.get("url", "")
            if url and (url == "#" or not url.startswith("http")):
                bad_urls += 1
    if bad_urls:
        warnings.append(f"BAD URLS: {bad_urls} placeholder or invalid URLs found")

    # ── Check for duplicate URLs across sections ─────────────────────────
    seen_urls = {}
    for section_key in ("top_stories", "overnight_items", "also_today",
                         "business_economy", "northeast_asia"):
        for item in (digest.get(section_key) or []):
            url = item.get("url", "")
            if url and url.startswith("http"):
                if url in seen_urls:
                    warnings.append(
                        f"DUPLICATE: URL appears in both {seen_urls[url]} and {section_key}")
                    break
                seen_urls[url] = section_key

    # ── Check for "None" strings in critical fields ──────────────────────
    val = digest.get("re_line")
    if str(val).strip() == "None":
        warnings.append('NONE STRING: "re_line" field contains literal "None"')

    # ── Digest date matches today ────────────────────────────────────────
    digest_date = digest.get("digest_date", "")
    today_str = datetime.now(timezone.utc).strftime("%A, %d %B %Y")
    if digest_date and digest_date != today_str:
        warnings.append(f"DATE MISMATCH: digest says '{digest_date}', today is '{today_str}'")

    # ── Public sentiment must have all 4 metrics ─────────────────────────
    sentiment = digest.get("public_sentiment") or {}
    for key in ("presidential_approval", "party_ruling", "party_opposition", "party_independent"):
        data = sentiment.get(key) or {}
        if not data.get("value"):
            warnings.append(f"SENTIMENT: {key} has no value")

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
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
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
    validation_warnings = validate_digest(digest_data)
    if validation_warnings:
        print("\n⚠️  PRE-SEND VALIDATION WARNINGS:")
        for w in validation_warnings:
            print(f"    • {w}")
        print()
    else:
        print("\n✅  Validation passed — all checks OK")

    # ── Step 2b: Push flagged entries to databases ────────────────────────────
    if not args.no_push:
        push_summary = process_digest_entries(digest_data)
    else:
        print("\n  --no-push: skipping database updates")

    # ── Step 3: Render HTML ──────────────────────────────────────────────────
    from render import render

    # Inject web URL for "Read Online" link (set via env or GitHub Pages)
    web_base = os.environ.get("WEB_URL", "")
    if web_base:
        digest_data["web_url"] = web_base.rstrip("/") + "/latest.html"

    html = render(digest_data)

    date_slug = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
    if args.no_send:
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
