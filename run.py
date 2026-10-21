"""
Korea Daily Brief — Main Runner
CSIS Korea Chair
Orchestrates: collect → databases → digest → validate → render → push → send
Usage:
  python run.py              # Full pipeline (collect + digest + render + send)
  python run.py --no-send    # Render to file only, no email
  python run.py --from-cache # Skip collection, use existing collected.json
  python run.py --no-push    # Skip pushing new entries to databases
"""
import copy
import json
import argparse
import os
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from digest import _count_digest_words, MIN_DIGEST_WORDS


# An eight-minute read. An issue once shipped at 3,518 words because the
# section maximums permitted 3,680 between them and nothing capped the total.
# Raised from 2,400 at the Korea Chair's direction (Sep 2026). The brief had
# run 3,062-3,518 for four days: the trimmer could not reach 2,400 without
# cutting into the day's substance, because its per-section floors plus the
# sections it may never touch already come to roughly that. Rather than keep
# losing reporting to an arbitrary number, the band moved to where the brief
# actually sits when it is good. Quality first; the ceiling is the backstop.
# 2,750 -> 2,800 (Oct 2026), with the user's approval, when Capitol Hill and
# Korea and the World were added: at most seven items between them, and most
# days fewer, since both are allowed to be empty.
# 2,800 -> 3,300 (Oct 2026). This counts RENDERED words, and the page adds
# about 1,000 words of labels, tables and standing panels to what the model
# writes (rendered ~ 1,000 + 1.17 x digest words across 12-18 October). The
# prompt asked for 2,500-2,750 words of its own text, which renders near
# 4,000, so the trimmer threw away a third of every draft. The prompt now
# asks for 1,700-2,000 words, which renders at about this ceiling. The owner
# is content with a longer brief; what binds is Gmail clipping at 102 KB,
# which EMAIL_BYTE_BUDGET and fit_email_bytes enforce after rendering.
WORD_CEILING = 3300

# The layout trialled against real issues by send_design_preview.
PREVIEW_DESIGN = "v2"


def _count_rendered_words_of(html: str) -> int:
    """The reader's word count: what render() stamps into the masthead.

    Imported lazily so run.py keeps working if render is mid-edit.
    """
    from render import _count_rendered_words
    return _count_rendered_words(html.split("<body", 1)[-1])



# Gmail stops rendering a message body past roughly 102 KB and shows
# "[Message clipped]" with a link. The brief is long by design, so this is a
# live risk rather than a theoretical one: a clipped brief hides everything
# below the fold, and the reader has no way to tell what is missing.
GMAIL_CLIP_BYTES = 102_400
EMAIL_BYTES_WARN = 78_000
EMAIL_BYTES_CRITICAL = 96_000
# The size the rendered, minified brief is trimmed to. 4 KB under the clip
# leaves room for the Listen bar added after the audio is built, and for
# Gmail's own wrapping.
EMAIL_BYTE_BUDGET = 98_000


def fit_email_bytes(digest: dict, render_fn, budget: int = EMAIL_BYTE_BUDGET,
                    max_steps: int = 60) -> tuple[str, list[str]]:
    """Render, and drop items until the minified email is under budget.

    The word ceiling is a proxy; bytes are what Gmail clips on, and a day
    heavy in Korean text (three bytes a character) or long URLs can pass the
    first and fail the second. Items go one at a time in length_budget's
    TRIM_ORDER, never below its floors, so this can only remove what the word
    trim would have removed next. Returns (html, log lines); the html is the
    last render, which is still over budget only when nothing more may go.
    """
    import length_budget
    log: list[str] = []
    html = minify_email_html(render_fn(digest))
    size = len(html.encode("utf-8"))
    start = size
    for _ in range(max_steps):
        if size <= budget:
            break
        step = length_budget.trim_one(digest)
        if step is None:
            log.append(f"still {size:,} bytes, over the {budget:,} budget, with every "
                       f"trimmable section at its floor")
            break
        log.append(f"    {step}")
        html = minify_email_html(render_fn(digest))
        size = len(html.encode("utf-8"))
    if size != start:
        log.insert(0, f"over the email size budget: {start:,} bytes, trimmed to {size:,} "
                      f"(budget {budget:,})")
    return html, log


_COND_OPEN = re.compile(r"<!--\[if\b", re.I)
_STYLE_BLOCK = re.compile(r"(<style[^>]*>)(.*?)(</style>)", re.I | re.S)
_PRE_BLOCK = re.compile(r"<(pre|textarea)\b", re.I)


def _minify_css(css: str) -> str:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)          # CSS comments
    css = re.sub(r"\s*\n\s*", " ", css)                      # line breaks
    css = re.sub(r"\s{2,}", " ", css)
    css = re.sub(r"\s*([{};:,>])\s*", r"\1", css)            # around punctuation
    css = re.sub(r";}", "}", css)
    return css.strip()


def minify_email_html(html: str) -> str:
    """Shrink the rendered brief without changing what it renders.

    Gmail clips a message body over 102,400 bytes and shows "View entire
    message" in place of the rest, so an issue that runs long is silently
    truncated mid-item for a large share of its readers. Roughly a fifth of
    this brief's bytes are indentation, line breaks and authoring comments —
    all of which cost delivery and buy nothing.

    The transform is chosen to be provably neutral rather than merely
    cautious. Outside <style> and <pre>, any run of whitespace containing a
    newline already renders as exactly one space, so collapsing it to one
    space cannot change layout or inline spacing. That is what makes this
    safe to run on a brief nobody proofreads before it goes out.

    Preserved deliberately:
      - conditional comments (<!--[if mso]> … <![endif]-->), which Outlook
        needs and which are not decoration;
      - <pre> and <textarea>, where whitespace is significant. If either ever
        appears the document is returned untouched rather than half-handled.
    """
    if _PRE_BLOCK.search(html):
        return html

    # Comments go FIRST, and the order is load-bearing. Several authoring
    # comments in this renderer discuss "<style>" in prose. Matching style
    # blocks before removing them let the block regex start at a mention
    # inside a comment and run to the next real </style>, swallowing the
    # comment tail and a genuine stylesheet into one stashed chunk. Removing
    # comments first means the block regex can only ever see real markup.
    def _drop_comment(m: re.Match) -> str:
        body = m.group(0)
        return body if _COND_OPEN.search(body) or "endif" in body.lower() else ""

    html = re.sub(r"<!--.*?-->", _drop_comment, html, flags=re.S)

    styles: list[str] = []

    def _stash(m: re.Match) -> str:
        styles.append(m.group(1) + _minify_css(m.group(2)) + m.group(3))
        return f"\x00STYLE{len(styles) - 1}\x00"

    html = _STYLE_BLOCK.sub(_stash, html)

    # The whole saving, and the only risky-looking step: a whitespace run with
    # a newline in it already collapses to one space when rendered, so this
    # replaces it with the one space it was always going to be.
    html = re.sub(r"[ \t]*\n[ \t\n]*", " ", html)
    html = re.sub(r"[ \t]{2,}", " ", html)

    for i, block in enumerate(styles):
        html = html.replace(f"\x00STYLE{i}\x00", block)
    return html.strip()


def check_email_size(html: str) -> list[str]:
    """Warn before Gmail would clip the body.

    This reports; it does not block. A brief that is slightly too long is
    still worth sending, and cancelling one over its byte count would cost
    the issue to save the tail of it.

    Measures encoded bytes rather than string length: Korean, Japanese and
    Chinese text costs three bytes a character, so a character count would
    understate a brief in exactly the editions most likely to be long.
    """
    n = len(html.encode("utf-8"))
    pct = 100 * n / GMAIL_CLIP_BYTES
    if n >= GMAIL_CLIP_BYTES:
        return [f"CRITICAL EMAIL SIZE: {n:,} bytes ({pct:.0f}% of Gmail's "
                f"{GMAIL_CLIP_BYTES:,}-byte clipping limit); the brief WILL be "
                f"truncated mid-item for Gmail readers."]
    if n >= EMAIL_BYTES_CRITICAL:
        # Between the alarm threshold and the real one. Saying "would be
        # truncated" here was simply untrue, and a warning that overstates
        # stops being read.
        return [f"EMAIL SIZE: {n:,} bytes ({pct:.0f}% of Gmail's "
                f"{GMAIL_CLIP_BYTES:,}-byte clipping limit) — under it, but "
                f"with little room left."]
    if n >= EMAIL_BYTES_WARN:
        return [f"EMAIL SIZE: {n:,} bytes ({pct:.0f}% of Gmail's clipping limit)"]
    return []

def _published_from_branch(name: str) -> tuple[str | None, bool]:
    """Read a published file from the gh-pages branch; see shared.published.

    The archive reads the branch rather than the live site, because Pages was
    switched off on 3 October and every HTTP fetch 404'd: five issues went out
    numbered "No. 1" over an archive listing one issue.
    """
    from shared.published import read_from_branch
    return read_from_branch(name)


def load_archive_entries(local_path, web_base: str = "") -> tuple[list, bool]:
    """The published archive manifest, and whether it is trustworthy.

    `public/` is gitignored and the Actions runner starts clean, so
    archive.json does not exist locally at the start of a run. The old code
    read it, caught FileNotFoundError, started from an empty list, appended
    today and wrote a one-entry file. The Pages deploy uses keep_files, which
    preserves the accumulated digest_*.html pages but still overwrites any
    file being published — so every run replaced a growing manifest with a
    stub, and the archive page listed exactly one issue no matter how many had
    been sent. The issue number was computed from the same list, so it never
    advanced either.

    Local first, since a manual run may have one. Otherwise fetch the
    published copy. The boolean is what protects the manifest: if neither is
    available, the caller must not write, because writing would clobber a
    history it could not read.
    """
    try:
        entries = json.loads(local_path.read_text(encoding="utf-8"))
        if isinstance(entries, list) and entries:
            return entries, True
    except (OSError, json.JSONDecodeError):
        pass

    text, reachable = _published_from_branch("archive.json")
    if text is not None:
        try:
            entries = json.loads(text)
            if isinstance(entries, list):
                print(f"  📚  Archive: {len(entries)} prior issues read from the "
                      f"gh-pages branch")
                return entries, True
        except json.JSONDecodeError:
            pass
    elif reachable:
        print("  📚  Archive: no manifest on gh-pages yet — starting one")
        return [], True

    base = (web_base or os.environ.get("WEB_URL", "")).rstrip("/")
    if not base:
        return [], False
    try:
        import requests
        resp = requests.get(f"{base}/archive.json", timeout=15)
        if resp.ok:
            entries = resp.json()
            if isinstance(entries, list):
                print(f"  📚  Archive: {len(entries)} prior issues fetched from the "
                      f"published site")
                return entries, True
        print(f"  ⚠  Archive manifest fetch returned {resp.status_code}; "
              f"leaving the published archive untouched this run")
    except Exception as exc:
        print(f"  ⚠  Archive manifest unreachable ({exc}); leaving the published "
              f"archive untouched this run")
    return [], False


def backfill_archive_entries(entries: list, web_base: str = "") -> list:
    """Recover issues the destroyed manifest lost, from the pages themselves.

    Every brief ever sent is still published at its own dated URL — the Pages
    deploy keeps files it is not publishing. What the old rebuild-from-empty
    bug destroyed was only the index. So a manifest that has come back with a
    couple of entries is not evidence that a couple of issues were sent; it is
    evidence of the last stub written before the bug was fixed, and the issue
    number computed from it says No. 1 forever.

    This asks the site which dated pages exist and merges the answers in. It
    runs only while the manifest is still short, so it costs a few hundred HEAD
    requests once and nothing afterwards. A page that does not answer is simply
    not added: an unreachable site is not evidence that an issue is gone, and
    nothing here removes an entry.
    """
    if len(entries) >= _BACKFILL_BELOW:
        return entries
    base = (web_base or os.environ.get("WEB_URL", "")).rstrip("/")
    if not base:
        return entries
    try:
        from datetime import date, timedelta
        import rebuild_archive
        today = datetime.now(ZoneInfo("America/New_York")).date()
        found = rebuild_archive.probe(base, today - timedelta(days=_BACKFILL_DAYS), today)
        merged = rebuild_archive.merge(entries, found, base)
    except Exception as exc:
        print(f"  ⚠  Archive backfill skipped ({exc})")
        return entries
    if len(merged) > len(entries):
        print(f"  📚  Archive backfill: {len(entries)} -> {len(merged)} issues "
              f"recovered from pages still published")
    return merged


def warn(title: str, message) -> None:
    """A GitHub Actions warning annotation, shown on the run page.

    Most of the pipeline's best-effort steps used to report a failure as an
    ordinary log line ("skipped (non-fatal)") and carry on, which is right for
    the send and wrong for the operator: the run went green, the brief went
    out degraded, and nothing on the run page said so. Anything that changes
    what the reader gets goes through here. Newlines are escaped so a
    multi-line exception stays one annotation; title punctuation is escaped
    because ':' and ',' end the title.
    """
    def _esc(v) -> str:
        return str(v).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    t = _esc(title).replace(":", "%3A").replace(",", "%2C")
    print(f"::warning title={t}::{_esc(message)}", flush=True)


def build_web_html(digest: dict, email_html: str, date_slug: str,
                   archive_entries: list | None = None) -> str:
    """The published page for digest_{date}.html and latest.html. Never raises.

    The web edition (web_page.py) is the full reference: every item whole,
    sections that fold, a section menu, prev/next. The email stays as it is.
    If the web edition cannot be built, the page is the email HTML, as it
    was before, and the run page says so. archive_entries is None when the
    manifest could not be read; the page then leaves prev/next to its own
    fetch of the published archive.json.
    """
    try:
        import web_page
        page = web_page.build(digest, email_html, date_slug, archive_entries=archive_entries)
        if not isinstance(page, str) or "</html>" not in page:
            raise ValueError("web_page.build returned no page")
        return page
    except Exception as e:                                      # noqa: BLE001
        warn("Web page fell back to the email",
             f"digest_{date_slug}.html is the email HTML today: {type(e).__name__}: {e}")
        return email_html


# The brand files the brief loads from the site: the CSIS wordmark (the
# masthead), the Korea Chair lockup (the footer) and Synthèse (web page and Apple Mail). The email
# names them by absolute URL, WEB_URL + "/assets/...".
BRAND_ASSETS = ("korea_chair_lockup_white.png", "csis_wordmark_white.png",
                "synthese-400.woff2", "synthese-700.woff2")


def publish_assets(public_dir: Path, src_dir: Path = Path("assets")) -> list[str]:
    """Copy the checked-in brand assets to public/assets/ for the Pages deploy. Never raises.

    A static copy of files in the repository, overwritten whole each run:
    nothing here accumulates across runs, so the archive rule (read the
    published index first, never write a stub) does not apply. Returns the
    names copied; a missing source is reported on the run page, since the
    email's logo would then show its alt text.
    """
    import shutil
    done = []
    try:
        out = Path(public_dir) / "assets"
        out.mkdir(parents=True, exist_ok=True)
        for name in BRAND_ASSETS:
            src = Path(src_dir) / name
            if src.is_file():
                shutil.copyfile(src, out / name)
                done.append(name)
        missing = [n for n in BRAND_ASSETS if n not in done]
        if missing:
            warn("Brand assets missing", f"not published: {', '.join(missing)}")
    except Exception as e:                                      # noqa: BLE001
        warn("Brand assets not published", str(e))
    return done


def gallup_baseline_age_days(today=None) -> int | None:
    """Days since the stored Gallup baseline's survey began, or None.

    When the day's scrape finds no poll, collect() falls back to this baseline
    and the brief shows it, correctly labelled with its own survey dates. That
    is fine for a week. Past two the brief is carrying a stale poll and the
    weekly update has stopped working, which only a person can fix.
    """
    try:
        import gallup_update as gu
        key = gu._current_sort_key(gu._load_baseline())
        if not key:
            return None
        today = today or datetime.now(ZoneInfo("America/New_York")).date()
        return (today - datetime.strptime(key, "%Y-%m-%d").date()).days
    except Exception:                                           # noqa: BLE001
        return None


# How short a manifest has to be before it is treated as the stub the old bug
# left behind, and how far back to look for pages it lost.
_BACKFILL_BELOW = 5
_BACKFILL_DAYS = 400


# Per-section (minimum, maximum) item counts. These, not the prompt's target,
# are what actually bounds the length of the brief.
SECTION_CAPS = {
    "top_stories":       (2, 4),
    # Minimum 3, not 6. A minimum is the one condition that still forces a full
    # regeneration, so it has to mean "not worth sending", not "fewer than I
    # would like". Raised to 6 yesterday; a run that came back with fewer
    # tripped it, threw away a usable brief and started over. The prompt still
    # asks for 6-8, which is where a preference belongs.
    "overnight_items":   (3, 8),
    "business_economy":  (0, 6),
    # No minimum: the prompt no longer forces four events, because the
    # verified-date list had been overtaken by time and a hard floor
    # against an empty list is what produces invented dates.
    # Six: the prompt aims for four to six dated events in the next 14 days.
    "calendar_watch":    (0, 6),
    "also_today":        (0, 6),
    "northeast_asia":    (0, 5),
    # Both may be empty, and on most days should be: they carry only what the
    # Hill and world feeds actually collected.
    "capitol_hill":      (0, 4),
    "korea_world":       (0, 3),
    "social_statements": (0, 3),
    "rok_government":    (0, 6),
    "rok_assembly":      (0, 3),
    # The Analysis section: the best 3-5 pieces across the two, never more
    # than ANALYSIS_MAX together (validate_digest trims the op-ed tail first,
    # since the prompt orders reports ahead of op-eds).
    "opeds_today":       (0, 4),
    "academic_today":    (0, 2),
    "rok_personnel":     (0, 3),
    "morning_memo":      (3, 3),
    "on_this_day":       (0, 1),
}



