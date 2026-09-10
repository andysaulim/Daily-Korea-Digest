"""
Weekly API cost sheet across every edition.

Each brief records its own spend in its own repository, so no single file
answers "what did last week cost". This reads metrics.jsonl from all of them
through the GitHub API, adds the days up per edition, and mails one table.

    python cost_weekly.py            # print it
    python cost_weekly.py --send     # print and email it
    python cost_weekly.py --days 30

Needs a token in GITHUB_TOKEN or GH_PAT with read access to the editions. A
repository it cannot read is reported as unreachable rather than as zero: an
edition that silently drops out of a cost sheet is how spend goes unnoticed.

The recipient is COST_REPORT_TO. It is deliberately NOT the digest
distribution list — this is an operator's report, not a reader's.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from cost_daily import normalise

# repo -> (label, path to metrics.jsonl within the repo)
EDITIONS = [
    ("Daily-Korea-Digest",                     "Korea",       "metrics.jsonl"),
    ("daily-japan-digest",                     "Japan",       "metrics.jsonl"),
    ("daily-china-digest",                     "China",       "metrics.jsonl"),
    ("daily-australia-pacific-islands-digest", "Australia",   "metrics.jsonl"),
    ("middle-east-digest",                     "Middle East", "pipeline/metrics.jsonl"),
]
OWNER = "andysaulim"
API = "https://api.github.com"


def _token() -> str:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_PAT") or ""


def _get(url: str):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "cost-weekly",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def fetch_metrics(repo: str, path: str) -> tuple[list[dict], str | None]:
    """(rows, problem). Three outcomes worth telling apart, because they call
    for different actions: data, no data yet, and cannot read.

    A repository that has not recorded a run yet is NOT an error — it is a
    zero that will fill in. A repository the token cannot reach is an error,
    and its zero is a lie. Reporting the second as the first is how an edition
    drops out of a cost sheet without anyone noticing.
    """
    import base64
    try:
        meta = _get(f"{API}/repos/{OWNER}/{repo}")
        branch = meta.get("default_branch", "main")
    except urllib.error.HTTPError as e:
        return [], f"repo unreachable, HTTP {e.code}"
    except Exception as e:                                      # noqa: BLE001
        return [], f"repo unreachable, {type(e).__name__}"
    try:
        blob = _get(f"{API}/repos/{OWNER}/{repo}/contents/{path}?ref={branch}")
        raw = base64.b64decode(blob["content"]).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return [], "no runs recorded yet"
        return [], f"HTTP {e.code}"
    except Exception as e:                                      # noqa: BLE001
        return [], type(e).__name__
    rows = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows, None


def window(rows: list[dict], days: int) -> dict:
    """Per-day totals inside the trailing window."""
    cutoff = (datetime.now(ZoneInfo("America/New_York")).date()
              - timedelta(days=days - 1)).isoformat()
    per_day = defaultdict(lambda: {"cost": 0.0, "runs": 0, "calls": 0,
                                   "tin": 0, "tout": 0, "untracked": 0})
    for row in rows:
        day = str(row.get("date", ""))[:10]
        if len(day) != 10 or day < cutoff:
            continue
        d = per_day[day]
        d["runs"] += 1
        u = normalise(row)
        if u is None:
            d["untracked"] += 1
            continue
        d["cost"] += u["est_cost_usd"]
        d["calls"] += u["api_calls"]
        d["tin"] += u["input_tokens"]
        d["tout"] += u["output_tokens"]
    return dict(sorted(per_day.items()))


def collect(days: int) -> tuple[dict, dict]:
    per_edition, errors = {}, {}
    for repo, label, path in EDITIONS:
        rows, err = fetch_metrics(repo, path)
        if err:
            errors[label] = err
        per_edition[label] = window(rows, days)
    return per_edition, errors


def as_text(per_edition: dict, errors: dict, days: int) -> str:
    out = [f"API cost, last {days} days (ET)", ""]
    head = f"{'Edition':<13}{'Days':>5}{'Runs':>6}{'Calls':>7}{'Cost':>10}{'$/day':>8}"
    out += [head, "-" * len(head)]
    grand = 0.0
    for label, per_day in per_edition.items():
        cost = sum(d["cost"] for d in per_day.values())
        runs = sum(d["runs"] for d in per_day.values())
        calls = sum(d["calls"] for d in per_day.values())
        grand += cost
        note = f"   {errors[label]}" if label in errors else ""
        per = cost / len(per_day) if per_day else 0.0
        out.append(f"{label:<13}{len(per_day):>5}{runs:>6}{calls:>7}{cost:>9.2f}{per:>8.2f}{note}")
    out += ["-" * len(head),
            f"{'TOTAL':<13}{'':>5}{'':>6}{'':>7}{grand:>9.2f}",
            "",
            f"Projected monthly at this rate: ${grand / days * 30:.2f}"]
    unreachable = {k: v for k, v in errors.items() if "unreachable" in v or v.startswith("HTTP")}
    if unreachable:
        out += ["", "These contribute zero to the total but are NOT zero: "
                + ", ".join(unreachable), "Check the token's access before trusting it."]
    return "\n".join(out)


def as_html(per_edition: dict, errors: dict, days: int) -> str:
    rows = ""
    grand = 0.0
    for label, per_day in per_edition.items():
        cost = sum(d["cost"] for d in per_day.values())
        runs = sum(d["runs"] for d in per_day.values())
        grand += cost
        per = cost / len(per_day) if per_day else 0.0
        _p = errors.get(label, "")
        warn = ("" if not _p else
                f' <span style="color:{"#B00020" if ("unreachable" in _p or _p.startswith("HTTP")) else "#6B7280"};'
                f'font-weight:{"700" if ("unreachable" in _p or _p.startswith("HTTP")) else "400"};'
                f'font-size:11px;">{_p}</span>')
        rows += (f'<tr><td style="padding:6px 10px;border-bottom:1px solid #EEE;">{label}{warn}</td>'
                 f'<td style="padding:6px 10px;border-bottom:1px solid #EEE;text-align:right;">{runs}</td>'
                 f'<td style="padding:6px 10px;border-bottom:1px solid #EEE;text-align:right;">'
                 f'${cost:.2f}</td>'
                 f'<td style="padding:6px 10px;border-bottom:1px solid #EEE;text-align:right;">'
                 f'${per:.2f}</td></tr>')
    _bad = {k: v for k, v in errors.items() if "unreachable" in v or v.startswith("HTTP")}
    caveat = ("" if not _bad else
              '<p style="font-family:Arial,sans-serif;font-size:12px;color:#B00020;">'
              'An unreachable repository contributes zero to this total but is not zero. '
              'Check the token\'s access before trusting the figure.</p>')
    return f"""<div style="font-family:Georgia,serif;max-width:560px;">
