import subprocess
import re
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

VALID_CATEGORIES = ["系统", "健身", "复盘", "阅读", "产品", "写作"]
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
                        "enum": ["new", "list", "read", "deploy", "preview"],
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
                        "enum": ["系统", "健身", "复盘", "阅读", "产品", "写作"],
                        "description": "（action=new 必填）文章分类",
                    },
                    "description": {
                        "type": "string",
                        "description": "（action=new 必填）一句话摘要，显示在列表页",
                    },
                    "body": {
                        "type": "string",
                        "description": "（action=new 可选）文章正文 Markdown 内容；不填则留空等待编辑",
                    },
                    "filename": {
                        "type": "string",
                        "description": "（action=read 必填）文件名，如 ru-he-zhong-jian-ren-sheng-xi-tong.md",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "（action=list）返回条数，默认 10",
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
        f"URL（发布后）：https://iver.yivxer.com/posts/{slug}/\n\n"
        f"本地预览：hugo server\n"
        f"部署：bash {BLOG_DIR}/deploy.sh"
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


def _deploy() -> str:
    deploy_sh = BLOG_DIR / "deploy.sh"
    if not deploy_sh.exists():
        return f"错误：deploy.sh 不存在 → {deploy_sh}"
    try:
        result = subprocess.run(
            ["bash", str(deploy_sh)],
            capture_output=True, text=True, timeout=120, cwd=str(BLOG_DIR)
        )
        out = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            return f"部署成功！\n\n{out}"
        else:
            return f"部署失败（exit {result.returncode}）：\n\n{out}"
    except subprocess.TimeoutExpired:
        return "部署超时（120s）"
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
        case "deploy":
            return _deploy()
        case "preview":
            return _preview()
        case _:
            return f"未知 action：{action}。可选：new / list / read / deploy / preview"