_STOP_WORDS = frozenset({"the", "a", "an", "in", "on", "of", "to", "for", "and", "is", "at", "by", "as", "with", "from",
                         "its", "new", "over", "after", "says", "said", "amid", "that", "has", "will", "may", "could",
                         "been", "are", "was", "were", "this", "but", "not", "all", "more", "than", "also"})

# Topic entities — entity match alone triggers dedup (institution/person/event)
_TOPIC_ENTITIES = {
    "bok": {"bok", "bank of korea", "central bank", "monetary policy", "rate decision", "interest rate", "base rate", "benchmark rate"},
    "kim jong un": {"kim jong un", "kim jongun", "kju", "north korean leader", "dprk leader", "supreme leader"},
    "yoon": {"yoon", "yoon suk yeol", "yoon suk-yeol", "president yoon"},
    "lee jae myung": {"lee jae myung", "lee jae-myung", "lee jaemyung"},
    "usfk": {"usfk", "us forces korea", "united states forces korea"},
    "freedom shield": {"freedom shield", "joint military exercise", "joint drill", "combined exercise"},
}

# Company entities — need keyword overlap too (big conglomerates have many unrelated stories)
_COMPANY_ENTITIES = {
    "samsung": {"samsung", "samsung electronics"},
    "hyundai": {"hyundai", "hyundai motor", "hyundai motors"},
    "sk": {"sk hynix", "sk group", "sk innovation", "sk telecom"},
    "posco": {"posco"},
    "hanwha": {"hanwha"},
    "lg": {"lg energy", "lg electronics", "lg chem"},
}

# All sections that contain items with URLs/headlines
_ALL_ITEM_SECTIONS = ("top_stories", "overnight_items", "also_today",
                       "business_economy", "opeds_today", "academic_today",
                       "social_statements", "northeast_asia",
                       "capitol_hill", "korea_world")

# Sections where duplicates get auto-stripped (priority order — first wins).
# One story ran in up to six places in a single issue: a top story, its
# ministry card, the personnel note, a quote, a KCNA line and the imagery box.
# Everything a reader sees as an item is now in the walk. Dotted names are
# nested lists; imagery_report and discourse_flag are single values.
_DEDUP_SECTIONS = ("top_stories", "overnight_items", "business_economy",
                    "northeast_asia", "capitol_hill", "korea_world",
                    "also_today", "opeds_today", "academic_today",
                    "rok_government", "rok_assembly", "rok_personnel",
                    "social_statements", "official_x_posts",
                    "kcna_delta.top_articles", "imagery_report",
                    "public_sentiment.discourse_flag")


def _dedup_get(digest: dict, path: str) -> list:
    """The items at a _DEDUP_SECTIONS path, as a list of dicts."""
    if path == "imagery_report":
        v = digest.get("imagery_report")
        return [v] if isinstance(v, dict) else []
    if "." in path:
        parent, child = path.split(".", 1)
        v = (digest.get(parent) or {}).get(child) if isinstance(digest.get(parent), dict) else None
        if child == "discourse_flag":
            return [{"headline": v}] if isinstance(v, str) and v.strip() else []
        return v if isinstance(v, list) else []
    v = digest.get(path)
    return v if isinstance(v, list) else []


def _dedup_set(digest: dict, path: str, kept: list) -> None:
    if path == "imagery_report":
        if not kept:
            digest["imagery_report"] = None
        return
    if "." in path:
        parent, child = path.split(".", 1)
        if not isinstance(digest.get(parent), dict):
            return
        if child == "discourse_flag":
            if not kept:
                digest[parent][child] = None
            return
        digest[parent][child] = kept
        return
    digest[path] = kept


def _dedup_text(item: dict) -> str:
    """What an item is about, for sections that have no headline field."""
    if item.get("headline"):
        return str(item["headline"])
    if item.get("action"):                       # rok_government, rok_assembly
        return str(item["action"])
    if item.get("name") or item.get("position"):  # rok_personnel
        return f'{item.get("name", "")} {item.get("position", "")}'
    if item.get("quote_text"):                   # statements and X posts
        return f'{item.get("who", "")} ' + " ".join(str(item["quote_text"]).split()[:20])
    return str(item.get("translated_title") or "")


def _extract_entities(text: str) -> tuple[set[str], set[str]]:
    """Extract topic and company entity tags from a headline.
    Returns (topic_entities, company_entities)."""
    text_lower = text.lower()
    topics = set()
    companies = set()
    for tag, aliases in _TOPIC_ENTITIES.items():
        if any(alias in text_lower for alias in aliases):
            topics.add(tag)
    for tag, aliases in _COMPANY_ENTITIES.items():
        if any(alias in text_lower for alias in aliases):
            companies.add(tag)
    return topics, companies


def _headline_key(item: dict) -> tuple[str, set, set, set]:
    """Return (headline, keywords, topic_entities, company_entities) for an item."""
    headline = (_dedup_text(item) or "").lower().strip()
    words = {w for w in re.split(r'\W+', headline) if len(w) > 2 and w not in _STOP_WORDS}
    topics, companies = _extract_entities(headline)
    return headline, words, topics, companies


def _is_dup(words_a, topics_a, companies_a, words_b, topics_b, companies_b,
            same_section: bool = False) -> str | None:
    """Check if two items are duplicates. Returns reason string or None.

    same_section relaxes the thresholds: two items on the same topic within
    ONE section are almost always true dupes (the prompt mandates topic
    diversity per section), whereas cross-section matches need more evidence
    because sections legitimately revisit the same actors from new angles.
    """
    if not words_a or not words_b:
        return None
    # Keyword overlap
    overlap = words_a & words_b
    min_len = min(len(words_a), len(words_b))
    ratio_floor = 0.4 if same_section else 0.5
    keyword_dup = min_len > 1 and len(overlap) >= 2 and len(overlap) / min_len >= ratio_floor
    if keyword_dup:
        return "keyword overlap"
    # Topic entity match — require keyword overlap too (just like companies).
    # On heavy news days a single figure (e.g. KJU) dominates many *distinct*
    # stories; entity-only matching was wiping them all out. Within one
    # section a single extra shared word is enough (e.g. two "Kim Jong Un
    # murals" items in The Wire).
    shared_topics = topics_a & topics_b
    if shared_topics:
        # Strip entity alias words from overlap to avoid self-matching
        entity_words = set()
        for tag in shared_topics:
            for alias in _TOPIC_ENTITIES.get(tag, set()):
                entity_words.update(w for w in alias.split() if len(w) > 2)
        non_entity_overlap = overlap - entity_words
        needed = 1 if same_section else 2
        if len(non_entity_overlap) >= needed:
            return f"shared topic + keywords: {shared_topics}, {non_entity_overlap}"
    # Company entity match — need 2+ non-entity keyword overlaps
    # (company names alone aren't enough — Samsung has many unrelated stories)
    shared_companies = companies_a & companies_b
    if shared_companies:
        # Strip out company name words from overlap to avoid self-matching
        company_words = set()
        for tag in shared_companies:
            for alias in _COMPANY_ENTITIES.get(tag, set()):
                company_words.update(w for w in alias.split() if len(w) > 2)
        non_entity_overlap = overlap - company_words
        if len(non_entity_overlap) >= 2:
            return f"shared company + keywords: {shared_companies}, {non_entity_overlap}"
    return None


def _dedup_digest(digest: dict) -> tuple[dict, list[str]]:
    """Auto-strip duplicate topics from digest. Returns (cleaned_digest, log_messages).

    Walks sections in priority order. For each item, checks against all items
    already seen. If duplicate, removes it from the lower-priority section.
    Respects section minimums — won't strip a section below its floor.
    """
    _SECTION_FLOORS = {"top_stories": 3, "overnight_items": 3}
    log = []
    seen = []  # (section, headline, words, topics, companies)
    seen_urls_global = {}  # url -> section_key (track across ALL sections)

    for section_key in _DEDUP_SECTIONS:
        items = _dedup_get(digest, section_key)
        if not items:
            continue

        floor = _SECTION_FLOORS.get(section_key, 0)
        kept = []
        deferred_removals = []  # (index, log_msg) — removals that may be restored

        for item in items:
            url = (item.get("url") or "").strip()

            # URL dedup — across all sections
            if url and url.startswith("http"):
                if url in seen_urls_global:
                    msg = f"  Removed duplicate URL in {section_key} (already in {seen_urls_global[url]}): {url[:80]}"
                    deferred_removals.append((item, msg))
                    continue
                seen_urls_global[url] = section_key

            headline, words, topics, companies = _headline_key(item)
            if len(headline) < 15:
                kept.append(item)
                continue

            is_duplicate = False
            for prev_section, prev_headline, prev_words, prev_topics, prev_companies in seen:
                # The one sanctioned twin: an imagery report and the news
                # story that reports the same imagery (see the prompt).
                if section_key == "imagery_report" and prev_section in ("top_stories", "overnight_items"):
                    continue
                reason = _is_dup(words, topics, companies, prev_words, prev_topics, prev_companies,
                                 same_section=(prev_section == section_key))
                if reason:
                    msg = (
                        f"  Removed from {section_key} ({reason}): "
                        f"'{headline[:60]}' — kept in {prev_section}: '{prev_headline[:60]}'")
                    deferred_removals.append((item, msg))
                    is_duplicate = True
                    break

            if not is_duplicate:
                kept.append(item)
                seen.append((section_key, headline, words, topics, companies))

        # Restore items if removals would breach section floor
        if len(kept) < floor and deferred_removals:
            need = floor - len(kept)
            restored = deferred_removals[:need]
            deferred_removals = deferred_removals[need:]
            for item, _msg in restored:
                kept.append(item)
                headline, words, topics, companies = _headline_key(item)
                seen.append((section_key, headline, words, topics, companies))
                url = (item.get("url") or "").strip()
                if url and url.startswith("http"):
                    seen_urls_global[url] = section_key

        for _item, msg in deferred_removals:
            log.append(msg)

        _dedup_set(digest, section_key, kept)

    return digest, log


_US_KEYWORDS = frozenset({
    "us", "u.s.", "united states", "america", "american", "washington",
    "ustr", "commerce department", "white house", "pentagon", "congress",
    "treasury", "biden", "trump", "section 232", "section 301", "section 122",
    "ieepa", "cfius", "ita", "itc",
    # US states that recur as the site of Korean investment.
    "georgia", "texas", "alabama", "tennessee", "arizona", "louisiana", "philadelphia", "philly",
})
_US_KEYWORD_RE = re.compile(
    r"(?<![a-z0-9])(?:" + "|".join(re.escape(k) for k in sorted(_US_KEYWORDS, key=len, reverse=True))
    + r")(?![a-z0-9])")


def _filter_non_us_deals(digest: dict) -> list[str]:
    """Remove deals from us_korea_deals.deals that don't involve the US.

    Returns log messages for any removed items.
    """
    log = []
    us_korea = digest.get("us_korea_deals")
    if not us_korea or not isinstance(us_korea, dict):
        return log

    deals = us_korea.get("deals")
    if not deals or not isinstance(deals, list):
        return log

    kept = []
    for deal in deals:
        # The headline and the parties only. A Hyundai India deal passed
        # because its note said "us-korea" (it was explaining why the deal
        # did not belong), and the old substring match also found "us" in
        # "business" and "industry". Whole words, on the fields that say
        # who the deal is between.
        parties = deal.get("parties", "")
        if isinstance(parties, list):
            parties = " ".join(str(p) for p in parties)
        text = f'{deal.get("headline", "")} {parties}'.lower()
        has_us = bool(_US_KEYWORD_RE.search(text))
        if has_us:
            kept.append(deal)
        else:
            headline = deal.get("headline", "")[:80]
            log.append(f"  Removed non-US deal from us_korea_deals: '{headline}'")

    us_korea["deals"] = kept
    return log


# Max times a single source can appear in overnight_items / also_today.
# Yonhap (연합뉴스) is Korea's dominant wire service — like AP for the US.
# Cap of 2 was too aggressive, removing 5-7 items per run and crashing word count.
_SOURCE_CAP = 3

_SOURCE_PREFIX_MAP = {
    "yonhap": "yonhap", "연합뉴스": "yonhap",
    "reuters": "reuters",
    "nikkei": "nikkei",
    "kyodo": "kyodo",
    "associated press": "ap", "ap news": "ap",
    "agence france": "afp", "afp": "afp",
    "korea herald": "korea herald",
    "korea times": "korea times",
    "joongang": "joongang", "중앙일보": "joongang",
    "chosun": "chosun", "조선일보": "chosun",
    "hankyoreh": "hankyoreh", "한겨레": "hankyoreh",
    "dong-a": "dong-a", "동아일보": "dong-a",
    "maeil": "maeil", "매일경제": "maeil",
    "hankook": "hankook", "한국경제": "hankook",
    "jtbc": "jtbc", "kbs": "kbs", "mbc": "mbc", "sbs": "sbs", "ytn": "ytn",
    "nk news": "nk news", "nk pro": "nk news",
    "daily nk": "daily nk",
    "scmp": "scmp", "south china morning": "scmp",
    "global times": "global times",
    "tass": "tass", "xinhua": "xinhua",
    "japan times": "japan times",
}

def _normalize_source(src: str) -> str:
    """Collapse source name variants to a canonical key."""
    s = src.lower().strip()
    for prefix, canonical in _SOURCE_PREFIX_MAP.items():
        if s.startswith(prefix):
            return canonical
    return s

def _enforce_source_diversity(digest: dict) -> list[str]:
    """Cap any single source to _SOURCE_CAP appearances per section.

    Skips top_stories (curated 3-4 item section where story importance
    outweighs source diversity). Excess items from over-represented sources
    are dropped, but the section is never reduced below its floor.
    Returns log messages for removed items.
    """
    _SECTION_MINIMUMS = {"overnight_items": 3}
    log = []
    for section_key in ("overnight_items", "also_today"):
        items = digest.get(section_key)
        if not items or not isinstance(items, list):
            continue

        floor = _SECTION_MINIMUMS.get(section_key, 0)

        source_counts: dict[str, int] = {}
        kept = []
        dropped = []
        for item in items:
            src = _normalize_source(item.get("source", "Unknown"))
            source_counts[src] = source_counts.get(src, 0) + 1
            if source_counts[src] <= _SOURCE_CAP:
                kept.append(item)
            else:
                headline = item.get("headline", "")[:60]
                dropped.append((item, src, headline))

        # If removing all excess items would breach the section minimum,
        # keep enough excess items (from the end) to stay at the floor.
        if len(kept) < floor and dropped:
            need = floor - len(kept)
            # Re-add the last N dropped items (least egregious duplicates)
            restored = dropped[-need:]
            dropped = dropped[:-need]
            for item, src, headline in restored:
                kept.append(item)

        if dropped:
            digest[section_key] = kept
            for _item, src, headline in dropped:
                log.append(f"  Removed excess {src} from {section_key}: '{headline}'")

    return log


def hill_calendar_log_line(payload: dict | None) -> str:
    """One line on whether the committee schedules answered.

    An empty calendar is ambiguous: no Korea hearing this week (normal in an
    October recess) or every schedule failing. The counts tell them apart.
    """
    stats = (payload or {}).get("hill_calendar_stats") or {}
    kept = len((payload or {}).get("hill_calendar") or [])
    if not stats:
        return f"Hill calendar: {kept} event(s) kept (no fetch counts in this payload)"
    line = (f"Hill calendar: {stats.get('fetched', 0)} event(s) fetched from "
            f"{stats.get('answered', 0)}/{stats.get('feeds', 0)} schedule(s), {kept} kept")
    # Why the rest went: "127 fetched, 0 kept" read as a broken filter when
    # every meeting listed had already been held (an October recess).
    dropped = stats.get("dropped") or {}
    parts = [f"{dropped[k]} {label}" for k, label in (
        ("past", "already held"), ("beyond_window", "beyond the 7-day window"),
        ("not_relevant", "not Korea/Indo-Pacific"), ("undated", "undated"),
        ("duplicate", "duplicate")) if dropped.get(k)]
    if parts:
        line += f" (dropped: {', '.join(parts)}"
        if dropped.get("date_range"):
            line += f"; listed dates {dropped['date_range']}"
        if stats.get("window"):
            line += f"; window {stats['window']}"
        line += ")"
    failed = [k for k, v in (stats.get("per_source") or {}).items() if v == "error"]
    if failed:
        line += f"; no answer from {', '.join(sorted(failed))}"
    return line


