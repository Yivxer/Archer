"""
Artifact Storage (Step 1/4)

统一管理所有落盘内容，目录结构：
.artifacts/
  tool_results/YYYY-MM-DD/   ← 超长技能输出
  reflections/YYYY-MM-DD/    ← /reflect 结构化输出（Step 5 使用）
  summaries/YYYY-MM-DD/      ← 上下文压缩摘要（预留）
"""
import uuid
from datetime import datetime
from pathlib import Path

ARTIFACTS_DIR = Path(__file__).parent.parent / ".artifacts"

# 合法的 artifact 类型
ARTIFACT_TYPES = ("tool_results", "reflections", "summaries")


def _subdir(artifact_type: str) -> Path:
    if artifact_type not in ARTIFACT_TYPES:
        artifact_type = "tool_results"
    date_str = datetime.now().strftime("%Y-%m-%d")
    d = ARTIFACTS_DIR / artifact_type / date_str
    d.mkdir(parents=True, exist_ok=True)
    return d


def save(content: str, artifact_type: str = "tool_results",
         prefix: str = "artifact") -> Path:
    """保存内容到 artifact 文件，返回路径。"""
    uid = uuid.uuid4().hex[:8]
    path = _subdir(artifact_type) / f"{prefix}_{uid}.txt"
    path.write_text(content, encoding="utf-8")
    return path


def save_tool_result(skill_name: str, content: str) -> Path:
    """向后兼容接口，tool_runtime 使用。"""
    return save(content, artifact_type="tool_results", prefix=skill_name)


def save_reflection(content: str, label: str = "reflect") -> Path:
    """保存 /reflect 结构化输出（Step 5 使用）。"""
    return save(content, artifact_type="reflections", prefix=label)


def dir_size() -> int:
    """返回 .artifacts/ 目录总字节数，目录不存在时返回 0。"""
    if not ARTIFACTS_DIR.exists():
        return 0
    return sum(f.stat().st_size for f in ARTIFACTS_DIR.rglob("*") if f.is_file())


def fmt_size(n_bytes: int) -> str:
    """将字节数格式化为人类可读字符串。"""
    for unit in ("B", "KB", "MB", "GB"):
        if n_bytes < 1024:
            return f"{n_bytes:.1f} {unit}" if unit != "B" else f"{n_bytes} B"
        n_bytes /= 1024
    return f"{n_bytes:.1f} TB"
