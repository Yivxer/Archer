"""
stance.py — 每轮动态对话姿态（mode）选择

设计目标：
- 把已有的 12 个对话模式（modes/*.md）从"手动持久切换"升级为"按当轮内容自动选择"。
- 纯规则、零额外 token：关键词信号 + 意图基线打分，不调用 LLM。
- 尊重手动锁定：用户用 /mode <x> 锁定后，自动选择让位。
- 轻量历史感知：极短跟随式输入（"继续""嗯""然后呢"）沿用上一轮姿态，避免跳挡。

返回的姿态始终落在 available（实际存在的模式）之内，否则回退到 default_mode。
"""
from __future__ import annotations

from pathlib import Path


def available_modes(cfg: dict) -> set[str]:
    """返回当前实际可用的模式名集合（modes_dir 文件 + archer.toml 定义）。"""
    persona = cfg.get("persona", {}) if isinstance(cfg, dict) else {}
    names: set[str] = set(persona.get("modes", {}).keys())
    modes_dir = persona.get("modes_dir", "")
    if modes_dir:
        d = Path(modes_dir).expanduser()
        if d.is_dir():
            names.update(p.stem for p in d.glob("*.md"))
    try:
        from core.plugin import iter_plugin_mode_names

        names.update(iter_plugin_mode_names())
    except Exception:
        pass
    return names


# ── 显式信号词：命中即强烈倾向对应姿态（权重高，可压过意图基线）──────────────────
# 顺序即平局时的优先级（越靠前越优先）。
_SIGNALS: list[tuple[str, tuple[str, ...]]] = [
    ("writer", (
        "写一篇", "写一段", "写封信", "写信", "写一首", "独白", "书信", "宣言",
        "帮我写", "润色", "改写", "写成", "隐喻", "碎片笔记", "起个标题", "拟个标题",
    )),
    ("ritualist", (
        "仪式", "告别", "收尾", "送别", "结束这", "结束一段", "开始新", "重新开始",
        "标记一下", "标记这", "转变", "进入新", "开个头", "封存",
    )),
    ("critic", (
        "挑战我", "反驳", "找漏洞", "找问题", "挑刺", "批评我", "压力测试",
        "泼冷水", "有没有漏洞", "说服你", "帮我挑", "戳破", "盲点", "自我说服",
    )),
    ("builder", (
        "写代码", "改代码", "修bug", "修 bug", "重构", "部署", "调试", "报错",
        "实现功能", "跑测试", "commit", "提交代码", "接口", "前端", "后端",
        "这段代码", "编译", "stack trace", "traceback",
    )),
    ("operator", (
        "帮我执行", "帮我运行", "帮我整理", "帮我搜索", "帮我生成", "帮我修改",
        "帮我创建", "列出", "导出", "批量", "整理成表", "归档", "重命名",
    )),
    ("philosopher", (
        "意义", "人生", "存在", "自由", "命运", "灵魂", "主体", "虚无",
        "想透", "本质是", "为什么活", "活着", "价值是什么", "我是谁",
    )),
    ("therapist", (
        "总是这样", "又一次", "为什么我总", "反复", "控制不住", "停不下来",
        "防御", "关系模式", "童年", "原生家庭", "明明…却", "明明却",
    )),
    ("witness", (
        "复盘", "回顾", "这段时间", "这几个月", "这一年", "这半年", "走到这",
        "一路走来", "回头看", "阶段", "轨迹", "我变了", "和以前比",
    )),
    ("questioner", (
        "为什么会", "想不明白", "想不通", "帮我分析", "怎么理解", "本质是什么",
        "怎么想清楚", "矛盾", "纠结", "想不清",
    )),
    ("coach", (
        "怎么开始", "卡住", "卡在", "没法启动", "无法开始", "拖延", "迟迟",
        "推一把", "帮我推进", "接下来怎么", "下一步该", "动不起来",
    )),
    ("mirror", (
        "帮我理清", "理一理", "理清思路", "我自己想", "别引导", "帮我想清楚",
        "梳理一下", "捋一捋",
    )),
    ("listener", (
        "累了", "好累", "难受", "心烦", "烦死", "委屈", "孤独", "想说说",
        "听我说", "不用建议", "别给方案", "只是想", "不想被", "撑不住", "崩溃",
    )),
]

