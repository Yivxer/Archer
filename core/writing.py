"""
writing.py — 文章输出规范加载与任务 profile 选择

规范文件位于项目 writing/ 目录（可通过 archer.toml [writing] 覆盖）。
只负责注入 prompt，不短路 LLM。
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SPEC_DIR = _ROOT / "writing"

_PROFILE_SIGNALS: list[tuple[str, tuple[str, ...]]] = [
    ("revise", (
        "语病", "错别字", "标点", "润色", "检查错误", "检查语病", "校对", "通顺",
        "不要多加", "别多加", "不要增加", "不增加", "改动列表", "修订",
        "优化一下", "优化这篇", "优化文章", "改通顺", "通顺一点",
        "检查有没有", "有没有语病", "有没有错误", "润色一下", "润色这篇",
    )),
    ("blog", (
        "博客", "札记", "发一篇", "发文章", "hugo", "枫弋札记", "iver.yivxer",
    )),
    ("note", (
        "obsidian", "记入笔记", "写成笔记", "整理成笔记", "笔记里",
    )),
    ("draft", (
        "写一篇", "写一段", "写封信", "起草", "帮我写", "拟一篇", "成稿",
    )),
]


def writing_spec_dir(cfg: dict) -> Path:
    writing = cfg.get("writing", {}) if isinstance(cfg.get("writing"), dict) else {}
    raw = writing.get("spec_dir", "")
    if raw:
        return Path(str(raw)).expanduser()
    return _DEFAULT_SPEC_DIR


def writing_auto_profile(cfg: dict) -> bool:
    writing = cfg.get("writing", {}) if isinstance(cfg.get("writing"), dict) else {}
    return writing.get("auto_profile", True) is not False


def resolve_writing_profile(
    user_input: str,
    cfg: dict,
    *,
    mode: str | None = None,
    explicit: str | None = None,
) -> str | None:
    """根据用户输入 / 模式 / 配置解析写作 profile；无匹配返回 None。"""
    if explicit:
        return explicit
    writing = cfg.get("writing", {}) if isinstance(cfg.get("writing"), dict) else {}
    if not writing_auto_profile(cfg):
        default = writing.get("default_profile", "")
        return str(default).strip() or None

    text = (user_input or "").strip().lower()
    if not text:
        if mode == "writer":
            return "draft"
        return None

    for profile, keywords in _PROFILE_SIGNALS:
        if any(kw in text for kw in keywords):
            return profile

    if mode == "writer":
        return "draft"
    return None


def _read_spec_file(path: Path) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


def load_writing_prompt_blocks(cfg: dict, profile: str | None = None) -> list[str]:
    """加载总规范 + 可选 profile，供 build_system_prompt 注入。"""
    spec_dir = writing_spec_dir(cfg)
    blocks: list[str] = []

    base = _read_spec_file(spec_dir / "ARTICLE_SPEC.md")
    if base:
        blocks.append(f"[文章输出规范]\n{base}")

    if profile:
        prof = _read_spec_file(spec_dir / "profiles" / f"{profile}.md")
        if prof:
            blocks.append(prof)

    return blocks
