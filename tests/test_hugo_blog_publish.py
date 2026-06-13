import subprocess
import tempfile
from pathlib import Path

from skills import hugo_blog


def test_hugo_blog_deploy_verifies_target_post_url(monkeypatch):
    with tempfile.TemporaryDirectory() as root:
        blog = Path(root)
        posts = blog / "content" / "posts"
        posts.mkdir(parents=True)
        (blog / "deploy.sh").write_text("#!/bin/bash\n", encoding="utf-8")
        (blog / "hugo.toml").write_text('baseURL = "https://iver.yivxer.com"\n', encoding="utf-8")
        (posts / "test-post.md").write_text(
            '---\ntitle: "Test"\nslug: "test-post"\n---\n\nbody',
            encoding="utf-8",
        )
        commands = []

        def fake_run_command(cmd, timeout):
            commands.append((cmd, timeout))
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        verified = []

        def fake_verify_url(url, timeout=20):
            verified.append(url)
            return True, f"HTTP 200 {url}"

        monkeypatch.setattr(hugo_blog, "BLOG_DIR", blog)
        monkeypatch.setattr(hugo_blog, "POSTS_DIR", posts)
        monkeypatch.setattr(hugo_blog, "_run_command", fake_run_command)
        monkeypatch.setattr(hugo_blog, "_verify_url", fake_verify_url)

        result = hugo_blog.run({"action": "deploy", "filename": "test-post.md"})

        assert commands[0][0] == ["hugo", "--cleanDestinationDir", "--minify"]
        assert commands[1][0] == ["bash", str(blog / "deploy.sh")]
        assert verified == ["https://iver.yivxer.com/posts/test-post/"]
        assert "部署成功" in result
        assert "线上地址：https://iver.yivxer.com/posts/test-post/" in result
        assert "构建输出" not in result


def test_hugo_blog_deploy_rejects_external_verify_url(monkeypatch):
    with tempfile.TemporaryDirectory() as root:
        blog = Path(root)
        (blog / "deploy.sh").write_text("#!/bin/bash\n", encoding="utf-8")
        monkeypatch.setattr(hugo_blog, "BLOG_DIR", blog)

        result = hugo_blog.run({"action": "deploy", "url": "https://example.com/post/"})

        assert "url 只允许验证枫弋札记或本地预览地址" in result
