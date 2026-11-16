# 技能契约与缺口核对 · 2026-11-16

核对对象是远端 `codex/foundation-20261001` @ `4673f9af665cc1057d690380253a44f613dfedd6`，以及本分支在其上的改动。用户本机 `6c0f9071544375155e3d35ce8b1770227fdf6e98` 未推送，本环境看不到那次提交的补丁，不能把它算作已在此验收，也没有与它对过合并。

本轮没有读私人会话、记忆库或配置密钥，没有调用模型，没有启动安装版，没有切 Runtime 权限，没有打开 Part 8 投递。健康检查失败只说明当时进程没在跑，不记成启动崩溃。

技能个数以 `skills.loader.register_all_skills()` 和 `GET /skills` 为准。本文不写死个数。`docs/structure.md` 里 2026-07-18 的 43 是当时 `ls skills/*.py` 的文件数，已改为指向注册表。

## 六域短记

### 核心问答 — 已实现，本轮未做安装态复验

`terminal/api/fastapi_app.py` 的 `/chat/stream` 在断连时释放并发槽，占槽时返回 429 `chat_busy`（约第 258、521 行）。这是已合入的 PR #4。本轮没有起服务重放。

### 记忆续话题 — 已实现，真样本仍缺

`terminal/api/session_routes.py` 对调用方传入的未知 `threadId` 失败关闭（约第 166 行），不再静默新建话题。`ensure_thread_for_continue`（约第 279 行）负责续话题前补索引。真实跨会话样本和安装版私人回答抽检不在本轮；没有读用户会话文件，不能把旧文档里的 0/10 改写成新测量。Part 8 仍关闭。

### Skills / 工作流 — 有缺陷，本分支修了契约投影

修之前：

- `GET /skills`（`terminal/api/profile_routes.py` 的 `_skills`）只返回 name、description、risk、enabled。Desktop `SkillsPage` 只画这四项。`SkillItem.permissionLevel` 已存在，但接口不填，设置页权限矩阵因此全部落到 `unknown`。
- `skills/meta.py` 把缺失或无法识别的 risk 收成 `low`。`soul_evolution.py` 用带注解的赋值 `SKILL: dict[...] = ...`，loader 只认普通赋值，注册描述变成名字本身，风险显示成低。
- `skills/run_shell.py` 把 `run` 直接 import 进来。loader 要求文件里有 `def run`，别名因此没有进入生产注册表。`core/permission_levels.py` 也不认识 `github_ops` / `run_shell`，未命中的名字最后返回 `read-only`。
- 审批记录在 `read_tool_approval_audit`，里面有 policyReason、message，可能含命令或路径。Skills 页原先不展示，也没有单独的调用日志。

本分支：

- `skills/catalog.py` 以注册表名字为真源，投影权限、审批、输入摘要、输出摘要和脱敏后的最近审批。未列入分类表的名字，权限和审批都是 `unknown`，不会显示成只读或无须审批。
- 权限分类是代码审查后的固定值或最高值（`permissionBasis=fixed|ceiling`）。`browser_automation` 对不上现有四档，权限保持 `unknown`，审批仍按当前 policy 记为不要求。
- 现有技能都没有结构化输出声明，输出摘要固定为「未声明结构化输出」，不编造输出。
- 最近审批只保留 decision、executed、permissionLevel、timestamp。没有记录时写「窗口内没有记录」，读失败时写「暂时读不到记录」。不把空窗口说成从未调用。
- `run_shell` 改为字面量 `SKILL` 加真正的 `def run`，并与 `shell` 走同一条命令分级。`github_ops` 的读操作、建 issue、任意 `gh` 分开标权限。
- 未分类名字的单次调用仍可能被 `permission_level_for_tool` 标成 `read-only`（现有 `safe_tool` 审计测试锁定了这个回落）。目录投影不复用这个回落。

### 反馈与 Runtime — 真人样本 / 人工授权，本轮不重做

远端这个 tip 已有 initiative 反馈路由。2026-11-06 的 Today 曝光/反馈和 Runtime review packet 在未推送的 `6c0f907`，涉及的文件见文末，本分支没有改它们，也没有补做那次提交。真实反馈条数、人工批准和 `vault_reflection` 切权仍待人完成。

### 桌面持久化 / 稳定性 — 仅缺真实验收，没有新的可复现崩溃

设置保存路由还在。用户已把真实设置保存留到有可逆需求时。本机今天没有 Archer 进程，不能用健康检查失败证明崩溃。本轮没有改存储层。

### 工程回归 — 明确暂停的测试债未动

