"""
npm_run — 前端构建命令技能

封装 npm / pnpm / yarn 常用操作，风险级别降为 medium（CONFIRM 确认即可），
避免每次通过 shell 技能执行 npm 都触发高风险强确认。

支持操作：
  install  — 安装依赖
  build    — 构建生产版本
  dev      — 启动开发服务器（后台）
  run      — 执行任意 package.json script
  list     — 列出可用 scripts

工作目录默认为命令指定的 cwd，不填则用当前 Archer 进程工作目录。
"""
import subprocess
import json
from pathlib import Path

SKILL = {
    "name": "npm_run",
    "description": "执行前端构建命令（npm/pnpm/yarn）：安装依赖、构建、启动开发服务器",
    "version": "1.0.0",
    "author": "archer-builtin",
    "risk": "medium",
    "default_timeout": 120,
}

# 允许使用的包管理器
_MANAGERS = {"npm", "pnpm", "yarn", "bun"}

# 内置操作映射
_BUILTIN_ACTIONS = {
    "install": "install",
    "build": "run build",
    "dev": "run dev",
    "test": "run test",
    "lint": "run lint",
}


def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "npm_run",
            "description": (
                "在指定目录执行前端构建命令。"
                "action=install 安装依赖；action=build 构建生产版本；"
                "action=dev 启动开发服务器；action=run 执行自定义 script；"
                "action=list 列出 package.json 中的所有 scripts。"
                "manager 可选 npm/pnpm/yarn/bun，默认 npm，会自动检测 lock 文件。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {
                        "type": "string",
                        "description": "项目目录路径（含 package.json 的目录），支持 ~ 开头",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["install", "build", "dev", "test", "lint", "run", "list"],
                        "description": "操作类型",
                    },
                    "script": {
                        "type": "string",
                        "description": "（action=run 必填）package.json 中的 script 名称，如 'type-check'",
                    },
                    "manager": {
                        "type": "string",
                        "enum": ["npm", "pnpm", "yarn", "bun"],
                        "description": "包管理器，留空自动检测（pnpm-lock > yarn.lock > bun.lockb > npm）",
                    },
                },
                "required": ["cwd", "action"],
            },
        },
    }


def _detect_manager(cwd: Path) -> str:
    """自动检测包管理器（按 lock 文件判断）。"""
    if (cwd / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (cwd / "yarn.lock").exists():
        return "yarn"
    if (cwd / "bun.lockb").exists():
        return "bun"
    return "npm"


def run(args: dict) -> str:
    raw_cwd = args.get("cwd", "").strip()
    action = args.get("action", "")
    script = args.get("script", "").strip()
    manager = args.get("manager", "").strip().lower()

    if not raw_cwd:
        return "错误：必须指定 cwd（项目目录）"

    cwd = Path(raw_cwd).expanduser()
    if not cwd.exists():
        return f"目录不存在：{cwd}"
    if not cwd.is_dir():
        return f"{cwd} 不是目录"

    pkg_json = cwd / "package.json"

    # ── list ─────────────────────────────────────────────────────────────────
    if action == "list":
        if not pkg_json.exists():
            return f"未找到 package.json：{cwd}"
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            scripts = data.get("scripts", {})
            if not scripts:
                return "package.json 中没有定义任何 scripts"
            lines = [f"  {k:<20} {v}" for k, v in scripts.items()]
            return f"package.json scripts（{cwd.name}）：\n" + "\n".join(lines)
        except Exception as e:
            return f"读取 package.json 失败：{e}"

    if not pkg_json.exists():
        return f"未找到 package.json：{cwd}\n提示：请确认 cwd 是否正确（应包含 package.json 的目录）"

    # 自动检测包管理器
    if not manager or manager not in _MANAGERS:
        manager = _detect_manager(cwd)

    # ── 构建命令 ──────────────────────────────────────────────────────────────
    if action in _BUILTIN_ACTIONS:
        cmd_suffix = _BUILTIN_ACTIONS[action]
        cmd = f"{manager} {cmd_suffix}"
    elif action == "run":
        if not script:
            return "错误：action=run 需要指定 script 参数"
        cmd = f"{manager} run {script}"
    else:
        return f"未知操作：{action}"

    # dev 命令特殊处理：不等待完成，只启动
    is_dev = (action == "dev")
    timeout = 10 if is_dev else 120

    try:
        if is_dev:
            # 后台启动，不阻塞
            proc = subprocess.Popen(
                cmd, shell=True, cwd=str(cwd),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return (
                f"已后台启动：{cmd}\n"
                f"  目录：{cwd}\n"
                f"  PID：{proc.pid}\n"
                f"  提示：开发服务器通常在 http://localhost:3000 或 :5173，用 page_screenshot 验证"
            )
        else:
            result = subprocess.run(
                cmd, shell=True, cwd=str(cwd),
                capture_output=True, text=True, timeout=timeout
            )
            output = (result.stdout + result.stderr).strip()
            status = "✅ 成功" if result.returncode == 0 else f"❌ 失败（code {result.returncode}）"
            output_preview = output[-3000:] if len(output) > 3000 else output
            return (
                f"{status}：{cmd}\n"
                f"  目录：{cwd}\n"
                f"---\n{output_preview}"
            )
    except subprocess.TimeoutExpired:
        return f"超时（{timeout}s）：{cmd}\n提示：如果是首次 install，可能需要更长时间，请直接在终端运行"
    except Exception as e:
        return f"执行失败：{e}"