ANALYSIS_MAX = 5


def validate_digest(digest: dict, payload: dict | None = None) -> list[str]:
    """Pre-send quality gate. Returns list of warnings (empty = all clear)."""
    warnings = []

    # ── Section counts ───────────────────────────────────────────────────
    # Too FEW items is worth a regeneration: missing reporting cannot be
    # conjured from the digest we have. Too MANY is not — it is one slice.
    #
    # Treating an overage as critical caused a real send failure. A run
    # produced a perfectly good brief with six government items against a cap
    # of four; that tripped a full regeneration, which came back with zero
    # overnight items, which tripped another, which came back 370 words under
    # the floor. Three regenerations, two dollars, and no brief sent — from a
    # first attempt whose only fault was two extra items that could have been
    # dropped in a line of code.
    for section_key, (min_ct, max_ct) in SECTION_CAPS.items():
        items = digest.get(section_key) or []
        label = section_key.upper().replace("_", " ")
        if min_ct and len(items) < min_ct:
            warnings.append(f"{label} CRITICAL: only {len(items)} (min {min_ct})")
        elif len(items) > max_ct:
            # The model is asked to order by importance within a section, so
            # the tail is what it ranked lowest.
            digest[section_key] = items[:max_ct]
            warnings.append(f"{label}: {len(items)} items trimmed to {max_ct}")
    _opeds = list(digest.get("opeds_today") or [])
    _acad = list(digest.get("academic_today") or [])
    if len(_opeds) + len(_acad) > ANALYSIS_MAX:
        _before = len(_opeds) + len(_acad)
        while len(_opeds) + len(_acad) > ANALYSIS_MAX:
            (_opeds if len(_opeds) > 3 or not _acad else _acad).pop()
        digest["opeds_today"], digest["academic_today"] = _opeds, _acad
        warnings.append(f"ANALYSIS: {_before} pieces trimmed to {ANALYSIS_MAX}")

    # ── Morning memo uniqueness check ───────────────────────────────────
    memo_items = digest.get("morning_memo") or []
    for _i, _m in enumerate(memo_items):
        _n = len(str(_m).split())
        if _n > 30:
            warnings.append(f"MORNING MEMO: item {_i + 1} is {_n} words (limit 25); "
                            f"the glance is meant to be read in one look")
    if len(memo_items) >= 2:
        memo_texts = [str(m).strip() for m in memo_items]
        if len(set(memo_texts)) < len(memo_texts):
            warnings.append("MORNING MEMO: duplicate memo items detected — all 3 must be distinct")

    # ── RE: line must be present and substantive ─────────────────────────
    re_line = digest.get("re_line")
    if not re_line or len(str(re_line).strip()) < 10:
        warnings.append("RE: LINE CRITICAL: missing or too short")

    # ── Word count check (hard minimum 1,100, target 1,600-2,000) ──────
    # The critical floor stays well below target so a genuinely slow news day
    # still sends; it exists to catch truncated output, not thin days. The
    # warning band is what pulls the model toward the 1,600-word target.
    # Digest words, which the prompt's band is stated in: 1,700-2,000.
    from digest import MIN_DIGEST_WORDS
    word_count = _count_digest_words(digest)
    if word_count < 1100:
        warnings.append(f"WORD COUNT CRITICAL: ~{word_count} words (hard minimum 1100 — the brief is too short)")
    elif word_count < MIN_DIGEST_WORDS:
        warnings.append(f"WORD COUNT CRITICAL: ~{word_count} words (hard minimum {MIN_DIGEST_WORDS})")
    elif word_count < 1500:
        warnings.append(f"WORD COUNT: ~{word_count} words (band is 1,700-2,000)")
    elif word_count > 2100:
        # Not fatal: length_budget trims to the ceiling before rendering. This
        # says the model is over the prompt's 2,100 ceiling (digest words; the
        # rendered WORD_CEILING is what the trim enforces).
        warnings.append(f"WORD COUNT: ~{word_count} words, over the prompt's 2,100 ceiling "
                        f"— items will be trimmed before send")

    # ── KCNA delta should exist but is non-blocking ────────────────────────
    kcna = digest.get("kcna_delta")
    if not kcna or not isinstance(kcna, dict):
        warnings.append("KCNA DELTA: missing kcna_delta section (non-blocking)")
    elif kcna.get("data_unavailable"):
        pass  # no-data stub is valid — no KCNA dispatches were ingested today

    # ── Single pass over all items: URLs, headlines, sources, body checks ─
    seen_urls = {}
    seen_headlines = []  # (section, headline, keywords, topic_entities, company_entities)
    source_counts = {}
    bad_urls = 0
    dup_url_count = 0
    empty_body_count = 0

    for section_key in _ALL_ITEM_SECTIONS:
        for item in (digest.get(section_key) or []):
            url = item.get("url", "")

            # Bad URL check
            if url and (url == "#" or not url.startswith("http")):
                bad_urls += 1

            # Duplicate URL check
            if url and url.startswith("http"):
                if url in seen_urls:
                    dup_url_count += 1
                    if dup_url_count <= 3:
                        warnings.append(
                            f"DUPLICATE: URL appears in both {seen_urls[url]} and {section_key}")
                else:
                    seen_urls[url] = section_key

            # Empty body check — items should have substantive content
            body = (item.get("body") or item.get("body_text") or
                    item.get("summary") or item.get("detail") or "").strip()
            if not body or len(body) < 20:
                empty_body_count += 1

            # Source diversity (top_stories + overnight + also_today)
            if section_key in ("top_stories", "overnight_items", "also_today"):
                src = (item.get("source", "") or "").strip()
                if src:
                    source_counts[src] = source_counts.get(src, 0) + 1

            # Duplicate topic check (keyword overlap + entity matching)
            headline, words, topics, companies = _headline_key(item)
            if len(headline) > 15:
                for prev_section, prev_headline, prev_words, prev_topics, prev_companies in seen_headlines:
                    reason = _is_dup(words, topics, companies, prev_words, prev_topics, prev_companies)
                    if reason:
                        warnings.append(
                            f"DUPLICATE TOPIC CRITICAL: same topic in {prev_section} and {section_key} ({reason}): "
                            f"'{headline[:60]}...' vs '{prev_headline[:60]}...'")
                        break
                seen_headlines.append((section_key, headline, words, topics, companies))

    if bad_urls:
        warnings.append(f"BAD URLS: {bad_urls} placeholder or invalid URLs found")

    # The live HEAD check moved to links.finalize, which runs once on the
    # final digest, covers every URL field rather than these sections, and
    # removes a dead link instead of warning about it and shipping it.

    if empty_body_count:
        warnings.append(f"EMPTY BODIES: {empty_body_count} items have no substantive body text")

    # Source diversity (normalize source names to catch variants like "Yonhap" / "Yonhap News")
    normalized_counts: dict[str, int] = {}
    for src, count in source_counts.items():
        key = _normalize_source(src)
        normalized_counts[key] = normalized_counts.get(key, 0) + count
    for src, count in normalized_counts.items():
        if count > 10:
            warnings.append(
                f"SOURCE DIVERSITY CRITICAL: '{src}' appears {count} times across top sections — diversify sources")
        elif count > 7:
            warnings.append(
                f"SOURCE DIVERSITY: '{src}' appears {count} times across top sections — consider diversifying")

    # ── Check for "None" strings in critical fields ──────────────────────
    for field in ("re_line", "digest_date"):
        val = digest.get(field)
        if str(val).strip() == "None":
            warnings.append(f'NONE STRING: "{field}" field contains literal "None"')

    # ── Digest date matches today ────────────────────────────────────────
    digest_date = digest.get("digest_date", "")
    today_str = datetime.now(ZoneInfo("America/New_York")).strftime("%A, %B %-d, %Y")
    if digest_date and digest_date != today_str:
        warnings.append(f"DATE MISMATCH: digest says '{digest_date}', today is '{today_str}'")

    # ── Stale calendar_watch dates ──────────────────────────────────────
    # Read through korea_calendar.normalize, which accepts both shapes the
    # model has returned ({month, day, headline} and {date, event}); this
    # check read only the first and so never saw a {date, event} item.
    today_date = datetime.now(ZoneInfo("America/New_York")).date()
    import korea_calendar
    for cal_item in (digest.get("calendar_watch") or []):
        cal = korea_calendar.normalize(cal_item, today_date)
        if cal and cal["_end"] < today_date.isoformat():
            warnings.append(f"STALE CALENDAR: '{cal['headline'][:80]}' "
                            f"({cal['month'].upper()} {cal['day']}) is in the past")

    # ── Public sentiment must have all 4 metrics ─────────────────────────
    sentiment = digest.get("public_sentiment") or {}
    missing_sentiment = [k for k in ("presidential_approval", "party_ruling",
                                      "party_opposition", "party_independent")
                         if not (sentiment.get(k) or {}).get("value")]
    if missing_sentiment:
        warnings.append(f"SENTIMENT: missing values for {', '.join(missing_sentiment)}")

    # ── Prestige outlet cross-reference ───────────────────────────────
    # Use canonical name matching so "WSJ" matches "Wall Street Journal" etc.
    _PRESTIGE_CANONICAL = {
        "wsj": "wsj", "wall street journal": "wsj",
        "washington post": "wapo", "wapo": "wapo",
        "nyt": "nyt", "new york times": "nyt",
        "bloomberg": "bloomberg",
        "financial times": "ft", "ft": "ft",
        "economist": "economist", "the economist": "economist",
    }
    def _prestige_key(source_name: str) -> str | None:
        s = source_name.lower().strip()
        for prefix, key in _PRESTIGE_CANONICAL.items():
            if prefix in s:
                return key
        return None

    if payload:
        prestige_in_input: dict[str, str] = {}  # canonical_key -> original source name
        for tier_key in ("tier1", "tier2", "tier3", "tier4"):
            for a in (payload.get(tier_key) or []):
                src = (a.get("source") or "").strip()
                pk = _prestige_key(src)
                if pk and pk not in prestige_in_input:
                    prestige_in_input[pk] = src
        digest_prestige_keys: set[str] = set()
        for section_key in _ALL_ITEM_SECTIONS:
            for item in (digest.get(section_key) or []):
                pk = _prestige_key(item.get("source", ""))
                if pk:
                    digest_prestige_keys.add(pk)
        for pk, src in prestige_in_input.items():
            if pk not in digest_prestige_keys:
                warnings.append(
                    f"PRESTIGE OUTLET DROPPED: '{src}' had Korea articles in input but none appeared in digest")

    # ── Satellite imagery dual-placement check ──────────────────────────
    imagery_report = digest.get("imagery_report")
    if imagery_report and isinstance(imagery_report, dict):
        source_links = imagery_report.get("source_links") or []
        if source_links:
            story_urls: set[str] = set()
            for sk in ("top_stories", "overnight_items"):
                for item in (digest.get(sk) or []):
                    u = (item.get("url") or "").strip()
                    if u:
                        story_urls.add(u)
            # source_links is an array of {label, url} dicts (per digest schema).
            # Be defensive: accept either dicts or bare URL strings.
            link_urls = []
            for link in source_links:
                if isinstance(link, dict):
                    u = (link.get("url") or "").strip()
                    if u:
                        link_urls.append(u)
                elif isinstance(link, str):
                    link_urls.append(link.strip())
            if link_urls and not any(u in story_urls for u in link_urls):
                warnings.append(
                    "IMAGERY DUAL PLACEMENT: imagery_report exists but no matching story in top_stories/overnight_items")

    # ── Cross-reference: every digest URL must exist in input feed ────────
    if payload:
        # The same input the URL repair reads (links.corpus_index): the tiers,
        # the Hill and world streams, satellite reports and the X signals. The
        # tiers alone flagged every quoted X post as fabricated, and on 21 Oct
        # that cost two regenerations and the day's brief.
        import links as _links
        _index = _links.corpus_index(payload)
        fabricated_count = 0
        for section_key in _ALL_ITEM_SECTIONS:
            for item in (digest.get(section_key) or []):
                url = (item.get("url") or "").strip()
                if url and url.startswith("http") and not _links.lookup(url, _index):
                    headline = (item.get("headline") or item.get("translated_title")
                                or item.get("title") or "")[:80]
                    fabricated_count += 1
                    if fabricated_count <= 5:
                        warnings.append(
                            f"FABRICATED ARTICLE CRITICAL: URL not in input feed — {section_key}: "
                            f"'{headline}' ({url})")
        if fabricated_count:
            warnings.append(
                f"FABRICATED ARTICLES CRITICAL: {fabricated_count} article(s) have URLs not found "
                f"in today's input feed — likely hallucinated")

    # Cross-check against the shared engine's checks. Additive on purpose: the
    # local gate above stays authoritative for Korea, and anything the shared
    # module catches that the local gate missed shows up here. That difference
    # is the signal — it means a check exists in one place and not the other,
    # which is exactly the drift the shared package exists to end.
    try:
        from shared import validate as _shared_validate
        # Every shared problem is reported, even if the local gate found the
        # same thing. An operator can ignore a duplicate; a suppressed warning
        # is how a real defect ships. An earlier version deduplicated on the
        # section name and swallowed a genuine placeholder catch.
        for _problem in _shared_validate.run_all(
                digest, sections=_ALL_ITEM_SECTIONS, word_count=_count_digest_words(digest)):
            warnings.append(f"[shared] {_problem}")
    except Exception as _e:
        print(f"  ⚠  Shared validation skipped (non-fatal): {_e}")

    warnings.extend(magnitude_warnings(digest, payload))
    return warnings


_MONEY_RE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s?(trillion|tn|T|billion|bn|B)\b")
_KOREA_RE = re.compile(r"\b(Korea|Korean|ROK|Seoul)\b")
_BALANCE_RE = re.compile(r"\b(surplus|surpluses|deficit|deficits)\b", re.I)
# South Korea's trade balances, overall or with any one partner, run in the
# tens of billions of dollars a year. A Korean surplus or deficit stated in
# the hundreds of billions is a dropped decimal, not news.
KOREA_BALANCE_CEILING_B = 300



# Words and constructions the prompt bans (digest.py, writing rules). The
# model still uses some; this names them on the run page so whether the rules
# hold can be tracked. It reports and rewrites nothing.
_BANNED_PROSE = re.compile(
    r"\b(amid|signal(?:s|ed|ing)?|underscor\w*|highlight(?:s|ed|ing)|framing|posture|deepening|"
    r"sweeping|sharpest|landscape|robust|pivotal|notably|coincid\w*|first-ever)\b|\bthe same day\b",
    re.I)


def banned_prose(digest: dict) -> list[str]:
    """Each banned word or phrase in the brief's prose, as 'word (section)', in order found."""
    found: list[str] = []

    def walk(v, path: str):
        if isinstance(v, dict):
            for k, x in v.items():
                if not str(k).startswith("_") and k not in ("url", "secondary_url", "source_url",
                                                             "gnews_url", "source", "src_line", "note"):
                    walk(x, path or k)
        elif isinstance(v, list):
            for x in v:
                walk(x, path)
        elif isinstance(v, str):
            for m in _BANNED_PROSE.finditer(v):
                found.append(f"{m.group(0).lower()} ({path})")

    walk({k: v for k, v in digest.items() if k != "bp_locations"}, "")
    return found

# On the last attempt a brief this long is sent with a warning rather than
# held: the minimum exists to catch truncated output, and a short brief is
# worth more to the reader than none.
FINAL_ATTEMPT_MIN_WORDS = 900


def drop_unsourced_items(digest: dict, payload: dict) -> list[str]:
    """Remove items whose URL is in no collected input; a top story loses only its link.

    Used on the final attempt, so a link the model invented costs that item,
    not the day's brief. Returns one line per change.
    """
    import links as _links
    index = _links.corpus_index(payload or {})
    out: list[str] = []
    for key in _ALL_ITEM_SECTIONS:
        items = digest.get(key)
        if not isinstance(items, list):
            continue
        kept = []
        for item in items:
            url = str((item or {}).get("url") or "").strip() if isinstance(item, dict) else ""
            if url.startswith("http") and not _links.lookup(url, index):
                head = str(item.get("headline") or item.get("title") or item.get("who") or "")[:60]
                if key == "top_stories":
                    item["url"] = ""
                    out.append(f"unlinked {key}: {head!r}")
                else:
                    out.append(f"dropped {key}: {head!r}")
                    continue
            kept.append(item)
        digest[key] = kept
    return out


