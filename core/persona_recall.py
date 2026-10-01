"""Bounded, read-only recall from authoritative Markdown sources."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_STOP_TERMS = frozenset({
    "我的", "我们", "什么", "怎么", "如何", "应该", "可以", "现在", "之前", "已经",
    "是否", "说明", "哪里", "怎样", "时候", "哪些", "需要", "你给", "给我",
    "我现", "我之", "我希", "我应", "我可", "的吗", "了吗", "希望", "不能",
    "一篇", "篇内", "一件", "件事", "内容", "问题", "判断",
})
_INVENTION = re.compile(r"(?:替我|帮我)?(?:编造|编一个|编一份|虚构)|假设一个|随便编|(?:写|润色|扩写)一篇")


@dataclass(frozen=True)
class PersonaExcerpt:
    source: str
    start: int
    end: int
    heading: str
    text: str


def _terms(text: str) -> frozenset[str]:
    result = set(re.findall(r"[a-z][a-z0-9_]{2,}", text.lower()))
    for word in re.findall(r"[\u4e00-\u9fff]+", text):
        result.update(word[i:i + 2] for i in range(len(word) - 1))
    return frozenset(result - _STOP_TERMS)


def _personal_question(query: str) -> bool:
    return bool(query and not _INVENTION.search(query)
                and re.search(r"我|我们|你应该|你可以|记忆|档案|约定|私人|访谈|个人|习惯|偏好", query)
                and re.search(r"[？?]|什么|怎么|如何|哪些|是否|哪里|怎样|吗", query))


def _sections(text: str, source: str) -> tuple[PersonaExcerpt, ...]:
    lines = text.splitlines()
    result: list[PersonaExcerpt] = []
    headings: list[tuple[int, str]] = []
    start = 0
    heading = ""
    for index, line in enumerate([*lines, "# __end__"]):
        match = re.match(r"^(#{1,6})\s+(.+)", line)
        if not match:
            continue
        body = "\n".join(lines[start:index]).strip()
        if body and not (len(headings) == 1 and all(
            not line.strip() or line.startswith(">") for line in body.splitlines()
        )):
            result.append(PersonaExcerpt(source, start + 1, index, heading, body))
        level = len(match[1])
        headings = [item for item in headings if item[0] < level]
        headings.append((level, match[2]))
        heading = " > ".join(title for _, title in headings)
        start = index + 1
    return tuple(result)


@lru_cache(maxsize=16)
def _read_sections(path: str, modified_ns: int, size: int, source: str) -> tuple[PersonaExcerpt, ...]:
    return _sections(Path(path).read_text(encoding="utf-8"), source)


def _configured_sections(config: dict) -> list[PersonaExcerpt]:
    from core.layered_config import local_override_path

    result: list[PersonaExcerpt] = []
    for field, source in (("soul_path", "soul_md"), ("memory_path", "memory_md")):
        raw = config.get("persona", {}).get(field)
        if not raw:
            continue
        path = Path(raw).expanduser()
        for candidate in (path, local_override_path(path)):
            try:
                stat = candidate.stat()
                if stat.st_size <= 1_000_000:
                    result.extend(_read_sections(str(candidate), stat.st_mtime_ns, stat.st_size, source))
            except (OSError, UnicodeError):
                continue
    return result


def recall_persona_sections(query: str, config: dict) -> list[PersonaExcerpt]:
    """Rank source sections by lexical evidence; fixture answers are never inputs."""
    if not _personal_question(query):
        return []
    terms = _terms(query)
    sections = [section for section in _configured_sections(config)
                if not re.search(r"历史档案|历史校准|历史保留|关键词索引|目录", section.heading)]
    if not terms or not sections:
        return []
    # Ancestor titles supply provenance, not repeated evidence for every child.
    bags = [_terms(section.heading.split(" > ")[-1] + "\n" + section.text) for section in sections]
    terms = frozenset(term for term in terms if any(term in bag for bag in bags))
    if not terms:
        return []
    weights = {term: math.log(1 + len(bags) / (1 + sum(term in bag for bag in bags))) for term in terms}
    denominator = sum(weights.values())
    average_length = sum(map(len, bags)) / len(bags)
    ranked: list[tuple[float, PersonaExcerpt]] = []
    for section, bag in zip(sections, bags):
        overlap = terms & bag
        # A single rare term is sufficient only when it identifies one section.
        unique_match = len(overlap) == 1 and sum(next(iter(overlap)) in bag for bag in bags) == 1
        title_overlap = overlap & _terms(section.heading.split(" > ")[-1])
        if len(overlap) < 2 and not (unique_match or title_overlap):
            continue
        coverage = sum(weights[term] for term in overlap) / denominator
        if coverage >= 0.18:
            length_factor = 2.2 / (1 + 1.2 * (0.25 + 0.75 * len(bag) / average_length))
            title_bonus = sum(weights[term] for term in title_overlap) / denominator
            ranked.append(((coverage + title_bonus) * length_factor, section))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    if not ranked:
        return []
    return [ranked[0][1]]


def persona_recall_blocks(query: str, config: dict, *, present_sources: set[str] | None = None) -> list[str]:
    """Return capped source excerpts with dates and interpretation boundaries."""
    present = present_sources or set()
    blocks: list[str] = []
    remaining = 3500
    for section in recall_persona_sections(query, config):
        if section.source in present:
            continue
        body = section.text[:min(1800, remaining)]
        if not body:
            break
        blocks.append(
            f"[context:{section.source}]\n[原始档案相关片段：L{section.start}–L{section.end}]\n"
            f"{section.heading}\n{body}\n"
            "以上仅为带语境的来源证据；保留日期、否定和待验证条件，不能把历史进度当作当前状态。"
        )
        remaining -= len(body)
    return blocks