# ── 意图基线：无显式信号时，按 intent 给基线姿态（权重中）──────────────────────────
_INTENT_BASE: dict[str, str] = {
    "emotional":  "listener",
    "decision":   "questioner",
    "reflection": "witness",
    "project":    "builder",
    "task":       "operator",
    "chat":       "",   # 用 default_mode
}

# 极短跟随式输入：沿用上一轮姿态
_CONTINUATION = frozenset([
    "继续", "然后呢", "然后", "嗯", "嗯嗯", "对", "是的", "好", "好的", "ok",
    "还有呢", "那这个呢", "接着说", "go on", "再说说", "说下去",
])

_SIGNAL_WEIGHT = 3
_INTENT_WEIGHT = 2


def select_stance(
    user_text: str,
    *,
    intent: str = "chat",
    available: set[str] | None = None,
    default_mode: str = "listener",
    prev_stance: str | None = None,
) -> tuple[str, str]:
    """选择当轮对话姿态。

    返回 (stance, reason)。reason 是简短的可读说明，便于调试 / 状态栏提示。
    """
    text = (user_text or "").strip()
    lowered = text.lower()

    def _ok(name: str) -> bool:
        return available is None or name in available

    def _fallback() -> tuple[str, str]:
        if prev_stance and _ok(prev_stance):
            return prev_stance, "沿用"
        if _ok(default_mode):
            return default_mode, "默认"
        return (next(iter(available)) if available else default_mode), "默认"

    # 1) 极短跟随式输入 → 沿用上一轮，避免频繁跳挡
    if prev_stance and _ok(prev_stance) and (text in _CONTINUATION or (len(text) <= 4 and intent == "chat")):
        return prev_stance, "跟随上一轮"

    # 2) 打分：显式信号 + 意图基线
    scores: dict[str, int] = {}
    matched: dict[str, str] = {}
    for stance, kws in _SIGNALS:
        if not _ok(stance):
            continue
        for kw in kws:
            if kw in lowered:
                scores[stance] = scores.get(stance, 0) + _SIGNAL_WEIGHT
                matched.setdefault(stance, kw)
                break

    base = _INTENT_BASE.get(intent, "")
    if base and _ok(base):
        scores[base] = scores.get(base, 0) + _INTENT_WEIGHT

    if not scores:
        return _fallback()

    # 平局时按 _SIGNALS 顺序优先；意图基线置于最后
    order = [name for name, _ in _SIGNALS] + [base]
    best = max(scores, key=lambda s: (scores[s], -order.index(s) if s in order else -99))

    if best in matched:
        reason = f"命中“{matched[best]}”"
    elif best == base:
        reason = f"意图={intent}"
    else:
        reason = "信号"
    return best, reason


def resolve_active_stance(
    cfg: dict,
    user_text: str,
    intent: str,
    *,
    available: set[str] | None = None,
    prev_stance: str | None = None,
) -> tuple[str, str]:
    """结合配置锁定状态，给出当轮实际生效的姿态。

    - persona.mode_auto == False（用户用 /mode 锁定）→ 返回 current_mode，不自动选。
    - 否则按 select_stance 动态选择。
    """
    persona = cfg.get("persona", {}) if isinstance(cfg, dict) else {}
    default_mode = persona.get("default_mode", "listener")
    auto = persona.get("mode_auto", True)

    if not auto:
        locked = persona.get("current_mode", default_mode)
        return locked, "锁定"

    return select_stance(
        user_text,
        intent=intent,
        available=available,
        default_mode=default_mode,
        prev_stance=prev_stance,
    )