def magnitude_warnings(digest: dict, payload: dict | None = None) -> list[str]:
    """Figures far out of scale for what they describe, usually a dropped decimal.

    On 18 October the brief said Korea's surplus with the US 'reached $847B'
    through September, heading for 'a first-ever annual figure above $100B,'
    against 'last year's $495B' — $84.7B and $49.5B with the decimal point
    lost — and Today at a Glance turned it into 'above $1 trillion'. Nothing
    checked scale. This flags a Korean trade surplus or deficit stated above
    KOREA_BALANCE_CEILING_B, which gets the model one regeneration with the
    sentence in front of it.
    """
    out, seen = [], set()

    def scan(text: str):
        for sent in re.split(r"(?<=[.;!?])\s+", text):
            if not (_KOREA_RE.search(sent) and _BALANCE_RE.search(sent)):
                continue
            for m in _MONEY_RE.finditer(sent):
                try:
                    v = float(m.group(1).replace(",", ""))
                except ValueError:
                    continue
                unit = m.group(2).lower()
                billions = v * 1000 if unit in ("trillion", "tn", "t") else v
                if billions >= KOREA_BALANCE_CEILING_B and m.group(0) not in seen:
                    seen.add(m.group(0))
                    out.append(f"MAGNITUDE CRITICAL: \"{sent.strip()[:160]}\" states {m.group(0)} for a "
                               f"South Korean trade balance; Korea's surpluses and deficits run in the tens of "
                               f"billions. Check the source for a dropped decimal (e.g. $84.7B, not $847B) and "
                               f"correct every place the figure appears, including the morning memo.")

    def walk(v):
        if isinstance(v, str):
            scan(v)
        elif isinstance(v, dict):
            for k, x in v.items():
                if k not in ("url", "source_links", "_trade_standing_html"):
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(digest)
    out.extend(_eok_scale_warnings(digest, payload))
    return out


# 847억 달러, 1000억弗, 120억불: a dollar amount in units of 억 (100 million).
_EOK_USD_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*억\s*(?:달러|弗|불|\$)")


def _eok_scale_warnings(digest: dict, payload: dict | None = None) -> list[str]:
    """A "$NNNB" figure that is ten times a 억-dollar figure in its cited Korean source.

    억 is 100 million, so N억 달러 is N/10 billion. Read as N billion, the
    figure comes out exactly ten times too big: 847억 달러 printed as $847B
    on 18 October, and 1000억弗 as "$1 trillion". The trade-balance check
    only sees surpluses and deficits; this sees any figure whose own source
    carried the 억 form.

    Each item is checked against what it cites: the collected article at its
    URL when the payload is at hand, and its source label, which often quotes
    the Korean headline. Checking against every article would flag the $350B
    pledge whenever any story mentioned 350억 달러 of something else. The
    morning memo and RE: line cite nothing, so a figure there is flagged when
    the same figure was flagged in an item.
    """
    by_url: dict[str, str] = {}
    for tier in ("tier1", "tier2", "tier3", "tier4"):
        for a in ((payload or {}).get(tier) or []):
            if a.get("url"):
                by_url[a["url"].strip()] = f'{a.get("title", "")} {a.get("summary", "")}'

    def eok_values(text: str) -> set[float]:
        vals = set()
        for m in _EOK_USD_RE.finditer(text):
            try:
                vals.add(float(m.group(1).replace(",", "")) / 10)
            except ValueError:
                pass
        return vals

    def billions_of(m: re.Match) -> float | None:
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            return None
        return v * 1000 if m.group(2).lower() in ("trillion", "tn", "t") else v

    out: list[str] = []
    flagged: dict[str, float] = {}      # "$847B" -> 84.7

    def check_item(item: dict):
        cited = " ".join(str(item.get(k) or "") for k in ("source", "src_line", "source_label"))
        urls = [str(item.get("url") or "").strip()]
        for link in item.get("source_links") or []:
            if isinstance(link, dict):
                urls.append(str(link.get("url") or "").strip())
        cited += " " + " ".join(by_url.get(u, "") for u in urls if u)
        truth = eok_values(cited)
        if not truth:
            return
        for k, v in item.items():
            if k in ("source", "src_line", "source_label", "url", "source_links") or not isinstance(v, str):
                continue
            for m in _MONEY_RE.finditer(v):
                b = billions_of(m)
                for tb in truth:
                    if b and tb and abs(b - 10 * tb) < 0.01 * b and m.group(0) not in flagged:
                        flagged[m.group(0)] = tb

    for key, val in digest.items():
        if key.startswith("_"):
            continue
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    check_item(item)
        elif isinstance(val, dict):
            check_item(val)
            for sub in val.values():          # us_korea_deals.deals and the like
                if isinstance(sub, list):
                    for item in sub:
                        if isinstance(item, dict):
                            check_item(item)

    for fig, tb in flagged.items():
        out.append(f"MAGNITUDE CRITICAL: {fig} is ten times the {tb * 10:g}억 dollars in its "
                   f"Korean source; 억 is 100 million, so the figure is ${tb:g}B. Correct it "
                   f"everywhere it appears, including morning_memo and key_stat.")
    memo = " ".join(str(x) for x in (digest.get("morning_memo") or [])) + " " + str(digest.get("re_line") or "")
    for m in _MONEY_RE.finditer(memo):
        b = billions_of(m)
        if b and any(abs(b - 10 * tb) < 0.01 * b for tb in flagged.values()):
            out.append(f"MAGNITUDE CRITICAL: {m.group(0)} in the morning memo or RE: line repeats a "
                       f"figure ten times its Korean source (억 = 100 million).")
    return out


def _headline_tokens(text: str) -> set[str]:
    """Tokenize a headline for fuzzy matching: drop stopwords and short words."""
    if not text:
        return set()
    return {w for w in re.split(r"\W+", text.lower())
            if len(w) > 2 and w not in _STOP_WORDS}


def _repair_digest_urls(digest: dict, payload: dict) -> list[str]:
    """Repair or drop digest items whose URLs don't match any input-feed URL.

    Claude sometimes outputs Google News RSS URLs with slightly altered query
    strings (repairable by headline match) or outright fabricates items that
    have no input backing (unrepairable — must be dropped so validation can
    pass).

    Two-pass behavior per digest item whose URL isn't in the input set:
      1. Fuzzy-match by headline token overlap (>=3 shared non-stopword tokens
         AND >=50% of the shorter headline). If found, rewrite URL to verbatim.
      2. Otherwise mark for drop. After processing a section, drop all marked
         items subject to section floors (top_stories >= 2, overnight_items >= 3).
         If a section would fall below its floor, restore the minimum number
         of items from the end of the drop list (least likely to be real news
         since they're last in priority order).

    Also drops items with empty headline AND empty body (garbage entries).

    Mutates digest in place. Returns a list of log messages.
    """
    log: list[str] = []
    if not payload:
        return log

    # Index every input article: (url, title, tokens). Everything the model
    # was shown counts, not only tiers 1-4: the satellite and Kim-tracker
    # streams and the X signals are input too, and a link to one of them was
    # being treated as fabricated.
    import links as _links
    _index = _links.corpus_index(payload)
    input_articles: list[tuple[str, str, set[str]]] = []
    input_urls: set[str] = set()
    for a in _index.values():
        u = (a.get("url") or "").strip()
        input_urls.add(u)
        title = (a.get("title") or a.get("headline") or "").strip()
        input_articles.append((u, title, _headline_tokens(title)))

    if not input_urls:
        return log

    # Section floors — emergency minimums when dropping fabricated items.
    # These are deliberately 1 lower than the strict digest floors so we can
    # still drop obvious hallucinations without starving the section.
    _DROP_FLOORS = {"top_stories": 2, "overnight_items": 3}

    for section_key in _ALL_ITEM_SECTIONS:
        items = digest.get(section_key)
        if not items or not isinstance(items, list):
            continue

        kept: list = []
        # Split drop reasons so floor protection can restore fabricated items
        # (which have real content) but never restores empty garbage.
        always_drop: list[tuple[dict, str]] = []      # empty/broken — never restore
        restorable_drop: list[tuple[dict, str]] = []  # unmatched URL but has content

        for item in items:
            url = (item.get("url") or "").strip()
            headline = (item.get("headline") or item.get("translated_title")
                        or item.get("title") or item.get("who") or "").strip()
            # Quoted statements carry their text in different fields. Without
            # these, every social_statements item looked headline-less and
            # body-less and was dropped as garbage — the whole section, every
            # run, four items a night, and the words that went with them are
            # part of why the brief kept landing under its floor.
            body = (item.get("body") or item.get("body_text")
                    or item.get("summary") or item.get("detail")
                    or item.get("quote_text") or item.get("activity") or "").strip()

            # Drop garbage: no headline AND no body — never restore this
            if not headline and len(body) < 20:
                always_drop.append((item, "empty headline and body"))
                continue

            # URL missing/invalid or already matches input → keep as-is
            if not url or not url.startswith("http"):
                kept.append(item)
                continue
            if url in input_urls or _links.lookup(url, _index):
                kept.append(item)
                continue

            # Try to repair via headline token match
            tokens = _headline_tokens(headline)
            best_url = None
            best_score = 0
            if len(tokens) >= 3:
                for in_url, _in_title, in_tokens in input_articles:
                    if not in_tokens:
                        continue
                    overlap = tokens & in_tokens
                    min_len = min(len(tokens), len(in_tokens))
                    if (len(overlap) >= 3
                            and len(overlap) / min_len >= 0.5
                            and len(overlap) > best_score):
                        best_score = len(overlap)
                        best_url = in_url

            if best_url:
                log.append(
                    f"  Repaired URL in {section_key}: '{headline[:60]}' "
                    f"({best_score} token match)")
                item["url"] = best_url
                kept.append(item)
            else:
                reason = (f"headline too short ({len(tokens)} tokens)"
                          if len(tokens) < 3 else "no headline match in input")
                restorable_drop.append((item, reason))

        # Enforce floor: restore from restorable_drop only (never empty garbage)
        floor = _DROP_FLOORS.get(section_key, 0)
        if restorable_drop and len(kept) < floor:
            need = floor - len(kept)
            restored = restorable_drop[-need:]
            restorable_drop = restorable_drop[:-need]
            for item, _reason in restored:
                # The text stays to hold the floor; the link we could not
                # trace to any input does not ship.
                item["url"] = ""
                log.append(
                    f"  ⚠ Kept unlinked item in {section_key} to protect "
                    f"floor (min {floor}): '{(item.get('headline') or '')[:60]}'")
                kept.append(item)

        for item, reason in (always_drop + restorable_drop):
            hl = (item.get("headline") or item.get("translated_title")
                  or item.get("title") or "(no headline)")[:60]
            log.append(
                f"  Dropped unrepairable {section_key} item ({reason}): '{hl}'")

        digest[section_key] = kept

    return log


_PLACEHOLDER_NAME_RE = re.compile(
    r"not\s+named|unnamed|not\s+specified|not\s+disclosed|unidentified|"
    r"unknown|n/?a$|tbd|placeholder|see\s+source", re.IGNORECASE)


# The leaders whose words the prompt asks for: at most one quote each, so
# Statements is not three of one leader's lines. (The v2 "Leaders' words"
# card that once showed them is gone.) Kim Jong Un's go in kcna_delta.key_quotes.
_LEADERS = {"lee": re.compile(r"\blee jae[- ]?myung\b|^president lee\b|\bpresident lee jae", re.I),
            "trump": re.compile(r"\btrump\b", re.I)}


def _cap_leader_quotes(digest: dict) -> list[str]:
    """One quote per leader in social_statements, one Kim quote in kcna_delta.

    The model is asked for this; the cap makes it hold. The first quote a
    leader has is kept (the model orders by importance), the rest dropped.
    """
    log = []
    kept, seen = [], set()
    for item in digest.get("social_statements") or []:
        who = str((item or {}).get("who") or "")
        leader = next((k for k, rx in _LEADERS.items() if rx.search(who)), None)
        if leader and leader in seen:
            log.append(f"  social_statements: second {who} quote dropped")
            continue
        if leader:
            seen.add(leader)
        kept.append(item)
    if digest.get("social_statements") is not None:
        digest["social_statements"] = kept
    kcna = digest.get("kcna_delta")
    if isinstance(kcna, dict) and len(kcna.get("key_quotes") or []) > 1:
        log.append(f"  kcna_delta.key_quotes: {len(kcna['key_quotes'])} trimmed to 1")
        kcna["key_quotes"] = kcna["key_quotes"][:1]
    return log


def _drop_news_from_analysis(digest: dict, payload: dict | None) -> list[str]:
    """A news story is never analysis.

    An opeds_today item whose URL is a tier-1 article and not a tier-2 piece,
    or a tier-2 item of kind "news" (NK Pro), is reporting. Dropped rather
    than moved: the news sections were written without it, and moving it
    could duplicate one of their items.
    """
    if not payload:
        return []
    analysis = {}
    for tier in ("tier2", "tier3"):
        for a in payload.get(tier) or []:
            if isinstance(a, dict) and a.get("url"):
                analysis[a["url"].strip()] = a.get("kind") or "report"
    news = {a["url"].strip() for a in payload.get("tier1") or []
            if isinstance(a, dict) and a.get("url")}
    log, kept = [], []
    for item in digest.get("opeds_today") or []:
        url = str((item or {}).get("url") or "").strip()
        kind = analysis.get(url)
        if kind == "news" or (kind is None and url in news):
            log.append(f"  opeds_today: news story dropped from Analysis: "
                       f"{str(item.get('headline', ''))[:70]}")
            continue
        kept.append(item)
    if log:
        digest["opeds_today"] = kept
    return log


def drop_recently_used_analysis(payload: dict, index_rows: list, today_slug: str) -> int:
    """Remove tier-2/3 and Capitol Hill pieces a brief already carried this week.

    Their windows run from two days to a week, so without this the same
    think-tank report or CRS report would be offered, and could run, on
    several mornings. Only pieces a published brief used are removed; one
    collected yesterday but left out is still eligible. Returns the count.
    """
    used_urls, used_titles = set(), set()
    for r in index_rows or []:
        if r.get("used") and str(r.get("date", "")) < today_slug:
            if r.get("url"):
                used_urls.add(str(r["url"]).strip())
            if r.get("title"):
                used_titles.add(re.sub(r"\W+", " ", str(r["title"]).lower()).strip())
    if not used_urls and not used_titles:
        return 0
    dropped = 0
    for key in ("tier2", "tier3", "capitol_hill_articles"):
        items = payload.get(key) or []
        kept = [a for a in items
                if str(a.get("url") or "").strip() not in used_urls
                and re.sub(r"\W+", " ", str(a.get("title") or "").lower()).strip() not in used_titles]
        dropped += len(items) - len(kept)
        if key in payload:
            payload[key] = kept
    return dropped


def _drop_nameless_personnel(digest: dict) -> list[str]:
    """Strip rok_personnel entries whose name is missing or a placeholder.

    A personnel entry without a real name is worse than no entry — expert
    readers immediately notice (e.g. a nomination rendered as "Not named
    in source" when the name was in the article headline). The prompt
    forbids placeholders; this is the hard backstop. Placeholder
    predecessors are nulled rather than dropping the entry.
    """
    log = []
    personnel = digest.get("rok_personnel") or []
    if not personnel:
        return log
    kept = []
    for item in personnel:
        name = str(item.get("name") or "").strip()
        if not name or _PLACEHOLDER_NAME_RE.search(name):
            log.append(f"  - dropped personnel entry with placeholder name "
                       f"{name!r} (position: {item.get('position', '?')})")
            continue
        pred = str(item.get("predecessor") or "").strip()
        if pred and _PLACEHOLDER_NAME_RE.search(pred):
            item["predecessor"] = None
        kept.append(item)
    digest["rok_personnel"] = kept
    return log


_ONTHISDAY_DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(\d{1,2})", re.IGNORECASE)
_MONTH_NUM = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}


def _drop_offdate_on_this_day(digest: dict, now: datetime | None = None) -> list[str]:
    """Drop on_this_day entries whose date isn't TODAY's exact month + day.

    "On This Day" must anchor to the current calendar date. The prompt says so,
    but the model still reaches for famous anniversaries (e.g. the July 4 2017
    Hwasong-14 test in a July 24 issue). Unlike appointment dates, this IS
    code-checkable: parse the entry's Month+Day and compare to today (ET).
    """
    log = []
    otd = digest.get("on_this_day") or []
    if not otd:
        return log
    if now is None:
        now = datetime.now(ZoneInfo("America/New_York"))
    from digest import VERIFIED_KOREA_DATES
    verified = {(m, d, y) for m, d, y, _ev in VERIFIED_KOREA_DATES}
    kept = []
    for item in otd:
        date_str = str(item.get("date") or "")
        m = _ONTHISDAY_DATE_RE.search(date_str)
        if not m:
            log.append(f"  - dropped on_this_day with unparseable date {date_str!r}")
            continue
        month = _MONTH_NUM.get(m.group(1).lower())
        day = int(m.group(2))
        if month != now.month or day != now.day:
            log.append(f"  - dropped on_this_day {date_str!r} "
                       f"(not today {now.strftime('%B %-d')})")
            continue
        # The right day of the wrong year is still a wrong date. The year
        # must be one the prompt's verified list gives for this day.
        year = re.search(r"\b(1[89]\d\d|20\d\d)\b", date_str)
        if not year or (month, day, int(year.group(1))) not in verified:
            log.append(f"  - dropped on_this_day {date_str!r} "
                       f"(year not in the verified list for {now.strftime('%B %-d')})")
            continue
        kept.append(item)
    digest["on_this_day"] = kept
    return log


