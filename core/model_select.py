"""
model_select.py — 每轮模型选择（model_auto）

当 api.model_auto=true 时，按意图与任务类型在 models[] 里选快/重模型；
用户 /model <名> 锁定后让位。图片附件始终走 vision_model。
"""
from __future__ import annotations

_HEAVY_INTENTS = frozenset({"task", "project", "decision", "reflection"})
_REASONING_SIGNALS = frozenset({
    "分析", "复盘", "推理", "论证", "利弊", "架构", "设计", "规划",
    "对比", "tradeoff", "证明", "拆解", "评估",
})


def _api_models(cfg: dict) -> list[str]:
    api = cfg.get("api", {})
    models = api.get("models")
    if isinstance(models, list) and models:
        return [str(m) for m in models if str(m).strip()]
    primary = str(api.get("model", "") or "").strip()
    return [primary] if primary else []


def resolve_active_model(
    cfg: dict,
    *,
    user_text: str = "",
    intent: str = "chat",
    needs_tools: bool = False,
    has_images: bool = False,
) -> tuple[str, str]:
    """返回 (model_name, reason)。reason 用于终端 dim 提示。"""
    api = cfg.get("api", {})
    models = _api_models(cfg)
    primary = str(api.get("model", "") or (models[0] if models else ""))
    vision = str(api.get("vision_model", "") or primary)
    model_auto = api.get("model_auto", True) is not False

    if has_images:
        return vision, "vision"

    if not model_auto:
        return primary, "locked"

    if len(models) < 2:
        return primary, "single"

    fast, heavy = models[0], models[1]
    lowered = user_text.lower()

    if needs_tools or intent in ("task", "project"):
        return heavy, "task"
    if intent in _HEAVY_INTENTS or any(sig in lowered for sig in _REASONING_SIGNALS):
        return heavy, "reasoning"
    if intent == "emotional":
        return fast, "emotional"
    return fast, "chat"


def status_model_label(cfg: dict) -> str:
    """供 /status 与桌面状态栏：auto 或锁定模型名。"""
    api = cfg.get("api", {})
    if api.get("model_auto", True) is not False:
        return "auto"
    return str(api.get("model", "") or "")
