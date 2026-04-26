# Archer 构建日志

> 格式：bullet，只写改了什么和为什么，最新在前。

---

## [Claude Code] 架构重构 P0 — 安全稳定底座（20260426）

- **Step 0 基线冻结**：新增 `tests/` 目录，9 个 smoke test，`BACKLOG.md`（15 条已知问题），`OVERVIEW.md`（供外部 AI 审查），git tag `step-0-baseline`
- **Step 1 Skill Runtime Wrapper**：新增 `core/tool_runtime.py`，统一技能调用入口；ThreadPoolExecutor timeout 防卡死；结构化 ToolResult（ok/error.type/retryable）；超长结果（>12k chars）存 artifact 不进 messages
- **Step 2 Policy Layer**：新增 `core/policy.py`，三级决策 DENY/CONFIRM/ALLOW；shell 黑名单 13 条（rm -rf ~/sudo/mkfs/fork bomb/curl|sh 等）；file_ops 写操作需确认；installer URL 安装改为下载→代码扫描→预览→输入 `INSTALL <name>` 全字确认；shell/file_ops/github_ops SKILL 元数据加 risk/timeout 字段
- **Step 3 pending 持久化**：`memory/store.py` 新增 `pending_memories` 表；移除 `archer.py` 全局列表 `_PENDING_MEMORIES`；accept/reject 改用真实 DB ID（不再是 1-based 序号）；进程崩溃后 pending 不丢失
- **Step 4 artifact 规范化**：`core/artifacts.py` 支持 tool_results/reflections/summaries 三类子目录；`dir_size()` + `fmt_size()`；`/status` 新增 pending 数量（黄色提示）和 artifact 占用显示
- **Step 5 /reflect 重写**：新增结构化 JSON 输出（summary/user_intent/decisions/open_questions/memory_candidates/next_actions）；结果进入 session.history（允许追问）；summary 存为 `type='reflection'` 记忆；完整 JSON 落盘 `.artifacts/reflections/`；新增 `_reflect_to_text()` 纯函数
- **测试**：5 个测试文件，66 个测试，全绿；每步一个 git tag（step-0 → step-5）

**待续（P1 灵魂成长层）**：
- Step 6：Memory Schema 生命周期字段（confidence/valid_until/last_used_at）
- Step 7：patterns/themes 图结构
- Step 8：事件触发提炼机制（替换每 3 轮同步提炼）
- Step 9：Project State（/project 命令）
- Step 10：SOUL 演化（diff proposal，永不自动覆写）

---

## [Claude Code] UI · token统计（20260426）

- `core/llm.py`：新增 `_last_usage` / `_session_tokens` 全局变量，`stream_options={"include_usage": True}` 捕获流式 token 用量，对外暴露 `get_last_usage()` / `get_session_tokens()`
- 修复重复累加：用 `call_usage` 局部变量暂存，generator 耗尽后才写入全局，避免多 chunk 叠加
- `core/input.py`：补全菜单取消灰色背景（`bg:default`），与终端底色统一
- `archer.py` 状态栏：输入框下方只显示模型名，token 统计（`↑输入 ↓输出 · session 累计`）移至 LLM 响应完成后显示
- 修复双空行：删除 `_run_with_tools` 里多余的 `console.print()`，`_stream()` 自带 `\n` 前缀已足够
