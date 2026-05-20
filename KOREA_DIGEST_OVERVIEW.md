# CSIS Korea Daily Brief — System Overview

**Automated daily intelligence product for the CSIS Korea Chair**
Designed as a Presidential Daily Brief-style newsletter for senior policymakers, Korea scholars, and elite journalists.

---

## 1. What It Does

Every morning at 6:00 AM ET, the system:

1. **Collects** articles from 138+ sources across 4 tiers (Korean, English, government, KCNA)
2. **Fetches** live market data (KRW/USD, KOSPI, BOK rate, 10Y yield) and polling numbers
3. **Loads** CSIS databases (NK-Russia timeline, NK provocations since 1958) for historical context
4. **Synthesizes** everything through Claude Opus into a structured 1,200–1,400 word briefing
5. **Validates** the output (URL checks, deduplication, word count, hallucination guards)
6. **Renders** a styled HTML email optimized for Gmail/Outlook
7. **Sends** via Gmail SMTP and publishes to GitHub Pages

The entire pipeline runs unattended on GitHub Actions. Total execution: ~3–5 minutes.

---

## 2. The 9 Sections

| # | Section | What It Contains |
|---|---------|-----------------|
| 1 | **Today at a Glance** | 3-bullet morning memo — the top-line takeaway |
| 2 | **Top Stories + Overnight Flash** | 2–4 lead stories + up to 6 overnight items with full sourcing |
| 3 | **DPRK Official Statements** | Kim Jong Un appearance status, official quotes (up to 4 with speaker attribution), senior official activity |
| 4 | **Satellite & Location Watch** | 11 monitored facilities (Yongbyon, Punggye-ri, Sohae, Sinpo, etc.) with status badges + imagery reports from 38 North/AEI |
| 5 | **ROK Government** | Ministry-by-ministry action cards (Blue House, MOFA, MND, NIS, FSC, etc.) + National Assembly + personnel changes |
| 6 | **Election Tracker** | Local election race tracker with party standings and countdown |
| 7 | **Business & Economy** | Corporate news, trade data, US-Korea investment deals |
| 8 | **Northeast Asia Watch** | Japan, China, Russia → Korea developments |
| 9 | **Public Sentiment Tracker** | Presidential approval + party support (Gallup Korea/Realmeter) |

**Also included:** Market indicators bar (header), Key Stat of the Day, The Wire (secondary items), Statements & Analysis (op-eds, think tank pieces, academic papers), On This Day (footer).

---

## 3. Source Architecture — 138+ Feeds Across 4 Tiers

### Tier 1 — Breaking News (71 feeds)
The raw intelligence intake. Collected in parallel every morning.

- **Korean English-language dailies:** Korea Herald, Korea Times, Yonhap English, JoongAng Daily, Chosun English, Hankyoreh English, Dong-A English
- **Korean-language newspapers:** 조선일보, 한겨레, 동아일보, 경향신문, 뉴스1, 연합뉴스, MBN (Claude translates during analysis)
- **Korean broadcast:** JTBC, KBS, MBC, SBS, YTN, Channel A, Arirang
- **Korean business dailies:** 매일경제, 한국경제, Korea Economic Daily
- **International correspondents:** WSJ, NYT, WaPo, FT, Reuters, AP, Bloomberg, BBC, CNN, CNBC, Guardian, Al Jazeera
- **Regional Asia:** Nikkei, Japan Times, SCMP, Kyodo, Mainichi, Asahi, CNA
- **US Government:** White House, State Dept, Pentagon, USFK, INDOPACOM, Commerce, Treasury, OFAC, BIS
- **ROK/Japan Government:** ROK MOFA, MOTIE, MND, Japan MOFA
- **US Congress:** Senate Foreign Relations, Senate Armed Services, House Foreign Affairs
- **International orgs:** IAEA, UN Security Council, CISA
- **Reaction layer:** Global Times, Xinhua, TASS, Caixin, China Daily, People's Daily
- **NK-specialist:** NK News

### Tier 2 — Analysis & Commentary (30 feeds)
Think tanks and policy outlets, ranked by prestige tier (A/B/C).

