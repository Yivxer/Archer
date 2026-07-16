from __future__ import annotations

import pytest

from core.config_contract import (
    CURRENT_CONFIG_VERSION,
    ConfigValidationError,
    migrate_config_file,
    validate_config,
)
from core.secret_store import SecretStoreError, migrate_plaintext_api_keys, resolve_profile_api_key
from terminal.api._config import _mask_key


def test_legacy_config_is_upgraded_in_memory():
    cfg = validate_config({"api": {"active_profile": "lite"}})
    assert cfg["config_version"] == CURRENT_CONFIG_VERSION


def test_future_config_version_is_rejected():
    with pytest.raises(ConfigValidationError, match="newer than supported"):
        validate_config({"config_version": CURRENT_CONFIG_VERSION + 1})


def test_invalid_section_and_profile_are_rejected():
    with pytest.raises(ConfigValidationError, match=r"\[api\]"):
        validate_config({"api": "not-a-table"})
    with pytest.raises(ConfigValidationError, match="unknown model profile"):
        validate_config({"model_profiles": {"ultra": {}}})
    with pytest.raises(ConfigValidationError, match="unknown top-level"):
        validate_config({"surprise": {}})


def test_enabled_mcp_server_requires_explicit_tool_permissions():
    with pytest.raises(ConfigValidationError, match="permissions is required"):
        validate_config({
            "mcp": {
                "enabled": True,
                "servers": [{"name": "fetch", "enabled": True, "command": "uvx"}],
            }
        })


def test_mcp_tool_permission_levels_are_validated():
    with pytest.raises(ConfigValidationError, match="invalid level"):
        validate_config({
            "mcp": {
                "enabled": True,
                "servers": [{
                    "name": "fetch",
                    "enabled": True,
                    "command": "uvx",
                    "permissions": {"tools": {"fetch_url": "admin"}},
                }],
            }
        })


def test_mcp_explicit_read_write_permissions_are_accepted():
    cfg = validate_config({
        "mcp": {
            "enabled": True,
            "servers": [{
                "name": "fetch",
                "enabled": True,
                "command": "uvx",
                "permissions": {
                    "tools": {"fetch_url": "read", "publish": "write"},
                    "allowed_domains": ["example.com"],
                },
            }],
        }
    })
    assert cfg["mcp"]["servers"][0]["enabled"] is True


def test_remote_mcp_endpoint_must_match_domain_allowlist():
    with pytest.raises(ConfigValidationError, match="match permissions.allowed_domains"):
        validate_config({
            "mcp": {
                "enabled": True,
                "servers": [{
                    "name": "remote",
                    "enabled": True,
                    "transport": "streamable_http",
                    "url": "https://evil.example/mcp",
                    "permissions": {
                        "tools": {"search": "read"},
                        "allowed_domains": ["mcp.example.com"],
                    },
                }],
            }
        })


def test_environment_secret_has_priority(monkeypatch):
    monkeypatch.setenv("ARCHER_PRO_API_KEY", "env-secret")
    monkeypatch.setattr("core.secret_store.read_system_credential", lambda _profile: "keychain-secret")
    assert resolve_profile_api_key("pro", {"api_key_ref": "keychain:pro"}) == "env-secret"


def test_cross_profile_credential_reference_is_rejected():
    with pytest.raises(SecretStoreError, match="invalid credential reference"):
        resolve_profile_api_key("pro", {"api_key_ref": "keychain:lite"})


def test_api_key_status_never_echoes_key_fragments():
    assert _mask_key("sk-sensitive-ending1234") == "••••"


def test_plaintext_is_removed_only_after_secure_write(monkeypatch):
    cfg = {
        "api": {"active_profile": "pro", "api_key": "legacy-secret"},
        "model_profiles": {"pro": {"api_key": "profile-secret"}},
    }
    stored = []
    monkeypatch.setattr(
        "core.secret_store.write_system_credential",
        lambda profile, value: stored.append((profile, value)) or f"keychain:{profile}",
    )
    migrated = migrate_plaintext_api_keys(cfg)
    assert stored == [("pro", "profile-secret")]
    assert "api_key" not in migrated["api"]
    assert "api_key" not in migrated["model_profiles"]["pro"]
    assert migrated["model_profiles"]["pro"]["api_key_ref"] == "keychain:pro"
    assert cfg["api"]["api_key"] == "legacy-secret"


def test_failed_secure_write_keeps_original_plaintext(monkeypatch):
    cfg = {"api": {"active_profile": "lite", "api_key": "legacy-secret"}}
    monkeypatch.setattr(
        "core.secret_store.write_system_credential",
        lambda *_args: (_ for _ in ()).throw(SecretStoreError("unavailable")),
    )
    with pytest.raises(SecretStoreError, match="unavailable"):
        migrate_plaintext_api_keys(cfg)
    assert cfg["api"]["api_key"] == "legacy-secret"


def test_config_file_migration_is_atomic_without_plaintext_backup(tmp_path, monkeypatch):
    path = tmp_path / "archer.toml"
    original = '[api]\nactive_profile = "lite"\napi_key = "legacy-secret"\n'
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        "core.secret_store.write_system_credential",
        lambda profile, _value: f"keychain:{profile}",
    )

    assert migrate_config_file(path) is True
    written = path.read_text(encoding="utf-8")
    assert f"config_version = {CURRENT_CONFIG_VERSION}" in written
    assert 'api_key_ref = "keychain:lite"' in written
    assert "legacy-secret" not in written
    assert not path.with_suffix(".toml.pre-v1.bak").exists()
