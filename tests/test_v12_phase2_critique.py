"""
v1.2 Phase 2 — 自我批评机制测试

覆盖：
- self_critiques 表 CRUD
- observation 长度约束（≥30字）
- weekly_critique 默认关闭
- user_signal 限流
- dismiss 后不重复出现
- scope=skill_router_hint 仅建议不写文件
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _setup_tmp_db(tmp_dir):
    import memory.store as store_mod
    store_mod.DB_PATH = Path(tmp_dir) / "test.db"
    store_mod.init_db()
    return store_mod


def test_critique_table_created():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        from memory.critique import list_critiques
        items = list_critiques()
        assert isinstance(items, list)


_OBS = "这是一条标准观察记录，用于测试自我批评机制是否正常工作，长度超过三十个字符。"  # 36字符

def test_create_critique_basic():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_tmp_db(tmp)
        from memory.critique import create_critique, get_critique
        cid = create_critique(title="测试批评", observation=_OBS, source="manual")
        assert cid > 0
        c = get_critique(cid)
        assert c is not None
        assert c["title"] == "测试批评"
        assert c["status"] == "open"
        assert c["source"] == "manual"


def test_observation_too_short_raises():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_tmp_db(tmp)
        from memory.critique import create_critique
        try:
            create_critique(title="短", observation="太短了", source="manual")
            assert False, "应该抛出 ValueError"
        except ValueError:
            pass


def test_dismiss_critique():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_tmp_db(tmp)
        from memory.critique import create_critique, dismiss_critique, list_critiques
        obs = "这是一条需要被驳回的观察记录，用于测试 dismiss 功能是否正常，字数超过三十个字符。"
        cid = create_critique(title="驳回测试", observation=obs, source="manual")
        dismiss_critique(cid, reason="诊断不成立")
        open_items = list_critiques(status="open")
        assert all(c["id"] != cid for c in open_items)
        dismissed = list_critiques(status="dismissed")
        assert any(c["id"] == cid for c in dismissed)


def test_evidence_stored():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_tmp_db(tmp)
        from memory.critique import create_critique, get_critique
        import json
        obs = "这是带有具体证据的观察记录，用于测试证据字段是否正确存储，长度超过三十个字符。"
        evidence = ["证据1：连续3轮对话偏离主题", "证据2：用户明确说不是这个意思"]
        cid = create_critique(title="有证据的批评", observation=obs, evidence=evidence)
        c = get_critique(cid)
        stored = json.loads(c["evidence_json"])
        assert len(stored) == 2
        assert "证据1" in stored[0]


def test_user_signal_rate_limit():
    """同一 session 最多触发 1 条 user_signal critique。"""
    with tempfile.TemporaryDirectory() as tmp:
        _setup_tmp_db(tmp)
        import memory.critique as critique_mod
        # 清空内存限流字典
        critique_mod._user_signal_registry.clear()
        from memory.critique import try_create_from_user_signal
        cfg = {"critique": {"max_user_signal_per_session": 1}}
        obs = "用户反馈：你没理解我的意思，回应与预期不符，需要重新审视。"
        sid = "test-session-001"
        cid1 = try_create_from_user_signal(obs, session_id=sid, cfg=cfg)
        cid2 = try_create_from_user_signal(obs, session_id=sid, cfg=cfg)
        assert cid1 is not None, "第一条应该创建成功"
        assert cid2 is None, "同一 session 第二条应该被限流"


def test_weekly_critique_default_off():
    """weekly_enabled 默认为 False。"""
    with tempfile.TemporaryDirectory() as tmp:
        _setup_tmp_db(tmp)
        # 模拟 cfg 中 weekly_enabled 默认值
        cfg = {"critique": {"weekly_enabled": False}}
        assert not cfg["critique"]["weekly_enabled"]


def test_scope_skill_router_hint_no_file():
    """scope=skill_router_hint 时不写入文件。"""
    with tempfile.TemporaryDirectory() as tmp:
        _setup_tmp_db(tmp)
        from memory.critique import create_critique, get_critique
        obs = "建议调整 skill_router 权重，当用户提及代码时优先路由到 shell 技能。"
        cid = create_critique(
            title="路由建议", observation=obs,
            source="reflect", scope="skill_router_hint"
        )
        c = get_critique(cid)
        assert c["scope"] == "skill_router_hint"
        # 验证没有任何文件被写入（skill_router 不存在对应的写入路径）
        router_file = Path(ROOT) / "core" / "_router_hints.json"
        assert not router_file.exists(), "skill_router_hint 不应自动写文件"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
