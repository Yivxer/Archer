#!/usr/bin/env python3
"""Collect stability metrics from exported eventLog + connection transitions.

Usage:
    python3 scripts/collect_metrics.py --events eventLog.json
    python3 scripts/collect_metrics.py --events eventLog.json --transitions transitions.json
    python3 scripts/collect_metrics.py --events eventLog.json --since 2026-07-01

Data sources (export from Desktop DevTools console):
    # eventLog:
    JSON.stringify(JSON.parse(localStorage.getItem('archer-runtime-events') || '[]'), null, 2)
    # connection transitions:
    JSON.stringify(JSON.parse(localStorage.getItem('archer-connection-transitions') || '[]'), null, 2)

Metrics produced:
    1. failure.hint counts by keyword (top-level + per-day)
    2. trace count + traces with failures
    3. tool.request → tool.result 闭环率
    4. dead→ready latency (from connection transitions)
    5. state distribution (time spent in each state, approximate)
    6. chat turn TTFT / total / context / tool / CPU p50+p95
    7. process peak RSS and explicit performance-terminal Trace closure

Exit codes:
    0 = 指标采集成功（即使有警告）
    1 = 参数错误 / 文件读取失败
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"错误: 无法读取 {path}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except json.JSONDecodeError as exc:
        print(f"错误: JSON 解析失败 {path}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        # 兼容带 Z 的 ISO8601
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        # naive datetime（如 "2026-07-03"）补 UTC，避免与 aware 比较报 TypeError
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def day_key(ts: str) -> str:
    dt = parse_iso(ts)
    return dt.strftime("%Y-%m-%d") if dt else "unknown"


def filter_since(events: list[dict[str, Any]], since: str) -> list[dict[str, Any]]:
    """过滤出 createdAt >= since 的事件"""
    since_dt = parse_iso(since)
    if since_dt is None:
        return events
    result = []
    for e in events:
        dt = parse_iso(e.get("createdAt", ""))
        if dt is None or dt >= since_dt:
            result.append(e)
    return result


# ───────────────────────── failure.hint 指标 ─────────────────────────

def collect_failure_hints(events: list[dict[str, Any]]) -> dict[str, Any]:
    """统计 failure.hint 事件"""
    hints = [e for e in events if e.get("type") == "failure.hint"]
    by_keyword = Counter(e.get("keyword", "<missing>") for e in hints)
    by_day = defaultdict(Counter)
    for e in hints:
        by_day[day_key(e.get("createdAt", ""))][e.get("keyword", "<missing>")] += 1

    return {
        "total": len(hints),
        "by_keyword": dict(by_keyword.most_common()),
        "by_day": {day: dict(counts) for day, counts in sorted(by_day.items())},
    }


# ───────────────────────── trace 闭环指标 ─────────────────────────

def collect_trace_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    """统计 trace 闭环：tool.request → tool.result + text.final/failure.hint"""
    traces: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "events": [],
        "has_final": False,
        "has_failure": False,
        "tool_requests": 0,
        "tool_results": 0,
        "has_performance_terminal": False,
    })
    performance_events: list[dict[str, Any]] = []

    for e in events:
        runtime = e.get("performanceEvent") or e.get("runtimeContextEvent") or e
        runtime = runtime if isinstance(runtime, dict) else e
        tid = e.get("traceId") or runtime.get("traceId")
        if not tid:
            continue
        t = traces[tid]
        t["events"].append(e)
        etype = e.get("type", "")
        if runtime.get("phase") == "performance":
            t["has_performance_terminal"] = True
            performance_events.append(runtime)
        if etype in ("text.final",):
            t["has_final"] = True
        if etype == "failure.hint":
            t["has_failure"] = True
        if etype == "tool.request":
            t["tool_requests"] += 1
        if etype == "tool.result":
            t["tool_results"] += 1

    total = len(traces)
    if total == 0:
        return {"total": 0}

    closed = sum(
        1 for t in traces.values()
        if t["has_final"] or t["has_failure"] or t["has_performance_terminal"]
    )
    failed = sum(1 for t in traces.values() if t["has_failure"])
    tool_unclosed = sum(
        1 for t in traces.values()
        if t["tool_requests"] > 0 and t["tool_requests"] > t["tool_results"]
    )

    def distribution(field: str, *, nested: str = "") -> dict[str, int]:
        raw_values = [
            (event.get(nested) or {}).get(field) if nested else event.get(field)
            for event in performance_events
        ]
        values = sorted(int(value) for value in raw_values if isinstance(value, (int, float)))
        if not values:
            return {"count": 0}
        count = len(values)
        return {
            "count": count,
            "min": values[0],
            "p50": values[min(int(count * 0.50), count - 1)],
            "p95": values[min(int(count * 0.95), count - 1)],
            "max": values[-1],
        }

    return {
        "total": total,
        "closed": closed,
        "closed_rate": f"{closed / total * 100:.1f}%" if total else "n/a",
        "with_failure": failed,
        "failure_rate": f"{failed / total * 100:.1f}%" if total else "n/a",
        "tool_unclosed": tool_unclosed,
        "performance": {
            "total_duration_ms": distribution("totalDurationMs"),
            "ttft_ms": distribution("ttftMs"),
            "context_build_ms": distribution("contextBuildMs"),
            "tool_duration_ms": distribution("toolDurationMs"),
            "cpu_time_ms": distribution("cpuTimeMs"),
            "peak_rss_bytes": distribution("peakRssBytes"),
            "prompt_tokens": distribution("promptTokens", nested="tokenUsage"),
            "completion_tokens": distribution("completionTokens", nested="tokenUsage"),
            "total_tokens": distribution("totalTokens", nested="tokenUsage"),
            "history_estimated_tokens": distribution("historyEstimatedTokens", nested="tokenUsage"),
            "compression_trigger_rate": _compression_trigger_rate(performance_events),
        },
    }


def _compression_trigger_rate(events: list[dict[str, Any]]) -> dict[str, int | str]:
    values = [
        bool(event["tokenUsage"].get("compressionTriggered"))
        for event in events if isinstance(event.get("tokenUsage"), dict)
        and "compressionTriggered" in event["tokenUsage"]
    ]
    triggered = sum(values)
    return {
        "count": len(values),
        "triggered": triggered,
        "rate": f"{triggered / len(values) * 100:.1f}%" if values else "n/a",
    }


# ───────────────────────── dead→ready 耗时 ─────────────────────────

def collect_connection_metrics(transitions: list[dict[str, Any]]) -> dict[str, Any]:
    """从连接状态转换记录计算 dead→ready / recovering→ready 恢复耗时

    恢复路径：
      - recovering → ready（自动重启）：recovery_start = 进入 recovering 的时刻
      - dead → connecting → ready（用户触发）：recovery_start = 离开 dead 的时刻
      - 不含用户在 dead 状态的等待时间（只测系统恢复速度）

    算法（状态机走法）：
      - 进入 recovering → 记 recovery_start
      - 离开 dead（from=dead）→ 记 recovery_start
      - 到达 ready 且有 recovery_start → 结算 latency，清空 start
      - 到达 dead 且无 start → 等待用户恢复（不计 start）
    """
    if not transitions:
        return {"total_transitions": 0, "note": "无转换记录（未提供 --transitions 或无数据）"}

    sorted_t = sorted(transitions, key=lambda t: t.get("at", 0))
    total = len(sorted_t)
    state_counts = Counter(t.get("to", "?") for t in sorted_t)

    recoveries = []
    recovery_start: int | None = None  # 恢复起点时间戳
    recovery_from: str | None = None   # 恢复来源（dead/recovering）

    for t in sorted_t:
        to_state = t.get("to")
        from_state = t.get("from")
        at = t.get("at", 0)

        # 进入 recovering → 自动恢复开始
        if to_state == "recovering":
            recovery_start = at
            recovery_from = "recovering"
            continue

        # 离开 dead（用户点击恢复）→ 恢复开始
        if from_state == "dead" and to_state != "dead" and recovery_start is None:
            recovery_start = at
            recovery_from = "dead"
            # 继续往下看是否到 ready

        # 到达 ready 且有恢复进行中 → 结算
        if to_state == "ready" and recovery_start is not None:
            latency_ms = at - recovery_start
            if latency_ms >= 0:
                recoveries.append({
                    "from_state": recovery_from,
                    "to_state": "ready",
                    "latency_ms": latency_ms,
                    "latency_s": round(latency_ms / 1000, 1),
                    "signal": t.get("signal", "?"),
                    "started_at": recovery_start,
                    "ready_at": at,
                })
            recovery_start = None
            recovery_from = None

        # 进入 dead 且无恢复进行中 → 等待用户（不计 start）
        if to_state == "dead" and recovery_start is None:
            pass  # 等待用户触发 user_recover

    latencies = [r["latency_ms"] for r in recoveries]
    result = {
        "total_transitions": total,
        "state_distribution": dict(state_counts.most_common()),
        "recovery_count": len(recoveries),
    }

    if latencies:
        latencies_sorted = sorted(latencies)
        n = len(latencies_sorted)
        result.update({
            "latency_min_s": round(latencies_sorted[0] / 1000, 1),
            "latency_max_s": round(latencies_sorted[-1] / 1000, 1),
            "latency_avg_s": round(sum(latencies_sorted) / n / 1000, 1),
            "latency_p50_s": round(latencies_sorted[n // 2] / 1000, 1),
            "latency_p95_s": round(latencies_sorted[min(int(n * 0.95), n - 1)] / 1000, 1),
        })
        under_10s = sum(1 for l in latencies if l <= 10_000)
        result["under_10s"] = under_10s
        result["under_10s_rate"] = f"{under_10s / n * 100:.1f}%"

    return result


# ───────────────────────── 报告输出 ─────────────────────────

def print_report(failure: dict, traces: dict, conn: dict, since: str | None) -> None:
    print("═══════════════════════════════════════════")
    print("  Archer 稳定性指标采集报告")
    print("═══════════════════════════════════════════")
    if since:
        print(f"  时间范围: 自 {since} 起")
    print()

    # failure.hint
    print("── failure.hint 统计 ──────────────────────")
    print(f"  总数: {failure['total']}")
    if failure["total"] > 0:
        print("  按 keyword 分布:")
        for kw, cnt in failure["by_keyword"].items():
            print(f"    {kw:<30} {cnt}")
        if failure["by_day"]:
            print("  按天分布:")
            for day, counts in failure["by_day"].items():
                day_total = sum(counts.values())
                print(f"    {day}: {day_total} 次")
    print()

    # trace 闭环
    print("── Trace 闭环统计 ─────────────────────────")
    if traces["total"] == 0:
        print("  无 trace 数据")
    else:
        print(f"  trace 总数: {traces['total']}")
        print(f"  闭环率: {traces['closed_rate']}（{traces['closed']}/{traces['total']}）")
        print(f"  含 failure 的 trace: {traces['with_failure']}（{traces['failure_rate']}）")
        print(f"  tool.request 未闭合: {traces['tool_unclosed']}")
        performance = traces.get("performance", {})
        if performance.get("total_duration_ms", {}).get("count", 0):
            print("  性能分位（ms，min/p50/p95/max）:")
            for label, key in (
                ("总耗时", "total_duration_ms"),
                ("TTFT", "ttft_ms"),
                ("上下文", "context_build_ms"),
                ("工具", "tool_duration_ms"),
                ("CPU", "cpu_time_ms"),
            ):
                item = performance[key]
                print(
                    f"    {label}: {item.get('min', 'n/a')}/"
                    f"{item.get('p50', 'n/a')}/{item.get('p95', 'n/a')}/"
                    f"{item.get('max', 'n/a')}"
                )
            rss = performance["peak_rss_bytes"]
            print(f"  进程 RSS 峰值: {rss.get('max', 0) / 1024 / 1024:.1f} MiB")
    print()

    # 连接状态
    print("── 连接状态恢复统计 ───────────────────────")
    if conn["total_transitions"] == 0:
        print(f"  {conn.get('note', '无数据')}")
    else:
        print(f"  转换总数: {conn['total_transitions']}")
        print(f"  状态分布: {conn.get('state_distribution', {})}")
        print(f"  恢复次数（dead/recovering → ready）: {conn['recovery_count']}")
        if conn.get("recovery_count", 0) > 0:
            print(f"  恢复耗时（秒）:")
            print(f"    min: {conn['latency_min_s']}s")
            print(f"    max: {conn['latency_max_s']}s")
            print(f"    avg: {conn['latency_avg_s']}s")
            print(f"    p50: {conn['latency_p50_s']}s")
            print(f"    p95: {conn['latency_p95_s']}s")
            print(f"  ≤10s 达标率: {conn.get('under_10s_rate', 'n/a')}（{conn.get('under_10s', 0)}/{conn['recovery_count']}）")
    print()

    # Q3 达标判定
    print("── Q3 验收门槛判定 ────────────────────────")
    weekly_failures = failure["total"]
    print(f"  故障数（≤5/周）: {weekly_failures} → {'✓ 达标' if weekly_failures <= 5 else '✗ 未达标'}")
    if conn.get("recovery_count", 0) > 0:
        under_10s_rate = conn.get("under_10s", 0) / conn["recovery_count"]
        print(f"  dead→ready≤10s: {conn.get('under_10s_rate', 'n/a')} → {'✓ 达标' if under_10s_rate >= 0.9 else '✗ 未达标（<90%）'}")
    else:
        print("  dead→ready≤10s: 无恢复数据")
    print()

    print("═══════════════════════════════════════════")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect stability metrics from eventLog + connection transitions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--events", required=True, help="eventLog JSON 文件路径")
    parser.add_argument("--transitions", help="连接状态转换 JSON 文件路径（可选）")
    parser.add_argument("--since", help="只统计此日期之后的事件（ISO8601，如 2026-07-01）")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON（便于管道处理）")
    args = parser.parse_args(argv)

    events_path = Path(args.events).expanduser()
    events = load_json(events_path)
    if not isinstance(events, list):
        print("错误: events 文件根节点必须是数组", file=sys.stderr)
        return 1

    if args.since:
        events = filter_since(events, args.since)

    transitions = []
    if args.transitions:
        tpath = Path(args.transitions).expanduser()
        transitions = load_json(tpath)
        if not isinstance(transitions, list):
            print("错误: transitions 文件根节点必须是数组", file=sys.stderr)
            return 1

    failure = collect_failure_hints(events)
    traces = collect_trace_metrics(events)
    conn = collect_connection_metrics(transitions)

    if args.json:
        print(json.dumps({
            "failure_hints": failure,
            "traces": traces,
            "connection": conn,
            "since": args.since,
        }, ensure_ascii=False, indent=2))
    else:
        print_report(failure, traces, conn, args.since)

    return 0


if __name__ == "__main__":
    sys.exit(main())
