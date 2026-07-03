#!/usr/bin/env python3
"""Replay a trace from a persisted eventLog JSON file and verify L2 order contract.

Usage:
    python3 scripts/replay_trace.py <trace_id> --file <eventLog.json>

Exit codes:
    0 = trace 解析成功，顺序契约满足
    1 = trace 不存在（eventLog 中无该 traceId 的事件）
    2 = 顺序违规（事件序列违反 L2 顺序契约）
    3 = 参数错误 / 文件读取失败

L2 顺序契约（参考 Archer 稳定性框架 §五）:
    runtime.context → [status.event / orchestration.event] → [tool.request → approval.result? → tool.result]* → (text.final | failure.hint) → done
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# L2 顺序契约定义
# 每个事件类型在序列中允许出现的位置阶段
PHASE_SETUP = "setup"          # runtime.context / status.event / orchestration.event
PHASE_TOOL_REQ = "tool_req"    # tool.request
PHASE_APPROVAL = "approval"    # approval.result
PHASE_TOOL_RESULT = "tool_result"  # tool.result
PHASE_FINAL = "final"          # text.final / failure.hint / runtime.error
PHASE_POST = "post"            # job.event / plan.event / initiative.event (可在多阶段出现)

# 事件类型 -> 所属阶段映射
EVENT_PHASE = {
    "runtime.context": PHASE_SETUP,
    "status.event": PHASE_SETUP,
    "orchestration.event": PHASE_SETUP,
    "tool.request": PHASE_TOOL_REQ,
    "approval.result": PHASE_APPROVAL,
    "tool.result": PHASE_TOOL_RESULT,
    "text.final": PHASE_FINAL,
    "failure.hint": PHASE_FINAL,
    "runtime.error": PHASE_FINAL,
    "text.delta": PHASE_FINAL,  # 流式增量，归到 final 阶段（不影响契约）
    "job.event": PHASE_POST,
    "plan.event": PHASE_POST,
    "initiative.event": PHASE_POST,
}

# 阶段优先级（数字越大表示越靠后）
PHASE_ORDER = {
    PHASE_SETUP: 0,
    PHASE_TOOL_REQ: 1,
    PHASE_APPROVAL: 2,
    PHASE_TOOL_RESULT: 3,
    PHASE_FINAL: 4,
    PHASE_POST: -1,  # POST 阶段可在任意位置出现，特殊处理
}

# 每个阶段允许的前置阶段
ALLOWED_PREV_PHASE = {
    PHASE_SETUP: {PHASE_SETUP},
    PHASE_TOOL_REQ: {PHASE_SETUP, PHASE_TOOL_RESULT},  # setup 后或上一轮 tool.result 后
    PHASE_APPROVAL: {PHASE_TOOL_REQ},                   # 必须紧跟 tool.request
    PHASE_TOOL_RESULT: {PHASE_APPROVAL, PHASE_TOOL_REQ},  # approval 后或直接 tool.request 后（不需审批）
    PHASE_FINAL: {PHASE_SETUP, PHASE_TOOL_RESULT, PHASE_FINAL},  # setup 后（纯聊天）或 tool.result 后或流式 final
    PHASE_POST: set(),  # 不参与顺序检查
}


class Violation:
    """顺序违规记录"""

    def __init__(self, idx: int, event_id: str, event_type: str, reason: str, detail: str = ""):
        self.idx = idx
        self.event_id = event_id
        self.event_type = event_type
        self.reason = reason
        self.detail = detail

    def __str__(self) -> str:
        head = f"  [{self.idx:03d}] {self.event_type} ({self.event_id}): {self.reason}"
        if self.detail:
            return f"{head}\n        {self.detail}"
        return head


def load_events(file_path: Path) -> list[dict[str, Any]]:
    """从 JSON 文件加载事件列表"""
    try:
        raw = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"无法读取文件 {file_path}: {exc}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"JSON 解析失败 {file_path}: {exc}") from exc

    if not isinstance(parsed, list):
        raise SystemExit(f"文件根节点必须是数组，得到 {type(parsed).__name__}")

    return parsed


def filter_by_trace(events: list[dict[str, Any]], trace_id: str) -> list[dict[str, Any]]:
    """过滤出指定 traceId 的事件"""
    matched = [e for e in events if e.get("traceId") == trace_id]
    return matched


def sort_by_created_at(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 createdAt 排序；缺失则按原顺序"""
    def sort_key(e: dict[str, Any]) -> str:
        return e.get("createdAt", "")
    return sorted(events, key=sort_key)


