"""
Step 0 — Smoke Tests
不依赖 LLM 连接，只验证核心模块可正常导入和基础功能可用。
"""
import json
import sys
import tempfile
from pathlib import Path

# 确保项目根目录在 path 中
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ─── 1. Config ────────────────────────────────────────────────────────────────

def test_config_loads():
    """archer.toml 可正常解析。"""
    import tomllib
    cfg_path = ROOT / "archer.toml"
    assert cfg_path.exists(), "archer.toml 不存在"
    with open(cfg_path, "rb") as f:
        cfg = tomllib.load(f)
    assert "api" in cfg, "缺少 [api] 段"
    assert "model" in cfg["api"], "缺少 api.model"
    assert "persona" in cfg, "缺少 [persona] 段"
    assert "memory" in cfg, "缺少 [memory] 段"


# ─── 2. Session ───────────────────────────────────────────────────────────────

def test_session_add_and_save():
    """Session 可添加对话并保存为 JSON 文件。"""
    import importlib, types

    # 临时替换 SESSIONS_DIR，避免写入真实目录
    with tempfile.TemporaryDirectory() as tmp:
        import core.session as sess_mod
        original_dir = sess_mod.SESSIONS_DIR
        sess_mod.SESSIONS_DIR = Path(tmp)

        try:
            from core.session import Session
            s = Session()
            s.add("你好", "嗨，有什么我可以帮你的？")
            assert len(s.history) == 2
            assert s.history[0]["role"] == "user"
            assert s.history[1]["role"] == "assistant"

            saved = s.save()
            assert saved.exists(), "会话文件未生成"
            data = json.loads(saved.read_text(encoding="utf-8"))
            assert len(data) == 2
        finally:
            sess_mod.SESSIONS_DIR = original_dir


def test_session_clear():
    """Session.clear() 清空 history。"""
    with tempfile.TemporaryDirectory() as tmp:
        import core.session as sess_mod
        sess_mod.SESSIONS_DIR = Path(tmp)
        from core.session import Session
        s = Session()
        s.add("a", "b")
        s.clear()
        assert s.history == []


# ─── 3. Memory ────────────────────────────────────────────────────────────────

def test_memory_init_and_crud():
    """Memory DB 可初始化、写入、查询、更新、归档。"""
    with tempfile.TemporaryDirectory() as tmp:
        import memory.store as store_mod
        original_path = store_mod.DB_PATH
        store_mod.DB_PATH = Path(tmp) / "test.db"

        try:
            store_mod.init_db()

            # save
            mid = store_mod.save("测试记忆内容", tags="test", type="insight", importance=3)
            assert isinstance(mid, int) and mid > 0

            # list
            mems = store_mod.list_all(10)
            assert any(m["id"] == mid for m in mems)

            # search（trigram 需至少 3 个字符成索引）
            results = store_mod.search("测试记忆")
            assert any(m["id"] == mid for m in results), \
                f"search 未返回 id={mid}，结果：{results}"

            # update
            ok = store_mod.update(mid, "更新后的内容")
            assert ok

            # archive
            ok = store_mod.archive(mid)
            assert ok
            mems_after = store_mod.list_all(10)
            assert not any(m["id"] == mid for m in mems_after)

        finally:
            store_mod.DB_PATH = original_path


def test_memory_dedup():
    """相同内容写入两次，只保留一条。"""
    with tempfile.TemporaryDirectory() as tmp:
        import memory.store as store_mod
        store_mod.DB_PATH = Path(tmp) / "dedup.db"
        store_mod.init_db()

        mid1 = store_mod.save("重复内容", importance=3)
        mid2 = store_mod.save("重复内容", importance=5)
        assert mid1 == mid2, "相同内容应该返回同一 ID"


# ─── 4. Skills Loader ─────────────────────────────────────────────────────────

def test_skills_load():
    """skills 目录下的技能可正常加载，且每个技能包含必要字段。"""
    from skills.loader import load_skills
    skills = load_skills()
    assert isinstance(skills, dict), "load_skills 应返回 dict"
    assert len(skills) > 0, "至少应有一个技能"

    for name, mod in skills.items():
        assert hasattr(mod, "SKILL"), f"技能 {name} 缺少 SKILL 元数据"
        assert hasattr(mod, "schema"), f"技能 {name} 缺少 schema()"
        assert hasattr(mod, "run"), f"技能 {name} 缺少 run()"
        s = mod.schema()
        assert s.get("type") == "function", f"技能 {name} schema type 应为 function"
        assert "function" in s, f"技能 {name} schema 缺少 function 键"


def test_skills_tools_format():
    """get_tools 输出格式符合 OpenAI function calling 规范。"""
    from skills.loader import load_skills, get_tools
    skills = load_skills()
    tools = get_tools(skills)
    assert isinstance(tools, list)
    for t in tools:
        assert t.get("type") == "function"
        fn = t.get("function", {})
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn


# ─── 5. File Ref ──────────────────────────────────────────────────────────────

def test_file_ref_no_refs():
    """普通输入不含 @路径，解析结果为空 refs。"""
    from core.file_ref import parse_refs
    text, refs = parse_refs("你好，今天天气怎么样？")
    assert text == "你好，今天天气怎么样？"
    assert refs == []


def test_file_ref_with_valid_file():
    """@有效路径 能正确解析并注入文件内容。"""
    from core.file_ref import parse_refs
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                    delete=False, encoding="utf-8") as f:
        f.write("这是测试文件内容")
        fpath = f.name
    try:
        text, refs = parse_refs(f"请总结 @{fpath}")
        assert len(refs) == 1
        assert refs[0]["type"] == "text"
        assert "这是测试文件内容" in refs[0]["content"]
    finally:
        Path(fpath).unlink(missing_ok=True)


# ─── Runner ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_config_loads,
        test_session_add_and_save,
        test_session_clear,
        test_memory_init_and_crud,
        test_memory_dedup,
        test_skills_load,
        test_skills_tools_format,
        test_file_ref_no_refs,
        test_file_ref_with_valid_file,
    ]

    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
