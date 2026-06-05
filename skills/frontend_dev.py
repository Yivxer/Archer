"""
frontend_dev — 前端页面/组件生成与迭代

调用 LLM 直接生成可直接预览的 HTML/CSS/JS 代码，
或基于现有文件迭代改进。

适用场景：
- 从零生成一个落地页 / 博客页 / 管理后台
- 给出现有页面截图或代码，让它改进 UI/UX
- 生成某个组件的代码（React / Vue / 原生）
"""
from pathlib import Path

SKILL = {
    "name": "frontend_dev",
    "description": "前端页面与组件生成/迭代：生成 HTML/CSS/JS 或 React/Vue 组件代码",
    "version": "1.0.0",
    "author": "archer-builtin",
    "risk": "low",
    "default_timeout": 45,
}

# 懒加载 LLM（避免循环依赖）
def _llm_stream(prompt: str) -> str:
    """调用 Archer 内部 LLM，返回完整文本（非流式，取最后一轮完整输出）。"""
    from core.llm import stream_chat, get_last_usage
    result_parts = []
    for chunk in stream_chat([{"role": "user", "content": prompt}]):
        if isinstance(chunk, str):
            result_parts.append(chunk)
    return "".join(result_parts)


# ── Schema ───────────────────────────────────────────────────────────

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "frontend_dev",
            "description": (
                "前端开发：生成或改进网页 / 组件代码。"
                "支持 HTML 单文件、React 组件、Vue 组件。"
                "生成结果可直接保存为 .html 文件在浏览器预览。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["generate", "improve"],
                        "description": "generate=从零生成；improve=基于现有代码迭代改进",
                    },
                    "description": {
                        "type": "string",
                        "description": "需求描述（generate 时必填）：页面类型、风格、功能、目标设备",
                    },
                    "framework": {
                        "type": "string",
                        "enum": ["html", "react", "vue", "svelte"],
                        "description": "输出框架，默认 html（单文件自包含）",
                    },
                    "existing_code": {
                        "type": "string",
                        "description": "现有代码（action=improve 时传入），可直接贴代码或传文件路径",
                    },
                    "improvement_notes": {
                        "type": "string",
                        "description": "改进方向（action=improve 时使用）：要改什么、什么问题、目标效果",
                    },
                    "save_path": {
                        "type": "string",
                        "description": "保存路径（.html/.jsx/.vue 等），填写后自动保存代码到文件",
                    },
                },
                "required": ["action"],
            },
        },
    }


# ── Run ─────────────────────────────────────────────────────────────

def run(args: dict) -> str:
    action = args.get("action", "").strip()

    if action == "generate":
        return _generate(args)
    if action == "improve":
        return _improve(args)

    return f"错误：未知 action「{action}」，请用 generate 或 improve"


def _generate(args: dict) -> str:
    description = args.get("description", "").strip()
    if not description:
        return "错误：action=generate 需要 description 参数"
    framework = args.get("framework", "html").strip().lower()
    save_path = args.get("save_path", "").strip() or None

    prompt = (
        "你是一位资深前端工程师。请直接输出完整可运行的代码，不要加解释文字。\n\n"
        f"需求：{description}\n"
        f"框架：{framework}\n\n"
        "要求：\n"
        "1. 代码必须完整可运行，不要写「此处省略」\n"
        "2. 如果是 HTML，必须是单文件（CSS/JS 内联），可直接用浏览器打开\n"
        "3. 如果指定了 React/Vue，用 CDN 引入（不要写 npm install）\n"
        "4. 输出格式：直接以 ```html 或 ```jsx 代码块开始\n"
    )

    result = _llm_stream(prompt)
    code = _extract_code(result)
    if not code:
        return f"⚠️ 生成结果未包含代码块，原始输出：\n{result[:2000]}"

    resp = f"✅ 已生成 {framework} 代码（{len(code)} 字符）\n\n"
    resp += f"```{framework}\n{code[:2000]}{'...' if len(code)>2000 else ''}\n```"
    if save_path:
        p = Path(save_path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(code, encoding="utf-8")
        resp += f"\n\n✅ 已保存到：{p}"
    else:
        resp += "\n\n提示：传入 save_path 参数可自动保存为文件"
    return resp


def _improve(args: dict) -> str:
    existing = args.get("existing_code", "").strip()
    notes    = args.get("improvement_notes", "").strip()
    save_path = args.get("save_path", "").strip() or None

    if not existing:
        return "错误：action=improve 需要 existing_code 参数（代码或文件路径）"

    # 如果传入的是文件路径，读取文件
    p = Path(existing)
    if p.exists() and p.is_file():
        existing = p.read_text(encoding="utf-8")
        save_path = save_path or str(p)

    if not notes:
        return "错误：action=improve 需要 improvement_notes 参数（要改什么）"

    prompt = (
        "你是一位资深前端工程师。请基于现有代码进行改进，输出完整代码。\n\n"
        f"现有代码：\n```\n{existing}\n```\n\n"
        f"改进方向：{notes}\n\n"
        "要求：输出完整改进后的代码，不要省略，不要加解释。"
    )

    result = _llm_stream(prompt)
    code   = _extract_code(result)
    if not code:
        return f"⚠️ 改进结果未包含代码块，原始输出：\n{result[:2000]}"

    resp = f"✅ 已改进代码（{len(code)} 字符）\n\n"
    resp += f"```{''}\n{code[:2000]}{'...' if len(code)>2000 else ''}\n```"
    if save_path:
        p2 = Path(save_path).expanduser()
        p2.parent.mkdir(parents=True, exist_ok=True)
        p2.write_text(code, encoding="utf-8")
        resp += f"\n\n✅ 已保存到：{p2}"
    return resp


def _extract_code(text: str) -> str:
    """从 LLM 输出中提取第一个代码块。"""
    import re
    # ```lang\n...\n```
    m = re.search(r"```(?:html|jsx|js|vue|svelte|typescript|ts|css)?\n(.*?)\n```", text, re.DOTALL)
    if m:
        return m.group(1).rstrip()
    return ""
