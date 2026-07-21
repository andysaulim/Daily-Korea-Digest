# Semantic layer for the Korea Daily Brief: what we built and what we deferred

**Date:** 2026-07-21
**Branch:** `feat/semantic-dedup` (not merged; live 6 AM send is untouched)
**Author:** Andy + Claude

## Purpose

Add a free, self-hosted embedding layer to the pipeline so that three "commodity"
operations stop costing Opus tokens or manual effort: finding duplicate stories,
matching stories by meaning across languages, and searching the archive. The model
runs on CPU inside the existing GitHub Actions job. No GPU, no paid API, no server.

Model: `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` (via fastembed,
ONNX, no torch). It was chosen over the originally planned `bge-m3` for two reasons:
fastembed does not ship bge-m3 (using it would have silently disabled the feature),
and this model is purpose-built for cross-lingual paraphrase matching and is lighter
(about 1.0 GB). Similarity threshold for dedup is 0.75, tuned on real Korean/English
headline pairs (same-event pairs scored 0.79 to 0.93, different events 0.23 to 0.49).

---

## What we built

### Phase 1: semantic dedup (already committed, commit c8a1c6b)

Before the collected articles reach the digest prompt, near-duplicate stories in
tier1 (news) and tier2 (op-eds) are collapsed, including cross-lingual duplicates
(the same launch reported by Yonhap in English and 조선일보 in Korean). This shrinks
the payload Claude sees every run, so Claude is no longer paid to dedup what a free
CPU model already handled. The existing URL-exact dedup stays as the cheap first gate.

Key properties:
- Per-tier only. It never collapses across tiers, because tiers map to distinct
  digest sections (a news report and an op-ed on the same event are different
  deliverables and both should survive).
- Every drop is logged to `collected.json` under `semantic_dedup_log` for audit.
- Degrades to a no-op if the model cannot load, so an embedding failure never breaks
  the daily send.

### Phase 2: semantic archive and search (this commit)

The pipeline already keeps a permanent record of every collected article in
`corpus.py` (written to `public/corpus/` on GitHub Pages). Phase 2 gives that archive
a meaning-aware layer:

1. **Persisted vectors.** Each run now embeds every corpus article and writes a
   compact monthly sidecar, `public/corpus/vectors_{YYYY-MM}.json` (int8-quantized,
   about 1 KB per article). Vectors live only here. They never enter the daily audit
   records or the digest prompt. The write is best-effort: if it fails, the corpus
   still saves exactly as before.

2. **`corpus_search.py`, a semantic search tool.** Give it a query in English or
   Korean and it embeds the query with the same model, ranks every archived article
   by cosine similarity, and prints the best matches with date, source, title, and URL.
   It reads the local `public/corpus/` when present, otherwise fetches from GitHub
   Pages. This is full model quality with no in-browser constraints.
   Example: `python corpus_search.py "north korea missile test" --top 15`

3. **"More like this" in `corpus.html`.** The corpus page gains a small "similar"
   button on each article. Clicking it lazy-loads that month's vector sidecar and,
   entirely in the browser (no model download), shows the most similar articles from
   the same month, ranked by cosine. Verified working: for an English missile article
   it surfaced the Korean 조선일보 version first (0.88), then a related missile story
   (0.74), then joint-drills (0.49), with the interest-rate story last (0.32).

---

## Files changed

| File | Change | Phase |
|------|--------|-------|
| `embeddings.py` | Added `quantize` / `dequantize` (int8 base64) | 2 |
| `corpus.py` | `build_vectors`, `update_vectors_shard`, sidecar wired into `save_corpus`, manifest records the vector file | 2 |
| `corpus_search.py` (new) | Semantic search CLI over the archive | 2 |
| `templates/corpus.html` | Client-side "more like this" (dequantize + cosine in JS) | 2 |
| `run.py` | Corpus log line now shows the vector count | 2 |
| `test_corpus_phase2.py` (new) | Quantize round-trip and ranking tests | 2 |
| `collect.py` | Cross-lingual semantic dedup pass over tier1+tier2 | 1 |
| `requirements.txt` | Added `fastembed` (ONNX, no torch) | 1 |
| `.github/workflows/daily-digest.yml` | Cache the ONNX model across runs | 1 |
| `.gitignore` | Ignore `.fastembed_cache/` | 1 |

