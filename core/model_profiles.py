"""Model profile resolution for Archer API tiers."""
from __future__ import annotations

import os
from copy import deepcopy

MODEL_PROFILE_IDS = ("lite", "pro", "max")

DEFAULT_MODEL_PROFILES: dict[str, dict[str, object]] = {
    "lite": {
        "label": "DSK",
        "provider": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "model": "deepseek-chat",
        "model_auto": True,
        "vision_model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "pro": {
        "label": "KIM",
        "provider": "Kimi",
        "base_url": "",
        "api_key": "",
        "model": "",
        "model_auto": False,
        "vision_model": "",
        "models": [],
    },
    "max": {
        "label": "GLM",
        "provider": "GLM",
        "base_url": "",
        "api_key": "",
        "model": "",
        "model_auto": False,
        "vision_model": "",
        "models": [],
    },
}


def active_model_profile_id(cfg: dict) -> str:
    api = cfg.get("api", {}) if isinstance(cfg.get("api"), dict) else {}
    profile_id = str(api.get("active_profile", "lite") or "lite").strip().lower()
    return profile_id if profile_id in MODEL_PROFILE_IDS else "lite"


def model_profiles(cfg: dict) -> dict[str, dict[str, object]]:
    api = cfg.get("api", {}) if isinstance(cfg.get("api"), dict) else {}
    configured = cfg.get("model_profiles", {})
    if not isinstance(configured, dict):
        configured = {}

    profiles = deepcopy(DEFAULT_MODEL_PROFILES)
    for profile_id in MODEL_PROFILE_IDS:
        raw = configured.get(profile_id, {})
        if isinstance(raw, dict):
            profiles[profile_id].update({key: value for key, value in raw.items() if value is not None})

    # Backward compatibility: old configs kept the default chat model directly
    # under [api]. Treat that as lite only when lite is not explicitly present
    # and the active profile is still lite; otherwise Kimi/GLM top-level fields
    # can leak into the DeepSeek card after switching profiles.
    has_lite_profile = isinstance(configured.get("lite"), dict)
    active_profile = str(api.get("active_profile", "lite") or "lite").strip().lower()
    if not has_lite_profile and active_profile == "lite":
        for key in ("provider", "base_url", "api_key", "model", "model_auto", "vision_model", "models"):
            if key in api:
                profiles["lite"][key] = api[key]

    lite = profiles["lite"]
    lite_url = str(lite.get("base_url", "")).lower()
    api_url = str(api.get("base_url", "")).lower()
    if lite.get("base_url") and lite.get("model") and not str(lite.get("api_key", "")).strip():
        if "deepseek" in lite_url and "deepseek" in api_url and api.get("api_key"):
            lite["api_key"] = api["api_key"]
        env_key = (
            os.environ.get("DEEPSEEK_API_KEY", "").strip()
            or os.environ.get("ARCHER_LITE_API_KEY", "").strip()
        )
        if env_key:
            lite["api_key"] = env_key

    return profiles


def active_api_config(cfg: dict) -> dict:
    api = dict(cfg.get("api", {}) if isinstance(cfg.get("api"), dict) else {})
    profile_id = active_model_profile_id(cfg)
    profile = dict(model_profiles(cfg)[profile_id])

    for key in ("provider", "base_url", "api_key", "model", "model_auto", "vision_model", "models"):
        value = profile.get(key)
        if value not in ("", [], None):
            api[key] = value
        elif key not in api:
            api[key] = value
    api["active_profile"] = profile_id
    return api


def cfg_with_active_api(cfg: dict) -> dict:
    resolved = dict(cfg)
    resolved["api"] = active_api_config(cfg)
    return resolved
