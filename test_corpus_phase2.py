"""
Deterministic tests for Phase 2 (semantic corpus archive + search).

Cover the risky, model-free logic: int8 vector quantization round-trip and the
cosine ranking core. The real end-to-end (save_corpus writes a vector sidecar ->
corpus_search finds the right article) is exercised by the opt-in smoke run in
the commit notes / memo, since it downloads a model.

Run:  python test_corpus_phase2.py
"""
from embeddings import cosine, dequantize, quantize
from corpus_search import rank


def test_quantize_roundtrip_preserves_cosine():
    vec = [((i * 37) % 101 - 50) / 50.0 for i in range(128)]
    back = dequantize(quantize(vec))
    assert len(back) == len(vec)
    c = cosine(vec, back)
    assert c >= 0.99, f"int8 round-trip cosine too low: {c}"
    print(f"PASS  quantize round-trip cosine {c:.4f} (>=0.99)")


def test_quantize_is_compact():
    s = quantize([0.02] * 768)
    assert len(s) < 1100, f"768-dim vector packed unexpectedly large: {len(s)}"
    print(f"PASS  768-dim vector packs to {len(s)} base64 chars (~1 KB)")


def test_rank_orders_by_cosine_and_attaches_meta():
    vectors = {"a": [1, 0, 0], "b": [0.9, 0.1, 0], "c": [0, 1, 0]}
    meta = {"a": {"title": "A"}, "b": {"title": "B"}, "c": {"title": "C"}}
    res = rank([1, 0, 0], vectors, meta, top=3)
    urls = [u for _, u, _ in res]
    assert urls == ["a", "b", "c"], urls
    assert res[0][2]["title"] == "A", "meta row must be attached to each hit"
    assert res[0][0] >= res[1][0] >= res[2][0], "scores must be descending"
    print(f"PASS  rank orders by cosine: {[(round(s, 3), u) for s, u, _ in res]}")


def test_rank_respects_top_k():
    vectors = {str(i): [1, i / 100.0, 0] for i in range(10)}
    res = rank([1, 0, 0], vectors, {}, top=3)
    assert len(res) == 3
    print("PASS  rank respects top-k")


if __name__ == "__main__":
    test_quantize_roundtrip_preserves_cosine()
    test_quantize_is_compact()
    test_rank_orders_by_cosine_and_attaches_meta()
    test_rank_respects_top_k()
    print("\nAll Phase 2 deterministic tests passed.")
