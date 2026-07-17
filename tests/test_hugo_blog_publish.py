import os
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
        # deploy.sh 现在接受 target_url 作为参数（用于验证文章 URL）
        assert commands[1][0] == ["bash", str(blog / "deploy.sh"), "https://iver.yivxer.com/posts/test-post/"]
        assert verified == ["https://iver.yivxer.com/posts/test-post/"]
        assert "部署成功" in result
        assert "线上地址：https://iver.yivxer.com/posts/test-post/" in result
        assert "构建输出" not in result


def test_hugo_blog_deploy_reuses_recent_result_for_same_post_fingerprint(monkeypatch):
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

        monkeypatch.setattr(hugo_blog, "BLOG_DIR", blog)
        monkeypatch.setattr(hugo_blog, "POSTS_DIR", posts)
        monkeypatch.setattr(hugo_blog, "_run_command", fake_run_command)
        monkeypatch.setattr(hugo_blog, "_verify_url", lambda url, timeout=20: (True, f"HTTP 200 {url}"))
        hugo_blog._DEPLOY_RESULT_CACHE.clear()

        first = hugo_blog.run({"action": "deploy", "filename": "test-post.md"})
        second = hugo_blog.run({"action": "deploy", "filename": "test-post.md"})

        assert "部署成功" in first
        assert "复用最近一次部署结果" in second
        assert len(commands) == 2
        assert commands[0][0] == ["hugo", "--cleanDestinationDir", "--minify"]
        assert commands[1][0] == ["bash", str(blog / "deploy.sh"), "https://iver.yivxer.com/posts/test-post/"]


def test_hugo_blog_deploy_rejects_external_verify_url(monkeypatch):
    with tempfile.TemporaryDirectory() as root:
        blog = Path(root)
        (blog / "deploy.sh").write_text("#!/bin/bash\n", encoding="utf-8")
        monkeypatch.setattr(hugo_blog, "BLOG_DIR", blog)

        result = hugo_blog.run({"action": "deploy", "url": "https://example.com/post/"})

        assert "url 只允许验证枫弋札记或本地预览地址" in result


def test_hugo_blog_verify_url_empty_returns_false():
    """根因 B 回归测试：空 URL 不应放行（否则 action=deploy 无 filename 时会误判成功）"""
    ok, msg = hugo_blog._verify_url("")
    assert ok is False
    assert "未提供文章 URL" in msg or "无法验证" in msg


def test_hugo_blog_new_reuses_existing_identical_post(monkeypatch):
    with tempfile.TemporaryDirectory() as root:
        blog = Path(root)
        posts = blog / "content" / "posts"
        posts.mkdir(parents=True)
        monkeypatch.setattr(hugo_blog, "BLOG_DIR", blog)
        monkeypatch.setattr(hugo_blog, "POSTS_DIR", posts)

        args = {
            "action": "new",
            "title": "Smoke",
            "slug": "smoke",
            "category": "技术",
            "description": "desc",
            "body": "body",
        }
        first = hugo_blog.run(args)
        second = hugo_blog.run(args)

        assert "文章已创建" in first
        assert "已存在且内容一致" in second
        assert len(list(posts.glob("smoke.md"))) == 1


def test_hugo_blog_new_rejects_existing_slug_with_different_content(monkeypatch):
    with tempfile.TemporaryDirectory() as root:
        blog = Path(root)
        posts = blog / "content" / "posts"
        posts.mkdir(parents=True)
        monkeypatch.setattr(hugo_blog, "BLOG_DIR", blog)
        monkeypatch.setattr(hugo_blog, "POSTS_DIR", posts)

        first = hugo_blog.run({
            "action": "new",
            "title": "Smoke",
            "slug": "smoke",
            "category": "技术",
            "description": "desc",
            "body": "body",
        })
        second = hugo_blog.run({
            "action": "new",
            "title": "Smoke",
            "slug": "smoke",
            "category": "技术",
            "description": "desc",
            "body": "different",
        })

        assert "文章已创建" in first
        assert "文件已存在但内容不同" in second


