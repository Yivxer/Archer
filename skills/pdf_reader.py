import fitz  # pymupdf
from pathlib import Path

SKILL = {
    "name": "pdf_reader",
    "description": "读取本地 PDF 文件，提取文字内容，支持指定页码范围",
    "version": "1.0.0",
    "author": "archer-builtin",
}

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "pdf_reader",
            "description": (
                "读取本地 PDF 文件，提取纯文本内容。"
                "支持指定页码范围，返回文字供分析、摘要、提问使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "PDF 文件的绝对路径或 ~/... 路径",
                    },
                    "start_page": {
                        "type": "integer",
                        "description": "起始页码（从 1 开始），默认第 1 页",
                    },
                    "end_page": {
                        "type": "integer",
                        "description": "结束页码（含），默认读到第 20 页（避免过长）",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "最多返回字符数，默认 6000",
                    },
                },
                "required": ["path"],
            },
        },
    }

def run(args: dict) -> str:
    raw_path = args.get("path", "").strip()
    if not raw_path:
        return "错误：path 不能为空"

    p = Path(raw_path).expanduser()
    if not p.exists():
        return f"文件不存在：{p}"
    if p.suffix.lower() != ".pdf":
        return f"不是 PDF 文件：{p.name}"

    start  = max(1, int(args.get("start_page", 1))) - 1  # 转 0-index
    end    = int(args.get("end_page", 20))
    maxch  = int(args.get("max_chars", 6000))

    try:
        doc   = fitz.open(str(p))
        total = doc.page_count
        end   = min(end, total)

        parts = [f"📄 {p.name}  共 {total} 页，读取第 {start+1}–{end} 页\n"]
        for i in range(start, end):
            page_text = doc[i].get_text().strip()
            if page_text:
                parts.append(f"--- 第 {i+1} 页 ---\n{page_text}")
        doc.close()

        full = "\n\n".join(parts)
        if len(full) > maxch:
            full = full[:maxch] + f"\n\n…（已截断，共 {len(full)} 字符，可用 start_page/end_page 分段读取）"
        return full

    except Exception as e:
        return f"读取失败：{e}"
