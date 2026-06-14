# P5.13 Scheduled Tasks 产品化 — 设计文档

日期：2026-06-13  
状态：阶段二（实现完成）

## 存储

| 层 | 位置 | 角色 |
|----|------|------|
| 权威 | `archer.db` → `scheduled_tasks` 表 | CRUD、到期检测、执行后更新 |
| 镜像 | `memory/schedules.json` | 人工可读、Desktop 展示路径提示 |

每次增删改或执行后，`core.scheduler.sync_schedules_json()` 重写 JSON 镜像。

## 任务字段

- `skill_name` / `interval_h`（由 `daily|weekly|monthly|Nh` 解析）
- `label`、`args_json`、`catchup`（`latest` | `skip`）
- `enabled`、`last_run_at`、`next_run_at`

## CLI

- `/schedule list|add|remove|enable|disable|run`（与既有 `/cron` 共用实现）
- 启动时 `run_due_tasks()` 自动执行到期项

## Desktop API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/schedules` | 列表 + `jsonPath` |
| POST | `/schedules` | `{ skillName, interval, label?, catchup?, args? }` |
| POST | `/schedules/{id}/remove` | 删除 |
| POST | `/schedules/{id}/enable` | 启用 |
| POST | `/schedules/{id}/disable` | 禁用 |
| POST | `/schedules/{id}/run` | 立即执行 |

## Desktop UI

Settings → **定时** 标签：列表、启用/禁用、删除、立即运行；表单添加任务（技能 + 间隔 + 标签）。

## 验收

- [x] `tests/test_scheduler.py`（含 JSON 镜像）
- [x] Desktop API schedule 路由测试
- [x] Settings 定时任务面板
