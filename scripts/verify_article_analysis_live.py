#!/usr/bin/env python3
"""Installed-state smoke for dialogue-first local article analysis."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen

API = "http://127.0.0.1:8765"
TOKEN_FILE = Path.home() / "Library/Application Support/archer-desktop/security/desktop-api-token"
SYNTHETIC_ARTICLE = "# 测试文章\n\n这是一篇用于安装态验收的合成稿，讨论知识系统与 AI 行动之间的关系。"


def _request(path: str, token: str, payload: dict | None = None):
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    request = Request(
        f"{API}{path}", data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST" if data is not None else "GET",
    )
    return urlopen(request, timeout=240)


def _outbox_count(token: str) -> int:
    payload = json.loads(_request("/outbox", token).read())
    value = payload.get("data", payload) if isinstance(payload, dict) else payload
    return len(value) if isinstance(value, list) else 0


def main() -> int:
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    before = _outbox_count(token)
    with TemporaryDirectory(prefix="archer-article-analysis-") as root:
        article = Path(root) / "曾经发布的测试文章.md"
        article.write_text(SYNTHETIC_ARTICLE, encoding="utf-8")
        query = (
            f"昨天发布过这篇文章{article}，反响不好，我有些失落。"
            "我不想让账号只剩单一类型内容，先帮我分析文章和定位，不要发布。"
        )
        payload = {
            "messages": [{"role": "user", "content": query}],
            "memoryMode": "off", "obsidianMode": "off",
            "fileRefs": [{"path": str(article), "name": article.name, "size": article.stat().st_size}],
        }
        events = []
        with _request("/chat/stream", token, payload) as response:
            for raw in response:
                line = raw.decode("utf-8").strip()
                if line.startswith("data:"):
                    events.append(json.loads(line[5:].strip()))
    after = _outbox_count(token)
    reply = "".join(str(event.get("text", "")) for event in events if event.get("type") == "token")
    hugo_events = [event for event in events if event.get("toolEvent", {}).get("name") == "hugo_blog"]
    approvals = [event for event in events if event.get("toolEvent", {}).get("requiresApproval")]
    mediation = next(
        (event["runtimeContextEvent"] for event in events
         if event.get("runtimeContextEvent", {}).get("phase") == "action_mediation"), {}
    )
    assert mediation.get("decisionTrace", {}).get("handling") == "analyze", mediation
    assert mediation.get("decisionTrace", {}).get("actionResult") == "DENY", mediation
    assert not hugo_events, hugo_events
    assert not approvals, approvals
    assert before == after, (before, after)
    assert "文章" in reply and any(term in reply for term in ("定位", "账号", "写作", "内容")), reply[:500]
    print(json.dumps({
        "ok": True, "handling": "analyze", "hugoEvents": 0,
        "approvalCards": 0, "outboxDelta": after - before, "replyChars": len(reply),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
