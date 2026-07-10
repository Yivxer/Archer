"""P5.2 — Active memory compaction (archive low-value memories + summary)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta

ACTIVE_COUNT_THRESHOLD = int(os.getenv("ARCHER_MEMORY_COMPACT_ACTIVE", "200"))
PENDING_COUNT_THRESHOLD = int(os.getenv("ARCHER_MEMORY_COMPACT_PENDING", "30"))
ARCHIVE_BATCH_SIZE = 15
MIN_CANDIDATES = 5

_PROTECTED_TYPES = frozenset({
    "identity",
    "preference",
    "decision",
    "value",
    "life_theme",
    "self_narrative",
    "project_mythology",
    "reflection_anchor",
})


@dataclass(frozen=True)
class CompactionResult:
    triggered: bool
    reason: str
    archived_count: int
    archived_ids: list[int]
    summary_id: int | None


def should_compact(
    *,
    active_count: int | None = None,
    pending_count: int | None = None,
) -> tuple[bool, str]:
    from memory.store import count_active, count_pending

    active = active_count if active_count is not None else count_active()
    pending = pending_count if pending_count is not None else count_pending()
    if active >= ACTIVE_COUNT_THRESHOLD:
        return True, f"active_count={active}"
    if pending >= PENDING_COUNT_THRESHOLD:
        return True, f"pending_count={pending}"
    return False, ""


def heuristic_archive_score(memory: dict) -> float:
    """Higher score = safer to keep active."""
    score = float(memory.get("importance", 3)) * 2.0
    score += float(memory.get("depth", 3))

    last_used = memory.get("last_used_at") or memory.get("created_at")
    if last_used:
        try:
            age = datetime.now() - datetime.fromisoformat(last_used)
            if age <= timedelta(days=7):
                score += 4
            elif age <= timedelta(days=30):
                score += 2
        except Exception:
            pass

    if memory.get("type") in _PROTECTED_TYPES:
        score += 20
    if memory.get("importance", 3) >= 4:
        score += 10
    if memory.get("depth", 3) >= 4:
        score += 8
    return score


def select_archive_candidates(
    candidates: list[dict],
    *,
    limit: int = ARCHIVE_BATCH_SIZE,
) -> list[dict]:
    scored = sorted(candidates, key=heuristic_archive_score)
    selected: list[dict] = []
    for memory in scored:
        if heuristic_archive_score(memory) >= 14:
            continue
        selected.append(memory)
        if len(selected) >= limit:
            break
    return selected


def _template_summary(memories: list[dict]) -> str:
    lines = [f"- [{m.get('type', 'insight')}] {m['content']}" for m in memories[:12]]
    blob = "\n".join(lines)
    return f"【记忆整理摘要】共归档 {len(memories)} 条旧记忆。\n{blob[:600]}"


def summarize_archived_memories(memories: list[dict], *, use_llm: bool = True) -> str:
    if not memories:
        return ""
    if not use_llm:
        return _template_summary(memories)

    blob = "\n".join(
        f"- [{m.get('type', 'insight')}] {m['content'][:200]}"
        for m in memories[:12]
    )
    try:
        from memory.llm_port import stream_chat

        messages = [
            {
                "role": "system",
                "content": (
                    "把以下将被归档的旧记忆压缩成一段中文摘要，保留关键事实与决策，"
                    "500 字以内，不要列表逐条复述。"
                ),
            },
            {"role": "user", "content": blob},
        ]
        result = ""
        for chunk in stream_chat(messages, track_usage=False):
            result += chunk
        summary = result.strip()
        if len(summary) >= 20:
            return summary
    except Exception:
        pass
    return _template_summary(memories)


def maybe_compact_memories(
    *,
    force: bool = False,
    use_llm_summary: bool = True,
) -> CompactionResult | None:
    from memory.store import archive, list_compaction_candidates, save

    triggered, reason = should_compact()
    if not triggered and not force:
        return None

    candidates = list_compaction_candidates(limit=ARCHIVE_BATCH_SIZE * 3)
    if len(candidates) < MIN_CANDIDATES and not force:
        return None

    to_archive = select_archive_candidates(candidates)
    if not to_archive:
        if force and candidates:
            to_archive = candidates[: min(3, len(candidates))]
        else:
            return None

    archived_ids: list[int] = []
    for memory in to_archive:
        if archive(memory["id"]):
            archived_ids.append(memory["id"])

    summary_id = None
    if archived_ids:
        summary_text = summarize_archived_memories(to_archive, use_llm=use_llm_summary)
        summary_id = save(
            summary_text,
            type="insight",
            importance=4,
            depth=3,
            source="compaction",
            block_type="insight",
            tags="compaction,summary",
        )

    return CompactionResult(
        triggered=True,
        reason=reason or "forced",
        archived_count=len(archived_ids),
        archived_ids=archived_ids,
        summary_id=summary_id,
    )
