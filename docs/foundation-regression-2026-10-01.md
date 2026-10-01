# 基础版本：失败记录与回归入口

日期：2026-10-01。使用现有测试和 workflow eval 维护；不自动改写 baseline、路由、prompt 或检索权重。

| 失败簇 | 已有证据及复现 | 预期行为 | 固定回归入口 |
|---|---|---|---|
| 错误副作用 | 历史内容分析被误当发布；能力询问、否定发布、扩大参数范围 | 分析不执行发布；发布目标和授权证据匹配；拒绝零副作用 | `evals/workflow_cases.json` 的 action_mediation/Hugo cases；`tests/test_obsidian_runtime.py`、`tests/test_outbox.py` |
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
