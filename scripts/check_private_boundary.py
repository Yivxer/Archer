#!/usr/bin/env python3
"""Check that Archer private files stay out of the public repository."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

PRIVATE_PATHS = (
    ".env",
    "archer.toml",
    "SOUL.md",
    "MEMORY.md",
    "COVENANT.md",
    "PRESENCE.md",
    "memory/archer.db",
)

REQUIRED_GITIGNORE_PATTERNS = (
    ".env",
    "archer.toml",
    "SOUL.md",
    "MEMORY.md",
    "COVENANT.md",
    "PRESENCE.md",
    "*.db",
    "sessions/",
    ".artifacts/",
)

PUBLIC_TEMPLATE_PATHS = (
    "archer.toml.example",
    "templates/archer.example.toml",
    "templates/env.example",
    "templates/SOUL.template.md",
    "templates/MEMORY.template.md",
    "templates/COVENANT.template.md",
    "templates/PRESENCE.template.md",
)

SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)(api_key|access_token|secret)\s*=\s*['\"]([^'\"]{16,})['\"]"),
)

PLACEHOLDER_WORDS = ("your", "xxxx", "example", "placeholder", "here")


def check() -> list[str]:
    errors: list[str] = []
    errors.extend(_check_gitignore())
    errors.extend(_check_tracked_private_files())
    errors.extend(_check_public_templates())
    return errors


def _check_gitignore() -> list[str]:
    path = ROOT / ".gitignore"
    if not path.exists():
        return [".gitignore is missing"]
    text = path.read_text(encoding="utf-8")
    return [
        f".gitignore missing private pattern: {pattern}"
        for pattern in REQUIRED_GITIGNORE_PATTERNS
        if pattern not in text
    ]


def _check_tracked_private_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--", *PRIVATE_PATHS],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    tracked = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return [f"private file is tracked by git: {item}" for item in tracked]


def _check_public_templates() -> list[str]:
    errors: list[str] = []
    for rel in PUBLIC_TEMPLATE_PATHS:
        path = ROOT / rel
        if not path.exists():
            errors.append(f"public template missing: {rel}")
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(0).lower()
                if any(word in value for word in PLACEHOLDER_WORDS):
                    continue
                errors.append(f"possible real secret in public template: {rel}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="run checks and exit non-zero on failure")
    args = parser.parse_args()
    errors = check()
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    if args.check:
        print("private boundary ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
