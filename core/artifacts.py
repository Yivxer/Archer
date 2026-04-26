import uuid
from datetime import datetime
from pathlib import Path

ARTIFACTS_DIR = Path(__file__).parent.parent / ".artifacts"


def save_tool_result(skill_name: str, content: str) -> Path:
    date_str = datetime.now().strftime("%Y-%m-%d")
    target_dir = ARTIFACTS_DIR / "tool_results" / date_str
    target_dir.mkdir(parents=True, exist_ok=True)
    uid = uuid.uuid4().hex[:8]
    path = target_dir / f"{skill_name}_{uid}.txt"
    path.write_text(content, encoding="utf-8")
    return path
