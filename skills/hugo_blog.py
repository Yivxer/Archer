import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from datetime import date

BLOG_DIR = Path("/Users/Yivxer/yivxer-blog")
POSTS_DIR = BLOG_DIR / "content" / "posts"

SKILL = {
    "name": "hugo_blog",
    "description": "管理枫弋博客（枫弋札记）：新建文章、列出文章、阅读文章、本地预览、部署上线",
    "version": "1.0.0",
    "author": "archer-builtin",
}

VALID_CATEGORIES = ["系统", "健身", "复盘", "阅读", "产品", "写作", "技术"]
MAX_POST_CHARS = 200_000

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "hugo_blog",
            "description": (
                "管理枫弋博客（iver.yivxer.com）。"
                "action=new 新建文章草稿；"
                "action=list 列出最近文章；"
                "action=read 阅读某篇文章全文；"
                "action=deploy 部署到服务器；"
                "action=preview 本地预览（启动 hugo server）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["new", "list", "read", "edit", "deploy", "preview"],
                        "description": "操作类型",
                    },
                    "title": {
                        "type": "string",
                        "description": "（action=new 必填）文章标题",
                    },
                    "slug": {
                        "type": "string",
                        "description": "（action=new 可选）URL slug，纯小写英文/拼音加连字符；不填则自动从标题生成",
                    },
                    "category": {
                        "type": "string",
                        "enum": VALID_CATEGORIES,
                        "description": "（action=new 必填）文章分类",
                    },
                    "description": {
                        "type": "string",
                        "description": "（action=new 必填）一句话摘要，显示在列表页",
                    },
                    "filename": {
                        "type": "string",
                        "description": "（action=read/edit 必填，deploy 可选）文件名，如 ru-he-zhong-jian-ren-sheng-xi-tong.md；deploy 时用于验证单篇文章 URL",
                    },
                    "body": {
                        "type": "string",
                        "description": "（action=new/edit 可选）文章正文 Markdown；edit 时传入则替换全文正文",
                    },
                    "patch": {
                        "type": "object",
                        "description": "（action=edit 可选）frontmatter 字段更新，如 {\"title\":\"新标题\",\"description\":\"新摘要\",\"category\":\"系统\"}",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "（action=list）返回条数，默认 10",
                    },
                    "url": {
                        "type": "string",
                        "description": "（action=deploy 可选）部署后要验证的完整文章 URL",
                    },
                },
                "required": ["action"],
            },
        },
    }


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "untitled"


def _safe_slug(text: str) -> str:
    slug = (text or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", slug):
        slug = _slugify(slug)
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:80] or "untitled"


def _post_path(filename: str) -> Path:
    name = filename.strip()
    if not name:
        raise ValueError("filename 不能为空")
    if not name.endswith(".md"):
        name += ".md"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.md", name):
        raise ValueError("filename 只能包含字母、数字、点、下划线或短横线")
    posts_dir = POSTS_DIR.resolve()
    path = (POSTS_DIR / name).resolve()
    path.relative_to(posts_dir)
    return path


def _site_base_url() -> str:
    config = BLOG_DIR / "hugo.toml"
    if config.exists():
        text = config.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r'(?m)^baseURL\s*=\s*["\'](.+?)["\']', text)
        if match:
            return match.group(1).rstrip("/")
    return "https://iver.yivxer.com"


def _slug_from_post(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")[:2000]
    match = re.search(r'(?m)^slug:\s*["\']?([^"\'\n]+)["\']?', text)
    if match:
        return _safe_slug(match.group(1))
    return _safe_slug(path.stem)


def _target_url(args: dict) -> str:
    explicit_url = str(args.get("url", "")).strip()
    if explicit_url:
        if not explicit_url.startswith(("https://iver.yivxer.com/", "http://localhost:", "http://127.0.0.1:")):
            raise ValueError("url 只允许验证枫弋札记或本地预览地址")
        return explicit_url

    filename = str(args.get("filename", "")).strip()
    if filename:
        path = _post_path(filename)
        slug = _slug_from_post(path) if path.exists() else _safe_slug(path.stem)
    else:
        slug = _safe_slug(str(args.get("slug", "")).strip())

    if not slug or slug == "untitled":
        return ""
    return f"{_site_base_url()}/posts/{slug}/"


def _resolve_hugo_bin() -> str:
    extra_path = os.pathsep.join((
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
        "/usr/local/bin",
        os.environ.get("PATH", ""),
    ))
    found = shutil.which("hugo", path=extra_path)
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/hugo", "/usr/local/bin/hugo"):
        if Path(candidate).exists():
            return candidate
    return "hugo"


def _run_command(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    argv = list(cmd)
    if argv and argv[0] == "hugo":
        argv[0] = _resolve_hugo_bin()
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join(filter(None, (
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
        "/usr/local/bin",
        env.get("PATH", ""),
    )))
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(BLOG_DIR),
        env=env,
    )


def _verify_url(url: str, timeout: int = 20) -> tuple[bool, str]:
    if not url:
        return True, "未指定单篇文章 URL，跳过单页验证"

    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Archer/2.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.getcode())
    except urllib.error.HTTPError as exc:
        if exc.code != 405:
            return False, f"HTTP {exc.code} {url}"
        get_request = urllib.request.Request(url, method="GET", headers={"User-Agent": "Archer/2.0"})
        try:
            with urllib.request.urlopen(get_request, timeout=timeout) as response:
                status = int(response.getcode())
        except Exception as get_exc:
            return False, f"GET 验证失败：{get_exc}"
    except Exception as exc:
        return False, f"验证失败：{exc}"

    if 200 <= status < 400:
        return True, f"HTTP {status} {url}"
    return False, f"HTTP {status} {url}"


