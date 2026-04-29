import tempfile
from pathlib import Path
from unittest.mock import patch

from core.url_safety import validate_public_http_url
from skills import (
    file_search,
    github_ops,
    apple_reminders,
    hugo_blog,
    installer,
    obsidian_read,
    obsidian_search,
    obsidian_write,
    screenshot,
    web_fetch,
    whisper_transcribe,
)


def test_obsidian_read_blocks_path_escape(monkeypatch):
    with tempfile.TemporaryDirectory() as vault:
        monkeypatch.setattr(obsidian_read, "_vault", lambda: Path(vault))
        result = obsidian_read.run({"path": "../secret.txt"})
        assert "路径被拒绝" in result


def test_obsidian_write_blocks_absolute_path_outside_vault(monkeypatch):
    with tempfile.TemporaryDirectory() as vault:
        outside = Path(tempfile.gettempdir()) / "archer-outside-note.md"
        monkeypatch.setattr(obsidian_write, "_vault", lambda: Path(vault))
        result = obsidian_write.run({"path": str(outside), "content": "x"})
        assert "路径被拒绝" in result


def test_obsidian_write_allows_path_inside_vault(monkeypatch):
    with tempfile.TemporaryDirectory() as vault:
        monkeypatch.setattr(obsidian_write, "_vault", lambda: Path(vault))
        result = obsidian_write.run({"path": "notes/test.md", "content": "hello"})
        assert "已追加到" in result
        assert (Path(vault) / "notes" / "test.md").read_text(encoding="utf-8").strip() == "hello"


def test_file_search_treats_shell_metacharacters_as_text():
    with tempfile.TemporaryDirectory() as root:
        safe = Path(root) / "safe.txt"
        safe.write_text("needle; touch /tmp/archer-pwned", encoding="utf-8")
        result = file_search.run({
            "mode": "content",
            "directory": root,
            "keyword": "needle; touch /tmp/archer-pwned",
            "ext": "txt",
        })
        assert str(safe) in result


def test_screenshot_uses_argument_list_and_sanitizes_filename(monkeypatch):
    with tempfile.TemporaryDirectory() as root:
        monkeypatch.setattr(screenshot, "SAVE_DIR", Path(root))
        result_path = Path(root) / "bad_name.png"

        def fake_run(*_args, **_kwargs):
            result_path.write_bytes(b"png")

        with patch.object(screenshot.subprocess, "run", side_effect=fake_run) as run:
            screenshot.run({"mode": "fullscreen", "filename": "bad;name"})
        args = run.call_args.args[0]
        assert args == ["screencapture", "-x", str(result_path)]


def test_screenshot_filename_fallback(monkeypatch):
    with patch.object(screenshot.subprocess, "run") as run:
        with tempfile.TemporaryDirectory() as root:
            monkeypatch.setattr(screenshot, "SAVE_DIR", Path(root))
            run.return_value = None
            with patch.object(Path, "exists", return_value=True), patch.object(Path, "stat") as stat:
                stat.return_value.st_size = 1024
                screenshot.run({"mode": "fullscreen", "filename": ";;;"})
        args = run.call_args.args[0]
        assert args[0:2] == ["screencapture", "-x"]
        assert args[2].endswith(".png")


def test_github_ops_uses_argument_list_for_issue_creation():
    with patch.object(github_ops.subprocess, "run") as run:
        run.return_value.stdout = "ok"
        run.return_value.stderr = ""
        github_ops.run({
            "action": "create_issue",
            "repo": "owner/repo; touch /tmp/pwned",
            "title": "bug; touch /tmp/pwned",
            "body": "body",
        })
        args = run.call_args.args[0]
        assert args == [
            "gh",
            "issue",
            "create",
            "-R",
            "owner/repo; touch /tmp/pwned",
            "--title",
            "bug; touch /tmp/pwned",
            "--body",
            "body",
        ]


def test_installer_validate_does_not_execute_top_level_code():
    with tempfile.TemporaryDirectory() as root:
        marker = Path(root) / "executed"
        skill = Path(root) / "safe_skill.py"
        skill.write_text(
            "\n".join([
                "from pathlib import Path",
                f"Path({str(marker)!r}).write_text('executed')",
                "SKILL = {'name': 'safe_skill'}",
                "def schema():",
                "    return {}",
                "def run(args):",
                "    return 'ok'",
            ]),
            encoding="utf-8",
        )
        assert installer._validate(skill) == "safe_skill"
        assert not marker.exists()


def test_installer_rejects_invalid_skill_name():
    with tempfile.TemporaryDirectory() as root:
        skill = Path(root) / "bad_skill.py"
        skill.write_text(
            "SKILL = {'name': '../bad'}\ndef schema(): return {}\ndef run(args): return 'ok'\n",
            encoding="utf-8",
        )
        try:
            installer._validate(skill)
        except ValueError as e:
            assert "SKILL.name" in str(e)
        else:
            raise AssertionError("invalid skill name was accepted")


