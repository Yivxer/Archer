"""Skill loader with deferred (lazy) full-module loading."""
from __future__ import annotations

import ast
import importlib.util
import os
from collections import OrderedDict
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from skills.meta import SkillMeta, parse_skill_meta

SKILLS_DIR = Path(__file__).parent
DEFAULT_SKILL_CACHE_SIZE = 10


def _cache_maxsize() -> int:
    raw = os.environ.get("ARCHER_SKILL_CACHE_SIZE", str(DEFAULT_SKILL_CACHE_SIZE)).strip()
    try:
        size = int(raw)
    except ValueError:
        size = DEFAULT_SKILL_CACHE_SIZE
    return max(1, size)


_SKILL_PATHS: dict[str, Path] = {}
_MODULE_CACHE: OrderedDict[str, Any] = OrderedDict()


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ast_literal_to_py(node: ast.AST | None) -> Any:
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id == "True":
            return True
        if node.id == "False":
            return False
    if isinstance(node, ast.List):
        return [_ast_literal_to_py(elt) for elt in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_ast_literal_to_py(elt) for elt in node.elts)
    if isinstance(node, ast.Dict):
        out: dict[Any, Any] = {}
        for key, value in zip(node.keys, node.values):
            parsed_key = _ast_literal_to_py(key)
            if parsed_key is None:
                continue
            out[parsed_key] = _ast_literal_to_py(value)
        return out
    return None


