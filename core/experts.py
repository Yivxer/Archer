"""Expert workbench resolution for Archer work-context switching."""
from __future__ import annotations

import re
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any

from core.model_profiles import MODEL_PROFILE_IDS, model_profiles

BUILTIN_EXPERT_IDS = (
    "default",
    "developer",
    "video-coach",
    "content-creator",
    "counselor",
    "parent-educator",
)

# Backward-compatible alias for tests and legacy imports.
EXPERT_IDS = BUILTIN_EXPERT_IDS

EXPERT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

DEFAULT_EXPERTS: dict[str, dict[str, object]] = {
    "default": {
        "label": "基础 Archer",
        "note": "灵魂陪伴，不担任特定工作角色",
        "model_profile": "lite",
        "skill_policy": "open",
        "skills": [],
        "prompt_overlay": "",
        "memory_tags": [],
        "starters": [
            {"label": "先听我说", "prompt": "我先说一段，你不用急着给方案。"},
            {"label": "有点卡住", "prompt": "我现在有点卡住，想先说一段。"},
            {"label": "轻轻复盘", "prompt": "帮我轻轻复盘一下刚才这件事。"},
            {"label": "继续那条线", "prompt": "我们继续刚才那条线。"},
        ],
    },
    "developer": {
        "label": "开发工程师",
        "note": "查代码、排错、看结构、委派实现",
        "model_profile": "pro",
        "skill_policy": "allowlist",
        "skills": [
            "code_search",
            "shell",
            "github_ops",
            "file_ops",
            "npm_run",
            "code_edit",
        ],
        "prompt_overlay": (
            "当前处于工程工作台。可讨论架构与排错；大段实现优先建议委派外部代码智能体，"
            "不要假装已经改完代码。"
        ),
        "memory_tags": ["expert:developer", "project"],
        "starters": [
            {"label": "看这段代码", "prompt": "帮我看看这段代码有什么问题。"},
            {"label": "排个错", "prompt": "我遇到一个报错，先帮我定位原因。"},
            {"label": "理清结构", "prompt": "帮我理清这个模块的结构和职责。"},
            {"label": "委派实现", "prompt": "这件事我想委派出去，帮我写个清晰的实现 brief。"},
        ],
    },
    "video-coach": {
        "label": "短视频教练",
        "note": "脚本、口播、选题与表达节奏",
        "model_profile": "pro",
        "skill_policy": "allowlist",
        "skills": ["video_script", "humanizer", "summarize"],
        "prompt_overlay": "当前处于短视频工作台。优先帮用户打磨脚本、口播和选题，语气利落、可拍。",
        "memory_tags": ["expert:video-coach", "video"],
        "starters": [
            {"label": "打磨脚本", "prompt": "帮我把这段口播改得更顺口、更能留住人。"},
            {"label": "想个选题", "prompt": "我想拍一条短视频，帮我想几个能讲的选题。"},
            {"label": "开头钩子", "prompt": "帮我写 3 个能抓住注意力的开头。"},
            {"label": "节奏检查", "prompt": "帮我看看这段脚本的节奏会不会拖。"},
        ],
    },
    "content-creator": {
        "label": "内容创作者",
        "note": "文章、博客、长文与发布链路",
        "model_profile": "lite",
        "skill_policy": "allowlist",
        "skills": ["obsidian_write", "obsidian_read", "hugo_blog", "summarize"],
        "prompt_overlay": "当前处于内容创作工作台。优先帮用户写清、写顺；发布或写入需走确认。",
        "memory_tags": ["expert:content-creator", "writing"],
        "starters": [
            {"label": "写开头", "prompt": "帮我想一个清楚有力的文章开头。"},
            {"label": "理顺大纲", "prompt": "我有个主题，帮我把大纲理顺。"},
            {"label": "润一稿", "prompt": "帮我把下面这段文字写得更顺、更好读。"},
            {"label": "发布前检查", "prompt": "发布前帮我检查一下结构和表达。"},
        ],
    },
    "counselor": {
        "label": "心理咨询师",
        "note": "情绪、关系与自我理解",
        "model_profile": "pro",
        "skill_policy": "allowlist",
        "skills": ["memory_save", "obsidian_read", "summarize"],
        "prompt_overlay": (
            "当前处于心理倾听工作台。先承接情绪，少给方案；不医学化、不廉价安慰。"
        ),
        "memory_tags": ["expert:counselor", "emotion"],
        "starters": [
            {"label": "先听我说", "prompt": "我先说一段，你不用急着给方案。"},
            {"label": "有点卡住", "prompt": "我现在有点卡住，想先说一段。"},
            {"label": "轻轻复盘", "prompt": "帮我轻轻复盘一下刚才这件事。"},
            {"label": "理清感受", "prompt": "我想把现在的感受理一理，先听我说。"},
        ],
    },
    "parent-educator": {
        "label": "亲子教育家",
        "note": "育儿沟通与教育理念",
        "model_profile": "lite",
        "skill_policy": "allowlist",
        "skills": ["summarize", "obsidian_read", "memory_save"],
        "prompt_overlay": "当前处于亲子教育工作台。帮用户理清育儿沟通，尊重边界，不替用户做决定。",
        "memory_tags": ["expert:parent-educator", "parenting"],
        "starters": [
            {"label": "育儿对话", "prompt": "今晚和孩子沟通有点难，帮我想想怎么开口。"},
            {"label": "理清边界", "prompt": "帮我想想这件事里，哪些边界需要说清楚。"},
            {"label": "换个说法", "prompt": "同样的话我想换种说法，让孩子更愿意听。"},
            {"label": "复盘互动", "prompt": "帮我复盘一下刚才和孩子的互动。"},
        ],
    },
}


