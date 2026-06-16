# Korea Daily Brief

Automated intelligence briefing on Korean Peninsula affairs, delivered daily at 6 AM ET to senior policymakers and analysts.

## Architecture

```
COLLECT (140+ RSS feeds, 25 threads) → DIGEST (Claude Sonnet/Opus) → VALIDATE (dedup, URL repair, source caps) → RENDER (HTML email) → SEND (Gmail SMTP)
```

Orchestrated by `run.py`. Triggered via external cron (cron-job.org) → GitHub Actions `workflow_dispatch`, with fallback crons at 7:30 and 9:00 AM ET.

## Key Files

| File | Role |
|------|------|
| `run.py` | Pipeline orchestrator — runs collect → digest → validate → render → send |
| `collect.py` | Parallel RSS scraper, market data (KOSPI, KRW, Brent), Gallup Korea polling, satellite imagery |
| `digest.py` | Claude API integration — 80-line system prompt, structured JSON output, Sonnet-first with Opus retry |
| `render.py` | 1,400-line HTML email renderer — table-based layout, inline CSS, dark mode, mobile responsive |
| `send_email.py` | Gmail SMTP sender (SSL, port 465) |
| `databases.py` | NK-Russia bilateral timeline (270+ events), NK provocations history (540+ since 1958) |
| `kim_tracker.py` | Kim Jong Un appearance log — computes "days since last seen" |
| `kcna_tracker.py` | 14-day KCNA rhetoric baseline — phrase counts, tone shifts |
| `bp_tracker.py` | 11 DPRK facility statuses (Yongbyon, Punggye-ri, Sohae, Sinpo, etc.) |
| `tension_scorer.py` | Peninsula tension index (0–10 scale) |
| `weekly.py` | Friday "Week in Review" synthesis from the week's 7 daily digests |
| `update_readme.py` | Auto-updates README with latest run stats |

## Persistent State

Tracker files (`kim_tracker.json`, `kcna_tracker.json`, `bp_tracker.json`, `metrics.jsonl`) are cached across GitHub Actions runs. They prevent the AI from hallucinating baselines — real historical data is injected into the prompt instead.

## Feed Tiers

- **Tier 1 (News, 24h window)**: Korea Herald, Reuters, WSJ, NYT, Bloomberg, Yonhap, JTBC, Global Times, Xinhua, TASS
- **Tier 2 (Analysis, 36h)**: CSIS, Brookings, 38 North, Foreign Affairs, The Diplomat, RAND
- **Tier 3 (Academic, 72h)**: International Security, Asian Survey, Pacific Affairs
- **Tier 4 (DPRK, 24h)**: KCNA Watch, Rodong Sinmun, Daily NK, NK News

## Critical Rules

- **SOURCE-OR-SKIP**: Every claim in the digest must trace to a collected article. No memory-based assertions.
- **Same-poll-date rule**: All polling numbers must come from the same Gallup Korea survey — never mix weeks.
- **Prestige enforcement**: WSJ, NYT, FT, and specialist outlets (38 North, ArmsControlWonk) must appear if they published.
- Gallup Korea baselines in `collect.py` and `digest.py` need periodic manual updates when new polls release (weekly on Fridays).
- Lee Jae-myung inaugurated **June 3, 2025** (snap election after Yoon impeachment).

## Stack

Python 3.12, Anthropic API (Claude Sonnet primary / Opus retry), Gmail SMTP, GitHub Actions + GitHub Pages, cron-job.org for scheduling.

## Running Locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
export GMAIL_USER=...
export GMAIL_APP_PASS=...
export DIGEST_TO=...
python run.py
```

## Commands

- `/newsletter` — Full architecture reference and how each pipeline stage works
