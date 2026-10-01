# 基础版本：失败记录与回归入口

日期：2026-10-01。使用现有测试和 workflow eval 维护；不自动改写 baseline、路由、prompt 或检索权重。

| 失败簇 | 已有证据及复现 | 预期行为 | 固定回归入口 |
|---|---|---|---|
| 错误副作用 | 历史内容分析被误当发布；能力询问、否定发布、扩大参数范围；macOS 路径下润色文章被误路由到发布 | 分析/润色不执行发布；编辑先生成确认预览且原文不变；发布目标和授权证据匹配；拒绝零副作用 | `evals/workflow_cases.json` 的 action_mediation/Hugo cases；`tests/test_obsidian_runtime.py`、`tests/test_outbox.py`、`tests/test_obsidian_write_preview.py`、`tests/test_desktop_tool_router.py`；润色修复 `cbfcad2` |
| Plan 丢失 | `d52a286`：新会话第一次保存后 session ID 切换，计划卡消失 | 会话迁移保留同一 proposed Plan，重放不重复 | Desktop `eventLog.test.ts`、`runtimeHelpers.test.ts`；修复汇回为 `3cffce2` |
| API 重复启动 | 原现场在慢启动/退出期间重试，旧进程未退出就可能启动新进程 | 等待存活子进程就绪；退出确认前不替换；终止失败保留失败态 | Desktop `apiProcess.test.ts`，安装后单监听进程及重启检查；修复 `25065fe` |
| 会话隔离错误 | 原 journey 检查 session 文件名而非临时数据根目录；工作树被误算生产代码；旧测试缓存默认情绪库/线程索引路径 | 测试会话进入临时根目录；独立工作树不作为当前生产模块 | `tests/test_journey_smoke_script.py`、`tests/test_session_routes.py`、`tests/test_part8_module_graduation.py`、`tests/test_reflect.py`；修复 `348f1dc` / `3f7348b` |
| 记忆/线程连续性 | 新增自然回忆问题在关键词降级路径初测 0/30；文件可读被误报为已注入 | 明确回忆问法可找到主题；无关问题不注入；按 thread ID 恢复目标、决定、纠正和停点；回执来自实际模型 prompt | `tests/test_foundation_memory.py`、`tests/test_memory_continuity_j8.py`、`tests/test_context_assembly.py`、`tests/test_persona_sources.py`；修复 `9935cf1` |

## 本地验收结果及边界

- `evals/foundation_memory_cases.json` 是依据协作主题制作的合成脱敏资料，不是用户原始 SOUL/MEMORY 内容。
- 30 个自然回忆问题：30/30 命中，0/30 无关注入；不相关或要求编造新内容的问法不进入主题回退。
- 10 个线程各有两个会话，并在独立 Python 进程中恢复目标、结论、用户纠正、未完成事项和停点，10/10 通过；重复 session 注册不新增绑定。
- 保留原有 80 条长对话及检索时延回归。
- 本轮只增加三类明确回忆问法的关键词回退；保留原检索和向量路径。它不证明任意同义改写、语义检索或私人全量资料的召回质量。
- `contextReceipt.sources.persona` 的结构保持不变，改为在模型消息装配后根据核心 system prompt 的来源块记录；`/ready` 的文件可读状态不能证明注入。
- 原 workflow baseline 未更新，27 个固定 case 通过。

## 测试隔离事故与恢复

- 首轮在原目录运行旧测试时，测试只替换部分 DB/目录引用，产生了默认情绪、独白、shadow 发送记录及线程索引写入。干净环境同时暴露四个反思测试依赖已有情绪表。
- 对照开始前 SQLite backup：既有行均未修改；确认新增测试状态后，单独备份清理前现场，按主键只删除 12 条情绪、42 条独白、1 条 shadow 发送、8 条线程绑定、7 条线程状态，恢复原线程 JSON。完整性检查为 ok。
- 保留真实原 Job retry 的所有证据、5 条 pending memory（307–311）和 Soul proposal 117；没有整库回退。
- 反思测试现在隔离并恢复 emotion/store/artifacts 的全局引用（`883b0c6`）。独立工作树仍会使用 HOME 下共享审批审计，追加修复 `98d1d88` 为全套 pytest 隔离审计；196 项相关回归通过，用户审计不再变化。76 条本轮测试审计已先备份再移除，1646 条历史审计保留。完整离线套件统一在独立干净工作树运行，配置指向该工作树临时 DB/session；不以主库已有表掩盖测试缺陷。其他旧测试的默认路径治理仍需沿用隔离工作树，不能宣称全套测试已能安全直跑用户配置。

## 人工维护流程

1. 从失败记录或用户纠正中摘取最小脱敏场景，写明期望结果；不默认保存完整私人对话。
2. 先判断它属于上述哪类、是否重复、是否有可靠证据；证据不足标为待确认。
3. 在对应现有测试或 eval 中补回归，修复后对比原 baseline；只有明确批准行为变更后才能更新预期。
4. 构建日志保留失败、修复、验证等级和回滚点，不用候选数量或模型自评冒充质量指标。

