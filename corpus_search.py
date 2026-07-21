"""
corpus_search.py — semantic search over the Korea Daily Brief article corpus.

Embeds your query with the SAME model the pipeline uses (so cross-lingual
KO<->EN matching works), then ranks every archived article by cosine similarity
against the persisted vectors (public/corpus/vectors_{YYYY-MM}.json). Full model
quality, server-side — no in-browser model required.

Usage:
  python corpus_search.py "north korea missile test"
  python corpus_search.py "한미 동맹 균열"                 --top 15
  python corpus_search.py "semiconductor export controls"  --months 2026-07,2026-06
  python corpus_search.py "kim jong un" --web https://andysaulim.github.io/Daily-Korea-Digest

Reads local public/corpus/ when present, otherwise HTTP-fetches from GitHub Pages.
The corpus accumulates vectors from the first Phase-2 run forward; older days
that predate it are searchable by keyword (corpus.html) but not semantically.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

from embeddings import cosine, dequantize, embed

LOCAL_CORPUS = Path("public/corpus")
DEFAULT_WEB = os.environ.get(
    "WEB_URL", "https://andysaulim.github.io/Daily-Korea-Digest"
).rstrip("/")


def _load_json(name: str, web: str):
    """Local-first, then HTTP GET. Returns parsed JSON or None (never raises)."""
    lp = LOCAL_CORPUS / name
    if lp.exists():
        try:
            return json.loads(lp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    try:
        r = requests.get(f"{web}/corpus/{name}", timeout=10)
        if r.status_code == 200:
            return r.json()
    except (requests.RequestException, ValueError):
        return None
    return None


def available_months(web: str = DEFAULT_WEB) -> list:
    """Months that have a vector sidecar, newest first (from the manifest)."""
    man = _load_json("manifest.json", web) or {}
    months = set()
    for d in man.get("days", []):
        v = d.get("vectors")
        if v:
            months.add(v.replace("vectors_", "").replace(".json", ""))
    return sorted(months, reverse=True)


def load_corpus(months: list, web: str = DEFAULT_WEB):
    """Return (vectors, meta): {url: float_vec} and {url: index_row}."""
    meta, vectors = {}, {}
    for m in months:
        for row in (_load_json(f"index_{m}.json", web) or []):
            u = (row.get("url") or "").strip()
            if u:
                meta.setdefault(u, row)
        for u, emb in (_load_json(f"vectors_{m}.json", web) or {}).items():
            if u:
                vectors[u] = dequantize(emb)
    return vectors, meta


def rank(query_vec, vectors: dict, meta: dict, top: int = 10) -> list:
    """Pure ranking core: cosine(query, each) -> top results as
    [(score, url, meta_row), ...]. No model or I/O — unit-testable."""
    scored = [(cosine(query_vec, v), u) for u, v in vectors.items()]
    scored.sort(key=lambda t: t[0], reverse=True)
    return [(s, u, meta.get(u, {})) for s, u in scored[:top]]


def search(query: str, top: int = 10, months=None, web: str = DEFAULT_WEB) -> list:
    months = months or available_months(web)
    if not months:
        print("No vector shards found — the corpus may predate Phase 2, or "
              "isn't deployed yet.")
        return []
    vectors, meta = load_corpus(months, web)
    if not vectors:
        print("No vectors loaded from", ", ".join(months))
        return []
    qv = embed([query])
    if not qv:
        print("Could not embed the query (embedding backend unavailable).")
        return []
    return rank(qv[0], vectors, meta, top)


def main():
    # Korean output on a non-UTF-8 Windows console would otherwise crash.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description="Semantic search over the Korea Daily Brief article corpus.")
    ap.add_argument("query", help="free-text query (English or Korean)")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--months", default=None,
                    help="comma-separated YYYY-MM to restrict the search")
    ap.add_argument("--web", default=DEFAULT_WEB,
                    help="GitHub Pages base URL for the HTTP fallback")
    args = ap.parse_args()
    months = [m.strip() for m in args.months.split(",")] if args.months else None

    results = search(args.query, top=args.top, months=months, web=args.web)
    if not results:
        return
    print(f"\nTop {len(results)} for: {args.query!r}\n")
    for score, url, row in results:
        flag = " [PUBLISHED]" if row.get("used") else ""
        print(f"  {score:.3f}  {row.get('date', '?')}  {row.get('source', '?')}{flag}")
        print(f"         {row.get('title', url)}")
        print(f"         {url}\n")


if __name__ == "__main__":
    main()
