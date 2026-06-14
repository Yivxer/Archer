"""P5.6 — Lifecycle hooks (PreToolUse, PostToolUse, PreCompact, etc.)."""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any, Callable

HOOK_EVENTS = frozenset({
    "PreToolUse",
    "PostToolUse",
    "PreCompact",
    "PostCompact",
    "SessionStart",
    "SessionStop",
})

HOOK_TYPES = frozenset({"command", "python", "prompt"})


@dataclass
class HookContext:
    event: str
    tool_name: str = ""
    tool_args: dict | None = None
    tool_output: str = ""
    session_id: str = ""
    metadata: dict = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "tool_name": self.tool_name,
            "tool_input": dict(self.tool_args or {}),
            "tool_output": self.tool_output,
            "session_id": self.session_id,
            "metadata": dict(self.metadata),
        }


@dataclass
class HookResult:
    continue_: bool = True
    message: str = ""
    tool_args: dict | None = None
    metadata: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @classmethod
    def allow(cls, *, tool_args: dict | None = None, message: str = "", metadata: dict | None = None) -> HookResult:
        return cls(
            continue_=True,
            message=message,
            tool_args=tool_args,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def block(cls, message: str = "") -> HookResult:
        return cls(continue_=False, message=message or "blocked by hook")


@dataclass(frozen=True)
class HookDefinition:
    event: str
    hook_type: str
    handler: str = ""
    command: str = ""
    prompt: str = ""
    matcher: str = ""
    enabled: bool = True
    fail_closed: bool = False

    def matches(self, context: HookContext) -> bool:
        if not self.enabled:
            return False
        if not self.matcher:
            return True
        if context.tool_name:
            return fnmatch(context.tool_name, self.matcher)
        return True


def _resolve_handler(path: str) -> Callable[[dict], Any]:
    if ":" not in path:
        raise ValueError(f"python hook handler must be module:function, got {path!r}")
    module_name, func_name = path.split(":", 1)
    module = importlib.import_module(module_name)
    func = getattr(module, func_name)
    if not callable(func):
        raise TypeError(f"python hook handler not callable: {path}")
    return func


def _parse_hook_response(raw: Any) -> HookResult:
    if isinstance(raw, HookResult):
        return raw
    if not isinstance(raw, dict):
        return HookResult.allow()

    continue_flag = raw.get("continue", raw.get("continue_", True))
    tool_input = raw.get("tool_input", raw.get("tool_args"))
    message = str(raw.get("message") or "")
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}

    if continue_flag is False:
        return HookResult.block(message or "blocked by hook")
    return HookResult.allow(
        tool_args=dict(tool_input) if isinstance(tool_input, dict) else None,
        message=message,
        metadata=metadata,
    )


class HookRegistry:
    def __init__(self, hooks: list[HookDefinition] | None = None, *, enabled: bool = True):
        self.enabled = enabled
        self._hooks = list(hooks or [])

    def register(self, hook: HookDefinition) -> None:
        if hook.event not in HOOK_EVENTS:
            raise ValueError(f"unknown hook event: {hook.event}")
        if hook.hook_type not in HOOK_TYPES:
            raise ValueError(f"unknown hook type: {hook.hook_type}")
        self._hooks.append(hook)

    def for_event(self, event: str) -> list[HookDefinition]:
        return [hook for hook in self._hooks if hook.event == event and hook.enabled]

    @classmethod
    def from_config(cls, cfg: dict | None) -> HookRegistry:
        hooks_cfg = (cfg or {}).get("hooks") or {}
        enabled = bool(hooks_cfg.get("enabled", True))
        hooks: list[HookDefinition] = []

        for event in HOOK_EVENTS:
            entries = hooks_cfg.get(event) or []
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                hook_type = str(entry.get("type", "")).strip().lower()
                if hook_type not in HOOK_TYPES:
                    continue
                hooks.append(
                    HookDefinition(
                        event=event,
                        hook_type=hook_type,
                        handler=str(entry.get("handler", "")).strip(),
                        command=str(entry.get("command", "")).strip(),
                        prompt=str(entry.get("prompt", "")).strip(),
                        matcher=str(entry.get("matcher", "")).strip(),
                        enabled=entry.get("enabled", True) is not False,
                        fail_closed=entry.get("fail_closed", False) is True,
                    )
                )
        reg = cls(hooks, enabled=enabled)
        try:
            from core.plugin import load_plugin_hook_definitions

            for hook in load_plugin_hook_definitions():
                reg.register(hook)
        except Exception:
            pass
        return reg


