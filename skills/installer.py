import shutil
import urllib.request
import importlib.util
from pathlib import Path

SKILLS_DIR = Path(__file__).parent

def _github_raw(url: str) -> str:
    """github.com/.../blob/... → raw.githubusercontent.com/...."""
    url = url.replace("https://github.com/", "https://raw.githubusercontent.com/")
    url = url.replace("/blob/", "/")
    return url

def _validate(path: Path) -> str:
    """验证技能文件格式，返回技能名，格式错误抛异常。"""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "SKILL"):
        raise ValueError("缺少 SKILL 元数据")
    if not hasattr(mod, "schema"):
        raise ValueError("缺少 schema() 函数")
    if not hasattr(mod, "run"):
        raise ValueError("缺少 run() 函数")
    return mod.SKILL["name"]

def install(source: str) -> str:
    """安装技能，返回技能名。source 可以是本地路径或 URL。"""
    if source.startswith("http"):
        if "github.com" in source and "/blob/" in source:
            source = _github_raw(source)
        filename = source.split("/")[-1].split("?")[0]
        if not filename.endswith(".py"):
            raise ValueError("只支持 .py 文件")
        dest = SKILLS_DIR / filename
        urllib.request.urlretrieve(source, dest)
    else:
        src = Path(source)
        if not src.exists():
            raise FileNotFoundError(f"文件不存在：{source}")
        dest = SKILLS_DIR / src.name

        shutil.copy2(src, dest)

    try:
        name = _validate(dest)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise ValueError(f"技能格式验证失败：{e}")

    return name

def remove(name: str):
    path = SKILLS_DIR / f"{name}.py"
    if not path.exists():
        raise FileNotFoundError(f"技能不存在：{name}")
    path.unlink()
