"""
X (Twitter) signal scraper via twitterapi.io.

Pulls recent posts from a CURATED ALLOWLIST of authoritative Korea-relevant
accounts (ROK presidential office, ministries, politicians; US officials such
as the ambassador) and returns them as UNCORROBORATED SIGNALS — tips for the
model, never a source of record. SOURCE-OR-SKIP still applies downstream: a
tweet may point the brief at something, but a claim must be confirmed by a real
article before it ships.

Best-effort by design: if no API key is set, or any request fails, this returns
[] and never blocks the pipeline.

CONFIG:
  - API key: set one of TWITTERAPI_KEY / TWITTERAPI_IO_KEY / X_SCRAPER_KEY.
  - Handles: edit X_ACCOUNTS below. VERIFY every handle — a wrong handle scrapes
    the wrong account. Remove the "verify": True flag once you've confirmed one.
"""
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import requests

_API_ENDPOINT = "https://api.twitterapi.io/twitter/user/last_tweets"
_KEY_ENV_NAMES = ("TWITTERAPI_KEY", "TWITTERAPI_IO_KEY", "X_SCRAPER_KEY")


def _api_key():
    for name in _KEY_ENV_NAMES:
        v = os.environ.get(name)
        if v:
            return v
    return None


# ── CURATED ALLOWLIST ────────────────────────────────────────────────────────
# {handle (no @), display name}. "verify": True = handle not yet confirmed by a
# human; it is STILL scraped, but flag it in the log so you don't trust a wrong
# account. Confirm each handle on x.com, fix as needed, then drop the flag.
X_ACCOUNTS = {
    "ROK Presidential / Government": [
        {"handle": "the_blue_house", "name": "ROK Presidential Office", "verify": True},
        {"handle": "Jaemyung_Lee", "name": "President Lee Jae-myung", "verify": True},
    ],
    "ROK Ministries": [
        {"handle": "mofa_kr", "name": "ROK Ministry of Foreign Affairs", "verify": True},
        {"handle": "ROK_MND", "name": "ROK Ministry of National Defense", "verify": True},
        {"handle": "unikoreagov", "name": "ROK Ministry of Unification", "verify": True},
    ],
    "ROK Politicians": [
        # Major party leadership — fill in / confirm current handles.
        {"handle": "", "name": "Democratic Party leader", "verify": True},
        {"handle": "", "name": "People Power Party leader", "verify": True},
    ],
    "US Officials": [
        {"handle": "MichelleSteelCA", "name": "Amb. Michelle Steel", "verify": True},
        {"handle": "USEmbassySeoul", "name": "US Embassy Seoul", "verify": True},
    ],
    # Optional DPRK-watcher lane (recommended earlier) — add if wanted:
    # "DPRK Watchers": [
    #     {"handle": "nknewsorg", "name": "NK News", "verify": True},
    #     {"handle": "38NorthNK", "name": "38 North", "verify": True},
    # ],
}


def _parse_twitter_date(s: str):
    if not s:
        return None
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


def _extract_tweets(data):
    """Pull the tweet list out of twitterapi.io's response, tolerating shapes."""
    if isinstance(data, dict):
        d = data.get("data")
        if isinstance(d, dict) and isinstance(d.get("tweets"), list):
            return d["tweets"]
        if isinstance(data.get("tweets"), list):
            return data["tweets"]
        if isinstance(d, list):
            return d
    if isinstance(data, list):
        return data
    return []


def _fetch_user_tweets(handle: str, key: str, hours: int, max_items: int):
    try:
        r = requests.get(_API_ENDPOINT, params={"userName": handle},
                         headers={"X-API-Key": key}, timeout=10)
        if r.status_code != 200:
            return []
        tweets = _extract_tweets(r.json())
    except Exception:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for t in tweets:
        if not isinstance(t, dict):
            continue
        text = (t.get("text") or t.get("full_text") or "").strip()
        if not text:
            continue
        created = t.get("createdAt") or t.get("created_at") or ""
        dt = _parse_twitter_date(created)
        if dt and dt < cutoff:
            continue
        tid = str(t.get("id") or t.get("id_str") or "").strip()
        url = t.get("url") or t.get("twitterUrl") or (
            f"https://x.com/{handle}/status/{tid}" if tid else f"https://x.com/{handle}")
        out.append({"text": text[:500], "url": url, "created_at": created})
        if len(out) >= max_items:
            break
    return out


def collect_x_signals(hours: int = 24, max_per_account: int = 3) -> list:
    """Fetch recent posts from the allowlist. Returns a list of signal dicts
    {handle, name, category, verify, text, url, created_at}. Never raises."""
    key = _api_key()
    if not key:
        print("  🐦  X scraper: no API key set "
              f"({' / '.join(_KEY_ENV_NAMES)}) — skipping")
        return []
    accounts = [(cat, a) for cat, lst in X_ACCOUNTS.items() for a in lst
                if (a.get("handle") or "").strip()]
    if not accounts:
        print("  🐦  X scraper: allowlist empty — skipping")
        return []
    signals = []
    unverified = 0
    try:
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(_fetch_user_tweets, a["handle"], key, hours, max_per_account): (cat, a)
                    for cat, a in accounts}
            for fut in as_completed(futs):
                cat, a = futs[fut]
                try:
                    tweets = fut.result()
                except Exception:
                    tweets = []
                for tw in tweets:
                    signals.append({"handle": a["handle"], "name": a["name"],
                                    "category": cat, "verify": bool(a.get("verify")), **tw})
                    if a.get("verify"):
                        unverified += 1
    except Exception as e:
        print(f"  🐦  X scraper: failed ({e}) — continuing without signals")
        return []
    note = f" ({unverified} from unverified handles — confirm them)" if unverified else ""
    print(f"  🐦  X scraper: {len(signals)} signals from {len(accounts)} accounts{note}")
    return signals


if __name__ == "__main__":
    import json
    print(json.dumps(collect_x_signals(), ensure_ascii=False, indent=2))
