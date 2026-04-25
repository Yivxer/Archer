import subprocess
from datetime import datetime
from pathlib import Path

SKILL = {
    "name": "screenshot",
    "description": "截取屏幕并保存到本地",
    "version": "1.0.0",
    "author": "archer-builtin",
}

SAVE_DIR = Path.home() / "Desktop" / "Archer截图"

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "screenshot",
            "description": "截取全屏或指定窗口，保存为 PNG 文件到桌面/Archer截图目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["fullscreen", "window", "timed"],
                        "description": "截图模式：fullscreen=全屏（默认）、window=交互选择窗口、timed=5秒后截图",
                    },
                    "filename": {
                        "type": "string",
                        "description": "保存文件名（不含扩展名），默认用时间戳",
                    },
                },
            },
        },
    }

def run(args: dict) -> str:
    mode     = args.get("mode", "fullscreen")
    filename = args.get("filename", "").strip()

    SAVE_DIR.mkdir(parents=True, exist_ok=True)

    if not filename:
        filename = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = SAVE_DIR / f"{filename}.png"

    match mode:
        case "fullscreen": cmd = f'screencapture -x "{save_path}"'
        case "window":     cmd = f'screencapture -W "{save_path}"'
        case "timed":      cmd = f'screencapture -T 5 "{save_path}"'
        case _:            cmd = f'screencapture -x "{save_path}"'

    try:
        subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        if save_path.exists():
            size_kb = save_path.stat().st_size // 1024
            return f"截图已保存：{save_path}\n大小：{size_kb} KB"
        return "截图失败：文件未生成"
    except Exception as e:
        return f"截图失败：{e}"
