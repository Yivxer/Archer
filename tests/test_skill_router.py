"""
P2-B — SkillRouter Tests
验证关键词路由、URL/路径正则、多组命中、过滤不存在技能、纯聊天返回空。
"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.skill_router import select_skills


def _mock_skills(*names: str) -> dict:
    """构造最小 mock skills dict，包含指定名称。"""
    result = {}
    for name in names:
        mod = types.ModuleType(name)
        mod.SKILL = {"name": name}
        result[name] = mod
    return result


ALL = _mock_skills(
    "file_ops", "file_search", "shell", "obsidian_read", "obsidian_write",
    "obsidian_search", "web_fetch", "github_ops", "screenshot", "image_ocr",
    "pdf_reader", "rss_reader", "weather", "whisper_transcribe",
    "apple_reminders", "summarize", "humanizer", "hugo_blog",
    "weekly_review", "installer",
)


# ─── 纯聊天 → 无技能 ────────────────────────────────────────────────────────────

def test_pure_chat_returns_empty():
    assert select_skills("你好，今天心情怎么样？", ALL) == {}

def test_question_returns_empty():
    assert select_skills("三体里的黑暗森林是什么意思？", ALL) == {}

def test_empty_input_returns_empty():
    assert select_skills("", ALL) == {}

def test_no_skills_loaded():
    assert select_skills("帮我看看这个文件", {}) == {}


# ─── 文件关键词 ────────────────────────────────────────────────────────────────

def test_file_keyword_chinese():
    result = select_skills("帮我看看这个文件", ALL)
    assert "file_ops" in result
    assert "file_search" in result

def test_directory_keyword():
    result = select_skills("列出这个目录下的内容", ALL)
    assert "file_ops" in result

def test_path_regex_absolute():
    result = select_skills("读取 /Users/Yivxer/test.txt 的内容", ALL)
    assert "file_ops" in result
    assert "file_search" in result

def test_path_regex_home():
    result = select_skills("打开 ~/Documents/note.md", ALL)
    assert "file_ops" in result

def test_path_regex_relative():
    result = select_skills("看看 ./config.toml", ALL)
    assert "file_ops" in result


# ─── Shell 关键词 ──────────────────────────────────────────────────────────────

def test_shell_keyword():
    result = select_skills("在终端运行这个", ALL)
    assert "shell" in result

def test_bash_keyword():
    result = select_skills("用 bash 执行命令", ALL)
    assert "shell" in result

def test_shell_name():
    result = select_skills("shell ls -la", ALL)
    assert "shell" in result


# ─── URL / 网页 ────────────────────────────────────────────────────────────────

def test_url_https():
    result = select_skills("抓取 https://example.com 的内容", ALL)
    assert "web_fetch" in result

def test_url_http():
    result = select_skills("http://old-site.com", ALL)
    assert "web_fetch" in result

def test_webpage_keyword():
    result = select_skills("打开这个网页", ALL)
    assert "web_fetch" in result


# ─── Obsidian 笔记 ────────────────────────────────────────────────────────────

def test_obsidian_keyword():
    result = select_skills("写入笔记到 obsidian", ALL)
    assert "obsidian_write" in result
    assert "obsidian_read" in result
    assert "obsidian_search" in result

def test_note_keyword():
    result = select_skills("查找笔记", ALL)
    assert "obsidian_search" in result


# ─── 其他单一技能 ──────────────────────────────────────────────────────────────

def test_weather_keyword():
    result = select_skills("今天天气怎么样", ALL)
    assert "weather" in result

def test_pdf_suffix():
    result = select_skills("解析一下这个 report.pdf", ALL)
    assert "pdf_reader" in result

def test_github_keyword():
    result = select_skills("查看 github 上的 PR", ALL)
    assert "github_ops" in result

def test_rss_keyword():
    result = select_skills("读取 rss 订阅", ALL)
    assert "rss_reader" in result

def test_screenshot_keyword():
    result = select_skills("帮我截图", ALL)
    assert "screenshot" in result

def test_weekly_review_keyword():
    result = select_skills("帮我做周复盘", ALL)
    assert "weekly_review" in result


# ─── 多组命中 ─────────────────────────────────────────────────────────────────

def test_multi_group():
    result = select_skills("从 https://example.com 下载文件", ALL)
    assert "web_fetch" in result
    assert "file_ops" in result

def test_file_and_obsidian():
    result = select_skills("把这个文件写入笔记", ALL)
    assert "file_ops" in result
    assert "obsidian_write" in result


# ─── 过滤未加载技能 ───────────────────────────────────────────────────────────

def test_filters_unloaded_skills():
    partial = _mock_skills("file_ops")
    result = select_skills("帮我看看这个文件", partial)
    assert "file_ops" in result
    assert "file_search" not in result  # 未加载，不应出现

def test_url_but_web_fetch_not_loaded():
    partial = _mock_skills("shell")
    result = select_skills("https://example.com", partial)
    assert "web_fetch" not in result
    assert result == {}
