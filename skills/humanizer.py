SKILL = {
    "name": "humanizer",
    "description": "把文字改得更自然，去掉 AI 腔、官腔和空泛排比",
    "version": "1.0.0",
    "author": "archer-builtin",
}

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "humanizer",
            "description": (
                "润色文字，去掉明显的 AI 腔、套话、排比和宣传腔，让表达更克制自然。"
                "适合文章润色、口播稿打磨、对外表达优化。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "要润色的文字",
                    },
                    "style": {
                        "type": "string",
                        "enum": ["natural", "casual", "formal"],
                        "description": "目标风格：natural=自然克制（默认）、casual=口语化、formal=正式但不生硬",
                    },
                    "keep_structure": {
                        "type": "boolean",
                        "description": "是否保持原文段落结构，默认 true",
                    },
                },
                "required": ["text"],
            },
        },
    }

def run(args: dict) -> str:
    text          = args.get("text", "").strip()
    style         = args.get("style", "natural")
    keep_structure = args.get("keep_structure", True)

    if not text:
        return "错误：text 不能为空"

    style_hint = {
        "natural": "自然克制，去掉 AI 套话和排比，表达真实",
        "casual":  "口语化，像真人说话，轻松直接",
        "formal":  "正式但不生硬，专业感而不官腔",
    }.get(style, "自然克制")

    structure_hint = "保持原文段落结构。" if keep_structure else "可以重新组织段落结构。"

    return (
        f"请润色以下文字，风格要求：{style_hint}。{structure_hint}"
        f"去掉明显的 AI 腔、空泛排比、宣传腔和套话，让表达更真实自然。"
        f"直接输出润色后的结果，不要解释修改了什么。\n\n"
        f"原文：\n{text}"
    )
