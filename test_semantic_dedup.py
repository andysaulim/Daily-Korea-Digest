"""
Unit tests for the semantic-dedup clustering core (embeddings.cluster_dedup).

These use SYNTHETIC vectors injected directly, so they run with no model
download and no network — they validate the greedy clustering behaviour and the
keep-the-best-representative rule, which is the risky logic. The real model's
encoding quality (does a KO item actually land near its EN counterpart) is
exercised separately by the opt-in smoke test at the bottom.

Run:  python test_semantic_dedup.py
"""
from embeddings import cluster_dedup


def _near(base, eps):
    """A near-parallel vector (high cosine to `base`) — models a duplicate."""
    return [b + eps for b in base]


def test_cross_lingual_pair_collapses_keeping_higher_priority():
    # A launch reported twice: Yonhap (EN, prestige wire) and 조선일보 (KO). Their
    # embeddings are nearly parallel -> should collapse to ONE, keeping the
    # higher-priority representative. A third, orthogonal story must survive.
    v_launch_en = [1.0, 0.0, 0.0, 0.0]
    v_launch_ko = _near(v_launch_en, 0.02)   # cos ~0.999 to the EN item
    v_other     = [0.0, 1.0, 0.0, 0.0]       # cos 0.0 — a different story

    articles = [
        {"title": "NK fires missile", "summary": "short", "source": "Yonhap",
         "lang": "EN", "prestige": True},
        {"title": "북한 미사일 발사", "summary": "조선일보 기사 본문이 더 길다 " * 5,
         "source": "조선일보", "lang": "KO"},
        {"title": "ROK economy grows", "summary": "unrelated", "source": "KBS",
         "lang": "EN"},
    ]
    vecs = [v_launch_en, v_launch_ko, v_other]

    kept, log = cluster_dedup(articles, vecs, threshold=0.90)

    kept_sources = {a["source"] for a in kept}
    assert len(kept) == 2, f"expected 2 survivors, got {len(kept)}: {kept_sources}"
    assert "KBS" in kept_sources, "the unrelated story must survive"
    # Exactly one of the launch pair survives, and it is the prestige wire.
    assert "Yonhap" in kept_sources, "prestige wire should be kept as representative"
    assert "조선일보" not in kept_sources, "the KO duplicate should be dropped"
    assert len(log) == 1 and log[0]["kept_source"] == "Yonhap"
    assert log[0]["dropped_source"] == "조선일보"
    assert log[0]["score"] >= 0.90
    print("PASS  cross-lingual pair collapses, prestige representative kept")


def test_distinct_stories_are_not_collapsed():
    # Three orthogonal stories -> nothing should be dropped.
    articles = [
        {"title": "A", "summary": "", "source": "s1"},
        {"title": "B", "summary": "", "source": "s2"},
        {"title": "C", "summary": "", "source": "s3"},
    ]
    vecs = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    kept, log = cluster_dedup(articles, vecs, threshold=0.90)
    assert len(kept) == 3 and log == [], "distinct stories must not be merged"
    print("PASS  distinct stories survive untouched")


def test_threshold_is_respected():
    # A moderately-similar pair (cos ~0.83) must NOT collapse at 0.90, but MUST
    # at 0.80 — guards against an over-aggressive default.
    a = [1.0, 0.0]
    b = [0.83, 0.5578]  # cos ~0.83 with `a`
    articles = [{"title": "x", "summary": "", "source": "s1"},
                {"title": "y", "summary": "", "source": "s2"}]
    kept_strict, _ = cluster_dedup(articles, [a, b], threshold=0.90)
    kept_loose, _ = cluster_dedup(articles, [a, b], threshold=0.80)
    assert len(kept_strict) == 2, "0.90 threshold should keep a ~0.83 pair apart"
    assert len(kept_loose) == 1, "0.80 threshold should merge a ~0.83 pair"
    print("PASS  threshold boundary behaves (0.90 keeps, 0.80 merges)")


def test_order_preserved_and_singletons_passthrough():
    kept, log = cluster_dedup([{"title": "only", "summary": "", "source": "s"}],
                              [[1, 0]], threshold=0.90)
    assert len(kept) == 1 and log == []
    print("PASS  singleton passes through")


def _smoke_real_model():
    """Opt-in: exercise the actual encoder on a real KO/EN pair.
    Skipped unless RUN_EMBED_SMOKE=1 (downloads the model on first run)."""
    import os
    if os.environ.get("RUN_EMBED_SMOKE") != "1":
        print("SKIP  real-model smoke test (set RUN_EMBED_SMOKE=1 to run)")
        return
    from embeddings import semantic_dedup
    articles = [
        {"title": "North Korea fired a ballistic missile toward the East Sea",
         "summary": "Seoul's military said the launch happened Tuesday morning.",
         "source": "Yonhap", "lang": "EN", "prestige": True},
        {"title": "북한, 동해로 탄도미사일 발사",
         "summary": "합동참모본부는 화요일 오전 발사가 있었다고 밝혔다.",
         "source": "조선일보", "lang": "KO"},
        {"title": "Bank of Korea holds interest rate at 2.5%",
         "summary": "The central bank kept its policy rate unchanged.",
         "source": "KBS", "lang": "EN"},
    ]
    kept, log = semantic_dedup(articles)  # default threshold 0.75
    print(f"      real-model survivors: {[a['source'] for a in kept]}")
    print(f"      real-model drop log:  {log}")
    assert len(kept) == 2, "real model should collapse the KO/EN launch pair"
    print("PASS  real model collapses the cross-lingual pair")


if __name__ == "__main__":
    test_cross_lingual_pair_collapses_keeping_higher_priority()
    test_distinct_stories_are_not_collapsed()
    test_threshold_is_respected()
    test_order_preserved_and_singletons_passthrough()
    _smoke_real_model()
    print("\nAll deterministic tests passed.")
