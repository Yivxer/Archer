"""P5.7 — Layered markdown config loading and merge helpers."""
from __future__ import annotations

import os
import re
from pathlib import Path


def local_override_path(base_path: Path) -> Path:
    return base_path.with_name(f"{base_path.stem}.local{base_path.suffix}")


def merge_layered_markdown(base: str, override: str, *, label: str = "local") -> str:
    """Append override after base; empty parts are ignored."""
    base_text = (base or "").strip()
    override_text = (override or "").strip()
    if not override_text:
        return base_text
    if not base_text:
        return override_text
    return f"{base_text}\n\n---\n\n[{label} override]\n\n{override_text}"


def read_text_file(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def load_layered_file(path_str: str) -> str:
    """Load a markdown file plus sibling ``*.local.md`` override if present."""
    if not path_str:
        return ""
    base_path = Path(path_str).expanduser()
    base_text = read_text_file(base_path)
    local_text = read_text_file(local_override_path(base_path))
    return merge_layered_markdown(base_text, local_text, label="local")


def resolve_project_root(cfg: dict | None = None) -> Path:
    env_root = os.environ.get("ARCHER_PROJECT_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    if cfg:
        configured = str((cfg.get("persona") or {}).get("project_root", "")).strip()
        if configured:
            return Path(configured).expanduser().resolve()

    return Path.cwd().resolve()


def load_project_archer_layers(project_root: Path | None = None, *, cfg: dict | None = None) -> str:
    """Load ``ARCHER.md`` then ``ARCHER.local.md`` from the project root."""
    root = project_root or resolve_project_root(cfg)
    base_text = read_text_file(root / "ARCHER.md")
    local_text = read_text_file(root / "ARCHER.local.md")
    return merge_layered_markdown(base_text, local_text, label="ARCHER.local")


_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def extract_markdown_section(text: str, heading: str) -> str:
    """Return body of the first ``## heading`` section (case-insensitive)."""
    if not text or not heading:
        return ""

    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        return ""

    target = heading.strip().lower()
    for index, match in enumerate(matches):
        title = match.group(1).strip().lower()
        if title != target:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        return text[start:end].strip()
    return ""


def load_project_persona_layers(*, cfg: dict | None = None, project_root: Path | None = None) -> str:
    """Persona-specific slice from layered project ARCHER files."""
    archer_text = load_project_archer_layers(project_root=project_root, cfg=cfg)
    section = extract_markdown_section(archer_text, "Persona")
    if section:
        return section
    if archer_text and not _SECTION_RE.search(archer_text):
        return archer_text
    return ""