- **A-tier:** CSIS, Brookings, Carnegie, RAND, CFR, 38 North, Foreign Affairs, AccessDPRK, ArmsControlWonk, AEI, KEIA, Beyond Parallel, NK Pro
- **B-tier:** Stimson, IISS, ASAN Institute, EAI, Sejong, SIPRI, War on the Rocks, Foreign Policy, Hudson, Heritage, Atlantic Council, NBR, PIIE, USIP, CRS
- **C-tier:** The Diplomat

### Tier 3 — Academic (20 feeds)
Peer-reviewed journals, ranked A+/A/B.

- **A+:** International Security, International Organization, World Politics, APSR
- **A:** Journal of Conflict Resolution, Journal of Peace Research, Security Studies, ISQ, Journal of Strategic Studies, Asian Survey, Pacific Review, Foreign Affairs, Survival
- **B:** Korean Journal of Defense Analysis, North Korean Review, Asian Security, Pacific Affairs, Korean Studies, Nonproliferation Review, Washington Quarterly

### Tier 4 — KCNA & State Media (17 feeds)
Direct and indirect KCNA monitoring for official DPRK statements.

- **Direct:** KCNA Watch, kcna.kp, Rodong Sinmun
- **Wire relays:** KCNA via Yonhap, Reuters, AP, AFP, BBC, NYT, WaPo
- **Specialist:** KCNA via 38 North, Daily NK, NK News, NK Pro
- **Catch-all:** "KCNA said," "Pyongyang said," "state media," Kim Jong Un statements

### Additional Data Sources
- **Kim Jong Un tracker feeds** (5 feeds): appearance/activity monitoring via NK Leadership Watch, Daily NK, KCNA Watch
- **Market data:** Yahoo Finance (KRW/USD, KOSPI, Brent, S&P 500) + Stooq fallback + BOK ECOS API (base rate, GDP, CPI)
- **Polling data:** Korean-locale Google News scraping for Gallup Korea/Realmeter weekly polls, with Korean Wikipedia structured tables as primary source
- **CSIS databases:** NK-Russia cooperation timeline, NK provocations since 1958 (fetched from GitHub repos for historical context)

---

## 4. How It Works — Pipeline Architecture

```
collect.py          →    digest.py         →    run.py           →    render.py      →    send_email.py
(138+ RSS feeds)         (Claude Opus)          (validation)          (HTML email)        (Gmail SMTP)
(market data)            (structured JSON)      (URL checks)          (table layout)      (GitHub Pages)
(polling scrape)         (system prompt)        (dedup)               (mobile resp.)
(CSIS databases)         (prompt caching)       (word count)
                                                (retry loop)
```

### Step-by-step:

1. **`collect.py`** — Parallel RSS fetching via `ThreadPoolExecutor`. Each tier runs concurrently. Articles are deduplicated, filtered by Korea relevance (regex + keyword matching), and tagged with source metadata. Market data fetched from Yahoo Finance with Stooq fallback. Polling scraped from Google News Korean headlines.

2. **`digest.py`** — Builds a ~20,000-token prompt containing all collected articles, market data, tracker history (Kim appearances, KCNA rhetoric, facility status), CSIS database context, and detailed section-by-section instructions. Sends to Claude Opus with prompt caching enabled. Claude returns structured JSON with all 15+ sections.

3. **`run.py`** — Orchestrator. Runs validation gate: checks section counts (hard caps), URL validity (parallel HEAD checks), duplicate detection (headline similarity + URL dedup), word count floor (850 minimum), and hallucination guards. If critical validation fails, retries digest generation up to 2x with validation feedback injected into the prompt.

4. **`render.py`** — Converts digest JSON to table-based HTML email (1,400 lines). Every style is inline for email client compatibility. Responsive via `@media` queries. Solid `background-color` fallbacks for gradient-challenged clients (Gmail, Outlook).

5. **`send_email.py`** — Gmail SMTP with retry logic. Also writes `public/latest.html` for GitHub Pages archive.

### Persistent Trackers (cached across runs via GitHub Actions):
- **`kim_tracker.json`** — Confirmed Kim Jong Un appearances with dates and activities
- **`kcna_tracker.json`** — Daily KCNA output history (quotes, watch flags)
- **`bp_tracker.json`** — 11 monitored facility statuses (Yongbyon, Punggye-ri, Sohae, Sinpo, THAAD Seongju, Tumangang-Khasan, Sinuiju-Dandong, Rason SEZ, Yellow Sea NLL, Yellow Sea PMZ, Vostochny/Dunai)

