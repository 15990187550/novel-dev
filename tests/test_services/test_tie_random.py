from novel_dev.services.tie_random import tie_random_pick


def test_same_experiment_id_yields_same_pick():
    candidates = ["a", "b"]
    p1 = tie_random_pick("exp_1", candidates)
    p2 = tie_random_pick("exp_1", candidates)
    assert p1 == p2
    assert p1 in candidates


def test_different_experiment_ids_can_yield_different_picks():
    """至少 80% 的实验 ID 哈希到不同 candidate(只 2 个 candidate 时严格 50/50)"""
    candidates = ["a", "b"]
    seen = set()
    for i in range(100):
        seen.add(tie_random_pick(f"exp_{i}", candidates))
    # 100 个不同实验 ID 应该两个 candidate 都出现过
    assert seen == {"a", "b"}


def test_three_candidates_works():
    candidates = ["x", "y", "z"]
    for i in range(50):
        p = tie_random_pick(f"exp_{i}", candidates)
        assert p in candidates


def test_raises_on_empty_candidates():
    import pytest
    with pytest.raises(ValueError):
        tie_random_pick("exp_1", [])
