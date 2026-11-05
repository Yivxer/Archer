# 灵魂档案系统

Archer 有三层系统，用于塑造它如何理解你、如何在对话中出现。

## 三个层次

### SOUL.md — 你是谁

你的长期灵魂档案。Archer 在你寻求决策、复盘或情绪加权指导时读取这个文件。

**应该写什么：**
- 你的价值观，按优先级排列
- 核心张力——你生活中相互拉扯的一对对事物
- 防御模式——你倾向于如何回避不适
- 恢复机制——真正有效的应对方式
- 你希望如何与 AI 协作

Archer 永远不会自动覆写这个文件。变更通过 `/soul list` 提议，只有你才能接受。

### SOUL_PROFILE.json — 结构化灵魂摘要

SOUL_PROFILE 是给 prompt 使用的紧凑结构化摘要，不替代 SOUL.md，也不承载完整叙事。

字段包括：
- core_values
- recurring_fears
- creative_identity
- life_themes
- emotional_patterns
- relationship_patterns
- aesthetic_preferences
- project_mythology
- language_style
- important_questions
- current_life_stage

注入策略：
- 优先注入 1 条 current_life_stage
- 再按当前意图选择 1-2 条匹配的长期特质
- 单轮最多 7 条
- 空档案不注入
- 不每轮塞入完整 Soul Profile

### COVENANT.md — 硬性边界

根契约定义了 Archer 无论如何都会或不会做的事情。

**应该写什么：**
- 你永远不希望 Archer 执行的行为
- 你希望 Archer 坚守的正向承诺
- 如何处理沉默和缺席

这个文件在会话中不可编辑。要提议修改，用 `/covenant propose`。提案保存到历史记录——由你亲自审阅并应用。

### PRESENCE.md — Archer 如何出现

当前关系的互动风格。比 COVENANT 更灵活，比模式设置更具体。

**应该写什么：**
- 默认语气（辅导式、倾听式、挑战式）
- 回应节奏规则
- 如何处理密集或抽象的话题
- 如何处理敏感的个人话题
- 何时以及如何推动行动

要建议调整，用 `/presence suggest`。与契约提案一样，变更保存供你审阅。

---

## 注入逻辑

Archer 不会每轮都注入三个层次——对简单问题来说那会浪费 Token。

| 查询类型 | 注入 SOUL？ | 注入 MEMORY.md？ |
|----------|------------|-----------------|
| `chat`（问候、简单问题） | 否 | 否 |
| `task`（做某事） | 否 | 是 |
| `project`（项目相关） | 否 | 是 |
| `decision`（选择、建议） | **是** | 是 |
| `emotional`（情绪、身心状况） | **是** | 是 |
| `reflection`（回顾、模式分析） | **是** | 是 |

COVENANT 和 PRESENCE 摘要每轮都会注入（它们很短）。运行时安全规则始终优先注入，位于所有内容之前。

专家档案的相对顺序是固定的，不能由人格字段重排：`COVENANT → Soul → Expert overlay → Personality injection → Stance → Skill context`。常量在 `core/agent_profile.py` 的 `PROFILE_PROMPT_ORDER`；`build_system_prompt()` 把 COVENANT 和 Soul 留在原锚点，并把后四层按同一元组接到提示词尾部。人格注入只从专家的人格字段来，不能改写 `covenant_path`。

如果配置了 `persona.soul_profile_path`，Archer 会额外读取 SOUL_PROFILE.json，并按意图注入少量结构化摘要；它不会替代 SOUL.md，也不会把完整档案每轮塞进上下文。

---

## 灵魂演化

随着你使用 Archer，它可能会检测到值得添加到灵魂档案的信号：

- 身份陈述（"我意识到我……"）
- 重大决策
- 在复盘中浮现的反复模式

当它检测到一个信号时，会创建一条 `soul_proposal`。你用以下命令审阅：

```
/soul list
```

接受你认可的提案：
```
/soul accept 3
```

被接受的提案会以时间戳**追加**到 SOUL.md 末尾。原有内容永不修改。

---

## 自我批评系统

独立于灵魂演化，Archer 有一个自我批评机制，用于观察自身的行为模式。

```
/critique list
```

批评是关于 Archer 自身倾向的观察——例如，发现它在你想要简洁时解释过多。

批评的特点：
- 存储在 `self_critiques` 表中
- 由你审阅，不自动应用
- 有频率限制（自动检测每会话最多 1 条）
- 不用于自动修改代码或行为

把它当作 Archer 的自省日志，而不是行为补丁系统。

---

## 模板文件

`templates/` 目录包含所有四个文件的起点：

- `templates/SOUL.template.md`
- `templates/MEMORY.template.md`
- `templates/COVENANT.template.md`
- `templates/PRESENCE.template.md`

安装脚本将这些文件复制到 `~/.archer/`。它们是有意精简的——按照你自己的节奏填写。
