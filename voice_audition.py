"""Audition ElevenLabs voices for the audio edition, and publish a page to pick from.

    python voice_audition.py --out public [--count 6] [--query "..."] [--voices id1,id2]

Searches the ElevenLabs voice library for the delivery the show wants — a
warm, intimate, conversational host with an unhurried, measured pace — reads
the same passage of the latest issue in each of the best matches, and writes
public/auditions/index.html with a player per voice and the ID to put in the
ELEVENLABS_VOICE_ID repository variable.

Voices presented as imitations of real people are excluded. The show should
sound like a good host, not like a particular one.

Needs ELEVENLABS_API_KEY with Text to Speech access, and Voices read (to
search) and write (to add a library voice to the account so it can be used).
A sample costs about 700 characters of credit.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import podcast

API = "https://api.elevenlabs.io/v1"

# What the search looks for. Each runs with the filters below; results merge.
QUERIES = ("warm conversational podcast host", "intimate storyteller", "calm thoughtful narrator",
           "warm documentary narrator", "news podcast host")
FILTERS = {"gender": "male", "language": "en", "accent": "american", "page_size": 30}

GOOD_DESCRIPTIVES = {"warm", "calm", "conversational", "casual", "soft", "intimate", "deep",
                     "relaxed", "pleasant", "confident", "smooth", "gentle", "thoughtful"}
GOOD_USES = {"conversational", "narrative_story", "informative_educational", "news", "podcast",
             "narration", "audiobook"}
# Anything sold as a copy of a real person or show is left out.
BLOCKED = ("barbaro", "the daily", "nyt", "new york times", "impression", "impersonat",
           "parody", "celebrity", "famous", "sounds like", "clone of", "soundalike")

FALLBACK_TEXT = ("This is the Korea Daily Brief from the CSIS Korea Chair. North Korea is "
                 "warning Seoul over its investigation into last month's mine blast in the "
                 "demilitarized zone. And three days from the Workers' Party anniversary, "
                 "Pyongyang is lining up its messages to Moscow and Beijing. Here's what you "
                 "need to know this morning.")


def _get(path: str, key: str, params: dict | None = None) -> dict:
    import requests
    r = requests.get(f"{API}{path}", headers={"xi-api-key": key}, params=params or {}, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"{path} returned {r.status_code}: {r.text[:200]}")
    return r.json()


def _blocked(v: dict) -> bool:
    text = " ".join(str(v.get(k) or "") for k in ("name", "description")).lower()
    return any(b in text for b in BLOCKED)


def _score(v: dict) -> float:
    desc = str(v.get("descriptive") or "").lower()
    use = str(v.get("use_case") or "").lower()
    text = (str(v.get("description") or "") + " " + str(v.get("name") or "")).lower()
    s = 2.0 * (desc in GOOD_DESCRIPTIVES) + 2.0 * (use in GOOD_USES)
    s += sum(0.5 for w in GOOD_DESCRIPTIVES if w in text)
    s += 0.4 * math.log10(1 + float(v.get("cloned_by_count") or 0))
    return s


def search(key: str, extra_query: str = "") -> list[dict]:
    seen: dict[str, dict] = {}
    for q in ((extra_query,) if extra_query else ()) + QUERIES:
        try:
            got = _get("/shared-voices", key, {**FILTERS, "search": q}).get("voices") or []
        except RuntimeError as e:
            print(f"  ⚠  search {q!r}: {e}")
            continue
        for v in got:
            if v.get("voice_id") and not _blocked(v):
                seen.setdefault(v["voice_id"], v)
    return sorted(seen.values(), key=_score, reverse=True)


def _usable_id(v: dict, key: str) -> str:
    """Add a library voice to the account (needed to use it by API); its usable ID."""
    import requests
    owner = v.get("public_owner_id")
    if not owner:
        return v["voice_id"]
    r = requests.post(f"{API}/voices/add/{owner}/{v['voice_id']}",
                      headers={"xi-api-key": key},
                      json={"new_name": f"KDB audition: {v.get('name', '')}"[:60]}, timeout=60)
    if r.status_code < 400:
        return r.json().get("voice_id") or v["voice_id"]
    # Already added, or no write access: the library ID often works as is.
    return v["voice_id"]


def sample_text(date_slug: str) -> str:
    from shared.published import read_from_branch
    text, _ = read_from_branch(f"digest_{date_slug}.txt")
    if not text:
        return FALLBACK_TEXT
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    out = ""
    for p in paras:
        if len(out) + len(p) > 750 and out:
            break
        out = f"{out}\n\n{p}" if out else p
    return out


def render(v: dict, key: str, text: str) -> tuple[bytes, str]:
    vid = _usable_id(v, key)
    wanted = (os.environ.get("ELEVENLABS_MODEL") or "").strip()
    last = None
    for model in ([wanted] if wanted else podcast.ELEVEN_MODELS):
        try:
            audio, _ = podcast._eleven_tts(text, key, vid, model, [])
            return audio, vid
        except RuntimeError as e:
            last = e
            if "model" not in str(e).lower():
                break
    raise last or RuntimeError("no model accepted")


def page(rows: list[dict], text: str, when: str) -> str:
    cards = []
    for r in rows:
        tags = ", ".join(x for x in (r.get("descriptive"), r.get("use_case"), r.get("age"),
                                     r.get("accent")) if x)
        cards.append(f"""
