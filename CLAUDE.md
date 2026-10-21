# Korea Daily Brief

Automated intelligence briefing on Korean Peninsula affairs, delivered daily at 7 AM ET to senior policymakers and analysts.

## Architecture

```
COLLECT (160+ feeds, 25 threads) → RANK (editorial priority) → DIGEST (Claude Sonnet/Opus) → VALIDATE (dedup, URL repair, source caps) → RENDER (HTML email) → SEND (Gmail SMTP)
```

Orchestrated by `run.py`. Triggered via external cron (cron-job.org) → GitHub Actions `workflow_dispatch`, with fallback crons at 7:30 and 9:00 AM ET (each listed for both EDT and EST, since GitHub cron is UTC). cron-job.org must be set to America/New_York so the primary trigger also follows daylight saving.

## Key Files

| File | Role |
|------|------|
| `run.py` | Pipeline orchestrator — runs collect → digest → validate → render → send |
| `collect.py` | Parallel RSS scraper, market data (KOSPI, KRW, Brent), Gallup Korea polling, satellite imagery |
| `digest.py` | Claude API integration — 80-line system prompt, structured JSON output, Sonnet-first with Opus retry |
| `render.py` | 1,400-line HTML email renderer — table-based layout, inline CSS, dark mode, mobile responsive |
| `listen.py` | Audio extras: chapters (JSON + ID3), VTT transcript, show notes, `listen/` player page |
| `send_email.py` | Gmail SMTP sender (SSL, port 465) |
| `databases.py` | NK-Russia bilateral timeline (270+ events), NK provocations history (540+ since 1958) |
| `kim_tracker.py` | Kim Jong Un appearance log — computes "days since last seen" |
| `kcna_tracker.py` | 14-day KCNA rhetoric baseline — phrase counts, tone shifts |
| `bp_tracker.py` | 11 DPRK facility statuses (Yongbyon, Punggye-ri, Sohae, Sinpo, etc.) |
| `tension_scorer.py` | Peninsula tension index (0–10 scale) — **built but not wired**; nothing imports it |
| `weekly.py` | Friday "Week in Review" synthesis from the week's 7 daily digests |
| `update_readme.py` | Auto-updates README with latest run stats |
| `feed_health.py` | Per-feed delivery streaks across runs — flags feeds silent 3+ runs |
| `length_budget.py` | Trims items from weaker sections when the brief runs over its ceiling |
| `korea_calendar.py` | Fixed observances, computed from today's date rather than recalled |
| `test_sources.py` | Guards the prompt's source claims against the actual feed list |
| `test_render_visual.py` | Measures contrast, typeface count and mobile overflow in a browser |

## Persistent State

Tracker files (`kim_tracker.json`, `kcna_tracker.json`, `bp_tracker.json`, `feed_health.json`, `metrics.jsonl`) are cached across GitHub Actions runs. They prevent the AI from hallucinating baselines — real historical data is injected into the prompt instead.

## Sourcing

Read this before touching `collect.py` or the prompt's source rules.

**A feed is a list of candidate URLs, not one URL.** They are tried in order
and the first to return items wins: the publisher's own RSS first, a Google
News `site:` search last. Use `_native(native_url, gnews_query)` to define one.
Never put a search ahead of a native feed.

The reason is that the brief used to be ~150 Google News searches, so one
change upstream would take nearly every source at once, silently — the issue
would just arrive thin. The fallback also means an unverified native URL is
safe to add: if it is wrong, the search behind it answers as before.

**Primary sources bypass the relevance filter.** `KOREA_KEYWORDS` strips world
news out of general wires. Applied to a ROK ministry feed it deleted most of
it, because a real headline like `2027년도 예산안 국무회의 의결` contains none
of its Korean tokens. Feeds listed in `KOREA_NATIVE_FEEDS` are exempt. Add any
new ROK government or Korean-language feed to that set, or most of it is
discarded before the model sees it.

**Only the top N articles per tier reach the model** (140 for tier 1). They are
ordered by `digest.rank_for_prompt` — primary documents, then outlets a
mandatory rule names, then flagged correspondents, then Korean full-text —
taking one per source before any source gets a second. Before this, the cut was
by network latency, and the outlets the prompt calls mandatory often were not
in the prompt at all.

**Never name a source in the prompt that no feed collects.** It invites the
model to satisfy the instruction from memory, which is what SOURCE-OR-SKIP
exists to prevent. `test_sources.py` enforces this.

**Feed health** is tracked across runs in `feed_health.json`. A feed silent 3+
consecutive runs is reported in the run log with the date it last delivered.
Check that before assuming a source is covered.

**ROK government feeds** fall back to press searches by ministry name and
spokesperson (`"외교부 대변인"`, `국방부 브리핑`) in the Korean Google News
edition, never to `site:*.go.kr`: Google indexes almost no .go.kr pages, and
the old site searches delivered 15 items a week across twenty feeds. korea.kr
ended its RSS service on 2026-07-01. Only a government-domain URL ranks as a
primary document; a press report of a briefing ranks in band 2.