_REGISTRY: HookRegistry | None = None


def get_hook_registry(cfg: dict | None = None) -> HookRegistry:
    global _REGISTRY
    if cfg is not None:
        return HookRegistry.from_config(cfg)
    if _REGISTRY is None:
        try:
            from core.llm import load_config

            _REGISTRY = HookRegistry.from_config(load_config())
        except Exception:
            _REGISTRY = HookRegistry(enabled=False)
    return _REGISTRY


def set_hook_registry(registry: HookRegistry | None) -> None:
    global _REGISTRY
    _REGISTRY = registry


def _run_python_hook(defn: HookDefinition, payload: dict[str, Any]) -> HookResult:
    func = _resolve_handler(defn.handler)
    return _parse_hook_response(func(payload))


def _run_command_hook(defn: HookDefinition, payload: dict[str, Any]) -> HookResult:
    proc = subprocess.run(
        defn.command,
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        shell=True,
        timeout=30,
    )
    if proc.returncode != 0 and not proc.stdout.strip():
        raise RuntimeError(proc.stderr.strip() or f"command hook exited {proc.returncode}")
    stdout = proc.stdout.strip()
    if not stdout:
        return HookResult.allow()
    return _parse_hook_response(json.loads(stdout))


def _run_prompt_hook(defn: HookDefinition, payload: dict[str, Any]) -> HookResult:
    _ = (defn.prompt, payload)
    return HookResult.allow(metadata={"prompt_hook": "noop"})


def _run_single_hook(defn: HookDefinition, context: HookContext) -> HookResult:
    payload = context.to_payload()
    if defn.hook_type == "python":
        if not defn.handler:
            raise ValueError("python hook requires handler")
        return _run_python_hook(defn, payload)
    if defn.hook_type == "command":
        if not defn.command:
            raise ValueError("command hook requires command")
        return _run_command_hook(defn, payload)
    if defn.hook_type == "prompt":
        return _run_prompt_hook(defn, payload)
    raise ValueError(f"unsupported hook type: {defn.hook_type}")


def run_hooks(
    event: str,
    context: HookContext,
    *,
    cfg: dict | None = None,
    registry: HookRegistry | None = None,
) -> HookResult:
    """Run configured hooks for an event and merge outcomes."""
    reg = registry or get_hook_registry(cfg)
    if not reg.enabled:
        return HookResult.allow()

    merged = HookResult.allow()
    for hook in reg.for_event(event):
        if not hook.matches(context):
            continue
        try:
            result = _run_single_hook(hook, context)
        except Exception as exc:
            err = f"{hook.hook_type} hook failed: {exc}"
            if hook.fail_closed:
                return HookResult.block(err)
            merged.errors.append(err)
            continue

        if not result.continue_:
            return HookResult.block(result.message or "blocked by hook")

        if result.tool_args is not None:
            merged.tool_args = dict(result.tool_args)
        if result.message:
            merged.message = result.message
        merged.metadata.update(result.metadata)
        merged.errors.extend(result.errors)

    return merged


def hooks_enabled(cfg: dict | None = None) -> bool:
    hooks_cfg = (cfg or {}).get("hooks") or {}
    return bool(hooks_cfg.get("enabled", True))
