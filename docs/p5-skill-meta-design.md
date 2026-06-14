# P5.3 Skills 元数据与自动触发 — 设计文档

日期：2026-06-13  
状态：阶段二（实现完成）

## 问题

- 43 个 Python 技能仅有 `SKILL` 基础字段，编排层无法按意图预选
- `skill_router.select_skills()` 依赖硬编码 `_ROUTES`，与技能文件脱节
- Desktop system prompt 不知道「本轮可能用哪些技能」

## 目标

每个技能自描述 `__meta__`，编排层通过 `auto_match_skills()` 预选并注入 prompt。

## SkillMeta 结构

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | str | 与 `SKILL["name"]` 一致 |
| `description` | str | 一句话用途 |
| `keywords` | list[str] | 自动匹配关键词 |
| `risk` | str | low / medium / high / critical |
| `model_preference` | str | 可选，如 `fast` / `reasoning` |
| `auto_trigger` | bool | 是否参与自动匹配，默认 true |

存放：各 `skills/*.py` 顶部 `__meta__` dict；缺省时从 `SKILL` 推断。

## 匹配逻辑

```
auto_match_skills(intent, user_input)
  → select_skills() 基础命中 (+5)
  → __meta__.keywords 子串命中 (+3/词)
  → intent=task 时 medium/high risk 技能 +1
  → 按分数排序，返回 top N 名称列表
```

## 集成

- `skills/loader.py`：`parse_skill_meta()` / `get_skill_meta()`
- `core/skill_router.py`：`auto_match_skills()`
- `core/orchestrator.py`：`matched_skills` + `format_matched_skills_for_prompt()`
- `core/context.py`：`matched_skills_block` 注入 system prompt

## 首批 __meta__（10 个核心技能）

web_search, web_fetch, file_ops, file_search, obsidian_read, obsidian_write, obsidian_search, shell, github_ops, code_search

## 验收

- [x] `tests/test_skill_meta.py` 通过
- [x] `tests/test_skill_router.py` 回归绿
- [x] orchestrator 测试绿