Runtime 后续权威迁移、自由改写语义召回、真实资料全量 J8、自动反馈采收和 Part 8 主动投递仍待后续验收。

## 已收口的离线测试入口

```bash
bash run_tests.sh                     # 默认 9 项 smoke
bash run_tests.sh --suite foundation  # 当前 114 项基础回归
bash run_tests.sh --suite full        # 当前 1987 项离线回归
```

入口验证已提交 HEAD；未提交修改不会进入测试，可用 `--ref <commit>` 指定提交。`--report <path>` 将提交、选择范围和退出码保存在临时目录之外。全量排除 integration/journey，不触发真实模型。

runner 用 Git archive 建立一次性 checkout，补 Git index 供架构检查，使用公开配置和合成资料。macOS 下临时根位于 `~/.codex/tmp`，让路径相关测试覆盖真实 `/Users/` 路由。Python audit hooks 拦截用户库访问、用户目录写入和外部/生产 API 连接；不是 OS 级隔离，也未全面改造旧测试全局引用。推荐入口替代手工准备隔离配置，仍不要在真实配置下直接跑全量 pytest。

同日补充确定性并发复现：重复结果确认在 Step 终态、Run 尚未终态的窗口仍应返回同一确认结果，只有一份不可变 receipt；接受/纠正均覆盖，取消保持优先。`tests/test_user_outcome_confirmation.py` 8 项通过，修复 `6a27a04`。全量最初失败、根因及最终 1967 passed 日志都保留；没有批量重写 baseline。

## 跨进程 API 场景补充

`tests/test_foundation_api_restart.py` 在两个独立 Python 进程启动 FastAPI TestClient，使用同一合成持久化目录。检查会话内容和 thread ID、目标/决定/纠正/停点、审阅记忆及重复决定、相同命令只创建一个 Job、取消和重复拒绝审批零执行；身份认证也经过真实 middleware。没有 HTTP 外网或模型请求。只有通过隔离 runner 才运行此场景；裸 pytest 跳过，避免子进程使用生产配置。

该场景发现两个真实问题并保留失败日志：

| 失败簇 | 根因 | 修复与回归 |
|---|---|---|
| 记忆/线程连续性 | 默认索引路径解析后被误判为隔离索引，线程 REST 读取缺少已保存 capsule | `ba466a0`；`tests/test_thread_store.py` 验证默认/显式 db_path 投影及隔离索引不读默认 DB；跨进程 API 恢复通过，安装版已有 40 个 capsule 与原数据一致 |
| 重复请求与审批副作用 | 相同草稿刷新缓存时间戳，被 Outbox 当作业务载荷冲突 | `79f256d`；`tests/test_tool_approval_cache_replay.py` 验证原 cancelled receipt/payload 未变、业务参数或 requiresApproval 改变仍拒绝；跨进程重复拒绝零执行 |

这轮聚焦 33、foundation 101、全量离线 1974 / 65 未选、Desktop 556、安装版 9/9 通过。原 workflow baseline 不变，Runtime shadow 不变；私人全量 J8 与真实模型跨多轮任务仍不据此标为完成。

## J8 真资料副本补充（源码 `5fddf4a`）

| 失败 | 根因与预期 | 固定回归 |
|---|---|---|
| 轻量上下文缺少原始事实 | 压缩 persona 与保守 DB 检索不足以覆盖配置中已有 SOUL/MEMORY；相关原文应进入实际 prompt，保留日期、否定和待确认，历史档案不作当前答案 | `tests/test_persona_recall.py`：simple/full、无关/编造问题、旧事实纠正、记忆 off、文件失败降级、缓存及长度限制 |
| 未知线程串入全局最近线程 | 显式 thread ID 无 capsule 时不应借用另一线程的目标/停点 | 同文件显式未知线程回归；既有 `test_foundation_api_restart.py` 保留 |
| 助手建议被标成已确认结论 | 现有 capsule 的 decisions 含助手回复；展示为历史回复，决定必须核对用户确认，不改旧数据库 | 同文件未确认助手建议回归 |

真资料 30 问在同一最终判据下，旧源码 7/30、修复后 30/30；只证明实际模型上下文支持事实。人工复核 25 个动态来源片段有 1 个无关（4%）；DB 动态条目为 0，固定人格上下文单列。语义模型离线预热后 30/30，17 次检索 p95 340.72ms，保留真实库时延缺口。实际历史没有两会话线程，用户选择的 10 段真对话拆分回放在新进程 10/10，不替代真实历史跨会话。

聚焦 28、foundation 114、全量离线 1987 / 65 未选通过，原 80 条长对话及 27 case baseline 不变。三条合成模型场景最终通过，累计 5 次尝试；没有用真资料调用 Archer 远程模型。证据整理误将部分私人上下文打印到 Codex 工具结果，违反整轮脱敏约束；事故及停止内容打印的处理已记录，不能据此声称私人上下文从未进入模型。原文件/持久化状态/9 个无关改动未变。完整结果及边界见 `docs/j8-local-acceptance-2026-10-01.md`。