---

## 5. Anti-Hallucination System

The digest serves expert readers (NSC staff, Korea desk officers, senior scholars). One wrong name or fabricated article destroys credibility. The system enforces:

| Guard | What It Does |
|-------|-------------|
| **Source-or-Skip** | Every factual claim must trace to an input article or reference baseline. If neither, it's dropped. |
| **Think Tank Fabrication Block** | Hard block on generic-sounding think tank entries ("CFR examines evolving security environment"). Claude is explicitly told these patterns destroy credibility. |
| **URL Validation** | Every article URL is HEAD-checked in parallel. 404/410 = dead link warning. |
| **Duplicate Detection** | Headline similarity scoring + URL dedup across all sections. |
| **Historical Claim Ban** | Claude cannot cite dates or precedents from training data. Only from today's articles or provided reference databases. |
| **Arithmetic Lock** | Pre-calculated totals (market data, facility counts) are passed through verbatim. Claude cannot recalculate. |
| **Validation Retry Loop** | If critical warnings fire, the digest is regenerated up to 2x with validation feedback injected. |
| **Word Count Floor** | Hard minimum 850 words. Blocks truncated outputs. |
| **Section Caps** | Hard max per section (e.g., top_stories: 2–4, overnight: 3–6). Prevents bloat or fabrication padding. |

---

## 6. Cost Estimate

### Per-run cost breakdown:

| Component | Cost |
|-----------|------|
| **Claude Opus API** (primary digest generation) | ~$0.30–0.60 per run |
| **Claude Sonnet API** (validation retries, if needed) | ~$0.05–0.10 per retry |
| **Prompt caching** (system prompt cached across calls) | Reduces input cost ~50% on retries |
| **GitHub Actions** | Free (public repo) |
| **Gmail SMTP** | Free |
| **External APIs** (Yahoo Finance, BOK ECOS) | Free |
| **RSS feeds** (Google News, direct) | Free |

### Monthly estimate:

| Scenario | Monthly Cost |
|----------|-------------|
| Normal (1 run/day, no retries) | **~$9–18/month** |
| With retries (~30% of days need 1 retry) | **~$12–22/month** |
| Worst case (daily retries + manual re-runs) | **~$25–35/month** |

The only paid dependency is the Anthropic API. Everything else is free infrastructure.

---

## 7. Replication Guide

### What you need:

| Requirement | Details |
|-------------|---------|
| **GitHub repo** | Public or private. GitHub Actions runs the pipeline. |
| **Anthropic API key** | Claude Opus access. Set as `ANTHROPIC_API_KEY` secret. |
| **Gmail account** | With App Password enabled. Set `GMAIL_USER`, `GMAIL_APP_PASS`, `DIGEST_TO` secrets. |
| **Python 3.12** | With `anthropic`, `feedparser`, `requests`, `httpx` packages. |
| **Optional: BOK API key** | For live BOK economic indicators. Free registration at ecos.bok.or.kr. |
| **Optional: GitHub PAT** | For database push-back (NK-Russia timeline, provocations). |

### To replicate for a different region/topic:

1. **Fork the repo** and modify `collect.py`:
   - Replace `TIER1_FEEDS` through `TIER4_FEEDS` with your region's sources
   - Update `KOREA_KEYWORDS` regex to your topic filter
   - Adjust market data tickers in `_collect_markets()`

2. **Modify `digest.py`**:
   - Rewrite `SYSTEM_PROMPT` for your analyst persona and audience
   - Update section definitions (what sections exist, field specs per section)
   - Adjust reference databases and tracker context blocks

3. **Modify `render.py`**:
   - Update section renderers to match your new digest structure
   - Adjust branding (header, footer, colors)

4. **Modify `bp_tracker.json`** (if applicable):
   - Replace monitored locations with your region's facilities/sites

5. **Set up GitHub Actions**:
   - Copy `.github/workflows/daily-digest.yml`
   - Add secrets to repo settings
   - Adjust cron schedule for your timezone