def _strip_deploy_noise(text: str) -> str:
    """去掉 Hugo 统计表、SSH 警告等不适合聊天展示的终端噪音。"""
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if "post-quantum" in lowered or stripped.startswith("** WARNING"):
            continue
        if re.fullmatch(r"[-+|=\s…]+", stripped):
            continue
        if re.match(r"^(Pages|Paginator pages|Non-page files|Static files|Processed images|Aliases|Cleaned|Total in)\b", stripped):
            continue
        if stripped.startswith("Start building sites") or stripped.startswith("hugo v"):
            continue
        kept.append(stripped)
    return "\n".join(kept[-8:])


def _format_deploy_success(target_url: str, verify_msg: str) -> str:
    lines = ["部署成功。"]
    if target_url:
        lines.append(f"线上地址：{target_url}")
    if verify_msg and verify_msg != "未指定单篇文章 URL，跳过单页验证":
        lines.append(f"验证：{verify_msg}")
    return "\n".join(lines)


def _new_post(args: dict) -> str:
    title = args.get("title", "").strip()
    if not title:
        return "错误：title 不能为空"

    category = args.get("category", "").strip()
    if category not in VALID_CATEGORIES:
        return f"错误：category 必须是以下之一：{', '.join(VALID_CATEGORIES)}"

    desc = args.get("description", "").strip()
    if not desc:
        return "错误：description 不能为空"

    slug = _safe_slug(args.get("slug", "").strip() or title)
    body = args.get("body", "").strip()
    if len(body) > MAX_POST_CHARS:
        return f"错误：body 过长（{len(body)} 字符），上限 {MAX_POST_CHARS}"

    today = date.today().isoformat()
    filename = f"{slug}.md"
    try:
        filepath = _post_path(filename)
    except ValueError as e:
        return f"错误：{e}"
    POSTS_DIR.mkdir(parents=True, exist_ok=True)

    if filepath.exists():
        return f"错误：文件已存在 → {filepath}"

    frontmatter = (
        f'---\n'
        f'title: "{title}"\n'
        f'date: {today}\n'
        f'slug: "{slug}"\n'
        f'categories: ["{category}"]\n'
        f'description: "{desc}"\n'
        f'---\n\n'
    )
    content = frontmatter + (body if body else "")

    filepath.write_text(content, encoding="utf-8")
    return (
        f"文章已创建：{filepath}\n"
        f"标题：{title}\n"
        f"分类：{category}\n"
        f"slug：{slug}\n"
        f"URL（发布后）：https://iver.yivxer.com/posts/{slug}/"
    )