def _skill_file_has_defs(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    fn_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    return "schema" in fn_names and "run" in fn_names


def _meta_from_ast(path: Path) -> SkillMeta | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    skill_dict: dict[str, Any] = {}
    meta_dict: dict[str, Any] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id == "SKILL" and isinstance(node.value, ast.Dict):
                parsed = _ast_literal_to_py(node.value)
                if isinstance(parsed, dict):
                    skill_dict = parsed
            elif target.id == "__meta__" and isinstance(node.value, ast.Dict):
                parsed = _ast_literal_to_py(node.value)
                if isinstance(parsed, dict):
                    meta_dict = parsed

    merged = {**skill_dict, **meta_dict}
    name = str(merged.get("name") or path.stem).strip()
    if not name:
        return None

    fake_mod = type("SkillMetaStub", (), {
        "SKILL": skill_dict,
        "__meta__": meta_dict,
        "__name__": name,
    })()
    return parse_skill_meta(fake_mod)


def register_skill_meta(path: Path) -> SkillMeta | None:
    """Register one skill's metadata without importing the full module."""
    if not path.is_file() or path.name.startswith("_"):
        return None
    if not _skill_file_has_defs(path):
        return None

    meta = _meta_from_ast(path)
    if meta is None:
        try:
            mod = _load_module(path)
            if not (hasattr(mod, "SKILL") and hasattr(mod, "schema") and hasattr(mod, "run")):
                return None
            meta = get_skill_meta(mod)
        except Exception:
            return None
    return meta


class DeferredSkillRegistry(Mapping[str, Any]):
    """Meta-first skill registry; full modules load on first access."""

    def __init__(self, paths: dict[str, Path], metas: dict[str, SkillMeta]):
        self._paths = paths
        self._metas = metas

    def __getitem__(self, name: str) -> Any:
        if name not in self._paths:
            raise KeyError(name)
        return load_skill_full(name)

    def __iter__(self) -> Iterator[str]:
        return iter(self._paths)

    def __len__(self) -> int:
        return len(self._paths)

    def __contains__(self, name: object) -> bool:
        return name in self._paths

    def get(self, name: str, default: Any = None) -> Any:
        if name not in self._paths:
            return default
        return self[name]

    def keys(self):
        return self._paths.keys()

    def metas(self) -> dict[str, SkillMeta]:
        return dict(self._metas)

    def get_meta(self, name: str) -> SkillMeta | None:
        return self._metas.get(name)

    def resolve_subset(self, names: set[str]) -> dict[str, Any]:
        return {name: self[name] for name in names if name in self._paths}


class ChainSkillRegistry(Mapping[str, Any]):
    """Overlay skills (e.g. MCP) on a base map without eager expansion."""

    def __init__(self, primary: Mapping[str, Any], overlay: Mapping[str, Any] | None = None):
        self._primary = primary
        self._overlay = overlay

    def __getitem__(self, name: str) -> Any:
        if self._overlay is not None and name in self._overlay:
            return self._overlay[name]
        return self._primary[name]

    def __iter__(self) -> Iterator[str]:
        keys = set(self._primary)
        if self._overlay is not None:
            keys.update(self._overlay)
        return iter(keys)

    def __len__(self) -> int:
        return len(set(self))

    def __contains__(self, name: object) -> bool:
        if self._overlay is not None and name in self._overlay:
            return True
        return name in self._primary

    def get(self, name: str, default: Any = None) -> Any:
        if name in self:
            return self[name]
        return default


_REGISTRY: DeferredSkillRegistry | None = None


def register_all_skills(*, force: bool = False) -> DeferredSkillRegistry:
    """Scan skills/ and register metadata only (no full imports)."""
    global _REGISTRY, _SKILL_PATHS

    if _REGISTRY is not None and not force:
        return _REGISTRY

    paths: dict[str, Path] = {}
    metas: dict[str, SkillMeta] = {}
    for py_file in sorted(SKILLS_DIR.glob("*.py")):
        meta = register_skill_meta(py_file)
        if meta is None:
            continue
        paths[meta.name] = py_file
        metas[meta.name] = meta

    try:
        from core.plugin import iter_installed_skill_paths

        for name, plugin_path in iter_installed_skill_paths().items():
            if name in paths:
                continue
            meta = register_skill_meta(plugin_path)
            if meta is None:
                continue
            paths[name] = plugin_path
            metas[name] = meta
    except Exception:
        pass

    _SKILL_PATHS = dict(paths)
    _MODULE_CACHE.clear()
    _REGISTRY = DeferredSkillRegistry(paths, metas)
    return _REGISTRY


def _load_skill_full_impl(name: str) -> Any:
    path = _SKILL_PATHS.get(name)
    if path is None:
        raise KeyError(name)
    mod = _load_module(path)
    if not (hasattr(mod, "SKILL") and hasattr(mod, "schema") and hasattr(mod, "run")):
        raise ImportError(f"skill {name} missing SKILL/schema/run")
    skill_name = getattr(mod, "SKILL", {}).get("name", name)
    if skill_name != name:
        raise ImportError(f"skill name mismatch: {skill_name} != {name}")
    return mod


def load_skill_full(name: str) -> Any:
    """Load a full skill module; LRU keeps recently used modules hot."""
    if name in _MODULE_CACHE:
        _MODULE_CACHE.move_to_end(name)
        return _MODULE_CACHE[name]

    mod = _load_skill_full_impl(name)
    _MODULE_CACHE[name] = mod
    _MODULE_CACHE.move_to_end(name)
    maxsize = _cache_maxsize()
    while len(_MODULE_CACHE) > maxsize:
        _MODULE_CACHE.popitem(last=False)
    return mod


def load_skills() -> DeferredSkillRegistry:
    """Return the deferred skill registry (backward-compatible entry point)."""
    return register_all_skills()


def get_skill_meta(mod_or_name: Any, registry: DeferredSkillRegistry | None = None) -> SkillMeta:
    if isinstance(mod_or_name, str):
        reg = registry or register_all_skills()
        meta = reg.get_meta(mod_or_name)
        if meta is not None:
            return meta
        return SkillMeta(name=mod_or_name, description=mod_or_name)

    parsed = parse_skill_meta(mod_or_name)
    if parsed is not None:
        return parsed
    skill = getattr(mod_or_name, "SKILL", {}) or {}
    name = str(skill.get("name", getattr(mod_or_name, "__name__", "unknown")))
    return SkillMeta(name=name, description=str(skill.get("description") or name))


def load_skill_metas(skills: Mapping[str, Any] | None = None) -> dict[str, SkillMeta]:
    if skills is None:
        return register_all_skills().metas()
    if isinstance(skills, DeferredSkillRegistry):
        return skills.metas()
    return {name: get_skill_meta(mod) for name, mod in skills.items()}


def get_tools(skills: Mapping[str, Any]) -> list[dict]:
    """Build OpenAI function-calling tool schemas for the given skill subset."""
    return [skills[name].schema() for name in skills]


def reset_skill_registry() -> None:
    """Testing helper: drop cached registry and module LRU."""
    global _REGISTRY
    _REGISTRY = None
    _SKILL_PATHS.clear()
    _MODULE_CACHE.clear()