6. **Test locally**:
   ```bash
   python run.py --no-send    # Generates digest without emailing
   python run.py --from-cache # Re-runs digest from cached articles
   ```

### File inventory:

| File | Lines | Role |
|------|-------|------|
| `collect.py` | 1,653 | RSS collection, market data, polling scrape |
| `render.py` | 1,408 | HTML email renderer |
| `run.py` | 1,122 | Orchestrator, validation, postprocessing |
| `digest.py` | 888 | Claude API integration, prompt building |
| `databases.py` | 746 | CSIS database fetch/push (NK-Russia, provocations) |
| `kim_tracker.py` | 247 | Kim Jong Un appearance tracking |
| `send_email.py` | 210 | Gmail SMTP + GitHub Pages publish |
| `weekly.py` | 286 | Weekly summary generator |
| `kcna_tracker.py` | 120 | KCNA rhetoric history |
| `bp_tracker.py` | 103 | Facility status persistence |
| **Total** | **~7,300** | |

---

## 8. Q&A

**Q: How accurate are the articles? Can Claude hallucinate stories?**
A: Multiple layers prevent this. Every article must have a real URL from the input feed. URLs are HEAD-checked. Think tank fabrication is explicitly blocked. If validation catches a hallucinated entry, the digest is regenerated with feedback. Expert readers would catch a fabricated CSIS or Brookings piece instantly — the anti-hallucination system is designed for that audience.

**Q: What happens if the pipeline fails?**
A: The workflow has a fallback cron at 7:00 AM ET. If the primary 6:00 AM run fails or is skipped, the fallback fires. If it already succeeded, the fallback detects this and skips. If both fail, no email is sent — silence is better than a bad product.

**Q: How does the Korean-language content work?**
A: ~20 of the 71 Tier 1 feeds are Korean-language sources (조선일보, 한겨레, JTBC, KBS, etc.). These articles are collected with their original Korean titles and summaries. Claude Opus translates and analyzes them during digest generation. This gives the brief coverage that English-only monitoring misses.

**Q: What's the latency?**
A: Collection takes ~30–60 seconds (parallel RSS fetching). Claude Opus synthesis takes ~60–120 seconds. Validation and rendering take ~15 seconds. Total pipeline: 2–4 minutes from trigger to inbox.

**Q: Can readers see past issues?**
A: Yes. Each digest is archived to GitHub Pages at `andysaulim.github.io/Daily-Korea-Digest`. The email includes a "Read online" link. Daily JSONs are also archived for the weekly summary generator.

**Q: How is the facility tracker maintained?**
A: `bp_tracker.json` persists across runs via GitHub Actions cache. When a 38 North or AEI satellite imagery report appears in the day's articles, Claude updates the relevant facility's status and note. Otherwise, the last known status carries forward. The 11 monitored sites cover nuclear (Yongbyon, Punggye-ri), missile (Sohae, Sinpo), border crossings (Tumangang-Khasan, Sinuiju-Dandong), economic zones (Rason), military (THAAD Seongju), maritime (Yellow Sea NLL/PMZ), and logistics (Vostochny/Dunai arms shipments).

**Q: Why not use GPT-4 or Gemini?**
A: Claude Opus was chosen for: (1) large context window handling 138+ articles per run, (2) structured JSON output reliability, (3) prompt caching reducing repeat costs, (4) strong performance on Korean-language content. The system is model-agnostic in principle — swap the model ID in `digest.py` — but the prompt engineering is tuned for Claude's strengths.

**Q: What's the difference between this and a human analyst?**
A: This doesn't replace an analyst — it replaces the first 2 hours of their morning. Instead of scanning 70+ sources, pulling market data, checking KCNA, and drafting a summary, the analyst opens their inbox to a structured brief and spends their time on analysis, not collection. The system handles breadth; the human provides depth.

---

## 9. What's Next

- **Gallup Korea direct integration** — Currently scraping poll numbers from news headlines. Working toward structured polling data extraction.
- **Weekly digest** — `weekly.py` aggregates daily JSONs into a weekly summary (architecture exists, refinement ongoing).
- **Database auto-push** — New NK-Russia cooperation events and provocations are automatically flagged and pushed to CSIS timeline databases.
- **Subscriber management** — Currently single-recipient. Future: distribution list with subscribe/unsubscribe.
