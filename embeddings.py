"""
embeddings.py — multilingual embeddings for semantic dedup (Phase 1) and, later,
corpus search (Phase 2).

Backend: fastembed (ONNX Runtime, CPU, no torch).
Model:   sentence-transformers/paraphrase-multilingual-mpnet-base-v2 — purpose-
         built for cross-lingual paraphrase/semantic-similarity, so a Korean
         article (조선일보) and its English wire counterpart (Yonhap) about the
         same event collapse to one item before the digest reaches Claude.
         (bge-m3 was the original plan but fastembed doesn't ship it; this model
         is lighter — 1.0 GB — and a better fit for the dedup task.)

Threshold: 0.75, tuned empirically on real KO/EN headline pairs. Measured
         cosines: same event 0.79–0.93 (incl. cross-lingual), different events
         0.23–0.49 — a wide, safe gap. Raise toward 0.80 if false collapses
         appear on live data; lower slightly to catch more cross-lingual dups.

Design constraints (match the pipeline):
  - No GPU. Runs on ubuntu-latest inside the workflow's 25-min budget.
  - The ONNX model is cached across runs by the workflow (key: embed-model-onnx-v1)
    via FASTEMBED_CACHE, so the download happens once, not every morning.
  - Degrades gracefully: if fastembed or the model can't load, embed() returns
    None and callers fall back to the existing URL-exact dedup — the pipeline
    never breaks because of an embedding failure.
  - The clustering core (cluster_dedup / cosine) is pure-Python and dependency-
    free, so it is unit-testable without downloading the model.

Swap the model with EMBED_MODEL (e.g. paraphrase-multilingual-MiniLM-L12-v2 for
a lighter/faster run — but note it does NOT separate cross-lingual dups reliably,
so it only catches same-language duplicates). Point the cache elsewhere with
FASTEMBED_CACHE.

Local Windows note: a local run needs HF_HUB_DISABLE_SYMLINKS=1 (HF cache symlink
perms) and a UTF-8 console (PYTHONUTF8=1). Neither affects the Linux CI runner.
"""
from __future__ import annotations

import base64
import os

DEFAULT_THRESHOLD = 0.75

_MODEL_NAME = os.environ.get(
    "EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
)
_CACHE_DIR = os.environ.get("FASTEMBED_CACHE", ".fastembed_cache")

try:
    import numpy as _np
except Exception:  # numpy is pulled in by fastembed; absent only in bare test envs
    _np = None

_model = None
_load_failed = False


def _log(msg: str) -> None:
    print(f"    [embeddings] {msg}")


# ─────────────────────────────────────────────────────────────────────────────
# Model loading + encoding (production path)
# ─────────────────────────────────────────────────────────────────────────────

def get_model():
    """Lazy-load the fastembed model once per process. Returns None (and disables
    itself for the rest of the run) if the backend or model can't be loaded."""
    global _model, _load_failed
    if _model is not None:
        return _model
    if _load_failed:
        return None
    try:
        from fastembed import TextEmbedding
    except Exception as e:
        _load_failed = True
        _log(f"fastembed unavailable ({e}); semantic steps disabled")
        return None
    try:
        _model = TextEmbedding(model_name=_MODEL_NAME, cache_dir=_CACHE_DIR)
        _log(f"loaded {_MODEL_NAME}")
    except Exception as e:
        _load_failed = True
        _log(f"could not load {_MODEL_NAME} ({e}); semantic steps disabled")
        return None
    return _model


def embed(texts):
    """Return a list of L2-normalized vectors for `texts`, or None if embeddings
    are unavailable. Normalizing makes cosine == dot product downstream."""
    model = get_model()
    if model is None:
        return None
    texts = list(texts)
    if not texts:
        return []
    try:
        raw = list(model.embed(texts))
    except Exception as e:
        _log(f"embed() failed ({e}); semantic steps disabled for this run")
        return None
    out = []
    for v in raw:
        if _np is not None:
            v = _np.asarray(v, dtype="float32")
            n = float(_np.linalg.norm(v))
            out.append(v / n if n else v)
        else:  # pragma: no cover — CI always has numpy
            n = sum(x * x for x in v) ** 0.5
            out.append([x / n for x in v] if n else list(v))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Clustering core (pure-Python, unit-testable without the model)
