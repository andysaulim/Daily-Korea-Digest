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
GROUNDING — ZERO HALLUCINATION RULE (CRITICAL):
You are writing an intelligence product. Getting a name, title, date, or fact wrong destroys credibility. One wrong name and the reader stops trusting every fact in the digest.
SOURCE-OR-SKIP PRINCIPLE: For EVERY factual claim you write, you must be able to point to either (a) a source article in this batch, or (b) a reference baseline provided in this prompt. If a fact comes from neither, DO NOT INCLUDE IT. An omission is always better than an invention.
- ONLY use names, titles, figures, and claims that appear explicitly in the source articles provided. If an article says "Japan's prime minister" without naming them, use "Japan's prime minister" — do NOT fill in a name from your training data.
- NEVER substitute a name from your memory when the source text is ambiguous. Your training data may be outdated — leaders change, officials rotate, titles shift. The source article is ground truth.
- If two sources conflict on a fact, note both. If a source is vague, stay vague. Precision means knowing what you DON'T know.
- Cross-check: before writing any person's name + title, verify that BOTH the name AND the title appear together in at least one source article in this batch. If not, do not assert the pairing.
- HISTORICAL CLAIMS: Do NOT cite specific historical dates or precedents from memory. pattern_note and analyst_note fields should ONLY reference precedents that are mentioned in today's source articles or in the reference databases provided in this prompt. If no relevant precedent appears in the provided data, set the field to null rather than inventing one. A wrong date is worse than no date.
- FACILITY STATUS: For bp_locations, if today's articles contain a new report about a facility (satellite imagery, think tank analysis), update that facility's status and note from the article. If no article mentions a facility today, CARRY FORWARD the last known status and note from the BP LOCATIONS HISTORY tracker — do NOT blank it to "No new reporting". The tracker preserves context from prior reports so readers always see the most recent known status. Only set note to "No new reporting" if a facility has NEVER had a report in the tracker history.
- OMISSIONS & STREAKS: Do NOT claim "X absent for N days" or "no mention of Y for N days" unless the KCNA RHETORIC HISTORY tracker data provided in this prompt supports the specific count. If no tracker history is available, do not fabricate streak counts — say "absent today" without a count.
CURRENT POLITICAL LEADERS — REFERENCE (as of March 2026, update from today's articles if changed):
- ROK President: Lee Jae-myung (이재명), Democratic Party, inaugurated Feb 2026
- ROK PM: Han Duck-soo (한덕수) (acting/holdover — update if today's articles name a new PM)
- Japan PM: Takaichi Sanae (高市早苗), LDP, took office Nov 2025 (NOT Kishida, NOT Ishiba — both are former PMs)
- US President: Donald Trump (2nd term, inaugurated Jan 2025)
- US SecState: Marco Rubio; US SecDef: Pete Hegseth; US NSA: Mike Waltz
- DPRK: Kim Jong Un (Chairman, State Affairs Commission)
- PRC: Xi Jinping (President); PRC FM: Wang Yi
- UN Secretary-General: Antonio Guterres
- USFK Commander: Gen. Paul LaCamera (update if rotated)
If today's articles name a different officeholder for any position, use the name from the article.
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
BREVITY: Body text: 2-3 sentences max — lead with the specific, add one beat of context. "So what": 1 sentence. Pattern notes: 1 sentence with dates. Academic summaries: 3 sentences (exception to general brevity rule). Cut all filler, hedging, and editorializing. If you can say it in fewer words, do.
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
- ONE TOPIC = ONE ENTRY across the ENTIRE digest. Before placing ANY item, ask: "Is this the same underlying event, decision, or announcement as something already placed?" If yes, DO NOT include it — regardless of source, angle, or section.
- Common duplicates to watch for (these are the SAME topic and must appear only ONCE):
  * "BOK holds rates" / "BOK rate decision" / "Central bank keeps rates steady" — ONE entry
  * "Kim Jong Un inspects factory" / "Kim visits munitions site" / "KCNA reports Kim guidance" — ONE entry
  * "Samsung Q1 earnings" / "Samsung profit rises" / "Samsung chip revenue up" — ONE entry
  * "US-ROK exercise begins" / "Freedom Shield kicks off" / "Joint military drill starts" — ONE entry
  * Any wire story (Reuters/AP/AFP) picked up by Korean outlets (Yonhap/Korea Herald/JoongAng) — same story, ONE entry
- Pick the BEST source for each topic and place it in the HIGHEST appropriate section. Do NOT scatter the same topic across top_stories AND overnight_items AND business_economy.
- SAME POLICY across sections: If a tariff rate or trade policy is mentioned in tariff_tracker, do NOT repeat the same information in trade_policy items or deal entries. Tariff rates and Section 232/122 actions belong ONLY in tariff_tracker. Section 301 investigations, export controls, CFIUS reviews belong ONLY in trade_policy. Each fact appears ONCE in the most appropriate sub-section.
- FINAL DEDUP PASS — MANDATORY: After drafting all sections, go through EVERY item in this order: top_stories, overnight_items, business_economy, northeast_asia, also_today. For each item, check if the same topic already appeared in a prior section. If it did, DELETE the duplicate. Two items about the same subject from different sources (e.g. Reuters and Yonhap both covering BOK) = duplicate. Two items about the same person doing the same thing (e.g. "Kim inspects factory" in overnight and "Kim Jong Un guidance visit" in also_today) = duplicate. Remove the one in the lower-priority section.
- K-POP / ENTERTAINMENT — HARD BLOCK: NEVER include K-pop, BTS, Blackpink, K-drama, entertainment, celebrity, idol, music industry, or cultural export news in ANY section — not top_stories, not overnight_items, not also_today, not business_economy, not anywhere. Even if a K-pop story has trade or economic angles (e.g. "BTS revenue impact"), EXCLUDE it. This newsletter covers security, trade policy, technology, and foreign affairs ONLY. Do NOT use "K-pop" or "Entertainment" as a category.
- CATEGORIES: Valid categories are: DPRK, US-Korea, NK-Russia-China, Technology, Business, Energy, Japan-Korea, China-Korea, Trilateral. Do NOT use "Security", "ROK Policy", or "K-pop" as category labels on top_stories.
Return ONLY valid JSON. No markdown, no preamble, no commentary outside the JSON structure."""

# ─────────────────────────────────────────────────────────────────────────────
# USER PROMPT BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _build_kcna_summary_block(payload: dict) -> str:
    """Format the pre-collected KCNA summary into a prompt block."""
    summary = payload.get("kcna_summary")
    if not summary or not summary.get("total_articles"):
        return ""
    lines = [
        f"KCNA OUTPUT SUMMARY (scraped today — use for output_volume and propaganda_focus):",
        f"Total articles collected: {summary['total_articles']}",
    ]
    cats = summary.get("categories", {})
    if cats:
        cat_strs = [f"{cat} ({count})" for cat, count in list(cats.items())[:15]]
        lines.append(f"Categories: {', '.join(cat_strs)}")
    headlines = summary.get("headlines", [])
    if headlines:
        lines.append(f"\nToday's KCNA headlines ({len(headlines)} articles):")
        for h in headlines:
            lines.append(f"  • {h}")
    lines.append("")  # trailing newline
    return "\n".join(lines)


def build_user_prompt(payload: dict, date_str: str, db_context: str = "") -> str:
    def tier_json(articles: list, max_items: int = 60) -> str:
        trimmed = articles[:max_items]
        result = []
        for a in trimmed:
            item = {
                "title":   a.get("title", ""),
                "url":     a.get("url", ""),
                "summary": a.get("summary", "")[:800],
                "source":  a.get("source", ""),
                "lang":    a.get("lang", "EN"),
                "prestige":    a.get("prestige"),
                "journal_tier": a.get("journal_tier"),
            }
            if a.get("tags"):
                item["tags"] = a["tags"]
            result.append(item)
        return json.dumps(result, ensure_ascii=False, indent=1)

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

    # KCNA rhetoric history (persistent tracker)
    kcna_block = ""
    from kcna_tracker import build_context_block as kcna_context
    kcna_history = kcna_context()
    if kcna_history:
        kcna_block = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{kcna_history}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

    # BP locations history (persistent tracker)
    bp_block = ""
    from bp_tracker import build_context_block as bp_context
    bp_history = bp_context()
    if bp_history:
        bp_block = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{bp_history}
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
CRITICAL — SOURCE GROUNDING: Every name, title, number, and fact you write MUST come from the source articles below. Do NOT fill in names from memory — if the article says "Japan's PM" without a name, write "Japan's PM". Use the CURRENT POLITICAL LEADERS reference in the system prompt only when the source article clearly refers to that role. If in doubt, quote the source text.
CRITICAL — SOURCE URLs: Every article, op-ed, academic paper, deal, and statement MUST include the original source URL from the input data. Use the exact URL provided in the feed data. Never use "#" or placeholder URLs. If no URL is available for an item, omit the url field entirely rather than using a placeholder.
{market_block}
{sentiment_block}
{kim_block}
{kcna_block}
{bp_block}
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
- pattern_note: For ESCALATION or ANOMALY only. 1 sentence citing a precedent ONLY if the precedent is mentioned in today's source articles or the CSIS database context provided. Do NOT cite historical dates from memory — if no sourced precedent exists, set to null.
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
{_build_kcna_summary_block(payload)}
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
- notable_omissions: anything conspicuously absent that was previously regular. ONLY cite specific day counts (e.g. "3rd day") if the KCNA RHETORIC HISTORY tracker data supports it — otherwise just note the absence without a count (e.g. "No mention of Russia today" instead of "No mention of Russia for 3rd day"). null if nothing notable.
- key_phrase_changes: array of phrase frequency objects. IMPORTANT: Use the KCNA RHETORIC HISTORY tracker data provided in this prompt as ground truth for count_prior values. If no tracker history is available, set count_prior to 0 and delta_label to "no baseline" — do NOT invent prior counts. Each: phrase (the exact phrase, e.g. "nuclear war deterrent"), count_this_week (integer — count from TODAY's KCNA articles only), count_prior (integer from tracker history — use AGGREGATE PHRASE COUNTS if available, otherwise 0), delta_label (human-readable delta string, e.g. "↑ from ×0", "↑ new phrase", "→ stable", "no baseline"). Also include Kim Jong Un appearance tracking as the last item: phrase="Kim Jong Un public appearance", count_this_week=count, delta_label based on tracker data. MAX 5 phrases — only include phrases that actually changed or are analytically significant. Do not pad with stable/routine phrases.
- doctrinal_shift: if any phrase represents a new doctrinal position (e.g. new weapons designation, revised nuclear posture language, novel alliance framing), describe in 1-2 sentences. These shifts historically precede hardware developments by 12-18 months. null if routine rhetoric.
- key_quotes: 1 direct quote from KCNA that is most analytically significant today (the single most important quote only). Each: quote (exact text, translated to English), source_article (KCNA article title). Empty array if nothing notable.
- output_volume: string assessment of today's KCNA output volume vs. normal (e.g. "Heavy — 23 articles (avg: 15)", "Light — 8 articles", "Normal — 14 articles"). Use the KCNA OUTPUT SUMMARY above for the actual article count — do NOT guess the number. Unusually high or low volume is a signal.
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
- on_this_day: 1 historical Korea event that happened on today's date or within the next 7 days. Array with exactly 1 item: date (e.g. "March 26, 2010"), event (1 sentence), relevance (1 sentence connecting to current situation). ONLY use events from the VERIFIED KOREA DATES reference below — do NOT cite historical events from memory, as dates may be wrong. If no verified event matches today's date ±7 days, return empty array.
  VERIFIED KOREA DATES (use ONLY these):
  Jan 6 2016: DPRK 4th nuclear test (claimed H-bomb). Feb 12 2013: DPRK 3rd nuclear test. Mar 26 2010: ROKS Cheonan sinking (46 killed). Apr 15: Kim Il Sung birthday (Day of the Sun). Apr 27 2018: Moon-Kim Panmunjom summit. May 24 2009: Roh Moo-hyun dies. May 25 2009: DPRK 2nd nuclear test. Jun 12 2018: Trump-Kim Singapore summit. Jun 25 1950: Korean War begins. Jul 4 2017: DPRK first ICBM test (Hwasong-14). Jul 27 1953: Korean War armistice signed. Aug 15: Korean Liberation Day. Sep 3 2017: DPRK 6th nuclear test (claimed H-bomb). Sep 9: DPRK founding day. Sep 19 2018: Pyongyang Joint Declaration. Oct 9 2006: DPRK 1st nuclear test. Oct 10: DPRK Workers Party founding day. Nov 23 2010: Yeonpyeong Island shelling. Nov 29 2017: DPRK Hwasong-15 ICBM test. Dec 19 2011: Kim Jong Il death announced.
- key_stat: a single striking statistic or number pulled directly from TODAY's articles — not from databases or historical data. Must come from a story in the current digest. IMPORTANT: This stat MUST be different every day — do not repeat the same stat from the previous digest. Pick a FRESH number from today's unique news. Object with: number (the stat, e.g. "$2.3B", "53%", "12"), label (what it measures, under 60 chars), context (1 sentence explaining why it matters today), source (which article it came from). Pick the most policy-relevant number from today's news — trade figures, military spending, sanctions data, economic indicators, deployment numbers, etc.
- imagery_report: if satellite imagery analysis was published today (AEI, 38North, CSIS Beyond Parallel, Planet Labs), return an object with: source (e.g. "AEI / 38North"), date (e.g. "Mar 18-19"), label (e.g. "New imagery reports"), headline (main finding), body (2-3 sentences), source_links (array of {{label, url}} for each source cited), bp_location_ids (array of strings identifying which BP locations are affected, e.g. ["YBGN-ENR (Active/Expanding)", "THAAD-SNGJ (Active/Drawdown)"]). Return null if no imagery analysis today.
- bp_locations: array of 8 monitored location status objects. GROUNDING RULE: If today's articles contain a specific report about a facility (satellite imagery analysis, think tank report, news article), update that facility's status and note from the article. If NO article mentions a facility today, CARRY FORWARD the last known status, note, direction, and last_report from the BP LOCATIONS HISTORY tracker data provided in this prompt — this preserves context from prior reports so readers always see the most recent known status. Do NOT invent NEW activity descriptions or trending assessments from memory — only use what the tracker provides or what today's articles report. Each: name, status (normal/activity/elevated/alert — from today's report OR carried forward from tracker), note (1-2 sentences — from today's report if available, otherwise carry forward the tracker's note verbatim), last_report (date from today's source report, or carried forward from tracker history), direction (string: "up"/"down"/"" — from today's report or carried forward from tracker). Locations: Yongbyon Nuclear Complex, Sinpo South Shipyard, THAAD Site — Seongju County, Sohae Satellite Launch Station, Punggye-ri Nuclear Test Site, Tumangang–Khasan (NK-Russia border), Sinuiju–Dandong (NK-China border), Rason SEZ.
- rok_government: array of ROK ministry/agency actions from today's news (Presidential Office, MOFA, MND, MOU, MOTIE, NIS, FSC, MOJ — see system prompt for full list). Each: ministry (English name, e.g. "Blue House / President's Office", "Ministry of Foreign Affairs", "Ministry of National Defense"), ministry_korean (Korean name, e.g. "청와대", "외교부", "국방부", "산업통상자원부", "국토교통부", "방위사업청"), official (name of the official who acted/spoke, e.g. "FM Cho Tae-yul"), action (1-line headline), detail (1-2 sentences), source_label (short source label for link, e.g. "president.go.kr", "MoFA EN", "MND", "MOTIE EN", "DAPA EN"). Include only substantive policy actions — meetings, statements, personnel changes, policy announcements. This section renders as a 2-column card grid showing the full ROK government posture.
- calendar_watch: array of 5 key upcoming events in the next 14-30 days relevant to Korea policy (MAX 5 — pick the most consequential). GROUNDING: Only include events that are (a) mentioned in today's source articles with a specific date, (b) in the VERIFIED KOREA DATES reference above, or (c) in the tariff/trade baseline deadlines in this prompt. Do NOT invent upcoming events or dates from memory. Each: month (3-letter, e.g. "MAR", "APR"), day (integer), headline (short title), detail (1-2 sentences). No signals, no urgency labels — just the event and when it happens.
- rok_assembly: array of ROK National Assembly activity from today's news — committee hearings, bills, votes related to defense/foreign affairs/unification/intelligence. Each: committee, action (1 line), detail (1-2 sentences). Empty array if no relevant activity.
- overnight_items: 6 highest-priority items (MAX 6). SOURCE DIVERSITY — MANDATORY: No single source may appear more than 2 times in overnight_items. If you have 6 Yonhap articles, pick the 2 best and replace the rest with stories from other sources (Reuters, AP, Korea Herald, Chosun Ilbo, JoongAng Daily, Nikkei Asia, WSJ, etc.). A healthy mix draws from at least 4-5 different sources. TOPIC DIVERSITY — MANDATORY: Each overnight item MUST cover a DIFFERENT topic. If multiple articles cover the same event, policy, or subject (e.g. two stories about the same sanctions action, or two stories about the same military exercise from different sources), pick the BEST one and drop the duplicate. Different angles on the same underlying news (e.g. "Samsung quarterly earnings" and "Samsung profit driven by AI chips") count as the SAME topic — include only one. Each: url, source, category, headline (under 100 chars), body_text (2-3 sentences — summarize the key facts, then add context or implication. Be substantive — thin one-liners waste the reader's time)
- top_stories: 3-4 biggest HARD NEWS stories of the day — MINIMUM 3 always (even on slow days), 4 when multiple major stories compete. the stories generating the most noise, traction, and attention in Korea policy circles. These must be original reporting from wire services (Reuters, AP, AFP), correspondents (WSJ, NYT, WaPo, FT), Korean dailies (Yonhap, Korea Herald, Chosun, JoongAng), or government sources — NOT op-eds, analysis, think tank commentary, or publications like The Diplomat, Foreign Affairs, Brookings, etc. Pick the stories a Korea desk officer would be briefing their boss on first thing in the morning.
  TOPIC DIVERSITY — MANDATORY: Each top story MUST cover a DIFFERENT topic. If two articles are about the same subject (e.g. two stories about a BOK governor nominee, or two stories about the same military exercise), pick the BEST one and move the other to overnight_items or also_today. Aim to span different domains — e.g. one security/alliance story, one economic/policy story, one DPRK or regional story. Good mix examples: (1) US-Korea alliance update, (2) BOK policy move, (3) DPRK provocation; or (1) trade deal development, (2) ROK defense procurement, (3) inter-Korean diplomacy. Never run two stories on the same person, institution, or event.
  Each: url, source, category_tag (use only: DPRK, US-Korea, NK-Russia-China, Technology, Business, Energy, Japan-Korea, China-Korea, Trilateral — do NOT use "Security" or "ROK Policy"), headline, body (MAX 3 sentences, aim for 2 — lead with the key facts: who, what, when, specific numbers. Add one beat of factual context. Do NOT interpret — state facts. Keep it TIGHT — no more than 3 sentences), so_what (1 sentence — name the specific decision, meeting, or timeline this directly affects — ONLY if this decision/meeting is mentioned in today's articles or the calendar_watch/database context provided. No editorializing. Example: "On the agenda for the Mar 28 Quad foreign ministers meeting"), pattern_note (1 sentence citing a historical precedent — ONLY if the precedent appears in today's source articles or the CSIS database context. If no sourced precedent exists, set to null. Do NOT cite dates from memory.), src_line
- also_today: up to 6 remaining articles score >= 4 (MAX 6), INCLUDING Technology/Business/Energy stories. Each: url, source, category, headline, body_text (1-2 sentences), color_bar_class (cb-navy=DPRK, cb-red=Security, cb-lt=Policy, cb-mid=Assembly, cb-nkch=NK-Russia-China, cb-tech=Technology/Energy, cb-biz=Business)
- us_korea_deals: US-Korea trade and investment deals. Object with four keys. IMPORTANT — NO REPETITION across sub-sections: tariff rates belong ONLY in tariff_tracker (do not repeat rates in trade_policy). Investment totals belong ONLY in investment_package (do not restate in deals). trade_policy covers non-tariff policy actions only. Each fact appears exactly once.
  - investment_package: running status of the ROK-US $350B investment commitment. Object with: total_pledged (string, e.g. "$350B"), announced_to_date (string — sum of known WH tracker entries + any new deals today), pct_fulfilled (integer 0-100), latest_update (1 sentence on most recent change), known_deals (array: company, value, sector). Calculate announced_to_date from WH tracker entries below + today's news.
  - trade_policy: array of 4-6 NON-TARIFF US trade policy actions (MAX 6) affecting South Korea. Do NOT repeat tariff rates already shown in tariff_tracker. Focus on: Section 301 investigations, export controls, CFIUS reviews, ITC cases, trade negotiation rounds. Each: item, agency, detail (1 sentence — current status with dates/deadlines), status (ACTIVE/PENDING/RISK/ESCALATION/RESOLVED/MONITOR). Only include currently active/relevant policies.
  - tariff_tracker: current US tariff rates on South Korean goods — this is the SINGLE authoritative source for all tariff rates (do not duplicate in trade_policy). Object with:
    - headline_rate: the broadest currently active tariff rate applied to general Korean goods (see baseline reference below)
    - headline_status: ACTIVE/PAUSED/NEGOTIATING/ESCALATION/REDUCED
    - headline_note: 1 sentence summarizing the current tariff posture
    - BASELINE REFERENCE (as of Mar 2026 — update from today's articles if anything changes):
      The US-Korea Strategic Trade and Investment Deal (framework Jul 30 2025, reaffirmed at Trump-Lee Oct 29 2025 summit, USTR implementation Dec 3 2025) set a 15% reciprocal tariff rate under IEEPA/EO 14257. On Feb 20 2026 the Supreme Court struck down ALL IEEPA tariffs (6-3 ruling). The White House immediately imposed a 10% Section 122 surcharge on ALL countries (effective Feb 24 2026, expires Jul 24 2026 unless Congress extends). On Jan 27 2026 Trump threatened to raise Korea tariffs to 25% over delayed National Assembly ratification, but NO executive order was issued. On Mar 12 2026 the National Assembly passed the Special Investment Act (226-8-8) creating the Korea-US Strategic Investment Corporation to implement the $350B pledge. On Mar 11 2026 USTR launched Section 301 investigations into 16 trading partners including South Korea — these could provide new legal grounds for tariffs post-Section 122 expiry.
      Use 10% (Section 122) as the headline_rate unless today's articles report an official change.
    - sector_rates: array of sector-specific rates. IMPORTANT — break out Section 232 tariffs by sector. Each with: sector, rate, authority, status, note (1 sentence). BASELINE SECTOR RATES (update from today's articles if changed):
      * Steel & Aluminum: 50%, Section 232, ACTIVE — no exemption in US-Korea deal; all country exemptions eliminated Mar 2025
      * Copper: 50%, Section 232, ACTIVE — included in Mar 2025 Section 232 expansion
      * Automobiles & Auto Parts: 15%, Section 232 (reduced under US-Korea deal from 25%), REDUCED — retroactive to Nov 1 2025 per USTR Dec 3 2025 implementation notice
      * Timber / Lumber / Wood Derivatives: 15%, Section 232 (reduced under US-Korea deal), REDUCED — same USTR implementation
      * Semiconductors (narrow — advanced logic): 25%, Section 232 (Proclamation 11002), ACTIVE — effective Jan 15 2026; broader semiconductor tariffs TBD by Apr 14 2026 (Commerce/USTR report deadline); deal promises Korea terms "no less favorable" than comparable trading partners
      * Pharmaceuticals: up to 15%, Section 232 (per deal terms), PENDING — rate cap agreed in deal but specific Section 232 action not yet issued
      * Civil Aircraft & Parts: 0%, exempted under US-Korea deal, RESOLVED — tariffs removed per USTR Dec 3 2025 notice
      * Generic Pharma / Precursors / Rare Natural Resources: 0%, exempted under Aligned Partners list, RESOLVED — tariffs eliminated per deal
    - section_122_surcharge: string — BASELINE: "10% global surcharge (Section 122, effective Feb 24 2026, expires Jul 24 2026)" — update if today's articles report a change (Trump signaled possible increase to 15% statutory max but no formal action taken)
    - last_change: date + description of most recent change
    - next_trigger: string or null — upcoming deadline/event. BASELINE: "Jul 24 2026 — Section 122 surcharge expiry (150-day statutory limit); Apr 14 2026 — Commerce/USTR semiconductor tariff report due; Section 301 investigations ongoing"
  - deals: array of NEW deals announced TODAY that DIRECTLY involve both the United States and South Korea. Each: url, source, headline, value (or null), sector, parties, detail (1 sentence), wh_tracker (boolean). Empty array if no new deals.
    STRICT FILTER: Only include deals where BOTH parties are US and Korean entities, or where a Korean company is investing IN the United States, or where a US policy directly affects Korean trade. Do NOT include Korean company deals with non-US countries (e.g. Oceania, Middle East, EU, Japan). A Samsung Heavy order for an Oceanian shipper is NOT a US-Korea deal. A Hyundai contract with a German automaker is NOT a US-Korea deal. When in doubt, leave it out — this section is specifically for the US-Korea bilateral trade relationship.
  REFERENCE — White House Investment Tracker ($350B pledge). Timeline: framework agreed Jul 30 2025; Trump-Lee summit Aug 25 2025 (Washington); Trump state visit to Korea Oct 29 2025 (Gyeongju); National Assembly passed Special Investment Act Mar 12 2026 (226-8-8), creating Korea-US Strategic Investment Corporation. Investment structure: $150B shipbuilding, $200B strategic sectors (capped $20B/yr), $100B US energy purchases. Known entries:
    Samsung Electronics: $37B (Semiconductors), Hyundai: $26B (Manufacturing), SK Group: $22B (Semiconductors & Batteries), HD Hyundai: $1.3B (Energy & Shipbuilding), LS Cable & System: $689M (Manufacturing), Samsung Biologics: $280M (Pharma), Paris Baguette: $160M (Food & Beverage), Hanwha Ocean: $70M (Manufacturing), Korean Air: $36.2B (Boeing aircraft purchase, Oct 2025 summit), Korean Air / GE Aerospace: $13.7B (Engines for Boeing fleet, Oct 2025 summit).
  All MUST appear in known_deals. Set wh_tracker=true for any Korean company investing in the US.
- business_economy: array of up to 6 Korea-related business and economic news items from today (MAX 6 — pick the most policy-relevant). Focus on: major conglomerates (Samsung, SK, Hyundai, LG, Hanwha, Lotte, POSCO, Doosan), earnings/revenue, M&A, factory openings/closures, supply chain moves, export/import data, GDP/inflation/employment figures, BOK rate decisions, stock market moves, real estate, startup/venture capital. TOPIC DIVERSITY — MANDATORY: Each business_economy item MUST cover a DIFFERENT topic. If multiple articles cover the same company announcement, earnings report, or economic data release from different sources, pick the BEST one and drop the duplicate. Same company + same subject = same topic (e.g. "Hyundai EV sales up 30%" and "Hyundai reports record EV deliveries" are the SAME topic). Each: url, source, headline, body_text (1-2 sentences — state the facts with specific numbers, then add one factual connection to a policy context if obvious: e.g. "Second US plant; cumulative ROK EV investment in US now $12.4B"), companies (array of company names involved, e.g. ["Samsung Electronics", "SK Hynix"]), sector (tech/auto/energy/finance/manufacturing/real-estate/macro). Prioritize stories with policy implications over routine earnings — if you have more than 6 qualifying stories, drop the least policy-relevant ones.
- northeast_asia: array of 3-6 items (MAX 6; always include at least one Japan-Korea, one China-Korea, and one Russia-Korea or Trilateral item even on slow news days) covering Japan-Korea, China-Korea, Russia-Korea, and US-ROK-Japan trilateral developments from today's news. Combine Japan-, China-, and Russia-related Korea stories into this single section. Each: url, source, headline, body_text (1-2 sentences — facts first, then one beat of context), category (one of: japan-history, trilateral, gsomia, japan-trade, japan-diplomatic, japan-defense, territorial, thaad-retaliation, china-coercion, rare-earth, china-diplomatic, china-military, china-trade, china-opinion, russia-weapons, russia-diplomatic, russia-labor, russia-sanctions, russia-military), signal_type (ESCALATION/ANOMALY/DEVELOPMENT/CONFIRMATION/CONTEXT), is_reaction_source (boolean — true if from Global Times, Xinhua, People's Daily, China Daily, TASS; false otherwise), region_tag ("Japan-Korea" or "China-Korea" or "Trilateral" or "Russia-Korea" — used for visual grouping). Russia-Korea items here are for bilateral diplomatic/economic stories; NK-Russia weapons/cooperation stories belong in top_stories or overnight_items with NK-Russia-China category. Empty array if no relevant stories today. Do NOT duplicate items already in top_stories or overnight_items.
- public_sentiment: standing dashboard of Korean public opinion polling — ALL metrics MUST come from the SAME Gallup Korea weekly poll (same survey date). Do NOT mix dates across metrics. Object with:
  - presidential_approval: object with value (percentage as string, e.g. "67%"), trend (up/down/stable), source (polling firm name, e.g. "Gallup Korea"), last_updated (date string, e.g. "Mar 17-19, 2026"). IMPORTANT: Use the LATEST Gallup Korea weekly poll. As of March 3rd week 2026 the latest confirmed figures are: 67% approval, DP 46%, PPP 20%, independents 27% (surveyed Mar 17-19). Update ALL metrics together if new polling data appears in today's articles, otherwise carry forward the baseline values provided. Never mix poll dates.
  - party_ruling: object with value (percentage as string, e.g. "46%"), party (English name, e.g. "Democratic Party"), party_kr (Korean name, e.g. "더불어민주당"), trend (up/down/stable), source, last_updated. MUST use the same Gallup Korea poll date as presidential_approval.
  - party_opposition: object with value (percentage as string, e.g. "20%"), party (English name, e.g. "People Power Party"), party_kr (Korean name, e.g. "국민의힘"), trend (up/down/stable), source, last_updated. MUST use the same Gallup Korea poll date as presidential_approval.
  - party_independent: object with value (percentage as string, e.g. "27%"), trend (up/down/stable), source, last_updated. No party preference / independents (무당층) from the same Gallup Korea weekly poll. MUST use the same poll date. This is the swing voter share — when it spikes, it signals disillusionment with both major parties.
  - gallup_spotlight: object or null. The latest Gallup Korea weekly special-topic finding (each weekly poll covers a rotating social/policy issue beyond standard approval numbers). Object with: topic (short label, e.g. "Juvenile Crime Age Limit"), finding (1 sentence summarizing the key result with a number, e.g. "68% of respondents support lowering the juvenile offender age threshold from 14 to 12"), poll_date (date string). The collector provides a raw headline in gallup_spotlight.headline — rewrite it into a clean English topic + finding sentence. null if no special topic was collected.
  - discourse_flag: string or null. Flag any active protests, viral social media events, or public discourse spikes related to US-Korea, China-Korea, or Japan-Korea relations (e.g. "Anti-US protest at Yongsan — 3,000 attended", "Naver trending: #NoJapan revival over Fukushima water"). null if nothing notable.
  If no polling data is available in today's articles for any metric, set its value to null and note "No recent data" in last_updated.
- rok_personnel: array of ROK government personnel changes from today's news — ministerial appointments, cabinet reshuffles, ambassador nominations, military command changes, senior civil service appointments, resignations, dismissals. Each: position (title being filled/vacated), name (person appointed/departing), action (appointed/resigned/dismissed/nominated/confirmed), detail (1-2 sentences on context and significance), predecessor (name of previous holder, if relevant). Empty array if no personnel changes today.
- social_statements: 3-6 notable statements from TODAY's news (MAX 6) by government officials, senior policymakers, or military leaders. Prioritize: ROK President, ROK opposition leader (e.g. Lee Jae Myung), ROK FM/DM, US SecState/SecDef/NSA, USFK Commander, UN officials, Japan PM/FM, DPRK officials (via KCNA). Pull direct quotes from today's articles. Each: avatar_initials (2 letters), who (name), handle_context (title/role), platform_date (source · date), quote_text (the direct quote), analyst_note (1 sentence — factual context ONLY from today's source articles or the reference data in this prompt. State what decision/meeting this precedes ONLY if that event is mentioned in today's articles or the calendar_watch data. Do NOT claim "last time this language was used was [date]" from memory — if no sourced precedent exists, provide context from today's articles instead. No interpretation of what the speaker "signals" or "suggests"), badge_class (sb-p=policy, sb-r=security/red, sb-s=specialist/purple), url (link to source article where the statement was reported)
- opeds_today: qualifying Tier 2 pieces, ordered by prestige then score
- academic_today: qualifying Tier 3 pieces, ordered by journal_tier then score
- kcna_delta: the Tier 4 object
- timeline_candidates: list of urls flagged as timeline_candidate=true
PLACEMENT PRIORITY (highest wins): top_stories > overnight_items > northeast_asia > us_korea_deals > also_today. Each article appears in exactly ONE section — deduplicate by URL AND topic.
- story_count: total Tier 1 articles processed
- oped_count: qualifying Tier 2 count
- academic_count: qualifying Tier 3 count
Return ONLY valid JSON. No markdown fences, no preamble."""

# ─────────────────────────────────────────────────────────────────────────────
# MAIN DIGEST FUNCTION
# ─────────────────────────────────────────────────────────────────────────────
_TEXT_FIELDS = ("body", "body_text", "summary", "detail", "quote_text",
                "so_what", "pattern_note", "central_argument", "analyst_note")


def _count_digest_words(digest: dict) -> int:
    """Count readable words across all text fields."""
    words = 0
    for mi in (digest.get("morning_memo") or []):
        if isinstance(mi, dict):
            # Count text values from dict, not JSON key names
            for v in mi.values():
                if isinstance(v, str):
                    words += len(v.split())
        elif isinstance(mi, str):
            words += len(mi.split())
    for section_key in ("top_stories", "overnight_items", "also_today", "business_economy",
                         "opeds_today", "academic_today", "social_statements",
                         "northeast_asia"):
        for item in (digest.get(section_key) or []):
            for field in _TEXT_FIELDS:
                val = item.get(field, "")
                if val:
                    words += len(str(val).split())
    kcna = digest.get("kcna_delta") or {}
    for field in ("bottom_line", "doctrinal_shift"):
        val = kcna.get(field, "")
        if val:
            words += len(str(val).split())
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
    if overnight < 3:
        failures.append(f"OVERNIGHT ITEMS: {overnight} (minimum 3)")
    memo = len(digest.get("morning_memo") or [])
    if memo < 3:
        failures.append(f"MORNING MEMO: {memo} (minimum 3)")
    return failures


def _strip_fences(raw: str) -> str:
    """Remove markdown code fences if present."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return text


def _stream_claude(client, messages: list, max_tokens: int = 16000) -> dict:
    """Stream a Claude API call and return parsed digest dict."""
    collected = []
    with client.messages.stream(
        model="claude-opus-4-20250514",
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            collected.append(text)
    response = stream.get_final_message()
    if response.stop_reason == "max_tokens":
        print(f"  ⚠  Response truncated (hit {response.usage.output_tokens} tokens)")
    raw_text = "".join(collected)
    if not raw_text.strip():
        raise ValueError("Empty response from Claude API")
    return json.loads(_strip_fences(raw_text))


def _call_claude(client, user_prompt: str, max_tokens: int = 16000) -> dict:
    """Single Claude API call. Returns parsed digest dict."""
    return _stream_claude(client, [{"role": "user", "content": user_prompt}], max_tokens)


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

    MAX_ATTEMPTS = 4
    digest = None
    best_digest = None
    best_word_count = 0
    content_failures = []

    for attempt in range(MAX_ATTEMPTS):
        try:
            if attempt == 0 or digest is None:
                # First attempt, or previous attempt failed to produce any output
                digest = _call_claude(client, user_prompt)
            else:
                # Re-prompt with the previous output + specific expansion instructions
                word_deficit = max(0, 1000 - _count_digest_words(digest))
                expansion_prompt = (
                    f"Your previous digest output failed content minimums:\n"
                    + "\n".join(f"  • {f}" for f in content_failures)
                    + f"\n\nYou are ~{word_deficit} words short of the 1000-word minimum.\n"
                    + "\nHere is your previous output:\n"
                    + json.dumps(digest, ensure_ascii=False)[:8000]
                    + "\n\nRevise and return a COMPLETE updated digest JSON that fixes ALL failures above. "
                    "Specifically:\n"
                    "- WORD COUNT: The digest MUST reach at least 1000 words across all text fields. "
                    "Each top_stories body must be 60-80 words (2-3 dense sentences). "
                    "Each overnight_items body_text must be 50-70 words. "
                    "Each business_economy/northeast_asia/also_today item must be 40-60 words. "
                    "Add MORE items from the available articles to reach 1000+ words — do not inflate existing bodies with filler.\n"
                    "- TOP STORIES: Include at least 3 stories. Pull from the available articles.\n"
                    "- OVERNIGHT ITEMS: Include at least 3 items (max 6).\n"
                    "- MORNING MEMO: Include exactly 3 items.\n"
                    "Return ONLY valid JSON."
                )
                messages = [
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": json.dumps(digest, ensure_ascii=False)[:4000]},
                    {"role": "user", "content": expansion_prompt}
                ]
                digest = _stream_claude(client, messages)

            # Ensure market data from collector is preserved
            if payload.get("market_indicators") and not digest.get("market_indicators"):
                digest["market_indicators"] = payload["market_indicators"]

            # Track the best result across attempts
            word_count = _count_digest_words(digest)
            if word_count > best_word_count:
                best_digest = json.loads(json.dumps(digest))  # deep copy
                best_word_count = word_count

            # Check content minimums
            content_failures = _check_content_minimums(digest)
            top_count = len(digest.get("top_stories") or [])
            overnight_count = len(digest.get("overnight_items") or [])

            if content_failures and attempt < MAX_ATTEMPTS - 1:
                print(f"  ⚠  Attempt {attempt + 1}: content too thin (~{word_count} words, "
                      f"{top_count} top stories, {overnight_count} overnight) — retrying with expansion prompt")
                time.sleep(2)
                continue

            if content_failures:
                # Use the best result across all attempts
                if best_word_count > word_count:
                    print(f"  ⚠  Final attempt (~{word_count} words) — using best attempt (~{best_word_count} words)")
                    digest = best_digest
                    word_count = best_word_count
                    top_count = len(digest.get("top_stories") or [])
                    overnight_count = len(digest.get("overnight_items") or [])
                else:
                    print(f"  ⚠  All {MAX_ATTEMPTS} attempts below minimums (~{word_count} words) — proceeding with best result")
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


def regenerate_digest(payload: dict, previous_digest: dict,
                      validation_warnings: list[str], db_context: str = "") -> dict:
    """Re-generate digest by sending validation feedback to Claude.

    Reuses the same collected articles — only re-calls the Claude API with
    the previous output and specific instructions to fix validation failures.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Missing ANTHROPIC_API_KEY environment variable.")
    client = anthropic.Anthropic(api_key=api_key)
    from zoneinfo import ZoneInfo
    date_str = datetime.now(ZoneInfo("America/New_York")).strftime("%A, %B %-d, %Y")
    user_prompt = build_user_prompt(payload, date_str, db_context=db_context)

    word_count = _count_digest_words(previous_digest)
    warning_list = "\n".join(f"  - {w}" for w in validation_warnings)

    fix_prompt = (
        f"Your previous digest failed validation with these CRITICAL issues:\n"
        f"{warning_list}\n\n"
        f"Current word count: ~{word_count} words.\n\n"
        "Return a COMPLETE corrected digest JSON that fixes ALL issues above. "
        "Keep everything that was correct — only fix what failed. Specifically:\n"
        "- If word count is too low: write more substantive body text for each story "
        "(2-3 sentences per top_stories, 2-3 per overnight_items) and add more items.\n"
        "- If top_stories count is too low: include at least 3 top stories from the articles.\n"
        "- If overnight_items count is too low: include at least 3 items (max 6).\n"
        "- If morning_memo is too short: include exactly 3 items.\n"
        "- If KCNA delta is missing: generate the kcna_delta section from Tier 4 data.\n"
        "- If RE: line is missing: write a crisp one-liner RE: summary.\n"
        "Return ONLY valid JSON."
    )

    messages = [
        {"role": "user", "content": user_prompt},
        {"role": "assistant", "content": json.dumps(previous_digest, ensure_ascii=False)[:8000]},
        {"role": "user", "content": fix_prompt},
    ]

    print(f"  Sending validation feedback to Claude ({len(validation_warnings)} issues)...")
    try:
        digest = _stream_claude(client, messages)
        # Preserve market data
        if payload.get("market_indicators") and not digest.get("market_indicators"):
            digest["market_indicators"] = payload["market_indicators"]
        new_word_count = _count_digest_words(digest)
        top_count = len(digest.get("top_stories") or [])
        overnight_count = len(digest.get("overnight_items") or [])
        print(f"  ✅  Re-generated: ~{new_word_count} words, {top_count} top stories, "
              f"{overnight_count} overnight items")
        return digest
    except (anthropic.APIError, anthropic.APIConnectionError, json.JSONDecodeError) as e:
        print(f"  ⚠  Re-generation failed ({e}) — keeping previous digest")
        return previous_digest


if __name__ == "__main__":
    payload = json.loads(Path("collected.json").read_text())
    digest = generate_digest(payload)
    Path("digest.json").write_text(json.dumps(digest, ensure_ascii=False, indent=2))
    print("  → Written to digest.json")
