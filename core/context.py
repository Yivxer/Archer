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
"""

def _load_soul(soul_path: str) -> str:
    p = Path(soul_path)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""

def _load_memory(memory_path: str) -> str:
    p = Path(memory_path)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""

def build_system_prompt(cfg: dict, db_memories: str = "") -> str:
    soul = _load_soul(cfg["persona"]["soul_path"])
    memory = _load_memory(cfg["persona"]["memory_path"])

    parts = [_ARCHER_CORE]
    if soul:
        parts.append("---\n\n# 灵魂档案（SOUL.md）\n\n" + soul)
    if memory:
        parts.append("---\n\n# 当前记忆与状态（MEMORY.md）\n\n" + memory)
    if db_memories:
        parts.append("---\n\n" + db_memories)

    return "\n\n".join(parts)

def build_messages(history: list[dict], user_input: str, cfg: dict, db_memories: str = "") -> list[dict]:
    system = build_system_prompt(cfg, db_memories)
    return [
        {"role": "system", "content": system},
        *history,
        {"role": "user", "content": user_input},
    ]

def load_config() -> dict:
    p = Path(__file__).parent.parent / "archer.toml"
    with open(p, "rb") as f:
        return tomllib.load(f)