def check_order(events: list[dict[str, Any]]) -> list[Violation]:
    """检查事件序列是否满足 L2 顺序契约

    Returns:
        list[Violation]：违规列表（空表示全部合规）
    """
    violations: list[Violation] = []
    last_phase: str | None = None
    pending_tool_request: dict[str, Any] | None = None  # 等待 tool.result 的 tool.request
    has_final = False

    for idx, event in enumerate(events):
        event_id = str(event.get("id", f"<unknown-{idx}>"))
        event_type = event.get("type", "")

        # 未知事件类型，记录但不阻塞
        if event_type not in EVENT_PHASE:
            violations.append(Violation(
                idx=idx, event_id=event_id, event_type=event_type,
                reason="未知事件类型",
                detail=f"type={event_type!r} 不在 L2 契约事件枚举内",
            ))
            continue

        phase = EVENT_PHASE[event_type]

        # POST 阶段（job/plan/initiative）允许在任意位置出现
        if phase == PHASE_POST:
            continue

        # 已经到了 final 阶段后，不应再出现非 POST 事件
        if has_final and phase != PHASE_FINAL:
            violations.append(Violation(
                idx=idx, event_id=event_id, event_type=event_type,
                reason="final 之后再次出现非 final 事件",
                detail=f"已见 text.final/failure.hint，后又出现 {event_type}",
            ))
            continue

        # 阶段转移检查
        if last_phase is not None:
            allowed = ALLOWED_PREV_PHASE.get(phase, set())
            if allowed and last_phase not in allowed:
                violations.append(Violation(
                    idx=idx, event_id=event_id, event_type=event_type,
                    reason="阶段顺序违规",
                    detail=f"前一阶段={last_phase}, 当前阶段={phase}, 允许前置={sorted(allowed)}",
                ))
                # 继续检查后续事件，但更新 last_phase
            else:
                # approval.result 必须紧跟 tool.request（不能跨 tool.request）
                if phase == PHASE_APPROVAL:
                    req_id = event.get("requestId", "")
                    if pending_tool_request is None:
                        violations.append(Violation(
                            idx=idx, event_id=event_id, event_type=event_type,
                            reason="approval.result 缺少对应 tool.request",
                            detail=f"requestId={req_id}, 但无待审 tool.request",
                        ))
                    elif req_id and pending_tool_request.get("id") != req_id:
                        violations.append(Violation(
                            idx=idx, event_id=event_id, event_type=event_type,
                            reason="approval.result 的 requestId 与最近 tool.request 不匹配",
                            detail=f"期望 {pending_tool_request.get('id')}, 实际 {req_id}",
                        ))

                # tool.result 必须匹配最近的 tool.request（或对应 approval.result）
                if phase == PHASE_TOOL_RESULT:
                    req_id = event.get("requestId", "")
                    if pending_tool_request is None:
                        violations.append(Violation(
                            idx=idx, event_id=event_id, event_type=event_type,
                            reason="tool.result 缺少对应 tool.request",
                            detail=f"requestId={req_id}, 但无待完成 tool.request",
                        ))
                    elif req_id and pending_tool_request.get("id") != req_id:
                        violations.append(Violation(
                            idx=idx, event_id=event_id, event_type=event_type,
                            reason="tool.result 的 requestId 与最近 tool.request 不匹配",
                            detail=f"期望 {pending_tool_request.get('id')}, 实际 {req_id}",
                        ))
                    pending_tool_request = None  # 清除待完成

        # 状态更新
        if phase == PHASE_TOOL_REQ:
            pending_tool_request = event
        elif phase == PHASE_FINAL:
            has_final = True

        last_phase = phase

    # 检查未闭合的 tool.request
    if pending_tool_request is not None:
        violations.append(Violation(
            idx=len(events),
            event_id=pending_tool_request.get("id", "<unknown>"),
            event_type="tool.request",
            reason="tool.request 未闭合",
            detail="缺少对应的 tool.result",
        ))

    # 检查整个序列是否有 final（空 trace 除外）
    if events and not has_final:
        violations.append(Violation(
            idx=len(events),
            event_id="<trace-end>",
            event_type="<none>",
            reason="trace 未结束",
            detail="缺少 text.final 或 failure.hint 作为结束信号",
        ))

    return violations


def format_event_line(event: dict[str, Any], idx: int) -> str:
    """格式化单行事件展示"""
    event_type = event.get("type", "?")
    event_id = str(event.get("id", "?"))[:12]
    created = event.get("createdAt", "?")[:19]
    extra = ""

    if event_type == "tool.request":
        extra = f" tool={event.get('toolName', '?')} approval={event.get('requiresApproval', False)}"
    elif event_type == "tool.result":
        extra = f" ok={event.get('ok', '?')}"
    elif event_type == "approval.result":
        extra = f" decision={event.get('decision', '?')}"
    elif event_type == "failure.hint":
        extra = f" keyword={event.get('keyword', '?')}"
    elif event_type == "runtime.context":
        extra = f" phase={event.get('phase', '?')}"

    return f"  [{idx:03d}] {created} {event_type:<22} {event_id}{extra}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay a trace from eventLog and verify L2 order contract",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("trace_id", help="要回放的 traceId")
    parser.add_argument("--file", required=True, help="eventLog JSON 文件路径")
    parser.add_argument("--verbose", "-v", action="store_true", help="输出完整事件序列")
    args = parser.parse_args(argv)

    file_path = Path(args.file).expanduser()
    if not file_path.exists():
        print(f"错误: 文件不存在 {file_path}", file=sys.stderr)
        return 3

    events = load_events(file_path)
    matched = filter_by_trace(events, args.trace_id)

    if not matched:
        print(f"错误: traceId={args.trace_id} 在 {file_path} 中未找到", file=sys.stderr)
        # 输出可用的 traceId 列表（去重前 10 个）
        available = sorted({e.get("traceId") for e in events if e.get("traceId")})
        if available:
            print(f"\n可用 traceId（共 {len(available)} 个，显示前 10）:", file=sys.stderr)
            for tid in available[:10]:
                print(f"  {tid}", file=sys.stderr)
        return 1

    sorted_events = sort_by_created_at(matched)
    print(f"Trace {args.trace_id}: 共 {len(sorted_events)} 个事件")
    print()

    if args.verbose:
        print("事件序列:")
        for idx, event in enumerate(sorted_events):
            print(format_event_line(event, idx))
        print()

    violations = check_order(sorted_events)

    if not violations:
        print("✓ L2 顺序契约满足")
        return 0

    print(f"✗ 发现 {len(violations)} 处顺序违规:")
    for v in violations:
        print(str(v))
    return 2


if __name__ == "__main__":
    sys.exit(main())
