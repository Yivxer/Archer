"""I/O-backed context assembly stages for Desktop chat turns."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable
from uuid import uuid4


MAX_FILE_REF_BYTES = 1_000_000


@dataclass(frozen=True, slots=True)
class ContextAssemblyResult:
    messages: list[dict]
    events: list[dict]


def file_reference_context(
    file_refs: list[dict],
    *,
    event_factory: Callable[..., dict],
    allowed_extensions: set[str] | frozenset[str],
    per_file_limit: int = 6000,
    total_limit: int = 12000,
    max_file_bytes: int = MAX_FILE_REF_BYTES,
) -> tuple[str, list[dict]]:
    events: list[dict] = []
    sections: list[str] = []
    used = 0
    for idx, ref in enumerate(file_refs):
        path_value = str(ref.get("path", ""))
        display_name = str(ref.get("name") or Path(path_value).name or "未命名文件")
        event_id = f"file-reference-{idx + 1}"
        draft = {"path": path_value, "title": display_name, "size": ref.get("size", 0)}
        events.append(event_factory(
            event_id, "file.reference", "running", "low",
            f"读取本地文件：{display_name}", path_value, draft=draft,
        ))
        try:
            declared_size = int(ref.get("size") or 0)
            if declared_size > max_file_bytes:
                events.append(event_factory(
                    event_id, "file.reference", "blocked", "low",
                    f"已跳过超大文件：{display_name}",
                    f"file size limit exceeded: {declared_size} > {max_file_bytes}",
                    draft=draft,
                ))
                continue
            path = Path(path_value).expanduser()
            suffix = path.suffix.lower()
            if suffix and suffix not in allowed_extensions:
                events.append(event_factory(
                    event_id, "file.reference", "blocked", "low",
                    f"已跳过非文本文件：{display_name}", f"extension: {suffix}",
                    draft=draft,
                ))
                continue
            if not path.exists() or not path.is_file():
                events.append(event_factory(
                    event_id, "file.reference", "blocked", "low",
                    f"文件不可读取：{display_name}", "file not found", draft=draft,
                ))
                continue
            if used >= total_limit:
                events.append(event_factory(
                    event_id, "file.reference", "blocked", "low",
                    f"已跳过文件：{display_name}", "total file reference limit reached",
                    draft=draft,
                ))
                continue
            preloaded_text = ref.get("content")
            if isinstance(preloaded_text, str) and preloaded_text:
                raw_text = preloaded_text
                source_detail = "preloaded"
                preloaded_truncated = bool(ref.get("truncated"))
            else:
                raw_text = path.read_text(encoding="utf-8", errors="ignore")
                source_detail = "disk"
                preloaded_truncated = False
            if "\x00" in raw_text[:2048]:
                events.append(event_factory(
                    event_id, "file.reference", "blocked", "low",
                    f"已跳过疑似二进制文件：{display_name}", "binary-like content",
                    draft=draft,
                ))
                continue
            remaining = max(0, total_limit - used)
            limit = min(per_file_limit, remaining)
            text = raw_text[:limit]
            used += len(text)
            truncated = preloaded_truncated or len(raw_text) > len(text)
            sections.append(
                f"### {display_name}\npath: {path}\nsource: {source_detail}\n"
                f"truncated: {str(truncated).lower()}\n\n{text}"
            )
            done_draft = {
                **draft,
                "contentPreview": text[:500],
                "injectedChars": len(text),
                "truncated": truncated,
            }
            events.append(event_factory(
                event_id, "file.reference", "complete", "low",
                f"已注入本地文件：{display_name}",
                f"injected_chars: {len(text)}, truncated: {truncated}",
                draft=done_draft,
            ))
        except Exception as exc:
            events.append(event_factory(
                event_id, "file.reference", "blocked", "low",
                f"文件引用失败：{display_name}", str(exc)[:240], draft=draft,
            ))
    if not sections:
        return "", events
    return (
        "以下是用户在桌面端明确选择并引用的本地文本文件内容。"
        "只在回答当前问题明显相关时使用；如果内容被截断，需要说明只能基于片段判断。\n\n"
        + "\n\n---\n\n".join(sections),
        events,
    )


def assemble_memory_context(
    messages: list[dict],
    *,
    query: str,
    prior_history: list[dict],
    intent: str,
    needs_memory: bool,
    memory_mode: str,
    retrieve_limit: int,
    expert: dict,
    event_factory: Callable[..., dict],
    augment_query: Callable | None = None,
    retrieve: Callable | None = None,
    format_retrieval: Callable | None = None,
    expert_tags: Callable | None = None,
) -> ContextAssemblyResult:
    if memory_mode == "off":
        return ContextAssemblyResult(
            messages,
            [event_factory(
                "memory-retrieve", "memory.retrieve", "complete", "low",
                "记忆上下文已关闭", "mode: off, injected: False",
            )],
        )
    if memory_mode == "conservative" and not needs_memory:
        return ContextAssemblyResult(
            messages,
            [event_factory(
                "memory-retrieve", "memory.retrieve", "complete", "low",
                "保守模式：本轮未触发记忆检索",
                f"mode: {memory_mode}, intent: {intent}, needs_memory: False",
            )],
        )

    events = [event_factory(
        "memory-retrieve", "memory.retrieve", "running", "low",
        "检索与当前输入相关的本地记忆",
        f"mode: {memory_mode}, scope: local memory, limit: {retrieve_limit}",
    )]
    try:
        if augment_query is None:
            from core.context import augment_retrieval_query

            augment_query = augment_retrieval_query
        if retrieve is None or format_retrieval is None:
            from memory.retrieve import for_context, format_for_prompt

            retrieve = retrieve or for_context
            format_retrieval = format_retrieval or format_for_prompt
        if expert_tags is None:
            from core.experts import expert_memory_tags

            expert_tags = expert_memory_tags
        retrieval_kwargs = {
            "limit": retrieve_limit,
            "intent": intent,
            "tag_hints": expert_tags(expert) or None,
        }
        rewritten_query = augment_query(query, prior_history)
        try:
            core, related = retrieve(rewritten_query, **retrieval_kwargs)
        except TypeError as exc:
            if "tag_hints" not in str(exc):
                raise
            retrieval_kwargs.pop("tag_hints", None)
            core, related = retrieve(rewritten_query, **retrieval_kwargs)
        memory_context = format_retrieval(core, related)
        enriched = messages
        if memory_context:
            enriched = [{
                "role": "system",
                "content": (
                    "以下是 Archer 本地记忆检索结果。只在明显相关时使用；"
                    "不要主动逐条展示记忆内容，也不要声称已经展示全部记忆。\n\n"
                    f"{memory_context}"
                ),
            }, *messages]
        events.append(event_factory(
            "memory-retrieve", "memory.retrieve", "complete", "low",
            "已完成本地记忆检索",
            f"mode: {memory_mode}, core: {len(core)}, related: {len(related)}, injected: {bool(memory_context)}",
        ))
        return ContextAssemblyResult(enriched, events)
    except Exception as exc:
        events.append(event_factory(
            "memory-retrieve", "memory.retrieve", "blocked", "low",
            "本地记忆检索失败，已跳过", str(exc)[:240],
        ))
        return ContextAssemblyResult(messages, events)


def assemble_obsidian_context(
    messages: list[dict],
    *,
    query: str,
    obsidian_mode: str,
    preview_requested: bool,
    event_factory: Callable[..., dict],
    extract_target_path: Callable[[str], str | None],
    search: Callable | None = None,
    read: Callable | None = None,
    event_id_factory: Callable[[], str] | None = None,
) -> ContextAssemblyResult:
    if obsidian_mode == "off":
        return ContextAssemblyResult(messages, [event_factory(
            "obsidian-search", "obsidian_search", "complete", "low",
            "Obsidian 搜索上下文已关闭", "mode: off",
        )])

    events: list[dict] = []
    if search is None:
        from skills.obsidian_search import run as obsidian_search

        search = obsidian_search
    if event_id_factory is None:
        event_id_factory = lambda: uuid4().hex[:8]

    if obsidian_mode in ("summary", "full") and preview_requested:
        events.append(event_factory(
            "obsidian-search", "obsidian_search", "running", "low",
            "检索 Obsidian 笔记", f"mode: {obsidian_mode}, max_results: 5",
        ))
        try:
            result = str(search({"keyword": query[:80], "max_results": 5}))
            events.append(event_factory(
                "obsidian-search", "obsidian_search", "complete", "low",
                "Obsidian 搜索完成", f"mode: {obsidian_mode}, {result[:300]}",
            ))
            targeted_path = extract_target_path(query)
            has_targeted = bool(
                targeted_path
                and targeted_path != "Archer/客户端写入草稿.md"
            )
            injected_read = False
            enriched = messages
            if has_targeted:
                try:
                    if read is None:
                        from skills.obsidian_read import run as obsidian_read

                        read = obsidian_read
                    content = str(read({"path": targeted_path, "max_chars": 6000}))
                    if not content.startswith(("路径被拒绝", "笔记不存在")):
                        enriched = [{
                            "role": "system",
                            "content": (
                                "用户指定读取以下 Obsidian 笔记，请基于此内容回答：\n\n"
                                f"### {targeted_path}\n{content}"
                            ),
                        }, *messages]
                        injected_read = True
                        events.append(event_factory(
                            f"obsidian-read-{event_id_factory()}",
                            "obsidian_read", "complete", "low",
                            f"已读取并注入：{targeted_path}",
                            f"path: {targeted_path}, chars: {len(content)}",
                        ))
                except Exception:
                    pass
            if obsidian_mode == "full" and not injected_read:
                note_paths = re.findall(r"  - (.+\.md)", result)
                context_parts: list[str] = []
                if note_paths:
                    if read is None:
                        from skills.obsidian_read import run as obsidian_read

                        read = obsidian_read
                    for note_path in note_paths[:3]:
                        try:
                            content = read({"path": note_path, "max_chars": 3000})
                            context_parts.append(f"### {note_path}\n{content}")
                        except Exception:
                            continue
                if context_parts:
                    obsidian_context = (
                        "以下是 Obsidian vault 中与当前对话相关的笔记内容。"
                        "请在回答时参考这些笔记，但不要逐条陈列搜索结果。\n\n"
                        + "\n\n---\n\n".join(context_parts)
                    )
                    enriched = [{"role": "system", "content": obsidian_context}, *messages]
                elif "未找到" not in result:
                    enriched = [{
                        "role": "system",
                        "content": f"Obsidian vault 搜索结果：\n{result}",
                    }, *messages]
            return ContextAssemblyResult(enriched, events)
        except Exception as exc:
            events.append(event_factory(
                "obsidian-search", "obsidian_search", "blocked", "low",
                f"Obsidian 搜索{'失败' if obsidian_mode == 'full' else '预览失败'}",
                str(exc)[:240],
            ))
            return ContextAssemblyResult(messages, events)

    if obsidian_mode == "full":
        events.append(event_factory(
            "obsidian-search", "obsidian_search", "running", "low",
            "检索 Obsidian 笔记（full 模式）",
            f"mode: full, keyword: {query[:80]}",
        ))
        try:
            result = str(search({"keyword": query[:80], "max_results": 5}))
            events.append(event_factory(
                "obsidian-search", "obsidian_search", "complete", "low",
                "Obsidian 搜索完成", f"mode: full, {result[:300]}",
            ))
            enriched = messages
            if "未找到" not in result:
                enriched = [{
                    "role": "system",
                    "content": f"Obsidian vault 搜索结果：\n{result}",
                }, *messages]
            return ContextAssemblyResult(enriched, events)
        except Exception as exc:
            events.append(event_factory(
                "obsidian-search", "obsidian_search", "blocked", "low",
                "Obsidian 搜索失败", str(exc)[:240],
            ))
    return ContextAssemblyResult(messages, events)