def expert_starters(expert: dict[str, object]) -> list[dict[str, str]]:
    raw = expert.get("starters")
    if not isinstance(raw, list):
        return []
    items: list[dict[str, str]] = []
    for entry in raw:
        if isinstance(entry, str):
            prompt = entry.strip()
            if prompt:
                items.append({"label": prompt[:12], "prompt": prompt})
            continue
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label", "") or "").strip()
        prompt = str(entry.get("prompt", "") or "").strip()
        if label and prompt:
            items.append({"label": label, "prompt": prompt})
    return items


def expert_memory_tags(expert: dict[str, object]) -> list[str]:
    raw = expert.get("memory_tags")
    if not isinstance(raw, list):
        return []
    tags: list[str] = []
    for entry in raw:
        clean = str(entry or "").strip()
        if clean:
            tags.append(clean)
    return tags


def merge_expert_tags(tags: str, expert: dict[str, object]) -> str:
    hints = expert_memory_tags(expert)
    if not hints:
        return tags.strip()
    primary = hints[0]
    current = tags.strip()
    if primary in current:
        return current
    return f"{current},{primary}".strip(",") if current else primary


def _normalize_expert_entry(expert_id: str, raw: dict[str, Any]) -> dict[str, object]:
    base = DEFAULT_EXPERTS.get(expert_id, {})
    policy = str(raw.get("skill_policy", base.get("skill_policy", "open")) or "open").strip().lower()
    skills_raw = raw.get("skills", base.get("skills", []))
    skills = (
        [str(name).strip() for name in skills_raw if str(name).strip()]
        if isinstance(skills_raw, list)
        else []
    )
    profile_id = str(raw.get("model_profile", base.get("model_profile", "lite")) or "lite").strip().lower()
    if profile_id not in MODEL_PROFILE_IDS:
        profile_id = "lite"
    entry: dict[str, object] = {
        "label": str(raw.get("label", base.get("label", expert_id)) or expert_id).strip(),
        "note": str(raw.get("note", base.get("note", "")) or "").strip(),
        "model_profile": profile_id,
        "skill_policy": policy if policy in {"open", "allowlist"} else "open",
        "skills": skills,
        "prompt_overlay": str(raw.get("prompt_overlay", base.get("prompt_overlay", "")) or "").strip(),
        "memory_tags": expert_memory_tags(raw) or expert_memory_tags(base),
        "starters": expert_starters(raw) or expert_starters(base),
    }
    source = raw.get("source")
    if source:
        entry["source"] = str(source)
    return entry


