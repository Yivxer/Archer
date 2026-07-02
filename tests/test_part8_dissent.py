def test_dissent_offers_parallel_perspective_for_single_path_claim():
    from core.dissent import propose_dissent

    candidate = propose_dissent("我只能先把功能做全，产品才能开始有价值")

    assert candidate is not None
    assert candidate.kind == "single_path"
    assert "另一种看法" in candidate.message
    assert "最小价值" in candidate.message


def test_dissent_offers_parallel_perspective_for_absolute_outcome():
    from core.dissent import propose_dissent

    candidate = propose_dissent("只要用户多，产品一定能成功")

    assert candidate is not None
    assert candidate.kind == "absolute_outcome"
    assert "还有哪些条件" in candidate.message


def test_dissent_stays_silent_for_ordinary_statement():
    from core.dissent import propose_dissent

    assert propose_dissent("今天先整理一下笔记") is None
