"""
P2-B: 技能路由过滤

根据用户输入关键词动态决定暴露哪些技能，减少每次请求携带的 tool schema tokens。
无关键词命中 → 返回 {} → 主循环走纯流式，跳过全部 tool schema。
"""
import re
from typing import Any, Mapping

# (技能名集合, 触发关键词列表)  —— 大小写不敏感匹配
_ROUTES: list[tuple[frozenset, list[str]]] = [
    (
        frozenset({"file_ops", "file_search"}),
        ["文件", "目录", "文件夹", "路径", "新建文件", "删除文件", "创建文件", "读取文件"],
    ),
    (
        frozenset({"shell"}),
        ["shell", "bash", "终端", "命令行", "运行命令", "执行命令"],
    ),
    (
        frozenset({"obsidian_read", "obsidian_write", "obsidian_search"}),
        ["obsidian", "笔记", "知识库", "vault"],
    ),
    (
        frozenset({"web_fetch"}),
        ["网页", "网址", "网站", "抓取链接", "打开链接"],
    ),
    (
        frozenset({"github_ops"}),
        ["github", "git ", "pull request", "仓库", "代码库"],
    ),
    (
        frozenset({"screenshot"}),
        ["截图", "screenshot", "屏幕截图"],
    ),
    (
        frozenset({"image_ocr"}),
        ["ocr", "图片文字", "识别文字", "image_ocr"],
    ),
    (
        frozenset({"pdf_reader"}),
        [".pdf", "pdf文件", "pdf文档"],
    ),
    (
        frozenset({"rss_reader"}),
        ["rss", "订阅源"],
    ),
    (
        frozenset({"weather"}),
        ["天气", "weather", "气温"],
    ),
    (
        frozenset({"whisper_transcribe"}),
        ["录音", "语音转文字", "音频文件", "whisper"],
    ),
    (
        frozenset({"apple_reminders"}),
        ["提醒事项", "苹果提醒", "reminders"],
    ),
    (
        frozenset({"summarize", "humanizer"}),
        ["总结这个", "摘要这个", "humanize"],
    ),
    (
        frozenset({"hugo_blog"}),
        ["hugo", "博客发布"],
    ),
    (
        frozenset({"weekly_review"}),
        ["周复盘", "weekly review", "weekly_review"],
    ),
    (
        frozenset({"installer"}),
        ["安装技能", "install skill"],
    ),
]

# 绝对路径 / 家目录路径 / 相对路径 → 触发 file_ops + file_search
_PATH_RE = re.compile(r"(?:^|\s)(~|/)[\w./\-_]+|(?:^|\s)\./[\w./\-_]+")

# URL → 触发 web_fetch
_URL_RE = re.compile(r"https?://", re.IGNORECASE)


def select_skills(user_input: str, all_skills: Mapping[str, Any]) -> dict:
    """
    返回本轮应暴露给模型的技能子集。

    - 按关键词和正则匹配用户输入
    - 只返回 all_skills 中实际存在的技能
    - 无命中 → 返回 {}，主循环走 _stream 跳过全部 tool schema
    """
    if not user_input or not all_skills:
        return {}

    lower = user_input.lower()
    selected: set[str] = set()

    # URL 快速检测
    if _URL_RE.search(user_input):
        selected.add("web_fetch")

    # 路径快速检测
    if _PATH_RE.search(user_input):
        selected.update({"file_ops", "file_search"})

    # 关键词匹配
    for skill_names, keywords in _ROUTES:
        if any(kw in lower for kw in keywords):
            selected.update(skill_names)

    return {name: mod for name, mod in all_skills.items() if name in selected}