def test_hugo_blog_publish_returns_work_receipt(monkeypatch):
    with tempfile.TemporaryDirectory() as root:
        blog = Path(root)
        posts = blog / "content" / "posts"
        posts.mkdir(parents=True)
        (blog / "deploy.sh").write_text("#!/bin/bash\n", encoding="utf-8")
        (blog / "hugo.toml").write_text('baseURL = "https://iver.yivxer.com"\n', encoding="utf-8")

        def fake_run_command(cmd, timeout):
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        monkeypatch.setattr(hugo_blog, "BLOG_DIR", blog)
        monkeypatch.setattr(hugo_blog, "POSTS_DIR", posts)
        monkeypatch.setattr(hugo_blog, "_run_command", fake_run_command)
        monkeypatch.setattr(hugo_blog, "_verify_url", lambda url, timeout=5: (True, f"HTTP 200 {url}"))
        hugo_blog._DEPLOY_RESULT_CACHE.clear()

        result = hugo_blog.run_structured({
            "action": "publish",
            "title": "测试文章",
            "slug": "test-post",
            "category": "阅读",
            "description": "desc",
            "body": "第一段\n第二段",
            "sourcePath": "/tmp/source.md",
            "titleSource": "H1",
        })

        receipt = result["metadata"]["workReceipt"]
        assert result["ok"] is True
        assert receipt["done"] == "已发布《测试文章》到枫弋札记"
        assert receipt["source"] == "/tmp/source.md"
        assert receipt["target"] == "https://iver.yivxer.com/posts/test-post/"
        assert "HTTP 200" in receipt["verification"]
        assert "content/posts/test-post.md" in receipt["rollback"]


def test_hugo_blog_delete_and_deploy_returns_404_receipt(monkeypatch):
    with tempfile.TemporaryDirectory() as root:
        blog = Path(root)
        posts = blog / "content" / "posts"
        posts.mkdir(parents=True)
        (blog / "deploy.sh").write_text("#!/bin/bash\n", encoding="utf-8")
        (blog / "hugo.toml").write_text('baseURL = "https://iver.yivxer.com"\n', encoding="utf-8")
        (posts / "test-post.md").write_text(
            '---\ntitle: "测试文章"\nslug: "test-post"\n---\n\nbody',
            encoding="utf-8",
        )

        def fake_run_command(cmd, timeout):
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        monkeypatch.setattr(hugo_blog, "BLOG_DIR", blog)
        monkeypatch.setattr(hugo_blog, "POSTS_DIR", posts)
        monkeypatch.setattr(hugo_blog, "_run_command", fake_run_command)
        monkeypatch.setattr(hugo_blog, "_verify_url_missing", lambda url, timeout=5: (True, f"HTTP 404 {url}"))
        # 删除场景下 _verify_url 会发真 HTTP 请求，mock 为返回 True（删除后期望 404，由 _verify_url_missing 验证）
        monkeypatch.setattr(hugo_blog, "_verify_url", lambda url, timeout=5: (True, f"HTTP 200 {url}"))
        hugo_blog._DEPLOY_RESULT_CACHE.clear()

        result = hugo_blog.run_structured({
            "action": "delete_and_deploy",
            "filename": "test-post.md",
        })

        receipt = result["metadata"]["workReceipt"]
        assert result["ok"] is True
        assert not (posts / "test-post.md").exists()
        assert receipt["done"] == "已从枫弋札记移除《测试文章》"
        assert receipt["target"] == "https://iver.yivxer.com/posts/test-post/"
        assert "HTTP 404" in receipt["verification"]
        assert ".archer-trash/posts" in receipt["rollback"]


def test_hugo_blog_new_normalizes_single_line_paragraphs(monkeypatch):
    with tempfile.TemporaryDirectory() as root:
        blog = Path(root)
        posts = blog / "content" / "posts"
        posts.mkdir(parents=True)
        monkeypatch.setattr(hugo_blog, "BLOG_DIR", blog)
        monkeypatch.setattr(hugo_blog, "POSTS_DIR", posts)

        result = hugo_blog.run({
            "action": "new",
            "title": "Paragraphs",
            "slug": "paragraphs",
            "category": "阅读",
            "description": "desc",
            "body": "第一段。\n第二段。\n\n## 小标题\n\n- 条目一\n- 条目二",
        })

        assert "文章已创建" in result
        content = (posts / "paragraphs.md").read_text(encoding="utf-8")
        assert "第一段。\n\n第二段。" in content
        assert "## 小标题\n\n- 条目一\n- 条目二" in content


