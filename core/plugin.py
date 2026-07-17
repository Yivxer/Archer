"""P5.12 — Archer plugin install/list/remove."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_PLUGIN_ZIP_BYTES = 20_000_000

from core.hooks import HOOK_EVENTS, HookDefinition
from core.paths import ROOT

PLUGIN_MANIFEST = "plugin.json"
PLUGIN_DIR_NAME = ".archer-plugin"
INSTALLED_REGISTRY = "installed.json"
PLUGIN_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$", re.I)
PLUGIN_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,63}$")
PLUGIN_RISKS = frozenset({"low", "medium", "high", "critical"})
JSON_SCHEMA_TYPES = frozenset({"object", "array", "string", "number", "integer", "boolean", "null"})


def plugins_dir(default: Path | None = None) -> Path:
    base = default or (ROOT / "plugins")
    base.mkdir(parents=True, exist_ok=True)
    return base


def _registry_path(base: Path | None = None) -> Path:
    return plugins_dir(base) / INSTALLED_REGISTRY


def _load_registry(base: Path | None = None) -> dict[str, Any]:
    path = _registry_path(base)
    if not path.is_file():
        return {"plugins": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"plugins": {}}
    if not isinstance(raw, dict):
        return {"plugins": {}}
    plugins = raw.get("plugins")
    if not isinstance(plugins, dict):
        raw["plugins"] = {}
    return raw


def _save_registry(data: dict[str, Any], base: Path | None = None) -> None:
    path = _registry_path(base)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(raw_tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _is_plugin_url(source: str) -> bool:
    lowered = source.strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def _safe_extract_zip(zip_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    dest_root = dest.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target = (dest / member.filename).resolve()
            if not str(target).startswith(str(dest_root)):
                raise ValueError(f"zip 路径越界：{member.filename}")
        archive.extractall(dest)


def _download_url(url: str, dest: Path, *, max_bytes: int = MAX_PLUGIN_ZIP_BYTES) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Archer-Plugin/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        total = 0
        chunks: list[bytes] = []
        while True:
            block = response.read(65536)
            if not block:
                break
            total += len(block)
            if total > max_bytes:
                raise ValueError(f"下载过大（>{max_bytes} bytes）")
            chunks.append(block)
    dest.write_bytes(b"".join(chunks))


def materialize_plugin_source(source: str | Path) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    """Resolve local dir, .zip file, or http(s) .zip URL to an extract/install root."""
    raw = str(source).strip()
    if _is_plugin_url(raw):
        if ".zip" not in raw.split("?")[0].lower():
            raise ValueError("URL 安装目前仅支持 .zip 插件包")
        tmp = tempfile.TemporaryDirectory(prefix="archer-plugin-")
        zip_path = Path(tmp.name) / "bundle.zip"
        _download_url(raw, zip_path)
        extract_dir = Path(tmp.name) / "extract"
        _safe_extract_zip(zip_path, extract_dir)
        return extract_dir, tmp

    path = Path(raw).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"路径不存在：{source}")
    if path.is_file() and path.suffix.lower() == ".zip":
        if path.stat().st_size > MAX_PLUGIN_ZIP_BYTES:
            raise ValueError(f"zip 过大（>{MAX_PLUGIN_ZIP_BYTES} bytes）")
        tmp = tempfile.TemporaryDirectory(prefix="archer-plugin-")
        extract_dir = Path(tmp.name) / "extract"
        _safe_extract_zip(path, extract_dir)
        return extract_dir, tmp
    if path.is_file():
        raise ValueError("plugin install 需要目录或 .zip 包，不是单个文件")
    return path, None


def resolve_plugin_root(source: str | Path) -> Path:
    path = Path(source).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"路径不存在：{source}")
    if path.is_file():
        raise ValueError("plugin install 需要目录路径，不是单个文件")
    direct = path / PLUGIN_MANIFEST
    if direct.is_file():
        return path
    nested = path / PLUGIN_DIR_NAME / PLUGIN_MANIFEST
    if nested.is_file():
        return path / PLUGIN_DIR_NAME
    raise ValueError(f"未找到 {PLUGIN_MANIFEST}（根目录或 {PLUGIN_DIR_NAME}/ 下）")


def load_manifest(plugin_root: Path) -> dict[str, Any]:
    manifest_path = plugin_root / PLUGIN_MANIFEST
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"plugin.json 无法解析：{exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("plugin.json 必须是 JSON object")
    return raw


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    name = str(manifest.get("name", "")).strip()
    version = str(manifest.get("version", "")).strip()
    if not name or not PLUGIN_NAME_RE.fullmatch(name):
        raise ValueError("plugin.json 缺少合法 name（字母数字_-）")
    if not PLUGIN_VERSION_RE.fullmatch(version):
        raise ValueError("plugin.json version 必须是 semver")
    risk = manifest.get("risk")
    if not isinstance(risk, str) or risk not in PLUGIN_RISKS:
        raise ValueError("plugin.json risk 必须是 low/medium/high/critical")
    auto_trigger = manifest.get("auto_trigger")
    if not isinstance(auto_trigger, bool):
        raise ValueError("plugin.json auto_trigger 必须是 boolean")
    permissions = manifest.get("permissions")
    if not isinstance(permissions, list) or any(
        not isinstance(item, str) or not item.strip() for item in permissions
    ):
        raise ValueError("plugin.json permissions 必须是非空字符串数组（可为空数组）")
    inputs = _validate_io_schema("inputs", manifest.get("inputs"))
    outputs = _validate_io_schema("outputs", manifest.get("outputs"))
    description = str(manifest.get("description", "")).strip()
    skills = manifest.get("skills")
    modes = manifest.get("modes")
    hooks = manifest.get("hooks")
    if skills is not None and not isinstance(skills, list):
        raise ValueError("skills 必须是路径数组")
    if modes is not None and not isinstance(modes, list):
        raise ValueError("modes 必须是路径数组")
    if hooks is not None and not isinstance(hooks, dict):
        raise ValueError("hooks 必须是 object")
    return {
        "name": name,
        "version": version,
        "description": description,
        "risk": risk,
        "auto_trigger": auto_trigger,
        "permissions": list(dict.fromkeys(item.strip() for item in permissions)),
        "inputs": inputs,
        "outputs": outputs,
        "skills": [str(s) for s in skills] if skills else None,
        "modes": [str(m) for m in modes] if modes else None,
        "hooks": hooks if isinstance(hooks, dict) else None,
    }


def _validate_io_schema(field: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"plugin.json {field} 必须是 JSON schema object")
    schema_type = value.get("type")
    if not isinstance(schema_type, str) or schema_type not in JSON_SCHEMA_TYPES:
        raise ValueError(f"plugin.json {field}.type 非法")
    return dict(value)


def _discover_skill_files(plugin_root: Path, manifest: dict[str, Any]) -> list[Path]:
    if manifest.get("skills"):
        files = []
        for rel in manifest["skills"]:
            path = (plugin_root / rel).resolve()
            if not str(path).startswith(str(plugin_root.resolve())):
                raise ValueError(f"skill 路径越界：{rel}")
            if path.suffix != ".py" or not path.is_file():
                raise ValueError(f"skill 文件不存在：{rel}")
            files.append(path)
        return files
    skills_dir = plugin_root / "skills"
    if not skills_dir.is_dir():
        return []
    return sorted(
        p for p in skills_dir.glob("*.py")
        if p.is_file() and not p.name.startswith("_")
    )


def _discover_mode_files(plugin_root: Path, manifest: dict[str, Any]) -> list[Path]:
    if manifest.get("modes"):
        files = []
        for rel in manifest["modes"]:
            path = (plugin_root / rel).resolve()
            if not str(path).startswith(str(plugin_root.resolve())):
                raise ValueError(f"mode 路径越界：{rel}")
            if path.suffix != ".md" or not path.is_file():
                raise ValueError(f"mode 文件不存在：{rel}")
            files.append(path)
        return files
    modes_dir = plugin_root / "modes"
    if not modes_dir.is_dir():
        return []
    return sorted(modes_dir.glob("*.md"))


def _skill_name_from_file(path: Path) -> str:
    from skills.installer import _validate

    return _validate(path)


def _builtin_skill_names() -> set[str]:
    from skills.loader import SKILLS_DIR

    return {
        p.stem for p in SKILLS_DIR.glob("*.py")
        if p.is_file() and not p.name.startswith("_")
    }


def _installed_plugin_skill_names(base: Path, exclude: str | None = None) -> set[str]:
    names: set[str] = set()
    for entry in list_installed(base):
        if exclude and entry["name"] == exclude:
            continue
        root = Path(entry["path"])
        manifest = load_manifest(root)
        for path in _discover_skill_files(root, manifest):
            try:
                names.add(_skill_name_from_file(path))
            except Exception:
                names.add(path.stem)
    return names


def detect_conflicts(
    manifest: dict[str, Any],
    plugin_root: Path,
    *,
    base: Path | None = None,
    replacing: str | None = None,
) -> list[str]:
    issues: list[str] = []
    name = manifest["name"]
    registry = _load_registry(base).get("plugins", {})
    if name in registry and replacing != name:
        issues.append(f"插件已安装：{name}")

    skill_names: list[str] = []
    for path in _discover_skill_files(plugin_root, manifest):
        try:
            skill_names.append(_skill_name_from_file(path))
        except Exception as exc:
            issues.append(f"skill 校验失败 {path.name}：{exc}")

    reserved = _builtin_skill_names() | _installed_plugin_skill_names(base, exclude=replacing)
    for skill in skill_names:
        if skill in reserved:
            issues.append(f"skill 名冲突：{skill}")
        if not SKILL_NAME_RE.fullmatch(skill):
            issues.append(f"skill 名非法：{skill}")
    return issues


def install_plugin(source: str | Path, *, force: bool = False, base: Path | None = None) -> dict[str, Any]:
    materialized, tmp = materialize_plugin_source(source)
    try:
        plugin_root = resolve_plugin_root(materialized)
        return _install_plugin_root(plugin_root, force=force, base=base)
    finally:
        if tmp is not None:
            tmp.cleanup()


def _install_plugin_root(
    plugin_root: Path,
    *,
    force: bool,
    base: Path | None,
) -> dict[str, Any]:
    manifest = validate_manifest(load_manifest(plugin_root))
    name = manifest["name"]
    conflicts = detect_conflicts(
        manifest,
        plugin_root,
        base=base,
        replacing=name if force else None,
    )
    if conflicts:
        raise ValueError("安装冲突：\n- " + "\n- ".join(conflicts))

    root = plugins_dir(base)
    root.mkdir(parents=True, exist_ok=True)
    dest_root = root / name
    if dest_root.exists() and not force:
        raise ValueError(f"插件目录已存在：{name}（使用 force 覆盖）")

    staging_root = Path(tempfile.mkdtemp(prefix=f".{name}.installing-", dir=root))
    backup_root: Path | None = None
    previous_registry = _load_registry(base)
    shutil.rmtree(staging_root)
    try:
        shutil.copytree(plugin_root, staging_root)
        skill_files = _discover_skill_files(staging_root, manifest)
        mode_files = _discover_mode_files(staging_root, manifest)
    except Exception:
        if staging_root.exists():
            shutil.rmtree(staging_root)
        raise
    record = {
        "name": name,
        "version": manifest["version"],
        "description": manifest.get("description", ""),
        "path": str(dest_root),
        "enabled": True,
        "risk": manifest["risk"],
        "auto_trigger": manifest["auto_trigger"],
        "permissions": manifest["permissions"],
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "skill_count": len(skill_files),
        "mode_count": len(mode_files),
    }
    registry = json.loads(json.dumps(previous_registry))
    registry.setdefault("plugins", {})[name] = record
    try:
        if dest_root.exists():
            backup_root = root / f".{name}.backup"
            if backup_root.exists():
                shutil.rmtree(backup_root)
            dest_root.replace(backup_root)
        staging_root.replace(dest_root)
        _save_registry(registry, base)
    except Exception:
        if dest_root.exists():
            shutil.rmtree(dest_root)
        if backup_root is not None and backup_root.exists():
            backup_root.replace(dest_root)
        if staging_root.exists():
            shutil.rmtree(staging_root)
        raise
    finally:
        if backup_root is not None and backup_root.exists():
            shutil.rmtree(backup_root)

    from skills.loader import reset_skill_registry

    reset_skill_registry()
    return record


def list_installed(base: Path | None = None) -> list[dict[str, Any]]:
    registry = _load_registry(base).get("plugins", {})
    items = list(registry.values()) if isinstance(registry, dict) else []
    return sorted(items, key=lambda item: str(item.get("name", "")))


def remove_plugin(name: str, *, base: Path | None = None) -> None:
    if not PLUGIN_NAME_RE.fullmatch(name):
        raise ValueError("插件名非法")
    registry = _load_registry(base)
    plugins = registry.get("plugins", {})
    if name not in plugins:
        raise FileNotFoundError(f"插件未安装：{name}")
    dest = Path(plugins[name].get("path", plugins_dir(base) / name))
    backup = dest.parent / f".{name}.removing"
    if backup.exists():
        shutil.rmtree(backup)
    if dest.exists():
        dest.replace(backup)
    del plugins[name]
    try:
        _save_registry(registry, base)
    except Exception:
        if backup.exists():
            backup.replace(dest)
        raise
    if backup.exists():
        shutil.rmtree(backup)
    from skills.loader import reset_skill_registry

    reset_skill_registry()


def set_plugin_enabled(name: str, enabled: bool, *, base: Path | None = None) -> dict[str, Any]:
    if not PLUGIN_NAME_RE.fullmatch(name):
        raise ValueError("插件名非法")
    registry = _load_registry(base)
    plugins = registry.get("plugins", {})
    if name not in plugins:
        raise FileNotFoundError(f"插件未安装：{name}")
    record = dict(plugins[name])
    record["enabled"] = bool(enabled)
    plugins[name] = record
    _save_registry(registry, base)
    from skills.loader import reset_skill_registry

    reset_skill_registry()
    return record


def _enabled_plugins(base: Path | None = None) -> list[dict[str, Any]]:
    return [entry for entry in list_installed(base) if entry.get("enabled", True) is True]


def iter_installed_skill_paths(base: Path | None = None) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for entry in _enabled_plugins(base):
        root = Path(entry["path"])
        if not root.is_dir():
            continue
        try:
            manifest = validate_manifest(load_manifest(root))
        except Exception:
            continue
        for path in _discover_skill_files(root, manifest):
            try:
                name = _skill_name_from_file(path)
            except Exception:
                name = path.stem
            out[name] = path
    return out


def find_plugin_mode_file(mode_name: str, base: Path | None = None) -> Path | None:
    for entry in _enabled_plugins(base):
        root = Path(entry["path"])
        candidate = root / "modes" / f"{mode_name}.md"
        if candidate.is_file():
            return candidate
        try:
            manifest = load_manifest(root)
            for path in _discover_mode_files(root, manifest):
                if path.stem == mode_name:
                    return path
        except Exception:
            continue
    return None


def iter_plugin_mode_names(base: Path | None = None) -> set[str]:
    names: set[str] = set()
    for entry in _enabled_plugins(base):
        root = Path(entry["path"])
        try:
            manifest = load_manifest(root)
            for path in _discover_mode_files(root, manifest):
                names.add(path.stem)
        except Exception:
            continue
    return names


def load_plugin_hook_definitions(base: Path | None = None) -> list[HookDefinition]:
    hooks: list[HookDefinition] = []
    for entry in _enabled_plugins(base):
        root = Path(entry["path"])
        raw_hooks: dict[str, Any] | None = None
        manifest = load_manifest(root)
        if isinstance(manifest.get("hooks"), dict):
            raw_hooks = manifest["hooks"]
        hooks_file = root / "hooks.json"
        if hooks_file.is_file():
            try:
                file_hooks = json.loads(hooks_file.read_text(encoding="utf-8"))
                if isinstance(file_hooks, dict):
                    merged = dict(raw_hooks or {})
                    for event, entries in file_hooks.items():
                        if not isinstance(entries, list):
                            continue
                        merged.setdefault(event, [])
                        if isinstance(merged[event], list):
                            merged[event] = list(merged[event]) + entries
                        else:
                            merged[event] = entries
                    raw_hooks = merged
            except Exception:
                pass
        if not raw_hooks:
            continue
        for event in HOOK_EVENTS:
            entries = raw_hooks.get(event) or []
            if not isinstance(entries, list):
                continue
            for item in entries:
                if not isinstance(item, dict):
                    continue
                hook_type = str(item.get("type", "")).strip().lower()
                if hook_type not in {"command", "python", "prompt"}:
                    continue
                hooks.append(
                    HookDefinition(
                        event=event,
                        hook_type=hook_type,
                        handler=str(item.get("handler", "")).strip(),
                        command=str(item.get("command", "")).strip(),
                        prompt=str(item.get("prompt", "")).strip(),
                        matcher=str(item.get("matcher", "")).strip(),
                        enabled=item.get("enabled", True) is not False,
                        fail_closed=item.get("fail_closed", False) is True,
                    )
                )
    return hooks
