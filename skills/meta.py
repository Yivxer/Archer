"""P5.3 — Skill metadata parsing."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    keywords: tuple[str, ...] = ()
    risk: str = "low"
    model_preference: str = ""
    auto_trigger: bool = True


def _normalize_keywords(raw: object) -> tuple[str, ...]:
    if not raw:
        return ()
    if isinstance(raw, str):
        parts = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, (list, tuple, set)):
        parts = [str(part).strip() for part in raw]
    else:
        return ()
    return tuple(part for part in parts if part)


def parse_skill_meta(mod: Any) -> SkillMeta | None:
    skill = getattr(mod, "SKILL", None) or {}
    meta = getattr(mod, "__meta__", None) or {}
    if not isinstance(skill, dict):
        skill = {}
    if not isinstance(meta, dict):
        meta = {}

    name = str(meta.get("name") or skill.get("name") or getattr(mod, "__name__", "")).strip()
    if not name:
        return None

    description = str(
        meta.get("description")
        or skill.get("description")
        or (getattr(mod, "__doc__", "") or "").strip().split("\n")[0]
        or name
    ).strip()

    raw_risk = meta.get("risk") if isinstance(meta, dict) else None
    if raw_risk is None or (isinstance(raw_risk, str) and not raw_risk.strip()):
        raw_risk = skill.get("risk") if isinstance(skill, dict) else None
    risk = str(raw_risk).strip().lower() if raw_risk is not None else ""
    if risk not in {"low", "medium", "high", "critical"}:
        risk = "unknown"

    auto_trigger = meta.get("auto_trigger", True)
    if isinstance(auto_trigger, str):
        auto_trigger = auto_trigger.strip().lower() not in {"0", "false", "no", "off"}

    return SkillMeta(
        name=name,
        description=description,
        keywords=_normalize_keywords(meta.get("keywords")),
        risk=risk,
        model_preference=str(meta.get("model_preference") or "").strip(),
        auto_trigger=bool(auto_trigger),
    )
