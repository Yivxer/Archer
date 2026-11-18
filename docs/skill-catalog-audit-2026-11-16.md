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

## 2026-11-17 第三批：依赖可复现，并归因上一轮 17 个失败

### Before

`requirements.txt` 没有声明 OCR、PDF、RSS 和拼音。这三个技能在模块顶层导入第三方库，`test_skills_load` 会逐个导入模块，缺一个包就让整次加载失败。上一轮是在当前环境里额外安装后才跑过，换一台按声明安装的机器不能复现。

上一轮有上限全量是 2102 passed / 17 failed / 2 skipped。没有测试被 20 秒上限杀掉。

### 声明

- `requirements.txt`：运行和注册技能所需。不加入这四个库。
- `requirements-dev.txt`：测试运行器、`httpx`、Hugo 拼音用的 `pypinyin`、MCP SDK。CI 的 Python 步骤改为安装这个文件。
- `requirements-skills.txt`：`pymupdf`、`feedparser`、`pytesseract`。可选。缺它们时技能仍注册；`run()` 返回缺依赖说明，不换成假实现。
- `pypinyin` 放在 dev 声明里，因为中文 slug 的成功路径测试依赖它；生产代码原本就有导入失败后的回退，没有改成强制依赖。

`image_ocr`、`pdf_reader`、`rss_reader` 改为在 `run()` 里导入对应库。

### 上一轮 17 项

| 测试 | 原因 | 与基线 | 本批 |
| --- | --- | --- | --- |
| `test_architecture_boundaries.py::test_god_files_cannot_grow_beyond_part10_gate0_baseline` | `terminal/api/_routes.py` 633 行，基线 629 | `4673f9a` 上已是 633，不是本 PR 引入 | 不改闸门，不拆文件 |
| `TestApiSkillRouting::test_direct_hugo_publish_reads_explicit_path_with_spaces_and_heartbeats` | 聊天迭代没有发出名为 `hugo_blog` 的工具事件 | 上一轮撤掉 policy 改动后同样失败；装上拼音后仍失败 | 不放宽 Hugo 授权或策略 |
| `TestApiSkillRouting::test_hugo_upload_path_routes_even_when_needs_tools_is_false` | 同上 | 同上 | 同上 |
| `test_fastapi_routes.py::test_ready_is_public` | `/ready` 读到的人格路径不可读，`persona.ready` 为 false | 仓库不提交私人 `archer.toml` | 测试自建可读夹具，断言仍要求 ready 且 missing 为空 |
| `test_hooks.py::test_command_hook_reads_json_stdout` | 命令写成 `python`，环境只有 `python3` | 环境差异，不是本 PR 引入 | 测试改用当前解释器 |
| `test_hugo_blog_publish.py` 的 6 个中文 slug / 新建文章用例 | 未安装 `pypinyin`，回退成 `untitled` | 缺声明的依赖 | `requirements-dev.txt` 声明 `pypinyin` 后通过 |
| `test_mcp_remote.py::test_connect_streamable_http_uses_client` | `import mcp` 失败 | 缺声明的依赖，不是 `cfg=None` 放行 | 声明 `mcp` 后通过。没有改 MCP 权限 |
| `test_p2_listen_hotreload.py` 的首次加载和未变更缓存 | `_load_config()` 读 gitignore 的 `archer.toml` 后抛 FileNotFoundError | 仓库不提交私人配置 | 这两则改读 `archer.toml.example` |
| `test_smoke.py::test_config_loads` | 断言私人 `archer.toml` 存在 | 同上 | 改为解析样例，段断言保留 |
| `test_vault_sensor.py` 的窗口内焦点和缓存 | 两篇笔记同一秒时，排序不稳定，焦点落到 `Obsidian.md` | 原有夹具，不是本 PR 引入 | 把 Archer 的 mtime 明确设得更新但仍在窗口内 |

### After 的实测