# ─────────────────────────────────────────────────────────────────────────────

def cosine(a, b) -> float:
    """Cosine similarity. Works on numpy arrays or plain float sequences.
    Vectors from embed() are already normalized; we renormalize defensively."""
    if _np is not None:
        a = _np.asarray(a, dtype="float32")
        b = _np.asarray(b, dtype="float32")
        na = float(_np.linalg.norm(a))
        nb = float(_np.linalg.norm(b))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return float(_np.dot(a, b) / (na * nb))
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


# ─────────────────────────────────────────────────────────────────────────────
# Compact persistence: int8-quantize vectors for storage in the corpus sidecar
# ─────────────────────────────────────────────────────────────────────────────

def quantize(vec) -> str:
    """Pack a vector into base64-encoded int8 for compact, permanent storage
    (~768 bytes -> ~1 KB of base64 per article). Normalizes first; round-trips
    to within ~1e-2 cosine of the original — ample for ranking/related-articles.
    Pure-Python (no numpy) so it round-trips anywhere."""
    n = sum(x * x for x in vec) ** 0.5 or 1.0
    q = bytes((max(-127, min(127, round(x / n * 127))) & 0xFF) for x in vec)
    return base64.b64encode(q).decode("ascii")


def dequantize(s: str):
    """Inverse of quantize(): base64 int8 -> normalized float list (so cosine
    is a plain dot product)."""
    raw = base64.b64decode(s)
    vals = [b - 256 if b > 127 else b for b in raw]  # unsigned byte -> int8
    n = sum(v * v for v in vals) ** 0.5 or 1.0
    return [v / n for v in vals]


def _default_text(a: dict) -> str:
    return f"{a.get('title', '')} {a.get('summary', '')}".strip()


def _default_priority(a: dict):
    """Higher tuple = better representative to KEEP within a duplicate cluster:
    a flagged prestige journalist, then a prestige/tiered source, then the item
    with the most summary text (most context for Claude)."""
    return (
        1 if a.get("flagged_journalist") else 0,
        1 if (a.get("prestige") or a.get("journal_tier")) else 0,
        len(a.get("summary") or ""),
    )


def cluster_dedup(articles, vecs, threshold=DEFAULT_THRESHOLD, priority_fn=None):
    """Greedy near-duplicate collapse given precomputed vectors.

    Walks articles in priority order; keeps an item unless it is within
    `threshold` cosine of an already-kept item, in which case it is dropped as a
    duplicate of that item. Survivors are returned in the ORIGINAL input order.

    Returns (kept_articles, drop_log). Pure function — no model needed — so the
    clustering behaviour is unit-testable with synthetic vectors.
    """
    priority_fn = priority_fn or _default_priority
    n = len(articles)
    if n < 2:
        return list(articles), []

    order = sorted(range(n), key=lambda i: priority_fn(articles[i]), reverse=True)
    kept_idx: list[int] = []
    drop_log: list[dict] = []
    for i in order:
        dup_of, best = None, 0.0
        for k in kept_idx:
            s = cosine(vecs[i], vecs[k])
            if s >= threshold and s > best:
                best, dup_of = s, k
        if dup_of is None:
            kept_idx.append(i)
        else:
            a, b = articles[i], articles[dup_of]
            drop_log.append({
                "dropped": a.get("url") or a.get("title", ""),
                "dropped_source": a.get("source", ""),
                "kept": b.get("url") or b.get("title", ""),
                "kept_source": b.get("source", ""),
                "score": round(best, 3),
            })
    keep = set(kept_idx)
    kept = [a for j, a in enumerate(articles) if j in keep]
    return kept, drop_log


def semantic_dedup(articles, threshold=DEFAULT_THRESHOLD, text_fn=None, priority_fn=None):
    """Collapse near-duplicate articles by embedded title+summary similarity.

    If embeddings are unavailable (backend/model missing), returns the input
    unchanged with an empty log — the caller's URL-exact dedup still stands.
    """
    if len(articles) < 2:
        return list(articles), []
    text_fn = text_fn or _default_text
    vecs = embed([text_fn(a) for a in articles])
    if vecs is None:
        return list(articles), []  # graceful no-op
    return cluster_dedup(articles, vecs, threshold=threshold, priority_fn=priority_fn)
