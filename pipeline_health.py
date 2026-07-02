"""
Pipeline health monitor.

Runs after each digest to surface latent problems before they cause silent
failures. Prints warnings inline and returns a structured health report
that gets written to metrics.jsonl and (optionally) emailed weekly.

Watches for:
  - Gallup baseline staleness (>14 days = warn, >30 days = alert)
  - Model deprecation risk (unknown model IDs = alert)
  - Feed source diversity (any tier collecting <50% of expected count)
  - Prestige outlet coverage gaps
  - Fallback overuse (using canned sentiment values instead of live data)
"""
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


GALLUP_STALE_DAYS = 14
GALLUP_ALERT_DAYS = 30

TIER_EXPECTED_MIN = {
    "tier1": 60,
    "tier2": 10,
    "tier3": 3,
    "tier4": 3,
}

PRESTIGE_SOURCES = {
    "Wall Street Journal", "WSJ", "New York Times", "NYT",
    "Bloomberg", "Financial Times", "FT", "Reuters",
    "Washington Post", "WaPo", "The Economist",
}

KNOWN_MODEL_IDS = {
    "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
    "claude-sonnet-4-6", "claude-sonnet-4-5",
    "claude-haiku-4-5",
    "claude-fable-5",
}


def _parse_gallup_date(last_updated: str) -> datetime | None:
    """Parse strings like 'June 9-11, 2026' or 'May 19-21, 2026'."""
    if not last_updated:
        return None
    m = re.match(r"(\w+)\s+(\d+)(?:-\d+)?,\s+(\d{4})", last_updated)
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}",
                                 "%B %d %Y").replace(tzinfo=ZoneInfo("America/New_York"))
    except ValueError:
        return None


def check_gallup_staleness(digest: dict) -> list[dict]:
    """Warn if the Gallup baseline is old."""
    warnings = []
    sentiment = digest.get("public_sentiment") or {}
    approval = sentiment.get("presidential_approval") or {}
    last_updated = approval.get("last_updated", "")
    dt = _parse_gallup_date(last_updated)
    if not dt:
        warnings.append({
            "severity": "warn",
            "check": "gallup_staleness",
            "message": f"Cannot parse Gallup baseline date: {last_updated!r}",
        })
        return warnings
    now = datetime.now(ZoneInfo("America/New_York"))
    age_days = (now - dt).days
    if age_days > GALLUP_ALERT_DAYS:
        warnings.append({
            "severity": "alert",
            "check": "gallup_staleness",
            "message": (f"Gallup baseline is {age_days} days old ({last_updated}). "
                        f"Update collect.py + digest.py with fresh poll."),
            "age_days": age_days,
        })
    elif age_days > GALLUP_STALE_DAYS:
        warnings.append({
            "severity": "warn",
            "check": "gallup_staleness",
            "message": f"Gallup baseline is {age_days} days old ({last_updated}). Refresh due.",
            "age_days": age_days,
        })
    return warnings


def check_model_deprecation() -> list[dict]:
    """Warn if the code references model IDs not in the known-current set."""
    warnings = []
    for filename in ("digest.py", "weekly.py"):
        path = Path(filename)
        if not path.exists():
            continue
        text = path.read_text()
        found = set(re.findall(r'"(claude-[a-z0-9-]+)"', text))
        for model_id in found:
            if model_id not in KNOWN_MODEL_IDS:
                warnings.append({
                    "severity": "alert",
                    "check": "model_deprecation",
                    "message": (f"{filename} references {model_id!r} which is not in the "
                                "known-current model set. Verify it hasn't been retired."),
                    "file": filename,
                    "model_id": model_id,
                })
    return warnings


def check_tier_coverage(payload: dict) -> list[dict]:
    """Warn if any tier collected under its expected minimum."""
    warnings = []
    for tier, expected in TIER_EXPECTED_MIN.items():
        actual = len(payload.get(tier, []))
        if actual < expected:
            warnings.append({
                "severity": "warn" if actual >= expected // 2 else "alert",
                "check": "tier_coverage",
                "message": (f"{tier} collected {actual} items (expected ≥{expected}). "
                            "Feed loss likely."),
                "tier": tier,
                "actual": actual,
                "expected": expected,
            })
    return warnings


def check_prestige_coverage(digest: dict) -> list[dict]:
    """Warn if no prestige outlet appears in the digest despite the mandatory rule."""
    warnings = []
    seen_prestige = set()
    for section_key in ("top_stories", "overnight_items", "also_today",
                        "business_economy", "northeast_asia", "opeds_today"):
        for item in (digest.get(section_key) or []):
            src = (item.get("source") or "").strip()
            for prestige in PRESTIGE_SOURCES:
                if prestige.lower() in src.lower():
                    seen_prestige.add(prestige)
    if not seen_prestige:
        warnings.append({
            "severity": "warn",
            "check": "prestige_coverage",
            "message": ("No prestige outlets (WSJ/NYT/FT/Bloomberg/Reuters/etc.) in "
                        "today's digest. Verify feeds are collecting."),
        })
    return warnings


def check_sentiment_fallbacks(digest: dict) -> list[dict]:
    """Warn if the public sentiment values match the hardcoded fallback baseline.

    Signal that live scraping failed and we're rendering canned data.
    """
    warnings = []
    sentiment = digest.get("public_sentiment") or {}
    approval = sentiment.get("presidential_approval") or {}
    ruling = sentiment.get("party_ruling") or {}
    last_updated = approval.get("last_updated", "")
    fallback_source_hint = ruling.get("source", "")
    if "Gallup Korea" in fallback_source_hint and last_updated:
        dt = _parse_gallup_date(last_updated)
        if dt:
            age_days = (datetime.now(ZoneInfo("America/New_York")) - dt).days
            if age_days >= GALLUP_STALE_DAYS:
                warnings.append({
                    "severity": "warn",
                    "check": "sentiment_fallbacks",
                    "message": ("Sentiment likely from fallback baseline (age "
                                f"{age_days} days). Live Gallup scrape may be broken."),
                })
    return warnings


def run_health_checks(digest: dict, payload: dict) -> dict:
    """Run all health checks. Returns a report dict."""
    all_warnings = []
    all_warnings.extend(check_gallup_staleness(digest))
    all_warnings.extend(check_model_deprecation())
    all_warnings.extend(check_tier_coverage(payload))
    all_warnings.extend(check_prestige_coverage(digest))
    all_warnings.extend(check_sentiment_fallbacks(digest))

    alerts = [w for w in all_warnings if w["severity"] == "alert"]
    warns = [w for w in all_warnings if w["severity"] == "warn"]

    if all_warnings:
        print("\n🩺  Pipeline health checks:")
        for w in alerts:
            print(f"    🚨  ALERT: {w['message']}")
        for w in warns:
            print(f"    ⚠  WARN:  {w['message']}")
    else:
        print("\n🩺  Pipeline health checks: all clear")

    return {
        "checked_at": datetime.now(ZoneInfo("America/New_York")).isoformat(),
        "alerts": alerts,
        "warnings": warns,
        "all_clear": not all_warnings,
    }
