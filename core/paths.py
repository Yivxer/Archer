import tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "archer.toml"


def _load_config() -> dict:
    try:
        with open(CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


def _expand(path: str | Path) -> Path:
    return Path(path).expanduser()


def memory_db_path(default: Path | None = None) -> Path:
    cfg = _load_config()
    raw = cfg.get("memory", {}).get("db_path")
    if raw:
        return _expand(raw)
    return default or (ROOT / "memory" / "archer.db")


def sessions_dir(default: Path | None = None) -> Path:
    cfg = _load_config()
    raw = cfg.get("paths", {}).get("sessions_dir")
    if raw:
        return _expand(raw)
    return default or (ROOT / "memory" / "sessions")


def artifacts_dir(default: Path | None = None) -> Path:
    cfg = _load_config()
    raw = cfg.get("paths", {}).get("artifacts_dir")
    if raw:
        return _expand(raw)
    return default or (ROOT / ".artifacts")