**A native feed that answers can still be empty for us.** The Hill or
Brookings publish daily, so their feed always "wins", and the Korea filter
then dropped every item while the search behind it never ran. `_parse_feed`
takes the collector's keep test (`accept`): a candidate with nothing that
passes gives way to the next. Searches are wrapped by `_windowed()`, which
puts a `when:Nd` search ahead of the plain one, because a plain Google News
search returns its 100 most relevant hits, mostly too old for a 24h window.

**Prestige names match as whole words.** "ap " once matched the end of
"Yonhap ", so Yonhap took 130 of the 140 tier-1 slots and the Korea Herald,
Korea Times and the Korean dailies never reached the model.

Run `python test_sources.py` after any change here.

## Length

The prompt asks the model for **1,700-2,000 words** of its own text (hard
ceiling 2,100). `run.WORD_CEILING` (**3,300**) counts *rendered* words, and the
page adds about 1,000 words of labels and panels on top of what the model
writes (rendered ≈ 1,000 + 1.17 × model words). Below 1,300 the brief is
regenerated (`MIN_DIGEST_WORDS`).

The binding limit is bytes, not words: Gmail clips a message over ~102KB and
hides the rest behind "View entire message". `run.fit_email_bytes` drops items
in `length_budget.TRIM_ORDER` until the minified email is under 98,000 bytes.

Length is decided by `run.SECTION_CAPS`, not by the prompt's target. An issue
shipped at 3,518 words because the caps permitted about 3,680 between them and
nothing capped the total. Raise a cap only after checking what it does to the
sum; `test_sources.py` fails if the caps drift far above the ceiling.

`length_budget.py` is the enforcement. If the brief is over after the model
writes it, whole items are dropped from the end of the weaker sections in a
fixed order until it fits. Top stories and the morning memo are never trimmed.
Nothing is rewritten, so what survives is what the model wrote against its
sources.

## The archive and the corpus

`public/` is gitignored and the Actions runner starts clean, so **none of the
published index files exist locally when a run begins**. Any code that reads
one, finds nothing, starts empty and writes it back will silently destroy the
history: the Pages deploy keeps files it is not publishing but overwrites the
ones it is. That is what happened to `archive.json` and to
`corpus/manifest.json` — both were rebuilt from scratch every run, so the
archive page listed one issue and the issue number never advanced, however
many briefs had been sent.

Anything under `public/` that accumulates across runs must be read from the
published site first (`run.load_archive_entries`, `corpus._published`) and
**must not be written at all when that read fails**. Writing a file built
without the history is worse than not writing it: today's `digest_*.html` is
deployed either way and keep_files preserves the rest, so skipping the index
costs one day of listing, while writing a stub costs all of them.

## Feed Tiers

- **Tier 1 (News, 24h window)**: Korea Herald, Reuters, WSJ, NYT, Bloomberg, Yonhap, JTBC, Global Times, Xinhua, TASS; ROK primary sources (Presidential Office, MOFA, MND, Unification, MOEF, MOTIE, DAPA, Joint Chiefs, National Assembly, Prosecution, Courts, Bank of Korea, KOSTAT, Customs, DART, korea.kr); Korean-language dailies (조선·중앙·동아·한겨레·경향·한국일보·연합·뉴시스) and broadcast
- **Tier 2 (Analysis; 96h reports, 48h op-ed pages)**: ~52 feeds: US, Korean and regional think tanks (CSIS, Brookings, CFR, Carnegie, RAND, Stimson/38 North, CNAS, KEI, Asan, EAI, KINU, Sejong, Lowy, IISS...) and Korea-filtered op-ed pages. Each item carries a kind (report, oped, journal, news); `digest.rank_analysis` puts reports first.
- **Tier 3 (Academic, 7 days)**: ~17 journals via the publishers' contents RSS (International Security, Washington Quarterly, Survival, Asia Policy, Asian Survey, Pacific Affairs...)
- **Tier 4 (DPRK, 24h)**: KCNA Watch, Rodong Sinmun, Daily NK, NK News
- **Capitol Hill stream (48h; CRS and GovInfo 72h)**: congress.gov, GovInfo, CRS,
  committee feeds, The Hill, Roll Call, Politico, Punchbowl (`collect.CAPITOL_HILL_FEEDS`).
  Filtered for Korea, never in `KOREA_NATIVE_FEEDS`. Hearing schedules
  (`HILL_CALENDAR_FEEDS`) feed `hill_calendar`, attached by run.py, not the model.
- **Korea and the World stream (36h)**: targeted feeds for Europe/NATO, the Gulf,
  South and Southeast Asia, the Global South, Ukraine, the UN and defence/nuclear
  exports (`collect.KOREA_WORLD_FEEDS`). Filtered for Korea and a non-Northeast-Asia place.
- Both streams have their own prompt blocks (they skip the tier-1 cut) and are
  appended to tier 1 so validation and URL repair see them.

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
