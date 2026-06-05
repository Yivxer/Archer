"""
图片分析技能：调用视觉模型理解图片内容，支持描述、问答、对比。
与 image_ocr 的区别：OCR 只提取文字，本技能理解图片语义。
"""
import base64
import tomllib
from pathlib import Path

SKILL = {
    "name": "image_analysis",
    "description": "用视觉模型理解图片内容：描述画面、回答问题、分析图表、识别物体",
    "version": "1.0.0",
    "author": "archer-builtin",
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tiff"}


def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "image_analysis",
            "description": (
                "用视觉模型分析本地图片，可描述内容、回答关于图片的问题、分析图表数据。"
                "适合：理解截图含义、分析设计稿、看懂图表、识别场景。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "图片文件的绝对路径",
                    },
                    "question": {
                        "type": "string",
                        "description": "关于图片的问题，留空则描述图片整体内容",
                    },
                },
                "required": ["path"],
            },
        },
    }


def run(path: str, question: str = "") -> str:
    p = Path(path).expanduser()
    if not p.exists():
        return f"图片不存在：{path}"
    if p.suffix.lower() not in IMAGE_EXTS:
        return f"不支持的图片格式：{p.suffix}（支持：{', '.join(IMAGE_EXTS)}）"

    cfg_path = Path(__file__).parent.parent / "archer.toml"
    with open(cfg_path, "rb") as f:
        cfg = tomllib.load(f)

    vision_model = cfg["api"].get("vision_model", "")
    api_key = cfg["api"].get("api_key", "")
    base_url = cfg["api"].get("base_url", "https://api.openai.com/v1")

    if not vision_model:
        return "未配置视觉模型，请在 archer.toml 的 [api] 中设置 vision_model。"

    image_data = base64.standard_b64encode(p.read_bytes()).decode()
    suffix = p.suffix.lower().lstrip(".")
    mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
    prompt = question.strip() if question.strip() else "请描述这张图片的内容，包括主要元素、布局和任何值得注意的细节。"

    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(
        model=vision_model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{image_data}"}},
            ],
        }],
        max_tokens=1024,
    )
    return resp.choices[0].message.content or "（无返回内容）"
