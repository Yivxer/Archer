"""P5.6 — Lifecycle hooks tests."""
from __future__ import annotations

import json
import types

import pytest

from core.hooks import (
    HookContext,
    HookDefinition,
    HookRegistry,
    HookResult,
    run_hooks,
    set_hook_registry,
)
from tests import hook_fixtures


@pytest.fixture(autouse=True)
def _reset_hook_state():
    hook_fixtures.reset_calls()
    set_hook_registry(None)
    yield
    set_hook_registry(None)
    hook_fixtures.reset_calls()


def test_registry_from_config_parses_event_hooks():
    cfg = {
        "hooks": {
            "enabled": True,
            "PreToolUse": [
                {"type": "python", "handler": "tests.hook_fixtures:prepend_tag", "matcher": "alpha"},
            ],
            "SessionStart": [
                {"type": "command", "command": "echo '{\"continue\": true}'"},
            ],
        }
    }
    registry = HookRegistry.from_config(cfg)
    assert len(registry.for_event("PreToolUse")) == 1
    assert registry.for_event("PreToolUse")[0].matcher == "alpha"


def test_pre_tool_use_python_hook_modifies_args():
    registry = HookRegistry(enabled=True)
    registry.register(
        HookDefinition(
            event="PreToolUse",
            hook_type="python",
            handler="tests.hook_fixtures:prepend_tag",
        )
    )
    result = run_hooks(
        "PreToolUse",
        HookContext(event="PreToolUse", tool_name="alpha", tool_args={"q": "x"}),
        registry=registry,
    )
    assert result.continue_ is True
    assert result.tool_args == {"q": "x", "hooked": True}
    assert hook_fixtures.CALLS[0]["tool_name"] == "alpha"


def test_pre_tool_use_block_stops_execution():
    registry = HookRegistry(enabled=True)
    registry.register(
        HookDefinition(
            event="PreToolUse",
            hook_type="python",
            handler="tests.hook_fixtures:block_tool",
        )
    )
    result = run_hooks(
        "PreToolUse",
        HookContext(event="PreToolUse", tool_name="shell", tool_args={}),
        registry=registry,
    )
    assert result.continue_ is False
    assert "blocked" in result.message


def test_matcher_limits_tool_hooks():
    registry = HookRegistry(enabled=True)
    registry.register(
        HookDefinition(
            event="PreToolUse",
            hook_type="python",
            handler="tests.hook_fixtures:prepend_tag",
            matcher="web_search",
        )
    )
    skipped = run_hooks(
        "PreToolUse",
        HookContext(event="PreToolUse", tool_name="file_ops", tool_args={}),
        registry=registry,
    )
    assert skipped.tool_args is None
    assert hook_fixtures.CALLS == []

    matched = run_hooks(
        "PreToolUse",
        HookContext(event="PreToolUse", tool_name="web_search", tool_args={"q": "a"}),
        registry=registry,
    )
    assert matched.tool_args == {"q": "a", "hooked": True}


def test_hook_error_fail_open_by_default():
    registry = HookRegistry(enabled=True)
    registry.register(
        HookDefinition(
            event="PreToolUse",
            hook_type="python",
            handler="tests.hook_fixtures:fail_closed",
        )
    )
    result = run_hooks(
        "PreToolUse",
        HookContext(event="PreToolUse", tool_name="alpha", tool_args={}),
        registry=registry,
    )
    assert result.continue_ is True
    assert result.errors


def test_hook_error_fail_closed_blocks():
    registry = HookRegistry(enabled=True)
    registry.register(
        HookDefinition(
            event="PreToolUse",
            hook_type="python",
            handler="tests.hook_fixtures:fail_closed",
            fail_closed=True,
        )
    )
    result = run_hooks(
        "PreToolUse",
        HookContext(event="PreToolUse", tool_name="alpha", tool_args={}),
        registry=registry,
    )
    assert result.continue_ is False


def test_command_hook_reads_json_stdout(monkeypatch):
    registry = HookRegistry(enabled=True)
    registry.register(
        HookDefinition(
            event="SessionStart",
            hook_type="command",
            command="python -c \"import sys,json; print(json.dumps({'continue': True, 'metadata': {'ok': True}}))\"",
        )
    )
    result = run_hooks(
        "SessionStart",
        HookContext(event="SessionStart", session_id="sess-1"),
        registry=registry,
    )
    assert result.continue_ is True
    assert result.metadata.get("ok") is True


def test_pre_compact_runs_via_orchestrator(monkeypatch):
    from core.orchestrator import maybe_run_memory_compaction_after_turn

    cfg = {
        "hooks": {
            "enabled": True,
            "PreCompact": [
                {"type": "python", "handler": "tests.hook_fixtures:log_compact"},
            ],
        }
    }

    monkeypatch.setattr(
        "memory.compaction.maybe_compact_memories",
        lambda: types.SimpleNamespace(
            triggered=True,
            reason="test",
            archived_count=1,
            archived_ids=[1],
            summary_id=2,
        ),
    )

    payload = maybe_run_memory_compaction_after_turn(cfg=cfg)
    assert payload is not None
    assert hook_fixtures.CALLS
    assert hook_fixtures.CALLS[0]["event"] == "PreCompact"


def test_tool_loop_applies_pre_tool_use_hook(monkeypatch):
    import core.tool_loop as tool_loop
    from core.policy import PolicyResult, Decision
    from io import StringIO
    from rich.console import Console

    captured = {}

    def fake_invoke(name, args, skills):
        captured["args"] = dict(args)
        mod = types.SimpleNamespace(
            ok=True,
            summary="ok",
            truncated=False,
            meta={},
            to_message_content=lambda: "done",
        )
        return mod

    registry = HookRegistry(enabled=True)
    registry.register(
        HookDefinition(
            event="PreToolUse",
            hook_type="python",
            handler="tests.hook_fixtures:prepend_tag",
        )
    )

    monkeypatch.setattr(
        tool_loop,
        "run_hooks",
        lambda event, ctx, cfg=None, registry=None, _registry=registry: run_hooks(
            event, ctx, registry=_registry
        ),
    )
    monkeypatch.setattr(tool_loop, "policy_check", lambda *a, **k: PolicyResult(Decision.ALLOW))
    monkeypatch.setattr(tool_loop, "runtime_invoke", fake_invoke)
    responses = [
        types.SimpleNamespace(
            content="",
            tool_calls=[
                types.SimpleNamespace(
                    id="tc1",
                    function=types.SimpleNamespace(name="alpha", arguments=json.dumps({"q": "x"})),
                )
            ],
        ),
        types.SimpleNamespace(content="done", tool_calls=[]),
    ]

    monkeypatch.setattr(
        tool_loop,
        "call_with_tools",
        lambda messages, tools, model="": responses.pop(0),
    )
    monkeypatch.setattr(tool_loop, "get_tools", lambda skills: [])

    tool_loop.run_with_tools(
        [{"role": "user", "content": "go"}],
        {"alpha": object()},
        stream_fn=lambda messages, model: "final",
        console=Console(file=StringIO(), force_terminal=False, width=120),
        cfg={"hooks": {"enabled": True}},
    )

    assert captured["args"] == {"q": "x", "hooked": True}