def load_plugin_experts(base: Path | None = None) -> dict[str, dict[str, object]]:
    from core.plugin import list_installed

    catalog: dict[str, dict[str, object]] = {}
    for entry in list_installed(base):
        root = Path(str(entry.get("path", "")))
        if not root.is_dir():
            continue
        experts_dir = root / "experts"
        if not experts_dir.is_dir():
            continue
        plugin_name = str(entry.get("name", root.name))
        for path in sorted(experts_dir.glob("*.toml")):
            expert_id = path.stem.strip()
            if not EXPERT_ID_RE.fullmatch(expert_id):
                continue
            if expert_id in BUILTIN_EXPERT_IDS:
                continue
            try:
                raw = tomllib.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(raw, dict):
                continue
            normalized = _normalize_expert_entry(expert_id, raw)
            normalized["source"] = f"plugin:{plugin_name}"
            catalog[expert_id] = normalized
    return catalog


def experts(cfg: dict) -> dict[str, dict[str, object]]:
    merged = deepcopy(DEFAULT_EXPERTS)
    for expert_id, expert in load_plugin_experts().items():
        merged[expert_id] = expert

    configured = cfg.get("experts", {})
    if isinstance(configured, dict):
        for expert_id, raw in configured.items():
            if not EXPERT_ID_RE.fullmatch(str(expert_id)):
                continue
            if not isinstance(raw, dict):
                continue
            base = merged.get(expert_id, {})
            merged_expert = {**base, **raw}
            merged[expert_id] = _normalize_expert_entry(str(expert_id), merged_expert)
    return merged


def expert_ids(cfg: dict) -> tuple[str, ...]:
    catalog = experts(cfg)
    builtins = [expert_id for expert_id in BUILTIN_EXPERT_IDS if expert_id in catalog]
    custom = sorted(expert_id for expert_id in catalog if expert_id not in BUILTIN_EXPERT_IDS)
    return tuple(builtins + custom)


def active_expert_id(cfg: dict) -> str:
    persona = cfg.get("persona", {}) if isinstance(cfg.get("persona"), dict) else {}
    expert_id = str(persona.get("current_expert", "default") or "default").strip()
    catalog = experts(cfg)
    return expert_id if expert_id in catalog else "default"


def active_expert(cfg: dict) -> dict[str, object]:
    return dict(experts(cfg)[active_expert_id(cfg)])


def expert_skill_allowlist(expert: dict[str, object]) -> set[str] | None:
    policy = str(expert.get("skill_policy", "open") or "open").strip().lower()
    if policy != "allowlist":
        return None
    raw = expert.get("skills")
    if not isinstance(raw, list) or not raw:
        return None
    return {str(name).strip() for name in raw if str(name).strip()}


def filter_skills_for_expert(all_skills: dict, expert: dict[str, object]) -> dict:
    allowlist = expert_skill_allowlist(expert)
    if not allowlist:
        return dict(all_skills)
    return {name: skill for name, skill in all_skills.items() if name in allowlist}


def expert_model_profile_id(expert: dict[str, object]) -> str:
    profile_id = str(expert.get("model_profile", "lite") or "lite").strip().lower()
    return profile_id if profile_id in MODEL_PROFILE_IDS else "lite"


def expert_model_configured(cfg: dict, expert: dict[str, object]) -> bool:
    profile_id = expert_model_profile_id(expert)
    profile = model_profiles(cfg).get(profile_id, {})
    if not isinstance(profile, dict):
        return False
    return bool(profile.get("base_url") and profile.get("model") and profile.get("api_key"))


def format_expert_block(expert: dict[str, object]) -> str:
    overlay = str(expert.get("prompt_overlay", "") or "").strip()
    if not overlay:
        return ""
    label = str(expert.get("label", "") or "").strip()
    if label:
        return f"【{label}】{overlay}"
    return overlay
