"""记忆系统命令。"""
from __future__ import annotations

from .registry import register
from memory.store import (
    save, list_all, list_by_type, search, delete,
    update as update_memory, archive as archive_memory,
    add_pending, list_pending, count_pending, update_pending, accept_pending, reject_pending,
    count_soul_proposals,
)
from memory.soul import (
    propose_from_memories, propose_from_obsidian_hints, get_pending as get_soul_pending,
    accept as soul_accept, reject as soul_reject,
)
from terminal.ui import (
    _mem_type_rich, _memory_list, _memory_search, _memory_add,
    _memory_pending, _memory_pending_review,
    _memory_accept, _memory_reject, _memory_update,
    _memory_archive, _memory_delete, _memory_review,
)

def _handle_memory(parts: list[str], session=None):
    sub = parts[1] if len(parts) > 1 else ""
    arg = " ".join(parts[2:])
    match sub:
        case "list":   _memory_list()
        case "search": _memory_search(arg)
        case "add":    _memory_add(arg)
        case "pending": _memory_pending(arg)
        case "accept": _memory_accept(arg)
        case "reject": _memory_reject(arg)
        case "update": _memory_update(arg)
        case "archive": _memory_archive(arg)
        case "delete": _memory_delete(arg)
        case "review": _memory_review()
        case "extract":
            history = session.history if session else []
            if len(history) < 2:
                console.print("[dim]对话历史不足，无法提炼。[/dim]")
            else:
                _wait_for_extract()
                _auto_extract(history, silent=False)
        case "export":
            _memory_export(arg)
        case "reindex":
            console.print("[dim]正在重建向量索引（首次需要下载模型 ~120 MB）…[/dim]")
            try:
                from memory.vector_store import reindex_all
                ok, total = reindex_all()
                console.print(f"[green]向量索引重建完成：{ok}/{total} 条记忆已编码。[/green]")
            except Exception as e:
                console.print(f"[yellow]向量索引失败（sqlite-vec 或 sentence-transformers 未安装？）：{e}[/yellow]")
        case "stale":
            from memory.store import freshness_check, list_stale, refresh_memory
            if arg and arg.isdigit():
                ok = refresh_memory(int(arg))
                console.print(f"[dim]记忆 #{arg} 已刷新。[/dim]" if ok else f"[dim]记忆 #{arg} 不存在或非过期状态。[/dim]")
            else:
                new_stale = freshness_check()
                stale_list = list_stale()
                if not stale_list:
                    console.print("[dim]没有过期记忆。[/dim]")
                else:
                    for m in stale_list[:20]:
                        meta = " [dim]新标记[/dim]" if any(s['id'] == m['id'] for s in new_stale) else ""
                        console.print(f"  [dim]{m['id']:>4}[/dim]  [dim]{m['type']:<10}[/dim]  {m['content'][:70]}{meta}")
                    console.print(f"  [dim]共 {len(stale_list)} 条过期记忆。刷新：/memory stale <ID>[/dim]")
        case "contradictions":
            from memory.store import list_contradictions, resolve_contradiction
            parts_after = parts[2:] if len(parts) > 2 else []
            if len(parts_after) >= 2 and parts_after[0] == "resolve":
                cid = int(parts_after[1])
                keep = int(parts_after[2]) if len(parts_after) > 2 else 0
                if keep:
                    ok = resolve_contradiction(cid, keep)
                    console.print(f"[dim]矛盾 #{cid} 已解决。[/dim]" if ok else f"[dim]矛盾 #{cid} 不存在。[/dim]")
                else:
                    console.print("[yellow]用法：/memory contradictions resolve <矛盾ID> <保留的记忆ID>[/yellow]")
            else:
                contradictions = list_contradictions()
                if not contradictions:
                    console.print("[dim]没有未解决的矛盾。[/dim]")
                else:
                    for c in contradictions:
                        console.print(f"  [#c44e00]矛盾 #{c['id']}[/#c44e00]  [dim]{c['created_at']}[/dim]")
                        console.print(f"    A [dim]#{c['memory_a']}[/dim]: {c['content_a']}")
                        console.print(f"    B [dim]#{c['memory_b']}[/dim]: {c['content_b']}")
                        console.print(f"    [dim]裁决：/memory contradictions resolve {c['id']} <保留ID>[/dim]")
                        console.print()
        case _:
            console.print("[dim]子命令：list · search <词> · add <内容> · export [路径] · pending [review] · accept · reject · update · archive · delete · review · extract · reindex · stale · contradictions[/dim]")

