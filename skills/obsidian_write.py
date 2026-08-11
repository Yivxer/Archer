from __future__ import annotations

import hashlib
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from core.runtime_cancellation import CancellationToken
from skills._vault import (
    parse_frontmatter as _parse_frontmatter,
    read_note as _read_note,
    resolve_note_path as _resolve_note_path,
)

# per-path 写入锁：防止同一篇笔记多个确认卡并发点确认时
# 两次写入都通过 mtime 校验然后都落盘（mtime 校验是第二道防线，锁是第一道）。
_WRITE_LOCKS: dict[str, threading.Lock] = {}
_WRITE_LOCKS_GUARD = threading.Lock()
_WRITE_RESULT_CACHE: dict[str, tuple[float, str]] = {}
WRITE_RESULT_CACHE_TTL_SECONDS = 10 * 60
DESTRUCTIVE_MODES = {"overwrite", "prepend", "section"}
LONG_NOTE_BACKUP_LINE_THRESHOLD = 30


def _content_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _get_write_lock(path_key: str) -> threading.Lock:
    """获取某篇笔记的写入锁（per-path，避免不同笔记互相阻塞）。"""
    with _WRITE_LOCKS_GUARD:
        lock = _WRITE_LOCKS.get(path_key)
        if lock is None:
            lock = threading.Lock()
            _WRITE_LOCKS[path_key] = lock
        return lock


def _write_fingerprint(path: Path, *, mode: str, content: str, heading: str, add_ts: bool) -> str:
    payload = "\0".join([
        str(path.resolve()),
        mode,
        heading,
        "1" if add_ts else "0",
        content,
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cached_write_result(fingerprint: str) -> str | None:
    cached = _WRITE_RESULT_CACHE.get(fingerprint)
    if not cached:
        return None
    created_at, output = cached
    if time.time() - created_at > WRITE_RESULT_CACHE_TTL_SECONDS:
        _WRITE_RESULT_CACHE.pop(fingerprint, None)
        return None
    return "复用最近一次写入结果（写入指纹未变化）。\n" + output


def _remember_write_result(fingerprint: str, output: str) -> None:
    if output.startswith(("写入已取消", "写入失败", "错误：", "路径被拒绝", "未找到章节")):
        return
    _WRITE_RESULT_CACHE[fingerprint] = (time.time(), output)


def _backup_note_before_destructive_write(path: Path, existing: str) -> str | None:
    if not existing or len(existing.splitlines()) <= LONG_NOTE_BACKUP_LINE_THRESHOLD:
        return None
    backup_dir = path.parent / ".archer-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = backup_dir / f"{path.stem}.{stamp}.bak{path.suffix or '.md'}"
    backup_path.write_text(existing, encoding="utf-8")
    return str(backup_path)

SKILL = {
    "name": "obsidian_write",
    "description": "写入或追加内容到 Obsidian vault 中的笔记",
    "version": "1.2.0",
    "risk": "medium",
    "requires_confirmation": False,
}

__meta__ = {
    "name": "obsidian_write",
    "description": "写入或追加 Obsidian 笔记",
    "keywords": ["写入笔记", "obsidian", "记录到", "写回", "vault", "追加到章节"],
    "risk": "medium",
    "auto_trigger": True,
}

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "obsidian_write",
            "description": (
                "向 Obsidian vault 中的笔记写入内容。\n"
                "- mode=append: 在文件末尾追加（默认）\n"
                "- mode=overwrite: 覆盖整个文件\n"
                "- mode=prepend: 在正文开头插入（跳过 frontmatter）\n"
                "- mode=section: 插入到指定 heading 章节下方（需配合 heading 参数）\n"
                "若笔记不存在会自动创建。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "笔记路径（相对 vault 或绝对路径）",
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入的内容",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["append", "overwrite", "prepend", "section"],
                        "description": "写入模式，默认 append",
                    },
                    "heading": {
                        "type": "string",
                        "description": "mode=section 时的目标章节标题文本（不含 # 号），找到该 heading 后在其下方插入",
                    },
                    "add_timestamp": {
                        "type": "boolean",
                        "description": "追加时是否自动加时间戳，默认 false",
                    },
                },
                "required": ["path", "content"],
            },
        },
    }