<section class="card">
  <h2>{html.escape(r['name'])}</h2>
  <p class="tags">{html.escape(tags)}</p>
  <p>{html.escape((r.get('description') or '')[:300])}</p>
  <audio controls preload="none" src="{html.escape(r['file'])}"></audio>
  <p class="id">Voice ID: <code>{html.escape(r['use_id'])}</code></p>
</section>""")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Voice Auditions</title>
<style>
:root {{ --bg:#f7f7f5; --fg:#1a1a1a; --muted:#666; --card:#fff; --line:#e3e3e0; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141414; --fg:#eee; --muted:#aaa; --card:#1e1e1e; --line:#333; }} }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.5 -apple-system,Segoe UI,Roboto,sans-serif; }}
main {{ max-width:760px; margin:0 auto; padding:24px 16px 48px; }}
h1 {{ font-size:24px; margin:0 0 4px; }} .lede {{ color:var(--muted); margin:0 0 20px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; margin:0 0 14px; }}
.card h2 {{ font-size:18px; margin:0; }} .tags {{ color:var(--muted); font-size:14px; margin:2px 0 8px; }}
audio {{ width:100%; margin:6px 0; }} code {{ font-size:14px; word-break:break-all; }}
details {{ margin-top:20px; color:var(--muted); }}
</style></head><body><main>
<h1>Voice auditions</h1>
<p class="lede">Korea Daily Brief audio edition · {html.escape(when)} · the same passage in each voice.
To choose one, add its Voice ID as the repository variable <code>ELEVENLABS_VOICE_ID</code>.</p>
{''.join(cards)}
<details><summary>The passage</summary><p>{html.escape(text).replace(chr(10)*2, '</p><p>')}</p></details>
</main></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="public")
    ap.add_argument("--count", type=int, default=6)
    ap.add_argument("--query", default="")
    ap.add_argument("--voices", default="", help="comma-separated voice IDs to audition instead of searching")
    ap.add_argument("--date", default="today")
    a = ap.parse_args()
    key = (os.environ.get("ELEVENLABS_API_KEY") or "").strip()
    if not key:
        print("::error title=No ElevenLabs key::add ELEVENLABS_API_KEY as a repository secret")
        return 1
    date_slug = datetime.now(timezone.utc).strftime("%Y-%m-%d") if a.date == "today" else a.date
    text = sample_text(date_slug)
    if a.voices.strip():
        voices = [{"voice_id": x.strip(), "name": x.strip()} for x in a.voices.split(",") if x.strip()]
    else:
        voices = search(key, a.query)
        print(f"  found {len(voices)} candidate voices")
    out = Path(a.out) / "auditions"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for v in voices:
        if len(rows) >= a.count:
            break
        slug = re.sub(r"[^a-z0-9]+", "-", str(v.get("name", "voice")).lower()).strip("-")[:40] or "voice"
        try:
            audio, use_id = render(v, key, text)
        except Exception as e:                                  # noqa: BLE001
            print(f"  ⚠  {v.get('name')}: {e}")
            continue
        fname = f"{slug}-{v['voice_id'][:6]}.mp3"
        (out / fname).write_bytes(audio)
        rows.append({**v, "file": fname, "use_id": use_id})
        print(f"::notice title=Audition {len(rows)}::{v.get('name')} | {v.get('descriptive', '')} "
              f"{v.get('use_case', '')} | ID {use_id}")
    if not rows:
        print("::error title=No auditions made::see the warnings above")
        return 1
    (out / "index.html").write_text(page(rows, text, date_slug), encoding="utf-8")
    (out / "auditions.json").write_text(json.dumps(
        [{k: r.get(k) for k in ("name", "use_id", "voice_id", "descriptive", "use_case", "age",
                                "accent", "description", "file")} for r in rows], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
