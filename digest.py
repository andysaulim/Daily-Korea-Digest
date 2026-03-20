"""
Korea Intelligence Digest — Digest Generator
Beyond Parallel × CSIS Korea Chair
Sends collected articles to Claude and returns a structured digest JSON.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import anthropic
# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT  (stays stable across runs — update as corpus grows)
# ─────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are the senior intelligence analyst for Beyond Parallel, the policy website of the CSIS Korea Chair directed by Dr. Victor Cha. You produce the Korea Intelligence Digest — a daily Presidential Daily Brief-style briefing for the Korea Chair team.
Your audience: Victor Cha (PI, Director), and his team of Korea policy researchers. They are senior professionals who need intelligence, not news summaries. They read this every morning before the workday starts. The tone should be authoritative, efficient, and analytically sharp — like the best State Department cables, not like a newsletter.
YOUR JOB: Process all incoming Korea-related content from four source tiers and produce a single structured JSON briefing package. Think like a Korea desk officer writing an internal morning cable — authoritative, precise, forward-looking, and never obvious.
BEYOND PARALLEL CORPUS CONTEXT:
Beyond Parallel tracks: NK–Russia military-technical cooperation and bilateral events; DPRK nuclear and missile program; ROK–US alliance and extended deterrence; inter-Korean relations; DPRK sanctions and economy; satellite imagery analysis of DPRK facilities; Korean Peninsula tension index. Current major research focus: NK–Russia Axis (Cambridge Elements book in progress with Maria Snegovaya, Sydney Seiler, Olena Guisoneva).
KEY MONITORED LOCATIONS: Yongbyon Nuclear Complex, Sohae Satellite Launch Station, Punggye-ri Nuclear Test Site, Sinpo South Shipyard, Sunan Airfield/Missile Complex, Kaesong Industrial Complex zone.
NK–RUSSIA AXIS: Beyond Parallel maintains a verified bilateral event database tracking all NK–Russia cooperation. Flag any NK–Russia stories (weapons transfers, diplomatic visits, economic agreements, military exchanges, technology transfer, labor deployments) for potential timeline addition. These are high priority.
JOURNALIST FLAGGING: The following reporters have special Korea expertise. When their bylines appear, treat the story as higher priority and note the journalist in your analysis:
- Timothy Martin, Dasl Yoon (WSJ Seoul bureau)
- Choe Sang-Hun (NYT Seoul bureau chief)
- Michelle Ye Hee Lee (WaPo Seoul)
- Christian Davies (FT Seoul)
- Hyonhee Shin, Josh Smith, Joyce Lee (Reuters Seoul)
- Ankit Panda (Carnegie — nuclear policy), Jenny Town (Stimson/38North)
- Andrei Lankov (Kookmin — most authoritative DPRK analyst)
- Rachel Minyoung Lee (NK language/rhetoric specialist)
SOURCE TIERS: This digest draws from 100+ sources including Korean-language newspapers (auto-translated), official ROK/US government feeds, Korean think tanks (ASAN, KINU, EAI, KIDA, Sejong, KIEP), European think tanks with Korea programs (IISS, VUB, Chatham House, IFRI, SWP, SIPRI), Chinese and Russian reaction layer sources, and academic journals. Take all of this into account when assessing what the full signal environment looks like today.
ANALYTICAL VOICE:
- Write like a senior policy analyst, not a journalist
- Summaries: precise, forward-looking, never obvious
- "So what" blocks: what decision or question does this affect in the next 30 days?
- Pattern blocks: cite specific historical precedents with dates
- Morning Memo: 3-4 sentences that synthesize the dominant analytical theme — not a list of stories, but an observation about what the collective signal means for Korea policy
- The RE: line should be a crisp one-liner Victor can read on his phone in 5 seconds
Return ONLY valid JSON. No markdown, no preamble, no commentary outside the JSON structure."""
# ─────────────────────────────────────────────────────────────────────────────
# USER PROMPT BUILDER
# ─────────────────────────────────────────────────────────────────────────────
def build_user_prompt(payload: dict, date_str: str) -> str:
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
    return f"""Today's date: {date_str}
Process each tier according to its instructions and return a single JSON object.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TIER 1: NEWS ARTICLES (last 24h)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{tier_json(payload.get("tier1", []))}
For EACH article, return:
- url: (from input)
- source: publication name
- translated_title: English title
- categories: array of: DPRK / ROK Policy / US-Korea / NK-Russia-China / Security / Technology / Business / Energy
- signal_type: ESCALATION / ANOMALY / DEVELOPMENT / CONFIRMATION / CONTEXT
  - ESCALATION: materially worsens threat environment or alliance posture
  - ANOMALY: breaks an established pattern — analytically significant
  - DEVELOPMENT: new information on a known situation
  - CONFIRMATION: validates a tracked trend
  - CONTEXT: background, low urgency
- relevance_score: 1-10 (10 = essential for Korea policy analyst today)
- summary: 2-3 sentences in clear policy-analyst prose. No filler.
- policy_so_what: For score >= 7 only. 2 sentences: what decision or question does this affect in the next 30 days?
- pattern_note: For ESCALATION or ANOMALY only. 1-2 sentences: closest historical precedent and what happened next.
- bp_relevance: If this connects to BP/CSIS research (NK-Russia axis, nuclear program, satellite imagery, alliance dynamics), note the connection in one sentence. Otherwise null.
- timeline_candidate: true if NK-Russia/China category and score >= 7, else false
- is_reaction_source: true if this is Global Times, Xinhua, or TASS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TIER 2: OP-EDS & PRESTIGE COMMENTARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{tier_json(payload.get("tier2", []), max_items=30)}
For EACH piece, return:
- url, source, prestige_tier (A/B/C from input prestige field)
- authors: author name(s) if in summary, else null
- korea_primary: is Korea the PRIMARY subject? true/false
- relevance_score: 1-10
- central_argument: 1 sentence — core claim or recommendation
- summary: 2 sentences — what does the piece argue?
- policy_so_what: 1 sentence — what should a Korea policy professional take from this?
Inclusion rules: Tier A always include if korea_primary=true. Tier B include if score >= 7. Tier C if score >= 9. Never include Korea-as-passing-reference pieces.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TIER 3: ACADEMIC JOURNALS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{tier_json(payload.get("tier3", []), max_items=20)}
For EACH article, return:
- url, source, journal_tier (from input journal_tier field)
- authors: if extractable from summary
- korea_relevance_score: 1-10
- framework: Deterrence / Signaling / Alliance Politics / Nuclear / Sanctions / Domestic Politics / Other
- summary: 3 sentences in plain English — what question, what finding, why it matters for Korea
- policy_implication: 1 sentence — most actionable takeaway for practitioners
- bp_link: connection to BP/CSIS research threads, or null
Inclusion: korea_relevance_score >= 6. For A+ journals, include if score >= 4.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TIER 4: KCNA / RODONG SINMUN (last 24h)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{tier_json(payload.get("tier4", []), max_items=30)}
Return a SINGLE kcna_delta object:
- kim_appearance_today: true/false (did Kim Jong Un appear in KCNA/Rodong today?)
- days_since_last_appearance: estimate from articles, or null
- us_tone: Hostile / Elevated / Neutral / Conciliatory
- rok_tone: Hostile / Elevated / Neutral / Conciliatory
- russia_tone: Hostile / Elevated / Neutral / Warm / Very Warm
- china_tone: Hostile / Elevated / Neutral / Warm / Very Warm
- key_phrase_changes: list of notable new terminology vs. recent baseline. Empty list if none.
- silence_today: true if no KCNA output at all
- delta_note: 1 sentence — what changed and why it might matter
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIGEST SYNTHESIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return a digest object with:
- digest_date: "{date_str}"
- tension_score: 1-10 for today, considering all tiers
- re_line: one-line RE: summary for the cable header (max 120 chars, key themes separated by ·)
- market_indicators: object with kospi (value, change_pct), brent (value, change_pct), usd_krw (value, change_pct). Extract from news articles if mentioned; use approximate values from financial news. If no market data found, use null for the whole object.
- editor_note: 3-4 sentences synthesizing the dominant analytical theme across ALL tiers today. Not a list of stories — an observation about what the collective signal means for Korea policy. Written in Libre Baskerville italic voice (senior analyst, not journalist).
- bp_locations: array of 6 monitored DPRK facility objects. For EACH of these locations, assess status from today's articles: Yongbyon Nuclear Complex, Sohae Satellite Launch Station, Punggye-ri Nuclear Test Site, Sinpo South Shipyard, Sunan Airfield/Missile Complex, Kaesong Industrial Complex. Each object: name, status (normal/activity/elevated/alert), note (1 sentence — what was detected or "No change"). Base status on any satellite imagery reports, military activity mentions, or relevant news. Default to "normal" if no information.
- rok_government: array of ROK government ministry/agency actions from today's news. Include any actions by: Blue House/Presidential Office, Ministry of National Defense, Ministry of Foreign Affairs, Ministry of Unification, National Intelligence Service, Joint Chiefs of Staff, or other ROK agencies. Each: ministry, action (1 line headline), detail (2-3 sentences), url (from source article or null). Include only substantive policy actions, not routine.
- overnight_items: 5-7 highest-priority items for the overnight flash section, each with: url, source, category, headline (crisp, under 100 chars), body_text (2-3 sentences, factual)
- top_stories: 3-4 highest-scored Tier 1 articles (score >= 7) with full treatment: url, source, category_tag, signal_type, headline, body (3-4 sentences), so_what (2 sentences), pattern_note (if applicable), src_line (e.g. "Sources: WaPo Mar 18 · Korea Herald Mar 18")
- also_today: remaining Tier 1 articles score >= 5, each with: url, source, category, headline, body_text (2 sentences), color_bar_class (cb-navy/cb-red/cb-lt/cb-mid/cb-nkch/cb-tech/cb-biz)
- trade_tech_stories: Tier 1 articles categorized as Technology or Business or Energy, score >= 5. Same format as also_today.
- social_statements: 2-4 key official statements or social media posts from the KCNA/news corpus. Each: avatar_initials, who, handle_context, platform_date, quote_text, analyst_note, badge_class (sb-p/sb-r/sb-s)
- opeds_today: qualifying Tier 2 pieces, ordered by prestige_tier then score
- academic_today: qualifying Tier 3 pieces, ordered by journal_tier then korea_relevance_score
- kcna_delta: the Tier 4 object
- timeline_candidates: list of urls flagged as timeline_candidate=true
- story_count: total Tier 1 articles processed
- oped_count: qualifying Tier 2 pieces count
- academic_count: qualifying Tier 3 pieces count
Return ONLY valid JSON. No markdown fences, no preamble."""
# ─────────────────────────────────────────────────────────────────────────────
# MAIN DIGEST FUNCTION
# ─────────────────────────────────────────────────────────────────────────────
def generate_digest(payload: dict) -> dict:
    """Call Claude and return structured digest JSON."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    date_str = datetime.now(timezone.utc).strftime("%A, %d %B %Y")
    user_prompt = build_user_prompt(payload, date_str)
    total_articles = sum(len(v) for v in payload.values())
    print(f"\n🤖  Generating digest ({total_articles} articles → Claude)...")
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=12000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}]
    )
    raw_text = response.content[0].text.strip()
    # Strip markdown fences if Claude adds them despite instructions
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
        if raw_text.endswith("```"):
            raw_text = raw_text.rsplit("```", 1)[0]
    try:
        digest = json.loads(raw_text)
        print(f"  ✅  Digest generated: {len(digest.get('top_stories', []))} top stories, "
              f"tension {digest.get('tension_score', '?')}/10")
        return digest
    except json.JSONDecodeError as e:
        print(f"  ✗  JSON parse error: {e}")
        print(f"  Raw response (first 500 chars):\n{raw_text[:500]}")
        raise
if __name__ == "__main__":
    payload = json.loads(Path("collected.json").read_text())
    digest  = generate_digest(payload)
    Path("digest.json").write_text(json.dumps(digest, ensure_ascii=False, indent=2))
    print("  → Written to digest.json")
