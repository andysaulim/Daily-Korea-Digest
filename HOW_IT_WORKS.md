# How We Built the Korea Daily Brief

**An automated intelligence briefing delivered at 6 AM ET, every day, to senior policymakers.**

---

## What It Does

The Korea Daily Brief collects news from 140+ sources overnight, synthesizes it through Claude into a structured intelligence briefing, validates the output for accuracy, renders it as a premium HTML email, and delivers it before the morning commute. The entire pipeline runs unattended on GitHub Actions.

Recipients include analysts at CSIS, the State Department, Pentagon, and academic institutions focused on Korean Peninsula affairs.

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌────────────┐     ┌────────────┐     ┌────────────┐
│  COLLECT     │────▶│  DIGEST      │────▶│  VALIDATE  │────▶│  RENDER    │────▶│  SEND      │
│  140+ feeds  │     │  Claude API  │     │  Quality   │     │  HTML      │     │  Gmail     │
│  25 threads  │     │  Sonnet/Opus │     │  gates     │     │  email     │     │  SMTP      │
│  ~15 sec     │     │              │     │  auto-fix  │     │            │     │            │
└─────────────┘     └──────────────┘     └────────────┘     └────────────┘     └────────────┘
       │                    │                    │                  │
       ▼                    ▼                    ▼                  ▼
  Market data         NK-Russia DB        Dedup, URL         GitHub Pages
  Gallup polls        Provocations DB     repair, source     archive
  Sentiment           KCNA baseline       diversity caps     (public/)
