# P5.6 Hooks 生命周期事件 — 设计文档

日期：2026-06-13  
状态：阶段二（实现完成）

## 目标

在关键生命周期节点插入可配置钩子，支持日志、拦截、参数改写。

## 事件

| 事件 | 触发点 |
|------|--------|
| `PreToolUse` | 策略通过后、技能执行前 |
| `PostToolUse` | 技能执行后 |
| `PreCompact` | memory/chat 压缩前 |
| `PostCompact` | memory/chat 压缩后 |
| `SessionStart` | CLI 会话启动 |
| `SessionStop` | CLI 会话退出 |

## Hook 类型

| 类型 | 行为 |
|------|------|
| `python` | `module:function(context_dict) -> dict` |
| `command` | stdin 传 JSON context，stdout 解析 JSON 结果 |
| `prompt` | 预留：记录 prompt 模板，默认放行（不调用 LLM） |

## 配置（archer.toml）

```toml
[hooks]
enabled = true

[[hooks.PreToolUse]]
type = "python"
handler = "myhooks.audit:prepend_tag"
matcher = "web_search"   # 可选，限制工具名

[[hooks.SessionStart]]
type = "command"
command = "echo '{\"continue\": true}'"
```

## 返回协议

Hook 返回 dict（或 HookResult）：

- `continue` / `continue_`：false 则阻断
- `tool_input`：PreToolUse 可改写参数
- `message`：阻断或提示文案

## 模块

- `core/hooks.py` — HookRegistry + run_hooks
- `core/tool_loop.py` — Pre/PostToolUse
- `core/orchestrator.py` + `core/compressor.py` — Pre/PostCompact
- `terminal/archer.py` — SessionStart/Stop

## 验收

- [x] `tests/test_hooks.py`
- [x] tool_loop / compaction 回归
