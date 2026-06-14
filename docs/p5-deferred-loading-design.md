# P5.5 Deferred Tool Loading — 设计文档

日期：2026-06-13  
状态：阶段二（实现完成）

## 问题

`load_skills()` 启动时 import 全部 ~43 个技能模块，增加启动耗时与无关 context 开销。

## 目标

两阶段加载：

| 阶段 | 内容 | 时机 |
|------|------|------|
| Register | 技能名 + `SkillMeta`（keywords/description/risk） | 启动 / 首次 `register_all_skills()` |
| Full load | 完整 module（`schema` / `run`） | 首次路由命中或 `get_tools` 选中 |

## 接口

- `register_all_skills()` → `DeferredSkillRegistry`（meta-only，AST 扫描）
- `register_skill_meta(path)` → 单文件 meta 注册
- `load_skill_full(name)` → LRU 缓存完整模块（默认 maxsize=10，`ARCHER_SKILL_CACHE_SIZE` 可调）
- `load_skills()` → 兼容别名，返回 registry（按需加载）

## LRU

`functools.lru_cache` 包装 `load_skill_full`；缓存 miss 时 `importlib` 加载，evict 最久未用模块。

## 集成点

- `core/skill_router.py`：`select_skills` 只对命中技能 lazy resolve
- `core/skill_router.py`：`auto_match_skills` 只读 registry meta，不 import 全量
- `core/orchestrator.py` / `_routes._skills()`：列表展示用 meta
- `get_tools(subset)`：仅为选中技能加载 schema

## 验收

- [x] `tests/test_deferred_loading.py`
- [x] `test_skill_meta` / `test_smoke` 回归
