"""
tests/test_task_manager.py
测试 task_manager 的 schema、action 分发、参数校验。
mock memory.work 层，不依赖真实 DB。
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pytest
import importlib
mod = importlib.import_module("skills.task_manager")

# ── mock memory.work ──────────────────────────────────────────────────────

FAKE_WORK = {
    "create": MagicMock(return_value=42),
    "get": MagicMock(return_value={
        "id": 42,
        "title": "测试任务",
        "description": "描述",
        "status": "pending",
        "created_at": "2026-01-01 12:00:00",
        "checklist": [],
        "artifacts": [],
    }),
    "list_active": MagicMock(return_value=[
        {"id": 1, "title": "任务A", "description": "descA", "status": "pending", "created_at": "2026-01-01"},
        {"id": 2, "title": "任务B", "description": "descB", "status": "in_progress", "created_at": "2026-01-02"},
    ]),
    "list_all": MagicMock(return_value=[]),
    "update_status": MagicMock(return_value=True),
    "add_checklist_item": MagicMock(return_value=True),
    "check_item": MagicMock(return_value=True),
    "delete": MagicMock(return_value=True),
    "WORK_STATUSES": ["pending", "in_progress", "done", "cancelled"],
}


def _patch_work(monkeypatch):
    """monkeypatch mod._work() 的返回值。"""
    monkeypatch.setattr(mod, "_work", lambda: FAKE_WORK)


# ── 1. schema() ──────────────────────────────────────────────────────

def test_schema_structure():
    s = mod.schema()
    assert s["type"] == "function"
    f = s["function"]
    assert f["name"] == "task_manager"
    assert "action" in f["parameters"]["properties"]
    assert f["parameters"]["required"] == ["action"]


def test_schema_action_enum():
    s = mod.schema()
    f = s["function"]
    enum_vals = f["parameters"]["properties"]["action"]["enum"]
    assert "create" in enum_vals
    assert "list" in enum_vals
    assert "get" in enum_vals
    assert "update_status" in enum_vals
    assert "add_checklist" in enum_vals
    assert "check_item" in enum_vals
    assert "delete" in enum_vals


def test_schema_status_enum():
    s = mod.schema()
    f = s["function"]
    assert "pending" in f["parameters"]["properties"]["status"]["enum"]


# ── 2. run() 参数校验 ──────────────────────────────────────────────

def test_run_no_args():
    result = mod.run({})
    assert "未知" in result or "错误" in result


def test_run_create_no_title(monkeypatch):
    _patch_work(monkeypatch)
    result = mod.run({"action": "create"})
    assert "title" in result.lower() and ("需要" in result or "参数" in result)


def test_run_get_no_work_id(monkeypatch):
    _patch_work(monkeypatch)
    result = mod.run({"action": "get"})
    assert "work_id" in result.lower() and ("需要" in result or "参数" in result)


def test_run_update_status_no_work_id(monkeypatch):
    _patch_work(monkeypatch)
    result = mod.run({"action": "update_status", "status": "done"})
    assert "work_id" in result.lower() and ("需要" in result or "参数" in result)


def test_run_update_status_invalid_status(monkeypatch):
    _patch_work(monkeypatch)
    result = mod.run({"action": "update_status", "work_id": 1, "status": "foobar"})
    assert "必须是" in result or "错误" in result


def test_run_add_checklist_no_work_id(monkeypatch):
    _patch_work(monkeypatch)
    result = mod.run({"action": "add_checklist", "item_text": "步骤1"})
    assert "work_id" in result.lower() and ("需要" in result or "参数" in result)


def test_run_add_checklist_no_text(monkeypatch):
    _patch_work(monkeypatch)
    result = mod.run({"action": "add_checklist", "work_id": 1})
    assert "item_text" in result.lower() and ("需要" in result or "参数" in result)


def test_run_check_item_missing_args(monkeypatch):
    _patch_work(monkeypatch)
    result = mod.run({"action": "check_item", "work_id": 1})
    assert "item_index" in result.lower() and ("需要" in result or "参数" in result)


def test_run_delete_no_work_id(monkeypatch):
    _patch_work(monkeypatch)
    result = mod.run({"action": "delete"})
    assert "work_id" in result.lower() and ("需要" in result or "参数" in result)


def test_run_invalid_action(monkeypatch):
    _patch_work(monkeypatch)
    result = mod.run({"action": "foobar"})
    assert "未知" in result or "错误" in result


# ── 3. run() 正常流程（mock）───────────────────────────────────────

def test_run_create_success(monkeypatch):
    _patch_work(monkeypatch)
    result = mod.run({"action": "create", "title": "新任务", "description": "详情"})
    assert "✅" in result or "已创建" in result
    assert "42" in result  # work_id


def test_run_list_active(monkeypatch):
    _patch_work(monkeypatch)
    result = mod.run({"action": "list"})
    assert "任务列表" in result or "⏳" in result or "🔄" in result


def test_run_list_all(monkeypatch):
    _patch_work(monkeypatch)
    result = mod.run({"action": "list", "list_type": "all", "limit": 50})
    # list_all() 返回 []，走 "没有xxx 类型的任务" 分支
    assert "没有" in result and "all" in result, f"期望空列表提示，实际：{result}"


def test_run_get_success(monkeypatch):
    _patch_work(monkeypatch)
    result = mod.run({"action": "get", "work_id": 42})
    assert "测试任务" in result or "42" in result


def test_run_get_not_found(monkeypatch):
    _patch_work(monkeypatch)
    FAKE_WORK["get"].return_value = None
    result = mod.run({"action": "get", "work_id": 999})
    assert "不存在" in result or "错误" in result


def test_run_update_status_success(monkeypatch):
    _patch_work(monkeypatch)
    result = mod.run({"action": "update_status", "work_id": 1, "status": "done"})
    assert "✅" in result or "更新" in result


def test_run_add_checklist_success(monkeypatch):
    _patch_work(monkeypatch)
    result = mod.run({"action": "add_checklist", "work_id": 1, "item_text": "第一步"})
    assert "✅" in result or "新增" in result


def test_run_check_item_success(monkeypatch):
    _patch_work(monkeypatch)
    result = mod.run({"action": "check_item", "work_id": 1, "item_index": 1, "checked": True})
    assert "✅" in result or "勾选" in result


def test_run_delete_success(monkeypatch):
    _patch_work(monkeypatch)
    result = mod.run({"action": "delete", "work_id": 1})
    assert "🗑️" in result or "删除" in result


# ── 4. _fmt_item 辅助函数 ────────────────────────────────────────────

def test_fmt_item_basic():
    item = {
        "id": 1,
        "title": "测试",
        "description": "描述",
        "status": "pending",
        "created_at": "2026-01-01 12:00",
        "checklist": [],
        "artifacts": [],
    }
    lines = mod._fmt_item(item)
    assert any("测试" in l for l in lines)
    assert any("pending" in l for l in lines)


def test_fmt_item_with_checklist():
    item = {
        "id": 2,
        "title": "有清单",
        "description": "",
        "status": "in_progress",
        "created_at": "2026-01-01",
        "checklist": [{"done": True, "item": "步骤1"}, {"done": False, "item": "步骤2"}],
        "artifacts": [],
    }
    lines = mod._fmt_item(item)
    assert any("✅" in l for l in lines)
    assert any("⬜" in l for l in lines)


def test_fmt_item_with_artifacts():
    item = {
        "id": 3,
        "title": "有附件",
        "description": "",
        "status": "done",
        "created_at": "2026-01-01",
        "checklist": [],
        "artifacts": ["/tmp/a.txt", "/tmp/b.pdf"],
    }
    lines = mod._fmt_item(item)
    assert any("附件" in l for l in lines)
    assert any("a.txt" in l for l in lines)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
