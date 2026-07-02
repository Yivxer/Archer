def test_devil_challenges_absolute_product_assumption_gently():
    from core.devil import challenge_assumption

    proposal = challenge_assumption("只要把功能做得足够多，用户一定会留下来")

    assert proposal is not None
    assert proposal.assumption == "只要把功能做得足够多，用户一定会留下来"
    assert proposal.kind == "absolute_claim"
    assert "如果不成立" in proposal.question


def test_devil_challenges_must_statement_without_claiming_it_is_wrong():
    from core.devil import challenge_assumption

    proposal = challenge_assumption("我必须每天都高效，否则就会落后")

    assert proposal is not None
    assert proposal.kind == "must_statement"
    assert "有没有例外" in proposal.question


def test_devil_stays_silent_for_ordinary_statement():
    from core.devil import challenge_assumption

    assert challenge_assumption("今天想读一点书") is None
