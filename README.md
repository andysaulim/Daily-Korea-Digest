# Korea Daily Brief

Automated daily intelligence briefing on the Korean Peninsula for CSIS Korea Chair. Collects from 140+ sources, generates an analyst-grade digest via Claude, and delivers a styled HTML email at 6:00 AM ET.

**Live archive:** [andysaulim.github.io/Daily-Korea-Digest](https://andysaulim.github.io/Daily-Korea-Digest)

---

<!-- STATS:START -->
## Latest Run

| Metric | Value |
|--------|-------|
| Last generated | April 4, 2026 at 7:55 AM ET |
| Digest date | Saturday, April 4, 2026 |
| Articles collected | 43 |
| Unique sources | 20 |
| Top stories | 3 |
| Overnight items | 3 |
| Word count | ~891 |
| Kim Jong Un appeared | Yes |

<!-- STATS:END -->

## How It Works

```
collect.py          digest.py           render.py          send_email.py
140+ RSS feeds  -->  Claude Sonnet  -->  HTML email  -->  Gmail SMTP
  + market data       (Opus retry)       + archive        + GitHub Pages
  + sentiment          + CSIS databases   (public/)
  + KCNA                (NK-Russia,
                         provocations)
```

**Pipeline steps:**

1. **Collect** -- Scrapes 140+ RSS feeds in parallel across 4 tiers, plus market data (KOSPI, Brent, USD/KRW, BOK rate, exports, GDP) and Gallup Korea polling
2. **Enrich** -- Fetches CSIS databases from GitHub: NK-Russia bilateral timeline (270+ events) and NK provocations database (540+ events since 1958)
3. **Digest** -- Claude Sonnet generates the initial briefing; Opus escalates on retry if content minimums aren't met (target 1,200-1,400 words)
4. **Validate** -- Pre-send quality gate checks word count, source diversity, duplicates, prestige outlet inclusion, and data integrity. Validation retries use Sonnet first, Opus if needed.
5. **Render** -- Converts digest JSON to a table-based HTML email optimized for Gmail, Outlook, and Apple Mail
6. **Send** -- Delivers via Gmail SMTP with retry logic
7. **Archive** -- Pushes to GitHub Pages for web access

---

## Source Coverage

| Tier | Sources | Window | Content |
|------|---------|--------|---------|
| **1 -- News** | 90+ feeds | 24h | Korean dailies, wire services, international correspondents, government feeds, broadcast |
| **2 -- Analysis** | 25 feeds | 36h | Think tanks (CSIS, Brookings, Carnegie, RAND, CFR, 38 North) with A/B/C prestige tiers |
| **3 -- Academic** | 18 feeds | 72h | Journals (International Security, World Politics, Asian Survey) with A+/A/B tiers |
| **4 -- DPRK** | 4 feeds | 24h | KCNA Watch, Rodong Sinmun, official state media |

**Korean-language sources:** 조선일보, 한겨레, 동아일보, 경향신문, 뉴스1, 연합뉴스, 매일경제, 한국경제, plus broadcast (JTBC, KBS, MBC, SBS, YTN, Channel A). Titles translated to English in the digest.

**Korean English-language sources:** Korea Herald, Korea Times, Arirang News, Korea Economic Daily, Yonhap English, JoongAng Daily, Chosun English, Hankyoreh English, Dong-A English.

**Prestige outlet rule:** Korea stories from WSJ, NYT, Washington Post, Bloomberg, Financial Times, The Economist, CNN, Reuters, CNBC, and MSNBC are always included.

---

## Newsletter Sections

| Section | Description |
|---------|-------------|
| Market Indicators | KOSPI, Brent crude, USD/KRW, BOK rate, exports, GDP |
| Morning Memo | Top 3 stories at a glance (one sentence each) |
| Top Stories | 3-4 biggest hard news stories with "So what" and historical pattern notes |
| Overnight Flash | 8-12 secondary items across all categories |
| US-Korea Deals | Tariff tracker (sector-level: Section 232 steel/auto/semicon, Section 122 surcharge), $350B investment package, trade policy actions (hyperlinked to sources) |
| Business & Economy | Conglomerate moves, M&A, macro indicators |
| Northeast Asia | Japan-Korea, China-Korea, Russia-Korea, trilateral developments |
| KCNA Rhetoric Delta | Propaganda analysis: phrase frequency, tone shifts, doctrinal changes, Kim appearances |
| ROK Government | Ministry-level actions (MOFA, MND, MOU, MOTIE, NIS) |
| Public Sentiment | Presidential approval, party support, Gallup Korea spotlight |
| Social Statements | Direct quotes from senior officials with analyst context |
| Op-Eds & Academic | Think tank commentary and journal articles |
| Calendar Watch | Upcoming events in the next 14-30 days |
| Satellite & Location Watch | 11 monitored locations with status tracking; satellite imagery articles get dual placement as standalone news stories |

---

## Setup

### Prerequisites

- Python 3.12+
- Anthropic API key (Claude Sonnet)
- Gmail account with app password
- GitHub PAT (for database integration and Pages deployment)

### Install

```bash
git clone https://github.com/andysaulim/Daily-Korea-Digest.git
cd Daily-Korea-Digest
pip install -r requirements.txt
```

### Environment Variables

```bash
export ANTHROPIC_API_KEY="sk-ant-..."        # Claude API
export GMAIL_USER="you@gmail.com"            # Sender address
export GMAIL_APP_PASS="xxxx xxxx xxxx xxxx"  # Gmail app password
export DIGEST_TO="recipient1@example.com,recipient2@example.com"
export GITHUB_TOKEN="ghp_..."               # GitHub PAT (repo write)
export WEB_URL="https://yourname.github.io/Daily-Korea-Digest"  # Optional
```

### Run

```bash
python run.py                # Full pipeline: collect -> digest -> render -> send
python run.py --dry-run      # Collection only (outputs collected.json)
python run.py --from-cache   # Skip collection, reuse collected.json
python run.py --no-send      # Generate HTML but don't email
python run.py --no-push      # Skip GitHub database updates
```

---

## Automated Schedule

The GitHub Actions workflow (`.github/workflows/daily-digest.yml`) runs daily at **7:00 AM ET** (with a 7:30 AM fallback) and can be triggered manually via `workflow_dispatch`.

Required repository secrets:

| Secret | Purpose |
|--------|---------|
| `ANTHROPIC_API_KEY` | Claude API access |
| `GMAIL_USER` | Sender email |
| `GMAIL_APP_PASS` | Gmail app password |
| `DIGEST_TO` | Recipient list (comma-separated) |
| `GH_PAT` | GitHub PAT for Pages deploy and database writes |

---

## Validation Gates

Before sending, the digest passes through automated checks:

- **Word count**: Hard minimum 1,000 words (target 1,200-1,400)
- **Section minimums**: 3-4 top stories, 8-12 overnight items, 3 morning memo items
- **Source diversity**: No single source appears >3 times in top stories + overnight
- **Prestige outlets**: WSJ/NYT/WaPo/Bloomberg/FT/Economist/CNN/Reuters/CNBC/MSNBC stories never dropped
- **Deduplication**: URL-based + headline word-overlap detection (50% threshold, min 2 words)
- **Content filters**: K-pop/entertainment hard-blocked at collection and digest levels
- **Data integrity**: No placeholder URLs, no "None" strings, date matches today

---

## Project Structure

```
├── run.py              # Entry point and validation
├── collect.py          # 140+ RSS feeds, market data, sentiment polling
├── digest.py           # Claude system prompt and generation (with retry)
├── render.py           # HTML email renderer (mobile-optimized)
├── databases.py        # CSIS NK-Russia & provocations databases
├── send_email.py       # Gmail SMTP delivery
├── kim_tracker.py      # Kim Jong Un appearance persistence
├── kim_tracker.json    # Appearance history data
├── requirements.txt    # Python dependencies
├── .github/workflows/
│   └── daily-digest.yml  # Daily 6 AM ET schedule
└── public/             # GitHub Pages archive (generated)
```

---

## Dependencies

```
anthropic>=0.39.0    # Claude API client
feedparser>=6.0.0    # RSS feed parsing
requests>=2.31.0     # HTTP requests
```

All other imports use the Python standard library.

---

## Architecture Notes

- **Parallel collection**: RSS feeds fetched via `ThreadPoolExecutor` (~15 seconds for 140+ feeds)
- **Model strategy**: Sonnet for initial generation (cost-efficient), Opus escalation on retry if content minimums aren't met (~80% cost reduction vs Opus-first)
- **Retry logic**: Digest generation retries up to 3x if below content minimums; email send retries 3x with 5s backoff
- **Korean-language handling**: Articles tagged `lang="KO"` at collection; Claude translates titles and incorporates content
- **Email compatibility**: Table-based HTML layout with inline styles, tested for Gmail, Outlook, and Apple Mail; responsive via `@media` queries
- **Dark mode**: CSS `prefers-color-scheme` support for email clients that honor it
- **Kim tracker**: Persistent JSON file tracks confirmed appearances for pattern detection (absence alerts after 7+ days)

---

*CSIS Korea Chair*

---

<p align="center"><sub>Prepared by Andy Lim</sub></p>
