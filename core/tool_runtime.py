"""
Skill Runtime Wrapper (Step 1)

统一包装所有技能调用：
  - timeout（不卡死 REPL）
  - 结构化错误（LLM 可判断是否重试）
  - 执行时长追踪
  - 超长结果截断 + artifact 存储
"""
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.artifacts import save_tool_result

DEFAULT_TIMEOUT = 30       # 秒，无 SKILL 元数据时的兜底值
MAX_INLINE_CHARS = 12_000  # 约 3000 tokens，超过则存 artifact
PREVIEW_CHARS = 400        # 截断后注入 messages 的预览长度


@dataclass
class ToolResult:
    ok: bool
    skill: str
    summary: str
    content_preview: str = ""
    artifact_path: Path | None = None
    truncated: bool = False
    tokens_estimate: int = 0
    error: dict | None = None
    meta: dict = field(default_factory=dict)

    def to_message_content(self) -> str:
        """生成注入 messages['content'] 的字符串，LLM 可直接读取。"""
        if not self.ok:
            err = self.error or {}
            return (
                f"[技能错误] {self.summary}\n"
                f"type: {err.get('type', 'Error')}\n"
                f"retryable: {err.get('retryable', False)}"
            )
        parts = [self.summary]
        if self.content_preview:
            parts.append(self.content_preview)
        if self.truncated and self.artifact_path:
            parts.append(
                f"[输出过长，完整内容已保存至 {self.artifact_path}，"
                f"约 {self.tokens_estimate} tokens]"
            )
        return "\n".join(parts)


def invoke(skill_name: str, args: dict, skills: dict,
           timeout: int | None = None) -> ToolResult:
    """调用技能并返回 ToolResult，任何情况下都不抛异常。"""
    mod = skills.get(skill_name)
    if mod is None:
        return ToolResult(
            ok=False,
            skill=skill_name,
            summary=f"技能不存在：{skill_name}",
            error={
                "type": "SkillNotFound",
                "message": f"No skill named '{skill_name}'",
                "retryable": False,
            },
        )

    skill_meta = getattr(mod, "SKILL", {})
    effective_timeout = timeout or skill_meta.get("default_timeout", DEFAULT_TIMEOUT)

    started_at = time.time()
    started_str = _fmt_ts(started_at)

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(mod.run, args)
        raw = future.result(timeout=effective_timeout)
    except FutureTimeoutError:
        executor.shutdown(wait=False)
        return ToolResult(
            ok=False,
            skill=skill_name,
            summary=f"{skill_name} 执行超时（{effective_timeout}s）",
            error={
                "type": "TimeoutError",
                "message": f"Skill exceeded timeout of {effective_timeout} seconds",
                "retryable": True,
            },
            meta=_build_meta(started_str, started_at),
        )
    except Exception as e:
        executor.shutdown(wait=False)
        return ToolResult(
            ok=False,
            skill=skill_name,
            summary=f"{skill_name} 执行失败：{type(e).__name__}",
            error={
                "type": type(e).__name__,
                "message": str(e),
                "retryable": False,
            },
            meta=_build_meta(started_str, started_at),
        )
    finally:
        executor.shutdown(wait=False)

    content = str(raw) if raw is not None else ""
    tokens_est = max(1, len(content) // 4)
    truncated = len(content) > MAX_INLINE_CHARS
    artifact_path = None

    if truncated:
        artifact_path = save_tool_result(skill_name, content)
        preview = content[:PREVIEW_CHARS] + "…"
        summary = f"{skill_name} 完成（结果较长，约 {tokens_est} tokens，已存 artifact）"
    else:
        preview = content
        summary = f"{skill_name} 完成"

    return ToolResult(
        ok=True,
        skill=skill_name,
        summary=summary,
        content_preview=preview,
        artifact_path=artifact_path,
        truncated=truncated,
        tokens_estimate=tokens_est,
        meta=_build_meta(started_str, started_at),
    )


def _fmt_ts(ts: float) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _build_meta(started_str: str, started_at: float) -> dict:
    finished_at = time.time()
    return {
        "started_at": started_str,
        "finished_at": _fmt_ts(finished_at),
        "duration_ms": int((finished_at - started_at) * 1000),
    }
