"""Obsidian vault 公共配置读取与路径解析。

三个 obsidian_* 技能共用此模块，避免拷贝粘贴导致的「改一处漏两处」。
配置缺失时返回 None 而非抛 KeyError，调用方可做优雅降级。
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Iterator, Optional

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]|\n]+)(?:\|[^\]]*)?\]\]")

_SKIP_DIRS = {".git", ".obsidian", "node_modules", "__pycache__", ".trash", ".DS_Store"}


def _config_path() -> Path:
    return Path(__file__).parent.parent / "archer.toml"


def read_vault_path() -> Optional[Path]:
    """读取 archer.toml 的 [obsidian].vault_path。

    配置缺失、文件不存在、或字段为空时返回 None，绝不抛 KeyError。
    """
    cfg_path = _config_path()
    if not cfg_path.is_file():
        return None
    try:
        with open(cfg_path, "rb") as f:
            cfg = tomllib.load(f)
    except Exception:
        return None
    raw = (cfg.get("obsidian") or {}).get("vault_path", "")
    if not raw or not str(raw).strip():
        return None
    return Path(str(raw).strip()).expanduser()


def resolve_vault() -> Optional[Path]:
    """返回已 resolve 的 vault 路径，不存在或配置缺失返回 None。"""
    p = read_vault_path()
    if p is None:
        return None
    try:
        return p.resolve()
    except Exception:
        return None


def resolve_note_path(raw_path: str) -> Path:
    """把用户传入的路径解析为 vault 内的绝对路径。

    - 相对路径基于 vault 根
    - 必须位于 vault 内（防穿透）
    - 配置缺失时抛 PermissionError，调用方应捕获返回友好提示
    """
    vault = read_vault_path()
    if vault is None:
        raise PermissionError("Obsidian vault 未配置：请在 archer.toml 设置 [obsidian].vault_path")
    vault_resolved = vault.expanduser().resolve()
    if not vault_resolved.exists():
        raise PermissionError(f"Obsidian vault 不存在：{vault_resolved}")

    p = Path(raw_path).expanduser()
    if not p.is_absolute():
        p = vault_resolved / raw_path
    resolved = p.resolve()

    try:
        resolved.relative_to(vault_resolved)
    except ValueError:
        raise PermissionError("路径必须位于 Obsidian vault 内")
    return resolved


def walk_notes(vault: Path) -> Iterator[Path]:
    """遍历 vault 内所有 .md 笔记，跳过系统目录。"""
    for path in vault.rglob("*.md"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        resolved = path.resolve()
        try:
            resolved.relative_to(vault)
        except ValueError:
            continue
        yield resolved


def read_note(path: Path) -> str:
    """安全读取笔记内容，编码容错。"""
    return path.read_text(encoding="utf-8", errors="replace")


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """解析 YAML frontmatter，返回 (properties_dict, body_text)。

    解析失败时 properties 返回空 dict，body 为原文。
    仅做简单的 key: value 行解析，不依赖 PyYAML。
    """
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}, content

    fm_text = m.group(1)
    body = content[m.end():]
    props: dict = {}
    current_key: Optional[str] = None
    list_items: list[str] = []

    def flush_list():
        nonlocal current_key, list_items
        if current_key is not None and list_items:
            props[current_key] = list_items
            current_key = None
            list_items = []

    for line in fm_text.splitlines():
        stripped = line.rstrip()
        if not stripped or stripped.startswith("#"):
            continue
        # list item: "  - value" or "    - value"
        m_item = re.match(r"^\s+-\s*(.*)$", line)
        if m_item and current_key is not None:
            list_items.append(m_item.group(1).strip())
            continue
        # key: value
        m_kv = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$", stripped)
        if m_kv:
            flush_list()
            key = m_kv.group(1).strip()
            val = m_kv.group(2).strip()
            if val == "":
                current_key = key
                list_items = []
            else:
                # 去掉字符串引号
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                props[key] = val
    flush_list()
    return props, body


def extract_wikilinks(content: str) -> list[str]:
    """提取正文中所有 [[wikilink]] 目标名（不含 display text）。"""
    return [m.split("|")[0].strip() for m in _WIKILINK_RE.findall(content)]


def note_basename_matches(path: Path, target: str) -> bool:
    """判断笔记路径的 basename 是否匹配 wikilink 目标。"""
    return path.stem == target or path.name == target


def safe_edit_note(path: Path, old_string: str, new_string: str, *, backup_threshold: int = 30) -> tuple[bool, str]:
    """安全编辑笔记：替换 old_string 为 new_string。

    硬规则：
    - old_string 在文件中匹配不到时，拒绝编辑并返回 False
    - 文件行数超过 backup_threshold 时，先自动备份到 .archer-backups/
    - 返回 (success: bool, message: str)

    用于防止"客户端构建日志.md 被覆盖丢失 180 行"这类问题。
    """
    try:
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        line_count = len(lines)

        if old_string not in content:
            return False, f"编辑失败：未在「{path.name}」中找到要替换的内容（{line_count} 行）"

        if line_count > backup_threshold:
            backup_dir = path.parent / ".archer-backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            from datetime import datetime
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            backup_path = backup_dir / f"{path.stem}.{stamp}.bak{path.suffix or '.md'}"
            backup_path.write_text(content, encoding="utf-8")
            content = content.replace(old_string, new_string)
            path.write_text(content, encoding="utf-8")
            new_line_count = len(content.splitlines())
            return True, f"已编辑：{path.name}（{line_count} → {new_line_count} 行），已备份到 {backup_path}"

        content = content.replace(old_string, new_string)
        path.write_text(content, encoding="utf-8")
        new_line_count = len(content.splitlines())
        return True, f"已编辑：{path.name}（{line_count} → {new_line_count} 行）"

    except Exception as e:
        return False, f"编辑失败：{e}"

