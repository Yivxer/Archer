"""Versioned validation contract for ``archer.toml``."""
from __future__ import annotations

import os
import tomllib
from copy import deepcopy
from pathlib import Path

import tomli_w

from core.secret_store import migrate_plaintext_api_keys

CURRENT_CONFIG_VERSION = 2
KNOWN_TOP_LEVEL_FIELDS = frozenset({
    "config_version", "api", "model_profiles", "persona", "memory", "paths",
    "context", "ui", "obsidian", "critique", "security", "mcp",
    "runtime", "experts",
})


class ConfigValidationError(ValueError):
    """Raised when a configuration cannot be safely interpreted."""


PERSONA_PATH_FIELDS = frozenset({
    "soul_path", "memory_path", "covenant_path", "presence_path",
    "soul_profile_path",
})


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


def _validate_runtime_config(runtime: dict) -> None:
    modes = runtime.get("migration_modes", {})
    if not isinstance(modes, dict):
        raise ConfigValidationError("runtime.migration_modes must be a TOML table")
    from core.authority_migration import REGISTERED_AUTHORITY_DOMAINS

    unknown = sorted(set(modes) - REGISTERED_AUTHORITY_DOMAINS)
    if unknown:
        raise ConfigValidationError(
            f"unknown runtime migration domain(s): {', '.join(unknown)}"
        )
    invalid = sorted(
        domain for domain, mode in modes.items()
        if mode not in {"shadow", "authoritative"}
    )
    if invalid:
        raise ConfigValidationError(
            f"invalid runtime migration mode for: {', '.join(invalid)}"
        )
    command_modes = runtime.get("command_migration_modes", {})
    if not isinstance(command_modes, dict):
        raise ConfigValidationError(
            "runtime.command_migration_modes must be a TOML table"
        )
    unknown_command_domains = sorted(
        set(command_modes) - {"background_job"}
    )
    if unknown_command_domains:
        raise ConfigValidationError(
            "unknown command migration domain(s): "
            f"{', '.join(unknown_command_domains)}"
        )
    from core.job_execution_adapter import JobCommand

    background_job = command_modes.get("background_job", {})
    if not isinstance(background_job, dict):
        raise ConfigValidationError(
            "runtime.command_migration_modes.background_job must be a TOML table"
        )
    known_commands = {command.value for command in JobCommand}
    for job_kind, scoped_modes in background_job.items():
        if not str(job_kind).strip() or not isinstance(scoped_modes, dict):
            raise ConfigValidationError(
                "command migration Job kind must be a non-empty TOML table"
            )
        unknown_commands = sorted(set(scoped_modes) - known_commands)
        if unknown_commands:
            raise ConfigValidationError(
                f"unknown Job command(s) for {job_kind}: "
                f"{', '.join(unknown_commands)}"
            )
        invalid_commands = sorted(
            command for command, mode in scoped_modes.items()
            if mode not in {"shadow", "authoritative"}
        )
        if invalid_commands:
            raise ConfigValidationError(
                f"invalid Job command migration mode for {job_kind}: "
                f"{', '.join(invalid_commands)}"
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

    for section in (
        "api", "model_profiles", "memory", "paths", "persona", "security",
        "mcp", "runtime",
    ):
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

    persona = cfg.get("persona", {})
    if isinstance(persona, dict):
        for field in PERSONA_PATH_FIELDS:
            value = persona.get(field)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ConfigValidationError(f"persona.{field} must be a non-empty path")

    mcp = cfg.get("mcp", {})
    if isinstance(mcp, dict):
        _validate_mcp_config(mcp)

    runtime = cfg.get("runtime", {})
    if isinstance(runtime, dict):
        _validate_runtime_config(runtime)

    experts = cfg.get("experts")
    if experts is not None:
        from core.agent_profile import validate_experts_table

        validate_experts_table(experts)

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
