from core import turn_decision


def test_invalid_model_json_falls_back_to_read_only_analysis(monkeypatch):
    monkeypatch.setattr("core.llm.stream_chat", lambda *args, **kwargs: iter(["not-json"]))

    decision = turn_decision.decide_turn(
        "这篇文章反响不好，帮我分析 /Users/test/article.md",
        file_context="[本地文件] article.md\n正文",
        candidate_capabilities=["hugo_blog"],
    )

    assert decision.handling == "analyze"
    assert decision.action_requests == ()
    assert decision.valid is False


def test_model_decision_keeps_verbatim_action_evidence(monkeypatch):
    raw = '''{"user_goal":"发布文章","handling":"execute_action","context_requests":[],
    "action_requests":[{"capability":"hugo_blog","action":"publish","target":"/Users/test/a.md",
    "parameters":{},"evidence":"帮我发布到枫弋札记"}],"confidence":0.94,"summary":"明确发布"}'''
    monkeypatch.setattr("core.llm.stream_chat", lambda *args, **kwargs: iter([raw]))

    decision = turn_decision.decide_turn(
        "帮我发布到枫弋札记 /Users/test/a.md", file_context="正文",
        candidate_capabilities=["hugo_blog"],
    )

    assert decision.handling == "execute_action"
    assert decision.action_requests[0].evidence == "帮我发布到枫弋札记"
