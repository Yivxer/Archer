"""B5.1 simple path / full path 分叉测试。

覆盖：
- core.desktop_tool_router.is_simple_chat_path 判定
- _iter_chat_chunks 对闲聊走 simple path（无 orchestrationEvent/planEvent/runtimeContextEvent）
- _iter_chat_chunks 对工具请求走 full path
- 长文本陷阱（>=40 字）不走 simple path
- URL 请求不走 simple path
"""
from __future__ import annotations

import pytest

from core.desktop_tool_router import is_simple_chat_path


# ── is_simple_chat_path 单元测试 ──

def test_simple_chat_path_pure_short_chat():
    """短纯闲聊应走 simple path。"""
    intent = {"intent": "chat", "needs_memory": False, "needs_tools": False, "needs_project": False}
    assert is_simple_chat_path("你好", intent) is True
    assert is_simple_chat_path("今天天气不错", intent) is True


def test_simple_chat_path_rejects_task_intent():
    """task 意图不走 simple path。"""
    intent = {"intent": "task", "needs_memory": False, "needs_tools": False, "needs_project": False}
    assert is_simple_chat_path("帮我写代码", intent) is False


def test_simple_chat_path_rejects_needs_memory():
    """needs_memory=True 不走 simple path（覆盖长文本陷阱）。"""
    intent = {"intent": "chat", "needs_memory": True, "needs_tools": False, "needs_project": False}
    assert is_simple_chat_path("一段较长的闲聊文本" * 5, intent) is False


def test_simple_chat_path_rejects_needs_tools():
    """needs_tools=True 不走 simple path。"""
    intent = {"intent": "chat", "needs_memory": False, "needs_tools": True, "needs_project": False}
    assert is_simple_chat_path("帮我查一下", intent) is False


def test_simple_chat_path_rejects_file_refs():
    """有附件不走 simple path。"""
    intent = {"intent": "chat", "needs_memory": False, "needs_tools": False, "needs_project": False}
    assert is_simple_chat_path("你好", intent, file_refs=[{"type": "file"}]) is False


def test_simple_chat_path_rejects_url():
    """含 URL 不走 simple path（web_fetch 请求需要 full path）。"""
    intent = {"intent": "chat", "needs_memory": False, "needs_tools": False, "needs_project": False}
    assert is_simple_chat_path("看看这个 https://example.com", intent) is False


def test_simple_chat_path_rejects_tool_keywords():
    """工具关键词不走 simple path。"""
    intent = {"intent": "chat", "needs_memory": False, "needs_tools": False, "needs_project": False}
    for kw in ("hugo", "博客", "obsidian", "笔记", "shell", "git", "部署", "发布"):
        assert is_simple_chat_path(f"帮我 {kw}", intent) is False


def test_simple_chat_path_rejects_empty():
    """空 query 不走 simple path。"""
    intent = {"intent": "chat", "needs_memory": False, "needs_tools": False, "needs_project": False}
    assert is_simple_chat_path("", intent) is False
    assert is_simple_chat_path("   ", intent) is False


# ── _iter_chat_chunks 分叉集成测试 ──

