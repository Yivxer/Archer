"""Resolve model credentials without persisting plaintext in ``archer.toml``."""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import re
import subprocess


KEYCHAIN_SERVICE = "com.archer.model-api"
_SECURITY = Path("/usr/bin/security")
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_PROFILE_ENV_VARS = {
    "lite": ("ARCHER_LITE_API_KEY", "DEEPSEEK_API_KEY"),
    "pro": ("ARCHER_PRO_API_KEY", "KIMI_API_KEY", "MOONSHOT_API_KEY"),
    "max": ("ARCHER_MAX_API_KEY", "GLM_API_KEY", "ZHIPU_API_KEY"),
}


class SecretStoreError(RuntimeError):
    """Raised when a credential cannot be safely persisted."""


def _environment_key(profile_id: str, reference: str = "") -> str:
    if reference.startswith("env:"):
        name = reference.removeprefix("env:")
        if not _ENV_NAME.fullmatch(name):
            raise SecretStoreError("invalid environment credential reference")
        return os.environ.get(name, "").strip()
    for name in _PROFILE_ENV_VARS.get(profile_id, ()):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def read_system_credential(profile_id: str) -> str:
    if not _SECURITY.exists():
        return ""
    result = subprocess.run(
        [str(_SECURITY), "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", profile_id, "-w"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def write_system_credential(profile_id: str, value: str) -> str:
    if not value:
        raise SecretStoreError("refusing to persist an empty API key")
    if not _SECURITY.exists():
        raise SecretStoreError("system credential store is unavailable; use an API key environment variable")
    result = subprocess.run(
        [
            str(_SECURITY), "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE,
            "-a", profile_id, "-w", value,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SecretStoreError("system credential store rejected the API key")
    if read_system_credential(profile_id) != value:
        raise SecretStoreError("system credential store verification failed")
    return f"keychain:{profile_id}"


def resolve_profile_api_key(profile_id: str, profile: dict) -> str:
    reference = str(profile.get("api_key_ref", "") or "").strip()
    if reference and not reference.startswith("env:") and reference != f"keychain:{profile_id}":
        raise SecretStoreError(f"invalid credential reference for profile {profile_id}")
    environment = _environment_key(profile_id, reference)
    if environment:
        return environment
    if reference.startswith("keychain:"):
        keychain = read_system_credential(profile_id)
        if keychain:
            return keychain
    # Transitional read-only compatibility. All save paths remove this field
    # only after the secure store accepts it.
    return str(profile.get("api_key", "") or "").strip()


def migrate_plaintext_api_keys(cfg: dict) -> dict:
    """Return a copy with plaintext keys replaced by credential references."""
    migrated = deepcopy(cfg)
    api = migrated.setdefault("api", {})
    profiles = migrated.setdefault("model_profiles", {})
    active_profile = str(api.get("active_profile", "lite") or "lite").strip().lower()

    for profile_id, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        plaintext = str(profile.get("api_key", "") or "").strip()
        if plaintext:
            profile["api_key_ref"] = write_system_credential(profile_id, plaintext)
            profile.pop("api_key", None)

    legacy = str(api.get("api_key", "") or "").strip()
    if legacy:
        active = profiles.setdefault(active_profile, {})
        if not active.get("api_key_ref"):
            active["api_key_ref"] = write_system_credential(active_profile, legacy)
        api["api_key_ref"] = active["api_key_ref"]
        api.pop("api_key", None)
    elif isinstance(profiles.get(active_profile), dict) and profiles[active_profile].get("api_key_ref"):
        api["api_key_ref"] = profiles[active_profile]["api_key_ref"]
        api.pop("api_key", None)
    return migrated