隔离前缀只安装 `requirements.txt` 和 pytest，`PYTHONNOUSERSITE=1`，确认导不进 `pytesseract`：

- `test_skills_load`、`test_skills_tools_format`、`test_config_loads`、`test_optional_skill_imports.py`：5 passed。
- `payload_get("/skills")`：200。`image_ocr`、`pdf_reader`、`rss_reader` 仍在注册结果里。

同一前缀再安装 `requirements-dev.txt` 后，上一轮 17 项重跑：14 passed，剩下上面 3 项。

有上限全量，仍不是全绿：

`PYTHONNOUSERSITE=1 PYTHONPATH=/tmp/archer-repro-pkgs python3 -m pytest -m "not journey" --timeout=20 --timeout-method=signal --override-ini addopts= -q --tb=line`

46.53s 结束。2118 passed，3 failed，2 skipped。没有测试被 20 秒上限杀掉。3 个失败就是行数闸门和两条 Hugo 直发。没有安装 `requirements-skills.txt`。

### 仍要人工决定

1. Hugo 直发两条测试和当前动作中介路径不一致。要不要改测试去断言确认卡，还是恢复直发，需要单独看授权，不能在这一批放宽。
2. `_routes.py` 行数闸门。文件在本机未推送的 21 个路径里。
3. 可选技能后端要不要装进日常环境。声明已分开，不代表本机已经安装。
4. 没有和 `6c0f907` 做合并验证，没有安装或发版。

## 2026-11-18 第四批：Hugo 发布确认

远端 foundation 仍是 `4673f9a`。PR #8 仍打开，head 在本批之前是 `8d185a6`，没有别人的新提交。该 PR 的 Checks API 记录为 0：现有 workflow 只在 `main` / `master` 的 pull request 上触发，foundation 基线不会跑这套 CI。

### 根因

两条失败不是策略回落。聊天路径已经走到 Action Mediator，并把明确的「部署/上传到枫弋札记」判成 `AUTO_EXECUTE`。动作若被标成 `deploy`，而 posts 目录里没有对应旧文，重新部署和已有文章捷径都返回空，接着掉进会调用模型的 agent。这里没有模型，于是只有 `failureHint` / `error`，没有 `hugo_blog` 事件。测试还把 `_run_hugo_publish_workflow` 换成直接成功，但这条路径根本没调用它。路径提取也只认 `/Users/...md`，隔离环境里的绝对路径被丢掉。

### 改动

发布和重新部署进入 `_hugo_confirmation_result` 时不再直接执行，改为现有的确认卡：`requiresApproval`，草稿写入审批队列。`deploy` 没有旧文可接时，改走同一条发布确认，不再掉进 agent。Markdown 路径匹配放宽到一般绝对路径，仍不读用户真实博客目录。确认前若调用发布函数，测试会失败。

确认后的执行走现有 `_tool_approval`。测试把 `execute_tool_request` 换成不访问网络的夹具。同一 `eventId` 再确认会复用，不会第二次执行。拒绝，或确认一个不存在的卡片，都是 `executed: false`。

没有改明确发布在 mediator 里的 `AUTO_EXECUTE` 分类，也没有改「带附件说重新部署」那条已有捷径：它仍会在夹具博客目录里写文件并调用被替换的 runtime。那是另一条产品路径，本批不放宽，也不把它改成新渠道。

### 实测

`python3 -m pytest -m "not journey" --timeout=20 --timeout-method=signal --override-ini addopts=`，环境是已声明的 `requirements-dev.txt` 隔离前缀。

51.74s。2120 passed，1 failed，2 skipped。没有测试被 20 秒上限杀掉。唯一失败仍是 `test_god_files_cannot_grow_beyond_part10_gate0_baseline`：`terminal/api/_routes.py` 633 行，基线 629。没有改这个文件，也没有提高阈值。

### 仍要单独决定

