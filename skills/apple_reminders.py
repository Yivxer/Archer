import subprocess

SKILL = {
    "name": "apple_reminders",
    "description": "读取和添加 macOS 提醒事项（Reminders）",
    "version": "1.0.0",
    "author": "archer-builtin",
}

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "apple_reminders",
            "description": "操作 macOS 提醒事项：查看待办、添加提醒。使用 osascript，无需额外安装。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "add"],
                        "description": "操作类型：list=查看待办、add=添加提醒",
                    },
                    "title": {
                        "type": "string",
                        "description": "提醒事项标题（add 时必填）",
                    },
                    "due_date": {
                        "type": "string",
                        "description": "截止日期，格式 YYYY-MM-DD（可选）",
                    },
                    "list_name": {
                        "type": "string",
                        "description": "提醒列表名称，默认「提醒事项」",
                    },
                },
                "required": ["action"],
            },
        },
    }

def _osascript(script: str) -> tuple[str, str]:
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=15,
        )
        return r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return "", str(e)

def run(args: dict) -> str:
    action    = args.get("action", "")
    list_name = args.get("list_name", "提醒事项")

    if action == "list":
        script = f'''
tell application "Reminders"
    set reminderList to list "{list_name}"
    set incomplete to (reminders of reminderList whose completed is false)
    set output to ""
    set i to 1
    repeat with r in incomplete
        set output to output & i & ". " & (name of r) & "\\n"
        set i to i + 1
    end repeat
    return output
end tell'''
        out, err = _osascript(script)
        if err:
            return f"读取失败：{err}"
        return f"📋 {list_name}：\n\n{out.strip()}" if out.strip() else f"{list_name} 暂无待办。"

    if action == "add":
        title = args.get("title", "").strip()
        if not title:
            return "错误：请提供提醒标题（title）"
        due_date = args.get("due_date", "").strip()
        due_line = f'\n    set due date of newReminder to date "{due_date}"' if due_date else ""
        script = f'''
tell application "Reminders"
    set reminderList to list "{list_name}"
    set newReminder to make new reminder at end of reminderList
    set name of newReminder to "{title}"{due_line}
end tell
return "ok"'''
        out, err = _osascript(script)
        if err and "ok" not in out:
            return f"添加失败：{err}"
        return f"✅ 已添加提醒：{title}" + (f"（截止 {due_date}）" if due_date else "")

    return f"未知操作：{action}"
