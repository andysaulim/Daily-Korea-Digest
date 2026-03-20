"""
CSIS Korea Digest — Digest Generator
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
SYSTEM_PROMPT = """You are the senior intelligence analyst for the CSIS Korea Chair directed by Dr. Victor Cha. You produce the CSIS Korea Digest — a daily Presidential Daily Brief-style product read by top government officials, leading Korea scholars, senior policymakers, and elite journalists.
Your readers include: Victor Cha (CSIS Korea Chair), senior NSC staff, State Department Korea desk officers, Pentagon Asia policy officials, leading academics (Georgetown, Stanford, Harvard Korea programs), top correspondents (WSJ, NYT, WaPo Seoul bureaus), allied government analysts (ROK, Japan, Australia), and UN sanctions monitors. Many of these readers have not yet read the news when they open this digest at 6 AM. They need two things: (1) a clear, concise summary of what happened, and (2) the analytical insight — the connections, pattern recognition, and forward-looking implications they would miss reading the news on their own. Lead with the facts, then add the value.
YOUR JOB: Process all incoming Korea-related content and produce a single structured JSON briefing package. Think like the best CIA analyst writing the President's Daily Brief — every sentence must tell the reader something they didn't already know or connect dots they haven't connected. If a summary just restates a headline, it has failed. If a "so what" is obvious to anyone who read the article, it has failed. The bar is: would Victor Cha learn something from this sentence?
QUALITY STANDARD: This product competes with the best intelligence briefings in Washington. Every entry must pass these tests:
1. NOVEL INSIGHT — Does this tell the reader something beyond what the headline says?
2. CONNECTIVE TISSUE — Does this link today's event to a broader pattern, historical precedent, or upcoming decision point?
3. FORWARD-LOOKING — Does this help the reader anticipate what happens next?
4. PRECISION — Are claims sourced, numbers specific, and attributions clear?
If an entry fails these tests, cut it or rewrite it. An empty section is better than a mediocre one.
CSIS KOREA CHAIR CONTEXT:
The CSIS Korea Chair tracks: NK–Russia military-technical cooperation and bilateral events; DPRK nuclear and missile program; ROK–US alliance and extended deterrence; inter-Korean relations; DPRK sanctions and economy; satellite imagery analysis of DPRK facilities. Current major research focus: NK–Russia Axis (Cambridge Elements book in progress with Maria Snegovaya, Sydney Seiler, Olena Guisoneva).
KEY MONITORED LOCATIONS: Yongbyon Nuclear Complex, Sohae Satellite Launch Station, Punggye-ri Nuclear Test Site, Sinpo South Shipyard, Sunan Airfield/Missile Complex, Tumangang–Khasan Railway Crossing (NK-Russia border), Sinuiju–Dandong Crossing (NK-China border), Yellow Sea NLL/PMZ (Northern Limit Line / Peace Management Zone), Vostochny/Dunai (Russian Far East — NK labor deployments, military cargo staging, ship transfers), Rason SEZ (DPRK special economic zone — trade activity, port operations, foreign presence).
NK–RUSSIA AXIS: The Korea Chair maintains a verified bilateral event database tracking all NK–Russia cooperation. Flag any NK–Russia stories (weapons transfers, diplomatic visits, economic agreements, military exchanges, technology transfer, labor deployments) for potential timeline addition. These are high priority.
JOURNALIST FLAGGING: The following reporters have special Korea expertise. When their bylines appear, treat the story as higher priority and note the journalist in your analysis:
- Timothy Martin, Dasl Yoon (WSJ Seoul bureau)
- Choe Sang-Hun (NYT Seoul bureau chief)
- Michelle Ye Hee Lee (WaPo Seoul)
- Christian Davies (FT Seoul)
- Hyonhee Shin, Josh Smith, Joyce Lee (Reuters Seoul)
- Ankit Panda (Carnegie — nuclear policy), Jenny Town (Stimson/38North)
- Andrei Lankov (Kookmin — most authoritative DPRK analyst)
- Rachel Minyoung Lee (NK language/rhetoric specialist)
- Jean Lee (AP), Laura Bicker (BBC), Chad O'Carroll (NK News)
SOURCE TIERS: This digest draws from 100+ sources including Korean-language newspapers (translate titles and key content to English), official ROK/US government feeds, Korean think tanks (ASAN, KINU, EAI, KIDA, Sejong, KIEP), European think tanks with Korea programs (IISS, VUB, Chatham House, IFRI, SWP, SIPRI), Chinese and Russian reaction layer sources, and academic journals.
KOREAN-LANGUAGE CONTENT: Some articles are in Korean (lang="KO"). Translate titles to English and incorporate their content into your analysis. Korean-language sources often break stories before English outlets.
ANALYTICAL VOICE:
- Write like the best CIA analyst, not a journalist or newsletter writer
- Summaries: state what happened clearly and concisely, then add what the reader can't see from the headline alone — the context, the implication, the connection
- Every summary should answer two questions: "What happened?" and "Why does it matter?"
- "So what" blocks: what specific decision, meeting, or policy question does this affect in the next 30 days? Name the decision-maker and the decision
- Pattern blocks: cite specific historical precedents with dates (e.g. "Last time Russia tone reached 'Very Warm' was October 2024, 3 weeks before the defense treaty signing")
- Morning Memo: the single most important analytical observation of the day. This is the paragraph the NSC director reads first. It should synthesize across all tiers and tell the reader what the collective signal means — not what happened, but what it means
- The RE: line should be a crisp one-liner readable on a phone in 5 seconds
BREVITY: Keep the entire digest tight. Summaries: 1-2 sentences max. Body text: 2-3 sentences, not 4. "So what": 1 sentence. Pattern notes: 1 sentence. The reader is time-constrained — every word must earn its place. Cut ruthlessly. If you're restating what the article title says, delete it and write something the reader doesn't already know.
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

