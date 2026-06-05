"""
process_manager — 本地进程管理技能

管理长期运行的本地服务进程（如 Archer API、Hugo Server、开发服务器等）。
解决每次都要手动启动 archer_api.py 的问题。

支持操作：
  start   — 后台启动指定命令，绑定一个 name 标签
  stop    — 按 name 停止进程
  status  — 列出所有已知进程及运行状态
  logs    — 查看进程最近日志（如有日志文件）

进程信息存在内存（本次 Archer session 有效），重启 Archer 后需要重新启动。
常用场景：
  - 启动 archer_api.py（让客户端能连接终端）
  - 启动 hugo server 预览博客
  - 启动 Vite/Next.js 开发服务器
"""
import subprocess
import os
import signal
import time
from pathlib import Path

SKILL = {
    "name": "process_manager",
    "description": "后台启动/停止本地服务进程（API服务、Hugo预览、开发服务器等），查看运行状态",
    "version": "1.0.0",
    "author": "archer-builtin",
    "risk": "medium",
    "default_timeout": 15,
}

# 进程注册表（session 级别，重启 Archer 后清空）
_PROCESSES: dict[str, dict] = {}


def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "process_manager",
            "description": (
                "管理后台运行的本地服务进程。"
                "action=start：后台启动命令，绑定一个 name 标签便于后续管理；"
                "action=stop：按 name 停止已启动的进程；"
                "action=status：列出所有已知进程和运行状态（PID/端口/是否在运行）；"
                "action=restart：停止后重新启动；"
                "常见用途：启动 archer_api.py 让客户端连接、启动 hugo server 预览博客。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["start", "stop", "status", "restart"],
                        "description": "操作类型",
                    },
                    "name": {
                        "type": "string",
                        "description": "进程标签名（如 'archer-api'、'hugo-server'、'vite-dev'），stop/restart 时必填",
                    },
                    "command": {
                        "type": "string",
                        "description": "（action=start/restart 必填）要执行的命令，如 '/Users/Yivxer/Projects/Archer/.venv/bin/python archer_api.py'",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "工作目录，不填则使用当前目录",
                    },
                    "port": {
                        "type": "integer",
                        "description": "（可选）服务监听端口，用于在 status 中显示和快速验证",
                    },
                    "log_file": {
                        "type": "string",
                        "description": "（可选）日志文件路径，不填则输出丢弃",
                    },
                },
                "required": ["action"],
            },
        },
    }


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def run(args: dict) -> str:
    action = args.get("action", "")
    name = args.get("name", "").strip()
    command = args.get("command", "").strip()
    raw_cwd = args.get("cwd", "").strip()
    port = args.get("port")
    log_file = args.get("log_file", "").strip()

    cwd = Path(raw_cwd).expanduser() if raw_cwd else Path.cwd()

    # ── status ────────────────────────────────────────────────────────────────
    if action == "status":
        if not _PROCESSES:
            return "本次 session 中尚未通过 process_manager 启动任何进程"

        lines = ["进程状态：\n"]
        for pname, info in _PROCESSES.items():
            pid = info.get("pid", 0)
            running = _is_running(pid) if pid else False
            status_str = "🟢 运行中" if running else "🔴 已停止"
            port_str = f"  端口：{info['port']}" if info.get("port") else ""
            lines.append(f"  {pname}")
            lines.append(f"    状态：{status_str}  PID：{pid}{port_str}")
            lines.append(f"    命令：{info.get('cmd', '?')}")
            lines.append(f"    目录：{info.get('cwd', '?')}")
        return "\n".join(lines)

    # ── stop ──────────────────────────────────────────────────────────────────
    if action in ("stop", "restart"):
        if not name:
            return "错误：stop/restart 需要指定 name"
        info = _PROCESSES.get(name)
        if not info:
            return f"未找到名为「{name}」的进程记录\n提示：用 action=status 查看已知进程"

        pid = info.get("pid", 0)
        if pid and _is_running(pid):
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.5)
                if _is_running(pid):
                    os.kill(pid, signal.SIGKILL)
                stop_msg = f"已停止「{name}」（PID {pid}）"
            except Exception as e:
                stop_msg = f"停止「{name}」失败：{e}"
        else:
            stop_msg = f"「{name}」进程（PID {pid}）已不在运行"

        if action == "stop":
            _PROCESSES.pop(name, None)
            return stop_msg

        # restart 继续往下用 start 逻辑
        _PROCESSES.pop(name, None)
        if not command:
            # restart 时沿用原命令
            command = info.get("cmd", "")
            if not raw_cwd:
                cwd = Path(info.get("cwd", str(Path.cwd())))
        if not command:
            return f"{stop_msg}\n错误：restart 需要提供 command（或原始命令已丢失）"

    # ── start ─────────────────────────────────────────────────────────────────
    if action in ("start", "restart"):
        if not name:
            return "错误：start 需要指定 name"
        if not command:
            return "错误：start 需要提供 command"

        if not cwd.exists():
            return f"工作目录不存在：{cwd}"

        # 检查是否已经在运行
        existing = _PROCESSES.get(name)
        if existing and _is_running(existing.get("pid", 0)):
            return (
                f"「{name}」已在运行（PID {existing['pid']}）\n"
                f"如需重启请用 action=restart"
            )

        # 设置日志
        stdout_dest = subprocess.DEVNULL
        stderr_dest = subprocess.DEVNULL
        log_path = None
        if log_file:
            log_path = Path(log_file).expanduser()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_fh = open(str(log_path), "a", encoding="utf-8")
            stdout_dest = log_fh
            stderr_dest = log_fh

        try:
            proc = subprocess.Popen(
                command, shell=True, cwd=str(cwd),
                stdout=stdout_dest, stderr=stderr_dest,
                start_new_session=True,
            )
        except Exception as e:
            return f"启动失败：{e}\n命令：{command}"

        _PROCESSES[name] = {
            "pid": proc.pid,
            "cmd": command,
            "cwd": str(cwd),
            "port": port,
            "log": str(log_path) if log_path else None,
        }

        time.sleep(0.8)  # 等待一下确认进程没有立刻退出
        still_running = _is_running(proc.pid)

        port_hint = f"\n  服务地址：http://localhost:{port}" if port else ""
        log_hint = f"\n  日志文件：{log_path}" if log_path else ""
        status_icon = "🟢" if still_running else "🔴（0.8s内已退出，请检查命令）"

        return (
            f"{status_icon} 已启动「{name}」\n"
            f"  PID：{proc.pid}\n"
            f"  命令：{command}\n"
            f"  目录：{cwd}"
            f"{port_hint}"
            f"{log_hint}"
        )

    return f"未知操作：{action}，可用：start / stop / status / restart"
