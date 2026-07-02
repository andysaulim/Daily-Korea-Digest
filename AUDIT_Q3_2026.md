# Korea Daily Brief — Quarterly Audit (Q3 2026)

**Audit date:** June 18, 2026
**Auditor:** Claude (opus-4.7)
**Branch:** `claude/korea-digest-Uh7fN`

---

## Executive summary

The pipeline recovered from a production outage this week (deprecated model IDs). This audit tightens the pipeline against a recurrence, prunes dead feeds discovered during recovery, and wires in the previously-dormant tension scorer.

**Overall health:** Yellow → Green after this branch merges.

## 1. Incidents this quarter

| Date | Incident | Root cause | Fix |
|------|----------|------------|-----|
| Jun 15 | Full pipeline outage | Anthropic retired `claude-opus-4-20250514` and `claude-sonnet-4-20250514` | Updated to `claude-opus-4-8` / `claude-sonnet-4-6` |
| Jun 16 | JSON parse crash (4 attempts) | Newer models more verbose → `max_tokens=16000` truncated JSON | Raised to `32000` |
| Jun 16 | KOSPI hallucination ("KOSPI plunges 4.44% amid AI selloff") | Model fabricated market story not in source articles | Added explicit MARKET-DATA prompt rule |
| ongoing | Assistant prefills would 400 on 4.6+ models | Model family breaking change | Removed 3 prefill sites in digest.py + weekly.py |

## 2. Feed health audit

**Total feeds catalogued:** 138 core + 17 auxiliary = 155

### Feeds pruned
- `MSNBC Korea` — MSNBC publishes essentially no Korea reporting; feed always empty
- `Foreign Affairs` (Tier 3 duplicate — same source as Tier 2, was double-counting)
- `KCNA` direct `.kp` — TLD not indexed by Google News
- `Rodong Sinmun` `.rep.kp` — same TLD-indexing issue

### Feeds repaired
- `JoongAng Daily` — direct RSS returned 404; switched to Google News relay
- `Channel A` — wrong domain (`ichannela.com` → `channela.com`)
- `Stimson` — direct WordPress feed blocked; switched to Google News relay
- `EAI` — ASP endpoint defunct; switched to Google News relay
- `KCNA (NK Pro)` — misspelled domain (`korearisgroup.com` → `koreariskgroup.com`)

### Still needs manual attention
- `Korea Herald` — direct feed resolves but returns 0 articles. Filter rejecting all items? Investigate `_filter_korea_relevant` for over-strict matching.
- `KCNA Watch` — 403-blocked but fallback logic works (falls through to Google News scope query).

## 3. New capabilities added

### Pipeline health monitor (`pipeline_health.py`)
Runs after every digest. Warns on:
- **Gallup baseline staleness** — warns at 14 days, alerts at 30 days
- **Model deprecation risk** — flags any model ID not in the known-current set
- **Tier coverage gaps** — warns if any tier drops below expected minimums (T1: 60, T2: 10, T3: 3, T4: 3)
- **Prestige outlet gap** — warns if no WSJ/NYT/FT/Bloomberg/Reuters appear at all
- **Fallback overuse** — warns when scraped sentiment matches the hardcoded baseline (implies live scrape broke)

Findings are printed inline and rolled into `metrics.jsonl` for trend analysis.

### Peninsula Tension Index (activated)
`tension_scorer.py` was fully built (404 lines) but never called. Now:
- Computes daily after digest generation
- Writes to `tension_tracker.json` (cached across GH Actions runs)
- Persists 30 days of history for sparkline rendering
- Prints inline: `📈 Peninsula Tension Index: 4.5/10 (GUARDED, trend STABLE)`
- **Not yet rendered in the HTML** — deliberately holding until we redesign that section

### Failure-alert routing
Failure emails now go to `alim@csis.org` only, not the full distribution list.

## 4. Trackers audit

| Tracker | State | Notes |
|---------|-------|-------|
| `kim_tracker.json` | Active | "Days since last seen" computed correctly |
| `kcna_tracker.json` | Active | 14-day rhetoric baseline OK |
| `bp_tracker.json` | Active | 11 facilities monitored |
| `tension_tracker.json` | **New** | Now building history |
| `metrics.jsonl` | Active | Now records health-check counts |

## 5. Format / design review — recommendations for next quarter

Not implemented yet, presented as a menu for Q4:

1. **Peninsula Tension Index widget** — add to top-of-newsletter above Top Stories. Sparkline + score + level badge. Foundation is ready.
2. **AI & Semiconductors Watch** — currently scattered across Business & Economy. Warrants its own section given Samsung/SK Hynix + tariff dynamics.
3. **Trilateral Deliverables Tracker** — running list of US-ROK-Japan commitments with status (announced/negotiating/signed/implemented).
4. **Feed-of-the-day badge** — highlight if a specialist outlet (38 North / ArmsControlWonk / AccessDPRK) has a piece.
5. **Weekly digest** — the Friday "Week in Review" flow (`weekly.py`) is standalone but could be improved with the tension-index sparkline.

## 6. Watch items for Q4 audit

- Anthropic Opus 4.8 successor arrival (migrate proactively — don't wait for retirement)
- Gallup baseline update cadence — did anyone remember to update?
- Feed health trendline in `metrics.jsonl` — any tier drifting down?
- Ballot-shortage / NEC coverage — verify the new prompt rules aren't over-filtering
- Tension index calibration — 30 days of data will show whether the 0-10 scale is well-tuned

## 7. Changes in this branch

```
collect.py            — feed pruning + repairs
digest.py             — model IDs (Sonnet 4.6, Opus 4.8), max_tokens 32k, no prefills, market rule, updated Gallup baseline
weekly.py             — model ID update, prefill removed
pipeline_health.py    — NEW: health monitor
run.py                — health check + tension scoring wired in
.github/workflows/daily-digest.yml — failure alerts to operator only, tension tracker cached
AUDIT_Q3_2026.md      — NEW: this file
```
