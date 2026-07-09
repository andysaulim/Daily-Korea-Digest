"""
Weekly pipeline health check-in.

A standalone status reporter (does NOT run the pipeline). Run by the
corpus-healthcheck.yml workflow once a week; emails alim@csis.org a short
status covering the things that quietly rot: the article corpus accumulating,
AI-grounding populating, month-to-date API cost, model-ID deprecation, and
Gallup-baseline staleness.

Reuses existing pieces rather than re-implementing:
  - gallup_update._load_baseline / _baseline_age_days  → baseline staleness
  - gallup_update._email_operator                      → SSL smtplib send to operator
  - pipeline_health.check_model_deprecation            → retired model IDs
  - cost_report.load_metrics / monthly_breakdown       → MTD API cost
  - corpus.fetch_recent_index                          → corpus/grounding health

Exit code is always 0 — a health-check failure must not fail the workflow.
Run `python healthcheck.py --print` to see the report without emailing.
"""
import sys
from datetime import datetime, timezone


def _recent_corpus_days(n_days: int = 7) -> tuple[int, int]:
    """(#distinct days recorded in the last n_days, #published articles seen).
    Prefers shards the workflow downloaded to public/corpus/, else HTTP from
    Pages. (0, 0) if none / unreachable."""
    try:
        from pathlib import Path
        from corpus import fetch_recent_index
        local = Path("public/corpus") if Path("public/corpus").exists() else None
        rows = fetch_recent_index(n_days=n_days, local_dir=local)
    except Exception:
        return 0, 0
    days = {str(r.get("date", "")) for r in rows if r.get("date")}
    published = sum(1 for r in rows if r.get("used"))
    return len(days), published


def _mtd_cost() -> tuple[float, int]:
    """(month-to-date est. cost USD, tracked runs) from metrics.jsonl."""
    try:
        from cost_report import load_metrics, monthly_breakdown
        months = monthly_breakdown(load_metrics())
    except Exception:
        return 0.0, 0
    if not months:
        return 0.0, 0
    this_month = datetime.now(timezone.utc).strftime("%Y-%m")
    m = months.get(this_month) or list(months.values())[-1]
    return round(m.get("est_cost_usd", 0.0), 2), m.get("tracked_runs", 0)


def _grounding_depth() -> int | None:
    """Lines of RECENT COVERAGE context in the most recent tracked run, or None."""
    try:
        from cost_report import load_metrics
        rows = load_metrics()
    except Exception:
        return None
    for row in reversed(rows):
        if "recent_coverage_lines" in row:
            return row["recent_coverage_lines"]
    return None


def _gallup_status() -> tuple[str, int | None]:
    """(poll label, baseline age in days)."""
    try:
        from gallup_update import _load_baseline, _baseline_age_days
        bl = _load_baseline()
        return bl.get("poll", "?"), _baseline_age_days(bl)
    except Exception:
        return "?", None


def _model_alerts() -> list[str]:
    try:
        from pipeline_health import check_model_deprecation
        return [w["message"] for w in check_model_deprecation()]
    except Exception:
        return []


def build_report() -> tuple[str, str, bool]:
    """Assemble the check-in. Returns (subject, body, any_problem)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"Korea Daily Brief — weekly check-in ({now} UTC)", ""]
    problems = []

    # Corpus accumulation (from the Pages index) and grounding depth (from
    # local metrics) are independent signals — report both regardless.
    days, published = _recent_corpus_days(7)
    if days == 0:
        lines.append("📦  Corpus: no days recorded in the last 7 days.")
        lines.append("     (Expected while the corpus is brand new — it starts")
        lines.append("      accumulating from the first daily run after deploy.)")
        problems.append("corpus not accumulating")
    else:
        lines.append(f"📦  Corpus: {days}/7 recent days recorded, "
                     f"{published} published articles indexed.")

    depth = _grounding_depth()
    if depth is None:
        lines.append("🔁  Grounding: no run has logged coverage depth yet.")
    elif depth == 0:
        lines.append("🔁  Grounding: last run had an EMPTY recent-coverage block "
                     "(needs ≥2 days of corpus).")
    else:
        lines.append(f"🔁  Grounding: last run fed {depth} prior stories into "
                     "the prompt — precedent-citation active.")

    # Cost
    cost, runs = _mtd_cost()
    if runs:
        lines.append(f"💰  API cost month-to-date: ${cost:.2f} over {runs} runs.")
    else:
        lines.append("💰  API cost: no tracked runs this month yet.")

    # Gallup baseline
    poll, age = _gallup_status()
    if age is None:
        lines.append(f"📊  Gallup baseline: {poll} (age unknown).")
    else:
        flag = ""
        if age > 30:
            flag = "  ⚠ STALE — refresh due"; problems.append("Gallup baseline stale")
        elif age > 14:
            flag = "  ⚠ getting old"
        lines.append(f"📊  Gallup baseline: {poll}, {age} days old.{flag}")

    # Model deprecation
    model_alerts = _model_alerts()
    if model_alerts:
        lines.append("🚨  Model IDs:")
        for m in model_alerts:
            lines.append(f"     - {m}")
        problems.append("model deprecation risk")
    else:
        lines.append("🤖  Model IDs: all current.")

    lines.append("")
    lines.append("Corpus: https://andysaulim.github.io/Daily-Korea-Digest/corpus.html")
    lines.append("This is your automated weekly nudge to glance at the above.")
    if problems:
        lines.insert(1, f"⚠ Needs attention: {', '.join(problems)}\n")

    status = "⚠ ATTENTION" if problems else "✓ healthy"
    subject = f"Korea Daily Brief — weekly check-in ({status})"
    return subject, "\n".join(lines), bool(problems)


def main() -> int:
    print_only = "--print" in sys.argv
    try:
        subject, body, _problem = build_report()
    except Exception as e:
        print(f"Health check failed to assemble report: {e}")
        return 0
    print(subject)
    print("-" * len(subject))
    print(body)
    if not print_only:
        try:
            from gallup_update import _email_operator
            _email_operator(subject, body)
        except Exception as e:
            print(f"  ⚠ Email send failed: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