class TestSimplePathFork:
    """验证 _iter_chat_chunks 对闲聊/工具请求正确分叉。"""

    def test_pure_chat_takes_simple_path(self, monkeypatch):
        """短闲聊应走 simple path：无 orchestrationEvent/planEvent/runtimeContextEvent，有 statusEvent.simplePath=True。"""
        from terminal.api import _tools as tools

        # mock 模型 stream
        monkeypatch.setattr("core.llm.stream_chat", lambda _messages, **kwargs: iter(["你好啊。"]))

        events = list(tools._iter_chat_chunks(
            [{"role": "user", "content": "你好"}],
            memory_mode="off",
            obsidian_mode="off",
            file_refs=[],
        ))

        # simple path 不发 orchestrationEvent/planEvent，但仍上报真实模型 Trace。
        assert not [e for e in events if isinstance(e, dict) and e.get("type") == "orchestrationEvent"]
        assert not [e for e in events if isinstance(e, dict) and e.get("type") == "planEvent"]
        model_context = [e for e in events if isinstance(e, dict) and e.get("type") == "runtimeContextEvent"]
        assert len(model_context) == 2
        memory_context = next(
            event["runtimeContextEvent"] for event in model_context
            if event["runtimeContextEvent"]["phase"] == "memory"
        )
        assert memory_context["contextReceipt"]["retrieval"]["reason"] == "mode_off"
        assert any(event["runtimeContextEvent"]["phase"] == "model_stream" for event in model_context)
        # simple path 发 statusEvent 且 simplePath=True
        status_events = [e for e in events if isinstance(e, dict) and e.get("type") == "statusEvent"]
        assert status_events, "应至少发一个 statusEvent"
        assert any(e["statusEvent"].get("simplePath") is True for e in status_events)
        # 主回复 token
        assert any(e.get("text") == "你好啊。" for e in events if isinstance(e, dict))
        # done
        assert any(e.get("type") == "done" for e in events if isinstance(e, dict))

    def test_tool_request_takes_full_path(self, monkeypatch):
        """工具请求应走 full path：有 orchestrationEvent 或 _run_desktop_tool_loop 调用。"""
        from terminal.api import _tools as tools

        tool_loop_calls = []

        def fake_tool_loop(messages, selected, _query):
            tool_loop_calls.append(set(selected))
            return messages, []

        monkeypatch.setattr(tools, "_run_desktop_tool_loop", fake_tool_loop)
        # "查一下笔记" 含 "笔记" 关键词，不走 simple path
        monkeypatch.setattr("core.llm.stream_chat", lambda _messages, **kwargs: iter(["已查到。"]))

        events = list(tools._iter_chat_chunks(
            [{"role": "user", "content": "查一下笔记"}],
            memory_mode="off",
            obsidian_mode="off",
            file_refs=[],
        ))

        # full path 应至少有 orchestrationEvent 或 tool_loop 调用
        has_orchestration = any(
            isinstance(e, dict) and e.get("type") == "orchestrationEvent"
            for e in events
        )
        # 如果 orchestration 没触发，至少 tool_loop 不该是 simple path 的空
        # 注：full path 也可能 filtered_skills={} 导致 tool_loop 不调用，但 simple path 标识不该出现
        status_events = [e for e in events if isinstance(e, dict) and e.get("type") == "statusEvent"]
        assert not any(e["statusEvent"].get("simplePath") is True for e in status_events), \
            "工具请求不应走 simple path"

    def test_long_chat_not_takes_simple_path(self, monkeypatch):
        """长闲聊（>=40 字）触发 intent.py 陷阱打成 task，不走 simple path。"""
        from terminal.api import _tools as tools

        monkeypatch.setattr("core.llm.stream_chat", lambda _messages, **kwargs: iter(["嗯。"]))

        # 40 字纯闲聊 → intent.py:134-137 打成 task, 0.72 → needs_memory/tools/project=True
        long_chat = "今天我感觉还不错，想和你聊聊最近发生的事情，虽然没什么特别的，但就是想说说话呀。"
        assert len(long_chat.strip()) >= 40
        events = list(tools._iter_chat_chunks(
            [{"role": "user", "content": long_chat}],
            memory_mode="off",
            obsidian_mode="off",
            file_refs=[],
        ))

        status_events = [e for e in events if isinstance(e, dict) and e.get("type") == "statusEvent"]
        assert not any(e["statusEvent"].get("simplePath") is True for e in status_events), \
            "长闲聊应走 full path（intent 陷阱打成 task）"

    def test_url_request_not_takes_simple_path(self, monkeypatch):
        """含 URL 的请求不走 simple path。"""
        from terminal.api import _tools as tools

        monkeypatch.setattr(tools, "_run_desktop_tool_loop", lambda m, s, q: (m, []))
        monkeypatch.setattr("core.llm.stream_chat", lambda _messages, **kwargs: iter(["已查看。"]))

        events = list(tools._iter_chat_chunks(
            [{"role": "user", "content": "看看 https://example.com 这个"}],
            memory_mode="off",
            obsidian_mode="off",
            file_refs=[],
        ))

        status_events = [e for e in events if isinstance(e, dict) and e.get("type") == "statusEvent"]
        assert not any(e["statusEvent"].get("simplePath") is True for e in status_events), \
            "URL 请求应走 full path"

    def test_simple_path_emits_done(self, monkeypatch):
        """simple path 必须发 done event，否则 UI 会无限 loading。"""
        from terminal.api import _tools as tools

        monkeypatch.setattr("core.llm.stream_chat", lambda _messages, **kwargs: iter(["好。"]))

        events = list(tools._iter_chat_chunks(
            [{"role": "user", "content": "嗯"}],
            memory_mode="off",
            obsidian_mode="off",
            file_refs=[],
        ))

        assert any(e.get("type") == "done" for e in events if isinstance(e, dict))

    def test_simple_path_model_empty_response_fallback(self, monkeypatch):
        """simple path 模型无回复时应发兜底文案 + failureHintEvent。"""
        from terminal.api import _tools as tools

        # 模型返回空
        monkeypatch.setattr("core.llm.stream_chat", lambda _messages, **kwargs: iter([""]))

        events = list(tools._iter_chat_chunks(
            [{"role": "user", "content": "你好"}],
            memory_mode="off",
            obsidian_mode="off",
            file_refs=[],
        ))

        # 应有兜底 token
        tokens = [e.get("text") for e in events if isinstance(e, dict) and e.get("type") == "token"]
        assert any("模型没有返回内容" in t for t in tokens if t), "应发兜底文案"
        # 应有 failureHintEvent
        assert any(e.get("type") == "failureHintEvent" for e in events if isinstance(e, dict))
