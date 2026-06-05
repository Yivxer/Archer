"""
code_review — 代码审查

静态分析 + LLM 深度审查，输出结构化 Code Review 报告。

支持本地文件审查，也可直接贴代码。
审查维度：
- 正确性 & 边界条件
- 安全性（注入/XSS/权限）
- 性能（时间/空间复杂度）
- 可维护性（命名/结构/注释）
- 规范（代码风格/最佳实践）
"""
from pathlib import Path
import ast

SKILL = {
    "name": "code_review",
    "description": "代码审查：静态分析 + LLM 深度审查，输出结构化报告",
    "version": "1.0.0",
    "author": "archer-builtin",
    "risk": "low",
    "default_timeout": 60,
}

# ── 懒加载 LLM ─────────────────────────────────────────────

def _llm_stream(prompt: str) -> str:
    from core.llm import stream_chat
    parts = []
    for chunk in stream_chat([{"role": "user", "content": prompt}]):
        if isinstance(chunk, str):
            parts.append(chunk)
    return "".join(parts)


# ── Schema ─────────────────────────────────────────────────

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "code_review",
            "description": (
                "对代码文件或代码片段做结构化 Code Review。"
                "审查正确性、安全性、性能、可维护性、规范。"
                "支持本地文件路径或直接贴代码。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "代码文件路径（与 code 二选一，优先用文件）",
                    },
                    "code": {
                        "type": "string",
                        "description": "直接贴代码片段（与 file_path 二选一）",
                    },
                    "language": {
                        "type": "string",
                        "description": "代码语言（python/javascript/typescript/go/java...），自动检测失败时用",
                    },
                    "focus": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "审查重点，如 ['security', 'performance', 'readability']",
                    },
                    "save_path": {
                        "type": "string",
                        "description": "审查报告保存路径（.md），填写后自动保存",
                    },
                },
                "required": [],
            },
        },
    }


# ── AST 静态分析（Python）────────────────────────────────

def _static_analysis_python(code: str) -> list[str]:
    """Python AST 静态分析，返回问题列表。"""
    issues = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"语法错误（第 {e.lineno} 行）：{e.msg}"]

    for node in ast.walk(tree):
        # bare except
        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                issues.append(f"第 {node.lineno} 行：bare except——建议捕获具体异常类型")
        # eval / exec
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in ("eval", "exec"):
                issues.append(f"第 {node.lineno} 行：使用了 {func.id}()——存在代码注入风险")
        # TODO/FIXME 注释
        # （在 AST 层面无法直接获取注释，改从源码行扫描）

    # 扫描 TODO/FIXME
    for i, line in enumerate(code.splitlines(), 1):
        ll = line.strip().lower()
        if "todo" in ll or "fixme" in ll:
            issues.append(f"第 {i} 行：存在 TODO/FIXME 注释，建议跟踪处理")

    return issues


def _static_analysis_generic(code: str, language: str) -> list[str]:
    """通用静态分析（正则扫描危险模式）。"""
    import re
    issues = []

    patterns = [
        (r"\beval\s*\(",       "可能执行任意代码，存在注入风险"),
        (r"\bexec\s*\(",      "可能执行任意代码，存在注入风险"),
        (r"__import__\s*\(", "__import__ 可导入任意模块，谨慎使用"),
        (r"<script",          "可能存在 XSS 风险，确认输出是否已转义"),
        (r"\bpassword\s*=\s*['\"]", "硬编码密码，应移到环境变量或密钥管理"),
        (r"\bapi_key\s*=\s*['\"]", "硬编码 API Key，应移到环境变量"),
        (r"TODO|FIXME",     "存在未完成事项，建议跟踪"),
    ]

    for i, line in enumerate(code.splitlines(), 1):
        for pat, msg in patterns:
            if re.search(pat, line, re.IGNORECASE):
                issues.append(f"第 {i} 行：{msg}")

    return issues[:20]  # 最多 20 条


# ── Run ────────────────────────────────────────────────────

def run(args: dict) -> str:
    file_path = args.get("file_path", "").strip()
    code      = args.get("code", "").strip()
    language  = args.get("language", "").strip()
    focus     = args.get("focus", None) or []
    save_path = args.get("save_path", "").strip() or None

    # 读取文件 or 用传入的 code
    if file_path:
        p = Path(file_path).expanduser()
        if not p.exists():
            return f"错误：文件不存在 —— {p}"
        code = p.read_text(encoding="utf-8", errors="ignore")
        if not language:
            # 根据后缀猜语言
            suffix = p.suffix.lower()
            _map = {".py": "python", ".js": "javascript", ".ts": "typescript",
                     ".go": "go", ".java": "java", ".rs": "rust",
                     ".cpp": "cpp", ".c": "c", ".sh": "bash"}
            language = _map.get(suffix, "")

    if not code:
        return "错误：需要 file_path 或 code 参数（二选一）"

    # 静态分析
    if language == "python":
        static_issues = _static_analysis_python(code)
    else:
        static_issues = _static_analysis_generic(code, language)

    static_report = ""
    if static_issues:
        static_report = "## 静态分析问题\n\n" + "\n".join(f"- {i}" for i in static_issues)
    else:
        static_report = "## 静态分析\n\n未检测到明显问题。"

    # LLM 深度审查
    focus_hint = "，".join(focus) if focus else "全部维度"
    prompt = (
        "你是一位资深工程师，请对以下代码做结构化 Code Review。\n\n"
        f"代码语言：{language or '自动检测'}\n"
        f"审查重点：{focus_hint}\n\n"
        "报告结构（Markdown）：\n"
        "1. 综合评分（1-10 分）\n"
        "2. 总体评价（3-5 句话）\n"
        "3. 重大问题（必须修改）\n"
        "4. 改进建议（建议修改）\n"
        "5. 优点（做得好的地方）\n"
        "6. 规范检查（命名/格式/注释）\n"
        "要求：具体、有代码行号引用、不废话。\n\n"
        f"```\n{code[:8000]}\n```"
        f"{'...（代码已截断）' if len(code) > 8000 else ''}"
    )

    llm_report = _llm_stream(prompt)

    full_report = (
        f"# Code Review{' - ' + Path(file_path).name if file_path else ''}\n\n"
        f"- 语言：{language or '未指定'}\n"
        f"- 代码长度：{len(code)} 字符\n\n"
        f"{static_report}\n\n"
        f"---\n\n{llm_report}"
    )

    resp = f"✅ 代码审查完成\n\n{full_report}"
    if save_path:
        p2 = Path(save_path).expanduser()
        p2.parent.mkdir(parents=True, exist_ok=True)
        p2.write_text(full_report, encoding="utf-8")
        resp += f"\n\n✅ 已保存到：{p2}"

    return resp