---

## What we did NOT do, and why

1. **Free-text semantic search inside the browser (corpus.html).**
   The plan floated upgrading the keyword search box to semantic search. Doing that in
   the browser requires embedding the user's typed query client-side, which needs the
   model loaded in the browser. Our production model is about 1 GB, far too large to
   ship to a browser. Using a small model instead would reintroduce the exact
   cross-lingual weakness we measured and rejected in Phase 1 (the small MiniLM model
   scored Korean/English duplicates at only 0.68, indistinguishable from noise).
   Instead we shipped two things that work correctly: server-side full-quality search
   (`corpus_search.py`) for free-text queries, and in-browser "more like this" that
   needs no query model because it compares stored vectors directly.
   If free-text browser search becomes a priority, the clean options are a tiny search
   endpoint that embeds the query, or accepting a small multilingual model for both
   sides at reduced cross-lingual quality.

2. **Semantic "already covered" detection for grounding.**
   The corpus currently flags `dup_of_recent` by exact URL only, so a paraphrased or
   Korean/English repeat of yesterday's story is not caught. Embeddings could flag
   these semantic echoes to help Claude avoid re-reporting. We did not wire this in
   because it touches the live daily-send path and needs a real dry-run to tune, and
   because the current grounding block is already compact (title-only lines, deduped,
   capped at 40), so the token savings are marginal. The building blocks now exist
   (recent vectors are persisted), so this is a clean follow-up when wanted.

3. **Backfill of old articles.** Vectors accumulate from the first Phase 2 run forward.
   Articles collected before deployment were never retained with full text, so they
   cannot be embedded retroactively. This matches the corpus module's existing
   "accumulates from deployment forward" behavior.

4. **Reusing Phase 1's embeddings in the corpus step.** For separation of concerns and
   to guarantee vectors never leak into the digest prompt, the corpus embeds its
   records independently rather than reusing the tier1/tier2 vectors computed during
   Phase 1 dedup. This is a second embedding pass per run. It is acceptable inside the
   25-minute budget and can be optimized later if needed.

---

## Verification performed

- Phase 1: deterministic clustering tests, real-model smoke test through the
  production code path (Korean 조선일보 headline collapsed into the English Yonhap wire
  at cosine 0.877), graceful-degradation test.
- Phase 2: quantize round-trip preserves cosine at 0.9997; 768-dim vector packs to
  about 1 KB; ranking core ordered correctly. End-to-end: `save_corpus` wrote a vector
  sidecar for 4 articles, then `corpus_search` correctly ranked an English query to the
  Korean article and a Korean query to the English article. The `corpus.html` "more
  like this" feature was verified live in a browser against a served corpus.
- All modules compile; local test model caches were cleaned up afterward.

Not yet done (needs your repo or CI, cannot run locally): a live `python run.py
--dry-run` against the 100+ real feeds, the token-delta measurement via
`cost_report.py`, and a CI timing check under the 25-minute budget.

---

## Config knobs

- `EMBED_MODEL` (env): swap the model. Default is the mpnet multilingual model.
- `DEFAULT_THRESHOLD` in `embeddings.py`: dedup aggressiveness. Raise toward 0.80 if
  you see false collapses in the `semantic_dedup_log`, lower to catch more.
- `FASTEMBED_CACHE` (env): where the ONNX model is cached. CI caches this directory.

Local Windows runs need `HF_HUB_DISABLE_SYMLINKS=1` and `PYTHONUTF8=1`. Neither
affects the Linux CI runner.

## Suggested next steps

1. Run the live dry-run and check `semantic_dedup_log` for false collapses; adjust the
   threshold if needed.
2. Measure the token delta with `cost_report.py` to confirm the Phase 1 saving.
3. If you want it, wire the semantic echo detection into grounding (item 2 above).
