"""
video_script — 短视频脚本生成

为抖音 / 快手 / 小红书 / B站 / YouTube Shorts 生成结构化脚本。

输出格式（Markdown）：
- 标题（3 个备选）
- 时长建议
- 钩子（前 3 秒）
- 分镜脚本（时间轴 | 画面 | 旁白/字幕 | 镜头建议）
- 结尾 CTA
- 标签推荐
- 注意事项（完播率优化点）
"""
from pathlib import Path

SKILL = {
    "name": "video_script",
    "description": "短视频脚本生成：钩子、分镜、CTA、标签，支持多平台",
    "version": "1.0.0",
    "author": "archer-builtin",
    "risk": "low",
    "default_timeout": 45,
}

# 懒加载 LLM
def _llm_stream(prompt: str) -> str:
    from core.llm import stream_chat
    parts = []
    for chunk in stream_chat([{"role": "user", "content": prompt}]):
        if isinstance(chunk, str):
            parts.append(chunk)
    return "".join(parts)


# ── Schema ─────────────────────────────────────────────────────

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "video_script",
            "description": (
                "生成短视频脚本（抖音/快手/小红书/B站/YouTube Shorts）。"
                "输出钩子、分镜脚本、结尾 CTA、推荐标签。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "视频主题，如「3 分钟学会俯卧撑」「AI 写作工具测评」",
                    },
                    "platform": {
                        "type": "string",
                        "enum": ["douyin", "kuaishou", "xiaohongshu", "bilibili", "youtube_shorts", "auto"],
                        "description": "目标平台，默认 auto（通用优化）",
                    },
                    "duration": {
                        "type": "integer",
                        "description": "目标时长（秒），默认 60",
                    },
                    "style": {
                        "type": "string",
                        "enum": ["knowledge", "storytelling", "review", "vlog", "tutorial"],
                        "description": "内容风格：knowledge=知识/教程，storytelling=讲故事，review=测评，vlog=日常，tutorial=操作演示",
                    },
                    "has_product": {
                        "type": "boolean",
                        "description": "是否带货/种草，默认 false；true 时加强产品植入和 CTA",
                    },
                    "save_path": {
                        "type": "string",
                        "description": "保存路径（.md），填写后自动保存脚本",
                    },
                },
                "required": ["topic"],
            },
        },
    }


# ── Platform hints ──────────────────────────────────────────────

_PLATFORM_HINTS = {
    "douyin":         "抖音：完播率优先，前 3 秒必须有钩子，节奏快，字幕大",
    "kuaishou":       "快手：老铁文化，真实感强，口播自然，少炫技",
    "xiaohongshu":     "小红书：封面图+标题极重要，语气像「分享」而非「教学」",
    "bilibili":        "B站：允许较长铺垫，弹幕互动点要设计，知识区受欢迎",
    "youtube_shorts":  "YouTube Shorts：前 1 秒留人，带英文字幕，结尾引导订阅",
    "auto":            "通用优化：兼顾完播率和分享率，适合多平台分发",
}

# ── Run ────────────────────────────────────────────────────────

def run(args: dict) -> str:
    topic      = args.get("topic", "").strip()
    platform   = args.get("platform", "auto").strip()
    duration   = int(args.get("duration", 60))
    style      = args.get("style", "auto").strip()
    has_product = bool(args.get("has_product", False))
    save_path  = args.get("save_path", "").strip() or None

    if not topic:
        return "错误：topic 参数不能为空"

    platform_hint = _PLATFORM_HINTS.get(platform, _PLATFORM_HINTS["auto"])

    prompt = (
        "你是一位资深短视频编导。请为以下需求生成完整拍摄脚本。\n\n"
        f"主题：{topic}\n"
        f"目标平台：{platform}（{platform_hint}）\n"
        f"目标时长：{duration} 秒\n"
        f"内容风格：{style}\n"
        f"是否带货：{'是' if has_product else '否'}\n\n"
        "输出格式（Markdown）：\n"
        "1. 标题（提供 3 个，含爆款关键词）\n"
        "2. 时长建议 & 节奏安排\n"
        "3. 钩子设计（前 3 秒，必需）\n"
        "4. 分镜脚本表格（时间轴 | 画面描述 | 旁白/字幕 | 拍摄建议）\n"
        "5. 结尾 CTA（引导关注/评论/分享）\n"
        "6. 推荐标签（10 个）\n"
        "7. 完播率优化建议\n"
    )

    script = _llm_stream(prompt)

    resp = f"✅ 短视频脚本已生成（{platform}，{duration}s）\n\n{script}"
    if save_path:
        p = Path(save_path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# 短视频脚本：{topic}\n\n{script}", encoding="utf-8")
        resp += f"\n\n✅ 已保存到：{p}"

    return resp
