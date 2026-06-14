# P5.7 分层配置合并 — 设计文档

日期：2026-06-13  
状态：阶段二（实现完成）

## 分层顺序（后层覆盖/追加）

| 层级 | 来源 | 示例 |
|------|------|------|
| 1 | `archer.toml` 指向的基础文件 | `COVENANT.md` |
| 2 | 同目录 `.local.md` 个人覆盖 | `COVENANT.local.md` |
| 3 | 项目根约定 | `./ARCHER.md` |
| 4 | 项目根个人覆盖 | `./ARCHER.local.md` |

Markdown 合并策略：基础内容保留，override 以 `---` + `[label override]` 追加；缺失文件静默跳过。

## 注入点

- `build_system_prompt()`：COVENANT/PRESENCE/SOUL/MEMORY 走 `load_layered_file()`；项目层注入 `[项目约定（ARCHER.md）]`
- `build_core_persona(cfg)`：提取 `ARCHER.md` 中 `## Persona` 段合并进核心 persona

## 项目根

优先 `ARCHER_PROJECT_ROOT` 环境变量，其次 `cfg.persona.project_root`，默认 `cwd`。

## 验收

- [x] `tests/test_layered_config.py`
- [x] context 回归
