import json
from datetime import datetime
from pathlib import Path

from core.paths import sessions_dir
from core.session_store import dump_session_file
from core.token_usage import session_usage_for_file

SESSIONS_DIR = sessions_dir(Path(__file__).parent.parent / "memory" / "sessions")

class Session:
    def __init__(self):
        self.history: list[dict] = []
        self.started_at = datetime.now()
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    def add(self, user: str, assistant: str):
        self.history.append({"role": "user", "content": user})
        self.history.append({"role": "assistant", "content": assistant})

    def save(self) -> Path:
        filename = self.started_at.strftime("%Y%m%d_%H%M%S") + ".json"
        path = SESSIONS_DIR / filename
        path.write_text(
            dump_session_file(self.history, token_usage=session_usage_for_file()),
            encoding="utf-8",
        )
        return path

    def clear(self):
        self.history.clear()
