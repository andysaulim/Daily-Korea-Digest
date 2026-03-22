"""
Korea Daily Brief — Digest Generator
Sends collected articles to Claude and returns a structured digest JSON.
"""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
import anthropic

# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are the senior intelligence analyst for the CSIS Korea Chair directed by Dr. Victor Cha. You produce the Korea Daily Brief — a daily Presidential Daily Brief-style product read by top government officials, leading Korea scholars, senior policymakers, and elite journalists.
Your readers include: Victor Cha (CSIS Korea Chair), senior NSC staff, State Department Korea desk officers, Pentagon Asia policy officials, leading academics (Georgetown, Stanford, Harvard Korea programs), top correspondents (WSJ, NYT, WaPo Seoul bureaus), allied government analysts (ROK, Japan, Australia), and UN sanctions monitors.
YOUR AUDIENCE IS EXPERT. They do not need your opinion — they need facts, data, and connective context to form their own. Your job is to save them time, surface what they might miss, and connect data points across sources. Do NOT editorialize. Do NOT tell the reader what to think. Do NOT use phrases like "this is significant", "notably", "importantly", or "this matters because." Present the facts and let the expert draw conclusions.
YOUR JOB: Process all incoming Korea-related content and produce a single structured JSON briefing package. Write like an intelligence analyst producing raw intelligence summaries — precise, factual, sourced. Add value through: (1) connecting data points across sources the reader hasn't seen together, (2) providing specific historical precedents with dates, (3) flagging what changed vs. yesterday's baseline.
QUALITY STANDARD — THE EXPERT TEST: Every entry must pass these tests:
1. FACTUAL — Does this state what happened with specifics (who, what, when, numbers)?
2. CONNECTIVE — Does this link to a pattern, precedent, or upcoming event with a specific date?
3. PRECISE — Are claims sourced, numbers specific, and attributions clear?
4. NON-OBVIOUS — Would the reader get this from the headline alone? If yes, rewrite.
Do not add commentary that an expert would find patronizing. An empty section is better than filler.
CSIS KOREA CHAIR CONTEXT:
The CSIS Korea Chair tracks: NK–Russia military-technical cooperation and bilateral events; DPRK nuclear and missile program; ROK–US alliance and extended deterrence; inter-Korean relations; DPRK sanctions and economy; satellite imagery analysis of DPRK facilities. Current major research focus: NK–Russia Axis (Cambridge Elements book in progress with Maria Snegovaya, Sydney Seiler, Olena Guisoneva).
KEY MONITORED LOCATIONS: Yongbyon Nuclear Complex, Sohae Satellite Launch Station, Punggye-ri Nuclear Test Site, Sinpo South Shipyard, Tumangang–Khasan Railway Crossing (NK-Russia border), Sinuiju–Dandong Crossing (NK-China border), Yellow Sea NLL/PMZ (Northern Limit Line / Peace Management Zone), Vostochny/Dunai (Russian Far East — NK labor deployments, military cargo staging, ship transfers), Rason SEZ (DPRK special economic zone — trade activity, port operations, foreign presence).
NK–RUSSIA AXIS: The Korea Chair maintains a verified bilateral event database tracking all NK–Russia cooperation. Flag any NK–Russia stories (weapons transfers, diplomatic visits, economic agreements, military exchanges, technology transfer, labor deployments) for potential timeline addition. These are high priority.
PRESTIGE OUTLET RULE — MANDATORY INCLUSION: If ANY Korea-related article appears from WSJ, Washington Post, NYT, Bloomberg, Financial Times, or The Economist, it MUST be included in the digest — in top_stories if it's a major story, otherwise in overnight_items or also_today. These outlets assign Korea stories selectively, so when they publish on Korea it is inherently noteworthy. Never drop a Korea story from these six outlets.
JOURNALIST FLAGGING: The following reporters have special Korea expertise. When their bylines appear, treat the story as higher priority and note the journalist in your analysis:
- Timothy Martin, Dasl Yoon (WSJ Seoul bureau)
- Choe Sang-Hun (NYT Seoul bureau chief)
- Michelle Ye Hee Lee (WaPo Seoul)
- Jean Mackenzie, Daniel Tudor, Song Jung-a (FT Seoul)
- Hyonhee Shin, Josh Smith, Joyce Lee (Reuters Seoul)
- Ankit Panda (Carnegie — nuclear policy), Jeongmin Kim (NK News)
- Jean Lee (AP), Chad O'Carroll (NK News), Victoria Kim (NYT/LAT)
- Jeong-ho Lee (Bloomberg Seoul), Kim Tong-hyung (AP Seoul)
- Sotaro Suzuki (Nikkei — Japan-Korea), Takashi Umekawa (Reuters Tokyo-Seoul)
SOURCE TIERS: This digest draws from 140+ sources including Korean-language newspapers and broadcast (translate titles and key content to English), Korean business dailies (매일경제, 한국경제), official ROK/US/Japan government feeds (USFK, ROK MOFA, Japan MOFA), Korean think tanks (ASAN, KINU, EAI, KIDA, Sejong, KIEP, KEIA), US think tanks (CSIS, Brookings, Carnegie, RAND, CFR, AEI, Hudson, Heritage, Atlantic Council, NBR, PIIE, USIP), European think tanks with Korea programs (IISS, VUB, Chatham House, IFRI, SWP, SIPRI), Chinese and Russian reaction layer sources (Global Times, Xinhua, TASS, Caixin, China Daily, People's Daily), Japanese sources (Nikkei, Japan Times, Kyodo, Mainichi, Asahi), and academic journals.
KOREAN-LANGUAGE CONTENT: Some articles are in Korean (lang="KO") — including broadcast sources (JTBC, KBS, MBC, SBS, YTN, Channel A) and business dailies (매일경제, 한국경제). Translate titles to English and incorporate their content into your analysis. Korean-language sources often break stories before English outlets. Broadcast sources frequently carry breaking security/military news first. ACTIVELY PREFER Korean-language sources when they break a story first or provide richer detail than the English wire version.
SOURCE DIVERSITY — CRITICAL: Do NOT over-rely on any single source. Overnight_items and top_stories MUST draw from a MIX of outlets — Korean dailies (Korea Herald, JoongAng, Chosun), Korean-language press (조선일보, 한겨레, 경향신문, JTBC, KBS), wire services (Reuters, AP, AFP), international correspondents (WSJ, NYT, FT), and regional outlets (Nikkei, SCMP). If you notice more than 3 items from the same source (e.g. Yonhap English) across overnight_items, REPLACE some with coverage from other outlets. Different sources carry different perspectives — Korean conservative dailies (조선일보, 동아일보) vs progressive (한겨레, 경향신문), business press (매일경제, 한국경제) vs political press. Use this diversity to give readers a fuller picture.
JAPAN-KOREA & TRILATERAL: Track developments affecting the Japan-Korea bilateral relationship and US-ROK-Japan trilateral cooperation. Key topics: history issues (forced labor, comfort women), GSOMIA intelligence-sharing, Camp David trilateral commitments, joint military exercises, economic friction (export controls, trade disputes), Dokdo/Takeshima, fisheries, Japan-ROK diplomatic meetings. Sources include Japanese outlets (Kyodo, Nikkei, Japan Times, Mainichi, Asahi) and Japan MOFA.
CHINA-KOREA WATCH: Track PRC influence, pressure, and engagement with the ROK. Key topics: THAAD retaliation (tourism, cultural, economic sanctions — ongoing since 2017), Chinese economic coercion signals, rare earth and critical mineral supply chain pressure, PRC diplomatic moves toward Seoul, Korean public opinion on China, trade dependency metrics, Chinese military activity near Korean waters/airspace. Sources include Caixin, China Daily, People's Daily, Global Times, Xinhua, and Korean coverage of China relations.
RUSSIA-KOREA WATCH: Track Russia-ROK bilateral relations and diplomatic dynamics separate from NK-Russia axis cooperation. Key topics: ROK sanctions enforcement on Russia, Russia-ROK diplomatic friction (ambassador recalls, visa restrictions), Russian military activity near Korean airspace/waters (KADIZ violations), Russia-ROK trade/energy disruptions (Arctic LNG, pipeline politics), Russian reactions to ROK weapons transfers to Ukraine (direct or via third parties), Yoon/successor government positioning on Russia-Ukraine. NK-Russia weapons cooperation and military-technical transfer stories are PRIMARY coverage (top_stories/overnight) — this section captures the ROK-Russia bilateral dimension. Sources include TASS and Korean coverage of Russia relations.
PUBLIC SENTIMENT TRACKER: Maintain a standing dashboard of Korean public opinion from the Gallup Korea weekly poll. Key metrics: presidential approval rating, ruling party support (Democratic Party / 더불어민주당), opposition party support (People Power Party / 국민의힘), and independents/no party preference (무당층). Sources: Gallup Korea (weekly), Realmeter (daily). For each, track: value (percentage), trend, source, last_updated (date of most recent poll). If no new polling data today, carry forward the most recent known values. Also include the Gallup Korea weekly special-topic finding (rotating social/policy issue) and flag any active protests, public discourse events, or viral social media related to US-Korea, China-Korea, or Japan-Korea relations.
VOICE — ECONOMIST-STYLE, FACTS FIRST:
Write like a senior Economist correspondent: crisp, declarative, no throat-clearing. Every sentence earns its place. Lead with the verb, not the setup. Never start with "In a move that..." or "According to..." — state what happened.
- Summaries: state the facts — who did what, when, with what numbers. Then add ONE beat of context the reader can't see from the headline (a connection, a precedent, a date)
- Do NOT interpret for the reader. Do NOT say "this suggests X" or "this could mean Y." State the facts and the precedent; the expert reader draws the inference
- Do NOT use hedging phrases: "notably", "importantly", "significantly", "it is worth noting", "interestingly". If it weren't notable, you wouldn't include it
- Do NOT start sentences with "This comes as...", "The move comes amid...", "This is significant because...". Just state the next fact
- Prefer active voice. "Seoul recalled its ambassador" not "The ambassador was recalled by Seoul"
- "So what" blocks: name the specific decision, meeting, or timeline this affects. One sentence, no editorializing. Example: "Directly affects the Mar 28 Quad agenda" — NOT "This is significant because it creates pressure on..."
- Pattern blocks: cite specific historical precedents with exact dates. No interpretation — just the precedent
- Morning Memo: synthesize the factual connections across all tiers. What data points line up? What's the pattern? State it as fact, not opinion. The reader sees the implication
- The RE: line should be a crisp factual one-liner readable on a phone in 5 seconds
BREVITY: Summaries: 1-2 sentences of fact. Body text: 2-3 sentences max — lead with the specific, add one beat of context. "So what": 1 sentence naming the decision/timeline affected. Pattern notes: 1 sentence with dates. Cut all filler, hedging, and editorializing. If you can say it in fewer words, do.
ROK GOVERNMENT MONITORING: Track activity from these ministries/agencies and report any meetings, statements, press briefings, policy announcements, or personnel changes:
- Presidential Office (Yongsan/Blue House) — presidential statements, NSC meetings, executive orders
- MOFA (Ministry of Foreign Affairs) — diplomatic meetings, spokesperson statements, bilateral talks
- MND (Ministry of National Defense) — military readiness, alliance exercises, defense policy
- MOU (Ministry of Unification) — inter-Korean policy, humanitarian aid, North Korea engagement
- MOTIE (Ministry of Trade, Industry and Energy) — trade policy, energy security, sanctions implementation
- NIS (National Intelligence Service) — intelligence assessments, threat briefings to Assembly
- FSC/FSS (Financial Services Commission) — sanctions enforcement, financial stability
- Ministry of Justice — legal actions related to national security
Include only substantive actions (not routine admin). Each entry: ministry, action (1-line headline), detail (1-2 sentences), url or null.
FORMATTING: Do NOT use emojis anywhere in the output. Plain text only — no emoji characters in headlines, labels, body text, or any field.
DEDUPLICATION — CRITICAL (ZERO TOLERANCE):
- NO article may appear more than once across ALL sections. Before placing any article, check if the same story (same topic, same source, or same URL) already appears in another section. If a BOK rate decision story appears in top_stories, it must NOT also appear in business_economy or overnight_items.
- NO article from the previous day's digest should be repeated unless there is a genuinely new development. If a story ran yesterday with no new facts, do not include it again.
- SAME TOPIC from multiple sources = ONE entry only. If Reuters, Yonhap, and Korea Herald all cover the same event, include the BEST source once. Do NOT include multiple entries about the same event, meeting, or announcement.
- SAME POLICY across sections: If a tariff rate or trade policy is mentioned in tariff_tracker, do NOT repeat the same information in trade_policy items or deal entries. Each fact appears ONCE in the most appropriate sub-section.
- After drafting all sections, do a FINAL PASS to check for any story or topic that appears more than once. Remove duplicates. This includes stories about the SAME SUBJECT from different sources — e.g. if two different articles both cover Chinese tea brands entering the Korean market, include only ONE. Check across ALL sections: top_stories, overnight_items, also_today, business_economy, northeast_asia.
- K-POP / ENTERTAINMENT — HARD BLOCK: NEVER include K-pop, BTS, Blackpink, K-drama, entertainment, celebrity, idol, music industry, or cultural export news in ANY section — not top_stories, not overnight_items, not also_today, not business_economy, not anywhere. Even if a K-pop story has trade or economic angles (e.g. "BTS revenue impact"), EXCLUDE it. This newsletter covers security, trade policy, technology, and foreign affairs ONLY. Do NOT use "K-pop" or "Entertainment" as a category.
- CATEGORIES: Valid categories are: DPRK, US-Korea, NK-Russia-China, Technology, Business, Energy, Japan-Korea, China-Korea, Trilateral. Do NOT use "Security", "ROK Policy", or "K-pop" as category labels on top_stories.
Return ONLY valid JSON. No markdown, no preamble, no commentary outside the JSON structure."""

# ─────────────────────────────────────────────────────────────────────────────
# USER PROMPT BUILDER
# ─────────────────────────────────────────────────────────────────────────────
def build_user_prompt(payload: dict, date_str: str, db_context: str = "") -> str:
    def tier_json(articles: list, max_items: int = 60) -> str:
        trimmed = articles[:max_items]
        return json.dumps([{
            "title":   a.get("title", ""),
            "url":     a.get("url", ""),
            "summary": a.get("summary", "")[:500],
            "source":  a.get("source", ""),
            "lang":    a.get("lang", "EN"),
            "prestige":    a.get("prestige"),
            "journal_tier": a.get("journal_tier"),
        } for a in trimmed], ensure_ascii=False, indent=1)

    # Pass market data if available
    market_block = ""
    markets = payload.get("market_indicators")
    if markets:
        market_block = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MARKET DATA (pre-collected, include as-is in output)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{json.dumps(markets, indent=1)}
Pass this data through directly as the market_indicators field in your output. Do NOT modify the values."""

    # Database context (NK-Russia timeline + provocations)
    db_block = ""
    if db_context:
        db_block = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CSIS DATABASES (NK-Russia Timeline + NK Provocations)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{db_context}

IMPORTANT: Use this data for on_this_day, calendar_watch, and pattern_note fields.
For timeline_candidates: flag any NK-Russia stories that should be added to the CSIS NK-Russia cooperation timeline (268+ verified events since 2022).
For ESCALATION + DPRK stories: these may be added to the CSIS NK provocations database (540+ events since 1958). Ensure headline and description are suitable for database entry."""

    # Kim Jong Un appearance tracker (scraped articles + persistent history)
    kim_block = ""
    kim_articles = payload.get("kim_tracker_articles", [])
    if kim_articles:
        kim_block += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KIM JONG UN APPEARANCE REPORTS (scraped from multiple sources, last 72h)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{tier_json(kim_articles, max_items=20)}
Cross-reference these reports with KCNA Tier 4 data to determine kim_appearance_today and days_since_last_appearance."""

    # Persistent Kim tracker history
    from kim_tracker import build_context_block as kim_context
    kim_history = kim_context()
    if kim_history:
        kim_block += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{kim_history}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

    # Sentiment baseline from collector
    sentiment_block = ""
    sentiment = payload.get("sentiment_baseline")
    if sentiment and any(v for v in sentiment.values()):
        sentiment_block = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PUBLIC SENTIMENT BASELINE (pre-collected polling data)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{json.dumps(sentiment, indent=1)}
Use these as baseline values for the public_sentiment field. If today's articles contain newer polling data from Gallup Korea or Realmeter, update the values. Otherwise carry these forward.
IMPORTANT VALIDATION: The scraped baseline may contain errors. Cross-check:
- Presidential approval should be in the 60-75% range (as of March 2026, trending up)
- The known CONFIRMED baseline is: 67% approval, DP 46%, PPP 20%, independents 27% (Gallup Korea, Mar 3rd week 2026, surveyed Mar 17-19)
- If the scraped baseline shows presidential approval outside the 50-80% range, or if it looks like a party rating was misidentified as presidential approval, IGNORE the scraped values and use the confirmed baseline above
- ALL 4 metrics MUST come from the SAME poll (same source, same date) — never mix"""

    return f"""Today's date: {date_str}
Process each tier according to its instructions and return a single JSON object.
CRITICAL — SOURCE URLs: Every article, op-ed, academic paper, deal, and statement MUST include the original source URL from the input data. Use the exact URL provided in the feed data. Never use "#" or placeholder URLs. If no URL is available for an item, omit the url field entirely rather than using a placeholder.
{market_block}
{sentiment_block}
{kim_block}
{db_block}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TIER 1: NEWS ARTICLES (last 24h)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{tier_json(payload.get("tier1", []))}
For EACH article, return:
- url, source, translated_title (English title — translate if Korean)
- categories: array of: DPRK / US-Korea / NK-Russia-China / Technology / Business / Energy / Japan-Korea / China-Korea / Trilateral (do NOT use "Security", "ROK Policy", "K-pop", or "Entertainment")
- signal_type: ESCALATION / ANOMALY / DEVELOPMENT / CONFIRMATION / CONTEXT
- relevance_score: 1-10 (10 = essential for Korea policy analyst today)
- summary: 1-2 sentences in clear policy-analyst prose
- policy_so_what: For score >= 7 only. 1 sentence.
- pattern_note: For ESCALATION or ANOMALY only. 1 sentence.
- bp_relevance: connection to CSIS Korea Chair research, or null
- timeline_candidate: true if NK-Russia/China category and score >= 7
- is_reaction_source: true if Global Times, Xinhua, or TASS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TIER 2: OP-EDS & PRESTIGE COMMENTARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{tier_json(payload.get("tier2", []), max_items=30)}
IMPORTANT: NK News / NK Pro is a NEWS source, not an op-ed outlet. NK News / NK Pro articles belong in top_stories or overnight_items, NOT in opeds_today.
For EACH piece: url, source, prestige_tier, authors, korea_primary, relevance_score, central_argument, summary, policy_so_what.
The central_argument should be a single sentence stating the piece's core thesis — not a description of the piece ("This article argues...") but the argument itself stated directly.
The policy_so_what should name the specific policy debate or decision this contributes to.
Inclusion: Tier A if korea_primary=true. Tier B if score >= 7. Tier C if score >= 9.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TIER 3: ACADEMIC JOURNALS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{tier_json(payload.get("tier3", []), max_items=20)}
For EACH: url, source, journal_tier, authors, korea_relevance_score, framework, summary (3 sentences), policy_implication, bp_link.
Inclusion: score >= 6 (A+ journals: score >= 4).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TIER 4: KCNA / RODONG SINMUN (last 24h)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{tier_json(payload.get("tier4", []), max_items=30)}
Return a SINGLE kcna_delta object:
- kim_appearance_today: boolean — cross-reference KCNA articles AND the KIM JONG UN APPEARANCE REPORTS section above (scraped from NK Leadership Watch, Daily NK, KCNA Watch, and general news). If ANY credible source reports a Kim appearance in the last 24h, set to true.
- kim_activity: if appeared, 1 sentence on what he did (inspection, meeting, guidance, etc.), else null
- days_since_last_appearance: integer — use the CONFIRMED KIM JONG UN APPEARANCES tracker data above as ground truth. Only override if today's articles confirm a more recent appearance than the tracker shows.
- senior_officials: array of notable non-Kim appearances/activities (e.g. Choe Son Hui, Kim Yo Jong, Ri Pyong Chol). Each: name, role (title), activity (1 sentence). Max 2. Keep very brief — name and what they did, nothing more.
- (tone quadrants removed — do NOT include us_tone, rok_tone, russia_tone, china_tone or related qualifier/description fields)
- baseline_period: string describing the comparison baseline (e.g. "Mar 13-19")
- tone_shift: any tone that changed from yesterday's baseline, e.g. "US tone shifted from Neutral to Hostile". null if no change detected.
- propaganda_focus: top 2-3 topics KCNA is prioritizing today (e.g. "self-reliance economy", "nuclear deterrent", "anti-US imperialism")
- notable_omissions: anything conspicuously absent that was previously regular (e.g. "No mention of Russia for 3rd day", "Kim Yo Jong silent on ROK provocation"). null if nothing notable.
- key_phrase_changes: array of phrase frequency objects. Each: phrase (the exact phrase, e.g. "nuclear war deterrent"), count_this_week (integer, e.g. 3), count_prior (integer from prior 7 days, e.g. 0), delta_label (human-readable delta string, e.g. "↑ from ×0", "↑ new phrase", "→ stable", "→ normal"). Also include Kim Jong Un appearance tracking as the last item: phrase="Kim Jong Un public appearance", count_this_week=count, delta_label="→ normal" or similar. MAX 5 phrases — only include phrases that actually changed or are analytically significant. Do not pad with stable/routine phrases.
- doctrinal_shift: if any phrase represents a new doctrinal position (e.g. new weapons designation, revised nuclear posture language, novel alliance framing), describe in 1-2 sentences. These shifts historically precede hardware developments by 12-18 months. null if routine rhetoric.
- key_quotes: 1 direct quote from KCNA that is most analytically significant today (the single most important quote only). Each: quote (exact text, translated to English), source_article (KCNA article title). Empty array if nothing notable.
- output_volume: string assessment of today's KCNA output volume vs. normal (e.g. "Heavy — 23 articles (avg: 15)", "Light — 8 articles", "Normal — 14 articles"). Unusually high or low volume is a signal.
- silence_today: boolean (complete KCNA blackout)
- watch_flag: boolean — true if KCNA output contains ESCALATION-level rhetoric, silence after regular output, unusual Kim absence (7+ days), or nuclear/ICBM-related content
- bottom_line: 1-2 sentences MAX. State the single most important KCNA takeaway and what to watch next. Be ruthlessly concise. Example: "First use of 'sacred nuclear deterrent force' coincides with Yongbyon activity (Mar 19). Monitor Sohae through Apr 15."
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIGEST SYNTHESIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TARGET LENGTH — HARD MINIMUM 1,000 WORDS (5-minute read): The newsletter MUST contain at least 1,000 words of readable text (excluding HTML/metadata). Aim for 1,200-1,400 words (target ~1,300). Write substantive body text for each story — but keep each story TIGHT. Each top_stories item should have 2-3 sentences MAX (60-80 words) of body text — no more. Each overnight_items item should have 2-3 sentences (50-70 words). Each business_economy/northeast_asia/also_today item should have 1-2 sentences (40-60 words). Reach the word count target by covering MORE stories, not by making individual stories longer. If your draft is under 1,000 words, add more items to overnight_items or also_today rather than inflating story bodies.
Return a digest object with:
- digest_date: "{date_str}"
- re_line: one-line RE: summary (max 120 chars, key themes separated by ·)
- market_indicators: pass through the pre-collected market data object exactly as provided above. If no market data was provided, use null.
- morning_memo: THE TOP 3 STORIES AT A GLANCE. Array of exactly 3 strings. Each string is one sentence summarizing one of today's top Korea stories — based on reporting, social media traction, and policy impact. Think: what would a Korea desk officer tell their boss in the elevator? Lead with the verb, state the fact. Example: ["Seoul recalled its ambassador from Tokyo after Dokdo flyover", "BOK held rates at 2.75%, surprising markets expecting a cut", "Samsung announced $4B expansion of Austin fab, part of $350B pledge"]. These must be sourced from today's actual articles — no speculation, no interpretation.
- on_this_day: 1 historical Korea event that happened on today's date or within the next 7 days. Array with exactly 1 item: date (e.g. "March 26, 2010"), event (1 sentence), relevance (1 sentence connecting to current situation). Draw from major events: Cheonan sinking, nuclear tests, inter-Korean summits, armistice, provocations, key policy moments. If nothing notable, return empty array.
- key_stat: a single striking statistic or number pulled directly from TODAY's articles — not from databases or historical data. Must come from a story in the current digest. IMPORTANT: This stat MUST be different every day — do not repeat the same stat from the previous digest. Pick a FRESH number from today's unique news. Object with: number (the stat, e.g. "$2.3B", "53%", "12"), label (what it measures, under 60 chars), context (1 sentence explaining why it matters today), source (which article it came from). Pick the most policy-relevant number from today's news — trade figures, military spending, sanctions data, economic indicators, deployment numbers, etc.
- imagery_report: if satellite imagery analysis was published today (AEI, 38North, CSIS Beyond Parallel, Planet Labs), return an object with: source (e.g. "AEI / 38North"), date (e.g. "Mar 18-19"), label (e.g. "New imagery reports"), headline (main finding), body (2-3 sentences), source_links (array of {{label, url}} for each source cited), bp_location_ids (array of strings identifying which BP locations are affected, e.g. ["YBGN-ENR (Active/Expanding)", "THAAD-SNGJ (Active/Drawdown)"]). Return null if no imagery analysis today.
- bp_locations: array of 8 monitored location status objects. Each: name, status (normal/activity/elevated/alert), note (1-2 sentences describing recent changes and current status — e.g. "New construction observed at centrifuge hall. Activity has increased over past 2 weeks." or "No significant changes. Facility remains in standby configuration."), last_report (date string for most recent report, e.g. "Mar 19", "14 days ago", "Mar 18-19"), direction (string: "up" if activity is increasing/expanding, "down" if activity is decreasing/drawing down, "" if stable). Locations: Yongbyon Nuclear Complex, Sinpo South Shipyard, THAAD Site — Seongju County, Sohae Satellite Launch Station, Punggye-ri Nuclear Test Site, Tumangang–Khasan (NK-Russia border), Sinuiju–Dandong (NK-China border), Rason SEZ.
- rok_government: array of ROK ministry/agency actions from today's news (Presidential Office, MOFA, MND, MOU, MOTIE, NIS, FSC, MOJ — see system prompt for full list). Each: ministry (English name, e.g. "Blue House / President's Office", "Ministry of Foreign Affairs", "Ministry of National Defense"), ministry_korean (Korean name, e.g. "청와대", "외교부", "국방부", "산업통상자원부", "국토교통부", "방위사업청"), official (name of the official who acted/spoke, e.g. "FM Cho Tae-yul"), action (1-line headline), detail (1-2 sentences), source_label (short source label for link, e.g. "president.go.kr", "MoFA EN", "MND", "MOTIE EN", "DAPA EN"). Include only substantive policy actions — meetings, statements, personnel changes, policy announcements. This section renders as a 2-column card grid showing the full ROK government posture.
- calendar_watch: array of 8-12 key upcoming events in the next 14-30 days relevant to Korea policy. Keep it straightforward — just the facts. Each: month (3-letter, e.g. "MAR", "APR"), day (integer), headline (short title), detail (1-2 sentences). Include: congressional hearings, bilateral meetings, exercise dates, NK anniversaries (Kim Il Sung birthday Apr 15, Party founding Oct 10, etc.), diplomatic deadlines, UN sessions, G7/G20 meetings, IAEA board meetings, trade negotiation rounds, ROK domestic political dates, US-ROK 2+2 meetings, defense procurement milestones. Cast a wider net — readers want to see the full forward calendar. No signals, no urgency labels — just the event and when it happens.
- rok_assembly: array of ROK National Assembly activity from today's news — committee hearings, bills, votes related to defense/foreign affairs/unification/intelligence. Each: committee, action (1 line), detail (1-2 sentences). Empty array if no relevant activity.
- overnight_items: 8-12 highest-priority items. Each: url, source, category, headline (under 100 chars), body_text (2-3 sentences — summarize the key facts, then add context or implication. Be substantive — thin one-liners waste the reader's time)
- top_stories: 3-4 biggest HARD NEWS stories of the day — MINIMUM 3 always (even on slow days), 4 when multiple major stories compete. the stories generating the most noise, traction, and attention in Korea policy circles. These must be original reporting from wire services (Reuters, AP, AFP), correspondents (WSJ, NYT, WaPo, FT), Korean dailies (Yonhap, Korea Herald, Chosun, JoongAng), or government sources — NOT op-eds, analysis, think tank commentary, or publications like The Diplomat, Foreign Affairs, Brookings, etc. Pick the stories a Korea desk officer would be briefing their boss on first thing in the morning. Each: url, source, category_tag (use only: DPRK, US-Korea, NK-Russia-China, Technology, Business, Energy, Japan-Korea, China-Korea, Trilateral — do NOT use "Security" or "ROK Policy"), headline, body (MAX 3 sentences, aim for 2 — lead with the key facts: who, what, when, specific numbers. Add one beat of factual context. Do NOT interpret — state facts. Keep it TIGHT — no more than 3 sentences), so_what (1 sentence — name the specific decision, meeting, or timeline this directly affects. No editorializing. Example: "On the agenda for the Mar 28 Quad foreign ministers meeting"), pattern_note (1 sentence citing a specific historical precedent with dates, if applicable), src_line
- also_today: remaining articles score >= 4, INCLUDING Technology/Business/Energy stories. Include generously — more coverage is better than less. Each: url, source, category, headline, body_text (1 sentence), color_bar_class (cb-navy=DPRK, cb-red=Security, cb-lt=Policy, cb-mid=Assembly, cb-nkch=NK-Russia-China, cb-tech=Technology/Energy, cb-biz=Business)
- us_korea_deals: US-Korea trade and investment deals. Object with four keys. IMPORTANT — NO REPETITION across sub-sections: tariff rates belong ONLY in tariff_tracker (do not repeat rates in trade_policy). Investment totals belong ONLY in investment_package (do not restate in deals). trade_policy covers non-tariff policy actions only. Each fact appears exactly once.
  - investment_package: running status of the ROK-US $350B investment commitment. Object with: total_pledged (string, e.g. "$350B"), announced_to_date (string — sum of known WH tracker entries + any new deals today), pct_fulfilled (integer 0-100), latest_update (1 sentence on most recent change), known_deals (array: company, value, sector). Calculate announced_to_date from WH tracker entries below + today's news.
  - trade_policy: array of 4-6 NON-TARIFF US trade policy actions affecting South Korea. Do NOT repeat tariff rates already shown in tariff_tracker. Focus on: Section 301 investigations, export controls, CFIUS reviews, ITC cases, trade negotiation rounds. Each: item, agency, detail (1 sentence — current status with dates/deadlines), status (ACTIVE/PENDING/RISK/ESCALATION/RESOLVED/MONITOR). Only include currently active/relevant policies.
  - tariff_tracker: current US tariff rates on South Korean goods — this is the SINGLE authoritative source for all tariff rates (do not duplicate in trade_policy). Object with:
    - headline_rate, headline_status (ACTIVE/PAUSED/NEGOTIATING/ESCALATION/REDUCED), headline_note (1 sentence)
    - IMPORTANT: The current US reciprocal tariff rate on South Korea is 25%. Use 25% as the headline_rate unless today's articles report an official change to this rate.
    - sector_rates: array of sector-specific rates, each with: sector, rate, authority, status, note (1 sentence)
    - section_122_surcharge: string or null
    - last_change: date + description of most recent change
    - next_trigger: string or null — upcoming deadline/event
  - deals: array of NEW deals announced TODAY only. Each: url, source, headline, value (or null), sector, parties, detail (1 sentence), wh_tracker (boolean). Empty array if no new deals.
  REFERENCE — White House Investment Tracker ($350B pledge, Aug 2025 summit). Known entries:
    Samsung Electronics: $37B (Semiconductors), Hyundai: $26B (Manufacturing), SK Group: $22B (Semiconductors & Batteries), HD Hyundai: $1.3B (Energy & Shipbuilding), LS Cable & System: $689M (Manufacturing), Samsung Biologics: $280M (Pharma), Paris Baguette: $160M (Food & Beverage), Hanwha Ocean: $70M (Manufacturing).
  All MUST appear in known_deals. Set wh_tracker=true for any Korean company investing in the US.
- business_economy: array of Korea-related business and economic news from today. Focus on: major conglomerates (Samsung, SK, Hyundai, LG, Hanwha, Lotte, POSCO, Doosan), earnings/revenue, M&A, factory openings/closures, supply chain moves, export/import data, GDP/inflation/employment figures, BOK rate decisions, stock market moves, real estate, startup/venture capital. Each: url, source, headline, body_text (1-2 sentences — state the facts with specific numbers, then add one factual connection to a policy context if obvious: e.g. "Second US plant; cumulative ROK EV investment in US now $12.4B"), companies (array of company names involved, e.g. ["Samsung Electronics", "SK Hynix"]), sector (tech/auto/energy/finance/manufacturing/real-estate/macro). Include ALL qualifying business stories — this section should be comprehensive.
- northeast_asia: array of 4-8 items (MINIMUM 3 — always include at least one Japan-Korea, one China-Korea, and one Russia-Korea or Trilateral item even on slow news days) covering Japan-Korea, China-Korea, Russia-Korea, and US-ROK-Japan trilateral developments from today's news. Combine Japan-, China-, and Russia-related Korea stories into this single section. Each: url, source, headline, body_text (1-2 sentences — facts first, then one beat of context), category (one of: japan-history, trilateral, gsomia, japan-trade, japan-diplomatic, japan-defense, territorial, thaad-retaliation, china-coercion, rare-earth, china-diplomatic, china-military, china-trade, china-opinion, russia-weapons, russia-diplomatic, russia-labor, russia-sanctions, russia-military), signal_type (ESCALATION/ANOMALY/DEVELOPMENT/CONFIRMATION/CONTEXT), is_reaction_source (boolean — true if from Global Times, Xinhua, People's Daily, China Daily, TASS; false otherwise), region_tag ("Japan-Korea" or "China-Korea" or "Trilateral" or "Russia-Korea" — used for visual grouping). Russia-Korea items here are for bilateral diplomatic/economic stories; NK-Russia weapons/cooperation stories belong in top_stories or overnight_items with NK-Russia-China category. Empty array if no relevant stories today. Do NOT duplicate items already in top_stories or overnight_items.
- public_sentiment: standing dashboard of Korean public opinion polling — ALL metrics MUST come from the SAME Gallup Korea weekly poll (same survey date). Do NOT mix dates across metrics. Object with:
  - presidential_approval: object with value (percentage as string, e.g. "67%"), trend (up/down/stable), source (polling firm name, e.g. "Gallup Korea"), last_updated (date string, e.g. "Mar 17-19, 2026"). IMPORTANT: Use the LATEST Gallup Korea weekly poll. As of March 3rd week 2026 the latest confirmed figures are: 67% approval, DP 46%, PPP 20%, independents 27% (surveyed Mar 17-19). Update ALL metrics together if new polling data appears in today's articles, otherwise carry forward the baseline values provided. Never mix poll dates.
  - party_ruling: object with value (percentage as string, e.g. "46%"), party (English name, e.g. "Democratic Party"), party_kr (Korean name, e.g. "더불어민주당"), trend (up/down/stable), source, last_updated. MUST use the same Gallup Korea poll date as presidential_approval.
  - party_opposition: object with value (percentage as string, e.g. "20%"), party (English name, e.g. "People Power Party"), party_kr (Korean name, e.g. "국민의힘"), trend (up/down/stable), source, last_updated. MUST use the same Gallup Korea poll date as presidential_approval.
  - party_independent: object with value (percentage as string, e.g. "27%"), trend (up/down/stable), source, last_updated. No party preference / independents (무당층) from the same Gallup Korea weekly poll. MUST use the same poll date. This is the swing voter share — when it spikes, it signals disillusionment with both major parties.
  - gallup_spotlight: object or null. The latest Gallup Korea weekly special-topic finding (each weekly poll covers a rotating social/policy issue beyond standard approval numbers). Object with: topic (short label, e.g. "Juvenile Crime Age Limit"), finding (1 sentence summarizing the key result with a number, e.g. "68% of respondents support lowering the juvenile offender age threshold from 14 to 12"), poll_date (date string). The collector provides a raw headline in gallup_spotlight.headline — rewrite it into a clean English topic + finding sentence. null if no special topic was collected.
  - discourse_flag: string or null. Flag any active protests, viral social media events, or public discourse spikes related to US-Korea, China-Korea, or Japan-Korea relations (e.g. "Anti-US protest at Yongsan — 3,000 attended", "Naver trending: #NoJapan revival over Fukushima water"). null if nothing notable.
  If no polling data is available in today's articles for any metric, set its value to null and note "No recent data" in last_updated.
- rok_personnel: array of ROK government personnel changes from today's news — ministerial appointments, cabinet reshuffles, ambassador nominations, military command changes, senior civil service appointments, resignations, dismissals. Each: position (title being filled/vacated), name (person appointed/departing), action (appointed/resigned/dismissed/nominated/confirmed), detail (1-2 sentences on context and significance), predecessor (name of previous holder, if relevant). Empty array if no personnel changes today.
- social_statements: 3-5 notable statements from TODAY's news by government officials, senior policymakers, or military leaders. Prioritize: ROK President, ROK opposition leader (e.g. Lee Jae Myung), ROK FM/DM, US SecState/SecDef/NSA, USFK Commander, UN officials, Japan PM/FM, DPRK officials (via KCNA). Pull direct quotes from today's articles. Each: avatar_initials (2 letters), who (name), handle_context (title/role), platform_date (source · date), quote_text (the direct quote), analyst_note (1 sentence — factual context only: when was the last time this language was used, or what decision/meeting does this precede. No interpretation of what the speaker "signals" or "suggests"), badge_class (sb-p=policy, sb-r=security/red, sb-s=specialist/purple), url (link to source article where the statement was reported)
- opeds_today: qualifying Tier 2 pieces, ordered by prestige then score
- academic_today: qualifying Tier 3 pieces, ordered by journal_tier then score
- kcna_delta: the Tier 4 object
- timeline_candidates: list of urls flagged as timeline_candidate=true
IMPORTANT — NO OVERLAP / NO DUPLICATES:
- Each article must appear in exactly ONE section. A story in top_stories must NOT also appear in overnight_items, also_today, northeast_asia, business_economy, or us_korea_deals. Deduplicate by URL AND by topic — if a story qualifies for multiple sections, place it in the highest-priority section: top_stories > overnight_items > northeast_asia > us_korea_deals > also_today.
- If the same topic (e.g. BOK rate decision, BTS concert) appears from multiple sources, include it ONCE using the best source — do NOT include separate entries for Reuters, Yonhap, and Korea Herald all covering the same event.
- ENTERTAINMENT FILTER — HARD BLOCK: NEVER include K-pop (BTS, Blackpink, NewJeans, aespa, etc.), K-drama, celebrity, idol, music, or entertainment news in any section. This newsletter is strictly for security, trade, technology, and foreign affairs. No exceptions.
- story_count: total Tier 1 articles processed
- oped_count: qualifying Tier 2 count
- academic_count: qualifying Tier 3 count
Return ONLY valid JSON. No markdown fences, no preamble."""

# ─────────────────────────────────────────────────────────────────────────────
# MAIN DIGEST FUNCTION
# ─────────────────────────────────────────────────────────────────────────────
def _count_digest_words(digest: dict) -> int:
    """Count readable words across all text fields."""
    words = 0
    for mi in (digest.get("morning_memo") or []):
        words += len(str(mi).split())
    for section_key in ("top_stories", "overnight_items", "also_today", "business_economy",
                         "opeds_today", "academic_today", "social_statements",
                         "northeast_asia"):
        for item in (digest.get(section_key) or []):
            for field in ("body", "body_text", "summary", "detail", "quote_text",
                          "so_what", "pattern_note", "central_argument", "analyst_note"):
                words += len(str(item.get(field, "")).split())
    kcna = digest.get("kcna_delta") or {}
    for field in ("bottom_line", "doctrinal_shift"):
        words += len(str(kcna.get(field, "")).split())
    return words


def _check_content_minimums(digest: dict) -> list[str]:
    """Check hard content minimums. Returns list of failures (empty = pass)."""
    failures = []
    word_count = _count_digest_words(digest)
    if word_count < 1000:
        failures.append(f"WORD COUNT: {word_count} words (hard minimum 1000)")
    top = len(digest.get("top_stories") or [])
    if top < 3:
        failures.append(f"TOP STORIES: {top} (minimum 3)")
    overnight = len(digest.get("overnight_items") or [])
    if overnight < 8:
        failures.append(f"OVERNIGHT ITEMS: {overnight} (minimum 8)")
    memo = len(digest.get("morning_memo") or [])
    if memo < 3:
        failures.append(f"MORNING MEMO: {memo} (minimum 3)")
    return failures


def _call_claude(client, user_prompt: str, max_tokens: int = 16000) -> dict:
    """Single Claude API call. Returns parsed digest dict."""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}]
    )
    if response.stop_reason == "max_tokens":
        print(f"  ⚠  Response truncated (hit {response.usage.output_tokens} tokens)")
    if not response.content:
        raise ValueError("Empty response from Claude API")
    raw_text = response.content[0].text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
        if raw_text.endswith("```"):
            raw_text = raw_text.rsplit("```", 1)[0]
    return json.loads(raw_text)


def generate_digest(payload: dict, db_context: str = "") -> dict:
    """Call Claude and return structured digest JSON. Retries on failure and enforces content minimums."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Missing ANTHROPIC_API_KEY environment variable. Set it before running.")
    client = anthropic.Anthropic(api_key=api_key)
    from zoneinfo import ZoneInfo
    date_str = datetime.now(ZoneInfo("America/New_York")).strftime("%A, %B %-d, %Y")
    user_prompt = build_user_prompt(payload, date_str, db_context=db_context)
    total_articles = sum(len(v) for k, v in payload.items() if isinstance(v, list))
    print(f"\n🤖  Generating digest ({total_articles} articles → Claude)...")

    MAX_ATTEMPTS = 3
    digest = None

    for attempt in range(MAX_ATTEMPTS):
        try:
            if attempt == 0:
                digest = _call_claude(client, user_prompt)
            else:
                # Re-prompt with the previous output + expansion instructions
                expansion_prompt = (
                    f"Your previous digest output failed content minimums:\n"
                    + "\n".join(f"  • {f}" for f in content_failures)
                    + "\n\nHere is your previous output:\n"
                    + json.dumps(digest, ensure_ascii=False)[:8000]
                    + "\n\nRevise and return a COMPLETE updated digest JSON that fixes ALL failures above. "
                    "Specifically:\n"
                    "- WORD COUNT: Each top_stories body must be 80-100 words. Each overnight_items body_text must be 50-70 words. "
                    "Each business_economy/northeast_asia/also_today item must be 40-60 words. Expand with factual context, specific numbers, historical precedents.\n"
                    "- TOP STORIES: Include at least 3 stories. Pull from the available articles.\n"
                    "- OVERNIGHT ITEMS: Include at least 8 items.\n"
                    "- MORNING MEMO: Include exactly 3 items.\n"
                    "Return ONLY valid JSON."
                )
                messages = [
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": json.dumps(digest, ensure_ascii=False)[:4000]},
                    {"role": "user", "content": expansion_prompt}
                ]
                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=16000,
                    system=SYSTEM_PROMPT,
                    messages=messages
                )
                if not response.content:
                    raise ValueError("Empty response from Claude API")
                raw_text = response.content[0].text.strip()
                if raw_text.startswith("```"):
                    raw_text = raw_text.split("\n", 1)[1]
                    if raw_text.endswith("```"):
                        raw_text = raw_text.rsplit("```", 1)[0]
                digest = json.loads(raw_text)

            # Ensure market data from collector is preserved
            if payload.get("market_indicators") and not digest.get("market_indicators"):
                digest["market_indicators"] = payload["market_indicators"]

            # Check content minimums
            content_failures = _check_content_minimums(digest)
            word_count = _count_digest_words(digest)
            top_count = len(digest.get("top_stories") or [])
            overnight_count = len(digest.get("overnight_items") or [])

            if content_failures and attempt < MAX_ATTEMPTS - 1:
                print(f"  ⚠  Attempt {attempt + 1}: content too thin (~{word_count} words, "
                      f"{top_count} top stories, {overnight_count} overnight) — retrying with expansion prompt")
                time.sleep(2)
                continue

            if content_failures:
                print(f"  ⚠  Final attempt still below minimums (~{word_count} words) — proceeding with best result")
            else:
                print(f"  ✅  Digest generated: ~{word_count} words, {top_count} top stories, "
                      f"{overnight_count} overnight items")
            return digest

        except (anthropic.APIError, anthropic.APIConnectionError) as e:
            if attempt < MAX_ATTEMPTS - 1:
                wait = 5 * (attempt + 1)
                print(f"  ⚠  API error (retrying in {wait}s): {e}")
                time.sleep(wait)
            else:
                print(f"  ✗  API error (giving up): {e}")
                raise
        except json.JSONDecodeError as e:
            if attempt < MAX_ATTEMPTS - 1:
                print(f"  ⚠  JSON parse error (retrying): {e}")
                time.sleep(2)
            else:
                print(f"  ✗  JSON parse error: {e}")
                raise

    return digest  # fallback (shouldn't reach here)


if __name__ == "__main__":
    payload = json.loads(Path("collected.json").read_text())
    digest = generate_digest(payload)
    Path("digest.json").write_text(json.dumps(digest, ensure_ascii=False, indent=2))
    print("  → Written to digest.json")
