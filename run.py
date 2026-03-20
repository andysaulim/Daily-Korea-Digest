"""
Korea Intelligence Digest — Main Runner
Beyond Parallel × CSIS Korea Chair
Orchestrates: collect → digest → render → send
Usage:
  python run.py              # Full pipeline (collect + digest + render + send)
  python run.py --no-send    # Render to file only, no email
  python run.py --from-cache # Skip collection, use existing collected.json
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone


def main():
    parser = argparse.ArgumentParser(description="Korea Intelligence Digest pipeline")
    parser.add_argument("--no-send",    action="store_true", help="Render to file only, do not send email")
    parser.add_argument("--from-cache", action="store_true", help="Skip collection, use existing collected.json")
    parser.add_argument("--dry-run",    action="store_true", help="Collect only, don't call Claude")
    args = parser.parse_args()

    print("=" * 60)
    print("  Korea Intelligence Digest")
    print("  Beyond Parallel × CSIS Korea Chair")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # ── Step 1: Collect ───────────────────────────────────────────────────────
    if args.from_cache and Path("collected.json").exists():
        print("\n📦  Using cached collection (collected.json)")
        payload = json.loads(Path("collected.json").read_text())
        total = sum(len(v) for v in payload.values())
        print(f"  {total} articles loaded from cache")
    else:
        from collect import collect
        payload = collect()
        Path("collected.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.dry_run:
        print("\n  --dry-run: stopping after collection. See collected.json")
        return

    # ── Step 2: Generate digest via Claude ───────────────────────────────────
    from digest import generate_digest
    digest_data = generate_digest(payload)
    Path("digest.json").write_text(json.dumps(digest_data, ensure_ascii=False, indent=2))

    # ── Step 3: Render HTML ──────────────────────────────────────────────────
    from render import render
    html = render(digest_data)

    date_slug = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path  = Path(f"digest_{date_slug}.html")
    out_path.write_text(html, encoding="utf-8")
    print(f"\n📄  HTML rendered: {out_path} ({len(html):,} bytes)")

    # Also write latest.html for convenience
    Path("latest.html").write_text(html, encoding="utf-8")

    # ── Step 4: Send email ───────────────────────────────────────────────────
    if args.no_send:
        print("\n  --no-send: skipping email. Open latest.html to review.")
    else:
        from send_email import send
        send(html)

    print("\n✅  Done.\n")


if __name__ == "__main__":
    main()
