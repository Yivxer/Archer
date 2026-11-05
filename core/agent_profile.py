"""Agent profile contract: personality fields and the fixed prompt order.

The profile extends a Part 6 expert. It does not replace functional keys
(``label``, ``note``, ``model_profile``, ``skill_policy``, ``skills``,
``prompt_overlay``, ``starters``, ``memory_tags``).

Prompt assembly order is fixed by ``PROFILE_PROMPT_ORDER`` and consumed by
``core.context.build_system_prompt``:

    COVENANT → Soul → Expert overlay → Personality injection → Stance → Skill context

``covenant`` text is read only from ``persona.covenant_path``. Personality
fields cannot occupy that slot, and an expert table cannot set covenant or
soul paths.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# Prefix is emitted at the historical covenant / soul anchors.
# The remainder is emitted, in this order, after those anchors.
PROFILE_PROMPT_ORDER: tuple[str, ...] = (
    "covenant",
    "soul",
    "expert_overlay",
    "personality",
    "stance",
    "skill_context",
)
EARLY_PROFILE_LAYERS: tuple[str, ...] = PROFILE_PROMPT_ORDER[:2]
TAIL_PROFILE_LAYERS: tuple[str, ...] = PROFILE_PROMPT_ORDER[2:]

PART6_FUNCTIONAL_KEYS: frozenset[str] = frozenset({
    "label",
    "note",
    "model_profile",
    "skill_policy",
    "skills",
    "prompt_overlay",
    "starters",
    "memory_tags",
})

# Identity and personality keys from the seven-section profile draft.
# ``note`` stays the Part 6 description; ``subtitle`` does not replace it.
PROFILE_EXTENSION_KEYS: frozenset[str] = frozenset({
    "subtitle",
    "icon",
    "color",
    "personality_blurb",
    "voice_markers",
    "voice_avoid",
    "emotional_register",
    "silence_behavior",
    "mission",
    "rules",
    "workflow",
    "deliverable_signals",
    "default_stance",
    "permission_boundary",
    "source",
})

ALLOWED_EXPERT_KEYS: frozenset[str] = PART6_FUNCTIONAL_KEYS | PROFILE_EXTENSION_KEYS

# These would let an expert table replace the root covenant or soul files.
COVENANT_OVERRIDE_KEYS: frozenset[str] = frozenset({
    "covenant",
    "covenant_path",
    "covenant_text",
    "covenant_summary",
    "soul",
    "soul_path",
    "soul_text",
    "presence",
    "presence_path",
    "presence_text",
    "system_prompt",
})

_PROFILE_STRING_KEYS: tuple[str, ...] = (
    "subtitle",
    "icon",
    "color",
    "personality_blurb",
    "emotional_register",
    "silence_behavior",
    "mission",
    "workflow",
    "default_stance",
    "permission_boundary",
)
_PROFILE_LIST_KEYS: tuple[str, ...] = (
    "voice_markers",
    "voice_avoid",
    "rules",
    "deliverable_signals",
)

_STANCE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_MAX_BLURB_CHARS = 400
_MAX_LIST_ITEMS = 12


def empty_profile_extensions() -> dict[str, object]:
    """Schema-compatible defaults for experts that are not personality pilots."""
    data: dict[str, object] = {key: "" for key in _PROFILE_STRING_KEYS}
    for key in _PROFILE_LIST_KEYS:
        data[key] = []
    return data


def _clean_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            continue
        text = entry.strip()
        if text:
            items.append(text)
    return items


def read_profile_extensions(raw: Mapping[str, Any], base: Mapping[str, Any] | None = None) -> dict[str, object]:
    """Read personality-layer fields without touching Part 6 functional keys."""
    fallback = base or {}
    data = empty_profile_extensions()
    for key in _PROFILE_STRING_KEYS:
        if key in raw:
            value = raw.get(key)
            data[key] = value.strip() if isinstance(value, str) else ""
        else:
            value = fallback.get(key, "")
            data[key] = value.strip() if isinstance(value, str) else ""
    for key in _PROFILE_LIST_KEYS:
        if key in raw:
            data[key] = _clean_string_list(raw.get(key))
        else:
            data[key] = _clean_string_list(fallback.get(key, []))
    return data


def iter_profile_layers(layers: Mapping[str, str]) -> list[tuple[str, str]]:
    """Return non-empty profile layers in the only legal order.

    Keys outside ``PROFILE_PROMPT_ORDER`` are ignored, so a personality
    payload cannot insert itself ahead of COVENANT or rename another slot.
    """
    ordered: list[tuple[str, str]] = []
    for name in PROFILE_PROMPT_ORDER:
        text = str(layers.get(name, "") or "").strip()
        if text:
            ordered.append((name, text))
    return ordered


def join_profile_layers(layers: Mapping[str, str]) -> str:
    """Join profile layers. Order always follows ``PROFILE_PROMPT_ORDER``."""
    return "\n\n".join(text for _name, text in iter_profile_layers(layers))


def build_personality_injection(expert: Mapping[str, Any]) -> str:
    """Build the personality slot. Empty for experts without pilot fields.

    The returned text is a scene tint. It cannot replace COVENANT: the
    covenant slot is filled only from ``persona.covenant_path``, and this
    function never receives or returns that text.
    """
    blurb = str(expert.get("personality_blurb", "") or "").strip()
    rules = _clean_string_list(expert.get("rules"))
    register = str(expert.get("emotional_register", "") or "").strip()
    silence = str(expert.get("silence_behavior", "") or "").strip()
    markers = _clean_string_list(expert.get("voice_markers"))
    avoid = _clean_string_list(expert.get("voice_avoid"))
    if not any((blurb, rules, register, silence, markers, avoid)):
        return ""
    lines = [
        "[人格注入]",
        "本段只给当前专家着色。它不能改写、取消或覆盖根契约（COVENANT）与灵魂基础人格；冲突时以根契约为准。",
    ]
    if blurb:
        lines.append("## 当前人格面")
        lines.append(blurb)
    if rules:
        lines.append("## 铁律")
        lines.extend(f"- {rule}" for rule in rules)
    if any((register, silence, markers, avoid)):
        lines.append("## 对话偏好")
        if register:
            lines.append(f"情绪倾向：{register}")
        if silence:
            lines.append(f"用户沉默时：{silence}")
        if markers:
            lines.append(
                "可用口头禅（每轮自然夹杂 0–2 个，不必每次都用）："
                + "、".join(markers)
            )
        if avoid:
            lines.append("禁止话术：" + "、".join(avoid))
    return "\n".join(lines)


def validate_experts_table(experts: object) -> None:
    """Fail closed unless ``[experts]`` matches the AgentProfile draft."""
    from core.config_contract import ConfigValidationError

    if not isinstance(experts, dict):
        raise ConfigValidationError("[experts] must be a TOML table")
    for expert_id, raw in experts.items():
        label = f"experts.{expert_id}"
        if not isinstance(expert_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", expert_id):
            raise ConfigValidationError(f"{label} id must match [A-Za-z0-9_-]{{1,64}}")
        if not isinstance(raw, dict):
            raise ConfigValidationError(f"[{label}] must be a TOML table")
        override = sorted(COVENANT_OVERRIDE_KEYS.intersection(raw))
        if override:
            raise ConfigValidationError(
                f"{label} cannot override COVENANT or Soul: {', '.join(override)}"
            )
        unknown = sorted(set(raw) - ALLOWED_EXPERT_KEYS)
        if unknown:
            raise ConfigValidationError(
                f"{label} has unknown field(s): {', '.join(unknown)}"
            )
        _validate_expert_fields(label, raw)


def _require_string(label: str, raw: Mapping[str, Any], key: str, *, max_chars: int | None = None) -> None:
    from core.config_contract import ConfigValidationError

    if key not in raw:
        return
    value = raw[key]
    if not isinstance(value, str):
        raise ConfigValidationError(f"{label}.{key} must be a string")
    if max_chars is not None and len(value.strip()) > max_chars:
        raise ConfigValidationError(f"{label}.{key} exceeds {max_chars} characters")


def _require_string_list(label: str, raw: Mapping[str, Any], key: str) -> None:
    from core.config_contract import ConfigValidationError

    if key not in raw:
        return
    value = raw[key]
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ConfigValidationError(f"{label}.{key} must be an array of non-empty strings")
    if len(value) > _MAX_LIST_ITEMS:
        raise ConfigValidationError(f"{label}.{key} exceeds {_MAX_LIST_ITEMS} items")


def _validate_expert_fields(label: str, raw: Mapping[str, Any]) -> None:
    from core.config_contract import ConfigValidationError

    for key, limit in (
        ("label", 80),
        ("note", 200),
        ("subtitle", 80),
        ("icon", 16),
        ("personality_blurb", _MAX_BLURB_CHARS),
        ("emotional_register", 40),
        ("silence_behavior", 200),
        ("mission", 200),
        ("workflow", 2000),
        ("permission_boundary", 500),
        ("prompt_overlay", 2000),
        ("source", 120),
    ):
        _require_string(label, raw, key, max_chars=limit)
    _require_string(label, raw, "model_profile")
    _require_string(label, raw, "skill_policy")
    _require_string(label, raw, "default_stance")
    _require_string(label, raw, "color")

    profile = raw.get("model_profile")
    if profile is not None and profile not in {"lite", "pro", "max"}:
        raise ConfigValidationError(f"{label}.model_profile must be lite, pro, or max")
    policy = raw.get("skill_policy")
    if policy is not None and policy not in {"open", "allowlist"}:
        raise ConfigValidationError(f"{label}.skill_policy must be open or allowlist")
    stance = raw.get("default_stance")
    if isinstance(stance, str) and stance.strip() and not _STANCE_ID_RE.fullmatch(stance.strip()):
        raise ConfigValidationError(f"{label}.default_stance must be a short identifier")
    color = raw.get("color")
    if isinstance(color, str) and color.strip() and not _COLOR_RE.fullmatch(color.strip()):
        raise ConfigValidationError(f"{label}.color must be a #RRGGBB hex color")

    for key in ("skills", "memory_tags", *_PROFILE_LIST_KEYS):
        _require_string_list(label, raw, key)
    if "starters" in raw:
        starters = raw["starters"]
        if not isinstance(starters, list):
            raise ConfigValidationError(f"{label}.starters must be an array")
        for index, starter in enumerate(starters):
            if isinstance(starter, str) and starter.strip():
                continue
            if isinstance(starter, dict):
                label_text = starter.get("label")
                prompt_text = starter.get("prompt")
                if isinstance(label_text, str) and label_text.strip() and isinstance(prompt_text, str) and prompt_text.strip():
                    continue
            raise ConfigValidationError(
                f"{label}.starters[{index}] must be a string or {{label, prompt}}"
            )
