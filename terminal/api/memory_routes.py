"""Memory, hypotheses, Vault Bridge, and sensor API domain."""

from __future__ import annotations

import re
from pathlib import Path

from terminal.api.job_routes import _create_job


# Memory routes
# ---------------------------------------------------------------------------

def _memory(limit: int = 50, include_rejected: bool = False) -> list[dict]:
    from memory.store import init_db, list_all, list_pending
    init_db()

    def _item_fields(item: dict, status: str) -> dict:
        return {
            "id": int(item["id"]),
            "status": status,
            "type": item.get("type", "insight"),
            "content": item.get("content", ""),
            "confidence": f"{float(item.get('confidence') or 0):.2f}",
            "source": item.get("source", ""),
            "sessionId": item.get("session_id", "") or "",
            "depth": int(item.get("depth") or item.get("importance") or 3),
            "blockType": item.get("block_type", "insight"),
            "label": item.get("label", ""),
        }

    confirmed = [_item_fields(item, "confirmed") for item in list_all(limit=limit)]
    pending = [
        {
            **_item_fields(item, item.get("status", "pending")),
            "suggestReason": item.get("suggest_reason", ""),
            "sessionSummary": item.get("session_summary", ""),
        }
        for item in list_pending(limit=limit, include_rejected=include_rejected)
    ]
    return [*pending, *confirmed]


def _resolve_pending_memory(memory_id: str, accepted: bool) -> dict:
    from memory.store import accept_pending, reject_pending
    if not re.fullmatch(r"[0-9]+", memory_id):
        raise ValueError("memory id must be numeric")
    if accepted:
        written_ids = accept_pending(int(memory_id))
        if not written_ids:
            return {"ok": False, "id": int(memory_id), "accepted": True, "writtenIds": []}
        return {"ok": True, "id": int(memory_id), "accepted": True, "writtenIds": written_ids}
    deleted = reject_pending(int(memory_id))
    return {"ok": bool(deleted), "id": int(memory_id), "accepted": False, "deleted": deleted}


def _hypotheses(limit: int = 50, status: str = "active") -> dict:
    from memory.hypothesis_tracker import list_hypotheses
    from memory.store import init_db

    init_db()
    return {"ok": True, "hypotheses": list_hypotheses(status=status, limit=limit)}


def _create_hypothesis(payload: dict) -> dict:
    from memory.hypothesis_tracker import create_hypothesis, get_hypothesis
    from memory.store import init_db

    init_db()
    title = str(payload.get("title", "") or "").strip()
    statement = str(payload.get("statement", "") or "").strip()
    if not title:
        raise ValueError("title is required")
    if not statement:
        raise ValueError("statement is required")

    hypothesis_id = create_hypothesis(
        title,
        statement,
        source="manual",
        trigger_type=str(payload.get("triggerType", "") or "").strip(),
        confidence=payload.get("confidence", 0.7),
        validate_after_days=payload.get("validateAfterDays", 14),
        session_id=str(payload.get("sessionId", "") or "").strip() or None,
    )
    return {"ok": True, "id": hypothesis_id, "hypothesis": get_hypothesis(hypothesis_id)}


def _import_obsidian_hypotheses(payload: dict, cfg: dict) -> dict:
    from memory.hypothesis_tracker import import_hypotheses_from_obsidian
    from memory.store import init_db

    init_db()
    vault_path = cfg.get("obsidian", {}).get("vault_path", "")
    return import_hypotheses_from_obsidian(
        vault_path,
        days=payload.get("days", 30),
        validate_after_days=payload.get("validateAfterDays", 14),
        limit=payload.get("limit", 20),
    )


