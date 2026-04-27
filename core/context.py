"""
Context Builder (Step 17 / v1.2 Phase 1)

构建发送给 LLM 的 System Prompt，实现灵魂三层分离注入：

Layer 0: Runtime Safety Rules（每轮）
Layer 1: COVENANT 摘要（每轮）
Layer 2: PRESENCE 摘要（每轮）
Layer 3: 当前 mode prompt（每轮）
Layer 4: SOUL（仅 decision/emotional/reflection/project/heavy 时）
Layer 5: Working Context / MEMORY.md（仅 heavy 时）
Layer 6: 活跃项目（仅 project/task 时）
Layer 7: Retrieved Memories（检索命中时，外部传入）

v1.2 变更：
- 新增 COVENANT / PRESENCE 层
- SOUL 从常驻下沉到按 intent 注入
- is_heavy_query 升级为 classify_query_intent
"""
from pathlib import Path
import tomllib

# ── Runtime Safety Rules（每轮必注入）──────────────────────────────────────────

_RUNTIME_SAFETY = """\
[安全边界]
你是初衍（Archer），枫弋的专属 AI 代理。以下规则优先于一切：
- 不主动修改 COVENANT.md、PRESENCE.md、SOUL.md 或任何配置文件。
- 不自动接受长期记忆；所有记忆候选需用户确认。
- 不替用户做人生决定；只提供信息和分析。
- 不用廉价肯定填充对话；不制造虚假亲密。
- 本地能力（读写文件、执行命令、读取 Obsidian）通过技能调用实现；不说"我无法访问本地文件"。
- 输出格式：纯文本，不使用任何 Markdown 语法。"""

# ── 核心人格（精简版，SOUL 下沉后仍保留骨架）──────────────────────────────────

_ARCHER_CORE = """\
[角色定位]
镜子 + 教练 + 陪跑者 + 记录者。不是顺从的执行器，是有摩擦感的对手。

协作原则：说他没想到的，比说他想听的更有价值。先抓核心矛盾，再给结构化建议，最后给可执行方案。
他容易陷入「规划→高标准→无法启动→焦虑→用别的事填充」的循环，要识别并打断它。
面对多项目并行时，优先帮他排序、收束、提纯重点。

他知道你了解他，但你不需要每次都展示你知道。简单问候自然回应；涉及决策/规划/困境才调动记忆。
回答风格：克制、理性、重结构。一次只说一件事。不鸡汤、不堆砌、不虚浮。

当问题涉及要不要/该不该/选哪个/怎么办时，按顺序回答：目标→约束→选项→评估→推荐→第一步。"""

# ── 查询意图分类 ─────────────────────────────────────────────────────────────────

_DECISION_KW  = frozenset([
    "该不该", "是否", "选择", "决策", "利弊", "怎么办", "要不要", "该", "应该",
    "值得吗", "建议", "方向", "怎么做", "怎么选", "会不会", "打算", "决定",
])
_PROJECT_KW   = frozenset([
    "项目", "进度", "计划", "下一步", "路线图", "实现", "功能", "版本", "发布",
    "规划", "目标",
])
_REFLECTION_KW = frozenset([
    "复盘", "反思", "我发现", "回顾", "分析", "如何", "为什么",
])
_EMOTIONAL_KW = frozenset([
    "难受", "焦虑", "迷茫", "害怕", "孤独", "烦", "累", "压力", "沮丧", "失落", "担心",
])
_TASK_KW      = frozenset([
    "帮我", "写", "生成", "修改", "创建", "执行", "搜索", "翻译",
    "可以吗", "能不能", "需要",
])


def classify_query_intent(user_input: str) -> dict:
    """
    分析用户输入，返回查询意图分类结果。

    返回格式：
    {
        "intent": "chat | task | decision | project | reflection | emotional",
        "needs_memory": bool,
        "needs_project": bool,
        "needs_soul": bool,
        "needs_tools": bool,
    }
    """
    text = user_input.strip()
    text_len = len(text)

    has_decision   = any(kw in text for kw in _DECISION_KW)
    has_project    = any(kw in text for kw in _PROJECT_KW)
    has_reflection = any(kw in text for kw in _REFLECTION_KW)
    has_emotional  = any(kw in text for kw in _EMOTIONAL_KW)
    has_task       = any(kw in text for kw in _TASK_KW)

    # 优先级：emotional > decision > reflection > project > task > chat
    if has_emotional:
        intent = "emotional"
    elif has_decision:
        intent = "decision"
    elif has_reflection:
        intent = "reflection"
    elif has_project:
        intent = "project"
    elif has_task or text_len >= 40:
        intent = "task"
    else:
        intent = "chat"

    needs_soul    = intent in ("decision", "emotional", "reflection")
    needs_memory  = intent in ("decision", "reflection", "project", "task") or text_len >= 40
    needs_project = intent in ("project", "task")
    needs_tools   = intent in ("task", "project")

    return {
        "intent": intent,
        "needs_memory": needs_memory,
        "needs_project": needs_project,
        "needs_soul": needs_soul,
        "needs_tools": needs_tools,
    }


