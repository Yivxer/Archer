"""
test_obsidian_write_preview.py — Obsidian 写回强确认 diff 预览测试

覆盖：
- compute_preview 不落盘（文件内容不变）
- append mode：before=现有内容，after=现有+新内容
- overwrite mode：before=现有内容，after=新内容
- prepend mode：before=现有内容，after=新内容+现有（跳 frontmatter）
- section mode：在 heading 下方插入
- 文件不存在：before=空，after=新内容
- 路径无效：before=空，after=新内容，不抛异常
- limit 截断
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _patch_vault(monkeypatch, vault: Path):
    import skills._vault as vmod
    monkeypatch.setattr(vmod, "read_vault_path", lambda: vault)
    monkeypatch.setattr(vmod, "resolve_vault", lambda: vault)


def test_compute_preview_does_not_write(tmp_path, monkeypatch):
    """compute_preview 不应落盘修改文件。"""
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("# 原始内容\n\n这是现有笔记。", encoding="utf-8")
    _patch_vault(monkeypatch, vault)

    from skills.obsidian_write import compute_preview
    result = compute_preview({"path": "note.md", "content": "新内容", "mode": "append"})

    # 文件内容不应被修改
    assert note.read_text(encoding="utf-8") == "# 原始内容\n\n这是现有笔记。"
    assert result["exists"] is True


def test_compute_preview_append(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("现有内容", encoding="utf-8")
    _patch_vault(monkeypatch, vault)

    from skills.obsidian_write import compute_preview
    result = compute_preview({"path": "note.md", "content": "新内容", "mode": "append"})

    assert result["before"] == "现有内容"
    assert "现有内容" in result["after"]
    assert "新内容" in result["after"]
    assert result["mode"] == "append"
    assert result["exists"] is True


def test_compute_preview_overwrite(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("旧内容将被替换", encoding="utf-8")
    _patch_vault(monkeypatch, vault)

    from skills.obsidian_write import compute_preview
    result = compute_preview({"path": "note.md", "content": "全新内容", "mode": "overwrite"})

    assert result["before"] == "旧内容将被替换"
    assert result["after"] == "全新内容"
    assert "旧内容" not in result["after"]


def test_compute_preview_prepend_skips_frontmatter(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text(
        "---\ntitle: 测试\ntags: [a]\n---\n\n正文内容",
        encoding="utf-8",
    )
    _patch_vault(monkeypatch, vault)

    from skills.obsidian_write import compute_preview
    result = compute_preview({"path": "note.md", "content": "插入到开头", "mode": "prepend"})

    # before 应包含 frontmatter
    assert "title: 测试" in result["before"]
    # after 应在 frontmatter 之后、正文之前插入
    assert "插入到开头" in result["after"]
    assert "title: 测试" in result["after"]
    assert "正文内容" in result["after"]
    # frontmatter 应在插入内容之前
    assert result["after"].index("title: 测试") < result["after"].index("插入到开头")


def test_compute_preview_section_inserts_under_heading(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text(
        "# 标题\n\n现有段落\n\n## 章节\n\n旧内容\n",
        encoding="utf-8",
    )
    _patch_vault(monkeypatch, vault)

    from skills.obsidian_write import compute_preview
    result = compute_preview({
        "path": "note.md",
        "content": "新插入内容",
        "mode": "section",
        "heading": "章节",
    })

    assert "新插入内容" in result["after"]
    assert "旧内容" in result["after"]
    # 插入位置应在 "## 章节" 之后
    assert result["after"].index("## 章节") < result["after"].index("新插入内容")


def test_compute_preview_file_not_exists(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    _patch_vault(monkeypatch, vault)

    from skills.obsidian_write import compute_preview
    result = compute_preview({"path": "新笔记.md", "content": "全新内容", "mode": "append"})

    assert result["before"] == ""
    assert result["after"] == "全新内容"
    assert result["exists"] is False


def test_compute_preview_invalid_path_no_crash(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    _patch_vault(monkeypatch, vault)

    from skills.obsidian_write import compute_preview
    # 路径含穿透尝试，resolve_note_path 应拒绝
    result = compute_preview({"path": "../../etc/passwd", "content": "恶意", "mode": "append"})

    assert result["before"] == ""
    assert result["exists"] is False
    assert result["mode"] == "append"


def test_compute_preview_limit_truncates(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    long_content = "x" * 5000
    (vault / "note.md").write_text(long_content, encoding="utf-8")
    _patch_vault(monkeypatch, vault)

    from skills.obsidian_write import compute_preview
    result = compute_preview(
        {"path": "note.md", "content": "y" * 5000, "mode": "append"},
        limit=100,
    )

    assert len(result["before"]) <= 100
    assert len(result["after"]) <= 100


# ── 集成：_obsidian_write_draft 注入 before/after ────────────────────────

def test_obsidian_write_draft_includes_before_after(tmp_path, monkeypatch):
    """验证 _obsidian_write_draft 返回的 draft 包含 beforeText/afterText。"""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "日记.md").write_text("今天的原始内容", encoding="utf-8")
    _patch_vault(monkeypatch, vault)

    from terminal.api._tools import _obsidian_write_draft
    draft = _obsidian_write_draft("把追加的新内容写到日记.md")

    assert draft["path"] == "日记.md"
    assert draft["mode"] == "append"
    assert "beforeText" in draft
    assert "afterText" in draft
    assert "今天的原始内容" in draft["beforeText"]
    assert "今天的原始内容" in draft["afterText"]
    assert "追加的新内容" in draft["afterText"]
    assert draft["previewExists"] is True


def test_obsidian_edit_request_generates_overwrite_preview_draft(tmp_path, monkeypatch):
    """修改/润色明确 md 路径时，应生成 overwrite 预览而不是 append。"""
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "文章 初稿.md"
    note.write_text("---\ntitle: 旧标题\n---\n# 旧标题\n\n原始正文。", encoding="utf-8")
    _patch_vault(monkeypatch, vault)

    from terminal.api._tools import _obsidian_write_draft
    draft = _obsidian_write_draft(f"帮我润色一下{note}")

    assert draft["path"] == str(note)
    assert draft["mode"] == "overwrite"
    assert draft["previewMode"] == "overwrite"
    assert "原始正文" in draft["beforeText"]
    assert "Archer Desktop 自动写入" not in draft["afterText"]


def test_chat_stream_generates_overwrite_confirmation_for_obsidian_edit(tmp_path, monkeypatch):
    """聊天里的文章调整请求应生成写回确认卡，且不直接改动原文。"""
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "文章 初稿.md"
    original = "---\ntitle: 旧标题\n---\n# 旧标题\n\n原始正文。"
    note.write_text(original, encoding="utf-8")
    _patch_vault(monkeypatch, vault)

    def fake_stream(messages, **kwargs):
        last = str(messages[-1].get("content", ""))
        if "生成写入 Obsidian 的笔记" in last:
            yield "---\ntitle: 新标题\n---\n# 新标题\n\n润色后的正文。"
        else:
            yield "我会给出修改预览。"

    monkeypatch.setattr("core.llm.stream_chat", fake_stream)
    monkeypatch.setattr("core.writing.load_writing_prompt_blocks", lambda cfg, kind: [])

    from terminal.api import _tools as tools

    events = list(tools._iter_chat_chunks(
        [{"role": "user", "content": f"帮我润色一下{note}"}],
        memory_mode="off",
        obsidian_mode="off",
    ))

    write_events = [
        event["toolEvent"]
        for event in events
        if event.get("type") == "tool_event"
        and event.get("toolEvent", {}).get("name") == "obsidian_write"
    ]
    assert write_events
    write_event = write_events[-1]
    assert write_event["status"] == "waiting"
    assert write_event["requiresApproval"] is True
    draft = write_event["draft"]
    assert draft["args"]["mode"] == "overwrite"
    assert "原始正文" in draft["beforeText"]
    assert "润色后的正文" in draft["afterText"]
    assert note.read_text(encoding="utf-8") == original


# ── mtime 校验：防预览后外部修改被覆盖 ──────────────────────────────────

def test_compute_preview_returns_mtime(tmp_path, monkeypatch):
    """compute_preview 返回 mtime/size/fingerprint 字段，文件存在时有值，不存在时为 None。"""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("existing", encoding="utf-8")
    _patch_vault(monkeypatch, vault)

    from skills.obsidian_write import compute_preview
    result_exists = compute_preview({"path": "note.md", "content": "new", "mode": "append"})
    assert result_exists["mtime"] is not None
    assert isinstance(result_exists["mtime"], float)
    assert result_exists["size"] == len("existing".encode("utf-8"))
    assert isinstance(result_exists["fingerprint"], str)
    assert len(result_exists["fingerprint"]) == 64

    result_missing = compute_preview({"path": "新笔记.md", "content": "new", "mode": "append"})
    assert result_missing["mtime"] is None
    assert result_missing["size"] is None
    assert result_missing["fingerprint"] is None


def test_run_rejects_write_when_mtime_changed(tmp_path, monkeypatch):
    """预览后文件被外部修改（mtime 变化），run() 应拒绝写入。"""
    import time
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("原始内容", encoding="utf-8")
    _patch_vault(monkeypatch, vault)

    from skills.obsidian_write import compute_preview, run
    preview = compute_preview({"path": "note.md", "content": "追加", "mode": "append"})
    old_mtime = preview["mtime"]

    # 模拟用户在 Obsidian 里手动改了笔记，mtime 变化
    time.sleep(0.01)
    note.write_text("用户手动改了", encoding="utf-8")

    result = run({
        "path": "note.md",
        "content": "追加",
        "mode": "append",
        "expected_mtime": old_mtime,
    })

    assert "写入已取消" in result
    assert "外部修改" in result
    # 文件内容不应被覆盖
    assert note.read_text(encoding="utf-8") == "用户手动改了"


def test_run_allows_write_when_mtime_unchanged(tmp_path, monkeypatch):
    """mtime 未变化时，run() 应正常写入。"""
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("原始内容", encoding="utf-8")
    _patch_vault(monkeypatch, vault)

    from skills.obsidian_write import compute_preview, run
    preview = compute_preview({"path": "note.md", "content": "追加", "mode": "append"})

    result = run({
        "path": "note.md",
        "content": "追加",
        "mode": "append",
        "expected_mtime": preview["mtime"],
    })

    assert "已追加" in result
    assert "原始内容" in note.read_text(encoding="utf-8")
    assert "追加" in note.read_text(encoding="utf-8")


def test_run_rejects_write_when_fingerprint_changed_but_size_matches(tmp_path, monkeypatch):
    """mtime/size 相同但内容指纹不同，应拒绝写入，避免等长替换绕过校验。"""
    import os
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("abcdef", encoding="utf-8")
    _patch_vault(monkeypatch, vault)

    from skills.obsidian_write import compute_preview, run
    preview = compute_preview({"path": "note.md", "content": "追加", "mode": "append"})

    note.write_text("uvwxyz", encoding="utf-8")
    os.utime(note, (preview["mtime"], preview["mtime"]))

    result = run({
        "path": "note.md",
        "content": "追加",
        "mode": "append",
        "expected_mtime": preview["mtime"],
        "expected_size": preview["size"],
        "expected_fingerprint": preview["fingerprint"],
    })

    assert "写入已取消" in result
    assert "内容指纹" in result
    assert note.read_text(encoding="utf-8") == "uvwxyz"


def test_run_allows_write_without_expected_mtime(tmp_path, monkeypatch):
    """未提供 expected_mtime（旧调用方）时，run() 应正常写入，保持向后兼容。"""
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("原始内容", encoding="utf-8")
    _patch_vault(monkeypatch, vault)

    from skills.obsidian_write import run
    result = run({"path": "note.md", "content": "追加", "mode": "append"})

    assert "已追加" in result
    assert "追加" in note.read_text(encoding="utf-8")


def test_run_reuses_duplicate_append_by_idempotency_fingerprint(tmp_path, monkeypatch):
    """同一目标/模式/内容短时间重复提交，不应重复写入。"""
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("原始内容", encoding="utf-8")
    _patch_vault(monkeypatch, vault)

    from skills import obsidian_write
    obsidian_write._WRITE_RESULT_CACHE.clear()

    first = obsidian_write.run({"path": "note.md", "content": "追加", "mode": "append"})
    second = obsidian_write.run({"path": "note.md", "content": "追加", "mode": "append"})

    assert "已追加" in first
    assert "复用最近一次写入结果" in second
    assert note.read_text(encoding="utf-8").count("追加") == 1


def test_run_rejects_destructive_write_without_expected_mtime(tmp_path, monkeypatch):
    """overwrite/prepend/section 写已有笔记必须来自预览卡，避免无上下文覆盖。"""
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("原始内容", encoding="utf-8")
    _patch_vault(monkeypatch, vault)

    from skills.obsidian_write import run
    result = run({"path": "note.md", "content": "覆盖内容", "mode": "overwrite"})

    assert "写入已取消" in result
    assert "expected_mtime" in result
    assert note.read_text(encoding="utf-8") == "原始内容"


def test_run_backs_up_long_note_before_destructive_write(tmp_path, monkeypatch):
    """超过 30 行的已有笔记，破坏性写入前应自动备份。"""
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    original = "\n".join(f"line {i}" for i in range(35))
    note.write_text(original, encoding="utf-8")
    _patch_vault(monkeypatch, vault)

    from skills.obsidian_write import compute_preview, run
    preview = compute_preview({"path": "note.md", "content": "覆盖内容", "mode": "overwrite"})
    result = run({
        "path": "note.md",
        "content": "覆盖内容",
        "mode": "overwrite",
        "expected_mtime": preview["mtime"],
    })

    backups = list((vault / ".archer-backups").glob("note.*.bak.md"))
    assert "已覆盖写入" in result
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original
    assert note.read_text(encoding="utf-8") == "覆盖内容"


# ── P0-2: per-path 写入并发锁 ──────────────────────────────────────────────────

def test_get_write_lock_same_path_returns_same_lock(tmp_path):
    """同一路径应返回同一个 Lock 对象。"""
    from skills.obsidian_write import _get_write_lock
    key = str(tmp_path / "note.md")
    lock1 = _get_write_lock(key)
    lock2 = _get_write_lock(key)
    assert lock1 is lock2


def test_get_write_lock_different_paths_return_different_locks(tmp_path):
    """不同路径应返回不同 Lock 对象，避免互相阻塞。"""
    from skills.obsidian_write import _get_write_lock
    lock_a = _get_write_lock(str(tmp_path / "a.md"))
    lock_b = _get_write_lock(str(tmp_path / "b.md"))
    assert lock_a is not lock_b


def test_concurrent_append_writes_do_not_lose_content(tmp_path, monkeypatch):
    """两个线程并发 append 同一笔记，最终内容应包含两次写入，不丢内容。

    锁确保 read-modify-write（append 模式走 open(a) 不 read，但其他模式会 read；
    这里用 append 做行为 smoke，验证锁不破坏正常并发写入）。
    """
    import threading
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("BASE", encoding="utf-8")
    _patch_vault(monkeypatch, vault)

    from skills.obsidian_write import run

    results: list[str] = []
    results_lock = threading.Lock()

    def worker(content):
        r = run({"path": "note.md", "content": content, "mode": "append"})
        with results_lock:
            results.append(r)

    t1 = threading.Thread(target=worker, args=("AAA",))
    t2 = threading.Thread(target=worker, args=("BBB",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # 两个写入都成功
    assert all("已追加" in r for r in results), f"unexpected: {results}"
    # 最终内容包含两次写入 + 原始内容
    final = note.read_text(encoding="utf-8")
    assert "BASE" in final
    assert "AAA" in final
    assert "BBB" in final


def test_concurrent_prepend_with_same_preview_allows_only_one_write(tmp_path, monkeypatch):
    """两个 prepend 使用同一个预览 mtime 时，只允许一个落盘。

    prepend 是 read-modify-write。破坏性写入必须来自预览卡；
    第一笔写入后 mtime 改变，第二笔应取消，避免基于旧预览覆盖新内容。
    """
    import threading
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("BASE", encoding="utf-8")
    _patch_vault(monkeypatch, vault)

    from skills.obsidian_write import compute_preview, run
    preview = compute_preview({"path": "note.md", "content": "AAA", "mode": "prepend"})

    results: list[str] = []
    results_lock = threading.Lock()

    def worker(content):
        r = run({
            "path": "note.md",
            "content": content,
            "mode": "prepend",
            "expected_mtime": preview["mtime"],
            "expected_size": preview["size"],
        })
        with results_lock:
            results.append(r)

    t1 = threading.Thread(target=worker, args=("AAA",))
    t2 = threading.Thread(target=worker, args=("BBB",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert sum("已在开头插入" in r for r in results) == 1, f"unexpected: {results}"
    assert sum("写入已取消" in r for r in results) == 1, f"unexpected: {results}"
    final = note.read_text(encoding="utf-8")
    assert "BASE" in final
    assert ("AAA" in final) != ("BBB" in final)


def test_concurrent_writes_different_notes_do_not_block(tmp_path, monkeypatch):
    """不同笔记的写入不应互相阻塞（per-path 锁，不是全局锁）。"""
    import threading
    import time
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "a.md").write_text("a-base", encoding="utf-8")
    (vault / "b.md").write_text("b-base", encoding="utf-8")
    _patch_vault(monkeypatch, vault)

    from skills.obsidian_write import run

    # 在 run 里注入一个 sleep hook 不容易，改用直接验证最终结果：
    # 两个不同笔记并发写入都成功
    results: list[str] = []
    results_lock = threading.Lock()

    def worker(path, content):
        r = run({"path": path, "content": content, "mode": "append"})
        with results_lock:
            results.append(r)

    t1 = threading.Thread(target=worker, args=("a.md", "AAA"))
    t2 = threading.Thread(target=worker, args=("b.md", "BBB"))
    start = time.time()
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    elapsed = time.time() - start

    # 两个写入都成功
    assert all("已追加" in r for r in results)
    # 不同笔记的锁不互相阻塞，总耗时应该很短（< 2s，留足余量）
    assert elapsed < 2.0, f"concurrent writes took too long: {elapsed}s"
    # 内容正确
    assert "AAA" in (vault / "a.md").read_text(encoding="utf-8")
    assert "BBB" in (vault / "b.md").read_text(encoding="utf-8")