<h2 style="font-size:18px;color:#14181F;margin:0 0 4px;">API cost, last {days} days</h2>
<div style="font-family:Arial,sans-serif;font-size:11px;color:#6B7280;margin-bottom:12px;">
Per edition, ET days. Generated {datetime.now(ZoneInfo("America/New_York")):%A, %B %-d, %Y}.</div>
<table cellpadding="0" cellspacing="0" border="0" width="100%"
       style="font-family:Arial,sans-serif;font-size:13px;border-collapse:collapse;">
<tr style="background:#F2F3F5;">
  <td style="padding:6px 10px;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#6B7280;">Edition</td>
  <td style="padding:6px 10px;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#6B7280;text-align:right;">Runs</td>
  <td style="padding:6px 10px;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#6B7280;text-align:right;">Cost</td>
  <td style="padding:6px 10px;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#6B7280;text-align:right;">$/day</td>
</tr>
{rows}
<tr><td style="padding:8px 10px;font-weight:700;">Total</td><td></td>
<td style="padding:8px 10px;text-align:right;font-weight:700;">${grand:.2f}</td>
<td style="padding:8px 10px;text-align:right;color:#6B7280;">${grand / days:.2f}</td></tr>
</table>
<p style="font-family:Arial,sans-serif;font-size:12px;color:#4A5260;">
Projected monthly at this rate: <strong>${grand / days * 30:.2f}</strong></p>
{caveat}</div>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--send", action="store_true")
    args = ap.parse_args()

    if not _token():
        print("No GITHUB_TOKEN / GH_PAT set; cannot read the editions.")
        return 1

    per_edition, errors = collect(args.days)
    print(as_text(per_edition, errors, args.days))

    if args.send:
        to = os.environ.get("COST_REPORT_TO", "").strip()
        if not to:
            print("\nCOST_REPORT_TO is not set; not sending.")
            return 1
        # Guard: this is an operator's report. Mailing it to the reader list
        # would put internal spend in front of the distribution.
        dist = os.environ.get("DIGEST_TO", "")
        if dist and any(a.strip() and a.strip() in dist for a in to.split(",")):
            print("\nCOST_REPORT_TO overlaps DIGEST_TO; refusing to send.")
            return 1
        from send_email import send
        stamp = datetime.now(ZoneInfo("America/New_York")).strftime("%A, %B %-d, %Y")
        send(as_html(per_edition, errors, args.days),
             subject=f"Digest API cost | {stamp}",
             recipients=[a.strip() for a in to.split(",") if a.strip()])
        print(f"\nSent to {to}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