def _handle_soul(parts: list[str], cfg: dict):
    soul_path = cfg.get("persona", {}).get("soul_path", "")
    sub = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""

    match sub:
        case "" | "list":
            proposals = get_soul_pending()
            if not proposals:
                console.print("[dim]没有待审阅的 SOUL 演化提议。[/dim]")
                return
            console.print(f"\n[bold cyan]SOUL 演化提议[/bold cyan]  [dim]（{len(proposals)} 条待审阅）[/dim]\n")
            for p in proposals:
                console.print(f"  [dim]{p['id']}[/dim]  [yellow]{p['created_at'][:16]}[/yellow]  [{p['source']}]")
                console.print(f"    {p['content']}\n")
            console.print("[dim]/soul accept <ID|all> 写入SOUL.md · /soul reject <ID|all> 丢弃[/dim]")

        case "accept":
            if not arg:
                console.print("[yellow]用法：/soul accept <ID|all>[/yellow]")
                return
            if not soul_path:
                console.print("[red]未配置 soul_path，请在 archer.toml 的 [persona] 中设置。[/red]")
                return
            pid = arg if arg == "all" else arg
            if pid != "all" and not pid.isdigit():
                console.print("[yellow]ID 应为数字或 all[/yellow]")
                return
            ids, written = soul_accept(pid, soul_path)
            if not ids:
                console.print("[yellow]没有匹配的待审阅提议。[/yellow]")
                return
            console.print(f"[green]已追加 {len(ids)} 条内容到 SOUL.md：[/green]")
            for w in written:
                console.print(f"  · {w[:72]}")

        case "reject":
            if not arg:
                console.print("[yellow]用法：/soul reject <ID|all>[/yellow]")
                return
            pid = arg if arg == "all" else arg
            if pid != "all" and not pid.isdigit():
                console.print("[yellow]ID 应为数字或 all[/yellow]")
                return
            ids = soul_reject(pid)
            console.print(f"[dim]已丢弃 {len(ids)} 条 SOUL 演化提议。[/dim]")

        case "view":
            if not soul_path:
                console.print("[red]未配置 soul_path[/red]")
                return
            p = Path(soul_path).expanduser()
            if not p.exists():
                console.print(f"[yellow]SOUL.md 不存在：{soul_path}[/yellow]")
                return
            text = p.read_text(encoding="utf-8")
            # 只显示末尾演化记录部分，避免刷屏
            if "## 演化记录" in text:
                idx = text.rfind("## 演化记录")
                snippet = text[max(0, idx - 50):]
                console.print(f"[dim]… （仅显示最近演化记录）[/dim]\n")
                console.print(snippet[:1200], markup=False)
            else:
                console.print(f"[dim]SOUL.md 中暂无演化记录。文件路径：{soul_path}[/dim]")

        case _:
            console.print("[dim]子命令：list · accept <ID|all> · reject <ID|all> · view[/dim]")

def _handle_insight(parts: list[str]):
    """洞察记录查看：list / recent / search <词>。"""
    sub = parts[1] if len(parts) > 1 else "list"
    arg = " ".join(parts[2:]).strip()

    match sub:
        case "list" | "":
            items = list_by_type("insight", min_importance=3, limit=15)
            if not items:
                console.print("[dim]还没有洞察记录（importance >= 3）。对话中被触动时会自动记录，或用 /memory add 手动添加 insight 类型。[/dim]")
                return
            console.print(f"\n[bold cyan]洞察记录[/bold cyan]  [dim]（最近 {len(items)} 条）[/dim]\n")
            for m in items:
                stars = "★" * min(m.get("importance", 3), 5)
                date = (m.get("created_at") or "")[:10]
                console.print(f"  [dim]{m['id']}[/dim]  [{stars}]  {m['content']}  [dim]{date}[/dim]")
            console.print()

        case "recent":
            items = list_by_type("insight", min_importance=1, limit=10)
            if not items:
                console.print("[dim]还没有洞察记录。[/dim]")
                return
            console.print(f"\n[bold cyan]近期洞察[/bold cyan]  [dim]（最近 {len(items)} 条）[/dim]\n")
            for m in items:
                stars = "★" * min(m.get("importance", 3), 5)
                date = (m.get("created_at") or "")[:10]
                console.print(f"  [dim]{m['id']}[/dim]  [{stars}]  {m['content']}  [dim]{date}[/dim]")
            console.print()

        case "search":
            if not arg:
                console.print("[yellow]用法：/insight search <关键词>[/yellow]")
                return
            raw = search(arg, limit=10)
            items = [m for m in raw if m.get("type") == "insight"]
            if not items:
                console.print(f"[dim]没有找到包含「{arg}」的洞察记录。[/dim]")
                return
            console.print(f"\n[bold cyan]洞察搜索：{arg}[/bold cyan]\n")
            for m in items:
                stars = "★" * min(m.get("importance", 3), 5)
                date = (m.get("created_at") or "")[:10]
                console.print(f"  [dim]{m['id']}[/dim]  [{stars}]  {m['content']}  [dim]{date}[/dim]")
            console.print()

        case _:
            console.print("[dim]子命令：list · recent · search <词>[/dim]")


# ── 命令注册 ──────────────────────────────────────────────────────────────────

def _cmd_memory(ctx):
    _handle_memory(ctx['parts'], ctx['session'])


def _cmd_soul(ctx):
    _handle_soul(ctx['parts'], ctx['cfg'])


def _cmd_insight(ctx):
    _handle_insight(ctx['parts'])


register("/memory", _cmd_memory, "管理记忆库")
register("/soul", _cmd_soul, "查看 SOUL 演化提议")
register("/insight", _cmd_insight, "查看正向洞察记录")
