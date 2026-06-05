"""
browser_automation — Playwright 浏览器自动化

使用 uvx browser-use CLI 操作浏览器，支持：
- navigate：打开 URL
- click：点击元素
- type：向元素输入文本
- screenshot：截取当前页面
- extract：提取页面文本内容
- scroll：滚动页面

需要 uvx browser-use 已安装（会自动下载）。
首次运行会自动安装 Chromium。
"""
import json
import subprocess
import tempfile
import uuid
from pathlib import Path

SKILL = {
    "name": "browser_automation",
    "description": "Playwright 浏览器自动化：打开网页、点击元素、输入文本、截图、提取内容、滚动页面",
    "version": "1.0.0",
    "author": "archer-builtin",
    "risk": "medium",
    "default_timeout": 60,
}

# 每个 session 一个浏览器实例，避免冲突
_SESSIONS: dict[str, str] = {}  # session_id → session_name
_PROJ = Path(__file__).parent.parent
_SCREENSHOT_DIR = _PROJ / ".artifacts" / "browser_screenshots"


def _run(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    """运行 browser-use CLI 命令。"""
    try:
        result = subprocess.run(
            ["uvx", "browser-use"] + cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"命令超时（{timeout}s）"
    except FileNotFoundError:
        return -1, "", "uvx 未找到。请运行：pip install uvx"


def _ensure_session(session_id: str) -> str:
    """确保 session 存在，返回 session_name。"""
    if session_id not in _SESSIONS:
        _SESSIONS[session_id] = f"archer-{session_id[:8]}"
    return _SESSIONS[session_id]


def _session_cmd(session_id: str, cmd: list[str]) -> list[str]:
    sname = _ensure_session(session_id)
    return ["--session", sname] + cmd


def _new_session() -> str:
    sid = str(uuid.uuid4())[:8]
    return sid


# ── Actions ──────────────────────────────────────────────────────────────────

def _navigate(url: str, session_id: str) -> str:
    if not url.startswith(("http://", "https://", "file://")):
        return f"错误：URL 必须以 http://、https:// 或 file:// 开头，当前值：{url}"
    cmd = _session_cmd(session_id, ["open", url])
    code, out, err = _run(cmd)
    if code != 0:
        return f"导航失败：{err or out}"
    return f"✅ 已打开 {url}"


def _click(selector: str, session_id: str, screenshot: bool = False) -> str:
    cmd = _session_cmd(session_id, ["click", selector])
    if screenshot:
        cmd += ["&&", "screenshot"]
    code, out, err = _run(cmd)
    if code != 0:
        return f"点击失败（{selector}）：{err or out}"
    result = f"✅ 已点击 {selector}"
    if screenshot:
        result += "\n📸 截图已保存"
    return result


def _type_text(selector: str, text: str, session_id: str) -> str:
    cmd = _session_cmd(session_id, ["input", selector, text])
    code, out, err = _run(cmd)
    if code != 0:
        return f"输入失败（{selector}）：{err or out}"
    return f"✅ 已向 {selector} 输入文本"


def _scroll(direction: str = "down", amount: int = 1, session_id: str = "") -> str:
    valid = {"down", "up", "top", "bottom"}
    if direction not in valid:
        return f"错误：direction 必须是 {valid} 之一，当前值：{direction}"
    cmd = _session_cmd(session_id, ["scroll", direction, str(amount)])
    code, out, err = _run(cmd)
    if code != 0:
        return f"滚动失败：{err or out}"
    return f"✅ 页面已向 {direction} 滚动 {amount} 步"


def _screenshot(session_id: str) -> str:
    _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"screenshot-{session_id}-{uuid.uuid4().hex[:6]}.png"
    fpath = _SCREENSHOT_DIR / fname
    cmd = _session_cmd(session_id, ["screenshot", str(fpath)])
    code, out, err = _run(cmd)
    if code != 0:
        return f"截图失败：{err or out}"
    return f"✅ 截图已保存：{fpath}"


def _extract(session_id: str, selector: str = "") -> str:
    """提取页面文本。可选指定 CSS selector。"""
    if selector:
        cmd = _session_cmd(session_id, ["extract", selector])
    else:
        cmd = _session_cmd(session_id, ["get"])
    code, out, err = _run(cmd)
    if code != 0:
        return f"提取失败：{err or out}"
    text = out.strip()
    if not text:
        return "页面内容为空"
    # 截断超长内容
    if len(text) > 8000:
        text = text[:8000] + f"\n\n…（已截断，共 {len(text)} 字符）"
    return text


def _close(session_id: str) -> str:
    """关闭浏览器 session。"""
    if session_id in _SESSIONS:
        sname = _SESSIONS.pop(session_id)
        cmd = ["close", "--session", sname]
        _run(cmd)
    return "✅ 浏览器已关闭"


# ── Schema ───────────────────────────────────────────────────────────────────

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "browser_automation",
            "description": (
                "Playwright 浏览器自动化。提供 action 参数选择具体操作：\n"
                "- navigate: 打开 URL\n"
                "- click: 点击页面元素\n"
                "- type_text: 向元素输入文本\n"
                "- scroll: 滚动页面\n"
                "- screenshot: 截取当前页面\n"
                "- extract: 提取页面文本内容\n"
                "- close: 关闭浏览器 session\n"
                "使用 session_id 追踪同一浏览器会话，支持多标签页。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "navigate", "click", "type_text",
                            "scroll", "screenshot", "extract", "close",
                        ],
                        "description": "执行的操作类型",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "浏览器会话 ID，首次调用时自动生成可不填，后续操作请传入同一 ID",
                    },
                    "url": {
                        "type": "string",
                        "description": "目标 URL（action=navigate 时必须）",
                    },
                    "selector": {
                        "type": "string",
                        "description": "CSS 选择器（action=click/type_text/extract 时使用）",
                    },
                    "text": {
                        "type": "string",
                        "description": "要输入的文本（action=type_text 时使用）",
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["down", "up", "top", "bottom"],
                        "description": "滚动方向（action=scroll 时使用）",
                    },
                    "amount": {
                        "type": "integer",
                        "description": "滚动步数，默认 1（action=scroll 时使用）",
                    },
                    "take_screenshot": {
                        "type": "boolean",
                        "description": "操作后是否截图（action=click 时使用）",
                    },
                },
                "required": ["action"],
            },
        },
    }


