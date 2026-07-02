import os
import re
import hashlib
import shutil
import subprocess
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from datetime import date
from core.url_safety import open_public_http_url, validate_public_http_url


def _resolve_blog_dir() -> Path:
    """从 archer.toml [paths] blog_dir 读取，缺失则回退到默认路径。"""
    cfg_path = Path(__file__).parent.parent / "archer.toml"
    default = Path("/Users/Yivxer/yivxer-blog")
    if not cfg_path.exists():
        return default
    try:
        with open(cfg_path, "rb") as f:
            cfg = tomllib.load(f)
        blog_dir = (cfg.get("paths", {}) or {}).get("blog_dir", "")
        if blog_dir:
            return Path(blog_dir).expanduser()
    except Exception:
        pass
    return default


BLOG_DIR = _resolve_blog_dir()
POSTS_DIR = BLOG_DIR / "content" / "posts"

SKILL = {
    "name": "hugo_blog",
    "description": "管理枫弋博客（枫弋札记）：新建文章、列出文章、阅读文章、删除文章、本地预览、部署上线",
    "version": "1.1.0",
    "author": "archer-builtin",
    "risk": "medium",
    "requires_confirmation": False,  # agent 模式：deploy 直接执行，不弹卡片
}

VALID_CATEGORIES = ["系统", "健身", "复盘", "阅读", "产品", "写作", "技术"]
MAX_POST_CHARS = 200_000
DEPLOY_RESULT_CACHE_TTL_SECONDS = 300
_DEPLOY_RESULT_CACHE: dict[str, tuple[float, str]] = {}

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "hugo_blog",
            "description": (
                "管理枫弋博客（iver.yivxer.com）。"
                "action=publish 读取确认后的文章并发布上线；"
                "action=new 新建文章草稿；"
                "action=list 列出最近文章；"
                "action=read 阅读某篇文章全文；"
                "action=delete 从发布目录移除文章；"
                "action=delete_and_deploy 删除文章并重新部署；"
                "action=deploy 部署到服务器；"
                "action=preview 本地预览（启动 hugo server）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["publish", "new", "list", "read", "edit", "delete", "delete_and_deploy", "deploy", "preview", "doctor"],
                        "description": "操作类型（doctor 做部署环境自检）",
                    },
                    "title": {
                        "type": "string",
                        "description": "（action=new 必填，delete 可选）文章标题；delete 时可用标题匹配文章",
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
                        "description": "（action=read/edit/delete 必填，deploy 可选）文件名，如 ru-he-zhong-jian-ren-sheng-xi-tong.md；deploy 时用于验证单篇文章 URL",
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
                    "sourcePath": {
                        "type": "string",
                        "description": "（action=publish 可选）源稿路径，用于回执和审计",
                    },
                    "titleSource": {
                        "type": "string",
                        "enum": ["frontmatter title", "H1", "filename"],
                        "description": "（action=publish 可选）标题来源，禁止模型自拟标题覆盖源稿",
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
    """生成 URL-safe slug。

    策略：
    1. 纯 ASCII 英文/数字/连字符：直接用
    2. 含中文：用 pypinyin 转拼音（符合现有博客惯例，如 ai-bu-gai-cheng-wei-ego）
    3. 其他非 ASCII：_slugify 后 strip
    4. 最终为空：fallback "untitled"
    """
    slug = (text or "").strip().lower()
    if not slug:
        return "untitled"
    # 纯 ASCII 英文/数字/连字符：直接用
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", slug):
        return slug[:80]
    # 含中文字符：用 pypinyin 转拼音
    has_chinese = bool(re.search(r"[\u4e00-\u9fff]", slug))
    if has_chinese:
        try:
            from pypinyin import lazy_pinyin
            # 每个中文字符转拼音后用 - 分隔（符合现有博客惯例：ai-bu-gai-cheng-wei-ego）
            # 中英交界处也加 -，避免 egode 这种粘连
            parts = []
            prev_type = None  # 'cn' / 'en' / 'sep'
            for ch in slug:
                if "\u4e00" <= ch <= "\u9fff":
                    if prev_type == "en":
                        parts.append("-")
                    parts.append(lazy_pinyin(ch)[0])
                    parts.append("-")
                    prev_type = "cn"
                elif ch.isalnum():
                    if prev_type == "cn":
                        parts.append("-")
                    parts.append(ch)
                    prev_type = "en"
                else:
                    parts.append("-")
                    prev_type = "sep"
            slug = "".join(parts)
            slug = re.sub(r"-+", "-", slug).strip("-")
        except Exception:
            # pypinyin 不可用时 fallback 到 _slugify
            slug = _slugify(slug)
            slug = re.sub(r"[^a-z0-9-]", "", slug)
    else:
        # 其他非 ASCII：_slugify 后 strip 掉非 ASCII
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


def _deploy_fingerprint(args: dict, target_url: str) -> str | None:
    filename = str(args.get("filename", "")).strip()
    if not filename:
        return None
    path = _post_path(filename)
    if not path.exists():
        return None
    digest = hashlib.sha256()
    digest.update(str(BLOG_DIR.resolve()).encode("utf-8"))
    digest.update(b"\0")
    digest.update(target_url.encode("utf-8"))
    digest.update(b"\0")
    digest.update(path.name.encode("utf-8"))
    digest.update(b"\0")
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _cached_deploy_result(fingerprint: str | None) -> str | None:
    if not fingerprint:
        return None
    cached = _DEPLOY_RESULT_CACHE.get(fingerprint)
    if not cached:
        return None
    created_at, output = cached
    if time.time() - created_at > DEPLOY_RESULT_CACHE_TTL_SECONDS:
        _DEPLOY_RESULT_CACHE.pop(fingerprint, None)
        return None
    return "复用最近一次部署结果（内容指纹未变化）。\n" + output


def _remember_deploy_result(fingerprint: str | None, output: str) -> None:
    if not fingerprint or "部署成功" not in output:
        return
    _DEPLOY_RESULT_CACHE[fingerprint] = (time.time(), output)


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


def _verify_url(url: str, timeout: int = 5) -> tuple[bool, str]:
    if not url:
        return True, "未指定单篇文章 URL，跳过单页验证"

    try:
        safe_url = validate_public_http_url(url)
    except ValueError as e:
        return False, f"URL 校验失败：{e}"

    try:
        with open_public_http_url(safe_url, headers={"User-Agent": "Archer/2.0"}, timeout=timeout) as response:
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code} {url}"
    except Exception as exc:
        return False, f"验证失败：{exc}"

    if 200 <= status < 400:
        return True, f"HTTP {status} {url}"
    return False, f"HTTP {status} {url}"


def _verify_url_missing(url: str, timeout: int = 5) -> tuple[bool, str]:
    if not url:
        return True, "未指定单篇文章 URL，跳过删除验证"

    try:
        safe_url = validate_public_http_url(url)
    except ValueError as e:
        return False, f"URL 校验失败：{e}"

    try:
        with open_public_http_url(safe_url, headers={"User-Agent": "Archer/2.0"}, timeout=timeout) as response:
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        if int(exc.code) == 404:
            return True, f"HTTP 404 {url}"
        return False, f"HTTP {exc.code} {url}"
    except Exception as exc:
        return False, f"验证失败：{exc}"

    if status == 404:
        return True, f"HTTP 404 {url}"
    return False, f"HTTP {status} {url}"


def _strip_deploy_noise(text: str, keep_tail: int = 8) -> str:
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
    return "\n".join(kept[-keep_tail:])


def _format_deploy_success(target_url: str, verify_msg: str) -> str:
    lines = ["部署成功。"]
    if target_url:
        lines.append(f"线上地址：{target_url}")
    if verify_msg and verify_msg != "未指定单篇文章 URL，跳过单页验证":
        lines.append(f"验证：{verify_msg}")
    return "\n".join(lines)


def _new_post_content(*, title: str, slug: str, category: str, desc: str, body: str) -> str:
    today = date.today().isoformat()
    frontmatter = (
        f'---\n'
        f'title: "{title}"\n'
        f'date: {today}\n'
        f'slug: "{slug}"\n'
        f'categories: ["{category}"]\n'
        f'description: "{desc}"\n'
        f'---\n\n'
    )
    return frontmatter + (_normalize_markdown_body(body) if body else "")


def _normalize_markdown_body(body: str) -> str:
    """Make Obsidian-style single-line paragraphs render as Hugo paragraphs.

    Many Obsidian notes are written with one sentence per line. CommonMark treats
    those single newlines as one paragraph, so Hugo would render the whole note
    as a single <p>. Keep structural blocks intact and only separate adjacent
    plain-text lines.
    """
    text = (body or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""

    lines = text.splitlines()
    output: list[str] = []
    in_fence = False
    previous_kind = "blank"

    def line_kind(value: str) -> str:
        stripped = value.strip()
        if not stripped:
            return "blank"
        if stripped.startswith("```") or stripped.startswith("~~~"):
            return "fence"
        if re.match(r"^(#{1,6}\s|[-*+]\s|\d+\.\s|>\s?|!\[|\||</?\w)", stripped):
            return "structural"
        return "plain"

    for line in lines:
        kind = line_kind(line)
        if kind == "fence":
            if previous_kind == "plain" and output and output[-1] != "":
                output.append("")
            output.append(line.rstrip())
            in_fence = not in_fence
            previous_kind = "structural"
            continue

        if in_fence:
            output.append(line.rstrip())
            continue

        if kind == "blank":
            if output and output[-1] != "":
                output.append("")
            previous_kind = "blank"
            continue

        if kind == "plain" and previous_kind == "plain" and output and output[-1] != "":
            output.append("")

        output.append(line.rstrip())
        previous_kind = kind

    return "\n".join(output).strip()


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

    filename = f"{slug}.md"
    try:
        filepath = _post_path(filename)
    except ValueError as e:
        return f"错误：{e}"
    POSTS_DIR.mkdir(parents=True, exist_ok=True)

    content = _new_post_content(
        title=title,
        slug=slug,
        category=category,
        desc=desc,
        body=body,
    )

    if filepath.exists():
        existing = filepath.read_text(encoding="utf-8", errors="ignore")
        if existing == content:
            return (
                f"文章已存在且内容一致：{filepath}\n"
                f"标题：{title}\n"
                f"分类：{category}\n"
                f"slug：{slug}\n"
                f"URL（发布后）：https://iver.yivxer.com/posts/{slug}/"
            )
        return f"错误：文件已存在但内容不同 → {filepath}"

    filepath.write_text(content, encoding="utf-8")
    return (
        f"文章已创建：{filepath}\n"
        f"标题：{title}\n"
        f"分类：{category}\n"
        f"slug：{slug}\n"
        f"URL（发布后）：https://iver.yivxer.com/posts/{slug}/"
    )


def _new_post_metadata(args: dict, output: str) -> dict:
    metadata: dict[str, str] = {}
    match = re.search(r"文章(?:已创建|已存在且内容一致)：(.+?\.md)", output)
    if match:
        path = Path(match.group(1))
        metadata["createdFile"] = str(path)
        metadata["filename"] = path.name
    slug_match = re.search(r"(?m)^slug：(.+)$", output)
    if slug_match:
        metadata["slug"] = _safe_slug(slug_match.group(1).strip())
    elif args.get("slug") or args.get("title"):
        metadata["slug"] = _safe_slug(str(args.get("slug") or args.get("title") or ""))
    url_match = re.search(r"URL（发布后）：(\S+)", output)
    if url_match:
        metadata["url"] = url_match.group(1).strip()
    elif metadata.get("slug"):
        metadata["url"] = f"{_site_base_url()}/posts/{metadata['slug']}/"
    return metadata


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
        body_text = "\n" + _normalize_markdown_body(new_body)

    new_content = f"---\n{fm_text}\n---\n{body_text}"
    filepath.write_text(new_content, encoding="utf-8")

    changed = []
    if patch:
        changed.append(f"frontmatter 更新：{list(patch.keys())}")
    if new_body:
        changed.append(f"正文已替换（{len(new_body)} 字符）")
    return f"文章已更新：{filepath}\n" + "\n".join(changed)


def _post_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="ignore")[:4000]
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def _find_post_for_delete(args: dict) -> Path | None:
    filename = str(args.get("filename") or "").strip()
    if filename:
        try:
            path = _post_path(filename)
        except ValueError:
            return None
        return path if path.exists() else None

    slug = _safe_slug(str(args.get("slug") or "").strip())
    title = str(args.get("title") or "").strip()
    safe_title = _safe_slug(title) if title else ""
    for path in POSTS_DIR.glob("*.md"):
        fm = _post_frontmatter(path)
        post_slug = _safe_slug(fm.get("slug") or path.stem)
        post_title = fm.get("title", "")
        if slug and slug != "untitled" and (post_slug == slug or path.stem == slug):
            return path
        if title and post_title == title:
            return path
        if safe_title and safe_title != "untitled" and (post_slug == safe_title or path.stem == safe_title):
            return path
    return None


def _delete_post(args: dict) -> str:
    target = _find_post_for_delete(args)
    if target is None:
        label = str(args.get("filename") or args.get("slug") or args.get("title") or "").strip()
        return f"错误：未找到要删除的文章 → {label or '未指定 filename/slug/title'}"

    trash_dir = BLOG_DIR / ".archer-trash" / "posts"
    trash_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    destination = trash_dir / f"{stamp}-{target.name}"
    suffix = 1
    while destination.exists():
        destination = trash_dir / f"{stamp}-{suffix}-{target.name}"
        suffix += 1
    shutil.move(str(target), str(destination))
    _DEPLOY_RESULT_CACHE.clear()
    return (
        f"文章已移出发布目录：{target.name}\n"
        f"保留位置：{destination}\n"
        "需要重新 deploy 后，线上站点才会同步移除。"
    )


def _title_from_file(path: Path) -> str:
    fm = _post_frontmatter(path)
    return str(fm.get("title") or path.stem)


def _publish(args: dict) -> tuple[bool, str, dict]:
    new_output = _new_post(args)
    if new_output.startswith("错误："):
        return False, new_output, {}

    metadata = _new_post_metadata(args, new_output)
    filename = str(metadata.get("filename") or f"{_safe_slug(str(args.get('slug') or args.get('title') or ''))}.md")
    deploy_output = _deploy({"action": "deploy", "filename": filename})
    ok = "部署成功" in deploy_output and "验证：" in deploy_output
    output = f"{new_output}\n\n{deploy_output}"
    target_url = str(metadata.get("url") or _target_url({"filename": filename}))
    title = str(args.get("title") or Path(filename).stem)
    source = str(args.get("sourcePath") or args.get("source") or "用户输入")
    verification = ""
    verify_match = re.search(r"(?m)^验证：(.+)$", deploy_output)
    if verify_match:
        verification = verify_match.group(1).strip()
    elif "部署成功" in deploy_output:
        verification = "部署成功，未指定单页验证"
    else:
        verification = deploy_output.splitlines()[0] if deploy_output else "未完成验证"
    receipt = {
        "done": f"已发布《{title}》到枫弋札记",
        "source": source,
        "target": target_url,
        "verification": verification,
        "rollback": f"可从 content/posts/{filename} 移出后重新 deploy；源文件不改动",
        "traceId": str(args.get("traceId") or ""),
    }
    return ok, output, {"filename": filename, "url": target_url, "workReceipt": receipt}


def _delete_and_deploy(args: dict) -> tuple[bool, str, dict]:
    target = _find_post_for_delete(args)
    if target is None:
        label = str(args.get("filename") or args.get("slug") or args.get("title") or "").strip()
        return False, f"错误：未找到要删除的文章 → {label or '未指定 filename/slug/title'}", {}

    title = _title_from_file(target)
    target_url = _target_url({"filename": target.name})
    delete_output = _delete_post({"filename": target.name})
    if delete_output.startswith("错误："):
        return False, delete_output, {}

    deploy_output = _deploy({"action": "deploy"})
    verified, verify_msg = _verify_url_missing(target_url)
    ok = "部署成功" in deploy_output and verified
    output = f"{delete_output}\n\n{deploy_output}\n删除验证：{verify_msg}"
    trash_match = re.search(r"(?m)^保留位置：(.+)$", delete_output)
    receipt = {
        "done": f"已从枫弋札记移除《{title}》",
        "source": str(target),
        "target": target_url,
        "verification": verify_msg,
        "rollback": trash_match.group(1).strip() if trash_match else "可从 .archer-trash/posts 恢复后重新 deploy",
        "traceId": str(args.get("traceId") or ""),
    }
    return ok, output, {"url": target_url, "filename": target.name, "workReceipt": receipt}


def _doctor() -> str:
    """部署环境自检，逐项检查常见失败点。"""
    checks: list[tuple[str, bool, str]] = []

    # 1. 博客目录
    checks.append((
        "博客目录",
        BLOG_DIR.is_dir(),
        str(BLOG_DIR),
    ))

    # 2. 文章目录
    checks.append((
        "文章目录 (content/posts)",
        POSTS_DIR.is_dir(),
        str(POSTS_DIR),
    ))

    # 3. Hugo 配置
    hugo_cfg = BLOG_DIR / "hugo.toml"
    checks.append((
        "Hugo 配置 (hugo.toml)",
        hugo_cfg.is_file(),
        str(hugo_cfg),
    ))

    # 4. deploy.sh
    deploy_sh = BLOG_DIR / "deploy.sh"
    checks.append((
        "部署脚本 (deploy.sh)",
        deploy_sh.is_file(),
        str(deploy_sh),
    ))

    # 5. deploy.sh 可执行
    if deploy_sh.is_file():
        checks.append((
            "deploy.sh 可执行权限",
            os.access(deploy_sh, os.X_OK),
            "chmod +x deploy.sh",
        ))

    # 6. Hugo 二进制
    hugo_bin = _resolve_hugo_bin()
    hugo_ok = False
    hugo_ver = ""
    try:
        r = _run_command(["hugo", "version"], timeout=10)
        hugo_ok = r.returncode == 0
        hugo_ver = r.stdout.strip().splitlines()[0] if r.stdout.strip() else r.stderr.strip()[:80]
    except Exception as e:
        hugo_ver = str(e)
    checks.append((
        f"Hugo 可执行 ({hugo_bin})",
        hugo_ok,
        hugo_ver[:100],
    ))

    # 7. SSH / rsync 检查
    deploy_content = ""
    if deploy_sh.is_file():
        try:
            deploy_content = deploy_sh.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            pass
    if "rsync" in deploy_content or "ssh" in deploy_content.lower():
        ssh_ok = shutil.which("ssh") is not None
        rsync_ok = shutil.which("rsync") is not None
        checks.append(("ssh 命令可用", ssh_ok, shutil.which("ssh") or "not found"))
        checks.append(("rsync 命令可用", rsync_ok, shutil.which("rsync") or "not found"))

    # 8. 站点 baseURL
    base = _site_base_url()
    checks.append(("站点 baseURL", True, base))

    # 输出
    lines = ["博客部署环境自检：\n"]
    all_pass = True
    for name, ok, detail in checks:
        mark = "✅" if ok else "❌"
        if not ok:
            all_pass = False
        lines.append(f"  {mark} {name}")
        if detail:
            lines.append(f"     {detail}")

    lines.append("")
    if all_pass:
        lines.append("全部检查通过，可以部署。")
    else:
        lines.append("存在问题，请先修复后再部署。")
    return "\n".join(lines)


def _safe_doctor() -> str:
    """_doctor 的安全包装，确保自身异常不会向上传播导致 chat 流崩溃。"""
    try:
        return _doctor()
    except Exception as exc:
        return f"（自动诊断自身失败：{exc}）"


def _deploy(args: dict) -> str:
    if not BLOG_DIR.exists():
        return f"错误：博客目录不存在 → {BLOG_DIR}"
    deploy_sh = BLOG_DIR / "deploy.sh"
    if not deploy_sh.exists():
        return f"错误：deploy.sh 不存在 → {deploy_sh}"
    try:
        target_url = _target_url(args)
        deploy_fingerprint = _deploy_fingerprint(args, target_url)
        cached = _cached_deploy_result(deploy_fingerprint)
        if cached:
            return cached
        build = _run_command(["hugo", "--cleanDestinationDir", "--minify"], timeout=120)
        build_out = (build.stdout + build.stderr).strip()
        if build.returncode != 0:
            # 失败时保留更多上下文（30 行），便于定位错误
            detail = _strip_deploy_noise(build_out, keep_tail=30) or build_out[-2000:]
            return f"构建失败（exit {build.returncode}）：\n{detail}\n\n--- 自动诊断 ---\n{_safe_doctor()}"

        result = _run_command(["bash", str(deploy_sh)], timeout=180)
        out = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            # 失败时保留更多上下文（30 行），便于定位 deploy.sh 错误
            detail = _strip_deploy_noise(out, keep_tail=30) or out[-2000:]
            return f"部署失败（exit {result.returncode}）：\n{detail}\n\n--- 自动诊断 ---\n{_safe_doctor()}"

        verified, verify_msg = _verify_url(target_url)
        if verified:
            output = _format_deploy_success(target_url, verify_msg)
            _remember_deploy_result(deploy_fingerprint, output)
            return output
        detail = _strip_deploy_noise(out)
        return f"部署完成但单页验证失败：{verify_msg}" + (f"\n{detail}" if detail else "") + f"\n\n--- 自动诊断 ---\n{_safe_doctor()}"
    except subprocess.TimeoutExpired:
        return f"部署超时\n\n--- 自动诊断 ---\n{_safe_doctor()}"
    except Exception as e:
        return f"部署失败：{e}\n\n--- 自动诊断 ---\n{_safe_doctor()}"


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
    # B3.1: 顶层 try/except —— 单 skill 失败不应向上传播，依赖 tool_runtime.invoke 是二次防御
    try:
        action = args.get("action", "").strip()
        match action:
            case "publish":
                return _publish(args)[1]
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
            case "delete":
                return _delete_post(args)
            case "delete_and_deploy":
                return _delete_and_deploy(args)[1]
            case "deploy":
                return _deploy(args)
            case "preview":
                return _preview()
            case "doctor":
                return _doctor()
            case _:
                return f"未知 action：{action}。可选：publish / new / list / read / edit / delete / delete_and_deploy / deploy / preview / doctor"
    except Exception as exc:
        return f"hugo_blog 执行失败：{exc}"


def run_structured(args: dict) -> dict:
    # B3.1: 顶层 try/except —— 保证 run_structured 永远返回结构化 dict，不抛异常
    try:
        action = str(args.get("action", "")).strip()
        metadata: dict = {}
        if action == "publish":
            ok, output, metadata = _publish(args)
        elif action == "delete_and_deploy":
            ok, output, metadata = _delete_and_deploy(args)
        else:
            output = run(args)
            ok = not str(output).startswith(("错误：", "未知 action："))
        if ok and action == "new":
            metadata = _new_post_metadata(args, output)
        elif action == "deploy":
            target_url = ""
            try:
                target_url = _target_url(args)
            except Exception:
                target_url = ""
            metadata = {
                "url": target_url,
                "verified": "验证：" in output or "HTTP 200" in output,
            }
        return {
            "ok": ok,
            "summary": f"hugo_blog {action} 完成" if ok else f"hugo_blog {action} 失败",
            "output": output,
            "metadata": metadata,
        }
    except Exception as exc:
        return {
            "ok": False,
            "summary": f"hugo_blog {args.get('action', '')} 异常",
            "output": f"hugo_blog run_structured 异常：{exc}",
            "metadata": {},
        }
