"""
Post-generation verification pass.

A second, adversarial model call that re-reads the digest's most failure-prone
content and removes items it cannot verify as CURRENT (and, for the weekly,
SOURCED). It's the defense against the class of errors that slip past the
generation prompt and the date filters because they require *reading the
content*, not checking metadata:

  - stale think-tank / analysis pieces surfacing as today's commentary
    (an old AEI essay, a 2021 "Current State of THAAD" paper) — a lying feed
    date fools a date filter but not a reader.
  - fabricated weekly composites (a made-up "Lee departs for Washington…"
    itinerary stitched from two unrelated developments) — every ingredient
    looks real; only checking each specific against the sources catches it.

Design principles:
  - FAIL OPEN. Any failure of the verification call (API error, unparseable
    response, missing key) keeps the items exactly as they were. The pass can
    only ever REMOVE clearly-bad items; it must never blank a section that
    passed primary generation.
  - Per-item default is KEEP. An item is dropped only on an explicit
    keep:false verdict, so a truncated/partial response can't nuke content.
  - Cheap. One FAST_MODEL call per run over a small payload.
"""
import json
import os

import anthropic

from digest import FAST_MODEL, _robust_json_parse

try:
    from digest import _record_usage as _digest_record_usage
except Exception:  # pragma: no cover
    _digest_record_usage = None


def _client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("no ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=key)


def _call_json(system: str, user: str, max_tokens: int = 2000) -> dict:
    """Non-streaming JSON call on the fast model. Records usage for the cost
    tracker. Raises on any failure (callers fail open)."""
    client = _client()
    resp = client.messages.create(
        model=FAST_MODEL,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system}],
        messages=[{"role": "user", "content": user}],
    )
    if _digest_record_usage:
        try:
            _digest_record_usage(FAST_MODEL, resp.usage)
        except Exception:
            pass
    text = "".join(getattr(b, "text", "") for b in resp.content
                   if getattr(b, "type", None) == "text")
    return _robust_json_parse(text)


# ── Daily: stale-analysis check on opeds_today + academic_today ──────────────

_ANALYSIS_SYSTEM = (
    "You are the fact-checker for the Korea Daily Brief, a DAILY intelligence "
    "briefing dated __DATE__. Below are analysis / op-ed / academic items chosen "
    "for today's edition. For EACH item decide whether it is a CURRENT piece — "
    "published within roughly the last two weeks and tied to a recent "
    "development — or an OLD / EVERGREEN / RETROSPECTIVE analysis that must NOT "
    "appear in a daily brief.\n"
    "DROP (keep:false) an item that reads as: a general survey or retrospective; "
    "a 'diagnosis' or 'current state of' a controversy that peaked years ago "
    "(e.g. the THAAD–China dispute of 2016–17, the history of inter-Korean "
    "economic cooperation); an anniversary or historical reflection; or anything "
    "you cannot confirm is recent. When in doubt, DROP — omitting a stale item "
    "is always better than shipping it. KEEP (keep:true) items clearly tied to a "
    "current, dated development.\n"
    "Return ONLY JSON: {\"verdicts\":[{\"index\":0,\"keep\":true,\"reason\":\"...\"}]}"
)

_ANALYSIS_SECTIONS = ("opeds_today", "academic_today")


def _item_brief(item: dict) -> str:
    headline = (item.get("headline") or item.get("title")
                or item.get("central_argument") or "").strip()
    source = (item.get("source") or "").strip()
    summary = (item.get("summary") or item.get("body") or "").strip()
    return f"{headline} | source: {source} | {summary}"[:400]


def verify_stale_analysis(digest: dict, date_str: str) -> list:
    """Drop stale/evergreen items from opeds_today + academic_today. Returns a
    log of what was dropped. Fail-open: on any error, nothing is removed."""
    flat = []  # (section, local_index, item)
    for section in _ANALYSIS_SECTIONS:
        for i, item in enumerate(digest.get(section) or []):
            if isinstance(item, dict):
                flat.append((section, i, item))
    if not flat:
        return []

    lines = [f"{gi}. {_item_brief(item)}" for gi, (_, _, item) in enumerate(flat)]
    user = "ITEMS:\n" + "\n".join(lines)
    try:
        data = _call_json(_ANALYSIS_SYSTEM.replace("__DATE__", date_str), user)
        verdicts = {int(v["index"]): v for v in (data.get("verdicts") or [])
                    if "index" in v}
    except Exception as e:
        print(f"  ⚠  Verification pass skipped (analysis, non-fatal): {e}")
        return []

    drop_ids = set()
    log = []
    for gi, (section, _, item) in enumerate(flat):
        v = verdicts.get(gi)
        # default KEEP — only an explicit keep:false drops
        if v is not None and v.get("keep") is False:
            drop_ids.add(gi)
            hl = (item.get("headline") or item.get("title") or "?")[:70]
            log.append(f"  - dropped {section} item {hl!r}: {v.get('reason', 'not current')}")

    if drop_ids:
        survivors = {section: [] for section in _ANALYSIS_SECTIONS}
        for gi, (section, _, item) in enumerate(flat):
            if gi not in drop_ids:
                survivors[section].append(item)
        for section in _ANALYSIS_SECTIONS:
            digest[section] = survivors[section]
    return log


# ── Weekly: claim-tracing check on top_10 against the source digests ─────────

_WEEKLY_SYSTEM = (
    "You are the fact-checker for the Korea Daily Brief Week-in-Review. You are "
    "given (A) the week's daily-digest data (the ONLY allowed sources) and (B) "
    "the top stories written for the weekly. For EACH weekly story decide "
    "whether EVERY specific it asserts — destinations, dates, names, figures, "
    "meetings — is supported by the daily-digest data.\n"
    "DROP (keep:false) a story that: asserts a specific not found in the daily "
    "data; COMBINES two separate developments into one claim (e.g. merging a "
    "Latin-America trip and separate US tariff talks into a single itinerary "
    "'including Washington'); or projects a plan the sources did not state. KEEP "
    "(keep:true) stories whose every specific traces to the daily data.\n"
    "Return ONLY JSON: {\"verdicts\":[{\"index\":0,\"keep\":true,\"reason\":\"...\"}]}"
)


def verify_weekly_stories(weekly: dict, digests_json: str) -> list:
    """Drop unsupported/composite stories from the weekly top_10. Returns a log.
    Fail-open."""
    stories = weekly.get("top_10") or []
    if not stories:
        return []
    lines = []
    for i, s in enumerate(stories):
        if not isinstance(s, dict):
            continue
        hl = (s.get("headline") or "").strip()
        body = (s.get("body") or "").strip()
        lines.append(f"{i}. {hl} — {body}"[:600])
    user = (f"(A) DAILY DIGEST DATA:\n{digests_json[:120000]}\n\n"
            f"(B) WEEKLY TOP STORIES:\n" + "\n".join(lines))
    try:
        data = _call_json(_WEEKLY_SYSTEM, user, max_tokens=2000)
        verdicts = {int(v["index"]): v for v in (data.get("verdicts") or [])
                    if "index" in v}
    except Exception as e:
        print(f"  ⚠  Verification pass skipped (weekly, non-fatal): {e}")
        return []

    kept, log = [], []
    for i, s in enumerate(stories):
        v = verdicts.get(i)
        if v is not None and v.get("keep") is False:
            hl = (s.get("headline") or "?")[:70] if isinstance(s, dict) else "?"
            log.append(f"  - dropped weekly story {hl!r}: {v.get('reason', 'unsupported')}")
        else:
            kept.append(s)
    weekly["top_10"] = kept
    return log
