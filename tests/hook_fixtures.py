"""Test fixtures for P5.6 hook handlers."""

CALLS: list[dict] = []


def reset_calls() -> None:
    CALLS.clear()


def prepend_tag(context: dict) -> dict:
    CALLS.append(context)
    tool_input = dict(context.get("tool_input") or {})
    tool_input["hooked"] = True
    return {"continue": True, "tool_input": tool_input}


def block_tool(context: dict) -> dict:
    CALLS.append(context)
    return {"continue": False, "message": "blocked by test hook"}


def log_compact(context: dict) -> dict:
    CALLS.append(context)
    return {"continue": True, "metadata": {"seen": context.get("event")}}


def fail_closed(context: dict) -> dict:
    raise RuntimeError("hook exploded")
