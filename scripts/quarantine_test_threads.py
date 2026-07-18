#!/usr/bin/env python3
"""Recoverably remove Journey/test threads from the active user index."""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

from core.paths import ROOT, sessions_dir
from core.thread_store import THREADS_PATH, normalize_thread


TEST_MARKERS = ("journey", "测试对话", "test", "init", "hello", "old")


def is_test_thread(thread: dict) -> bool:
    title = str(thread.get("title", "") or "").strip().lower()
    return any(marker in title for marker in TEST_MARKERS)


def quarantine(*, apply: bool) -> dict:
    if not THREADS_PATH.exists():
        return {"matched": 0, "kept": 0, "backup": "", "applied": False}
    raw = json.loads(THREADS_PATH.read_text(encoding="utf-8"))
    threads = [thread for item in raw if (thread := normalize_thread(item))]
    matched = [thread for thread in threads if is_test_thread(thread)]
    kept = [thread for thread in threads if not is_test_thread(thread)]
    result = {"matched": len(matched), "kept": len(kept), "backup": "", "applied": apply}
    if not apply or not matched:
        return result

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = ROOT / "memory" / ".backups" / "context-protocol" / stamp
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(THREADS_PATH, backup / THREADS_PATH.name)
    session_backup = backup / "sessions"
    session_backup.mkdir()
    source_sessions = sessions_dir()
    copied = 0
    for thread in matched:
        for session_id in thread.get("sessionIds", []):
            source = source_sessions / f"{session_id}.json"
            if source.is_file():
                shutil.copy2(source, session_backup / source.name)
                copied += 1

    temporary = THREADS_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(THREADS_PATH)
    (backup / "manifest.json").write_text(json.dumps({
        "matchedThreads": matched,
        "copiedSessions": copied,
        "activeIndex": str(THREADS_PATH),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    result.update({"backup": str(backup), "copiedSessions": copied})
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(quarantine(apply=args.apply), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
