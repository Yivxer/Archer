"""Terminal events emitted after a model turn finishes."""

from __future__ import annotations

from uuid import uuid4


def empty_reply_events(*, had_tool_activity: bool, trace_id: str) -> list[dict]:
    return [
        {"type": "token", "text": (
            "已执行操作，详见上方卡片。" if had_tool_activity
            else "模型没有返回内容，请打开诊断查看原因。"
        )},
        {"type": "failureHintEvent", "failureHintEvent": {
            "id": f"failure-hint-{uuid4().hex[:8]}",
            "traceId": trace_id,
            "keyword": "tool_executed_no_summary" if had_tool_activity else "model_empty_response",
            "stage": "model_stream",
            "recoverable": True,
            "detail": (
                "工具事件已产生，但模型没有返回总结文本。" if had_tool_activity
                else "模型请求结束但没有返回可显示文本。"
            ),
        }},
    ]