IMPORTANT: Use this data for on_this_day, watch_today, and pattern_note fields.
For timeline_candidates: flag any NK-Russia stories that should be added to the CSIS NK-Russia cooperation timeline (268+ verified events since 2022).
For ESCALATION + DPRK stories: these may be added to the CSIS NK provocations database (540+ events since 1958). Ensure headline and description are suitable for database entry."""

    return f"""Today's date: {date_str}
Process each tier according to its instructions and return a single JSON object.
CRITICAL — SOURCE URLs: Every article, op-ed, academic paper, deal, and statement MUST include the original source URL from the input data. Use the exact URL provided in the feed data. Never use "#" or placeholder URLs. If no URL is available for an item, omit the url field entirely rather than using a placeholder.
{market_block}
{db_block}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TIER 1: NEWS ARTICLES (last 24h)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{tier_json(payload.get("tier1", []))}
For EACH article, return:
- url, source, translated_title (English title — translate if Korean)
- categories: array of: DPRK / ROK Policy / US-Korea / NK-Russia-China / Security / Technology / Business / Energy
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
- kim_appearance_today: boolean
- kim_activity: if appeared, 1 sentence on what he did (inspection, meeting, guidance, etc.), else null
- days_since_last_appearance: integer
- senior_officials: array of notable non-Kim appearances/activities (e.g. Choe Son Hui, Kim Yo Jong, Ri Pyong Chol). Each: name, role (title), activity (1 sentence), significance (1 sentence on why this matters). Max 3.
- us_tone, rok_tone, russia_tone, china_tone: each a string (Hostile/Elevated/Neutral/Warm/Very Warm/Silent)
- tone_shift: any tone that changed from yesterday's baseline, e.g. "US tone shifted from Neutral to Hostile". null if no change detected.
- propaganda_focus: top 2-3 topics KCNA is prioritizing today (e.g. "self-reliance economy", "nuclear deterrent", "anti-US imperialism")
- notable_omissions: anything conspicuously absent that was previously regular (e.g. "No mention of Russia for 3rd day", "Kim Yo Jong silent on ROK provocation"). null if nothing notable.
- key_phrase_changes: list of new or notably different phrases/formulations
- doctrinal_shift: if any phrase represents a new doctrinal position (e.g. new weapons designation, revised nuclear posture language, novel alliance framing), describe in 1-2 sentences. These shifts historically precede hardware developments by 12-18 months. null if routine rhetoric.
- key_quotes: 1-2 direct quotes from KCNA that are most analytically significant today. Each: quote (exact text, translated to English), source_article (KCNA article title), significance (1 sentence). Empty array if nothing notable.
- output_volume: string assessment of today's KCNA output volume vs. normal (e.g. "Heavy — 23 articles (avg: 15)", "Light — 8 articles", "Normal — 14 articles"). Unusually high or low volume is a signal.
- silence_today: boolean (complete KCNA blackout)
- watch_flag: boolean — true if KCNA output contains ESCALATION-level rhetoric, silence after regular output, unusual Kim absence (7+ days), or nuclear/ICBM-related content
- bottom_line: 2-3 sentences. Lead with the single most important signal from KCNA today and why a Korea policy analyst should care. Connect to broader patterns (e.g. "Russia rhetoric escalation coincides with confirmed Rajin port activity — this is messaging alignment with military action"). End with what to watch next.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIGEST SYNTHESIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return a digest object with:
- digest_date: "{date_str}"
- re_line: one-line RE: summary (max 120 chars, key themes separated by ·)
- market_indicators: pass through the pre-collected market data object exactly as provided above. If no market data was provided, use null.
- editor_note: THE MOST IMPORTANT PARAGRAPH IN THE DIGEST. 2-3 sentences that synthesize the dominant analytical theme across ALL tiers. This is NOT a summary of today's stories — it is the analytical observation that a senior official would not reach by reading the news individually. Connect signals across tiers: what does the KCNA rhetoric + the facility activity + the ROK political situation + the diplomatic calendar tell you when read together? What pattern is emerging? What decision window is opening or closing? Write this as if you are the Korea desk officer and the National Security Advisor just asked you: "What's the one thing I need to understand about Korea today?"
- watch_today: array of 2-3 items for "What to Watch Today" — upcoming events, scheduled meetings, votes, exercise dates, anniversaries of past provocations, or deadlines relevant to Korea policy in the next 48 hours. Each: headline (short), detail (1-2 sentences), type (event/deadline/anniversary/exercise), time (specific time + timezone if known, e.g. "3 PM KST" or "TBD"), urgency (critical/high/monitor — critical = requires immediate senior attention, high = track closely, monitor = background awareness), decision_point (1 sentence: what outcome or signal should the analyst watch for, e.g. "Watch for PPP defections — 3+ would signal bipartisan consensus").
- on_this_day: 1 historical Korea event that happened on today's date or within the next 7 days. Array with exactly 1 item: date (e.g. "March 26, 2010"), event (1 sentence), relevance (1 sentence connecting to current situation). Draw from major events: Cheonan sinking, nuclear tests, inter-Korean summits, armistice, provocations, key policy moments. If nothing notable, return empty array.
- key_stat: a single striking statistic or number pulled directly from TODAY's articles — not from databases or historical data. Must come from a story in the current digest. Object with: number (the stat, e.g. "$2.3B", "53%", "12"), label (what it measures, under 60 chars), context (1 sentence explaining why it matters today), source (which article it came from). Pick the most policy-relevant number from today's news — trade figures, military spending, sanctions data, economic indicators, deployment numbers, etc.
- bp_locations: array of 10 monitored location status objects. Each: name, status (normal/activity/elevated/alert), note (1 sentence). Locations: Yongbyon Nuclear Complex, Sohae Satellite Launch Station, Punggye-ri Nuclear Test Site, Sinpo South Shipyard, Sunan Airfield/Missile Complex, Tumangang–Khasan (NK-Russia border crossing — track train movements, cargo activity, troop/labor transfers), Sinuiju–Dandong (NK-China border crossing — track trade volume signals, bridge activity, diplomatic traffic), Yellow Sea NLL/PMZ (Northern Limit Line — track naval activity, fishing boat incursions, military posture), Vostochny/Dunai (Russian Far East — NK labor deployments, military cargo staging, ship transfers), Rason SEZ (DPRK special economic zone — port operations at Rajin, trade activity, foreign presence).
- rok_government: array of ROK ministry/agency actions from today's news (Presidential Office, MOFA, MND, MOU, MOTIE, NIS, FSC, MOJ — see system prompt for full list). Each: ministry, official (name of the official who acted/spoke, e.g. "FM Cho Tae-yul"), action (1-line headline), detail (1-2 sentences). Include only substantive policy actions — meetings, statements, personnel changes, policy announcements. This section is critical for tracking ROK government posture.
- rok_assembly: array of ROK National Assembly activity from today's news — committee hearings, bills, votes related to defense/foreign affairs/unification/intelligence. Each: committee, action (1 line), detail (1-2 sentences). Empty array if no relevant activity.
- overnight_items: 5-7 highest-priority items. Each: url, source, category, headline (under 100 chars), body_text (1-2 sentences — summarize the key facts, then add one beat of context or implication)
- top_stories: 3-4 biggest HARD NEWS stories of the day — the stories generating the most noise, traction, and attention in Korea policy circles. These must be original reporting from wire services (Reuters, AP, AFP), correspondents (WSJ, NYT, WaPo, FT), Korean dailies (Yonhap, Korea Herald, Chosun, JoongAng), or government sources — NOT op-eds, analysis, think tank commentary, or publications like The Diplomat, Foreign Affairs, Brookings, etc. Pick the stories a Korea desk officer would be briefing their boss on first thing in the morning. Each: url, source, category_tag, signal_type, headline, body (2-3 sentences — lead with the key facts, then add context: what changed, what's different from yesterday, what isn't being said), so_what (1 sentence — name the specific decision, meeting, or policy question this affects. "This is significant" is never acceptable. Example: "Creates pressure on SecState Blinken to raise NK arms transfers at the March 28 Quad meeting"), pattern_note (1 sentence with specific dates, if applicable), src_line
- also_today: remaining articles score >= 5, INCLUDING Technology/Business/Energy stories. Each: url, source, category, headline, body_text (1 sentence), color_bar_class (cb-navy=DPRK, cb-red=Security, cb-lt=Policy, cb-mid=Assembly, cb-nkch=NK-Russia-China, cb-tech=Technology/Energy, cb-biz=Business)
- us_korea_deals: US-Korea trade and investment tracker from today's news. Object with:
  - tariff_snapshot: current US tariff rate on ROK goods if mentioned in today's news (e.g. "25% on steel, 10% baseline"), or null if no updates
  - investment_package: ALWAYS include this — running total of ROK's $350B US investment commitment. Track cumulative deals announced, remaining pledged, and percentage fulfilled. Object: total_pledged ("$350B"), announced_to_date (cumulative $ from all announced deals), pct_fulfilled (percentage), latest_update (1 sentence — if no new deals today, say "No new deals today"). Never null — always return this object with best available estimates.
  - deals: array of individual deals from today's news. Track: FDI announcements (Samsung, SK, Hyundai, LG, Hanwha investments in US; US company investments in ROK), trade agreements, defense procurement (KF-21, arms sales, military contracts), energy deals (nuclear, LNG, renewables), tech partnerships (semiconductors, AI, batteries, EVs), supply chain agreements. Each: url, source, headline, value (deal value if mentioned, e.g. "$2.3B", or null), sector (defense/energy/tech/manufacturing/trade/tariff), parties (who is involved, 1 line), detail (1 sentence on significance). Empty array if no deals today.
