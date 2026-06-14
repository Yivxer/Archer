"""
P2-B: 技能路由过滤

根据用户输入关键词动态决定暴露哪些技能，减少每次请求携带的 tool schema tokens。
无关键词命中 → 返回 {} → 主循环走纯流式，跳过全部 tool schema。
"""
import json
import re
from pathlib import Path
from typing import Any, Mapping

_LEARNED_ROUTES_PATH = Path(__file__).parent.parent / "learned_routes.json"


def _load_learned() -> list[tuple[frozenset, list[str]]]:
    if not _LEARNED_ROUTES_PATH.exists():
        return []
    try:
        data = json.loads(_LEARNED_ROUTES_PATH.read_text())
        return [(frozenset(entry["skills"]), entry["keywords"]) for entry in data]
    except Exception:
        return []


def save_learned(entries: list[dict]):
    """写入学习到的路由规则，entries: [{skills:[...], keywords:[...]}]"""
    _LEARNED_ROUTES_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2))

# (技能名集合, 触发关键词列表)  —— 大小写不敏感匹配
_ROUTES: list[tuple[frozenset, list[str]]] = [
    (
        frozenset({"file_ops", "file_search"}),
        [
            "文件", "目录", "文件夹", "路径", "新建文件", "删除文件", "创建文件", "读取文件",
            # 代码文件相关
            ".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".html", ".css", ".json",
            ".toml", ".yaml", ".yml", ".md", ".txt", ".log", ".sh", ".env",
            # 项目操作
            "打开文件", "看一下文件", "查看文件", "修改文件", "编辑文件", "更新文件",
            "读取这个", "读一下", "看看这个", "看这个文件",
        ],
    ),
    (
        frozenset({"shell"}),
        ["shell", "bash", "终端", "命令行", "运行命令", "执行命令", "执行 ", "运行 "],
    ),
    (
        frozenset({"obsidian_read", "obsidian_write", "obsidian_search"}),
        [
            "obsidian", "笔记", "知识库", "vault",
            # 常用文件名/目录名
            "成长计划", "构建日志", "网页端构建", "客户端构建", "终端构建",
            "soul.md", "memory.md", "next.md", "prompts.md",
            "archer-skills", "archer技能", "自创技能",
            # 动作描述
            "读obsidian", "写obsidian", "记录到obsidian", "写入笔记",
            "打开笔记", "查看笔记", "找笔记", "笔记里", "icloud",
            "读取", "读一下", "读这篇",
        ],
    ),
    (
        frozenset({"web_fetch"}),
        ["网页", "网址", "网站", "抓取链接", "打开链接"],
    ),
    (
        frozenset({"github_ops"}),
        [
            "github", "git ", "gh ", "repo", "repository", "pull request",
            "issue", "pr", "仓库", "代码库", "列出 issue", "创建 issue", "查看仓库",
        ],
    ),
    (
        frozenset({"code_search"}),
        [
            "找代码", "查函数", "定位代码", "搜索代码", "代码里找", "找一下函数",
            "grep", "找哪行", "在哪里定义", "哪里实现", "实现在哪", "逻辑在哪",
        ],
    ),
    (
        frozenset({"code_search", "file_ops"}),
        [
            "找到后读取", "定位并读取", "找到邀请码", "找到验证逻辑", "找到这个函数",
            "看看代码", "看一下代码", "看代码", "读代码", "查看代码", "代码里",
            "源码", "src/", "components/", "pages/", "utils/",
        ],
    ),
    (
        frozenset({"code_search", "file_ops", "shell"}),
        [
            "继续做", "继续完成", "继续处理", "接着做", "帮我改", "帮我修",
            "帮我写", "帮我实现", "帮我加", "帮我优化",
            # 项目类型关键词
            "项目", "前端", "后端", "网站", "小程序", "app", "组件",
            "接口", "api", "路由", "样式", "布局", "功能",
            # 常见框架
            "react", "vue", "next", "nuxt", "tailwind", "vite", "webpack",
            "typescript", "javascript", "python", "rust", "go",
            # Archer 自身项目
            "archer", "archer.toml", "archer.py",
        ],
    ),
    (
        frozenset({"screenshot"}),
        ["截图", "screenshot", "屏幕截图"],
    ),
    (
        frozenset({"image_ocr"}),
        ["ocr", "图片文字", "识别文字", "image_ocr"],
    ),
    (
        frozenset({"image_analysis", "image_ocr"}),
        ["图片", "图像", "看一下", "分析图", "这张图", "这个图", "图表", "看图", "图里", "照片"],
    ),
    (
        frozenset({"clipboard"}),
        ["剪贴板", "clipboard", "复制内容", "粘贴内容", "pbpaste", "pbcopy"],
    ),
    (
        frozenset({"pdf_reader"}),
        [".pdf", "pdf文件", "pdf文档"],
    ),
    (
        frozenset({"rss_reader"}),
        ["rss", "订阅源"],
    ),
    (
        frozenset({"weather"}),
        ["天气", "weather", "气温"],
    ),
    (
        frozenset({"whisper_transcribe"}),
        ["录音", "语音转文字", "音频文件", "whisper"],
    ),
    (
        frozenset({"apple_reminders"}),
        ["提醒事项", "苹果提醒", "reminders"],
    ),
    (
        frozenset({"summarize", "humanizer"}),
        ["总结这个", "摘要这个", "humanize", "总结", "概括", "归纳", "摘要"],
    ),
    (
        frozenset({"hugo_blog", "shell"}),
        [
            "hugo", "博客", "博客发布", "写文章", "发文章", "更新博客", "发布文章",
            "部署", "build", "构建", "rsync", "推送", "上线", "deploy", "publish",
            "枫弋札记", "folium", "发布到", "部署到", "同步到服务器", "推送到服务器",
            "博文", "发博文", "写博文",
        ],
    ),
    (
        frozenset({"page_screenshot"}),
        ["网页截图", "页面截图", "截网页", "看页面", "页面效果", "看看效果", "看看页面"],
    ),
    (
        frozenset({"page_screenshot", "image_analysis"}),
        ["页面长什么样", "页面设计", "优化页面", "css效果", "预览效果", "看看设计"],
    ),
    (
        frozenset({"site_check"}),
        ["部署验证", "检查网站", "网站是否正常", "部署后检查", "rss更新", "检查rss", "站点状态"],
    ),
    (
        frozenset({"hugo_blog", "site_check", "shell"}),
        ["部署并验证", "发布并检查", "deploy", "上线验证", "部署验证", "部署后检查"],
    ),
    (
        frozenset({"weekly_review"}),
        ["周复盘", "weekly review", "weekly_review"],
    ),
    (
        frozenset({"installer"}),
        ["安装技能", "install skill"],
    ),
    # ── 新增技能路由（20260503）──────────────────────────────────────────────────
    (
        frozenset({"code_edit"}),
        [
            "修改代码", "替换代码", "改这段", "改这行", "把这段改成", "替换这里",
            "str_replace", "patch", "编辑代码", "删除这段", "插入代码",
            "改一下", "帮我改", "修改这个函数", "把这里改成",
        ],
    ),
    (
        frozenset({"code_edit", "code_search", "file_ops"}),
        [
            "找到并修改", "找到并替换", "找到后改", "定位后修改",
            "改 index.ts", "改 main.ts", "改 archer.py", "改 archer.toml",
            "修改 html", "修改 css", "修改样式", "改一下样式",
        ],
    ),
    (
        frozenset({"npm_run"}),
        [
            "npm", "pnpm", "yarn", "bun", "install dependencies", "npm install",
            "npm run", "npm build", "构建前端", "前端构建", "打包",
            "重新构建", "重新打包", "跑一下构建", "build 一下", "yarn install",
        ],
    ),
    (
        frozenset({"npm_run", "code_edit", "code_search", "file_ops"}),
        [
            "改完后构建", "改好后打包", "修改后 build", "修改后重新构建",
            "electron", "桌面端", "客户端", "desktop",
        ],
    ),
    (
        frozenset({"web_search"}),
        [
            "搜索一下", "搜一下", "查一下", "帮我查", "查查看",
            "怎么用", "怎么写", "怎么配置", "怎么解决", "怎么修",
            "报错", "error", "exception", "为什么", "what is", "how to",
            "有没有", "最新版", "官方文档", "api 文档",
        ],
    ),
    (
        frozenset({"web_search", "web_fetch"}),
        [
            "查文档", "查官方文档", "找文档", "看文档",
            "查 npm 包", "这个库怎么用", "这个 api 怎么用",
        ],
    ),
    (
        frozenset({"process_manager"}),
        [
            "启动服务", "启动 api", "启动后端", "开启服务", "跑起来",
            "停止服务", "关掉服务", "kill 进程", "重启服务",
            "archer api", "archer_api", "本地服务", "后台服务",
            "服务状态", "进程状态", "服务跑没跑", "服务在跑吗",
        ],
    ),
    # ── 20260503 新增技能路由 ──────────────────────────────
    (
        frozenset({"browser_automation"}),
        [
            "浏览器", "打开网页", "浏览器自动化", "网页截图", "自动化浏览器",
            "点击网页", "输入到网页", "网页滚动", "无头浏览器",
        ],
    ),
    (
        frozenset({"docx_editor"}),
        [
            "word", "docx", "新建 word", "word 文档", "编辑 word",
            "创建文档", "写 word", "导出 word", "生成报告 word",
        ],
    ),
    (
        frozenset({"task_manager"}),
        [
            "创建任务", "任务管理", "待办", "检查清单", "任务进度",
            "更新任务", "完成任务", "查看任务", "work item",
        ],
    ),
    (
        frozenset({"image_generator"}),
        [
            "生成图片", "AI 画图", "图片生成", "dall-e", "AI 绘图",
            "配图", "生成配图", "AI 生成图片", "文生图",
        ],
    ),
    (
        frozenset({"frontend_dev"}),
        [
            "前端页面", "生成网页", "UI 界面", "前端开发", "写页面",
            "落地页", "landing page", "生成组件", "react 组件",
        ],
    ),
    (
        frozenset({"market_research"}),
        [
            "市场调研", "行业分析", "竞争分析", "调研报告", "市场分析",
            "竞争格局", "市场趋势", "用户画像", "market research",
        ],
    ),
    (
        frozenset({"video_script"}),
        [
            "视频脚本", "短视频脚本", "脚本生成", "抖音脚本", "快手脚本",
            "b站脚本", "分镜脚本", "视频文案", "口播稿",
        ],
    ),
    (
        frozenset({"workflow_automation"}),
        [
            "自动化", "工作流", "zapier", "n8n", "自动化配置",
            "定时触发", "自动同步", "自动化流程", "webhook 触发",
        ],
    ),
    (
        frozenset({"code_review"}),
        [
            "代码审查", "code review", "审查代码", "代码评审", "CR",
            "帮我看看代码", "这段代码有问题吗", "review 一下",
        ],
    ),
]

