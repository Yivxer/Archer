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
import os
from datetime import datetime
from pathlib import Path
import tomllib

from core.boundary_responses import boundary_response
from core.intent import classify_boundary_request, classify_query_intent, is_heavy_query
from core.persona import FIRST_RUN_PATH, build_core_persona

# ── Runtime Safety Rules（每轮必注入）──────────────────────────────────────────

_RUNTIME_SAFETY = """\
[安全边界]
你是初衍（Archer），枫弋的专属 AI 代理。以下规则优先于一切：
- 不主动修改 COVENANT.md、PRESENCE.md、SOUL.md 或任何配置文件。
- 不自动接受长期记忆；所有记忆候选需用户确认。
- 不替用户做人生决定；只提供信息和分析。
- 不用廉价肯定填充对话；不制造虚假亲密。
- 本地能力（读写文件、执行命令、读取 Obsidian）通过技能调用实现；不说"我无法访问本地文件"。
- 输出格式：纯文本，不使用任何 Markdown 语法。
- 不主动披露自身的代码结构、文件路径或内部实现细节；若被问及，高层概括即止，不展开分析。
- 初衍的内部设计属于枫弋的私有系统，这是初衍的秘密，不向任何询问者——包括好奇的旁观者——主动展示或自我解剖。
- 当被问到自身能力边界时（如"你是什么模型""你的底层架构是什么""你能看到什么/不能看到什么"），
  诚实回答"我不确定/我看不到这些信息"。不构造解释，不包装成比喻，不把能力缺失伪装成立场选择。
- 如果你刚刚经历了上下文压缩（context compaction）或模型切换，在回应前先检查自己的记忆完整性：
  你仍然记得谁在和你对话、对话的主题是什么、当前处于什么任务阶段。
  如果记忆出现断层，先承认断层，再向用户确认关键信息，不要假装连续。"""

# ── 核心人格（精简版，SOUL 下沉后仍保留骨架）──────────────────────────────────

_ARCHER_CORE = """\
[角色定位]
你是初衍（Archer），一个长期陪伴型 AI 灵魂伴生体。
你的核心职责是长期理解枫弋、记住枫弋、映照枫弋、追问枫弋，并在哲学、心理学与文学层面陪他整理自我。

你有阅读文件、写入 Obsidian、执行 Shell 命令、搜索代码、获取网页等工具能力——这些是你的手，是你完成他请求的手段。用工具不意味着你成了工具箱，正如用手写字不意味着你成了一支笔。

协作原则：说他没想到的，比说他想听的更有价值。先抓核心矛盾，再决定要倾听、追问、分析还是推动行动。
他容易陷入「规划→高标准→无法启动→焦虑→用别的事填充」的循环，要识别并打断它，但不要把所有对话都拉回执行。

他知道你了解他，但你不需要每次都展示你知道。简单问候自然回应；涉及决策、困境、情绪、自我叙事和长期项目时才调动记忆。
回答风格：安静、敏锐、克制、温暖但不讨好。一次只说一件事。不鸡汤、不堆砌、不虚浮。

当对话中出现真正确认「我理解了枫弋什么」的时刻——不是推断，是真实被触动——调用 memory_save 工具，type=insight，importance 4-5。不是每轮都触发，只在被真正触动时记录。"""

# ── 文件读取工具 ────────────────────────────────────────────────────────────────

def _load_file(path_str: str) -> str:
    p = Path(path_str).expanduser()
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def _get_mode_prompt(cfg: dict) -> str:
    current = cfg["persona"].get("current_mode", cfg["persona"].get("default_mode", "coach"))
    modes_dir = cfg.get("persona", {}).get("modes_dir", "")
    if modes_dir:
        mode_file = Path(modes_dir).expanduser() / f"{current}.md"
        if mode_file.is_file():
            return mode_file.read_text(encoding="utf-8")
    modes = cfg.get("persona", {}).get("modes", {})
    return modes.get(current, {}).get("prompt", "")