```

---

## The Pipeline, Step by Step

### 1. Collection (`collect.py`)

Every morning, 25 parallel threads pull RSS feeds across four tiers:

| Tier | Sources | Window | Examples |
|------|---------|--------|----------|
| **1 — News** | 90+ feeds | 24h | Korea Herald, Reuters, WSJ, NYT, Bloomberg, Yonhap, JTBC, Global Times, Xinhua, TASS |
| **2 — Analysis** | 25 feeds | 36h | CSIS, Brookings, 38 North, Foreign Affairs, The Diplomat, RAND |
| **3 — Academic** | 18 feeds | 72h | International Security, Asian Survey, Pacific Affairs |
| **4 — DPRK** | 4-12 feeds | 24h | KCNA Watch, Rodong Sinmun (via relay), Daily NK, NK News |

Alongside the news, the collector scrapes:
- **Market data**: KOSPI, Brent crude, USD/KRW, BOK rate, CDS spreads, GDP estimates
- **Gallup Korea polling**: Presidential approval, party support, special-topic findings
- **Satellite imagery reports**: Status of 11 monitored DPRK facilities

Output: a structured JSON payload with every article scored and sorted by source prestige.

### 2. Digest Generation (`digest.py`)

The collected payload is sent to **Claude Sonnet** with an 80-line system prompt engineered for zero hallucination. Key prompt rules:

- **SOURCE-OR-SKIP**: Every claim must trace to a collected article. No memory-based assertions.
- **Same-poll-date rule**: All polling numbers must come from the same Gallup Korea survey — no mixing weeks.
- **Prestige enforcement**: WSJ, NYT, FT, and specialist outlets (38 North, ArmsControlWonk) must appear if they published.
- **Reference databases injected**: NK-Russia bilateral timeline (270+ events), NK provocations history (540+ since 1958), 14-day KCNA rhetoric baseline, Kim Jong Un appearance log.

The model outputs structured JSON with ~15 sections: top stories, overnight flash, KCNA analysis, satellite watch, ROK government, trade & tariffs, business, Northeast Asia, public sentiment, statements, op-eds, and more.

If Sonnet's output fails validation (word count < 850, missing sections, duplicates), the system **automatically retries** and escalates to **Claude Opus** on the second attempt.

### 3. Validation & Auto-Fix (`run.py`)

Before sending, the digest passes through quality gates:

- **Dedup**: Keyword overlap + entity matching (same company + same topic = duplicate)
- **URL repair**: Claude sometimes hallucinates Google News URLs — the validator fuzzy-matches headlines to fix them, and drops unfixable ones
- **Source diversity**: Caps any single outlet to 3 appearances per section
- **Prestige check**: Ensures top-tier outlets aren't dropped in favor of wire aggregators
- **Sentiment completeness**: All 4 polling metrics must be present and from the same survey date

Critical failures trigger automatic regeneration (up to 2 retries).

### 4. Rendering (`render.py`)

The validated JSON is converted to a **1,400-line HTML email template** optimized for Gmail, Outlook, and Apple Mail:

- Table-based layout (no CSS grid — email clients don't support it)
- Inline styles throughout (no external stylesheets)
- Color-coded section banners with category-specific accent colors
- Signal badges (ESCALATION, ANOMALY, DEVELOPMENT, CONFIRMATION)
- Market indicator strip with directional arrows
- 2x2 satellite facility grid with status badges
- Responsive mobile layout via media queries
- Dark mode support
- Plain-text fallback for legacy clients

### 5. Delivery (`send_email.py`)

Sent via Gmail SMTP (SSL, port 465) using an app password. The subject line is the digest's RE: line — a one-sentence summary of the day's top themes.

### 6. Archive

Every digest is saved to `/public/` and deployed to GitHub Pages:
- `latest.html` — always the most recent issue
- `digest_YYYY-MM-DD.html` — permanent archive
- `archive.json` — manifest for search and weekly synthesis

---

## Persistent Tracking

The system maintains state across runs via cached JSON files:

| Tracker | Purpose |
|---------|---------|
| `kim_tracker.json` | Confirmed Kim Jong Un public appearances — computes "days since last" |
| `kcna_tracker.json` | 14-day KCNA rhetoric baseline — phrase counts, tone, volume |
| `bp_tracker.json` | 11 DPRK facility statuses (Yongbyon, Punggye-ri, Sohae, Sinpo, etc.) |
| `metrics.jsonl` | Per-run metrics: word count, article counts, validation retries, send status |

These prevent the AI from hallucinating baselines — it gets real historical data instead of guessing.

---

## Automation

**Primary trigger**: An external cron service (cron-job.org) fires a GitHub Actions `workflow_dispatch` at exactly 6:00 AM ET. This avoids GitHub's cron queue delays (which historically pushed delivery to 7-10 AM).

**Fallback crons**: GitHub Actions schedules at 7:30 AM and 9:00 AM ET. A guard step checks if the dispatch already succeeded today and skips if so — preventing duplicate emails.

**Failure alerts**: If the pipeline crashes, a separate email is sent to the operator with a link to the failed GitHub Actions run.

**Weekly summary**: Every Friday at 9 AM ET, a separate workflow fetches the week's 7 daily digests and synthesizes a "Week in Review" briefing.

---

## Notable Design Decisions

**Why structured JSON, not free-form text?**
The AI outputs JSON, not prose. This lets us validate every field programmatically, enforce section minimums, dedup across sections, and render with pixel-perfect control. The HTML template is deterministic — only the data varies.

**Why Sonnet first, Opus on retry?**
Sonnet is faster and cheaper for the 90% of days when the output passes validation on the first try. Opus is reserved for complex news days where Sonnet under-generates or misses nuance.

**Why external cron instead of GitHub Actions cron?**
GitHub's cron scheduler has no SLA — jobs can be delayed 30 minutes to 4 hours depending on runner availability. An external trigger via the GitHub API fires instantly.

**Why persistent trackers instead of asking the AI to remember?**
LLMs can't reliably track state across sessions. Kim Jong Un's last public appearance, KCNA's rhetorical baseline, and satellite facility statuses are facts that change slowly — storing them in JSON and injecting them into the prompt is more reliable than asking the model to recall.

---

## Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12 |
| AI | Claude Sonnet (primary), Claude Opus (retry) via Anthropic API |
| Email | Gmail SMTP with app password |
| Hosting | GitHub Actions (compute), GitHub Pages (archive) |
| Scheduling | cron-job.org (primary), GitHub Actions cron (fallback) |
| Data | RSS/Atom feeds, Google News RSS relay, BOK ECOS API |

---

## Files

| File | Lines | Role |
|------|-------|------|
| `run.py` | 1,122 | Pipeline orchestrator |
| `collect.py` | 1,661 | Parallel RSS scraper + market data |
| `digest.py` | 889 | Claude API integration + prompt |
| `render.py` | 1,408 | HTML email renderer |
| `send_email.py` | 210 | Gmail SMTP sender |
| `databases.py` | 746 | NK-Russia + provocations databases |
| `kim_tracker.py` | 247 | Kim Jong Un appearance tracker |
| `kcna_tracker.py` | 120 | KCNA rhetoric baseline |
| `bp_tracker.py` | 103 | Satellite facility tracker |
| `tension_scorer.py` | 404 | Peninsula tension index (0-10) |
| `weekly.py` | 392 | Friday "Week in Review" synthesis |
| `update_readme.py` | 124 | README stats updater |