1. 带附件的「重新部署」捷径仍会在确认前写入夹具中的 posts 文件并执行 deploy。要不要也收成确认卡，是产品决定。
2. `_routes.py` 行数闸门。
3. 没有和本机 `6c0f907` 做合并验证。

## 2026-11-18 第五批：附件重新部署确认，以及 foundation PR 的 CI 触发

用户 17:14 要求继续。推送前核对：本分支与 `origin/cursor/skill-catalog-contract-783b` 都在 `b7dd431`，foundation 仍是 `4673f9af665cc1057d690380253a44f613dfedd6`。这两条远端没有未取回的新提交。工作区在改动前是干净的。没有覆盖本机未推送的 `6c0f907` 和那 21 个路径，也没有改 `terminal/api/_routes.py`。

### 附件入口覆盖边界

查过的确定性入口：

- `_try_direct_hugo_redeploy_with_attachment`：这是本批要收的捷径。匹配到已有文章后，以前会 `write_text` 再 `runtime_invoke` deploy。现在只返回现有 `_hugo_confirmation_result`。草稿保留 `action=edit`、`filename`、`title`、`body`、`sourcePath`，并带 `deployAfter: true`。确认前不写目标文件，也不调用发布 runtime。
- `_try_direct_hugo_publish`：上一批已经是确认卡。附件 Markdown 进草稿参数，确认前不写 posts。
- `_try_direct_hugo_deploy_existing`：只生成 deploy 确认卡，不改文章正文。
- `_try_direct_hugo_delete`：只生成 delete_and_deploy 确认卡，确认前不移动文件。
- `iter_hugo_turn_events` 在 deploy/redeploy 授权下的顺序仍是：附件重新部署、已有文章 deploy、发布确认，三条都空才进 agent。附件重新部署一旦匹配，就不会掉进 agent。

agent 兜底 `_run_hugo_agent_turn` 没有改。redeploy 授权下它只允许 list/read/deploy。`hugo_blog` 除 list/read/doctor 以外，策略仍是 CONFIRM，所以 edit 和 deploy 在 agent 里也会停在确认卡，不会直接调用 runtime。list/read 仍是 ALLOW，它们不写 posts、也不部署。没有改 Action Mediator 的动作分类，明确的当前轮发布仍可能被标成 `AUTO_EXECUTE`，但那条工作流现在停在确认卡。没有改 code_edit、memory_save、npm_run、installer、browser_automation 的策略。

同意之后走现有 `_tool_approval`。`hugo_blog` edit 写入正文并保留 frontmatter，然后 `apply_approval_followup` 看到 `deployAfter` 才调用一次 `_run_hugo_deploy_followup`。同一个 `eventId` 再同意会复用缓存。已执行参数的同一指纹再同意也不会再执行。拒绝、不存在的卡片不执行。`decision` 不是 approved/denied 时在执行前抛出 ValueError。目标文件缺失时 `executed` 为 false，输出以「文件不存在」开头，并且不调用 deploy。

共享 follow-up 的异常分支没有改：部署函数若抛异常，输出会追加「部署失败」，但 `executed` 仍为 true。这是新建文章后自动部署共用的行为。本批不改它，避免把那条成功语义一起改掉。写入失败本身已经是 `executed: false`。

技能加载器用文件路径另建模块，和 `import skills.hugo_blog` 不是同一个模块对象。测试同时替换这两处的博客目录和命令。夹具是临时目录。`_run_command` 和 `_verify_url` 是假的，不访问网络，不读博客凭证。本仓库没有私人 `archer.toml`。

### CI 触发

`.github/workflows/pr.yml` 的 `pull_request.branches` 和 `push.branches` 都加上 `codex/foundation-20261001`，原来的 `main` / `master` 保留。

`pull_request.branches` 匹配的是 PR 的 base，不是 head。因此 base 为 foundation 的 PR 会触发，不要求 head 分支名叫 foundation，也没有把 `cursor/` 写进过滤条件。`push.branches` 匹配的是被推送的 ref。推送到 `cursor/skill-catalog-contract-783b` 本身不会因为 head 名字命中 push 过滤；这个 PR 靠 pull_request 的 base 过滤。