def _run_unchecked(args: dict) -> str:
    raw_path = args.get("path", "").strip()
    content = args.get("content", "")
    mode = args.get("mode", "append")
    heading = (args.get("heading") or "").strip()
    add_ts = args.get("add_timestamp", False)
    # 预览阶段记录的 mtime，用于检测预览后文件是否被外部修改
    expected_mtime = args.get("expected_mtime")
    expected_size = args.get("expected_size")
    expected_fingerprint = args.get("expected_fingerprint")
    expected_exists = args.get("expected_exists")

    if mode == "section" and not heading:
        return "错误：mode=section 时必须指定 heading 参数"

    try:
        p = _resolve_note_path(raw_path)
    except Exception as e:
        return f"路径被拒绝：{e}"

    # per-path 锁：覆盖 mtime 校验 + 实际写入，确保同一笔记串行落盘
    lock = _get_write_lock(str(p.resolve()))
    with lock:
        try:
            write_fingerprint = _write_fingerprint(
                p,
                mode=mode,
                content=content,
                heading=heading,
                add_ts=bool(add_ts),
            )
            cached = _cached_write_result(write_fingerprint)
            if cached:
                return cached

            p.parent.mkdir(parents=True, exist_ok=True)

            if (
                expected_exists is not None
                and p.exists() != bool(expected_exists)
            ):
                return (
                    f"写入已取消：笔记「{p.name}」在预览后"
                    f"{'被创建' if p.exists() else '被删除'}，请重新生成确认卡。"
                )

            # mtime 校验：预览后文件被外部修改则拒绝写入
            if expected_mtime is not None and p.exists():
                current_stat = p.stat()
                current_mtime = current_stat.st_mtime
                if abs(current_mtime - float(expected_mtime)) > 0.001:
                    return (
                        f"写入已取消：笔记「{p.name}」在预览后被外部修改"
                        f"（预览 mtime={float(expected_mtime):.3f}，当前 mtime={current_mtime:.3f}），"
                        "请重新生成确认卡。"
                    )
                if expected_size is not None and current_stat.st_size != int(expected_size):
                    return (
                        f"写入已取消：笔记「{p.name}」在预览后大小发生变化"
                        f"（预览 size={int(expected_size)}，当前 size={current_stat.st_size}），"
                        "请重新生成确认卡。"
                    )
                if expected_fingerprint is not None:
                    current_fingerprint = _content_fingerprint(_read_note(p))
                    if current_fingerprint != str(expected_fingerprint):
                        return (
                            f"写入已取消：笔记「{p.name}」在预览后内容指纹发生变化，"
                            "请重新生成确认卡。"
                        )
            elif mode in DESTRUCTIVE_MODES and p.exists():
                return (
                    f"写入已取消：{mode} 写已有笔记必须携带 expected_mtime，"
                    "请先重新生成确认卡。"
                )

            ts_prefix = ""
            if add_ts:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M")
                ts_prefix = f"\n<!-- {ts} -->\n"

            final_content = ts_prefix + content

            if mode == "overwrite":
                existing = _read_note(p) if p.exists() else ""
                existing_lines = len(existing.splitlines()) if existing else 0
                backup_path = _backup_note_before_destructive_write(p, existing)
                p.write_text(final_content, encoding="utf-8")
                output = f"已覆盖写入：{p.name}（原 {existing_lines} 行）"
                if backup_path:
                    output += f"；已备份到 {backup_path}"
                _remember_write_result(write_fingerprint, output)
                return output

            # 其他模式需要读现有内容
            existing = _read_note(p) if p.exists() else ""

            if mode == "section":
                result = _insert_under_heading(existing, heading, final_content)
                if result is None:
                    return f"未找到章节「{heading}」，写入失败"
                existing_lines = len(existing.splitlines()) if existing else 0
                backup_path = _backup_note_before_destructive_write(p, existing)
                p.write_text(result, encoding="utf-8")
                output = f"已插入到章节「{heading}」下：{p.name}（原 {existing_lines} 行）"
                if backup_path:
                    output += f"；已备份到 {backup_path}"
                _remember_write_result(write_fingerprint, output)
                return output

            if mode == "prepend":
                # 跳过 frontmatter，在正文开头插入
                if existing:
                    _, body_start = _parse_frontmatter(existing)
                    # body_start 是去掉 frontmatter 后的正文，但我们需要原始文本的插入点
                    # 用正则找到第二个 --- 的位置
                    fm_match = re.match(r"^---\s*\n.*?\n---\s*\n", existing, re.DOTALL)
                    if fm_match:
                        insert_pos = fm_match.end()
                        new_text = existing[:insert_pos] + final_content + "\n" + existing[insert_pos:]
                    else:
                        new_text = final_content + "\n" + existing
                else:
                    new_text = final_content
                existing_lines = len(existing.splitlines()) if existing else 0
                backup_path = _backup_note_before_destructive_write(p, existing)
                p.write_text(new_text, encoding="utf-8")
                output = f"已在开头插入内容：{p.name}（原 {existing_lines} 行）"
                if backup_path:
                    output += f"；已备份到 {backup_path}"
                _remember_write_result(write_fingerprint, output)
                return output

            # 默认 append
            with open(p, "a", encoding="utf-8") as f:
                f.write("\n" + final_content)
            output = f"已追加到：{p.name}"
            _remember_write_result(write_fingerprint, output)
            return output

        except Exception as e:
            return f"写入失败：{e}"


def run(args: dict) -> str:
    return _run_unchecked(args)