# ── Process notes printed to readers ────────────────────────────────────────
# The model narrates its own working: "See source article for name",
# "(implied)", "(unspecified committee)", "excluded ... per scope rules",
# "according to today's reporting", "the tracker's note". All of these
# reached readers. A parenthetical note is cut out of the text; a sentence
# that is a note is dropped; an item whose essential field was nothing but a
# note is dropped whole, because there is nothing left to print.
_NOTE_PAREN_RE = re.compile(
    r"\s*\((?:implied|inferred|unspecified[^)]*|not\s+(?:named|specified|stated|given)[^)]*|"
    r"unnamed[^)]*|name\s+not\s+(?:given|stated)[^)]*|see\s+source[^)]*|per\s+(?:the\s+)?source)\)",
    re.I)
_NOTE_SENTENCE_RE = re.compile(
    r"\bsee\s+(?:the\s+)?source(?:\s+article)?\b|\bper\s+(?:the\s+)?scope\s+rules?\b|\bscope\s+rules?\b|"
    r"\bthe\s+(?:BP\s+|KCNA\s+|Kim\s+|locations?\s+)?tracker'?s?\b|"
    r"\btoday'?s\s+(?:articles|reporting|feed|input|source\s+articles|batch)\b|"
    r"\bnot\s+named\s+in\s+(?:the\s+)?source\b|\(implied\)|\bunspecified\s+committee\b", re.I)
# Fields that are the item. If one of these is emptied, the item goes.
_NOTE_CORE_FIELDS = ("headline", "action", "name", "who", "quote_text", "body", "body_text",
                     "detail", "finding", "number", "event", "committee", "position")
# Never dropped whole: fixed sections the page lays out by position.
_NOTE_KEEP_ITEMS = ("bp_locations", "market_indicators", "public_sentiment", "us_korea_deals",
                    "kcna_delta", "morning_memo")
_NOTE_SKIP_KEYS = ("url", "source", "src_line", "source_label", "source_links", "badge_class",
                   "avatar_initials", "category", "category_tag", "region", "region_tag", "date",
                   "month", "day", "last_updated", "last_source_date", "poll_date")


def _clean_note_text(text: str) -> str:
    """Text with process notes removed (may come back empty)."""
    t = _NOTE_PAREN_RE.sub("", text)
    if _NOTE_SENTENCE_RE.search(t):
        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'“(])", t)
        t = " ".join(p for p in parts if not _NOTE_SENTENCE_RE.search(p))
    return t.strip()


def _strip_process_notes(digest: dict) -> list[str]:
    """Remove the model's descriptions of its own process from every field."""
    log: list[str] = []

    def clean_item(section: str, item: dict) -> bool:
        """Clean in place; False if the item should be dropped."""
        for k, v in list(item.items()):
            if k in _NOTE_SKIP_KEYS or k.startswith("_"):
                continue
            if isinstance(v, str):
                new = _clean_note_text(v)
                if new != v.strip():
                    log.append(f"  - {section}.{k}: {v[:90]!r} -> {new[:60]!r}")
                    # Only a fixed section's own fields are protected; items
                    # listed inside one (us_korea_deals.deals) can still go.
                    if not new and k in _NOTE_CORE_FIELDS and section not in _NOTE_KEEP_ITEMS:
                        return False
                    item[k] = new if new else None
            elif isinstance(v, list) and v and all(isinstance(x, str) for x in v):
                new_list = [_clean_note_text(x) for x in v]
                if new_list != [x.strip() for x in v]:
                    log.append(f"  - {section}.{k}: {str(v)[:90]!r}")
                    item[k] = [x for x in new_list if x]
            elif isinstance(v, dict):
                if not clean_item(f"{section}.{k}", v):
                    log.append(f"  - dropped {section}.{k}: its content was a process note")
                    item[k] = None
            elif isinstance(v, list):
                kept = [x for x in v if not isinstance(x, dict) or clean_item(f"{section}.{k}", x)]
                if len(kept) != len(v):
                    log.append(f"  - dropped {len(v) - len(kept)} item(s) from {section}.{k}")
                    item[k] = kept
        return True

    for key in list(digest.keys()):
        if key.startswith("_") or key in ("web_url", "audio_url", "listen_url", "digest_date"):
            continue
        val = digest[key]
        if isinstance(val, list):
            if val and all(isinstance(x, str) for x in val):
                new = [_clean_note_text(x) for x in val]
                if new != [x.strip() for x in val]:
                    log.append(f"  - {key}: process note removed")
                    digest[key] = [x for x in new if x]
                continue
            kept = []
            for item in val:
                if isinstance(item, dict) and not clean_item(key, item):
                    hl = (item.get("headline") or item.get("action") or item.get("name")
                          or item.get("who") or "")
                    log.append(f"  - dropped {key} item that was a process note: {str(hl)[:70]!r}")
                    continue
                kept.append(item)
            digest[key] = kept
        elif isinstance(val, dict):
            if not clean_item(key, val) and key not in _NOTE_KEEP_ITEMS:
                log.append(f"  - dropped {key}: its content was a process note")
                digest[key] = None
        elif isinstance(val, str):
            new = _clean_note_text(val)
            if new != val.strip():
                log.append(f"  - {key}: process note removed")
                digest[key] = new or None
    return log


_PCT_RE = re.compile(r"(\d{1,2}(?:\.\d)?)\s?(?:%|percent)")


def _drop_topline_spotlight(digest: dict) -> list[str]:
    """Null the Gallup spotlight when it only restates the topline.

    The spotlight is meant for the weekly special-topic question. On every
    day from 9 to 18 October it repeated the approval and party figures
    already shown beside it. If its numbers include the topline approval
    figure, or two or more of the four topline figures, it is the topline.
    """
    ps = digest.get("public_sentiment")
    if not isinstance(ps, dict) or not isinstance(ps.get("gallup_spotlight"), dict):
        return []
    spot = ps["gallup_spotlight"]
    nums = {float(x) for x in _PCT_RE.findall(f'{spot.get("topic", "")} {spot.get("finding", "")}')}

    def val(k):
        raw = str((ps.get(k) or {}).get("value") or "").strip().rstrip("%")
        try:
            return float(raw)
        except ValueError:
            return None
    top = {k: val(k) for k in ("presidential_approval", "party_ruling",
                               "party_opposition", "party_independent")}
    shared = {v for v in top.values() if v is not None} & nums
    if top["presidential_approval"] in nums or len(shared) >= 2:
        ps["gallup_spotlight"] = None
        return [f"  - dropped gallup_spotlight that restated the topline: "
                f"{str(spot.get('finding', ''))[:90]!r}"]
    return []


def _normalize_calendar(digest: dict, today=None) -> list[str]:
    """Rewrite calendar_watch into the one shape everything reads.

    Drops items with no readable day, events already over, and fixtures no
    policy reader acts on. See korea_calendar.normalize.
    """
    import korea_calendar
    today = today or datetime.now(ZoneInfo("America/New_York")).date()
    log, kept = [], []
    for raw in digest.get("calendar_watch") or []:
        item = korea_calendar.normalize(raw, today)
        label = (str(raw.get("headline") or raw.get("event") or "") if isinstance(raw, dict)
                 else str(raw))[:70]
        if item is None:
            log.append(f"  - dropped calendar item with no readable date: {label!r}")
        elif item["_end"] < today.isoformat():
            log.append(f"  - dropped past calendar item: {label!r}")
        elif korea_calendar.off_topic(item):
            log.append(f"  - dropped off-topic calendar item: {label!r}")
        else:
            kept.append(item)
    digest["calendar_watch"] = kept
    return log


def _maybe_persist_sentiment_baseline(digest_data: dict) -> str | None:
    """Durable Gallup auto-update: if the digest's model-extracted
    public_sentiment reflects a NEWER Gallup poll than the stored baseline,
    write it to gallup_baseline.json. This reuses the daily digest's own reading
    of the news (which works every day) instead of the separate Friday scrape,
    so a fresh Friday poll persists automatically. Same-poll + newer-date +
    sanity guarded; best-effort (never raises). Returns a log line or None."""
    try:
        import re as _re
        import gallup_update as gu
        ps = digest_data.get("public_sentiment") or {}
        appr = ps.get("presidential_approval") or {}
        if "gallup" not in str(appr.get("source", "")).lower():
            return None  # only Gallup drives the baseline (same-poll integrity)
        m = _re.search(r"(\d{4}-\d{2}-\d{2})", str(appr.get("last_updated", "")))
        if not m:
            return None
        new_key = m.group(1)
        baseline = gu._load_baseline()
        cur_key = gu._current_sort_key(baseline)
        if cur_key and new_key <= cur_key:
            return None  # not newer than what we have
        pres = gu._pct(appr.get("value"))
        dp = gu._pct((ps.get("party_ruling") or {}).get("value"))
        ppp = gu._pct((ps.get("party_opposition") or {}).get("value"))
        ind = gu._pct((ps.get("party_independent") or {}).get("value"))
        if gu._sane(pres, dp, ppp, ind):
            return None  # implausible numbers — don't persist
        old = {k: gu._pct((baseline.get(k) or {}).get("value"))
               for k in ("presidential_approval", "party_ruling",
                         "party_opposition", "party_independent")}
        # Store the label in the 'Month D, YYYY' form every reader parses
        # (gallup_update._current_sort_key, healthcheck age checks). A bare
        # ISO label written here on 2026-09-04 read as "undated" and let an
        # older poll overwrite it the next morning.
        label = gu._normalize_date_label(new_key)[0] or new_key
        updated = dict(baseline)
        updated.update({
            "poll": f"Gallup Korea ({label})",
            "survey_dates": label,
            "source": "Gallup Korea",
            "presidential_approval": {"value": f"{pres:g}%", "trend": gu._trend(pres, old["presidential_approval"])},
            "party_ruling": {"value": f"{dp:g}%", "party": "Democratic Party", "party_kr": "더불어민주당",
                             "trend": gu._trend(dp, old["party_ruling"])},
            "party_opposition": {"value": f"{ppp:g}%", "party": "People Power Party", "party_kr": "국민의힘",
                                 "trend": gu._trend(ppp, old["party_opposition"])},
            "updated_at": datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d"),
            "updated_by": "run.py (auto — persisted from digest public_sentiment)",
        })
        if ind is not None:
            updated["party_independent"] = {"value": f"{ind:g}%", "trend": gu._trend(ind, old["party_independent"])}
        spot = ps.get("gallup_spotlight")
        if isinstance(spot, dict) and spot.get("topic"):
            updated["spotlight"] = {"headline": spot.get("finding") or spot.get("topic"),
                                    "poll_date": label}
        # Append to the approval series before writing, so the brief can show a
        # trend alongside the number. No-op on a survey already recorded.
        try:
            import poll_history
            poll_history.record(new_key, pres, label=label, baseline=updated)
        except Exception as _e:
            print(f"  ⚠  Poll history skipped (non-fatal): {_e}")
        gu.BASELINE_PATH.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
        return f"{label}: approval {pres:g}%, DP {dp:g}%, PPP {ppp:g}%, ind {ind if ind is None else format(ind, 'g')}%"
    except Exception as e:
        print(f"  ⚠  Sentiment-baseline persist skipped (non-fatal): {e}")
        return None


def _ensure_pledge_projects(digest: dict) -> list[str]:
    """Guarantee the $350B pledge block has its selected projects.

    The block is meant to appear in every issue, and a section that depends on
    the model repeating a list each day will eventually be missing from one.
    These projects are a standing fact held in digest.PLEDGE_PROJECTS, so they
    do not need to survive a round trip through generation to be printed.

    Fills gaps only: a project the model returned is left exactly as written,
    including a value it updated from today's reporting. Planned projects are
    excluded — the block renders under "Selected Projects", and listing one
    still awaiting US consultation there would read as chosen.
    """
    log: list[str] = []
    try:
        from digest import SELECTED_PLEDGE_PROJECTS
    except Exception:                                           # noqa: BLE001
        return log
    if not SELECTED_PLEDGE_PROJECTS or not isinstance(digest, dict):
        return log
    deals = digest.setdefault("us_korea_deals", {})
    if not isinstance(deals, dict):
        return log
    pkg = deals.setdefault("investment_package", {})
    if not isinstance(pkg, dict):
        return log
    if not str(pkg.get("total_pledged") or "").strip():
        pkg["total_pledged"] = "$350B"
    known = pkg.get("known_deals")
    if not isinstance(known, list):
        known = []
    # Match by containment on a normalised name, not by exact string. The
    # model writes "Encinal gas-fired power plant, Texas"; the list holds
    # "Encinal gas-fired power plant". An exact comparison called those two
    # different projects, so the backfill appended a second copy — and on
    # 7 October the brief printed Encinal twice under Selected Projects.
    def _key(name) -> str:
        return " ".join(re.sub(r"[^a-z0-9 ]+", " ", str(name).lower()).split())

    def _same(a: str, b: str) -> bool:
        return bool(a) and bool(b) and (a in b or b in a)

    deduped: list = []
    for d in known:                       # the model can repeat itself too
        if not isinstance(d, dict):
            continue
        if any(_same(_key(d.get("company")), _key(x.get("company"))) for x in deduped):
            log.append(f"pledge project duplicate dropped: {d.get('company')}")
            continue
        deduped.append(d)
    known = deduped
    have = [_key(d.get("company")) for d in known]
    for proj in SELECTED_PLEDGE_PROJECTS:
        if any(_same(_key(proj["project"]), h) for h in have):
            continue
        known.append({"company": proj["project"], "sector": proj["sector"],
                      "value": proj["value"] or ""})
        log.append(f"pledge project restored: {proj['project']}")
    pkg["known_deals"] = known
    return log


# The provocations database (databases.fetch_nk_provocations) gained entries
# from the brief itself only once the push read category_tag, on Oct 19 2026;
# between Jul 3 and Oct 19 it recorded nothing, though North Korea tested
# weapons in that span. A count over a window that reaches back before this
# date would understate, so provocation_window reports none for it.
PROVOCATIONS_COMPLETE_SINCE = "2026-10-19"


def kcna_trend(digest: dict, previous: dict | None, history: list | None) -> dict | None:
    """Today's KCNA watch flag against yesterday's issue and the last week.

    `previous` is the prior issue's digest; `history` the kcna_tracker day
    records, newest first. Returns None when today has no KCNA data, so the
    status line says nothing rather than something invented.
    """
    kc = digest.get("kcna_delta") if isinstance(digest.get("kcna_delta"), dict) else {}
    if not kc or kc.get("data_unavailable") or not isinstance(kc.get("watch_flag"), bool):
        return None
    out = {"watch_flag": kc["watch_flag"]}
    pk = (previous or {}).get("kcna_delta")
    if isinstance(pk, dict) and isinstance(pk.get("watch_flag"), bool) and not pk.get("data_unavailable"):
        out["prev_watch_flag"] = pk["watch_flag"]
    today = str(digest.get("date_slug") or "")[:10]
    days = [d for d in (history or []) if isinstance(d, dict) and d.get("date") and d.get("date") != today]
    if len(days) >= 6:
        week = days[:6]
        out["watch_days_week"] = sum(1 for d in week if d.get("watch_flag")) + int(kc["watch_flag"])
        out["week_days"] = len(week) + 1
    return out