def _vault_reflection(payload: dict) -> dict:
    """触发 Vault Bridge 笔记结晶（Phase 2）。

    支持两种模式：
    - path: 对单篇笔记做结晶
    - days: 扫描最近 N 天修改的笔记批量结晶

    当 background=true 时，创建 kind=vault_reflection 的后台 job，立即返回 jobId。
    """
    note_path = (payload.get("path") or "").strip()
    days = payload.get("days")
    force = bool(payload.get("force", False))
    background = bool(payload.get("background", False))

    if background:
        # 后台 job 化：把参数打包进 vaultArgs，由 _run_job 分派到 _execute_vault_reflection
        vault_args: dict = {"force": force}
        if note_path:
            vault_args["note_path"] = note_path
            title = f"Vault 结晶：{Path(note_path).name}"
        elif days is not None:
            try:
                days_int = int(days)
            except (TypeError, ValueError):
                days_int = 7
            try:
                max_notes = int(payload.get("maxNotes", 5))
            except (TypeError, ValueError):
                max_notes = 5
            vault_args["days"] = days_int
            vault_args["maxNotes"] = max_notes
            title = f"Vault 结晶：最近 {days_int} 天"
        else:
            return {"ok": False, "error": "需要 path（单篇笔记）或 days（扫描最近 N 天）参数"}

        create_payload = {
            "title": title,
            "kind": "vault_reflection",
            "prompt": title,  # prompt 必填，vault_reflection 不使用但需通过校验
            "vaultArgs": vault_args,
            "timeoutSeconds": int(payload.get("timeoutSeconds", 600)),
        }
        created = _create_job(create_payload)
        return {"ok": True, "background": True, "job": created.get("job", {})}

    # 同步执行
    from workflows.vault_reflection import reflect_on_note, reflect_on_recent

    if note_path:
        result = reflect_on_note(note_path, force=force)
    elif days is not None:
        try:
            days_int = int(days)
        except (TypeError, ValueError):
            days_int = 7
        try:
            max_notes = int(payload.get("maxNotes", 5))
        except (TypeError, ValueError):
            max_notes = 5
        # 进度回调：记录到日志，便于排查长时间阻塞
        progress_log: list[dict] = []
        def _on_progress(p: dict) -> None:
            progress_log.append(p)
            print(f"[vault_reflection] {p['done']}/{p['total']} {p['note_path']} ok={p['ok']}")
        result = reflect_on_recent(
            days=days_int, max_notes=max_notes, force=force,
            progress_callback=_on_progress,
        )
        result["progress"] = progress_log
    else:
        return {"ok": False, "error": "需要 path（单篇笔记）或 days（扫描最近 N 天）参数"}

    return result


def _list_recent_reflections(limit: int = 20) -> dict:
    """返回最近的 vault_reflection 结晶记录。"""
    from workflows.vault_reflection import list_recent_reflections

    return {"ok": True, "reflections": list_recent_reflections(limit)}


def _vault_refresh_index(force: bool = False) -> dict:
    """刷新 vault 笔记索引。"""
    from knowledge.vault_sensor import refresh_index

    return refresh_index(force=force)


def _vault_current_focus(detect: bool = False) -> dict:
    """获取/检测当前 focus 的笔记。

    detect=True 时主动调用 detect_current_focus()；
    否则返回上次缓存的 focus 状态。
    """
    from knowledge.vault_sensor import get_current_focus, detect_current_focus

    if detect:
        return detect_current_focus()
    return get_current_focus()


def _sensor_obsidian_focus(payload: dict) -> dict:
    """Receive an explicit focus event from an Obsidian sensor/plugin."""
    from knowledge.vault_sensor import ingest_focus_event

    return ingest_focus_event(payload)


def _sensors_status() -> dict:
    from knowledge.vault_sensor import get_current_focus

    return {"ok": True, "obsidian": get_current_focus()}


def _vault_search_index(keyword: str = "", limit: int = 20) -> dict:
    """从索引搜索笔记（不读文件）。"""
    from knowledge.vault_sensor import search_indexed_notes

    return {"ok": True, "notes": search_indexed_notes(keyword=keyword, limit=limit)}


def _batch_resolve_pending(accepted: bool) -> dict:
    from memory.store import accept_pending, reject_pending
    if accepted:
        written_ids = accept_pending("all")
        return {"ok": True, "accepted": True, "writtenIds": written_ids, "count": len(written_ids)}
    deleted = reject_pending("all")
    return {"ok": True, "accepted": False, "deleted": deleted}


# ---------------------------------------------------------------------------

