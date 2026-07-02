from pathlib import Path

from skills._vault import (
    resolve_vault as _resolve_vault,
    walk_notes as _walk_notes,
    read_note as _read_note,
    parse_frontmatter as _parse_frontmatter,
    extract_wikilinks as _extract_wikilinks,
    note_basename_matches as _note_basename_matches,
)

SKILL = {
    "name": "obsidian_search",
    "description": "在 Obsidian vault 中全文/标签/反向链接搜索，返回匹配的笔记列表",
    "version": "1.2.0",
    "author": "archer-builtin",
}

__meta__ = {
    "name": "obsidian_search",
    "description": "在 Obsidian vault 搜索笔记（全文/标签/反向链接/路径）",
    "keywords": ["找笔记", "obsidian", "知识库", "vault", "搜索笔记", "反向链接", "backlinks", "标签搜索"],
    "risk": "low",
    "auto_trigger": True,
}

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "obsidian_search",
            "description": (
                "在 Obsidian vault 中搜索笔记。支持四种模式："
                "1) 全文搜索（keyword）；"
                "2) 按标签过滤（tag，可与 keyword 组合）；"
                "3) 反向链接（backlinks_to，查哪些笔记链接了某篇笔记）；"
                "4) 按路径前缀过滤（path_prefix，限定在某个子目录下）。"
                "keyword 与 backlinks_to 至少填一个。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "全文搜索关键词（可选，与 backlinks_to 至少填一个）",
                    },
                    "tag": {
                        "type": "string",
                        "description": "按 frontmatter tags 或正文中的 #tag 过滤（可选）",
                    },
                    "backlinks_to": {
                        "type": "string",
                        "description": "反向链接目标笔记名（不含 .md），返回所有 [[链接]] 到它的笔记",
                    },
                    "path_prefix": {
                        "type": "string",
                        "description": "只在该路径前缀下搜索（相对 vault 根目录，如 20个人系统🚀/）",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最多返回条数，默认 20，上限 100",
                    },
                },
                "required": [],
            },
        },
    }

def run(args: dict) -> str:
    keyword = (args.get("keyword") or "").strip()
    tag = (args.get("tag") or "").strip()
    backlinks_to = (args.get("backlinks_to") or "").strip()
    path_prefix = (args.get("path_prefix") or "").strip()
    try:
        max_results = int(args.get("max_results", 20))
    except (TypeError, ValueError):
        max_results = 20
    max_results = max(1, min(max_results, 100))

    if not keyword and not backlinks_to and not tag:
        return "错误：keyword / tag / backlinks_to 至少填一个"

    vault = _resolve_vault()
    if vault is None:
        return "搜索失败：Obsidian vault 未配置（请在 archer.toml 设置 [obsidian].vault_path）"
    if not vault.exists():
        return f"搜索失败：vault 不存在：{vault}"

    try:
        matches: list[tuple[Path, list[str]]] = []
        needle = keyword.lower() if keyword else ""
        tag_lower = tag.lower() if tag else ""
        backlinks_target = backlinks_to.strip() if backlinks_to else ""

        for path in _walk_notes(vault):
            rel = path.relative_to(vault).as_posix()

            if path_prefix and not rel.startswith(path_prefix):
                continue

            try:
                content = _read_note(path)
            except Exception:
                continue

            props, body = _parse_frontmatter(content)

            if tag_lower:
                if not _has_tag(body, props, tag_lower):
                    continue

            if backlinks_target:
                links = _extract_wikilinks(content)
                if not any(_link_matches(link, backlinks_target) for link in links):
                    continue

            if needle:
                if needle not in content.lower():
                    continue

            # 收集匹配行（仅全文搜索时展示）
            match_lines = []
            if needle:
                for line in content.splitlines():
                    if needle in line.lower():
                        match_lines.append(line.strip()[:120])
                        if len(match_lines) >= 3:
                            break

            matches.append((path, match_lines))
            if len(matches) >= max_results + 1:
                break

        if not matches:
            parts = []
            if keyword:
                parts.append(f"关键词「{keyword}」")
            if tag:
                parts.append(f"标签「{tag}」")
            if backlinks_to:
                parts.append(f"反向链接到「{backlinks_to}」")
            return f"未找到匹配的笔记（{' + '.join(parts)}）。"

        desc_parts = []
        if keyword:
            desc_parts.append(f"关键词「{keyword}」")
        if tag:
            desc_parts.append(f"标签「{tag}」")
        if backlinks_to:
            desc_parts.append(f"反向链接到「{backlinks_to}」")
        desc = " + ".join(desc_parts)

        lines = [f"找到 {len(matches)} 篇笔记匹配（{desc}）：\n"]
        for f, ml in matches[:max_results]:
            rel = f.relative_to(vault)
            props, _ = _parse_frontmatter(_read_note(f))
            title = props.get("title") or f.stem
            lines.append(f"  - {rel}")
            if title and title != f.stem:
                lines.append(f"    title: {title}")
            if ml:
                for m in ml:
                    lines.append(f"    | {m}")

        if len(matches) > max_results:
            lines.append(f"\n…还有 {len(matches) - max_results} 条未显示")

        return "\n".join(lines)
    except Exception as e:
        return f"搜索失败：{e}"


def _has_tag(body: str, props: dict, tag_lower: str) -> bool:
    """检查笔记是否包含指定标签（frontmatter tags 或正文中的 #tag）。"""
    # frontmatter tags
    tags = props.get("tags")
    if tags:
        if isinstance(tags, list):
            if any(t.lower() == tag_lower for t in tags):
                return True
        elif isinstance(tags, str):
            if tags.lower() == tag_lower:
                return True

    # 正文 #tag
    import re
    pattern = re.compile(r"#" + re.escape(tag_lower) + r"(?=[\s\.,，。、！？\)\]\n]|$)", re.IGNORECASE)
    if pattern.search(body):
        return True

    return False


def _link_matches(link_target: str, query: str) -> bool:
    """判断 wikilink 目标是否匹配查询。支持 basename 和完整路径匹配。"""
    link_target = link_target.strip()
    if not link_target:
        return False
    # 去掉 heading/block 锚点
    base = link_target.split("#")[0].strip()
    if not base:
        return False
    query_base = query.split("#")[0].strip()
    # 完全匹配（带或不带 .md）
    if base == query_base or base == query_base + ".md":
        return True
    # basename 匹配
    from pathlib import Path
    if Path(base).stem == Path(query_base).stem:
        return True
    return False