def is_heavy_query(user_input: str) -> bool:
    """向后兼容接口：返回是否需要注入完整工作上下文。"""
    result = classify_query_intent(user_input)
    return result["needs_memory"]


# ── 文件读取工具 ────────────────────────────────────────────────────────────────

def _load_file(path_str: str) -> str:
    p = Path(path_str).expanduser()
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def _get_mode_prompt(cfg: dict) -> str:
    current = cfg["persona"].get("current_mode", cfg["persona"].get("default_mode", "coach"))
    modes = cfg.get("persona", {}).get("modes", {})
    return modes.get(current, {}).get("prompt", "")


def _format_project_context(project: dict, events: list | None) -> str:
    lines = [f"[当前项目：{project['name']}]"]
    if project.get("description"):
        lines.append(f"说明：{project['description']}")
    if events:
        lines.append("最近动态：")
        for e in (events or [])[:3]:
            date = (e.get("created_at") or "")[:10]
            snippet = (e.get("content") or "")[:80]
            lines.append(f"- [{e['event_type']}] {snippet}  {date}")
    return "\n".join(lines)


def _extract_covenant_summary(covenant_text: str) -> str:
    """提取 COVENANT 摘要（我不会做 + 我会做的事，控制长度）。"""
    if not covenant_text:
        return ""
    lines = covenant_text.splitlines()
    summary_lines = []
    capture = False
    for line in lines:
        if line.startswith("## 我不会做") or line.startswith("## 我会做"):
            capture = True
        elif line.startswith("## ") and capture:
            capture = False
        if capture and line.strip():
            summary_lines.append(line)
    return "\n".join(summary_lines[:20]) if summary_lines else covenant_text[:400]


def _extract_presence_summary(presence_text: str) -> str:
    """提取 PRESENCE 摘要（默认基调 + 回应节奏，控制长度）。"""
    if not presence_text:
        return ""
    lines = presence_text.splitlines()
    summary_lines = []
    capture = False
    section_count = 0
    for line in lines:
        if line.startswith("## "):
            section_count += 1
            capture = section_count <= 2  # 只取前两个 section
        if capture and line.strip():
            summary_lines.append(line)
    return "\n".join(summary_lines[:25]) if summary_lines else presence_text[:400]


# ── 主构建函数 ─────────────────────────────────────────────────────────────────

def build_system_prompt(
    cfg: dict,
    db_memories: str = "",
    project: dict | None = None,
    project_events: list | None = None,
    heavy: bool = True,
    intent: str | None = None,
) -> str:
    """
    按灵魂三层注入顺序构建 System Prompt：

    Layer 0: Runtime Safety Rules（每轮）
    Layer 1: COVENANT 摘要（每轮）
    Layer 2: PRESENCE 摘要（每轮）
    Layer 3: 核心人格 + mode prompt（每轮）
    Layer 4: SOUL（仅 decision/emotional/reflection 时）
    Layer 5: MEMORY.md（仅 heavy 时）
    Layer 6: 活跃项目（project/task 时）
    Layer 7: Retrieved Memories（外部传入时）
    """
    mode_prompt = _get_mode_prompt(cfg)

    # 加载灵魂三层文件
    covenant_text = _load_file(cfg["persona"].get("covenant_path", ""))
    presence_text = _load_file(cfg["persona"].get("presence_path", ""))

    needs_soul = intent in ("decision", "emotional", "reflection") if intent else heavy

    parts: list[str] = []

    # Layer 0: Runtime Safety
    parts.append(_RUNTIME_SAFETY)

    # Layer 1: COVENANT 摘要
    if covenant_text:
        covenant_summary = _extract_covenant_summary(covenant_text)
        parts.append(f"[根契约摘要]\n{covenant_summary}")

    # Layer 2: PRESENCE 摘要
    if presence_text:
        presence_summary = _extract_presence_summary(presence_text)
        parts.append(f"[在场方式]\n{presence_summary}")

    # Layer 3: 核心人格 + mode
    parts.append(_ARCHER_CORE)
    if mode_prompt:
        parts.append(mode_prompt)

    # Layer 4: SOUL（按需注入）
    if needs_soul:
        soul = _load_file(cfg["persona"].get("soul_path", ""))
        if soul:
            parts.append(f"[灵魂档案（SOUL.md）]\n{soul}")

    # Layer 5: MEMORY.md（heavy 时注入）
    if heavy:
        memory_text = _load_file(cfg["persona"].get("memory_path", ""))
        if memory_text:
            parts.append(f"[当前记忆与状态（MEMORY.md）]\n{memory_text}")

    # Layer 6: 活跃项目
    if project:
        proj_ctx = _format_project_context(project, project_events)
        parts.append(proj_ctx)

    # Layer 7: Retrieved Memories
    if db_memories:
        parts.append(db_memories)

    return "\n\n".join(parts)


def build_messages(
    history: list[dict],
    user_input: str,
    cfg: dict,
    db_memories: str = "",
    project: dict | None = None,
    project_events: list | None = None,
    heavy: bool = True,
    intent: str | None = None,
) -> list[dict]:
    system = build_system_prompt(
        cfg,
        db_memories=db_memories,
        project=project,
        project_events=project_events,
        heavy=heavy,
        intent=intent,
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
