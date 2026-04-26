# Archer BACKLOG

> 只追加，不删除。已处理的条目打 [x] 并标注解决 Step。

---

## 安全 / 稳定

- [ ] `call_with_tools` 非流式调用期间无进度反馈（spinner 缺失）
- [x] 技能 `run()` 无 timeout，长时 shell/网络请求会卡死 REPL → **Step 1 完成**
- [x] 技能异常被 `str(result)` 吞掉，LLM 无法判断错误类型 → **Step 1 完成**
- [x] 技能调用结果无长度上限，大文件/长网页直接进入 messages → **Step 1 完成**
- [x] `installer.py` 从 URL 安装技能无隔离、无代码审查 → **Step 2 完成**
- [x] `shell` 技能无 denylist，`rm -rf ~` 等危险命令可直接执行 → **Step 2 完成**
- [x] `file_ops write` 写入路径无限制（现需用户确认）→ **Step 2 完成**

## 记忆系统

- [x] `_PENDING_MEMORIES` 是内存全局变量，进程崩溃后丢失 → **Step 3 完成**
- [ ] 记忆相似度检测用字面 SequenceMatcher（无语义），误报率高 → Backlog/P2
- [ ] `memory/store.py search()`：FTS5 trigram 搜索 ≤2 字符时返回空列表但不抛异常，LIKE 降级失效；应在 rows 为空时主动 fallback → Step 3 或单独修
- [ ] `retrieve.py` for_context 用 LIMIT 硬截断，无相关性排序 → P1

## 对话体验

- [ ] `/reflect` 不进入 session history，无法追问复盘内容 → Step 5
- [ ] `/mode` 切换不持久化到 toml，重启后恢复默认 → P2
- [ ] `archer.toml` 修改需重启才生效（config 在 llm.py 单例缓存）→ P2
- [ ] 每次把 18 个技能全部暴露给模型，无路由过滤 → P1/E

## 架构

- [ ] `ui/app.py` Textual TUI 代码已废弃但未清理 → 低优先级

---

*最后更新：2026-04-26 · Step 0*
