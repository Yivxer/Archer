def test_creative_scorer_returns_explainable_weighted_score():
    from core.scorer import CreativeCandidate, score_creative_candidate

    result = score_creative_candidate(
        CreativeCandidate(
            kind="reframe",
            message="最小闭环",
            novelty=0.8,
            relevance=0.6,
            safety=0.9,
        )
    )

    assert result.total == 0.74
    assert result.trace == {"novelty": 0.8, "relevance": 0.6, "safety": 0.9}


def test_creative_pipeline_filters_unsafe_or_low_score_candidates_and_ranks_rest():
    from core.pipeline import rank_creative_candidates
    from core.scorer import CreativeCandidate

    ranked = rank_creative_candidates(
        [
            CreativeCandidate("weak", "低分", novelty=0.2, relevance=0.2, safety=1.0),
            CreativeCandidate("unsafe", "风险", novelty=1.0, relevance=1.0, safety=0.3),
            CreativeCandidate("strong", "高分", novelty=0.9, relevance=0.8, safety=1.0),
            CreativeCandidate("medium", "中分", novelty=0.7, relevance=0.7, safety=1.0),
        ]
    )

    assert [item.candidate.kind for item in ranked] == ["strong", "medium"]
    assert ranked[0].score.total > ranked[1].score.total
    assert all(item.shadow is True for item in ranked)


def test_creative_pipeline_respects_limit():
    from core.pipeline import rank_creative_candidates
    from core.scorer import CreativeCandidate

    ranked = rank_creative_candidates(
        [
            CreativeCandidate("a", "A", 1.0, 0.7, 1.0),
            CreativeCandidate("b", "B", 0.9, 0.9, 1.0),
        ],
        limit=1,
    )

    assert len(ranked) == 1
    assert ranked[0].candidate.kind == "b"
