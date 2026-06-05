"""
网页截图技能：用 Chrome headless 截取任意 URL 并保存为 PNG。
截图后可配合 image_analysis 让 Archer「看到」页面实际效果，用于 CSS 调试和视觉验证。
"""
import re
import subprocess
from datetime import datetime
from pathlib import Path

SKILL = {
    "name": "page_screenshot",
    "description": "用 Chrome 无头浏览器截取网页截图，让 Archer 能「看到」页面视觉效果",
    "version": "1.0.0",
    "author": "archer-builtin",
}

_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SAVE_DIR = Path.home() / "Desktop" / "Archer截图"


def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "page_screenshot",
            "description": (
                "用无头 Chrome 对网页 URL 截图，保存为 PNG，返回文件路径。"
                "截图后可用 image_analysis 分析页面视觉效果。"
                "本地预览请先调用 hugo_blog action=preview 再截图。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "目标 URL，如 http://localhost:1313 或 https://iver.yivxer.com",
                    },
                    "filename": {
                        "type": "string",
                        "description": "保存文件名（不含扩展名），默认自动生成",
                    },
                    "width": {
                        "type": "integer",
                        "description": "视口宽度（像素），默认 1280",
                    },
                    "height": {
                        "type": "integer",
                        "description": "视口高度（像素），默认 900",
                    },
                    "delay_ms": {
                        "type": "integer",
                        "description": "等待页面渲染的毫秒数，默认 1500，有动画的页面建议 2500",
                    },
                },
                "required": ["url"],
            },
        },
    }


def run(args: dict) -> str:
    url = args.get("url", "").strip()
    if not url:
        return "错误：url 参数为空"
    if not url.startswith(("http://", "https://")):
        url = "http://" + url

    width    = int(args.get("width", 1280))
    height   = int(args.get("height", 900))
    delay_ms = int(args.get("delay_ms", 1500))
    filename = args.get("filename", "").strip()

    chrome = Path(_CHROME)
    if not chrome.exists():
        return (
            f"错误：未找到 Google Chrome → {_CHROME}\n"
            "请安装 Google Chrome 后重试。"
        )

    SAVE_DIR.mkdir(parents=True, exist_ok=True)

    if not filename:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"page_{ts}"
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._") or "page"
    save_path = SAVE_DIR / f"{filename}.png"

    cmd = [
        str(chrome),
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        f"--window-size={width},{height}",
        f"--virtual-time-budget={delay_ms}",
        f"--screenshot={save_path}",
        url,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if save_path.exists() and save_path.stat().st_size > 1024:
            size_kb = save_path.stat().st_size // 1024
            return (
                f"截图成功：{save_path}\n"
                f"尺寸：{width}×{height}  大小：{size_kb} KB\n"
                f"可用 image_analysis 分析：path={save_path}"
            )
        # Chrome --headless=new 有时不支持 --virtual-time-budget，降级重试
        cmd_retry = [c for c in cmd if not c.startswith("--virtual-time-budget")]
        result2 = subprocess.run(cmd_retry, capture_output=True, text=True, timeout=30)
        if save_path.exists() and save_path.stat().st_size > 1024:
            size_kb = save_path.stat().st_size // 1024
            return (
                f"截图成功：{save_path}\n"
                f"尺寸：{width}×{height}  大小：{size_kb} KB\n"
                f"可用 image_analysis 分析：path={save_path}"
            )
        stderr = (result2.stderr or result.stderr or "")[:400]
        return f"截图失败：文件未生成或为空\n{stderr}"
    except subprocess.TimeoutExpired:
        return "错误：截图超时（30s），请检查目标 URL 是否可访问"
    except Exception as e:
        return f"错误：{e}"
