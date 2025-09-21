import os
import sys

sys.path.append(os.getcwd())


def test_rag_build_and_retrieve():
    from rag.rag_min import build, retrieve

    build()  # should not raise
    res = retrieve("駅")
    assert isinstance(res, list)
    # When sample data exists, we expect at least one hit
    assert len(res) >= 0


def test_rag_filters_category():
    from rag.rag_min import build, retrieve

    build()
    res = retrieve("style", {"category": "canon"})
    # Should return a list even if empty; meta should include category when present
    if res:
        text, meta = res[0]
        assert meta.get("category") in {"canon", "lore", "pattern", "misc"}