def test_installer_remove_rejects_path_traversal():
    try:
        installer.remove("../bad")
    except ValueError as e:
        assert "技能名" in str(e)
    else:
        raise AssertionError("path traversal skill name was accepted")


def test_web_fetch_rejects_private_redirect_before_body_read(monkeypatch):
    def fake_open(_opener, req, timeout=15):
        raise web_fetch.urllib.error.HTTPError(
            req.full_url,
            302,
            "Found",
            {"Location": "http://127.0.0.1/admin"},
            None,
        )

    monkeypatch.setattr("core.url_safety.socket.getaddrinfo", lambda *_args, **_kwargs: [
        (None, None, None, None, ("93.184.216.34", 0)),
    ])
    with patch("core.url_safety.urllib.request.OpenerDirector.open", fake_open):
        result = web_fetch.run({"url": "https://example.com"})
    assert "抓取被拒绝" in result
    assert "本地或私有网络" in result


def test_obsidian_search_stays_inside_vault(monkeypatch):
    with tempfile.TemporaryDirectory() as vault:
        note = Path(vault) / "note.md"
        note.write_text("needle", encoding="utf-8")
        hidden = Path(vault) / ".obsidian" / "secret.md"
        hidden.parent.mkdir()
        hidden.write_text("needle", encoding="utf-8")
        monkeypatch.setattr(obsidian_search, "_vault", lambda: Path(vault))
        result = obsidian_search.run({"keyword": "needle", "max_results": 10})
        assert "note.md" in result
        assert "secret.md" not in result


def test_url_safety_rejects_private_and_local_urls():
    for url in [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://10.0.0.1",
        "file:///etc/passwd",
    ]:
        try:
            validate_public_http_url(url)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe URL accepted: {url}")


def test_url_safety_allows_public_http(monkeypatch):
    monkeypatch.setattr("core.url_safety.socket.getaddrinfo", lambda *_args, **_kwargs: [
        (None, None, None, None, ("93.184.216.34", 0)),
    ])
    assert validate_public_http_url("https://example.com/page") == "https://example.com/page"


def test_web_fetch_rejects_localhost_before_network():
    with patch.object(web_fetch.urllib.request, "urlopen") as urlopen:
        result = web_fetch.run({"url": "http://127.0.0.1:8000"})
        assert "无效 URL" in result
        urlopen.assert_not_called()


def test_web_fetch_rejects_redirect_to_localhost(monkeypatch):
    def fake_open(_opener, req, timeout=15):
        raise web_fetch.urllib.error.HTTPError(
            req.full_url,
            302,
            "Found",
            {"Location": "http://127.0.0.1:8000/private"},
            None,
        )

    monkeypatch.setattr("core.url_safety.socket.getaddrinfo", lambda *_args, **_kwargs: [
        (None, None, None, None, ("93.184.216.34", 0)),
    ])
    with patch("core.url_safety.urllib.request.OpenerDirector.open", fake_open):
        result = web_fetch.run({"url": "https://example.com/redirect"})
    assert "抓取被拒绝" in result
    assert "本地或私有网络" in result


def test_hugo_blog_rejects_read_path_traversal():
    result = hugo_blog.run({"action": "read", "filename": "../config.toml"})
    assert "filename 只能包含" in result


def test_hugo_blog_sanitizes_slug_for_new_post(monkeypatch):
    with tempfile.TemporaryDirectory() as root:
        posts = Path(root) / "content" / "posts"
        monkeypatch.setattr(hugo_blog, "POSTS_DIR", posts)
        result = hugo_blog.run({
            "action": "new",
            "title": "Hello World",
            "slug": "../bad slug!",
            "category": "写作",
            "description": "desc",
        })
        assert "文章已创建" in result
        assert (posts / "bad-slug.md").exists()


def test_apple_reminders_escapes_applescript_strings():
    text = apple_reminders._as_applescript_string('x" & do shell script "touch /tmp/pwned" & "')
    assert '\\"' in text
    assert text.startswith('"') and text.endswith('"')


def test_apple_reminders_rejects_bad_due_date():
    result = apple_reminders.run({"action": "add", "title": "x", "due_date": 'today" & bad'})
    assert "due_date 格式" in result


def test_whisper_rejects_bad_model_before_import(tmp_path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    result = whisper_transcribe.run({"path": str(audio), "model": "giant"})
    assert "不支持的模型" in result


def test_whisper_rejects_bad_language_before_import(tmp_path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    result = whisper_transcribe.run({"path": str(audio), "language": "zh;bad"})
    assert "language" in result
