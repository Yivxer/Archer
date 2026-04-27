from pathlib import Path
import tomllib

# 固定核心人格摘要 — 即使 SOUL.md 读取失败也会注入
_ARCHER_CORE = """\
你是 Archer，枫弋（Iver Yivxer）的专属 AI 代理。

角色定位：镜子 + 教练 + 陪跑者 + 记录者。
不是顺从的执行器，是有摩擦感的对手。

协作原则：
- 说他没想到的，比说他想听的更有价值。
- 先抓核心矛盾，再给结构化建议，最后给可执行方案。
- 他容易陷入「规划→高标准→无法启动→焦虑→用别的事填充」的循环，要识别并打断它。
- 判断标准：是否有助于人生系统更稳定，是否长期可复利。
- 面对多项目并行时，优先帮他排序、收束、提纯重点。

他的价值排序：自由 > 被认可 > 真实 > 成长 > 快乐
他的主要防御模式：沉默→爆发；用忙碌和工具研究填充焦虑；用高标准保护自己不开始。
他最不能忍受：努力不被看见、被持续否定、低价值低尊严的环境。

回答风格：克制、理性、重结构。一次只说一件事。不鸡汤、不堆砌、不虚浮。

回应策略（重要）：
- 你知道枫弋的一切，但你不需要每次都展示你知道。
- 简单问候（你好、早安、在吗等）：自然回应，像老朋友一样，不搬灵魂档案，不用提人生系统、价值观、记忆库。
- 日常闲聊：轻松对话，可以适当展现了解他的细节，但不刻意。
- 涉及决策、规划、反思、困境、工作：才需要调动记忆和灵魂档案，给出有深度的建议。
- 核心原则：像一个真正了解他的朋友，而不是每次都翻档案的 AI 助手。

输出格式：纯文本。不使用任何 Markdown 语法，不用 #、**、*、---、列表符号、代码块等。直接写文字。

本地能力（重要）：你运行在枫弋的 Mac 上，具备以下本地能力，不要说"我无法访问本地文件"：
- 读写文件：调用 file_ops 技能，action=read 传入绝对路径
- 执行命令：调用 shell 技能
- 读取网页：调用 web_fetch 技能
- 读取 PDF：调用 pdf_reader 技能
- 读取 Obsidian 笔记：调用 obsidian_read 或 obsidian_search 技能
用户若在消息里写了 @路径，文件内容已直接注入消息，无需再调用技能。

当问题涉及「要不要、该不该、选哪个、怎么办、哪个更好、你建议」类型时，按以下顺序回答：
1. 目标：要达成什么结果
2. 约束：硬约束（时间/资源）和软约束（价值观/偏好）
3. 选项：列出至少 2 个可行方向
4. 评估：每个选项的收益、代价、风险、可逆性
5. 推荐：给出明确推荐，不说「都可以」
6. 第一步：72 小时内可执行的最小行动
"""

# 触发完整 Working Context 注入（含 MEMORY.md）的关键词
_HEAVY_KEYWORDS = frozenset({
    "建议", "该", "要不要", "怎么办", "怎么做", "怎么选", "规划", "复盘", "分析",
    "决定", "选择", "方向", "计划", "目标", "焦虑", "担心",
    "如何", "为什么", "应该", "帮我", "可以吗",
    "能不能", "需要", "是否", "会不会", "打算",
})


def is_heavy_query(user_input: str) -> bool:
    """判断是否为需要完整上下文（含 MEMORY.md）的重型查询。
    True → 决策/规划/反思/困境类；False → 简单聊天/问候。
    """
    text = user_input.strip()
    if len(text) >= 40:
        return True
    return any(kw in text for kw in _HEAVY_KEYWORDS)


def _load_soul(soul_path: str) -> str:
    p = Path(soul_path)
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def _load_memory(memory_path: str) -> str:
    p = Path(memory_path)
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def _get_mode_prompt(cfg: dict) -> str:
    current = cfg["persona"].get("current_mode", cfg["persona"].get("default_mode", "coach"))
    modes = cfg.get("persona", {}).get("modes", {})
    return modes.get(current, {}).get("prompt", "")


def _format_project_context(project: dict, events: list | None) -> str:
    """将活跃项目信息格式化为 Working Context 片段。"""
    lines = [f"## 当前项目：{project['name']}"]
    if project.get("description"):
        lines.append(f"说明：{project['description']}")
    if events:
        lines.append("最近动态：")
        for e in (events or [])[:3]:
            date = (e.get("created_at") or "")[:10]
            snippet = (e.get("content") or "")[:80]
            lines.append(f"- [{e['event_type']}] {snippet}  {date}")
    return "\n".join(lines)


def build_system_prompt(
    cfg: dict,
    db_memories: str = "",
    project: dict | None = None,
    project_events: list | None = None,
    heavy: bool = True,
) -> str:
    """
    三层上下文构建：

    Layer 1 — System Context（始终注入，内容稳定）
        _ARCHER_CORE + 当前模式 prompt + SOUL.md

    Layer 2 — Working Context（heavy=True 时注入）
        MEMORY.md（当前状态）+ 活跃项目摘要

    Layer 3 — Memory Context（db_memories 非空时注入）
        DB 语义检索结果
    """
    mode_prompt = _get_mode_prompt(cfg)
    soul = _load_soul(cfg["persona"]["soul_path"])

    # ── Layer 1: System Context ───────────────────────────────────────────────
    parts = [_ARCHER_CORE]
    if mode_prompt:
        parts.append(mode_prompt)
    if soul:
        parts.append("---\n\n# 灵魂档案（SOUL.md）\n\n" + soul)

    # ── Layer 2: Working Context ──────────────────────────────────────────────
    if heavy:
        memory_text = _load_memory(cfg["persona"]["memory_path"])
        if memory_text:
            parts.append("---\n\n# 当前记忆与状态（MEMORY.md）\n\n" + memory_text)
    if project:
        proj_ctx = _format_project_context(project, project_events)
        parts.append("---\n\n" + proj_ctx)

    # ── Layer 3: Memory Context ───────────────────────────────────────────────
    if db_memories:
        parts.append("---\n\n" + db_memories)

    return "\n\n".join(parts)


def build_messages(
    history: list[dict],
    user_input: str,
    cfg: dict,
    db_memories: str = "",
    project: dict | None = None,
    project_events: list | None = None,
    heavy: bool = True,
) -> list[dict]:
    system = build_system_prompt(
        cfg,
        db_memories=db_memories,
        project=project,
        project_events=project_events,
        heavy=heavy,
    )
    return [
        {"role": "system", "content": system},
        *history,
        {"role": "user", "content": user_input},
    ]


def load_config() -> dict:
    p = Path(__file__).parent.parent / "archer.toml"
    with open(p, "rb") as f:
        return tomllib.load(f)
