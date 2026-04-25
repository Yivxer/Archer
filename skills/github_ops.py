import subprocess

SKILL = {
    "name": "github_ops",
    "description": "通过 gh CLI 操作 GitHub：查看仓库、issue、PR，创建 issue",
    "version": "1.0.0",
    "author": "archer-builtin",
}

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "github_ops",
            "description": (
                "操作 GitHub 仓库。需要已登录 gh CLI。"
                "支持：列出仓库、查看 issue/PR、创建 issue、执行任意 gh 子命令。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list_repos", "list_issues", "list_prs",
                                 "view_repo", "create_issue", "run"],
                        "description": (
                            "操作类型：list_repos=我的仓库列表、list_issues=issue 列表、"
                            "list_prs=PR 列表、view_repo=仓库详情、"
                            "create_issue=新建 issue、run=执行任意 gh 子命令"
                        ),
                    },
                    "repo": {
                        "type": "string",
                        "description": "仓库，格式 owner/repo 或仓库名（默认当前用户）",
                    },
                    "title": {"type": "string", "description": "issue 标题（create_issue 时必填）"},
                    "body":  {"type": "string", "description": "issue 正文（可选）"},
                    "command": {
                        "type": "string",
                        "description": "action=run 时的 gh 子命令（不含 gh 前缀），例如 'repo view ArcherOS'",
                    },
                },
                "required": ["action"],
            },
        },
    }

def _gh(cmd: str) -> str:
    try:
        r = subprocess.run(
            f"gh {cmd}", shell=True, capture_output=True, text=True, timeout=20
        )
        return (r.stdout + r.stderr).strip() or "(无输出)"
    except subprocess.TimeoutExpired:
        return "超时（20s）"
    except Exception as e:
        return f"错误：{e}"

def run(args: dict) -> str:
    action = args.get("action", "")
    repo   = args.get("repo", "")
    rf     = f" -R {repo}" if repo else ""

    match action:
        case "list_repos":   return _gh("repo list --limit 20")
        case "list_issues":  return _gh(f"issue list{rf} --limit 20")
        case "list_prs":     return _gh(f"pr list{rf} --limit 20")
        case "view_repo":    return _gh(f"repo view{rf}")
        case "create_issue":
            title = args.get("title", "").strip()
            if not title:
                return "错误：需要提供 title"
            body  = args.get("body", "")
            cmd   = f'issue create{rf} --title "{title}"'
            if body:
                cmd += f' --body "{body}"'
            return _gh(cmd)
        case "run":
            cmd = args.get("command", "").strip()
            return _gh(cmd) if cmd else "错误：需要提供 command"
        case _:
            return f"未知操作：{action}"
