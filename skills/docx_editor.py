"""
docx_editor — Word（.docx）文档创建与编辑

基于 python-docx 实现，支持：
- create：从零创建 Word 文档
- read：读取已有 docx 的文字内容
- append_paragraph：追加段落
- set_heading：写入标题（支持 1-4 级）
- add_table：插入表格
- save：保存到指定路径

python-docx 需要安装：
    uv pip install python-docx
"""
from pathlib import Path
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH


SKILL = {
    "name": "docx_editor",
    "description": "创建、读取、编辑 Word（.docx）文档：写入标题、段落、表格、样式",
    "version": "1.0.0",
    "author": "archer-builtin",
    "risk": "low",
    "default_timeout": 30,
}


def _load(path: str) -> Document:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"文件不存在：{p}")
    return Document(str(p))


def _new() -> Document:
    return Document()


def _save(doc: Document, path: str) -> str:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(p))
    return str(p)


# ── Actions ──────────────────────────────────────────────────────────────

def create(args: dict) -> str:
    """创建新 Word 文档，可初始化标题和第一段。"""
    title    = args.get("title", "").strip()
    content  = args.get("content", "").strip()
    save_path = args.get("save_path", "").strip()
    if not save_path:
        return "错误：save_path 不能为空"
    doc = _new()
    if title:
        doc.add_heading(title, level=1)
    if content:
        for para_text in content.split("\n"):
            if para_text.strip():
                doc.add_paragraph(para_text)
    result_path = _save(doc, save_path)
    return f"✅ 新文档已创建：{result_path}"


def read(args: dict) -> str:
    """读取 docx 文件，返回所有文字内容。"""
    path = args.get("path", "").strip()
    if not path:
        return "错误：path 不能为空"
    try:
        doc = _load(path)
    except FileNotFoundError as e:
        return str(e)
    except Exception as e:
        return f"读取失败：{e}"
    parts = []
    for i, para in enumerate(doc.paragraphs):
        if para.text.strip():
            # 标注标题级别
            if para.style.name.startswith("Heading"):
                level = para.style.name.replace("Heading", "") or "1"
                parts.append(f"{'#' * int(level)} {para.text}")
            else:
                parts.append(para.text)
    # 读取表格内容
    for ti, table in enumerate(doc.tables):
        parts.append(f"\n--- 表格 {ti+1} ---")
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            parts.append(" | ".join(cells))
    result = "\n".join(parts)
    if not result.strip():
        return f"文档为空（{path}）"
    if len(result) > 8000:
        return result[:8000] + f"\n\n…（已截断，共 {len(result)} 字符，可用 offset 分段读取）"
    return result


def append_paragraph(args: dict) -> str:
    """向现有文档追加段落，支持样式（normal / heading1-4 / bullet / number）。"""
    path   = args.get("path", "").strip()
    text   = args.get("text", "").strip()
    style  = args.get("style", "normal").strip().lower()
    if not path:
        return "错误：path 不能为空"
    if not text:
        return "错误：text 不能为空"
    try:
        doc = _load(path)
    except FileNotFoundError as e:
        return str(e)
    if style in ("heading1", "h1"):
        doc.add_heading(text, level=1)
    elif style in ("heading2", "h2"):
        doc.add_heading(text, level=2)
    elif style in ("heading3", "h3"):
        doc.add_heading(text, level=3)
    elif style in ("heading4", "h4"):
        doc.add_heading(text, level=4)
    elif style == "bullet":
        doc.add_paragraph(text, style="List Bullet")
    elif style == "number":
        doc.add_paragraph(text, style="List Number")
    else:
        doc.add_paragraph(text)
    _save(doc, path)
    return f"✅ 段落已追加到：{path}"


def add_table(args: dict) -> str:
    """向文档插入表格。rows/cols 指定大小，data 传入二维数组。"""
    path = args.get("path", "").strip()
    rows = int(args.get("rows", 2))
    cols = int(args.get("cols", 2))
    data = args.get("data", None)  # [["A","B"],["1","2"]]
    if not path:
        return "错误：path 不能为空"
    try:
        doc = _load(path)
    except FileNotFoundError as e:
        return str(e)
    table = doc.add_table(rows=rows, cols=cols)
    table.style = "Table Grid"
    if data and isinstance(data, list):
        for ri, row_data in enumerate(data[:rows]):
            for ci, cell_text in enumerate(row_data[:cols]):
                table.rows[ri].cells[ci].text = str(cell_text)
    _save(doc, path)
    return f"✅ 表格（{rows}×{cols}）已插入到：{path}"


def add_heading(args: dict) -> str:
    """向文档写入标题（不追加新段落，直接写标题）。"""
    path  = args.get("path", "").strip()
    text  = args.get("text", "").strip()
    level = int(args.get("level", 1))
    if not path:
        return "错误：path 不能为空"
    if not text:
        return "错误：text 不能为空"
    try:
        doc = _load(path)
    except FileNotFoundError as e:
        return str(e)
    doc.add_heading(text, level=max(1, min(4, level)))
    _save(doc, path)
    return f"✅ 标题（Level {level}）已写入：{path}"


# ── Schema ─────────────────────────────────────────────────────────────

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "docx_editor",
            "description": (
                "创建、读取、编辑 Word（.docx）文档。"
                "支持创建文档、读取内容、追加段落、写入标题、插入表格。"
                "适合生成报告、合同、简历、正式文档。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "create", "read",
                            "append_paragraph", "add_heading", "add_table",
                        ],
                        "description": "操作类型",
                    },
                    "path": {
                        "type": "string",
                        "description": "文档路径（action=read/append_paragraph/add_heading/add_table 时必填）",
                    },
                    "save_path": {
                        "type": "string",
                        "description": "保存路径（action=create 时必填）",
                    },
                    "title": {
                        "type": "string",
                        "description": "文档标题（action=create 时使用）",
                    },
                    "content": {
                        "type": "string",
                        "description": "初始文字内容（action=create 时使用）",
                    },
                    "text": {
                        "type": "string",
                        "description": "段落文字或标题文字（action=append_paragraph/add_heading 时使用）",
                    },
                    "style": {
                        "type": "string",
                        "description": "段落样式：normal / heading1-4 / bullet / number，默认 normal",
                    },
                    "level": {
                        "type": "integer",
                        "description": "标题级别（1-4），默认 1",
                    },
                    "rows": {
                        "type": "integer",
                        "description": "表格行数，默认 2",
                    },
                    "cols": {
                        "type": "integer",
                        "description": "表格列数，默认 2",
                    },
                    "data": {
                        "type": "array",
                        "description": "表格数据，二维数组 [[row1...],[row2...]]",
                        "items": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "required": ["action"],
            },
        },
    }


def run(args: dict) -> str:
    action = args.get("action", "").strip()
    if action == "create":
        return create(args)
    if action == "read":
        return read(args)
    if action == "append_paragraph":
        return append_paragraph(args)
    if action == "add_heading":
        return add_heading(args)
    if action == "add_table":
        return add_table(args)
    return (
        f"错误：未知 action「{action}」\n"
        "可用 action：create / read / append_paragraph / add_heading / add_table"
    )