PR #7（TestClient / SSE 防挂死）保持不合，本分支没有复制它的改动。下面的测试是进程自己结束的，不是到点杀进程后当成通过。没有跑全量，也没有 build / 安装。

## 本轮验证

通过：

- `python3 -m pytest tests/test_skill_catalog.py tests/test_skill_meta.py tests/test_policy.py::test_github_ops_confirm tests/test_policy.py::test_github_ops_create_issue_confirm tests/test_policy.py::test_github_ops_run_strong_confirm tests/test_policy.py::test_shell_write_redirect_confirm tests/test_policy.py::test_shell_git_commit_confirm -q --tb=no` → 24 passed
- `npx vitest run src/renderer/src/pages/SkillsPage.test.tsx`（在 `client/desktop/`，本环境 Node v22.23.4；package 引擎要求 Node 24，测试进程仍正常结束）→ 3 passed

未跑或未完成：

- `tests/test_smoke.py::test_skills_load` 在导入 `skills/image_ocr.py` 时缺少 `pytesseract`。这是当前环境没有可选依赖，测试没有走到断言。
- 全量 pytest、Desktop 全量、`tsc`、打包、安装版和真实 `/skills` 都没跑。
- 没有把本分支和 `6c0f907` 做合并演练。

## Workflow 候选（只记录，不配置、不执行）

1. Hugo 发布：已注册 `hugo_blog`。读/列表/doctor 当前放行，发布和部署需要审批，权限最高到远程部署。
2. Obsidian 受控写入：已注册 `obsidian_write`，权限是库写入。`Archer/` 前缀当前放行，其他路径要审批。
3. 周复盘：已注册 `weekly_review`，目录里标成只读；真正执行时会读 vault 材料。本轮没有跑它。

## 与未推送本机提交的重叠

以下 21 个路径本分支没有修改。其中有共享文件；不能声称已验证能干净合进 `6c0f907`。

- `client/desktop/package-lock.json`
- `client/desktop/package.json`
- `client/desktop/src/renderer/src/adapters/__tests__/localArcher.test.ts`
- `client/desktop/src/renderer/src/adapters/initiativeAdapter.ts`
- `client/desktop/src/renderer/src/adapters/initiativeReports.ts`
- `client/desktop/src/renderer/src/components/VisibleInitiativeCard.tsx`
- `client/desktop/src/renderer/src/lib/initiativeStore.ts`
- `client/desktop/src/renderer/src/pages/TodayPage.test.tsx`
- `client/desktop/src/renderer/src/pages/TodayPage.tsx`
- `client/desktop/src/renderer/src/styles/pages.css`
- `client/desktop/src/renderer/src/types.ts`
- `core/initiative_feedback.py`
- `core/job_cutover_human_review.py`
- `docs/feedback-runtime-preparation-2026-11-06.md`
- `docs/runtime-cutover-review-2026-11-06.md`
- `terminal/api/_routes.py`
- `terminal/api/initiative_routes.py`
- `terminal/api/runtime_run_routes.py`
- `tests/test_feedback_review_preparation.py`
- `tests/test_job_cutover_evidence_window.py`
- `tests/test_today_page.py`

`types.ts` 未改。Skills 页用新的 `skillCatalog.ts` 读取接口多出来的字段；旧的四字段响应会显示权限未知、审批未知。安装 npm 时曾改动 `package-lock.json`，已还原，不进入提交。设置页权限矩阵仍直接读 `permissionLevel` 字符串：有上限的技能会显示最高档本身，Skills 页才会写成「权限最高到…」。

## 后续队列（最多 6 项）

1. 真人样本：继续用自然续话题积累真实跨会话线程，并做安装版私人回答抽检。代码入口已在，本轮没有新测量。
2. 真人样本：至少 3 条真实 initiative 反馈。入口改动在未推送的 `6c0f907`，不要在远端分支重做。
3. 人工授权：`vault_reflection` 的 create / start / retry 仍待与当时指纹匹配的批准。审查材料在同一次未推送提交里。
4. 工程可修，需单独决定：`permission_level_for_tool` 对未分类技能仍回落 `read-only`。改它会改变已有审计语义。
5. 工程可修，但是产品决定：`code_edit`、`memory_save`、`npm_run`、`installer`、`browser_automation` 等有副作用，当前 policy 仍不要求审批。本轮只把这句话显示出来。
6. 明确暂停：PR #6 人格不合、不继续；PR #7 测试防挂死保留不合；Part 8 真投递保持关闭。

## 2026-11-16 第二批：调用期权限不再把未知收成只读

### Before

