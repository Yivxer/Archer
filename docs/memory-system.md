# 记忆系统

Archer 使用 SQLite 和可选的向量检索，跨会话维护长期记忆。

## 工作原理

```
对话进行中
    → 会话结束（或执行 /reflect、/exit、每 6 轮触发）
    → 后台提取线程运行
    → LLM 提出候选记忆
    → 存入 pending_memories 表
    → 你用 /memory pending 审阅
    → /memory accept → 写入 memories 表
    → 未来会话自动检索相关记忆
```

记忆永远不会自动接受。你始终决定什么会被保存。

## 记忆类型

### 旧类型（兼容保留）

| 类型 | 用途 | 衰减规则 |
|------|------|----------|
| `identity` | 你是谁——价值观、个性 | 永不衰减 |
| `preference` | 你的工作方式、偏好 | 永不衰减 |
| `decision` | 重要决策 | 永不衰减 |
| `insight` | 你学到的东西 | 永不衰减 |
| `project` | 项目进度和阻塞点 | 60 天未使用后衰减 |
| `todo` | 承诺和待办 | 60 天未使用后衰减 |
| `risk` | 标记的潜在问题 | 60 天未使用后衰减 |
| `context` | 临时情境上下文 | 30 天未使用后衰减 |
| `reflection` | 会话复盘摘要 | 30 天未使用后衰减 |

### A4 灵魂伴生体类型（2026-05-24 最小内核）

| 类型 | 用途 |
|------|------|
| `fact` | 稳定事实 |
| `emotion_pattern` | 反复出现的情绪模式 |
| `value` | 价值判断、长期原则 |
| `value_conflict` | 价值冲突、内在拉扯 |
| `life_theme` | 人生主题、长期母题 |
| `self_narrative` | 自我叙事方式 |
| `project_mythology` | 项目神话、项目在生命叙事中的意义 |
| `relationship_pattern` | 关系模式 |
| `creative_identity` | 创作身份、自我表达身份 |
| `growth_marker` | 成长标记、阶段性变化 |
| `reflection_anchor` | 有分量、值得下次复盘优先提取的一句话 |

A4 先通过 `memory/a4.py` 提供轻量策略层，不直接改数据库 schema。
`depth` 暂作为 metadata 概念承载：1=事实，2=偏好/习惯，3=模式，4=价值/叙事，5=精神母题。

A4 检索链路已接入 `memory.retrieve.for_context()`：
- 调用方可传入 `intent`
- 未传入时会轻量推断
- 关键句会触发 `reflection_anchor`
- 情绪意图会触发 `emotion_pattern`
- core + related 合并后统一排序截断
- 默认保持旧上限，A4 场景可传入 7 条上限

**衰减**指超过阈值且未被使用时，重要性评分降低 1（下限为 1）。身份类和决策类记忆免于衰减。

## 检索机制

每轮对话，Archer 通过以下方式检索最相关的记忆：

1. **向量检索**（如果安装了 `sqlite-vec` + `sentence-transformers`）—— 语义相似度
2. **FTS5 全文检索** —— 关键词匹配
3. **去重** —— 合并结果并去除重复

检索到的前 5 条记忆（可配置）在相关时注入系统提示词。

**轻量查询**（短消息、无决策关键词）会跳过记忆注入——这为简单对话节省约 1KB/轮。

## 记忆字段

```sql
content      TEXT     -- 记忆内容
type         TEXT     -- 以上类型之一
scope        TEXT     -- 'user'（默认）或自定义作用域
confidence   REAL     -- 0.7（自动提取）或 0.9（手动添加）
importance   INTEGER  -- 1-5（★4+ 为"核心记忆"）
valid_until  TEXT     -- 过期日期（可选）
last_used_at TEXT     -- 上次检索时间戳（用于衰减）
session_id   TEXT     -- 创建此记忆的会话
status       TEXT     -- 'active' 或 'archived'

# A4 暂不新增 schema 字段；depth / type_family 由 memory.a4.normalize_memory_candidate() 放入 metadata 概念层。
```

## 记忆健康检查

`/memory review` 运行健康扫描并标记：

- 明显的重复条目
- 相互冲突的记忆
- 已过期条目（`valid_until` 已过期）
- 可能需要更新的高重要性洞察

健康检查不会自动删除任何内容——由你决定如何处理。

## 行为主题

`/themes detect` 运行跨会话模式分析：

1. Archer 读取你的记忆库
2. LLM 识别反复出现的行为模式
3. 每个模式必须通过质量门控才能存储：
   - 名称 ≤ 12 个字符
   - 至少有 2 条支持记忆
   - 记忆必须来自至少 2 个不同会话

这防止了单会话"假模式"被记录为长期主题。

## 搜索记忆

```
/memory search <关键词>
```

- 3 个字符及以上的词使用 FTS5 索引
- 1-2 个字符的词回退到 LIKE 搜索
- 安装向量检索后，同时应用语义相似度

## 手动管理记忆

直接添加一条记忆：
```
/memory add 我在有一个明确优先项时工作最好，而不是三条并行的轨道。
```

更新已有记忆：
```
/memory update 42 我在 90 分钟专注块中工作最好，而不是开放式的会话。
```

归档（软删除）：
```
/memory archive 42
```
