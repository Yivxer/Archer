"""Versioned validation contract for ``archer.toml``."""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import tomllib

import tomli_w

from core.secret_store import migrate_plaintext_api_keys


CURRENT_CONFIG_VERSION = 2
KNOWN_TOP_LEVEL_FIELDS = frozenset({
    "config_version", "api", "model_profiles", "persona", "memory", "paths",
    "context", "ui", "obsidian", "critique", "security", "mcp",
})


class ConfigValidationError(ValueError):
    """Raised when a configuration cannot be safely interpreted."""


def _validate_mcp_config(mcp: dict) -> None:
    servers = mcp.get("servers", [])
    if not isinstance(servers, list):
        raise ConfigValidationError("mcp.servers must be an array of tables")
    names: set[str] = set()
    for index, server in enumerate(servers):
        label = f"mcp.servers[{index}]"
        if not isinstance(server, dict):
            raise ConfigValidationError(f"{label} must be a TOML table")
        name = str(server.get("name", "")).strip()
        if not name:
            raise ConfigValidationError(f"{label}.name is required")
        if name in names:
            raise ConfigValidationError(f"duplicate MCP server name: {name}")
        names.add(name)
        enabled = server.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ConfigValidationError(f"{label}.enabled must be a boolean")
        if not enabled:
            continue
        permissions = server.get("permissions")
        if not isinstance(permissions, dict):
            raise ConfigValidationError(f"{label}.permissions is required when enabled")
        tools = permissions.get("tools")
        if not isinstance(tools, dict) or not tools:
            raise ConfigValidationError(f"{label}.permissions.tools must not be empty")
        invalid = sorted(
            str(tool) for tool, level in tools.items()
            if str(level).strip().lower() not in {"read", "write"}
        )
        if invalid:
            raise ConfigValidationError(
                f"{label}.permissions.tools has invalid level: {', '.join(invalid)}"
            )
        domains = permissions.get("allowed_domains", [])
        if not isinstance(domains, list) or any(
            not isinstance(domain, str) or not domain.strip() for domain in domains
        ):
            raise ConfigValidationError(
                f"{label}.permissions.allowed_domains must be an array of domains"
            )
        transport = str(server.get("transport", "stdio")).strip().lower()
        if transport in {"streamable_http", "http", "remote"}:
            from core.mcp import _url_domain_allowed

            if not _url_domain_allowed(str(server.get("url", "")), domains):
                raise ConfigValidationError(
                    f"{label}.url must use http(s) and match permissions.allowed_domains"
                )


def validate_config(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise ConfigValidationError("archer.toml root must be a TOML table")

    cfg = deepcopy(raw)
    unknown = sorted(set(cfg) - KNOWN_TOP_LEVEL_FIELDS)
    if unknown:
        raise ConfigValidationError(f"unknown top-level config field(s): {', '.join(unknown)}")
    version = cfg.get("config_version", 0)
    if isinstance(version, bool) or not isinstance(version, int):
        raise ConfigValidationError("config_version must be an integer")
    if version < 0:
        raise ConfigValidationError("config_version cannot be negative")
    if version > CURRENT_CONFIG_VERSION:
        raise ConfigValidationError(
            f"config_version {version} is newer than supported version {CURRENT_CONFIG_VERSION}"
        )

    for section in ("api", "model_profiles", "memory", "paths", "persona", "security", "mcp"):
        value = cfg.get(section)
        if value is not None and not isinstance(value, dict):
            raise ConfigValidationError(f"[{section}] must be a TOML table")

    api = cfg.get("api", {})
    active_profile = api.get("active_profile") if isinstance(api, dict) else None
    if active_profile is not None and active_profile not in ("lite", "pro", "max"):
        raise ConfigValidationError("api.active_profile must be lite, pro, or max")

    profiles = cfg.get("model_profiles", {})
    if isinstance(profiles, dict):
        for profile_id, profile in profiles.items():
            if profile_id not in ("lite", "pro", "max"):
                raise ConfigValidationError(f"unknown model profile: {profile_id}")
            if not isinstance(profile, dict):
                raise ConfigValidationError(f"[model_profiles.{profile_id}] must be a TOML table")

    mcp = cfg.get("mcp", {})
    if isinstance(mcp, dict):
        _validate_mcp_config(mcp)

    cfg["config_version"] = CURRENT_CONFIG_VERSION
    return cfg


def load_config_file(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigValidationError(f"invalid TOML: {exc}") from exc
    return validate_config(raw)


def migrate_config_file(path: Path) -> bool:
    """Atomically upgrade a legacy config and remove plaintext API keys.

    Any credential-store failure happens before the config file is touched.
    The replacement is fully serialized and validated before the atomic swap,
    so migration does not leave a plaintext backup behind.
    """
    if not path.exists():
        return False
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    migrated = validate_config(migrate_plaintext_api_keys(validate_config(raw)))
    if migrated == raw:
        return False

    temporary = path.with_suffix(path.suffix + ".tmp")
    serialized = tomli_w.dumps(migrated)
    validate_config(tomllib.loads(serialized))
    temporary.write_text(serialized, encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    return True
