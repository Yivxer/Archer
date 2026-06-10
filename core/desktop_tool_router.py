"""
desktop_tool_router.py — 桌面端工具预检路由（想法 3 分步）

把 _tools.py 里分散的正则启发式收拢为带置信度的 ToolPlan：
- 高置信：规则直通（零 token）
- 低置信 / 缺参数：可选一次极小 LLM 路由或参数补全
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

_PREFLIGHT_SKILLS = frozenset({
    "shell", "github_ops", "obsidian_read", "obsidian_search", "obsidian_write",
})

_CONFIDENCE_RUN_THRESHOLD = 0.55
_CONFIDENCE_LLM_THRESHOLD = 0.65


@dataclass
class PreflightTool:
    skill: str
    confidence: float
    args: dict = field(default_factory=dict)
    source: str = "rules"


@dataclass
class DesktopToolPlan:
    tools: list[PreflightTool] = field(default_factory=list)
    obsidian_preview: bool = False
    obsidian_preview_confidence: float = 0.0
    obsidian_write: bool = False
    obsidian_write_confidence: float = 0.0

    def get(self, skill: str) -> PreflightTool | None:
        for item in self.tools:
            if item.skill == skill:
                return item
        return None

    def should_run(self, skill: str, threshold: float = _CONFIDENCE_RUN_THRESHOLD) -> bool:
        item = self.get(skill)
        return item is not None and item.confidence >= threshold


@dataclass
class DesktopTurnPlan:
    """一轮桌面聊天的技能选择 + 意图过滤 + 工具预检（统一入口）。"""
    raw_selected: dict
    filtered_skills: dict
    tool_plan: DesktopToolPlan
    intent: str = "chat"


# ── Obsidian path / content extraction（自 _tools.py 迁入）────────────────────

def clean_obsidian_path(path: str) -> str:
    return path.strip().strip("`'\"「」『』（）()[]【】，,。；;：:")


def extract_obsidian_target_path(query: str) -> str:
    known_notes = {
        "客户端构建日志": "50计划清单📌/Archer/客户端构建日志.md",
        "终端构建日志": "50计划清单📌/Archer/终端构建日志.md",
        "网页端构建日志": "50计划清单📌/Archer/网页端构建日志.md",
        "构建日志": "50计划清单📌/Archer/客户端构建日志.md",
    }
    lowered = query.lower()
    for keyword, path in known_notes.items():
        if keyword.lower() in lowered:
            return path

    quoted = re.search(r"[「『\"'`]([^」』\"'`]+\.md)[」』\"'`]", query, re.IGNORECASE)
    if quoted:
        return clean_obsidian_path(quoted.group(1))

    absolute = re.search(r"((?:/Users|~/).*?\.md)", query, re.IGNORECASE | re.DOTALL)
    if absolute:
        return clean_obsidian_path(absolute.group(1))

    relative = re.search(r"([A-Za-z0-9_\-./\u4e00-\u9fff📌🚀🦞]+\.md)", query, re.IGNORECASE)
    if relative:
        return clean_obsidian_path(relative.group(1))

    return "Archer/客户端写入草稿.md"


def extract_obsidian_write_content(query: str) -> str:
    target_path = extract_obsidian_target_path(query)
    if target_path and target_path in query:
        after_path = query.split(target_path, 1)[1].strip()
        after_path = after_path.lstrip("：:，,。；;、\n \t")
        if after_path:
            return after_path

    path_match = re.search(r"(?:/Users|~/).*?\.md", query, re.IGNORECASE | re.DOTALL)
    if path_match:
        after_path = query[path_match.end():].strip().lstrip("：:，,。；;、\n \t")
        if after_path:
            return after_path

    patterns = (
        r"(?:写入|写到|记录到|保存到|追加到|记到)[^：:\n]*[：:]\s*(.+)",
        r"内容[：:]\s*(.+)",
    )
    for pattern in patterns:
        match = re.search(pattern, query, re.DOTALL)
        if match and match.group(1).strip():
            return match.group(1).strip()
    return query.strip()


# ── Shell / GitHub extraction ────────────────────────────────────────────────

def extract_shell_command(query: str) -> str:
    for keyword in ("执行", "运行", "execute", "run"):
        pattern = re.compile(re.escape(keyword) + r"\s*[:：]?\s*(.+)", re.IGNORECASE)
        match = pattern.search(query)
        if match:
            return match.group(1).strip()
    cmd_patterns = [
        r"(?<![a-zA-Z])(" + "|".join([
            "hugo", "rsync", "scp", "ssh", "curl", "wget", "tar", "zip", "unzip", "make", "cmake",
        ]) + r")(?![a-zA-Z])",
        r"\b(npm|pip|yarn|pnpm|bun)\s+(install|run|build|test|start|dev)",
        r"\b(git|gh|docker|kubectl|brew)\s+\w+",
    ]
    for pat in cmd_patterns:
        m = re.search(pat, query, re.IGNORECASE)
        if m:
            start = m.start()
            rest = query[start:].strip()
            end_match = re.search(r"[。？！\n]", rest)
            if end_match:
                rest = rest[:end_match.start()]
            return rest.strip()
    return ""


def extract_github_args(query: str) -> dict:
    args = {"action": "", "repo": "", "title": "", "body": "", "command": ""}
    lowered = query.lower()
    if "列出" in query and "仓库" in query:
        args["action"] = "list_repos"
    elif "列出" in query and "issue" in lowered:
        args["action"] = "list_issues"
    elif "列出" in query and ("pr" in lowered or "pull request" in lowered):
        args["action"] = "list_prs"
    elif "查看" in query and "仓库" in query:
        args["action"] = "view_repo"
    elif "创建" in query and "issue" in lowered:
        args["action"] = "create_issue"
    elif any(k in lowered for k in ["gh ", "git ", "star ", "fork "]):
        args["action"] = "run"
        for prefix in ("gh ", "git "):
            if prefix in query:
                idx = query.lower().find(prefix)
                args["command"] = query[idx + len(prefix):].strip()
                break
    else:
        args["action"] = "list_repos"
    repo_match = re.search(r"([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)", query)
    if repo_match:
        args["repo"] = repo_match.group(1)
    title_match = re.search(r"标题[：:]\s*(.+?)(?:\n|$)", query)
    if title_match:
        args["title"] = title_match.group(1).strip()
    body_match = re.search(r"内容[：:]\s*(.+?)(?:\n|$)", query)
    if body_match:
        args["body"] = body_match.group(1).strip()
    return args


# ── Confidence scoring ───────────────────────────────────────────────────────

def score_shell_intent(query: str) -> tuple[float, dict]:
    lowered = query.lower()
    score = 0.0
    strong = (
        "执行 ", "运行 ", "command", "shell", "bash",
        "ls ", "cat ", "grep ", "npm ", "pip ", "python ", "node ",
        "mkdir ", "git ", "hugo ", "docker ",
    )
    if any(k in lowered for k in strong):
        score = max(score, 0.86)
    cmd_names = ("hugo", "rsync", "scp", "ssh", "curl", "wget", "docker", "kubectl", "brew")
    for cmd in cmd_names:
        if re.search(rf"(?<![a-zA-Z]){re.escape(cmd)}(?![a-zA-Z])", lowered):
            score = max(score, 0.78)
    if any(k in lowered for k in ("执行", "运行", "终端")):
        score = max(score, 0.62)
    command = extract_shell_command(query)
    args = {"command": command}
    if command and len(command) >= 3:
        score = max(score, 0.88)
    return min(score, 0.95), args


def score_github_intent(query: str) -> tuple[float, dict]:
    lowered = query.lower()
    score = 0.0
    strong = ("github", "pull request", "列出 issue", "创建 issue", "gh ", "仓库")
    medium = ("repo", "repository", "issue", "pr", "star", "代码库", "提交")
    if any(k in lowered for k in strong):
        score = max(score, 0.86)
    if any(k in lowered for k in medium) or re.search(r"\bpr\b", lowered):
        score = max(score, 0.72)
    if "git " in lowered and score < 0.5:
        score = max(score, 0.48)
    return min(score, 0.95), extract_github_args(query)


def score_obsidian_preview(query: str) -> float:
    lowered = query.lower()
    strong = ("obsidian", "vault", "知识库")
    medium = (
        "搜索", "看一下笔记", "查一下", "找一下", "读一下", "帮我读",
        "看看笔记", "翻一下", "读取", "读这篇", "打开笔记", "查看笔记",
    )
    if any(k in lowered for k in strong):
        return 0.88
    if any(k in lowered for k in medium) and "笔记" in lowered:
        return 0.76
    if any(k in lowered for k in medium):
        return 0.58
    return 0.0


def score_obsidian_write(query: str) -> tuple[float, dict]:
    lowered = query.lower()
    score = 0.0
    strong = ("写入", "写到", "记录到", "保存到", "追加到", "记到", "新建笔记", "创建笔记")
    medium = (
        "记个笔记", "记下来", "帮我记", "存一下", "保存一下", "记录一下",
        "写个笔记", "写进", "放到笔记", "存到", "备忘", "添加到笔记",
        "mark", "note this", "save this",
    )
    if any(k in lowered for k in strong):
        score = 0.86
    elif any(k in lowered for k in medium):
        score = 0.70
    path = extract_obsidian_target_path(query)
    return score, {"path": path, "mode": "append"}


def score_obsidian_read(query: str) -> tuple[float, dict]:
    conf = score_obsidian_preview(query)
    path = extract_obsidian_target_path(query)
    if path and path != "Archer/客户端写入草稿.md":
        conf = max(conf, 0.72)
    return conf, {"path": path, "max_chars": 4000}


# ── Backward-compatible boolean gates（供测试与旧调用）────────────────────────

def should_preview_obsidian(query: str) -> bool:
    return score_obsidian_preview(query) >= _CONFIDENCE_RUN_THRESHOLD


def should_draft_obsidian_write(query: str) -> bool:
    return score_obsidian_write(query)[0] >= _CONFIDENCE_RUN_THRESHOLD


def should_trigger_shell(query: str) -> bool:
    return score_shell_intent(query)[0] >= _CONFIDENCE_RUN_THRESHOLD


def should_trigger_github(query: str) -> bool:
    return score_github_intent(query)[0] >= _CONFIDENCE_RUN_THRESHOLD


# ── Hugo 博客意图（自 _tools.py 迁入，供技能过滤与预检共用）────────────────────

_HUGO_BLOG_TARGET_TERMS = (
    "博客", "博文", "枫弋札记", "hugo", "yivxer-blog", "iver.yivxer.com",
    "网站", "站点", "posts/", "content/posts",
)
_HUGO_DEPLOY_TERMS = (
    "部署", "上线", "发布", "上传", "推送", "同步到服务器",
    "deploy", "publish", "upload", "rsync",
)
_HUGO_CREATE_TERMS = (
    "写到博客", "发到博客", "发布到博客", "上传到博客",
    "新建博客", "博客文章", "博客草稿", "博文",
)


def has_hugo_blog_target(query: str) -> bool:
    lowered = query.lower()
    return any(term in lowered for term in _HUGO_BLOG_TARGET_TERMS)


def wants_hugo_deploy(query: str) -> bool:
    lowered = query.lower()
    if not any(term in lowered for term in _HUGO_DEPLOY_TERMS):
        return False
    if has_hugo_blog_target(query):
        return True
    return any(term in lowered for term in ("部署", "上线", "同步到服务器", "rsync"))


def wants_hugo_creation(query: str) -> bool:
    lowered = query.lower()
    return has_hugo_blog_target(query) and any(term in lowered for term in _HUGO_CREATE_TERMS)


# ── 技能意图过滤（自 _tools.py 迁入，与 skill_router 串联）────────────────────

def has_explicit_web_search_intent(query: str) -> bool:
    lowered = query.lower()
    return bool(re.search(r"https?://", query)) or any(term in lowered for term in (
        "搜索", "搜一下", "查一下", "查找", "联网", "上网", "网上", "网页",
        "最新", "新闻", "资料", "调研", "检索", "search", "google",
    ))


def has_explicit_file_write_intent(query: str) -> bool:
    lowered = query.lower()
    has_path = bool(re.search(
        r"(?:^|\s)(?:~|/Users/|\.{1,2}/)[^\s]+|\b[\w.-]+\.(?:md|txt|json|py|ts|tsx|js|css|html)\b",
        query,
    ))
    return has_path or any(term in lowered for term in (
        "保存到", "写入文件", "写到文件", "创建文件", "新建文件", "生成文件",
        "另存", "保存为", "放到", "写到路径", "修改文件", "编辑文件",
        "覆盖文件", "追加到", "append to", "save to", "write file",
    ))


def is_plain_content_request(query: str) -> bool:
    lowered = query.lower()
    return any(term in lowered for term in (
        "帮我生成一篇", "生成一篇", "帮我写一篇", "写一篇", "按照这个逻辑",
        "帮我分析文章", "分析文章", "改写", "润色", "扩写", "缩写",
        "写成文章", "整理成文章", "生成文章",
    ))


def filter_skills_for_intent(
    query: str,
    selected: dict,
    *,
    intent: str = "chat",
) -> dict:
    """在 skill_router 结果上再做副作用过滤，避免「写文章」误开工具。"""
    if (
        is_plain_content_request(query)
        and not has_explicit_web_search_intent(query)
        and not has_explicit_file_write_intent(query)
        and not (wants_hugo_deploy(query) or wants_hugo_creation(query))
    ):
        return {}

    filtered = dict(selected)
    if "hugo_blog" in filtered and not (wants_hugo_deploy(query) or wants_hugo_creation(query)):
        filtered.pop("hugo_blog", None)
    if not has_explicit_web_search_intent(query):
        filtered.pop("web_search", None)
        if not re.search(r"https?://", query):
            filtered.pop("web_fetch", None)
    if not has_explicit_file_write_intent(query):
        filtered.pop("file_ops", None)
    # 情绪/反思/闲聊：无明确联网意图时不自动开 web_search（「为什么」会误命中路由）
    if intent in ("emotional", "reflection", "chat") and not has_explicit_web_search_intent(query):
        filtered.pop("web_search", None)
    return filtered


# ── LLM fallback ─────────────────────────────────────────────────────────────

def _parse_json_blob(text: str) -> dict | None:
    try:
        return json.loads(text.strip())
    except Exception:
        pass
    m = re.search(r"\{[^{}]+\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except Exception:
        return None


def _llm_extract_shell_command(query: str) -> str:
    try:
        from core.llm import stream_chat
        prompt = (
            "从用户消息中提取要执行的 shell 命令。只输出 JSON："
            '{"command":"..."}；没有明确命令则 {"command":""}。\n'
            f"用户：{query.strip()}\nJSON："
        )
        full = "".join(stream_chat([{"role": "user", "content": prompt}], track_usage=False))
        parsed = _parse_json_blob(full) or {}
        return str(parsed.get("command", "")).strip()
    except Exception:
        return ""


def _llm_plan_tools(query: str, allowed_skills: set[str]) -> DesktopToolPlan | None:
    if not allowed_skills:
        return None
    try:
        from core.llm import stream_chat
        skills_str = "|".join(sorted(allowed_skills & _PREFLIGHT_SKILLS))
        prompt = (
            "你是桌面工具路由器。根据用户消息判断需要预检的本地工具。"
            f"允许的技能：{skills_str}。\n"
            '只输出 JSON：{"tools":[{"skill":"shell","confidence":0.0-1.0,"args":{}}]}\n'
            "没有明确工具需求则 {\"tools\":[]}。不要解释。\n"
            f"用户：{query.strip()}\nJSON："
        )
        full = "".join(stream_chat([{"role": "user", "content": prompt}], track_usage=False))
        parsed = _parse_json_blob(full) or {}
        tools_raw = parsed.get("tools") or []
        plan = DesktopToolPlan()
        for item in tools_raw:
            if not isinstance(item, dict):
                continue
            skill = str(item.get("skill", "")).strip()
            if skill not in allowed_skills:
                continue
            conf = float(item.get("confidence", 0.7))
            args = item.get("args") if isinstance(item.get("args"), dict) else {}
            plan.tools.append(PreflightTool(skill, conf, args, source="llm"))
        if plan.tools:
            return plan
    except Exception:
        pass
    return None


def plan_desktop_tools(
    query: str,
    selected_skills: dict | set[str],
    *,
    intent: str = "chat",
    needs_tools: bool = False,
    llm_fallback: bool = False,
) -> DesktopToolPlan:
    """生成桌面预检工具计划（规则优先，低置信可 LLM 补全）。"""
    skill_set = set(selected_skills.keys()) if isinstance(selected_skills, dict) else set(selected_skills)
    plan = DesktopToolPlan()

    preview_conf = score_obsidian_preview(query)
    plan.obsidian_preview_confidence = preview_conf
    plan.obsidian_preview = preview_conf >= _CONFIDENCE_RUN_THRESHOLD

    write_conf, write_args = score_obsidian_write(query)
    plan.obsidian_write_confidence = write_conf
    plan.obsidian_write = write_conf >= _CONFIDENCE_RUN_THRESHOLD

    if "shell" in skill_set:
        conf, args = score_shell_intent(query)
        if conf >= _CONFIDENCE_RUN_THRESHOLD:
            plan.tools.append(PreflightTool("shell", conf, args))

    if "github_ops" in skill_set:
        conf, args = score_github_intent(query)
        if conf >= _CONFIDENCE_RUN_THRESHOLD:
            plan.tools.append(PreflightTool("github_ops", conf, args))

    if "obsidian_read" in skill_set:
        conf, args = score_obsidian_read(query)
        if conf >= _CONFIDENCE_RUN_THRESHOLD:
            plan.tools.append(PreflightTool("obsidian_read", conf, args))

    if "obsidian_search" in skill_set and plan.obsidian_preview:
        plan.tools.append(PreflightTool(
            "obsidian_search", plan.obsidian_preview_confidence,
            {"keyword": query[:80], "max_results": 5},
        ))

    if "obsidian_write" in skill_set and plan.obsidian_write:
        plan.tools.append(PreflightTool("obsidian_write", plan.obsidian_write_confidence, write_args))

    max_conf = max((t.confidence for t in plan.tools), default=0.0)
    if (
        llm_fallback
        and max_conf < _CONFIDENCE_LLM_THRESHOLD
        and (needs_tools or intent in ("task", "project"))
        and skill_set & _PREFLIGHT_SKILLS
    ):
        llm_plan = _llm_plan_tools(query, skill_set)
        if llm_plan and llm_plan.tools:
            return llm_plan

    if llm_fallback:
        shell = plan.get("shell")
        if shell and not shell.args.get("command"):
            cmd = _llm_extract_shell_command(query)
            if cmd:
                shell.args["command"] = cmd
                shell.source = "llm_args"
                shell.confidence = max(shell.confidence, 0.72)

    return plan


def plan_desktop_turn(
    query: str,
    all_skills: dict | None = None,
    *,
    intent: str = "chat",
    needs_tools: bool = False,
    llm_fallback: bool = True,
) -> DesktopTurnPlan:
    """桌面一轮对话的完整工具规划：skill_router → 意图过滤 → 预检 ToolPlan。"""
    from core.skill_router import select_skills
    from skills.loader import load_skills

    skills = all_skills if all_skills is not None else load_skills()
    raw = select_skills(query, skills)
    filtered = filter_skills_for_intent(query, raw, intent=intent)
    tool_plan = plan_desktop_tools(
        query, filtered,
        intent=intent,
        needs_tools=needs_tools,
        llm_fallback=llm_fallback,
    )
    return DesktopTurnPlan(
        raw_selected=raw,
        filtered_skills=filtered,
        tool_plan=tool_plan,
        intent=intent,
    )
