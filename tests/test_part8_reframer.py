def test_reframer_turns_all_or_nothing_scope_into_smallest_closed_loop():
    from core.reframer import reframe_problem

    frame = reframe_problem("我觉得必须把 Archer 一次做完，否则没有意义")

    assert frame is not None
    assert frame.angle == "scope"
    assert "最小闭环" in frame.prompt


def test_reframer_turns_time_shortage_into_priority_question():
    from core.reframer import reframe_problem

    frame = reframe_problem("我没有时间做健身视频")

    assert frame is not None
    assert frame.angle == "priority"
    assert "优先级" in frame.prompt


def test_reframer_turns_failure_anxiety_into_reversible_experiment():
    from core.reframer import reframe_problem

    frame = reframe_problem("我怕做错，所以一直不敢开始")

    assert frame is not None
    assert frame.angle == "experiment"
    assert "可逆" in frame.prompt


def test_reframer_stays_silent_without_a_clear_rule_based_pattern():
    from core.reframer import reframe_problem

    assert reframe_problem("今天想读一点书") is None