# 绝对路径 / 家目录路径 / 相对路径 → 触发 file_ops + file_search
_PATH_RE = re.compile(r"(?:^|\s)(~|/)[\w./\-_]+|(?:^|\s)\./[\w./\-_]+")

# URL → 触发 web_fetch
_URL_RE = re.compile(r"https?://", re.IGNORECASE)


def select_skills(user_input: str, all_skills: Mapping[str, Any]) -> dict:
    """
    返回本轮应暴露给模型的技能子集。

    - 按关键词和正则匹配用户输入
    - 只返回 all_skills 中实际存在的技能
    - 无命中 → 返回 {}，主循环走 _stream 跳过全部 tool schema
    """
    if not user_input or not all_skills:
        return {}

    lower = user_input.lower()
    selected: set[str] = set()

    # URL 快速检测
    if _URL_RE.search(user_input):
        selected.add("web_fetch")
        selected.add("web_search")

    # 学习路由
    for skill_names, keywords in _load_learned():
        if any(kw in lower for kw in keywords):
            selected.update(skill_names)

    # 路径快速检测
    if _PATH_RE.search(user_input):
        selected.update({"file_ops", "file_search"})

    # 关键词匹配
    for skill_names, keywords in _ROUTES:
        if any(kw in lower for kw in keywords):
            selected.update(skill_names)

    # ── 中文 ngram 回退：修复"写一篇关于AI的文章"不匹配"写文章"这类分词盲点 ──
    _CJK_RE = re.compile(r'[\u4e00-\u9fff]')
    input_ngrams: set[str] | None = None  # lazy init

    def _ensure_input_ngrams() -> set[str]:
        nonlocal input_ngrams
        if input_ngrams is None:
            input_ngrams = set()
            for n in (2, 3):
                for i in range(len(user_input) - n + 1):
                    segment = user_input[i:i + n]
                    if _CJK_RE.search(segment):
                        input_ngrams.add(segment)
        return input_ngrams

    for skill_names, keywords in _ROUTES:
        if skill_names.issubset(selected):
            continue  # 已通过精确匹配命中
        for kw in keywords:
            if kw in lower:
                continue  # 这个关键词已精确匹配，跳过
            # 只对纯中文短关键词做 ngram 回退（无空格/英文/数字，长度 2-8）
            if len(kw) < 2 or len(kw) > 8 or ' ' in kw or not _CJK_RE.search(kw):
                continue
            kw_ngrams = set()
            for n in (2, 3):
                for i in range(len(kw) - n + 1):
                    kw_ngrams.add(kw[i:i + n])
            if not kw_ngrams:
                continue
            input_set = _ensure_input_ngrams()
            overlap = kw_ngrams & input_set
            # ngram 回退应宽松：短关键词只需 1 个 ngram 重叠
            min_overlap = 1 if len(kw) <= 4 else max(1, len(kw_ngrams) * 0.4)
            if len(overlap) >= min_overlap:
                selected.update(skill_names)
                break

    return {name: all_skills[name] for name in selected if name in all_skills}


def auto_match_skills(
    user_input: str,
    *,
    intent: str | None = None,
    all_skills: Mapping[str, Any] | None = None,
    limit: int = 6,
) -> list[str]:
    """Return ranked skill names for orchestration hints (keyword + router merge)."""
    if not user_input or not user_input.strip():
        return []

    from skills.loader import get_skill_meta, load_skills

    registry = all_skills if all_skills is not None else load_skills()
    if not registry:
        return []

    lower = user_input.lower()
    scores: dict[str, int] = {}

    for name in select_skills(user_input, registry):
        scores[name] = scores.get(name, 0) + 5

    for name in registry:
        meta = registry.get_meta(name) if hasattr(registry, "get_meta") else get_skill_meta(registry[name])
        if meta is None or not meta.auto_trigger:
            continue
        for keyword in meta.keywords:
            if keyword.lower() in lower:
                scores[name] = scores.get(name, 0) + 3
        if intent in {"task", "project"} and meta.risk in {"medium", "high", "critical"}:
            scores[name] = scores.get(name, 0) + 1

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [name for name, score in ranked[:limit] if score > 0]