workflow 级权限是 `contents: read`。没有使用 `pull_request_target`，没有新增 secrets，没有加部署或发布 job。Python 仍安装 `requirements-dev.txt`。Desktop 仍是 Node 24。架构行数测试和安全相关测试仍在 python-tests 列表里。ruff 和 mypy 原来的 `continue-on-error` 没有扩大。`nightly.yml` 使用 secrets 和 macos runner，本批没有改它。

`pull_request` 使用 PR 合并提交上的 workflow 文件。本文件在默认分支 `main` 上的旧副本仍只列了 main/master。推送后要读实际 Checks，不能把「过滤条件已改」说成 CI 已经跑绿。

### 实测

隔离环境：`PYTHONNOUSERSITE=1`，`PYTHONPATH=/tmp/archer-repro-pkgs`，依赖来自已声明的 `requirements-dev.txt`。没有私人 `archer.toml`。

针对性：`tests/test_hugo_blog_publish.py`、`tests/test_hugo_publish_interaction.py`、`tests/test_tool_stage.py`、`tests/test_desktop_api.py`、`tests/test_architecture_boundaries.py`，加 `--timeout=20 --timeout-method=signal`。3.84s。227 passed，1 failed。失败只有 `_routes.py` 行数闸门。

非 journey 全量：`python3 -m pytest -m "not journey" --timeout=20 --timeout-method=signal --override-ini addopts=`。49.67s。2121 passed，1 failed，2 skipped。没有测试被 20 秒上限杀掉。唯一失败仍是 `test_god_files_cannot_grow_beyond_part10_gate0_baseline`：`terminal/api/_routes.py` 633 行，基线 629。`core/policy.py` 仍是 730。没有提高阈值，没有删除闸门，没有按文件豁免。这是既有基线债。本批没有改 Desktop 的 TypeScript，所以没有另跑 types/build。

### 基线与未做的事

没有合并，没有安装，没有发版。没有改 Runtime gate、Part 8、真人审批。没有制造反馈或 J8。没有上传私人数据。没有和本机 `6c0f907` 做合并验证，不能说本机兼容已经验证。PR #7 保持不合并且没有复制它的补丁。PR #6 人格暂停，没有继续。

### CI 状态

推送 `a1bd23762d77a2eac8045345a6c545c3707139fe` 后，Checks API 有 5 个 run，不是 0。`pull_request` 已触发，head 是 `cursor/skill-catalog-contract-783b`，base 是 `codex/foundation-20261001`。这不是「只有 head 名字匹配才跑」。

总 run：https://github.com/Yivxer/Archer/actions/runs/44276246848

- Python 架构测试子集：failure。日志里唯一失败是 `test_god_files_cannot_grow_beyond_part10_gate0_baseline`，`terminal/api/_routes.py` 633 行，基线 629。这是既有基线债，本批没有改这个文件。https://github.com/Yivxer/Archer/actions/runs/44276246848/job/134705017206
- Ruff Lint：failure。这个 job 本来就是 `continue-on-error`，本批没有把它改成吞掉失败，也没有把它当成通过。https://github.com/Yivxer/Archer/actions/runs/44276246848/job/134705017310
- Mypy：success。job 仍是非阻塞。https://github.com/Yivxer/Archer/actions/runs/44276246848/job/134705016715
- TypeScript 单元测试：success。https://github.com/Yivxer/Archer/actions/runs/44276246848/job/134705017175
- TypeScript 类型检查 + 构建：success。https://github.com/Yivxer/Archer/actions/runs/44276246848/job/134705017269

不能说 CI 全绿。必需的 Python job 是红的，原因是上述行数闸门。`permissions: contents: read` 没有让 checkout、Python 安装或 Node 24 安装失败。