def run(args: dict) -> str:
    action = args.get("action", "").strip()
    session_id = args.get("session_id", "").strip()
    screenshot = bool(args.get("take_screenshot", False))

    if action == "close":
        sid = session_id or (_SESSIONS and next(iter(_SESSIONS))) or ""
        return _close(sid)

    # 新建 session（如果未提供）
    if not session_id:
        session_id = _new_session()
    elif session_id not in _SESSIONS:
        _ensure_session(session_id)

    if action == "navigate":
        url = args.get("url", "").strip()
        if not url:
            return "错误：action=navigate 需要 url 参数"
        result = _navigate(url, session_id)
        return f"[session_id: {session_id}]\n{result}"

    if action == "click":
        selector = args.get("selector", "").strip()
        if not selector:
            return "错误：action=click 需要 selector 参数"
        result = _click(selector, session_id, screenshot)
        return f"[session_id: {session_id}]\n{result}"

    if action == "type_text":
        selector = args.get("selector", "").strip()
        text = args.get("text", "").strip()
        if not selector:
            return "错误：action=type_text 需要 selector 参数"
        if not text:
            return "错误：action=type_text 需要 text 参数"
        result = _type_text(selector, text, session_id)
        return f"[session_id: {session_id}]\n{result}"

    if action == "scroll":
        direction = args.get("direction", "down").strip()
        amount = int(args.get("amount", 1))
        result = _scroll(direction, amount, session_id)
        return f"[session_id: {session_id}]\n{result}"

    if action == "screenshot":
        result = _screenshot(session_id)
        return f"[session_id: {session_id}]\n{result}"

    if action == "extract":
        selector = args.get("selector", "").strip()
        result = _extract(session_id, selector)
        return f"[session_id: {session_id}]\n{result}"

    return (
        f"错误：未知 action「{action}」\n"
        "可用 action：navigate / click / type_text / scroll / screenshot / extract / close"
    )