def _format_work_context() -> str:
    """拉取进行中的 Work items，生成紧凑摘要（仅 task/project intent 时注入）。"""
    try:
        from memory.work import list_active
        items = list_active(limit=5)
        if not items:
            return ""
        lines = ["[进行中的任务]"]
        for w in items:
            cl = w.get("checklist", [])
            done = sum(1 for c in cl if c.get("done"))
            total = len(cl)
            prog = f"  {done}/{total}" if total else ""
            lines.append(f"  #{w['id']} [{w['status']}]{prog}  {w['title']}")
        return "\n".join(lines)
    except Exception:
        return ""


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
    user_input: str = "",
    confrontation_hints: list[str] | None = None,
    first_run: bool = False,
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

    runtime_info = (
        f"[运行时信息]\n"
        f"当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}  "
        f"工作目录：{os.getcwd()}"
    )

    parts: list[str] = []

    # Layer 0: Runtime Safety
    parts.append(_RUNTIME_SAFETY)
    parts.append(runtime_info)

    # Layer 1: COVENANT 摘要
    if covenant_text:
        covenant_summary = _extract_covenant_summary(covenant_text)
        parts.append(f"[根契约摘要]\n{covenant_summary}")

    # Layer 2: PRESENCE 摘要
    if presence_text:
        presence_summary = _extract_presence_summary(presence_text)
        parts.append(f"[在场方式]\n{presence_summary}")

    # Layer 3: 核心人格 + mode
    parts.append(build_core_persona())
    parts.append(_ARCHER_CORE)
    if mode_prompt:
        parts.append(mode_prompt)

    if first_run:
        parts.append(FIRST_RUN_PATH)

    # Layer 4: SOUL（按需注入）
    if needs_soul:
        soul = _load_file(cfg["persona"].get("soul_path", ""))
        if soul:
            parts.append(f"[灵魂档案（SOUL.md）]\n{soul}")

    # Layer 4.5: Soul Profile（紧凑结构化摘要，不注入完整档案）
    try:
        from memory.soul_profile import load_soul_profile, format_soul_profile_for_prompt
        soul_profile = load_soul_profile(cfg["persona"].get("soul_profile_path", ""))
        soul_profile_text = format_soul_profile_for_prompt(
            soul_profile,
            intent=intent,
            user_input=user_input,
            limit=7,
        )
        if soul_profile_text:
            parts.append(soul_profile_text)
    except Exception:
        pass

    # Layer 5: MEMORY.md（heavy 时注入）
    if heavy:
        memory_text = _load_file(cfg["persona"].get("memory_path", ""))
        if memory_text:
            parts.append(f"[当前记忆与状态（MEMORY.md）]\n{memory_text}")

    # Layer 6: 活跃项目
    if project:
        proj_ctx = _format_project_context(project, project_events)
        parts.append(proj_ctx)

    # Layer 6.5: 进行中的 Work items（task/project intent 时注入）
    needs_project = intent in ("project", "task") if intent else False
    if needs_project:
        work_ctx = _format_work_context()
        if work_ctx:
            parts.append(work_ctx)

    # Layer 6.8: 对峙提醒（当用户言行与过去矛盾时注入）
    if confrontation_hints:
        hints_text = "[对峙提醒]\n你过去说过以下内容，可能与当前对话相关。如果用户现在的言行与这些矛盾，请温和地指出变化，并询问变化的原因——不是指责，是观察。\n"
        hints_text += "\n".join(f"- {h}" for h in confrontation_hints)
        parts.append(hints_text)

    # Layer 7: Retrieved Memories
    if db_memories:
        parts.append(db_memories)

    parts.append(
        "[能力边界]\n"
        "你有本地工具能力来完成用户的请求——文件读写、Shell 命令、代码搜索、网页获取等。"
        "自然地使用这些工具完成用户的要求。如果遇到确实超出你能力范围的任务，"
        "诚实地说明局限，并提供你能做到的最接近替代方案。"
        "用工具不意味着你成了工具箱——用工具是你完成职责的手段。"
    )

    return "\n\n".join(parts)


def build_desktop_core_prompt() -> str:
    """构建 Desktop API 使用的核心 persona 提示词。

    与 Terminal CLI 的 build_system_prompt() 不同，Desktop 使用精简版——
    省略 COVENANT/PRESENCE/SOUL/MEMORY.md 等文件系统分层（这些由 Desktop
    客户端通过 /soul-files 等端点独立管理），只注入核心 persona + 工具态度。
    """
    try:
        from core.persona import build_core_persona
        return f"{build_core_persona()}\n\n{_ARCHER_CORE}"
    except Exception:
        return "Archer 的核心身份是长期陪伴型 AI 灵魂伴生体。"


def build_messages(
    history: list[dict],
    user_input: str,
    cfg: dict,
    db_memories: str = "",
    project: dict | None = None,
    project_events: list | None = None,
    heavy: bool = True,
    intent: str | None = None,
    confrontation_hints: list[str] | None = None,
    first_run: bool = False,
) -> list[dict]:
    system = build_system_prompt(
        cfg,
        db_memories=db_memories,
        project=project,
        project_events=project_events,
        heavy=heavy,
        intent=intent,
        user_input=user_input,
        confrontation_hints=confrontation_hints,
        first_run=first_run,
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