def run_cancelable(args: dict, cancellation_token: CancellationToken) -> str:
    with cancellation_token.side_effect_guard() as allowed:
        if not allowed:
            return "写入已取消：Runtime cancellation requested before side effect"
        return _run_unchecked(args)


def _structured_result(args: dict, output: str) -> dict:
    ok = not output.startswith(("错误：", "路径被拒绝", "写入失败", "写入已取消", "未找到章节"))
    metadata: dict = {}
    if ok:
        raw_path = str(args.get("path", "")).strip()
        mode = str(args.get("mode", "append"))
        try:
            target = _resolve_note_path(raw_path)
            exists = target.exists()
            verification = f"文件存在：{target}" if exists else f"文件未确认存在：{target}"
        except Exception:
            target = Path(raw_path)
            verification = output
        backup = ""
        match = re.search(r"已备份到\s+(.+)$", output)
        if match:
            backup = match.group(1).strip()
        metadata["workReceipt"] = {
            "done": output.splitlines()[0],
            "source": "Archer 生成内容",
            "target": str(target),
            "verification": verification,
            "rollback": backup or "append 可手动删除新增段落；覆盖/插入模式会在长笔记写入前生成备份",
            "traceId": str(args.get("traceId") or ""),
        }
        metadata["path"] = str(target)
        metadata["mode"] = mode
    return {
        "ok": ok,
        "summary": "obsidian_write 完成" if ok else "obsidian_write 失败",
        "output": output,
        "metadata": metadata,
    }


def run_structured(args: dict) -> dict:
    return _structured_result(args, run(args))


def run_structured_cancelable(
    args: dict,
    cancellation_token: CancellationToken,
) -> dict:
    return _structured_result(args, run_cancelable(args, cancellation_token))


def _insert_under_heading(text: str, heading_text: str, content: str) -> str | None:
    """在指定 heading 下方插入内容。

    找到第一个匹配的 heading（任意层级），在其下一行插入。
    如果该 heading 下已有内容，插到现有内容之前（heading 紧下方）。
    未找到返回 None。
    """
    heading_lower = heading_text.strip().lower()
    if not heading_lower:
        return None

    # 匹配任意层级的 markdown heading
    pattern = re.compile(
        r"^(#{1,6})\s+" + re.escape(heading_lower) + r"\s*#*\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    m = pattern.search(text)
    if not m:
        return None

    insert_pos = m.end()
    # 跳过 heading 行末尾换行
    if insert_pos < len(text) and text[insert_pos] == "\n":
        insert_pos += 1

    return text[:insert_pos] + content + "\n" + text[insert_pos:]


def compute_preview(args: dict, *, limit: int = 2000) -> dict:
    """计算写入前后的文本预览，不落盘。

    用于确认卡展示 diff：读取现有笔记内容（before），
    按 mode 计算写入后的文本（after），截断到 limit 字符。

    返回 {"before": str, "after": str, "mode": str, "path": str,
           "exists": bool, "mtime": float | None, "size": int | None,
           "fingerprint": str | None}。
    mtime/size/fingerprint 为预览时文件状态，run() 落盘前会重读对比，
    不一致则拒绝写入以防覆盖外部修改。
    路径无效或文件不存在时 before 为空字符串，不抛异常。
    """
    raw_path = str(args.get("path", "")).strip()
    content = str(args.get("content", ""))
    mode = str(args.get("mode", "append"))
    heading = str(args.get("heading") or "").strip()

    try:
        p = _resolve_note_path(raw_path)
    except Exception:
        return {"before": "", "after": content[:limit], "mode": mode, "path": raw_path, "exists": False, "mtime": None, "size": None, "fingerprint": None}

    exists = p.exists()
    existing = _read_note(p) if exists else ""
    stat = p.stat() if exists else None
    mtime = stat.st_mtime if stat else None
    size = stat.st_size if stat else None
    fingerprint = _content_fingerprint(existing) if exists else None

    ts_prefix = ""
    if args.get("add_timestamp"):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        ts_prefix = f"\n<!-- {ts} -->\n"
    final_content = ts_prefix + content

    after = ""
    if mode == "overwrite":
        after = final_content
    elif mode == "section" and heading:
        result = _insert_under_heading(existing, heading, final_content)
        after = result if result is not None else existing
    elif mode == "prepend":
        if existing:
            fm_match = re.match(r"^---\s*\n.*?\n---\s*\n", existing, re.DOTALL)
            if fm_match:
                after = existing[:fm_match.end()] + final_content + "\n" + existing[fm_match.end():]
            else:
                after = final_content + "\n" + existing
        else:
            after = final_content
    else:  # append
        after = existing + "\n" + final_content if existing else final_content

    return {
        "before": existing[:limit],
        "after": after[:limit],
        "mode": mode,
        "path": raw_path,
        "exists": exists,
        "mtime": mtime,
        "size": size,
        "fingerprint": fingerprint,
    }
