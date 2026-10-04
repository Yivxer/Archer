"""Installer source-code risk scanning, independent of approval and persistence.

Callers continue to use core.policy.scan_code_for_dangers; this leaf module
owns AST scanning, encoded-source detection, and the syntax-error fallback.
"""
from __future__ import annotations

import ast
import re


# ── installer 代码扫描 ─────────────────────────────────────────────────────────
_DANGEROUS_APIS: list[str] = [
    s for s in [
        "eval(",
        "exec(",
        "compile(",
        "open(",
        "input(",
        "os.system(",
        "os.popen(",
        "subprocess.call(",
        "subprocess.run(",
        "subprocess.Popen(",
        "__import__(",
        "getattr(",
        "setattr(",
        "delattr(",
        "socket.socket(",
        "os.remove(",
        "os.unlink(",
        "os.rmdir(",
        "shutil.rmtree(",
        "importlib.",
        "__builtins__",
    ]
]


def scan_code_for_dangers(code: str) -> list[str]:
    """扫描代码文本，返回命中的危险 API 列表。

    增强检测（v1.5 P0-S3）：
    - AST 分析：直接检测函数调用，不受字符串拼接影响
    - 编码绕过检测：\\xHH、\\uHHHH、\\\\八进制
    - getattr/setattr/delattr 滥用检测
    - 回退机制：AST 解析失败时回退到字符串检测
    """
    dangers: list[str] = []

    # 1. AST 分析（主要检测手段）
    try:
        tree = ast.parse(code, mode="exec")
        dangers.extend(_scan_ast(tree))
    except SyntaxError:
        # 代码有语法错误，回退到字符串检测
        dangers.extend(_scan_string(code))

    # 2. 编码绕过检测（\\xHH、\\uHHHH）
    decoded = _decode_escape_sequences(code)
    if decoded != code:
        # 代码包含编码绕过，尝试扫描解码后的代码
        try:
            tree = ast.parse(decoded, mode="exec")
            dangers.extend(_scan_ast(tree))
        except SyntaxError:
            dangers.extend(_scan_string(decoded))

    # 去重
    seen: set[str] = set()
    unique: list[str] = []
    for d in dangers:
        if d not in seen:
            seen.add(d)
            unique.append(d)
    return unique


def _decode_escape_sequences(code: str) -> str:
    """
    展开代码中的转义序列，降低编码绕过风险。
    处理 \\xHH、\\uHHHH、\\ooo（八进制）。
    """
    result = code
    # \\xHH → 字符
    result = re.sub(
        r"\\x([0-9a-fA-F]{2})",
        lambda m: chr(int(m.group(1), 16)),
        result,
    )
    # \\uHHHH → 字符
    result = re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda m: chr(int(m.group(1), 16)),
        result,
    )
    # \\ooo（八进制）→ 字符（仅当是有效八进制时）
    result = re.sub(
        r"\\([0-7]{1,3})",
        lambda m: chr(int(m.group(1), 8)),
        result,
    )
    return result


def _scan_ast(tree: ast.AST) -> list[str]:
    """AST 遍历，检测危险函数调用。"""
    dangers: list[str] = []
    func_set = _DANGEROUS_FUNCTIONS

    class DangerVisitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:
            # 检测函数名
            name = _get_call_name(node)
            if name and name in func_set:
                dangers.append(name)
            # 检测 getattr(x, 'danger_name')
            if name == "getattr":
                attr_name = _get_string_arg(node, 1)
                if attr_name and f"__builtins__.{attr_name}" in func_set:
                    dangers.append(f"getattr(..., '{attr_name}')")
            self.generic_visit(node)

    DangerVisitor().visit(tree)
    return dangers


# 用于 AST 检测的函数名集合（不含括号，支持 'os.system' 形式）
_DANGEROUS_FUNCTIONS: set[str] = {
    "eval",
    "exec",
    "compile",
    "open",
    "input",
    "getattr",
    "setattr",
    "delattr",
    "os.system",
    "os.popen",
    "subprocess.call",
    "subprocess.run",
    "subprocess.Popen",
    "__import__",
    "socket.socket",
    "os.remove",
    "os.unlink",
    "os.rmdir",
    "shutil.rmtree",
}


def _get_call_name(node: ast.Call) -> str | None:
    """获取函数调用的名称，如 eval、os.system。"""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        prefix = _get_attr_prefix(func.value)
        return f"{prefix}.{func.attr}" if prefix else func.attr
    return None


def _get_attr_prefix(node: ast.AST) -> str:
    """递归获取属性前缀，如 os.system → 'os'。"""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _get_attr_prefix(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _get_string_arg(node: ast.Call, idx: int) -> str | None:
    """获取位置参数的字符串值（如果是字符串字面量）。"""
    if idx < len(node.args) and isinstance(node.args[idx], ast.Constant):
        val = node.args[idx].value
        if isinstance(val, str):
            return val
    return None


def _scan_string(code: str) -> list[str]:
    """回退方案：字符串匹配检测危险 API。"""
    return [api for api in _DANGEROUS_APIS if api in code]


# 构建 set 加速 AST 检测（已迁移到 _DANGEROUS_FUNCTIONS，此处保留兼容）
_DANGEROUS_APIS_SET: set[str] = set(_DANGEROUS_APIS)
