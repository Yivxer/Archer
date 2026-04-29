import shutil
import tempfile
import urllib.request
import ast
import re
from pathlib import Path

SKILLS_DIR = Path(__file__).parent

SKILL = {
    "name": "installer",
    "description": "安装或卸载技能",
    "version": "1.1.0",
    "author": "archer-builtin",
    "risk": "critical",
    "requires_confirmation": False,  # 技能内部自行处理审查和确认
    "default_timeout": 30,
}


def _github_raw(url: str) -> str:
    url = url.replace("https://github.com/", "https://raw.githubusercontent.com/")
    url = url.replace("/blob/", "/")
    return url


def _validate(path: Path) -> str:
    """静态验证技能文件格式，不 import、不执行待安装代码。"""
    code = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(code, filename=str(path))

    skill_name = ""
    has_schema = False
    has_run = False

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SKILL":
                    if not isinstance(node.value, ast.Dict):
                        raise ValueError("SKILL 必须是字面量 dict")
                    try:
                        meta = ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        raise ValueError("SKILL 必须是可静态解析的 dict")
                    if not isinstance(meta, dict):
                        raise ValueError("SKILL 必须是 dict")
                    skill_name = str(meta.get("name", "")).strip()
        elif isinstance(node, ast.FunctionDef):
            if node.name == "schema":
                has_schema = True
            elif node.name == "run":
                has_run = True

    if not skill_name:
        raise ValueError("缺少 SKILL.name")
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}", skill_name):
        raise ValueError("SKILL.name 只能包含字母、数字、下划线或短横线")
    if not has_schema:
        raise ValueError("缺少 schema() 函数")
    if not has_run:
        raise ValueError("缺少 run() 函数")
    return skill_name


def _review_and_confirm(code: str, filename: str, is_url: bool) -> bool:
    """
    展示代码预览、扫描危险 API，让用户决定是否安装。
    返回 True 表示用户确认安装。
    """
    from core.policy import scan_code_for_dangers

    dangers = scan_code_for_dangers(code)

    print(f"\n{'─' * 50}")
    print(f"  技能文件：{filename}")
    print(f"  代码行数：{code.count(chr(10)) + 1} 行")

    if dangers:
        print(f"\n  [!] 发现危险 API（{len(dangers)} 处）：")
        for d in dangers:
            print(f"      · {d}")
    else:
        print("\n  [OK] 未发现危险 API")

    # 显示前 30 行预览
    lines = code.splitlines()[:30]
    print(f"\n  代码预览（前 {len(lines)} 行）：")
    print("  " + "\n  ".join(lines))
    if code.count("\n") >= 30:
        print("  …（已截断）")

    print(f"\n{'─' * 50}")

    if is_url:
        # URL 安装：需要输入完整确认词
        skill_stem = filename.replace(".py", "")
        confirm_word = f"INSTALL {skill_stem}"
        print(f"  输入「{confirm_word}」确认安装，其他任意内容取消：")
        try:
            answer = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        return answer == confirm_word
    else:
        # 本地安装：y/n
        print("  确认从本地路径安装？[y/N] ", end="", flush=True)
        try:
            answer = input("").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        return answer == "y"


def install(source: str) -> str:
    """安装技能，返回技能名。source 可以是本地路径或 URL。"""
    is_url = source.startswith("http")

    if is_url:
        if "github.com" in source and "/blob/" in source:
            source = _github_raw(source)
        filename = source.split("/")[-1].split("?")[0]
        if not filename.endswith(".py"):
            raise ValueError("只支持 .py 文件")

        # 先下载到临时目录，不直接放入 skills/
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / filename
            urllib.request.urlretrieve(source, tmp_path)
            code = tmp_path.read_text(encoding="utf-8", errors="replace")

            if not _review_and_confirm(code, filename, is_url=True):
                raise PermissionError("用户取消安装")

            dest = SKILLS_DIR / filename
            shutil.copy2(tmp_path, dest)
    else:
        src = Path(source)
        if not src.exists():
            raise FileNotFoundError(f"文件不存在：{source}")
        code = src.read_text(encoding="utf-8", errors="replace")

        if not _review_and_confirm(code, src.name, is_url=False):
            raise PermissionError("用户取消安装")

        dest = SKILLS_DIR / src.name
        shutil.copy2(src, dest)

    try:
        name = _validate(dest)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise ValueError(f"技能格式验证失败：{e}")

    return name


def remove(name: str):
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}", name):
        raise ValueError("技能名只能包含字母、数字、下划线或短横线")
    path = SKILLS_DIR / f"{name}.py"
    if not path.exists():
        raise FileNotFoundError(f"技能不存在：{name}")
    path.unlink()


def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "installer",
            "description": "安装或卸载技能插件",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["install", "remove"]},
                    "source": {"type": "string", "description": "本地路径或 URL"},
                },
                "required": ["action"],
            },
        },
    }


def run(args: dict) -> str:
    action = args.get("action", "")
    source = args.get("source", "")
    if action == "install":
        if not source:
            return "错误：需要提供 source"
        try:
            name = install(source)
            return f"技能「{name}」安装成功"
        except PermissionError as e:
            return f"安装取消：{e}"
        except Exception as e:
            return f"安装失败：{e}"
    elif action == "remove":
        try:
            remove(source)
            return f"技能「{source}」已卸载"
        except Exception as e:
            return f"卸载失败：{e}"
    return f"未知操作：{action}"
