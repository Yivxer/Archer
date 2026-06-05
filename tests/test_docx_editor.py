"""
tests/test_docx_editor.py
测试 docx_editor 的 schema、参数校验、action 分发。
用 tempfile 做轻量集成测试（需要 python-docx 安装时跳过）。
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import importlib
mod = importlib.import_module("skills.docx_editor")

# 尝试导入 python-docx，记录是否可用
try:
    from docx import Document
    HAS_DOCX = True
except Exception:
    HAS_DOCX = False


# ── 1. schema() ──────────────────────────────────────────────────────

def test_schema_structure():
    s = mod.schema()
    assert s["type"] == "function"
    f = s["function"]
    assert f["name"] == "docx_editor"
    assert "action" in f["parameters"]["properties"]
    assert f["parameters"]["required"] == ["action"]


def test_schema_action_enum():
    s = mod.schema()
    f = s["function"]
    enum_vals = f["parameters"]["properties"]["action"]["enum"]
    assert "create" in enum_vals
    assert "read" in enum_vals
    assert "append_paragraph" in enum_vals
    assert "add_heading" in enum_vals
    assert "add_table" in enum_vals


def test_schema_optional_params():
    s = mod.schema()
    props = s["function"]["parameters"]["properties"]
    assert "path" in props
    assert "save_path" in props
    assert "title" in props
    assert "content" in props


# ── 2. run() 参数校验 ──────────────────────────────────────────────

def test_run_no_args():
    result = mod.run({})
    assert "未知" in result or "错误" in result


def test_run_create_no_save_path():
    result = mod.run({"action": "create", "title": "测试"})
    assert "save_path" in result and ("不能为空" in result or "错误" in result)


def test_run_read_no_path():
    result = mod.run({"action": "read"})
    assert "path" in result and ("不能为空" in result or "错误" in result)


def test_run_append_no_path():
    result = mod.run({"action": "append_paragraph", "text": "你好"})
    assert "path" in result and ("不能为空" in result or "错误" in result)


def test_run_append_no_text():
    result = mod.run({"action": "append_paragraph", "path": "/tmp/x.docx"})
    assert "text" in result and ("不能为空" in result or "错误" in result)


def test_run_add_heading_no_path():
    result = mod.run({"action": "add_heading", "text": "标题"})
    assert "path" in result and ("不能为空" in result or "错误" in result)


def test_run_add_table_no_path():
    result = mod.run({"action": "add_table"})
    assert "path" in result and ("不能为空" in result or "错误" in result)


def test_run_invalid_action():
    result = mod.run({"action": "foobar"})
    assert "未知" in result or "错误" in result


# ── 3. run() 集成（需要 python-docx）───────────────────────────────

@pytest.fixture(scope="module")
def has_docx():
    return HAS_DOCX


def test_create_and_read(tmp_path, has_docx):
    """create 后 read 能读到内容（需要 python-docx）。"""
    if not has_docx:
        pytest.skip("python-docx 未安装")
    import pytest
    save = tmp_path / "test.docx"
    r1 = mod.run({
        "action": "create",
        "title": "测试标题",
        "content": "第一段\n第二段",
        "save_path": str(save),
    })
    assert save.exists(), f"文件应已创建：{save}"
    assert "✅" in r1 or "已创建" in r1

    r2 = mod.run({"action": "read", "path": str(save)})
    assert "测试标题" in r2
    assert "第一段" in r2


def test_create_empty(tmp_path, has_docx):
    """无标题、无内容也能创建。"""
    if not has_docx:
        pytest.skip("python-docx 未安装")
    import pytest
    save = tmp_path / "empty.docx"
    r = mod.run({"action": "create", "save_path": str(save)})
    assert save.exists()
    assert "✅" in r or "已创建" in r


def test_read_nonexistent():
    result = mod.run({"action": "read", "path": "/tmp/nonexistent_xyz_12345.docx"})
    assert "不存在" in result or "错误" in result


def test_append_paragraph(tmp_path, has_docx):
    if not has_docx:
        pytest.skip("python-docx 未安装")
    import pytest
    save = tmp_path / "append.docx"
    # 先创建
    mod.run({"action": "create", "save_path": str(save), "title": "Doc"})
    # 再追加
    r = mod.run({"action": "append_paragraph", "path": str(save), "text": "追加的段落"})
    assert "✅" in r or "追加" in r
    # 读取验证
    r2 = mod.run({"action": "read", "path": str(save)})
    assert "追加的段落" in r2


def test_add_heading(tmp_path, has_docx):
    if not has_docx:
        pytest.skip("python-docx 未安装")
    import pytest
    save = tmp_path / "heading.docx"
    mod.run({"action": "create", "save_path": str(save)})
    r = mod.run({"action": "add_heading", "path": str(save), "text": "一级标题", "level": 1})
    assert "✅" in r or "写入" in r
    r2 = mod.run({"action": "read", "path": str(save)})
    assert "一级标题" in r2


def test_add_table(tmp_path, has_docx):
    if not has_docx:
        pytest.skip("python-docx 未安装")
    import pytest
    save = tmp_path / "table.docx"
    mod.run({"action": "create", "save_path": str(save)})
    r = mod.run({
        "action": "add_table",
        "path": str(save),
        "rows": 2,
        "cols": 2,
        "data": [["A", "B"], ["1", "2"]],
    })
    assert "✅" in r or "插入" in r
    r2 = mod.run({"action": "read", "path": str(save)})
    assert "A" in r2 and "1" in r2


# ── 4. _save 辅助函数 ──────────────────────────────────────────────

def test_save_creates_parent_dirs(tmp_path):
    """_save 自动创建不存在的父目录。"""
    deep = tmp_path / "deep" / "sub" / "test.docx"
    doc = mod._new()
    result_path = mod._save(doc, str(deep))
    assert Path(result_path).exists()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
