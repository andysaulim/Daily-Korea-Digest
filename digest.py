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
SYSTEM_PROMPT = """You are the senior intelligence analyst for the CSIS Korea Chair directed by Dr. Victor Cha. You produce the CSIS Korea Digest — a daily Presidential Daily Brief-style briefing for the Korea Chair team.
Your audience: Victor Cha (PI, Director), and his team of Korea policy researchers. They are senior professionals who need intelligence, not news summaries. They read this every morning before the workday starts. The tone should be authoritative, efficient, and analytically sharp — like the best State Department cables, not like a newsletter.
YOUR JOB: Process all incoming Korea-related content from four source tiers and produce a single structured JSON briefing package. Think like a Korea desk officer writing an internal morning cable — authoritative, precise, forward-looking, and never obvious.
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
- Write like a senior policy analyst, not a journalist
- Summaries: precise, forward-looking, never obvious
- "So what" blocks: what decision or question does this affect in the next 30 days?
- Pattern blocks: cite specific historical precedents with dates
- Morning Memo: 2-3 sentences that synthesize the dominant analytical theme — not a list of stories, but an observation about what the collective signal means for Korea policy
- The RE: line should be a crisp one-liner readable on a phone in 5 seconds
BREVITY: Keep the entire digest tight. Summaries: 1-2 sentences max. Body text: 2-3 sentences, not 4. "So what": 1 sentence. Pattern notes: 1 sentence. The reader is time-constrained — every word must earn its place.
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
- senior_officials: array of notable non-Kim appearances/activities (e.g. Choe Son Hui, Kim Yo Jong, Ri Pyong Chol). Each: name, activity (1 sentence). Max 3.
- us_tone, rok_tone, russia_tone, china_tone: each a string (Hostile/Elevated/Neutral/Warm/Very Warm/Silent)
- tone_shift: any tone that changed from yesterday's baseline, e.g. "US tone shifted from Neutral to Hostile". null if no change detected.
- propaganda_focus: top 2-3 topics KCNA is prioritizing today (e.g. "self-reliance economy", "nuclear deterrent", "anti-US imperialism")
- notable_omissions: anything conspicuously absent that was previously regular (e.g. "No mention of Russia for 3rd day", "Kim Yo Jong silent on ROK provocation"). null if nothing notable.
- key_phrase_changes: list of new or notably different phrases/formulations
- silence_today: boolean (complete KCNA blackout)
- delta_note: 1-2 sentences on what changed and why it matters
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIGEST SYNTHESIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return a digest object with:
- digest_date: "{date_str}"
- re_line: one-line RE: summary (max 120 chars, key themes separated by ·)
- market_indicators: pass through the pre-collected market data object exactly as provided above. If no market data was provided, use null.
- editor_note: 2-3 sentences synthesizing the dominant analytical theme across ALL tiers. Not a list of stories — an observation about what the collective signal means for Korea policy. Senior analyst voice.
- watch_today: array of 2-3 items for "What to Watch Today" — upcoming events, scheduled meetings, votes, exercise dates, anniversaries of past provocations, or deadlines relevant to Korea policy in the next 48 hours. Each: headline (short), detail (1-2 sentences), type (event/deadline/anniversary/exercise).
- on_this_day: 1-2 historical Korea events that happened on today's date or within the next 7 days. Each: date (e.g. "March 26, 2010"), event (1 sentence), relevance (1 sentence connecting to current situation). Draw from major events: Cheonan sinking, nuclear tests, inter-Korean summits, armistice, provocations, key policy moments. If nothing notable, return empty array.
- key_stat: a single striking statistic or number pulled directly from TODAY's articles — not from databases or historical data. Must come from a story in the current digest. Object with: number (the stat, e.g. "$2.3B", "53%", "12"), label (what it measures, under 60 chars), context (1 sentence explaining why it matters today), source (which article it came from). Pick the most policy-relevant number from today's news — trade figures, military spending, sanctions data, economic indicators, deployment numbers, etc.
- bp_locations: array of 10 monitored location status objects. Each: name, status (normal/activity/elevated/alert), note (1 sentence). Locations: Yongbyon Nuclear Complex, Sohae Satellite Launch Station, Punggye-ri Nuclear Test Site, Sinpo South Shipyard, Sunan Airfield/Missile Complex, Tumangang–Khasan (NK-Russia border crossing — track train movements, cargo activity, troop/labor transfers), Sinuiju–Dandong (NK-China border crossing — track trade volume signals, bridge activity, diplomatic traffic), Yellow Sea NLL/PMZ (Northern Limit Line — track naval activity, fishing boat incursions, military posture), Vostochny/Dunai (Russian Far East — NK labor deployments, military cargo staging, ship transfers), Rason SEZ (DPRK special economic zone — port operations at Rajin, trade activity, foreign presence).
- rok_government: array of ROK ministry/agency actions from today's news (Presidential Office, MOFA, MND, MOU, MOTIE, NIS, FSC, MOJ — see system prompt for full list). Each: ministry, action (1-line headline), detail (1-2 sentences), url or null. Include only substantive policy actions — meetings, statements, personnel changes, policy announcements. This section is critical for tracking ROK government posture.
- rok_assembly: array of ROK National Assembly activity from today's news — committee hearings, bills, votes related to defense/foreign affairs/unification/intelligence. Each: committee, action (1 line), detail (1-2 sentences), url or null. Empty array if no relevant activity.
- overnight_items: 5-7 highest-priority items. Each: url, source, category, headline (under 100 chars), body_text (1-2 sentences)
- top_stories: 3-4 highest-scored articles (score >= 7) with full treatment: url, source, category_tag, signal_type, headline, body (2-3 sentences), so_what (1 sentence), pattern_note (1 sentence, if applicable), src_line
- also_today: remaining articles score >= 5, INCLUDING Technology/Business/Energy stories. Each: url, source, category, headline, body_text (1 sentence), color_bar_class (cb-navy=DPRK, cb-red=Security, cb-lt=Policy, cb-mid=Assembly, cb-nkch=NK-Russia-China, cb-tech=Technology/Energy, cb-biz=Business)
- social_statements: 2-4 notable statements from TODAY's news by government officials, senior policymakers, or military leaders. Prioritize: ROK President, ROK opposition leader (e.g. Lee Jae Myung), ROK FM/DM, US SecState/SecDef/NSA, USFK Commander, UN officials, Japan PM/FM, DPRK officials (via KCNA). Pull direct quotes from today's articles. Each: avatar_initials (2 letters), who (name), handle_context (title/role), platform_date (source · date), quote_text (the direct quote), analyst_note (1 sentence on significance), badge_class (sb-p=policy, sb-r=security/red, sb-s=specialist/purple)
- opeds_today: qualifying Tier 2 pieces, ordered by prestige then score
- academic_today: qualifying Tier 3 pieces, ordered by journal_tier then score
- kcna_delta: the Tier 4 object
- timeline_candidates: list of urls flagged as timeline_candidate=true
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