def _list_posts(limit: int = 10) -> str:
    limit = max(1, min(limit, 50))
    posts = sorted(POSTS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not posts:
        return "暂无文章。"

    lines = [f"最近 {min(limit, len(posts))} 篇文章：\n"]
    for p in posts[:limit]:
        text = p.read_text(encoding="utf-8", errors="ignore")
        title = "（无标题）"
        dt = "（无日期）"
        cat = ""
        for line in text.splitlines():
            if line.startswith("title:"):
                title = line.split(":", 1)[1].strip().strip('"')
            elif line.startswith("date:"):
                dt = line.split(":", 1)[1].strip()
            elif line.startswith("categories:"):
                cat = line.split(":", 1)[1].strip().strip("[]\"'")
        lines.append(f"  [{dt}] [{cat}] {title}  →  {p.name}")
    return "\n".join(lines)


def _read_post(filename: str) -> str:
    try:
        p = _post_path(filename)
    except ValueError as e:
        return f"错误：{e}"
    if not p.exists():
        return f"文件不存在：{filename}"
    content = p.read_text(encoding="utf-8", errors="ignore")
    if len(content) > 6000:
        content = content[:6000] + f"\n…（已截断，共 {len(content)} 字符）"
    return content


def _edit_post(args: dict) -> str:
    filename = args.get("filename", "").strip()
    if not filename:
        return "错误：filename 不能为空"
    try:
        filepath = _post_path(filename)
    except ValueError as e:
        return f"错误：{e}"
    if not filepath.exists():
        return f"文件不存在：{filename}"

    content = filepath.read_text(encoding="utf-8")

    # 分离 frontmatter 和正文
    fm_match = re.match(r"^---\n(.*?)\n---\n?(.*)", content, re.DOTALL)
    if not fm_match:
        return "错误：文件格式不符合预期（缺少 frontmatter）"
    fm_text, body_text = fm_match.group(1), fm_match.group(2)

    # 更新 frontmatter 字段
    patch = args.get("patch") or {}
    allowed = {"title", "description", "category", "date"}
    for key, val in patch.items():
        if key not in allowed:
            continue
        if key == "category":
            if val not in VALID_CATEGORIES:
                return f"错误：category 必须是 {', '.join(VALID_CATEGORIES)} 之一"
            val_str = f'["{val}"]'
            fm_text = re.sub(rf'^categories:.*$', f'categories: {val_str}', fm_text, flags=re.MULTILINE)
        else:
            fm_text = re.sub(rf'^{key}:.*$', f'{key}: "{val}"', fm_text, flags=re.MULTILINE)

    # 替换正文（传了 body 才替换）
    new_body = args.get("body", "").strip()
    if new_body:
        if len(new_body) > MAX_POST_CHARS:
            return f"错误：body 过长（{len(new_body)} 字符），上限 {MAX_POST_CHARS}"
        body_text = "\n" + new_body

    new_content = f"---\n{fm_text}\n---\n{body_text}"
    filepath.write_text(new_content, encoding="utf-8")

    changed = []
    if patch:
        changed.append(f"frontmatter 更新：{list(patch.keys())}")
    if new_body:
        changed.append(f"正文已替换（{len(new_body)} 字符）")
    return f"文章已更新：{filepath}\n" + "\n".join(changed)


def _deploy(args: dict) -> str:
    deploy_sh = BLOG_DIR / "deploy.sh"
    if not deploy_sh.exists():
        return f"错误：deploy.sh 不存在 → {deploy_sh}"
    try:
        target_url = _target_url(args)
        build = _run_command(["hugo", "--cleanDestinationDir", "--minify"], timeout=120)
        build_out = (build.stdout + build.stderr).strip()
        if build.returncode != 0:
            detail = _strip_deploy_noise(build_out) or build_out[-1200:]
            return f"构建失败（exit {build.returncode}）：\n{detail}"

        result = _run_command(["bash", str(deploy_sh)], timeout=180)
        out = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            detail = _strip_deploy_noise(out) or out[-1200:]
            return f"部署失败（exit {result.returncode}）：\n{detail}"

        verified, verify_msg = _verify_url(target_url)
        if verified:
            return _format_deploy_success(target_url, verify_msg)
        detail = _strip_deploy_noise(out)
        return f"部署完成但单页验证失败：{verify_msg}" + (f"\n{detail}" if detail else "")
    except subprocess.TimeoutExpired:
        return "部署超时"
    except Exception as e:
        return f"部署失败：{e}"


def _preview() -> str:
    try:
        result = subprocess.run(
            ["hugo", "server", "--bind", "127.0.0.1", "--port", "1313"],
            capture_output=True, text=True, timeout=5, cwd=str(BLOG_DIR)
        )
        return "hugo server 已启动，浏览器打开 http://localhost:1313"
    except subprocess.TimeoutExpired:
        return "hugo server 已在后台启动，浏览器打开 http://localhost:1313"
    except FileNotFoundError:
        return "错误：未找到 hugo 命令，请确认已安装 Hugo"
    except Exception as e:
        return f"启动失败：{e}"


def run(args: dict) -> str:
    action = args.get("action", "").strip()
    match action:
        case "new":
            return _new_post(args)
        case "list":
            try:
                limit = int(args.get("limit", 10))
            except (TypeError, ValueError):
                limit = 10
            return _list_posts(limit)
        case "read":
            return _read_post(args.get("filename", ""))
        case "edit":
            return _edit_post(args)
        case "deploy":
            return _deploy(args)
        case "preview":
            return _preview()
        case _:
            return f"未知 action：{action}。可选：new / list / read / deploy / preview"