def test_hugo_blog_delete_moves_post_out_of_content(monkeypatch):
    with tempfile.TemporaryDirectory() as root:
        blog = Path(root)
        posts = blog / "content" / "posts"
        posts.mkdir(parents=True)
        monkeypatch.setattr(hugo_blog, "BLOG_DIR", blog)
        monkeypatch.setattr(hugo_blog, "POSTS_DIR", posts)

        post = posts / "ce-shi-fa-bu.md"
        post.write_text('---\ntitle: "测试发布"\nslug: "ce-shi-fa-bu"\n---\n\n正文', encoding="utf-8")

        result = hugo_blog.run({"action": "delete", "title": "测试发布"})

        assert "文章已移出发布目录" in result
        assert not post.exists()
        trash_files = list((blog / ".archer-trash" / "posts").glob("*ce-shi-fa-bu.md"))
        assert len(trash_files) == 1


def test_hugo_blog_doctor_then_deploy_end_to_end(monkeypatch):
    """端到端：doctor 自检全通过 → deploy 构建+部署 → URL 验证。

    覆盖完整链路：doctor 9 项检查 → deploy 调 hugo + bash deploy.sh → verify URL。
    """
    with tempfile.TemporaryDirectory() as root:
        blog = Path(root)
        posts = blog / "content" / "posts"
        posts.mkdir(parents=True)
        deploy_sh = blog / "deploy.sh"
        deploy_sh.write_text("#!/bin/bash\n", encoding="utf-8")
        os.chmod(deploy_sh, 0o755)
        (blog / "hugo.toml").write_text('baseURL = "https://iver.yivxer.com"\n', encoding="utf-8")
        (posts / "e2e-post.md").write_text(
            '---\ntitle: "E2E"\nslug: "e2e-post"\n---\n\nbody',
            encoding="utf-8",
        )

        commands_run = []
        def fake_run_command(cmd, timeout):
            commands_run.append((cmd, timeout))
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        verified_urls = []
        def fake_verify_url(url, timeout=20):
            verified_urls.append(url)
            return True, f"HTTP 200 {url}"

        monkeypatch.setattr(hugo_blog, "BLOG_DIR", blog)
        monkeypatch.setattr(hugo_blog, "POSTS_DIR", posts)
        monkeypatch.setattr(hugo_blog, "_run_command", fake_run_command)
        monkeypatch.setattr(hugo_blog, "_verify_url", fake_verify_url)

        # Step 1: doctor 自检应全通过
        doctor_result = hugo_blog.run({"action": "doctor"})
        assert " doctor " not in doctor_result or "✅" in doctor_result, f"doctor 应通过：{doctor_result}"
        # doctor 不应调 deploy.sh
        assert not any(cmd[0] == ["bash", str(deploy_sh)] for cmd in commands_run)
        # 清空 doctor 阶段命令记录，只测 deploy 阶段
        commands_run.clear()

        # Step 2: deploy 构建 + 部署
        deploy_result = hugo_blog.run({"action": "deploy", "filename": "e2e-post.md"})
        assert "部署成功" in deploy_result
        assert "线上地址：https://iver.yivxer.com/posts/e2e-post/" in deploy_result

        # 验证 deploy 阶段命令序列：hugo build → bash deploy.sh
        hugo_cmd = next((c for c, _ in commands_run if c and c[0] == "hugo" and "--minify" in c), None)
        bash_cmd = next((c for c, _ in commands_run if c and c[0] == "bash"), None)
        assert hugo_cmd == ["hugo", "--cleanDestinationDir", "--minify"]
        # deploy.sh 现在接受 target_url 参数（用于验证文章 URL）
        assert bash_cmd == ["bash", str(deploy_sh), "https://iver.yivxer.com/posts/e2e-post/"]

        # Step 3: URL 验证被调用
        assert verified_urls == ["https://iver.yivxer.com/posts/e2e-post/"]