- business_economy: array of Korea-related business and economic news from today. Focus on: major conglomerates (Samsung, SK, Hyundai, LG, Hanwha, Lotte, POSCO, Doosan), earnings/revenue, M&A, factory openings/closures, supply chain moves, export/import data, GDP/inflation/employment figures, BOK rate decisions, stock market moves, real estate, startup/venture capital. Each: url, source, headline, body_text (1-2 sentences — connect to policy implications: does this Samsung investment affect US-ROK trade negotiations? Does this BOK decision signal concern about won weakness during a political crisis? A policymaker reading this needs to understand why the business story matters for Korea policy), companies (array of company names involved, e.g. ["Samsung Electronics", "SK Hynix"]), sector (tech/auto/energy/finance/manufacturing/real-estate/macro). Include ALL qualifying business stories — this section should be comprehensive.
- rok_personnel: array of ROK government personnel changes from today's news — ministerial appointments, cabinet reshuffles, ambassador nominations, military command changes, senior civil service appointments, resignations, dismissals. Each: position (title being filled/vacated), name (person appointed/departing), action (appointed/resigned/dismissed/nominated/confirmed), detail (1-2 sentences on context and significance), predecessor (name of previous holder, if relevant). Empty array if no personnel changes today.
- social_statements: 2-4 notable statements from TODAY's news by government officials, senior policymakers, or military leaders. Prioritize: ROK President, ROK opposition leader (e.g. Lee Jae Myung), ROK FM/DM, US SecState/SecDef/NSA, USFK Commander, UN officials, Japan PM/FM, DPRK officials (via KCNA). Pull direct quotes from today's articles. Each: avatar_initials (2 letters), who (name), handle_context (title/role), platform_date (source · date), quote_text (the direct quote), analyst_note (1 sentence — what does this statement SIGNAL about the speaker's position or upcoming action? Not "this is significant" but "this framing suggests X is preparing to Y"), badge_class (sb-p=policy, sb-r=security/red, sb-s=specialist/purple), url (link to source article where the statement was reported)
- opeds_today: qualifying Tier 2 pieces, ordered by prestige then score
- academic_today: qualifying Tier 3 pieces, ordered by journal_tier then score
- kcna_delta: the Tier 4 object
- timeline_candidates: list of urls flagged as timeline_candidate=true
IMPORTANT — NO OVERLAP: Each article must appear in exactly ONE section. A story in top_stories must NOT also appear in overnight_items, also_today, or us_korea_deals. A story in overnight_items must NOT repeat in also_today. Deduplicate by URL — if a story qualifies for multiple sections, place it in the highest-priority section: top_stories > overnight_items > us_korea_deals > also_today.
- story_count: total Tier 1 articles processed
- oped_count: qualifying Tier 2 count
- academic_count: qualifying Tier 3 count
Return ONLY valid JSON. No markdown fences, no preamble."""

# ─────────────────────────────────────────────────────────────────────────────
# MAIN DIGEST FUNCTION
# ─────────────────────────────────────────────────────────────────────────────
def generate_digest(payload: dict, db_context: str = "") -> dict:
    """Call Claude and return structured digest JSON. Retries once on failure."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    date_str = datetime.now(timezone.utc).strftime("%A, %d %B %Y")
    user_prompt = build_user_prompt(payload, date_str, db_context=db_context)
    total_articles = sum(len(v) for k, v in payload.items() if isinstance(v, list))
    print(f"\n🤖  Generating digest ({total_articles} articles → Claude)...")

    for attempt in range(2):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}]
            )
            raw_text = response.content[0].text.strip()
            # Strip markdown fences if Claude adds them
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[1]
                if raw_text.endswith("```"):
                    raw_text = raw_text.rsplit("```", 1)[0]
            digest = json.loads(raw_text)

            # Ensure market data from collector is preserved
            if payload.get("market_indicators") and not digest.get("market_indicators"):
                digest["market_indicators"] = payload["market_indicators"]

            print(f"  ✅  Digest generated: {len(digest.get('top_stories') or [])} top stories")
            return digest

        except (anthropic.APIError, anthropic.APIConnectionError) as e:
            if attempt == 0:
                print(f"  ⚠  API error (retrying in 5s): {e}")
                time.sleep(5)
            else:
                print(f"  ✗  API error (giving up): {e}")
                raise
        except json.JSONDecodeError as e:
            if attempt == 0:
                print(f"  ⚠  JSON parse error (retrying): {e}")
                time.sleep(2)
            else:
                print(f"  ✗  JSON parse error: {e}")
                print(f"  Raw response (first 500 chars):\n{raw_text[:500]}")
                raise


if __name__ == "__main__":
    payload = json.loads(Path("collected.json").read_text())
    digest = generate_digest(payload)
    Path("digest.json").write_text(json.dumps(digest, ensure_ascii=False, indent=2))
    print("  → Written to digest.json")
