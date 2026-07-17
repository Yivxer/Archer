"""Skills, modes, experts, settings, and model profile API domain."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

import tomli_w

from core.config_contract import validate_config
from core.secret_store import migrate_plaintext_api_keys, write_system_credential

from terminal.api._config import (
    CONFIG_PATH,
    SETTINGS_ALLOWED_FIELDS,
    _load_config,
    _mask_key,
    _read_text,
    mutate_config_text,
    write_config_text,
)

logger = logging.getLogger("archer_api")


# Skill routes
# ---------------------------------------------------------------------------

def _disabled_skills_path() -> str:
    return os.path.join(os.path.dirname(__file__), "..", "memory", "disabled_skills.json")


def _load_disabled_skills() -> set:
    path = _disabled_skills_path()
    if not os.path.exists(path):
        return set()
    try:
        with open(path) as f:
            data = json.load(f)
        return set(data) if isinstance(data, list) else set()
    except Exception:
        return set()


def _save_disabled_skills(disabled: set) -> None:
    path = _disabled_skills_path()
    with open(path, "w") as f:
        json.dump(sorted(disabled), f)


def _toggle_skill(name: str, enabled: bool) -> dict:
    disabled = _load_disabled_skills()
    if enabled:
        disabled.discard(name)
    else:
        disabled.add(name)
    _save_disabled_skills(disabled)
    return {"ok": True, "name": name, "enabled": enabled}


def _skills() -> list[dict]:
    from skills.loader import register_all_skills
    disabled = _load_disabled_skills()
    registry = register_all_skills()
    result = []
    for name, meta in sorted(registry.metas().items()):
        result.append({
            "name": name,
            "description": meta.description,
            "risk": meta.risk,
            "enabled": name not in disabled,
        })
    return result


# ---------------------------------------------------------------------------
# Settings routes
# ---------------------------------------------------------------------------

def _mode_label_from_file(path: Path, fallback: str) -> str:
    try:
        first_line = path.read_text(encoding="utf-8").splitlines()[0].strip()
    except Exception:
        return fallback
    match = re.search(r"[模式：:]\s*([^）\]]+)", first_line)
    return match.group(1).strip() if match else fallback


def _available_modes(cfg: dict) -> dict:
    persona = cfg.get("persona", {})
    mode_auto = persona.get("mode_auto", True) is not False
    locked = persona.get("current_mode", persona.get("default_mode", "listener"))
    current = "auto" if mode_auto else locked
    default = persona.get("default_mode", "listener")
    raw_modes = persona.get("modes", {})
    toml_modes = raw_modes if isinstance(raw_modes, dict) else {}
    modes_dir_raw = str(persona.get("modes_dir", "") or "").strip()
    modes_dir = Path(modes_dir_raw).expanduser() if modes_dir_raw else None
    try:
        from core.orchestrator import _MODE_LABELS, _VALID_MODES
    except Exception:
        _VALID_MODES = {
            "coach", "mirror", "listener", "questioner", "philosopher", "writer",
            "therapist", "witness", "ritualist", "critic", "builder", "operator",
        }
        _MODE_LABELS = {mode: mode for mode in _VALID_MODES}

    items: list[dict] = []
    seen: set[str] = set()
    if modes_dir and modes_dir.is_dir():
        for path in sorted(modes_dir.glob("*.md")):
            mode_id = path.stem
            if mode_id not in _VALID_MODES and mode_id not in toml_modes:
                continue
            seen.add(mode_id)
            items.append({
                "id": mode_id,
                "label": _mode_label_from_file(path, mode_id),
                "source": "file",
                "active": (not mode_auto) and mode_id == locked,
            })

    for mode_id, meta in sorted(toml_modes.items()):
        if mode_id in seen:
            continue
        seen.add(mode_id)
        label = meta.get("name", mode_id) if isinstance(meta, dict) else mode_id
        items.append({
            "id": mode_id,
            "label": label,
            "source": "toml",
            "active": (not mode_auto) and mode_id == locked,
        })

    for mode_id in sorted(_VALID_MODES):
        if mode_id in seen:
            continue
        items.append({
            "id": mode_id,
            "label": _MODE_LABELS.get(mode_id, mode_id),
            "source": "builtin",
            "active": (not mode_auto) and mode_id == locked,
        })

    fallback_applied = not mode_auto and locked not in seen
    if fallback_applied:
        logger.warning("unknown configured mode %s; projecting auto fallback", locked)
        current = "auto"
    return {
        "current": current,
        "default": default,
        "modes": items,
        "modeAuto": mode_auto or fallback_applied,
        "fallbackApplied": fallback_applied,
    }


def _persist_current_mode(mode: str) -> None:
    def _mutate(text: str) -> str:
        new_line = f'current_mode = "{mode}"'
        if re.search(r'^current_mode\s*=', text, re.MULTILINE):
            return re.sub(r'^current_mode\s*=.*$', new_line, text, flags=re.MULTILINE)
        if re.search(r'^default_mode\s*=', text, re.MULTILINE):
            return re.sub(r'^(default_mode\s*=.*)$', rf'\1\n{new_line}', text, flags=re.MULTILINE)
        if "[persona]" in text:
            return re.sub(r'^\[persona\]\s*$', f"[persona]\n{new_line}", text, count=1, flags=re.MULTILINE)
        return text.rstrip() + f'\n\n[persona]\n{new_line}\n'

    mutate_config_text(_mutate)


def _persist_mode_auto(flag: bool) -> None:
    def _mutate(text: str) -> str:
        new_line = f'mode_auto = {"true" if flag else "false"}'
        if re.search(r'^mode_auto\s*=', text, re.MULTILINE):
            return re.sub(r'^mode_auto\s*=.*$', new_line, text, flags=re.MULTILINE)
        if re.search(r'^default_mode\s*=', text, re.MULTILINE):
            return re.sub(r'^(default_mode\s*=.*)$', rf'\1\n{new_line}', text, flags=re.MULTILINE)
        if "[persona]" in text:
            return re.sub(r'^\[persona\]\s*$', f"[persona]\n{new_line}", text, count=1, flags=re.MULTILINE)
        return text.rstrip() + f'\n\n[persona]\n{new_line}\n'

    mutate_config_text(_mutate)


def _persist_current_expert(expert_id: str) -> None:
    def _mutate(text: str) -> str:
        new_line = f'current_expert = "{expert_id}"'
        if re.search(r"^current_expert\s*=", text, re.MULTILINE):
            return re.sub(r"^current_expert\s*=.*$", new_line, text, flags=re.MULTILINE)
        if re.search(r"^default_mode\s*=", text, re.MULTILINE):
            return re.sub(r"^(default_mode\s*=.*)$", rf"\1\n{new_line}", text, flags=re.MULTILINE)
        if "[persona]" in text:
            return re.sub(r"^\[persona\]\s*$", f"[persona]\n{new_line}", text, count=1, flags=re.MULTILINE)
        return text.rstrip() + f"\n\n[persona]\n{new_line}\n"

    mutate_config_text(_mutate)


def _persist_active_profile(profile_id: str) -> None:
    def _mutate(text: str) -> str:
        new_line = f'active_profile = "{profile_id}"'
        if re.search(r"^active_profile\s*=", text, re.MULTILINE):
            return re.sub(r"^active_profile\s*=.*$", new_line, text, flags=re.MULTILINE)
        if re.search(r"^model\s*=", text, re.MULTILINE):
            return re.sub(r"^(model\s*=.*)$", rf"\1\n{new_line}", text, flags=re.MULTILINE, count=1)
        if "[api]" in text:
            return re.sub(r"^\[api\]\s*$", f"[api]\n{new_line}", text, count=1, flags=re.MULTILINE)
        return text.rstrip() + f"\n\n[api]\n{new_line}\n"

    mutate_config_text(_mutate)


def _expert_catalog_items(cfg: dict) -> list[dict]:
    from core.experts import (
        BUILTIN_EXPERT_IDS,
        expert_ids,
        expert_model_configured,
        expert_model_profile_id,
        expert_skill_allowlist,
        expert_starters,
        experts,
    )

    catalog = experts(cfg)
    items = []
    for expert_id in expert_ids(cfg):
        expert = catalog[expert_id]
        allowlist = expert_skill_allowlist(expert)
        source = str(expert.get("source", "builtin") or "builtin")
        items.append({
            "id": expert_id,
            "label": str(expert.get("label", expert_id)),
            "note": str(expert.get("note", "")),
            "modelProfile": expert_model_profile_id(expert),
            "skillCount": len(allowlist) if allowlist else 0,
            "configured": True,
            "modelConfigured": expert_model_configured(cfg, expert),
            "starters": expert_starters(expert),
            "source": source,
            "custom": expert_id not in BUILTIN_EXPERT_IDS,
        })
    return items


def _available_experts(cfg: dict) -> dict:
    from core.experts import active_expert_id
    persona = cfg.get("persona", {}) if isinstance(cfg.get("persona"), dict) else {}
    configured = str(persona.get("current_expert", "default") or "default").strip()
    current = active_expert_id(cfg)
    fallback_applied = configured != current
    if fallback_applied:
        logger.warning("unknown configured expert %s; projecting default fallback", configured)
    return {
        "current": current,
        "experts": _expert_catalog_items(cfg),
        "fallbackApplied": fallback_applied,
    }


def _switch_current_expert(payload: dict, cfg: dict) -> dict:
    from core.experts import (
        active_expert_id,
        expert_ids,
        expert_model_profile_id,
        experts,
    )

    expert_id = str(payload.get("expert", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", expert_id):
        raise ValueError("expert must be a short identifier")
    if expert_id not in expert_ids(cfg):
        raise ValueError(f"unknown expert: {expert_id}")

    catalog = experts(cfg)
    expert = catalog[expert_id]
    model_profile = expert_model_profile_id(expert)

    _persist_current_expert(expert_id)
    label = str(expert.get("label", expert_id))
    return {
        "ok": True,
        "current": expert_id,
        "label": label,
        "modelProfile": model_profile,
        "recommendedModelProfile": model_profile,
        "previous": active_expert_id(cfg),
    }


def _switch_current_mode(payload: dict, cfg: dict) -> dict:
    mode = str(payload.get("mode", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", mode):
        raise ValueError("mode must be a short identifier")
    available = _available_modes(cfg)
    # 特殊值 "auto"：恢复每轮自动选择姿态
    if mode == "auto":
        _persist_mode_auto(True)
        return {
            "ok": True,
            "current": "auto",
            "label": "自动",
            "modes": [{**item, "active": False} for item in available["modes"]],
        }
    modes = {item["id"]: item for item in available["modes"]}
    if mode not in modes:
        raise ValueError(f"unknown mode: {mode}")
    _persist_current_mode(mode)
    _persist_mode_auto(False)
    return {
        "ok": True,
        "current": mode,
        "label": modes[mode]["label"],
        "modes": [{**item, "active": item["id"] == mode} for item in available["modes"]],
    }


def _soul_files(cfg: dict) -> dict:
    persona = cfg.get("persona", {})
    return {
        "SOUL.md": _read_text(persona.get("soul_path")),
        "MEMORY.md": _read_text(persona.get("memory_path")),
        "COVENANT.md": _read_text(persona.get("covenant_path")),
        "PRESENCE.md": _read_text(persona.get("presence_path")),
    }


def _soul_profile_summary(cfg: dict) -> dict:
    from memory.soul_profile import _FIELD_LABELS, load_soul_profile
    from memory.store import list_by_type

    profile = load_soul_profile(cfg.get("persona", {}).get("soul_profile_path"))
    section_fields = [
        "core_values",
        "emotional_patterns",
        "life_themes",
        "creative_identity",
        "current_life_stage",
        "rhythm",
        "narrative",
        "tensions",
        "patterns",
    ]
    sections = [
        {
            "id": field_name,
            "label": _FIELD_LABELS.get(field_name, field_name),
            "items": list(getattr(profile, field_name, []))[:4],
        }
        for field_name in section_fields
    ]
    growth_markers = [
        item.get("content", "")
        for item in list_by_type("growth_marker", min_importance=1, limit=4)
        if item.get("content")
    ]
    sections.append({
        "id": "growth_markers",
        "label": "成长标记",
        "items": growth_markers,
    })
    return {
        "empty": not any(section["items"] for section in sections),
        "sections": sections,
    }


def _period_review(period: str) -> dict:
    from core.session import SESSIONS_DIR
    from memory.period_review import build_period_review
    from memory.store import DB_PATH

    return build_period_review(
        db_path=Path(DB_PATH),
        sessions_dir=Path(SESSIONS_DIR),
        period=period,
    )


def _journal_review(cfg: dict, days: int) -> dict:
    from memory.journal_review import build_journal_review
    from memory.store import DB_PATH

    return build_journal_review(
        vault_path=cfg.get("obsidian", {}).get("vault_path"),
        db_path=Path(DB_PATH),
        days=days,
    )


def _settings(cfg: dict) -> dict:
    from core.experts import active_expert_id
    from core.model_profiles import active_api_config, active_model_profile_id, model_profiles
    api = active_api_config(cfg)
    profiles = model_profiles(cfg)
    memory = cfg.get("memory", {})
    paths = cfg.get("paths", {})
    return {
        "activeProfile": active_model_profile_id(cfg),
        "activeExpert": active_expert_id(cfg),
        "experts": _expert_catalog_items(cfg),
        "modelProfiles": [
            {
                "id": profile_id,
                "label": str(profile.get("label", profile_id)),
                "provider": str(profile.get("provider", "")),
                "baseUrl": str(profile.get("base_url", "")),
                "model": str(profile.get("model", "")),
                "apiKeyPreview": _mask_key(str(profile.get("api_key", ""))),
                "configured": bool(profile.get("base_url") and profile.get("model") and profile.get("api_key")),
            }
            for profile_id, profile in profiles.items()
        ],
        "provider": api.get("provider", "OpenAI-compatible"),
        "baseUrl": api.get("base_url", ""),
        "model": api.get("model", ""),
        "apiKeyPreview": _mask_key(api.get("api_key", "")),
        "configPath": str(CONFIG_PATH),
        "memoryDbPath": memory.get("db_path", ""),
        "sessionsPath": paths.get("sessions_dir", ""),
    }


def _validate_settings_draft(payload: dict) -> dict:
    draft = payload.get("settings")
    if not isinstance(draft, dict):
        raise ValueError("settings must be an object")
    errors: list[str] = []
    allowed: dict[str, str] = {}
    blocked = sorted(key for key in draft.keys() if key not in SETTINGS_ALLOWED_FIELDS and key != "apiKeyPreview")
    for key in sorted(SETTINGS_ALLOWED_FIELDS):
        value = draft.get(key, "")
        if value is None:
            value = ""
        if not isinstance(value, str):
            errors.append(f"{key} must be a string")
            continue
        clean = value.strip()
        if len(clean) > 2048:
            errors.append(f"{key} is too long")
            continue
        allowed[key] = clean
    base_url = allowed.get("baseUrl", "")
    if base_url and not re.fullmatch(r"https?://[^\s]+", base_url):
        errors.append("baseUrl must start with http:// or https://")
    active_profile = allowed.get("activeProfile", "")
    if active_profile and active_profile not in ("lite", "pro", "max"):
        errors.append("activeProfile must be lite, pro, or max")
    model = allowed.get("model", "")
    if model and not re.fullmatch(r"[A-Za-z0-9._:/@+-]{1,160}", model):
        errors.append("model contains unsupported characters")
    api_key = allowed.get("apiKey", "")
    if api_key and ("\n" in api_key or "\r" in api_key):
        errors.append("apiKey must be a single line")
    for key in ("configPath", "memoryDbPath", "sessionsPath"):
        value = allowed.get(key, "")
        if "\x00" in value:
            errors.append(f"{key} contains an invalid character")
    return {
        "ok": not errors,
        "dryRun": True,
        "writable": False,
        "allowedFields": sorted(SETTINGS_ALLOWED_FIELDS),
        "blockedFields": blocked,
        "errors": errors,
        "message": (
            "settings draft passed validation; archer.toml write is intentionally disabled"
            if not errors
            else "settings draft has validation errors; archer.toml was not changed"
        ),
    }


def _save_settings_draft(payload: dict) -> dict:
    """Validate and save settings draft to archer.toml."""
    validation = _validate_settings_draft(payload)
    if not validation["ok"]:
        return {
            **validation,
            "savedFields": [],
            "restartRequired": False,
            "message": f"验证未通过，未保存；{validation['message']}",
        }
    draft = payload.get("settings", {})
    allowed_fields = validation["allowedFields"]
    backup_path = CONFIG_PATH.with_suffix(".toml.bak")
    if CONFIG_PATH.exists():
        backup_path.write_bytes(CONFIG_PATH.read_bytes())
    try:
        cfg = _load_config()
        if "api" not in cfg:
            cfg["api"] = {}
        if not isinstance(cfg.get("model_profiles"), dict):
            cfg["model_profiles"] = {}
        if "memory" not in cfg:
            cfg["memory"] = {}
        if "paths" not in cfg:
            cfg["paths"] = {}
        active_profile = draft.get("activeProfile", cfg["api"].get("active_profile", "lite")) or "lite"
        cfg["api"]["active_profile"] = active_profile
        profile_cfg = cfg["model_profiles"].setdefault(active_profile, {})
        profile_cfg["provider"] = draft.get("provider", profile_cfg.get("provider", ""))
        profile_cfg["base_url"] = draft.get("baseUrl", profile_cfg.get("base_url", ""))
        profile_cfg["model"] = draft.get("model", profile_cfg.get("model", ""))
        api_key = str(draft.get("apiKey", "") or "").strip()
        if api_key:
            profile_cfg["api_key_ref"] = write_system_credential(active_profile, api_key)
            profile_cfg.pop("api_key", None)
        cfg["api"]["base_url"] = draft.get("baseUrl", cfg["api"].get("base_url", ""))
        cfg["api"]["model"] = draft.get("model", cfg["api"].get("model", ""))
        if api_key:
            cfg["api"]["api_key_ref"] = profile_cfg["api_key_ref"]
            cfg["api"].pop("api_key", None)
        cfg["memory"]["db_path"] = draft.get("memoryDbPath", cfg["memory"].get("db_path", ""))
        cfg["paths"]["sessions_dir"] = draft.get("sessionsPath", cfg["paths"].get("sessions_dir", ""))
        cfg = validate_config(migrate_plaintext_api_keys(cfg))
        write_config_text(tomli_w.dumps(cfg))
        try:
            _load_config()
        except Exception as parse_exc:
            if backup_path.exists():
                CONFIG_PATH.write_bytes(backup_path.read_bytes())
            return {
                "ok": False, "savedFields": [], "restartRequired": False,
                "errors": [f"写入后配置文件损坏：{parse_exc}"],
                "message": "保存失败：配置文件写回损坏，已回滚",
            }
        restart_required = bool(
            draft.get("memoryDbPath") or draft.get("configPath") or draft.get("sessionsPath")
        )
        return {
            "ok": True,
            "savedFields": sorted(allowed_fields),
            "restartRequired": restart_required,
            "errors": [],
            "message": f"已保存 {len(allowed_fields)} 个字段到 archer.toml" + ("；需要重启 Archer API" if restart_required else ""),
        }
    except Exception as exc:
        if backup_path.exists():
            CONFIG_PATH.write_bytes(backup_path.read_bytes())
        return {
            "ok": False, "savedFields": [], "restartRequired": False,
            "errors": [str(exc)],
            "message": f"保存失败：{exc}；已回滚到备份",
        }
    finally:
        if backup_path.exists() and CONFIG_PATH.exists():
            try:
                if backup_path.read_bytes() == CONFIG_PATH.read_bytes():
                    backup_path.unlink()
            except Exception:
                pass


def _save_profile_settings(payload: dict) -> dict:
    """独立保存单个 model profile 的配置，不影响其他 profile。

    payload 结构：
    {
        "profileId": "lite" | "pro" | "max",
        "provider": "...",
        "baseUrl": "...",
        "model": "...",
        "apiKey": "..."  # 空字符串表示不更新 key
    }
    """
    from core.model_profiles import MODEL_PROFILE_IDS

    profile_id = str(payload.get("profileId", "") or "").strip().lower()
    if profile_id not in MODEL_PROFILE_IDS:
        return {"ok": False, "error": f"无效的 profileId: {profile_id}"}

    backup_path = CONFIG_PATH.with_suffix(".toml.bak")
    if CONFIG_PATH.exists():
        backup_path.write_bytes(CONFIG_PATH.read_bytes())
    try:
        cfg = _load_config()
        if not isinstance(cfg.get("model_profiles"), dict):
            cfg["model_profiles"] = {}
        profile_cfg = cfg["model_profiles"].setdefault(profile_id, {})

        # 只更新非空字段，空字段保留原值（避免清空已有配置）
        provider = str(payload.get("provider", "") or "").strip()
        base_url = str(payload.get("baseUrl", "") or "").strip()
        model = str(payload.get("model", "") or "").strip()
        api_key = str(payload.get("apiKey", "") or "").strip()

        if provider:
            profile_cfg["provider"] = provider
        if base_url:
            profile_cfg["base_url"] = base_url
        if model:
            profile_cfg["model"] = model
        if api_key:
            profile_cfg["api_key_ref"] = write_system_credential(profile_id, api_key)
            profile_cfg.pop("api_key", None)

        # 如果保存的是当前 active profile，同步更新 [api] 段
        active_profile = str(cfg.get("api", {}).get("active_profile", "lite"))
        if active_profile == profile_id:
            if base_url:
                cfg["api"]["base_url"] = base_url
            if model:
                cfg["api"]["model"] = model
            if api_key:
                cfg["api"]["api_key_ref"] = profile_cfg["api_key_ref"]
                cfg["api"].pop("api_key", None)

        cfg = validate_config(migrate_plaintext_api_keys(cfg))
        write_config_text(tomli_w.dumps(cfg))
        try:
            _load_config()
        except Exception as parse_exc:
            if backup_path.exists():
                CONFIG_PATH.write_bytes(backup_path.read_bytes())
            return {
                "ok": False,
                "error": f"写入后配置文件损坏：{parse_exc}，已回滚",
            }
        return {
            "ok": True,
            "profileId": profile_id,
            "message": f"已保存 {profile_id} 配置",
        }
    except Exception as exc:
        if backup_path.exists():
            CONFIG_PATH.write_bytes(backup_path.read_bytes())
        return {"ok": False, "error": f"保存失败：{exc}，已回滚"}
    finally:
        if backup_path.exists() and CONFIG_PATH.exists():
            try:
                if backup_path.read_bytes() == CONFIG_PATH.read_bytes():
                    backup_path.unlink()
            except Exception:
                pass


def _switch_active_profile(payload: dict) -> dict:
    """只切换 active_profile，不修改任何 profile 的配置。

    会从目标 profile 同步 base_url/model/api_key 到 [api] 段（仅当 profile 中存在该字段时），
    确保 legacy 代码读取 [api] 段时拿到的是新 profile 的配置。
    不会删除或覆盖任何 [model_profiles.*] 段的内容。
    """
    from core.model_profiles import MODEL_PROFILE_IDS, model_profiles

    profile_id = str(payload.get("profileId", "") or "").strip().lower()
    if profile_id not in MODEL_PROFILE_IDS:
        return {"ok": False, "error": f"无效的 profileId: {profile_id}"}

    backup_path = CONFIG_PATH.with_suffix(".toml.bak")
    if CONFIG_PATH.exists():
        backup_path.write_bytes(CONFIG_PATH.read_bytes())
    try:
        cfg = _load_config()
        if "api" not in cfg or not isinstance(cfg.get("api"), dict):
            cfg["api"] = {}
        cfg["api"]["active_profile"] = profile_id
        cfg["api"].pop("api_key", None)
        cfg["api"].pop("api_key_ref", None)

        # 从已解析的 profile 同步字段到 [api] 段（仅当 profile 有该字段且非空时）
        profiles = model_profiles(cfg)
        target = profiles.get(profile_id, {})
        for key in ("provider", "base_url", "model", "api_key_ref", "vision_model"):
            val = target.get(key)
            if val not in ("", None):
                cfg["api"][key] = val

        cfg = validate_config(cfg)
        write_config_text(tomli_w.dumps(cfg))
        try:
            _load_config()
        except Exception as parse_exc:
            if backup_path.exists():
                CONFIG_PATH.write_bytes(backup_path.read_bytes())
            return {"ok": False, "error": f"写入后配置文件损坏：{parse_exc}，已回滚"}
        return {
            "ok": True,
            "profileId": profile_id,
            "activeProfile": profile_id,
            "message": f"已切换到 {profile_id}",
        }
    except Exception as exc:
        if backup_path.exists():
            CONFIG_PATH.write_bytes(backup_path.read_bytes())
        return {"ok": False, "error": f"切换失败：{exc}，已回滚"}
    finally:
        if backup_path.exists() and CONFIG_PATH.exists():
            try:
                if backup_path.read_bytes() == CONFIG_PATH.read_bytes():
                    backup_path.unlink()
            except Exception:
                pass


def _model_test_config_from_draft(payload: dict, cfg: dict) -> dict:
    from core.model_profiles import active_api_config, active_model_profile_id, cfg_with_active_api

    draft = payload.get("settings")
    if not isinstance(draft, dict):
        raise ValueError("settings must be an object")
    validation = _validate_settings_draft(payload)
    if not validation["ok"]:
        return {"ok": False, "errors": validation["errors"]}

    test_cfg = dict(cfg)
    api = dict(test_cfg.get("api", {}) if isinstance(test_cfg.get("api"), dict) else {})
    active_profile = str(draft.get("activeProfile") or api.get("active_profile") or "lite")
    api["active_profile"] = active_profile
    test_cfg["api"] = api

    current_profile = active_model_profile_id(cfg)
    current_api = active_api_config(cfg)
    profiles = dict(test_cfg.get("model_profiles", {}) if isinstance(test_cfg.get("model_profiles"), dict) else {})
    profile = dict(profiles.get(active_profile, {}) if isinstance(profiles.get(active_profile), dict) else {})
    draft_profiles = draft.get("modelProfiles")
    if isinstance(draft_profiles, list):
        for item in draft_profiles:
            if not isinstance(item, dict) or str(item.get("id", "")).strip().lower() != active_profile:
                continue
            for draft_key, profile_key in (("provider", "provider"), ("baseUrl", "base_url"), ("model", "model")):
                value = str(item.get(draft_key, "") or "").strip()
                if value:
                    profile[profile_key] = value
            break
    for draft_key, profile_key in (("provider", "provider"), ("baseUrl", "base_url"), ("model", "model"), ("apiKey", "api_key")):
        value = str(draft.get(draft_key, "") or "").strip()
        if value:
            if (
                profile_key != "api_key"
                and active_profile != current_profile
                and value == str(current_api.get(profile_key, "") or "").strip()
            ):
                continue
            profile[profile_key] = value
    profiles[active_profile] = profile
    test_cfg["model_profiles"] = profiles
    return cfg_with_active_api(test_cfg)


def _test_model_profile(payload: dict, cfg: dict) -> dict:
    test_cfg = _model_test_config_from_draft(payload, cfg)
    if test_cfg.get("ok") is False:
        return {
            "ok": False,
            "profile": "",
            "provider": "",
            "model": "",
            "baseUrl": "",
            "latencyMs": 0,
            "message": "模型配置校验失败",
            "errors": test_cfg.get("errors", []),
        }

    api = test_cfg["api"]
    profile = str(api.get("active_profile", "lite"))
    provider = str(api.get("provider", ""))
    base_url = str(api.get("base_url", ""))
    model = str(api.get("model", ""))
    api_key = str(api.get("api_key", ""))
    missing = [
        name
        for name, value in (("baseUrl", base_url), ("model", model), ("apiKey", api_key))
        if not value
    ]
    if missing:
        return {
            "ok": False,
            "profile": profile,
            "provider": provider,
            "model": model,
            "baseUrl": base_url,
            "latencyMs": 0,
            "message": f"缺少字段：{', '.join(missing)}",
            "errors": [f"missing {name}" for name in missing],
        }

    try:
        from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
    except Exception as exc:
        return {
            "ok": False,
            "profile": profile,
            "provider": provider,
            "model": model,
            "baseUrl": base_url,
            "latencyMs": 0,
            "message": f"OpenAI SDK 不可用：{exc}",
            "errors": [str(exc)],
        }

    started = time.perf_counter()
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=20, max_retries=0)
        temperature = 1 if "moonshot." in base_url.lower() else 0
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=4,
            temperature=temperature,
            stream=False,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        content = response.choices[0].message.content if response.choices else ""
        return {
            "ok": True,
            "profile": profile,
            "provider": provider,
            "model": model,
            "baseUrl": base_url,
            "latencyMs": latency_ms,
            "message": "模型连接测试通过",
            "sample": (content or "").strip()[:40],
            "errors": [],
        }
    except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "ok": False,
            "profile": profile,
            "provider": provider,
            "model": model,
            "baseUrl": base_url,
            "latencyMs": latency_ms,
            "message": f"模型连接测试失败：{exc.__class__.__name__}",
            "errors": [str(exc)[:500]],
        }
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "ok": False,
            "profile": profile,
            "provider": provider,
            "model": model,
            "baseUrl": base_url,
            "latencyMs": latency_ms,
            "message": "模型连接测试失败",
            "errors": [str(exc)[:500]],
        }


# ---------------------------------------------------------------------------
