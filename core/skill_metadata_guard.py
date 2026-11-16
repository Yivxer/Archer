"""Fail closed when a tool call has no usable skill metadata.

Known skills with an explicit risk keep their existing policy. A missing
module, a non-dict SKILL payload, or a risk value outside the known set
cannot be treated as a low-risk allow.
"""
from __future__ import annotations

_KNOWN_RISKS = {"low", "medium", "high", "critical"}


def skill_call_metadata(mod):
    raw = getattr(mod, "SKILL", None) if mod is not None else None
    meta = raw if isinstance(raw, dict) else {}
    declared = meta.get("risk", None)
    risk = "low" if declared is None else str(declared).strip().lower()
    return raw, meta, declared, risk


def untrusted_skill_metadata_reason(mod, raw_meta, declared_risk, risk, skill_name: str) -> str:
    if mod is None or not isinstance(raw_meta, dict):
        return f"技能 [{skill_name}] 缺少可用元数据，不能按只读直接执行"
    if declared_risk is not None and risk not in _KNOWN_RISKS:
        return f"技能 [{skill_name}] 的风险元数据无法识别，不能按只读直接执行"
    return ""
