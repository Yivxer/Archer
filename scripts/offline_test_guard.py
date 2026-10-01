"""Accidental-side-effect guards for disposable Python regression processes."""

from __future__ import annotations

import ipaddress
import json
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


def _path(value: object) -> Path | None:
    if not isinstance(value, (str, bytes, os.PathLike)):
        return None
    raw = os.fsdecode(value)
    if raw == ":memory:":
        return None
    if raw.startswith("file:"):
        raw = unquote(urlsplit(raw).path)
        if not raw or raw == ":memory:":
            return None
    return Path(raw).expanduser().resolve()


def check_event(event: str, args: tuple, protected: tuple[Path, ...]) -> None:
    """Refuse private SQLite access, protected writes and non-test connections."""
    values: tuple = ()
    if event == "sqlite3.connect":
        values = args[:1]
    elif event == "open":
        _, mode, flags = args
        writable = any(letter in (mode or "") for letter in "wax+")
        writable = writable or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))
        if writable:
            values = args[:1]
    elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.truncate"}:
        values = args[:1]
    elif event in {"os.rename", "os.link", "os.symlink"}:
        values = args[:2]
    elif event == "socket.connect":
        address = args[1]
        if not isinstance(address, tuple):  # Unix-domain sockets are local.
            return
        host, port = address[:2]
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
        if not loopback or port == 8765:
            raise PermissionError("offline regression refuses external/production API access")
    for value in values:
        path = _path(value)
        if path is not None and any(path == root or root in path.parents for root in protected):
            raise PermissionError("offline regression refuses a protected user-state path")


def install() -> None:
    roots = tuple(
        Path(value).resolve()
        for value in json.loads(os.environ["ARCHER_OFFLINE_PROTECTED_ROOTS"])
    )
    sys.addaudithook(lambda event, args: check_event(event, args, roots))