`permission_level_for_tool` 在名字没有命中专门分支时返回 `read-only`。审批回写也只传名字和参数，不传 SKILL。因此 `code_edit`、`memory_save`、`npm_run`、`installer` 这类已注册技能，以及根本没有元数据的名字，在真实请求和审计里都会记成只读。`policy.check` 对缺少模块的名字直接 `ALLOW`（旧测试写明交给 runtime 的 SkillNotFound）。非法的 `SKILL` 对象会在读 `version` 时抛异常。

### After

- 已有分支保持不变：`shell` / `run_shell` / `shell_execute` 按命令分级；`github_ops` 的读操作、建 issue、任意 `gh` 仍分开。`shell_execute` 没有注册；如果调用方用这个名字，策略走 shell 的命令分级，不再掉进通用放行。
- 其余已分类名字使用目录契约。`code_edit`、`memory_save`、`npm_run`、`installer` 的调用标签是 `write-local`，`browser_automation` 是 `unknown`。这五者的审批决定没有改：前四个和 browser 仍按原来的 `ALLOW`。
- 未分类名字、MCP 权限不是明确的 read/write、以及 `SKILL` 不是对象时，权限是 `unknown`。调用方拿到字符串，不会因为新值抛异常。Desktop 契约解析接受 `unknown`。
- 没有模块、`SKILL` 不是对象、或风险值不在 low/medium/high/critical 时，`policy.check` 返回 `CONFIRM`，工具循环不会直接执行。已注册且风险字段省略的技能（例如 `site_check`、`soul_evolution`）仍走原来的放行，避免把已知策略一刀切改掉。
- `run_shell` 注册后执行的是 `shell.run`，命令分级和子任务拒绝名单与 shell 相同，没有单独放宽。

`core/policy.py` 仍是 730 行，没有超过行数闸门。新增判断放在 `core/skill_metadata_guard.py`。

### 这一批的验证

通过：

- `python3 -m pytest tests/test_permission_call.py tests/test_skill_catalog.py tests/test_policy.py tests/test_api_tool_service.py tests/test_smoke.py::test_skills_load tests/test_architecture_boundaries.py::test_god_files_cannot_grow_beyond_part10_gate0_baseline --override-ini addopts= -q --tb=line`：126 passed。同一次里的行数闸门失败只剩预先存在的 `terminal/api/_routes.py` 633 行，基线 629；该文件在 `4673f9a` 上已是 633 行，本批没改它。
- `tests/test_smoke.py::test_skills_load` 和 `test_skills_tools_format` 已执行到断言并通过。云端安装了 `requirements.txt`，以及技能源码会导入、但 requirements 没有写明的 `pytesseract`、`pymupdf`、`feedparser`。没有改 lock，也没有把这些包写回仓库。
- 直接调用 `payload_get("/skills")`：HTTP 200，返回行与 `register_all_skills()` 一致。`code_edit` 为 `write-local`，`browser_automation` 为 `unknown`，`web_search` 为 `read-only`。个数以这次注册结果为准，不在这里写成新的基线。
- Node v24.22.3：`npx vitest run` 上述三个 Desktop 测试文件 20 passed；`npx tsc --noEmit` 通过；`npm run build` 通过。

有上限的全量，不是全绿：

- `python3 -m pytest -m "not journey" --timeout=20 --timeout-method=signal --override-ini addopts= -q --tb=line`
- 57.29s 结束。2102 passed，17 failed，2 skipped。没有测试被 20 秒上限杀掉，这次没有复现 PR #7 的挂起。失败项是环境或原有闸门：缺 `archer.toml`、`python`、`mcp`、拼音库，Hugo 直发两条在撤掉本批 policy 改动后同样失败，以及上面的 `_routes.py` 行数。不把这些记成通过。

### 下一批可工程修，本批不做

1. `terminal/api/_routes.py` 行数闸门（633 > 629）。文件在本机未推送的 21 个路径里，本批不改。
2. `site_check` 与 `soul_evolution` 省略了 risk，调用策略仍是历史放行。
3. `file_ops` 的读动作在单次调用里是 `read-only`，目录里的最高权限仍是 `deploy-remote`。这是参数分级，不是未知回落。
4. `pytesseract`、`pymupdf`、`feedparser`、拼音转换没有写进 `requirements.txt`，干净环境会在导入或 slug 测试处失败。
5. MCP 在 `cfg=None` 的旧入口里，黑名单之后仍可能 `ALLOW`。生产入口会传配置。
6. 安装版和真实 `/skills` 仍未验收。五个已有明确放行策略的技能没有改审批。

