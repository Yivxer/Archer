import importlib.util
from pathlib import Path

SKILLS_DIR = Path(__file__).parent

def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def load_skills() -> dict:
    """扫描 skills/ 目录，返回 {name: module}。有 SKILL + schema + run 才算技能。"""
    skills = {}
    for py_file in SKILLS_DIR.glob("*.py"):
        if py_file.name.startswith("_"):
            continue
        try:
            mod = _load_module(py_file)
            if hasattr(mod, "SKILL") and hasattr(mod, "schema") and hasattr(mod, "run"):
                name = mod.SKILL["name"]
                skills[name] = mod
        except Exception:
            pass
    return skills

def get_tools(skills: dict) -> list[dict]:
    """生成 OpenAI function calling 格式的 tools 列表。"""
    return [mod.schema() for mod in skills.values()]
