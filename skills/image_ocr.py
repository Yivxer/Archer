import pytesseract
from PIL import Image
from pathlib import Path

SKILL = {
    "name": "image_ocr",
    "description": "从图片中提取文字（OCR），支持中英文，适合书页截图、公众号截图、拍照文字",
    "version": "1.0.0",
    "author": "archer-builtin",
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp", ".gif"}

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "image_ocr",
            "description": (
                "对本地图片进行 OCR 文字识别，提取图中文字。"
                "lang=chi_sim 中文（默认）、eng 英文、chi_sim+eng 中英混合。"
                "适用于书页拍照、截图提字、扫描件等场景。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "图片文件的绝对路径或 ~/... 路径",
                    },
                    "lang": {
                        "type": "string",
                        "description": "识别语言：chi_sim（中文，默认）、eng（英文）、chi_sim+eng（中英混合）",
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
    if p.suffix.lower() not in IMAGE_EXTS:
        return f"不支持的图片格式：{p.suffix}。支持：{', '.join(sorted(IMAGE_EXTS))}"

    lang = args.get("lang", "chi_sim").strip() or "chi_sim"

    try:
        img  = Image.open(str(p))
        text = pytesseract.image_to_string(img, lang=lang).strip()

        if not text:
            return f"未识别到文字（语言={lang}）。如是英文图片，尝试 lang=eng。"

        header = f"🔍 {p.name}  语言={lang}  共 {len(text)} 字符\n\n"
        if len(text) > 6000:
            text = text[:6000] + "\n\n…（已截断）"
        return header + text

    except pytesseract.TesseractNotFoundError:
        return "错误：未找到 tesseract，请运行：brew install tesseract tesseract-lang"
    except Exception as e:
        return f"OCR 失败：{e}"