def test_hugo_blog_deploy_failure_includes_doctor_diagnosis(monkeypatch):
    """部署失败时返回结果应附上 doctor 自动诊断。"""
    with tempfile.TemporaryDirectory() as root:
        blog = Path(root)
        posts = blog / "content" / "posts"
        posts.mkdir(parents=True)
        deploy_sh = blog / "deploy.sh"
        deploy_sh.write_text("#!/bin/bash\n", encoding="utf-8")
        os.chmod(deploy_sh, 0o755)
        (blog / "hugo.toml").write_text('baseURL = "https://iver.yivxer.com"\n', encoding="utf-8")
        (posts / "fail.md").write_text(
            '---\ntitle: "Fail"\nslug: "fail"\n---\n\nbody',
            encoding="utf-8",
        )

        # mock hugo build 失败
        def fake_run_command(cmd, timeout):
            if cmd and cmd[0] == "hugo" and "--minify" in cmd:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Error: build failed")
            if cmd and cmd[0] == "hugo" and cmd[1] == "version":
                return subprocess.CompletedProcess(cmd, 0, stdout="hugo v0.100.0", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        monkeypatch.setattr(hugo_blog, "BLOG_DIR", blog)
        monkeypatch.setattr(hugo_blog, "POSTS_DIR", posts)
        monkeypatch.setattr(hugo_blog, "_run_command", fake_run_command)

        result = hugo_blog.run({"action": "deploy", "filename": "fail.md"})

        # 失败信息应包含构建失败
        assert "构建失败" in result
        # 应附上 doctor 诊断
        assert "--- 自动诊断 ---" in result
        assert "博客部署环境自检" in result


def test_hugo_blog_verify_url_empty_returns_false():
    """根因 B 回归测试：空 URL 不应放行（否则 action=deploy 无 filename 时会误判成功）"""
    ok, msg = hugo_blog._verify_url("")
    assert ok is False
    assert "未提供文章 URL" in msg or "无法验证" in msg


def test_try_direct_hugo_redeploy_with_attachment_updates_and_deploys(monkeypatch):
    """带附件重新部署已有文章：确定性路径，不弹确认卡，直接执行 deploy"""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from terminal.api import _tools

    with tempfile.TemporaryDirectory() as root:
        blog = Path(root)
        posts = blog / "content" / "posts"
        posts.mkdir(parents=True)
        (blog / "deploy.sh").write_text("#!/bin/bash\n", encoding="utf-8")
        (blog / "hugo.toml").write_text('baseURL = "https://iver.yivxer.com"\n', encoding="utf-8")

        # 已有空正文的文章（模拟用户报告的「最新一篇内容是空的」场景）
        existing_post = posts / "liu-yue-fu-pan.md"
        existing_post.write_text(
            '---\ntitle: "六月：复盘"\nslug: "liu-yue-fu-pan"\ndate: 2026-06-30\ncategories: ["复盘"]\n---\n',
            encoding="utf-8",
        )

        monkeypatch.setattr(hugo_blog, "BLOG_DIR", blog)
        monkeypatch.setattr(hugo_blog, "POSTS_DIR", posts)

        # Mock _run_command 让 deploy 成功
        def fake_run_command(cmd, timeout):
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")
        monkeypatch.setattr(hugo_blog, "_run_command", fake_run_command)

        # Mock _verify_url 返回成功
        monkeypatch.setattr(hugo_blog, "_verify_url", lambda url, timeout=5: (True, f"HTTP 200 {url}"))

        # Mock runtime_invoke 避免真发 deploy
        class FakeToolResult:
            def __init__(self, ok, content_preview, summary):
                self.ok = ok
                self.content_preview = content_preview
                self.summary = summary
                self.error = None

        def fake_runtime_invoke(name, args, skills):
            assert name == "hugo_blog"
            assert args["action"] == "deploy"
            assert args["filename"] == "liu-yue-fu-pan.md"
            return FakeToolResult(True, "部署成功：https://iver.yivxer.com/posts/liu-yue-fu-pan/ HTTP 200", "hugo_blog deploy 完成")

        monkeypatch.setattr("core.tool_runtime.invoke", fake_runtime_invoke)

        # 构造附件内容（含 frontmatter + 正文）
        attachment_content = (
            '---\ntitle: "六月：复盘"\nslug: "liu-yue-fu-pan"\n---\n\n'
            "这是六月复盘的正文内容，超过 40 字符确保不被判定为太短。" * 3
        )

        # 附件 file_refs（path 指向临时文件）
        att_path = Path(root) / "june-review.md"
        att_path.write_text(attachment_content, encoding="utf-8")

        file_refs = [{"path": str(att_path), "name": "june-review.md", "content": attachment_content}]

        # 调用新捷径
        result = _tools._try_direct_hugo_redeploy_with_attachment(
            "请重新部署这篇六月复盘文章",
            file_refs,
            messages=[{"role": "user", "content": "请重新部署这篇六月复盘文章"}],
        )

        # 应返回非 None
        assert result is not None
        events, summary = result

        # 应有 1 个 tool_event，status=complete
        assert len(events) == 1
        assert events[0]["type"] == "tool_event"
        assert events[0]["toolEvent"]["status"] == "complete"
        assert events[0]["toolEvent"]["requiresApproval"] is False  # 不弹确认卡

        # 文件应被更新（正文写入）
        updated = existing_post.read_text(encoding="utf-8")
        assert "这是六月复盘的正文内容" in updated
        assert "slug: \"liu-yue-fu-pan\"" in updated  # 保留原 frontmatter

        # summary 应包含「已重新部署」
        assert "已重新部署" in summary


def test_try_direct_hugo_redeploy_with_attachment_no_attachment_returns_none():
    """无附件时不触发重新部署捷径"""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from terminal.api import _tools

    result = _tools._try_direct_hugo_redeploy_with_attachment(
        "重新部署六月复盘",
        None,
        messages=[{"role": "user", "content": "重新部署六月复盘"}],
    )
    assert result is None


def test_try_direct_hugo_redeploy_with_attachment_no_redeploy_keyword_returns_none():
    """query 不含重新部署关键词时不触发（避免普通「部署」请求被误判）"""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from terminal.api import _tools

    file_refs = [{"path": "/tmp/test.md", "name": "test.md", "content": "测试内容"}]
    result = _tools._try_direct_hugo_redeploy_with_attachment(
        "帮我部署这篇新文章",  # 不含「重新」「再」「更新」
        file_refs,
        messages=[{"role": "user", "content": "帮我部署这篇新文章"}],
    )
    assert result is None


# ── P0: 中文标题 slug 生成（pypinyin）─────────────────────────────────────────

def test_safe_slug_chinese_to_pinyin():
    """中文标题应转成拼音 slug，每字用 - 分隔。"""
    assert hugo_blog._safe_slug("自嗨的创作与自我的审查") == "zi-hai-de-chuang-zuo-yu-zi-wo-de-shen-cha"
    assert hugo_blog._safe_slug("减脂的代价") == "jian-zhi-de-dai-jia"
    assert hugo_blog._safe_slug("爱不该成为ego的放大器") == "ai-bu-gai-cheng-wei-ego-de-fang-da-qi"


def test_safe_slug_long_chinese_title_does_not_end_with_hyphen():
    title = "健身的第一个谎言，就是告诉你只要坚持就能看到改变"

    slug = hugo_blog._safe_slug(title)

    assert len(slug) <= 80
    assert not slug.endswith("-")


def test_safe_slug_pure_ascii_unchanged():
    """纯 ASCII 英文/数字/连字符应直接保留。"""
    assert hugo_blog._safe_slug("from-claude-to-codex-cursor") == "from-claude-to-codex-cursor"
    assert hugo_blog._safe_slug("english-title") == "english-title"
    assert hugo_blog._safe_slug("2026-summary") == "2026-summary"


def test_safe_slug_mixed_chinese_english():
    """中英混排应正确分隔，不粘连。"""
    assert hugo_blog._safe_slug("mixed 中英 mixed") == "mixed-zhong-ying-mixed"
    assert hugo_blog._safe_slug("2026年度总结") == "2026-nian-du-zong-jie"


def test_safe_slug_empty_and_symbols_fallback():
    """空字符串和纯符号应 fallback 到 untitled。"""
    assert hugo_blog._safe_slug("") == "untitled"
    assert hugo_blog._safe_slug("!!!") == "untitled"
    assert hugo_blog._safe_slug("   ") == "untitled"


def test_safe_slug_consistent_with_existing_blog_posts():
    """生成的 slug 应与现有博客文章 slug 风格一致（每字一横）。"""
    # 现有文章：ai-bu-gai-cheng-wei-ego-de-fang-da-qi
    # 用相同标题生成应得到相同结果
    assert hugo_blog._safe_slug("爱不该成为ego的放大器") == "ai-bu-gai-cheng-wei-ego-de-fang-da-qi"


def test_safe_slug_pypinyin_unavailable_falls_back():
    """pypinyin 不可用时应 fallback 到 _slugify，不抛异常。"""
    import sys
    original = sys.modules.get("pypinyin")
    sys.modules["pypinyin"] = None  # 让 import pypinyin 失败
    try:
        result = hugo_blog._safe_slug("测试标题")
        # fallback 路径：中文被 strip 掉，返回 untitled
        assert result == "untitled"
    finally:
        if original is not None:
            sys.modules["pypinyin"] = original
        else:
            sys.modules.pop("pypinyin", None)


def test_new_post_chinese_title_creates_correct_filename(monkeypatch):
    """中文标题应创建正确的拼音文件名，不再变成 untitled.md。"""
    with tempfile.TemporaryDirectory() as root:
        blog = Path(root)
        posts = blog / "content" / "posts"
        posts.mkdir(parents=True)
        monkeypatch.setattr(hugo_blog, "BLOG_DIR", blog)
        monkeypatch.setattr(hugo_blog, "POSTS_DIR", posts)

        result = hugo_blog.run({
            "action": "new",
            "title": "自嗨的创作与自我的审查",
            "category": "写作",
            "description": "测试摘要",
        })

        assert "错误" not in result
        assert "zi-hai-de-chuang-zuo-yu-zi-wo-de-shen-cha.md" in result
        # 文件应存在
        assert (posts / "zi-hai-de-chuang-zuo-yu-zi-wo-de-shen-cha.md").exists()
        # 不应创建 untitled.md
        assert not (posts / "untitled.md").exists()


def test_new_post_structured_result_reports_created_file(monkeypatch):
    with tempfile.TemporaryDirectory() as root:
        blog = Path(root)
        posts = blog / "content" / "posts"
        posts.mkdir(parents=True)
        monkeypatch.setattr(hugo_blog, "BLOG_DIR", blog)
        monkeypatch.setattr(hugo_blog, "POSTS_DIR", posts)

        result = hugo_blog.run_structured({
            "action": "new",
            "title": "测试文章",
            "category": "写作",
            "description": "测试摘要",
        })

        assert result["ok"] is True
        assert result["metadata"]["filename"] == "ce-shi-wen-zhang.md"
        assert Path(result["metadata"]["createdFile"]).resolve() == (posts / "ce-shi-wen-zhang.md").resolve()
        assert result["metadata"]["url"] == "https://iver.yivxer.com/posts/ce-shi-wen-zhang/"


def test_new_post_same_chinese_title_twice_is_idempotent_not_crash(monkeypatch):
    """同一中文标题和同内容创建两次应幂等，文件名是正确拼音而非 untitled。"""
    with tempfile.TemporaryDirectory() as root:
        blog = Path(root)
        posts = blog / "content" / "posts"
        posts.mkdir(parents=True)
        monkeypatch.setattr(hugo_blog, "BLOG_DIR", blog)
        monkeypatch.setattr(hugo_blog, "POSTS_DIR", posts)

        # 第一次创建
        r1 = hugo_blog.run({
            "action": "new", "title": "测试文章", "category": "写作", "description": "x",
        })
        assert "错误" not in r1
        # 第二次创建同名
        r2 = hugo_blog.run({
            "action": "new", "title": "测试文章", "category": "写作", "description": "x",
        })
        assert "文章已存在且内容一致" in r2
        # 文件名应是拼音，不是 untitled
        assert "ce-shi-wen-zhang.md" in r2


def test_safe_doctor_catches_exceptions():
    """_safe_doctor 应捕获 _doctor 内部异常，返回错误信息而非向上抛。"""
    def boom():
        raise RuntimeError("doctor boom")
    original = hugo_blog._doctor
    hugo_blog._doctor = boom
    try:
        result = hugo_blog._safe_doctor()
        assert "自动诊断自身失败" in result
        assert "doctor boom" in result
    finally:
        hugo_blog._doctor = original