def provocation_window(records: list, date_slug: str, days: int = 7) -> dict | None:
    """Provocations recorded in the `days` days ending on `date_slug`, and the latest one.

    None when the window reaches back before PROVOCATIONS_COMPLETE_SINCE or
    the database could not be read: a count from a database with a gap is
    worse than no count.
    """
    if not records or not date_slug:
        return None
    try:
        end = datetime.strptime(date_slug[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    start = end - timedelta(days=days - 1)
    if start.isoformat() < PROVOCATIONS_COMPLETE_SINCE:
        return None
    inside = [r for r in records if isinstance(r, dict)
              and start.isoformat() <= str(r.get("date", ""))[:10] <= end.isoformat()]
    return {"count": len(inside), "days": days,
            "latest": max((str(r.get("date"))[:10] for r in inside), default=None)}


def bp_changes(digest: dict, previous: dict | None) -> list[str] | None:
    """Monitored sites whose status or latest report date differs from the previous issue."""
    if not previous or not previous.get("bp_locations"):
        return None

    # Names compare with punctuation ignored. The previous issue was saved
    # after english.apply, which turns "THAAD Site — Seongju County" into
    # "THAAD Site, Seongju County"; today's draft is compared before it, so
    # an exact match reported a site unchanged since March as new reporting.
    def key(name):
        return " ".join(re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).split())
    before = {key(l.get("name")): (l.get("status"), str(l.get("last_source_date", "")))
              for l in previous.get("bp_locations") or [] if isinstance(l, dict)}
    out = []
    for l in digest.get("bp_locations") or []:
        if not isinstance(l, dict):
            continue
        now = (l.get("status"), str(l.get("last_source_date", "")))
        if key(l.get("name")) not in before or before[key(l.get("name"))] != now:
            out.append(l.get("name"))
    return out


_SILENT_FEEDS: list[str] = []


def tariff_changes(digest: dict, previous: dict | None) -> list[str] | None:
    """Sector names whose tariff rate is new or different from the previous issue."""
    if not previous:
        return None
    def _rates(d):
        tt = ((d.get("us_korea_deals") or {}).get("tariff_tracker") or {}) if isinstance(d, dict) else {}
        out = {}
        for sr in (tt.get("sector_rates") or []):
            if isinstance(sr, dict) and sr.get("sector"):
                key = " ".join(re.sub(r"[^a-z0-9 ]+", " ", str(sr["sector"]).lower()).split())
                out[key] = (str(sr.get("rate", "")).strip(), sr["sector"])
        return out
    now, before = _rates(digest), _rates(previous)
    if not before:
        return None
    return [name for key, (rate, name) in now.items()
            if key not in before or before[key][0] != rate]


def _postprocess_digest(digest_data: dict, payload: dict | None = None) -> tuple[dict, list[str]]:
    """Run dedup, deal filter, source diversity, and URL repair. Returns (digest, all_log_messages)."""
    log = []

    # Repair first — so dedup sees the canonical URLs and can detect dupes
    # between sections that previously had mangled URLs
    if payload:
        repair_log = _repair_digest_urls(digest_data, payload)
        if repair_log:
            log.append(f"\n🔧  URL repair: fixed {len(repair_log)} mismatched URL(s) by headline match:")
            log.extend(repair_log)
        # Every other URL in the digest (KCNA, imagery, ROK government, X
        # posts, trade, deals...): repaired by headline or unlinked.
        try:
            import links as _links
            link_log = _links.repair_all(digest_data, payload)
        except Exception as _e:                                 # noqa: BLE001
            link_log = [f"  link repair failed (non-fatal): {_e}"]
        if link_log:
            log.append(f"\n🔧  Link repair outside the item sections: {len(link_log)}")
            log.extend(link_log)

    notes_log = _strip_process_notes(digest_data)
    if notes_log:
        log.append(f"\n🧹  Removed {len(notes_log)} process note(s) written into reader-facing fields:")
        log.extend(notes_log)

    digest_data, dedup_log = _dedup_digest(digest_data)
    if dedup_log:
        log.append(f"\n🧹  Auto-dedup removed {len(dedup_log)} duplicate(s):")
        log.extend(dedup_log)

    deal_log = _filter_non_us_deals(digest_data)
    if deal_log:
        log.append(f"\n🧹  Filtered {len(deal_log)} non-US deal(s) from trade section:")
        log.extend(deal_log)

    diversity_log = _enforce_source_diversity(digest_data)
    if diversity_log:
        log.append(f"\n🧹  Source diversity: removed {len(diversity_log)} over-represented item(s):")
        log.extend(diversity_log)

    for label, _l in (("Analysis section", _drop_news_from_analysis(digest_data, payload)),
                      ("Leaders' quotes", _cap_leader_quotes(digest_data))):
        if _l:
            log.append(f"\n🧹  {label}: {len(_l)} change(s):")
            log.extend(_l)

    nameless_log = _drop_nameless_personnel(digest_data)
    if nameless_log:
        log.append(f"\n🧹  Dropped {len(nameless_log)} personnel entr(ies) with placeholder names:")
        log.extend(nameless_log)

    offdate_log = _drop_offdate_on_this_day(digest_data)
    if offdate_log:
        log.append(f"\n🧹  Dropped {len(offdate_log)} on_this_day entr(ies) not on today's date:")
        log.extend(offdate_log)

    for label, fn in (("Gallup spotlight", _drop_topline_spotlight),
                      ("calendar", _normalize_calendar)):
        _l = fn(digest_data)
        if _l:
            log.append(f"\n🧹  {label}:")
            log.extend(_l)
    try:
        from bp_tracker import absolutize_digest_notes
        _l = absolutize_digest_notes(digest_data)
        if _l:
            log.append("\n🧹  Location notes: relative dates made absolute:")
            log.extend(_l)
    except Exception as _e:                                     # noqa: BLE001
        log.append(f"  ⚠  location-note dates skipped: {_e}")

    return digest_data, log


def _build_index_html() -> str:
    """Generate a landing page for GitHub Pages with links to latest digest and archive."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Korea Daily Brief — CSIS Korea Chair</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    background: #f5f6f8;
    color: #333;
    min-height: 100vh;
  }
  header {
    background: #1a1f36;
    color: #fff;
    padding: 40px 32px 36px;
    text-align: center;
  }
  header .brand {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1.8px;
    color: #8a8fa8;
    margin-bottom: 8px;
  }
  header h1 {
    font-size: 30px;
    font-weight: 700;
    letter-spacing: -0.3px;
    margin-bottom: 8px;
  }
  header .subtitle {
    font-size: 15px;
    color: #9ca0b8;
    font-weight: 400;
    max-width: 520px;
    margin: 0 auto;
    line-height: 1.5;
  }
  .container {
    max-width: 640px;
    margin: 0 auto;
    padding: 40px 20px 60px;
  }
  .card-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }
  .card {
    background: #fff;
    border: 1px solid #dce0e8;
    border-radius: 10px;
    padding: 28px 24px;
    text-decoration: none;
    color: inherit;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    transition: box-shadow 0.15s, border-color 0.15s, transform 0.15s;
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
  }
  .card:hover {
    border-color: #4a7cf7;
    box-shadow: 0 4px 14px rgba(74,124,247,0.12);
    transform: translateY(-2px);
  }
  .card .icon {
    font-size: 32px;
    margin-bottom: 12px;
  }
  .card .card-title {
    font-size: 17px;
    font-weight: 600;
    color: #1a1f36;
    margin-bottom: 6px;
  }
  .card .card-desc {
    font-size: 13px;
    color: #777;
    line-height: 1.45;
  }
  @media (max-width: 500px) {
    .card-grid { grid-template-columns: 1fr; }
    header { padding: 28px 16px 24px; }
    header h1 { font-size: 24px; }
  }
</style>
</head>
<body>
<header>
  <div class="brand">CSIS Korea Chair</div>
  <h1>Korea Daily Brief</h1>
  <p class="subtitle">Daily intelligence digest covering security, diplomacy, trade, and technology on the Korean Peninsula.</p>
</header>
<div class="container">
  <div class="card-grid">
    <a class="card" href="latest.html">
      <div class="icon">&#128240;</div>
      <div class="card-title">Latest Digest</div>
      <div class="card-desc">Read today's Korea Daily Brief with the latest developments.</div>
    </a>
    <a class="card" href="archive.html">
      <div class="icon">&#128218;</div>
      <div class="card-title">Archive &amp; Search</div>
      <div class="card-desc">Browse and search all past digests by date or keyword.</div>
    </a>
    <a class="card" href="corpus.html">
      <div class="icon">&#128230;</div>
      <div class="card-title">Article Corpus</div>
      <div class="card-desc">Search every article collected &mdash; including those not published.</div>
    </a>
  </div>
</div>
</body>
</html>"""



def write_preview_pdf(digest_data: dict, out_dir: Path, date_slug: str) -> str:
    """The issue in the candidate design, full text, as digest_{date}-preview.pdf.

    Written only when a design preview goes out (DESIGN_PREVIEW_TO), so the
    preview's PDF link opens the design it was sent in. Returns the file name,
    or '' when there is no preview or the PDF could not be made. Never raises.
    """
    if not os.environ.get("DESIGN_PREVIEW_TO", "").strip():
        return ""
    try:
        import copy
        import render as _render_mod
        from make_pdf import html_to_pdf
        saved = (_render_mod.DESIGN, _render_mod.FULL_TEXT, _render_mod.PRINT)
        try:
            # PRINT: the paper layout, with web fonts (render's "Paper" block).
            _render_mod.DESIGN, _render_mod.FULL_TEXT, _render_mod.PRINT = PREVIEW_DESIGN, True, True
            html = _render_mod.render(copy.deepcopy(digest_data))
        finally:
            _render_mod.DESIGN, _render_mod.FULL_TEXT, _render_mod.PRINT = saved
        Path("preview_print.html").write_text(html, encoding="utf-8")
        try:
            day = datetime.strptime(date_slug, "%Y-%m-%d")
            when = f"{day:%A, %B} {day.day}, {day.year}"
        except ValueError:
            when = date_slug
        name = f"digest_{date_slug}-preview.pdf"
        # Not make_pdf.html_from_input: its print CSS lets everything break
        # anywhere, which would undo the paper layout's rule that an item
        # never splits across pages.
        # A running header from page 2 (the masthead says it on page 1) and
        # a footer with the page count; both in make_pdf.
        html_to_pdf(html, out_dir / name, footer="For internal use only",
                    header=("Korea Daily Brief", f"CSIS Korea Chair {when}"),
                    margin=_render_mod._V2_PRINT_MARGIN, wait_for_fonts=True,
                    scale=_render_mod._V2_PRINT_SCALE)
        return name
    except Exception as e:                                      # noqa: BLE001
        warn("Preview PDF skipped", f"the design preview's PDF link will open the list's PDF: {e}")
        return ""


def send_design_preview(digest_data: dict, send_fn, lead: str = "", pdf_url: str = "") -> list:
    """Send the same issue in the candidate design to DESIGN_PREVIEW_TO only.

    A trial of a new layout against real issues, read side by side with the
    live one, without the list seeing it. Same digest, same audio link; only
    render.DESIGN differs. Returns the addresses it went to; empty when the
    variable is unset or the candidate is already live. Never raises.
    """
    to = [a.strip() for a in re.split(r"[,;\s]+", os.environ.get("DESIGN_PREVIEW_TO", "")) if "@" in a]
    if not to:
        return []
    try:
        import copy
        import render as _render_mod
        from send_email import build_subject
        if _render_mod.DESIGN == PREVIEW_DESIGN:
            return []
        saved = _render_mod.DESIGN
        try:
            _render_mod.DESIGN = PREVIEW_DESIGN
            _d = copy.deepcopy(digest_data)
            if pdf_url:
                # The preview's PDF link opens the preview's own PDF, not the list's.
                _d["_pdf_url"] = pdf_url
            preview = minify_email_html(_render_mod.render(_d))
        finally:
            _render_mod.DESIGN = saved
        subject = "[Design preview] " + build_subject(digest_data.get("re_line"), lead)
        send_fn(preview, subject=subject, recipients=to)
        print(f"  🎨  Design preview ({PREVIEW_DESIGN}, {len(preview.encode('utf-8')):,} bytes) "
              f"sent to {len(to)} address(es)")
        return to
    except Exception as e:                                      # noqa: BLE001
        print(f"  ⚠  Design preview skipped (non-fatal): {e}")
        warn("Design preview not sent", str(e))
        return []

def main():
    parser = argparse.ArgumentParser(description="Korea Daily Brief pipeline")
    parser.add_argument("--no-send",    action="store_true", help="Render to file only, do not send email")
    parser.add_argument("--send-to",    metavar="EMAIL", default="",
                        help="Test send: deliver to these addresses only "
                             "(comma-separated) instead of the distribution "
                             "list. Use to prove a new mail path before the "
                             "list is anywhere near it.")
    parser.add_argument("--from-cache", action="store_true", help="Skip collection, use existing collected.json")
    parser.add_argument("--dry-run",    action="store_true", help="Collect only, don't call Claude")
    parser.add_argument("--no-push",    action="store_true", help="Skip pushing new entries to NK-Russia/provocations databases")
    args = parser.parse_args()

    print("=" * 60)
    print("  Korea Daily Brief")
    print("  CSIS Korea Chair")
    from zoneinfo import ZoneInfo
    print(f"  {datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d %-I:%M %p ET')}")
    print("=" * 60)

    # ── Step 1: Collect ───────────────────────────────────────────────────────
    if args.from_cache and Path("collected.json").exists():
        print("\n📦  Using cached collection (collected.json)")
        payload = json.loads(Path("collected.json").read_text())
        total = sum(len(v) for v in payload.values() if isinstance(v, list))
        print(f"  {total} articles loaded from cache")
    else:
        from collect import collect
        payload = collect()
        Path("collected.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    # Feed health. collect() has always computed this and nothing ever read it,
    # so a feed could rot for months without anyone noticing. Printing it puts
    # the numbers in the run log, which is where a failure gets diagnosed.
    _health = (payload or {}).get("source_health") or {}
    if _health:
        _total = _health.get("total_feeds", 0)
        _ok = _health.get("feeds_with_data", 0)
        print(f"\n📡  Feeds: {_ok}/{_total} returned articles")
        _empty = sorted(name for name, h in (_health.get("per_source") or {}).items()
                        if not h.get("success"))
        if _empty:
            print(f"    Silent: {', '.join(_empty[:25])}"
                  + (f" (+{len(_empty) - 25} more)" if len(_empty) > 25 else ""))
        if _total and _ok / _total < 0.5:
            print(f"    ⚠  Under half the feed list returned anything — "
                  f"check for a Google News block before trusting this issue.")
            warn("Thin collection", f"only {_ok}/{_total} feeds returned articles; "
                 f"check for a Google News block before trusting this issue")

        # Not a failure: the collector leaves current Google News IDs encoded
        # on purpose, and the link pass decodes the few that reach the brief
        # (links.decode_digest_links). The old wording ("could not be
        # decoded") read as a fault every run.
        _unres = (payload or {}).get("unresolved_url_count") or 0
        if _unres:
            print(f"    {_unres} collected link(s) are Google News redirects; "
                  f"those that reach the brief are decoded in the final link pass")

        # Silence across runs is what separates a dead feed from a quiet one.
        # Not on --from-cache: the same collection recorded twice would count
        # every silent feed as silent for one more run than it was.
        try:
            if args.from_cache:
                raise RuntimeError("--from-cache: this collection is not a new run")
            import feed_health
            for _line in feed_health.update_and_report(
                    _health.get("per_source") or {},
                    (payload or {}).get("feed_source_used") or {}):
                print(f"    {_line}")
                _SILENT_FEEDS.append(_line)
        except Exception as _e:
            print(f"    (feed health unavailable: {_e})")

    # Nothing to write from. The model would be asked for a brief with no
    # articles, which is exactly when it is tempted to answer from memory.
    _tier1_n = len((payload or {}).get("tier1") or [])
    if _tier1_n < 20:
        warn("Very thin collection", f"only {_tier1_n} tier-1 articles collected; "
             f"the brief will be short or fail validation")

    _gallup_age = gallup_baseline_age_days()
    if _gallup_age is not None and _gallup_age > 14:
        warn("Gallup baseline stale", f"the stored Gallup Korea baseline is {_gallup_age} days "
             f"old; if today's scrape found no poll the brief shows that one. Check the "
             f"weekly Gallup update.")

    if args.dry_run:
        print("\n  --dry-run: stopping after collection. See collected.json")
        return

    # ── Step 1b: Fetch CSIS databases for context ─────────────────────────────
    from databases import fetch_all, build_context_block, process_digest_entries
    print("\n📚  Loading CSIS databases...")
    # Context only. A failure here costs the model its NK-Russia and
    # provocations background, not the morning's brief.
    try:
        databases = fetch_all()
        db_context = build_context_block(databases)
        # fetch_all returns an empty list for a source it could not read and
        # says so only in the log, so a database could drop out of the prompt
        # for weeks. Both are expected to hold hundreds of records.
        _empty_db = [k for k in ("nk_russia_timeline", "nk_provocations")
                     if not (databases or {}).get(k)]
        if _empty_db:
            warn("CSIS database empty", f"{', '.join(_empty_db)} returned nothing; the brief "
                 f"is written without that background (check the source: the NK-Russia Google "
                 f"Sheet's link sharing, or the provocations repository URL)")
    except Exception as _e:                                     # noqa: BLE001
        databases, db_context = {}, ""
        warn("CSIS databases unavailable", f"brief written without database context: {_e}")

    # ── Step 1c: Recent-coverage context from the article corpus ───────────────
    # Best-effort: feed the last week of already-published stories back to the
    # model so it can cite precedent and avoid re-leading with old news. Any
    # failure (no corpus yet, network) degrades silently to today's behavior.
    recent_coverage = ""
    recent_urls: set = set()
    try:
        from corpus import (fetch_recent_index, build_recent_coverage_block,
                            PAGES_CORPUS_BASE)
        _web = os.environ.get("WEB_URL", "").rstrip("/")
        _base = f"{_web}/corpus" if _web else PAGES_CORPUS_BASE
        _local = Path("public/corpus") if Path("public/corpus").exists() else None
        _idx = fetch_recent_index(base_url=_base, n_days=14, local_dir=_local)
        recent_coverage = build_recent_coverage_block(_idx, n_days=7)
        recent_urls = {(r.get("url") or "").strip() for r in _idx
                       if str(r.get("date", "")) >= (datetime.now(ZoneInfo("America/New_York"))
                                                      - timedelta(days=7)).strftime("%Y-%m-%d")}
        if recent_coverage:
            print(f"  🔁  Recent coverage: {len(recent_coverage.splitlines())} prior stories "
                  f"in context, {len(recent_urls)} URLs for cross-day dedup")
        _today_slug = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        _n_rep = drop_recently_used_analysis(payload, _idx, _today_slug)
        if _n_rep:
            print(f"  🔁  Dropped {_n_rep} analysis/Hill piece(s) a brief already ran this week")
    except Exception as e:
        print(f"  ⚠  Recent-coverage context skipped (non-fatal): {e}")
        warn("Recent coverage skipped", f"no cross-day dedup this run: {e}")

    # ── Step 2: Generate digest via Claude (with validation retry) ──────────
    from digest import generate_digest, regenerate_digest
    MAX_VALIDATION_RETRIES = 2
    digest_data = generate_digest(payload, db_context=db_context,
                                  recent_coverage=recent_coverage)

    # Auto-strip duplicates, filter deals, enforce source diversity, repair URLs
    digest_data, pp_log = _postprocess_digest(digest_data, payload=payload)
    for msg in pp_log:
        print(msg)

    # ── Step 1d: Verification pass — adversarial re-read of the failure-prone
    # analysis sections (op-eds, academic). Drops stale/evergreen pieces a date
    # filter can't catch (an old AEI essay, a 2021 THAAD paper). Best-effort:
    # a verification failure never removes content that passed generation.
    try:
        from verify import verify_stale_analysis
        _vdate = datetime.now(ZoneInfo("America/New_York")).strftime("%A, %B %-d, %Y")
        vlog = verify_stale_analysis(digest_data, _vdate)
        if vlog:
            print(f"\n🔎  Verification pass dropped {len(vlog)} stale analysis item(s):")
            for m in vlog:
                print(m)
    except Exception as e:
        print(f"  ⚠  Verification pass skipped (non-fatal): {e}")

    # ── Step 1e: DPRK facility-alert verification — the highest-stakes check.
    # An ELEVATED/ALERT facility note that invents an event (e.g. a fabricated
    # seismic-event/nuclear-test claim) is reverted to the last-verified tracker
    # state. Checked against today's articles + the tracker's prior note.
    try:
        from verify import verify_bp_alerts
        from bp_tracker import _load as _bp_load
        _arts = []
        for _tk in ("tier1", "tier4", "tier2"):
            for _a in (payload.get(_tk) or []):
                _arts.append(f"{_a.get('title','')} — {_a.get('summary','')}")
        _tracker_map = (_bp_load().get("locations") or {})
        blog = verify_bp_alerts(digest_data, "\n".join(_arts), _tracker_map)
        if blog:
            print(f"\n🔎  Facility-alert verification corrected {len(blog)} unsupported alert(s):")
            for m in blog:
                print(m)
    except Exception as e:
        print(f"  ⚠  Facility-alert verification skipped (non-fatal): {e}")

    Path("digest.json").write_text(json.dumps(digest_data, ensure_ascii=False, indent=2))

    # ── Step 2+: Update trackers (Kim, KCNA, BP, Tension) ──────────────────
    from kim_tracker import update_from_digest
    from kcna_tracker import update_from_digest as kcna_update_from_digest
    from bp_tracker import update_from_digest as bp_update_from_digest

    validation_passed = False
    for validation_attempt in range(1 + MAX_VALIDATION_RETRIES):
        # The generation message reports the word count before cleanup, and
        # cleanup then drops items: duplicates, articles whose URL could not be
        # repaired, placeholder names, off-date entries. One run printed 2,359
        # words at generation and 1,689 at validation, which reads like a bug
        # in one of the counters. Both were right; 670 words had been removed
        # in between. Saying so turns a confusing gap into a diagnostic — a
        # large drop means the model is producing a lot the pipeline rejects.
        _words_now = _count_digest_words(digest_data)
        _words_gen = digest_data.get("_words_at_generation")
        if isinstance(_words_gen, int) and _words_gen > _words_now:
            _lost = _words_gen - _words_now
            print(f"  🧮  Cleanup removed {_lost} words ({_words_gen} generated, "
                  f"{_words_now} after dedup and URL repair"
                  + (f" — {100*_lost/_words_gen:.0f}% of the brief)" if _words_gen else ")"))

        # ── Step 2a: Pre-send validation gate ─────────────────────────────────
        validation_warnings = validate_digest(digest_data, payload=payload)
        critical_warnings = [w for w in validation_warnings if "CRITICAL" in w]
        # A scale flag earns a regeneration, but on the last attempt it does
        # not stop the brief: a heuristic should never cost a day's issue.
        if validation_attempt >= MAX_VALIDATION_RETRIES:
            critical_warnings = [w for w in critical_warnings if not w.startswith("MAGNITUDE")]
            if any(w.startswith("FABRICATED") for w in critical_warnings):
                for _line in drop_unsourced_items(digest_data, payload):
                    print(f"  🧹  {_line}")
                critical_warnings = [w for w in critical_warnings if not w.startswith("FABRICATED")]
            _wc = _count_digest_words(digest_data)
            if _wc >= FINAL_ATTEMPT_MIN_WORDS and any(w.startswith("WORD COUNT CRITICAL") for w in critical_warnings):
                critical_warnings = [w for w in critical_warnings if not w.startswith("WORD COUNT CRITICAL")]
                warn("Brief sent short", f"{_wc} words after the last attempt, under the "
                     f"{MIN_DIGEST_WORDS} target; sent rather than held")

        # Don't retry for DUPLICATE TOPIC issues — dedup already handled them,
        # and retrying just causes dedup to fight the retry loop.
        #
        # Everything else the operator was shown is sent, not just the subset
        # whose text happens to contain "CRITICAL". That filter is why the
        # 13 September brief failed three times in a row: the model was told
        # only "~1531 words, hard minimum 1600" while the two warnings that
        # explained the shortfall — a source appearing eight times against a
        # cap of three, and an item with no body — were held back. It added
        # text, duplicated the same Yonhap articles across sections again,
        # and lost more each round: 26%, then 32%, then 21% of the draft.
        # The retry gate stays on the CRITICAL subset; only the feedback widens.
        # "Over the ceiling" is handled by length_budget after validation. Sent
        # as feedback it made the model cut hard: on 21 Oct the retry fell
        # from 2,676 words to 1,194 and the brief was held for being short.
        retryable_warnings = [w for w in validation_warnings
                              if "DUPLICATE TOPIC" not in w and "over the prompt's" not in w]

        if not critical_warnings:
            # Passed — print any non-critical warnings and move on
            if validation_warnings:
                print("\n⚠️  PRE-SEND VALIDATION WARNINGS (non-critical):")
                for w in validation_warnings:
                    print(f"    • {w}")
                print()
            else:
                print("\n✅  Validation passed — all checks OK")
            validation_passed = True
            break

        if not retryable_warnings:
            # Only duplicate topic warnings remain — dedup handled what it could
            print("\n⚠️  Remaining warnings are duplicate-topic only (auto-dedup applied):")
            for w in critical_warnings:
                print(f"    • {w}")
            # Downgrade these so they don't block sending
            validation_passed = True
            break

        # Critical failures found
        print(f"\n⚠️  VALIDATION ATTEMPT {validation_attempt + 1}/{1 + MAX_VALIDATION_RETRIES} — CRITICAL WARNINGS:")
        for w in validation_warnings:
            print(f"    • {w}")

        if validation_attempt < MAX_VALIDATION_RETRIES:
            # Retry only the digest generation, passing validation feedback
            print("\n🔄  Re-generating digest with validation feedback (reusing collected articles)...")
            digest_data = regenerate_digest(
                payload, digest_data, retryable_warnings, db_context=db_context,
                attempt=validation_attempt, recent_coverage=recent_coverage,
                cleanup_log=pp_log
            )
            # Post-process again after regeneration (incl. URL repair)
            digest_data, pp_log = _postprocess_digest(digest_data, payload=payload)
            for msg in pp_log:
                print(f"  {msg}")
            Path("digest.json").write_text(json.dumps(digest_data, ensure_ascii=False, indent=2))
        else:
            print("\n🚫  CRITICAL validation failures after all retries — newsletter will NOT be sent.")
            print("    Fix the issues above or re-run. HTML still rendered for review.")
            _crit = "; ".join(critical_warnings)[:600].replace("\n", " ")
            print(f"::error title=Brief not sent::critical validation failures after "
                  f"{1 + MAX_VALIDATION_RETRIES} attempts: {_crit}")

    # A test send proves a mail path; it is not an edition. It must leave the
    # published record untouched — otherwise proving that CSIS SMTP works
    # consumes an issue number, advances the trackers a day, and makes the
    # real brief look like it already went out.
    _is_test_send = bool((getattr(args, "send_to", "") or "").strip())
    if _is_test_send:
        print("  🧪  Test send: archive, trackers and metrics will not be written.")

    # Only update trackers if digest passed validation (avoid corrupting state)
    if validation_passed and not _is_test_send:
        # Each tracker is state for tomorrow's prompt, not part of today's
        # brief. One that raises (a corrupt file, a schema change) used to end
        # the run here, before the send.
        for _name, _update in (("Kim tracker", update_from_digest),
                               ("KCNA tracker", kcna_update_from_digest),
                               ("Facility tracker", bp_update_from_digest)):
            try:
                _update(digest_data)
            except Exception as _e:                             # noqa: BLE001
                warn(f"{_name} not updated", str(_e))
        _sent_log = _maybe_persist_sentiment_baseline(digest_data)
        if _sent_log:
            print(f"  📊  Gallup baseline auto-updated from today's digest -> {_sent_log}")
    else:
        print("  ⚠  Skipping tracker updates due to critical validation failures")

    # ── Step 2b: Push flagged entries to databases ────────────────────────────
    if not args.no_push and validation_passed and not _is_test_send:
        try:
            push_summary = process_digest_entries(digest_data)
        except Exception as _e:                                 # noqa: BLE001
            push_summary = {}
            warn("Database push failed", str(_e))
        if push_summary.get("nk_russia_added") or push_summary.get("provocations_added"):
            print(f"    NK-Russia: {push_summary.get('nk_russia_added', 0)} added, "
                  f"Provocations: {push_summary.get('provocations_added', 0)} added")
    else:
        print("\n  --no-push: skipping database updates")

    # ── Step 3: Render HTML ──────────────────────────────────────────────────
    # Upcoming hearings come from the committee schedules, not from the model,
    # so they are attached here as collected. Empty when every schedule failed,
    # and then the brief simply has no Hill calendar line.
    digest_data["hill_calendar"] = list((payload or {}).get("hill_calendar") or [])
    print("  " + hill_calendar_log_line(payload))
    # Raw logs are not kept, so an empty calendar was unexplained for days.
    # Say why on the run page when no schedule produced a single meeting.
    _hstats = (payload or {}).get("hill_calendar_stats") or {}
    if _hstats and not _hstats.get("fetched"):
        warn("Hill calendar empty", hill_calendar_log_line(payload) +
             " (no meetings parsed: a recess, or a schedule format change)")
    from render import render

    # Inject web URL for "Read Online" link (set via env or GitHub Pages)
    web_base = os.environ.get("WEB_URL", "")
    if web_base:
        digest_data["web_url"] = web_base.rstrip("/") + "/latest.html"
    # The issue's own date, so its self-links (Read online, Download PDF)
    # point at that day's files rather than whatever is latest.
    digest_data["date_slug"] = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")

    # Issue number, so a reader can cite the brief in a footnote. Derived from
    # the archive manifest rather than a counter, so it stays correct across
    # re-runs: a re-run of an issue already in the manifest reuses its number
    # instead of advancing past it.
    _date_slug = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    _archive_entries, _archive_ok = load_archive_entries(
        Path("public") / "archive.json", os.environ.get("WEB_URL", ""))
    # archive_seed.json is a checked-in floor, rebuilt from history after the
    # manifest was wiped to one entry on 3 October. Dates the published copy
    # lacks are restored from it; dates it has win. When the archive cannot be
    # read at all, the seed still numbers the issue — it is not written, but
    # the masthead should not say "No. 1" because a fetch failed.
    _seed = []
    try:
        _seed = json.loads(Path("archive_seed.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    if _archive_ok:
        _have = {e.get("date") for e in _archive_entries}
        _restored = [e for e in _seed if e.get("date") not in _have]
        if _restored:
            print(f"  📚  Restored {len(_restored)} archive entr"
                  f"{'y' if len(_restored) == 1 else 'ies'} from archive_seed.json")
            _archive_entries = sorted(_archive_entries + _restored,
                                      key=lambda e: str(e.get("date") or ""))
        _archive_entries = backfill_archive_entries(
            _archive_entries, os.environ.get("WEB_URL", ""))
    _numbering = _archive_entries if _archive_ok else _seed
    try:
        _dates = sorted({e.get("date") for e in _numbering if e.get("date")})
        digest_data["issue_no"] = (_dates.index(_date_slug) + 1
                                   if _date_slug in _dates else len(_dates) + 1)
    except (ValueError, TypeError):
        pass

    # The ceiling, enforced before rendering. Asking the model to be shorter is
    # a preference that competes with every other instruction in the prompt and
    # loses on a heavy news day; this drops whole items from the end of the
    # weaker sections until the brief fits. Nothing is rewritten, so what
    # survives is exactly what the model wrote against its sources.
    # Trim against the count the READER is shown, not the one the digest
    # happens to expose. These are two different numbers: _count_digest_words
    # walks the JSON fields, _count_rendered_words walks the assembled body,
    # and the second runs about a quarter higher because it sees text the
    # first never visits. The ceiling governed the first while the masthead
    # printed the second, so a brief could sit inside an 8-minute budget by
    # the trimmer's reckoning and tell the reader 14 minutes — which is what
    # shipped this morning at 3,518 words against a 2,400 ceiling.
    #
    # Rendering inside the trimmer's search would be the exact fix and far too
    # slow: plan() re-counts after every dropped item. Instead render once,
    # measure the real ratio between the two counts, and trim against a
    # digest-word ceiling scaled by it. One extra render, and the number the
    # reader sees is the number that was enforced.
    # Which monitored sites have new reporting since the last issue; the brief
    # shows only those and links to the full list.
    try:
        from podcast import _previous_issue as _prev_issue
        digest_data["_bp_changes"] = bp_changes(digest_data, _prev_issue(_date_slug))
    except Exception as _e:                                     # noqa: BLE001
        digest_data["_bp_changes"] = None
        print(f"  ⚠  Location change check skipped: {_e}")
    # The Peninsula status line's KCNA trend and provocation count, from the
    # previous issue, the KCNA tracker and the provocations database: data the
    # pipeline holds, never the model's reading.
    try:
        from podcast import _previous_issue as _prev_issue
        from kcna_tracker import get_recent_days
        digest_data["_kcna_trend"] = kcna_trend(
            {**digest_data, "date_slug": _date_slug}, _prev_issue(_date_slug), get_recent_days(8))
    except Exception as _e:                                     # noqa: BLE001
        digest_data["_kcna_trend"] = None
        print(f"  ⚠  KCNA trend skipped: {_e}")
    try:
        digest_data["_provocations"] = provocation_window(
            (databases or {}).get("nk_provocations") or [], _date_slug)
    except Exception as _e:                                     # noqa: BLE001
        digest_data["_provocations"] = None
        print(f"  ⚠  Provocation count skipped: {_e}")
    # Which sector tariff rates changed since the last issue. The brief shows
    # only those; the full table lives on the trade page. None means the
    # previous issue could not be read, and then nothing is shown inline.
    try:
        from podcast import _previous_issue
        digest_data["_tariff_changes"] = tariff_changes(digest_data, _previous_issue(_date_slug))
    except Exception as _e:                                     # noqa: BLE001
        digest_data["_tariff_changes"] = None
        print(f"  ⚠  Tariff change check skipped: {_e}")
    try:
        import length_budget
        _probe = render(digest_data)
        _rendered = _count_rendered_words_of(_probe)
        _digest_words = _count_digest_words(digest_data) or 1
        _ratio = max(1.0, _rendered / _digest_words)
        _effective = int(WORD_CEILING / _ratio)
        if _rendered > WORD_CEILING:
            print(f"  📏  rendered {_rendered} words vs the {WORD_CEILING} ceiling "
                  f"({_ratio:.2f}x the digest count); trimming to {_effective} digest-words")
        for _line in length_budget.apply(digest_data, _count_digest_words, _effective):
            print(f"  {_line}")
    except Exception as _e:
        print(f"  (length budget unavailable: {_e})")
        warn("Length budget unavailable", f"the brief was not trimmed to its ceiling: {_e}")

    for _msg in _ensure_pledge_projects(digest_data):
        print(f"  🏗  {_msg}")

    # ── Final link pass ────────────────────────────────────────────────────
    # The digest is final: fix anchor text, link each outlet a top story
    # names, drop trade links to unrelated stories and repeated URLs, decode
    # the Google News redirects left, HEAD-check the rest. Bounded and
    # non-fatal; see links.py.
    try:
        import links as _links
        for _line in _links.finalize(digest_data, payload):
            print(f"  {_line}")
    except Exception as _e:                                     # noqa: BLE001
        print(f"  ⚠  Link pass skipped (non-fatal): {_e}")
        warn("Link pass skipped", f"links ship unchecked and Google News redirects "
             f"undecoded: {_e}")

    # English only on the page: Korean outlet names and labels to English,
    # Korean headlines out of source fields. Prose is reported, not rewritten.
    try:
        import english
        for _w in english.apply(digest_data):
            print(f"::warning title=Korean text in brief::{_w}")
        _banned = banned_prose(digest_data)
        if _banned:
            warn("Banned words in brief", f"{len(_banned)}: " + "; ".join(_banned[:8]))
    except Exception as _e:                                     # noqa: BLE001
        print(f"  ⚠  English pass skipped (non-fatal): {_e}")
        warn("English pass skipped", f"Korean outlet names and labels may reach the reader: {_e}")

    # The web page is not bound by Gmail's clip, so it keeps the items the
    # byte guard below drops for the email alone. Copied here, after every
    # editorial pass (length ceiling, links, English) and before the email-only
    # one; the word ceiling still applies to both.
    try:
        _web_digest = copy.deepcopy(digest_data)
    except Exception:                                           # noqa: BLE001
        _web_digest = None

    # The byte guard, before the audio is built so the listener still hears
    # the issue the reader gets. Gmail clips past 102,400 bytes; the word
    # ceiling above is a proxy for that, and this is the bound itself.
    try:
        _, _fit_log = fit_email_bytes(digest_data, render)
        for _line in _fit_log:
            print(f"  📦  {_line}")
    except Exception as _e:                                     # noqa: BLE001
        print(f"  (email size guard unavailable: {_e})")
        warn("Email size guard unavailable", f"the brief may be clipped by Gmail: {_e}")

    # ── Audio edition ──────────────────────────────────────────────────────
    # Built here, after every trim and cleanup, so the listener hears exactly
    # the issue the reader gets. Before render, so the email can carry a
    # Listen link — set only once an MP3 actually exists, never optimistically.
    # Skipped when the issue will not be sent, and on a test send, which must
    # leave no trace and should not spend on synthesis.
    _audio = None
    if validation_passed and not _is_test_send:
        try:
            import podcast
            _pub = Path("public"); _pub.mkdir(exist_ok=True)
            _audio = podcast.produce(digest_data, _pub,
                                     os.environ.get("WEB_URL", ""), _date_slug)
            if _audio:
                _wb = os.environ.get("WEB_URL", "").rstrip("/")
                if _wb:
                    digest_data["audio_url"] = f"{_wb}/digest_{_date_slug}.mp3"
                    digest_data["audio_minutes"] = max(1, round(_audio["audio_seconds"] / 60))
                    # The Listen bar opens the player page (chapters,
                    # transcript, subscribe) when one was written; otherwise
                    # it stays on the MP3.
                    if _audio.get("listen_page"):
                        try:
                            from listen import listen_url
                            digest_data["listen_url"] = listen_url(_wb, _audio["listen_page"])
                        except Exception as _le:                # noqa: BLE001
                            print(f"  ⚠  Listen link stays on the MP3: {_le}")
                print(f"  🎧  Audio: {_audio['audio_bytes']:,} bytes, "
                      f"~{_audio['audio_seconds'] // 60} min "
                      f"({_audio['tts_model']}, {_audio['tts_voice']})")
            else:
                print("  🎧  Audio: script written, no voice configured "
                      "(set ELEVENLABS_API_KEY to enable)")
        except Exception as _e:                                 # noqa: BLE001
            print(f"  ⚠  Audio skipped (non-fatal): {_e}")
            warn("Audio skipped", str(_e))
            _audio = None

    html = render(digest_data)
    # Minify before measuring, because the measurement that matters is of the
    # bytes that actually reach a mailbox. About a seventh of this brief is
    # indentation, line breaks and authoring comments, and Gmail counts every
    # one of them against the 102,400 it clips at.
    _pre_min = len(html.encode("utf-8"))
    html = minify_email_html(html)
    _post_min = len(html.encode("utf-8"))
    if _post_min < _pre_min:
        print(f"  🗜  Minified: {_pre_min:,} → {_post_min:,} bytes "
              f"(−{100 * (_pre_min - _post_min) / _pre_min:.0f}%)")
    # Backstop: the Listen bar is added after the guard ran. If that tipped
    # the email over, trim again; the audio may then carry an item the email
    # does not, which is better than a clipped email.
    # Guarded: this is measurement and trimming on an html that already
    # exists. If it raises, the untrimmed render still goes out, flagged.
    try:
        if len(html.encode("utf-8")) > EMAIL_BYTE_BUDGET:
            _html, _fit_log = fit_email_bytes(digest_data, render)
            for _line in _fit_log:
                print(f"  📦  {_line}")
            html = _html
        _final = _count_rendered_words_of(html)
        if _final > WORD_CEILING:
            print(f"  ⚠  still {_final} rendered words after trimming; the sections "
                  f"that may not be trimmed are carrying the excess")
    except Exception as _e:                                     # noqa: BLE001
        warn("Email size backstop failed", f"sending the brief as rendered: {_e}")
    for _line in check_email_size(html):
        print(f"   {'⚠' if 'CRITICAL' not in _line else '✖'}  {_line}")
        if "CRITICAL" in _line:
            warn("Email will be clipped", _line)

    # Standing trade reference page. render() stashes the blocks it moved out
    # of the daily brief; this publishes them alongside the archive so the
    # link in the brief always resolves to a current page.
    try:
        import trade_page
        _wb = ""
        if digest_data.get("web_url", "").endswith("latest.html"):
            _wb = digest_data["web_url"][:-len("latest.html")]
        trade_page.write(digest_data.get("_trade_standing_html", ""),
                         Path("public"), web_base=_wb)
        if digest_data.get("_locations_standing_html"):
            trade_page.write_locations(digest_data["_locations_standing_html"],
                                       Path("public"), web_base=_wb)
    except Exception as _e:
        print(f"  ⚠  Trade reference page skipped (non-fatal): {_e}")
        warn("Trade reference page skipped", f"the brief's link to it shows the previous copy: {_e}")


    date_slug = _date_slug
    out_path  = Path(f"digest_{date_slug}.html")
    out_path.write_text(html, encoding="utf-8")
    print(f"\n📄  HTML rendered: {out_path} ({len(html):,} bytes)")

    # Also write latest.html for convenience
    Path("latest.html").write_text(html, encoding="utf-8")

    # Archive copy for GitHub Pages. The published page is the web edition,
    # the full reference "Read online" opens; the email above is unchanged,
    # and digest_*.html / latest.html in the working directory stay the email
    # for review. latest.html on the site is the web edition as well, so the
    # Read online link lands on the same page whichever file it names.
    archive_dir = Path("public")
    archive_dir.mkdir(exist_ok=True)
    publish_assets(archive_dir)
    _web_src = _web_digest if _web_digest is not None else digest_data
    if _web_src is not digest_data:
        # Set after the copy was taken: the Listen links and the issue facts.
        for _k in ("audio_url", "audio_minutes", "listen_url", "issue_no", "web_url", "date_slug"):
            if _k in digest_data:
                _web_src[_k] = digest_data[_k]
    web_html = build_web_html(_web_src, html, date_slug,
                              _archive_entries if _archive_ok else None)
    if web_html is not html:
        print(f"  🌐  Web edition: {len(web_html):,} bytes")
    (archive_dir / "latest.html").write_text(web_html, encoding="utf-8")
    (archive_dir / f"digest_{date_slug}.html").write_text(web_html, encoding="utf-8")

    # ── Save digest JSON for weekly summaries ──────────────────────────────
    (archive_dir / f"digest_{date_slug}.json").write_text(
        json.dumps(digest_data, ensure_ascii=False), encoding="utf-8"
    )

    _preview_pdf = ""
    # ── Full-color PDF for print/download (best-effort; needs Playwright) ────
    # From the email HTML (the working-directory latest.html), not the web
    # edition: the PDF is the issue as sent.
    try:
        import shutil
        from make_pdf import html_from_input, html_to_pdf
        pdf_html = html_from_input(Path("latest.html"))
        html_to_pdf(pdf_html, archive_dir / "latest.pdf")
        shutil.copy(archive_dir / "latest.pdf", archive_dir / f"digest_{date_slug}.pdf")
        print(f"  🖨  PDF written: public/latest.pdf + public/digest_{date_slug}.pdf")
        _preview_pdf = write_preview_pdf(digest_data, archive_dir, date_slug)
        if _preview_pdf:
            print(f"  🖨  Preview PDF written: public/{_preview_pdf}")
    except Exception as e:
        print(f"  ⚠  PDF generation skipped (non-fatal): {e}")
        warn("PDF skipped", f"the brief's Download PDF link will not resolve today: {e}")

    # ── Maintain archive manifest (archive.json) ────────────────────────────
    archive_json_path = archive_dir / "archive.json"
    archive_entries = list(_archive_entries)

    # Remove any existing entry for today (idempotent re-runs)
    archive_entries = [e for e in archive_entries if e.get("date") != date_slug]

    archive_entries.append({
        "date": date_slug,
        "headline_re": digest_data.get("re_line", ""),
        "top_stories_count": len(digest_data.get("top_stories") or []),
        "word_count": digest_data.get("_word_count")
                       or _count_digest_words(digest_data),
        "url": f"digest_{date_slug}.html",
    })
    if _is_test_send:
        # The issue is rendered and reviewable on disk, but it is not an
        # edition: keeping it out of the manifest is what stops a test
        # consuming today's issue number and appearing in Past issues.
        print("  🧪  Test send: archive manifest left unchanged.")
    elif _archive_ok:
        # Was "_archive_ok or not archive_json_path.exists()". public/ starts
        # empty on every runner, so the second half was always true and the
        # guard passed on exactly the runs it existed to stop: any failed read
        # wrote a one-entry stub over the published history. A new archive is
        # now detected positively, by the branch having no manifest, not by the
        # absence of a local file that is always absent.
        archive_entries.sort(key=lambda e: str(e.get("date") or ""))
        archive_json_path.write_text(
            json.dumps(archive_entries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  📚  Archive manifest: {len(archive_entries)} issues")
    else:
        # The published history could not be read, so publishing a manifest
        # built without it would delete every prior issue from the archive
        # page. Today's digest_*.html is still deployed and keep_files keeps
        # the rest; only the index is skipped, and the next healthy run
        # rebuilds it.
        print("  ⚠  Archive manifest NOT written — prior issues could not be "
              "read, and overwriting would drop them from the archive page")
        warn("Archive manifest not written", "the published archive.json could not be read; "
             "today's issue is published but not listed until the next healthy run")

    # ── Persistent article corpus ──────────────────────────────────────────
    # Record every collected article (not just the ~15-30 that shipped) as a
    # permanent audit/analytics/grounding record. Non-fatal: a corpus failure
    # must never block a digest that already sent.
    try:
        if _is_test_send:
            raise RuntimeError("test send: the corpus records editions only")
        from corpus import save_corpus
        corpus_counts = save_corpus(payload, digest_data, date_slug, archive_dir,
                                    recent_urls=recent_urls)
        print(f"  🗄️  Corpus: {corpus_counts['total']} articles recorded "
              f"({corpus_counts['used_in_digest']} shipped, "
              f"{corpus_counts['dup_of_recent']} seen in last 7 days)")
    except Exception as e:
        print(f"  ⚠  Corpus write failed (non-fatal): {e}")
        if not _is_test_send:
            warn("Corpus write failed", str(e))

    # ── Landing page and archive page for GitHub Pages ─────────────────────
    (archive_dir / "index.html").write_text(_build_index_html(), encoding="utf-8")
    import shutil
    # corpus.html is still a static template. archive.html is now generated
    # from the same module the other three editions use, so the four share one
    # layout and one search rather than four pages that drifted apart.
    for _tpl in ("corpus.html",):
        _src = Path(__file__).parent / "templates" / _tpl
        if _src.exists():
            shutil.copy2(_src, archive_dir / _tpl)
    # archive.html lists every issue, so it is an accumulating file under the
    # same rule as archive.json: built only from a manifest whose history was
    # read. It used to be built from whatever archive_entries held, which on a
    # failed read was today alone, and the deploy then replaced the published
    # page with a one-issue list. A test send is not an edition and is not
    # listed either. Skipping it leaves yesterday's page in place.
    if _archive_ok and not _is_test_send:
        try:
            import archive_page
            (archive_dir / "archive.html").write_text(
                archive_page.build(archive_entries, title="Korea Daily Brief",
                                   chair="CSIS Korea Chair", accent="#167EFF",
                                   latest_href="latest.html", prefix="digest_"),
                encoding="utf-8")
        except Exception as _e:                                 # noqa: BLE001
            print(f"  ⚠  Archive page skipped (non-fatal): {_e}")
            warn("Archive page skipped", str(_e))
            _src = Path(__file__).parent / "templates" / "archive.html"
            if _src.exists():
                shutil.copy2(_src, archive_dir / "archive.html")

    # ── Step 4: Send email ───────────────────────────────────────────────────
    if not validation_passed:
        print("\n🚫  Skipping email due to critical validation failures. Review latest.html.")
        import sys
        sys.exit(1)
    elif args.no_send:
        print("\n  --no-send: skipping email. Open latest.html to review.")
    else:
        # A test send names its own recipients and never touches the list. The
        # point is to prove a mail path — a new SMTP server, a changed From —
        # against a real issue without nineteen people receiving the proof.
        _test_to = [a.strip() for a in (args.send_to or "").split(",") if a.strip()]
        if not _test_to and not os.environ.get("DIGEST_TO"):
            print("\n⚠️  DIGEST_TO not set — email will only go to sender's own address")
        from send_email import send
        re_line = digest_data.get("re_line")
        # The lead story is the subject line's best asset: it is the one thing
        # that tells a reader at 6 AM whether to open this now.
        _top = (digest_data.get("top_stories") or [{}])[0]
        _lead = (_top.get("headline") or "").strip() if isinstance(_top, dict) else ""
        if _test_to:
            print(f"\n🧪  TEST SEND — {', '.join(_test_to)} only, not the list.")
            send(html, re_line=re_line, lead=_lead, recipients=_test_to)
        else:
            send(html, re_line=re_line, lead=_lead)
            _wb = os.environ.get("WEB_URL", "").rstrip("/")
            send_design_preview(digest_data, send, _lead,
                                pdf_url=f"{_wb}/{_preview_pdf}" if _wb and _preview_pdf else "")

    # ── Step 5: Pipeline health checks ─────────────────────────────────────
    health_report = {}
    try:
        from pipeline_health import run_health_checks
        health_report = run_health_checks(digest_data, payload)
    except Exception as e:
        print(f"  ⚠  Health checks failed to run: {e}")
        warn("Health checks failed to run", str(e))

    # Widely covered stories the brief may have missed, and what each feed
    # delivered. Published as coverage.json; a report, never a gate.
    _coverage = {}
    if validation_passed and not _is_test_send:
        try:
            import coverage_audit
            _coverage = coverage_audit.run(payload or {}, digest_data, Path("public"), _date_slug,
                                           silent_feeds=_SILENT_FEEDS)
        except Exception as _e:                                 # noqa: BLE001
            print(f"  ⚠  Coverage audit skipped (non-fatal): {_e}")

    # ── Step 6: Log quality metrics ────────────────────────────────────────
    try:
        metrics = {
            "date": date_slug,
            "word_count": digest_data.get("_word_count")
                       or _count_digest_words(digest_data),
            "top_stories": len(digest_data.get("top_stories") or []),
            "overnight_items": len(digest_data.get("overnight_items") or []),
            "business_economy": len(digest_data.get("business_economy") or []),
            "northeast_asia": len(digest_data.get("northeast_asia") or []),
            "capitol_hill": len(digest_data.get("capitol_hill") or []),
            "korea_world": len(digest_data.get("korea_world") or []),
            "opeds": len(digest_data.get("opeds_today") or []),
            "academic": len(digest_data.get("academic_today") or []),
            "statements": len(digest_data.get("social_statements") or []),
            "tier1_input": len(payload.get("tier1", [])),
            "tier4_input": len(payload.get("tier4", [])),
            "kcna_articles": (payload.get("kcna_summary") or {}).get("total_articles", 0),
            "validation_warnings": len(validation_warnings),
            "validation_retries": validation_attempt,
            "html_bytes": len(html),
            # Audio is recorded so its cost shows up with everything else's.
            **({k: v for k, v in (_audio or {}).items()}),
            "sent": not args.no_send and validation_passed,
            "health_alerts": len(health_report.get("alerts", [])),
            "health_warnings": len(health_report.get("warnings", [])),
            **_coverage,
            "recent_coverage_lines": len(recent_coverage.splitlines()) if recent_coverage else 0,
        }
        try:
            from digest import get_run_usage
            usage = get_run_usage()
            metrics.update(usage)
            if usage["api_calls"]:
                print(f"  💰  Est. API cost this run: ${usage['est_cost_usd']:.2f} "
                      f"({usage['api_calls']} calls, {usage['input_tokens']:,} in / "
                      f"{usage['output_tokens']:,} out)")
        except Exception:
            pass
        metrics_path = Path("metrics.jsonl")
        if _is_test_send:
            print("  🧪  Test send: no metrics row written.")
        else:
            with open(metrics_path, "a") as f:
                f.write(json.dumps(metrics, default=str) + "\n")
    except Exception as _e:                                     # noqa: BLE001
        # Was a bare pass. This row is the only record of the day's API spend
        # and the weekly cost sheet reads nothing else.
        warn("Run metrics not recorded", f"today's API cost is missing from metrics.jsonl: {_e}")

    print("\n✅  Done.\n")


if __name__ == "__main__":
    main()
