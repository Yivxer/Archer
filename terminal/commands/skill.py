"""技能与模型命令。"""
from __future__ import annotations

from .registry import register
from rich.console import Console
from rich.table import Table
from skills.loader import load_skills
from skills.installer import install as skill_install, remove as skill_remove
from core.skill_router import select_skills
from terminal.ui import _brand_spinner
from pathlib import Path

console = Console()
_TOML_PATH = Path(__file__).resolve().parent.parent.parent / "archer.toml"

def _handle_skill(parts: list[str], skills: dict) -> dict:
    sub = parts[1] if len(parts) > 1 else ""
    arg = " ".join(parts[2:])
    match sub:
        case "list":
            _skill_list(skills)
        case "install":
            if not arg:
                console.print("[yellow]用法：/skill install <本地路径 或 GitHub URL>[/yellow]")
            else:
                try:
                    name = skill_install(arg)
                    skills = load_skills()
                    console.print(f"[green]技能「{name}」安装成功。[/green]")
                except Exception as e:
                    console.print(f"[red]安装失败：{e}[/red]")
        case "remove":
            if not arg:
                console.print("[yellow]用法：/skill remove <名字>[/yellow]")
            else:
                try:
                    skill_remove(arg)
                    skills = load_skills()
                    console.print(f"[dim]技能「{arg}」已卸载。[/dim]")
                except Exception as e:
                    console.print(f"[red]卸载失败：{e}[/red]")
        case "info":
            _skill_info(skills, arg)
        case "suggest":
            try:
                from memory.skill_gap import summary as gap_summary, apply_hints
                console.print(gap_summary())
                if arg.strip() == "--apply":
                    n = apply_hints()
                    console.print(f"[green]已写入 {n} 条路由规则到 learned_routes.json。[/green]" if n else "[dim]没有新规则可写入。[/dim]")
                elif arg.strip() == "":
                    console.print("[dim]加 --apply 将建议写入路由规则。[/dim]")
            except Exception as e:
                console.print(f"[yellow]缺口分析失败：{e}[/yellow]")
        case _:
            console.print("[dim]子命令：list · install · remove · info · suggest[/dim]")
    return skills

def _handle_model(parts: list[str], cfg: dict):
    models  = cfg["api"].get("models", [cfg["api"]["model"]])
    current = cfg["api"]["model"]
    if len(parts) < 2:
        console.print(f"\n  当前模型：[bold #c44e00]{current}[/]")
        for m in models:
            marker = "  [dim]←[/]" if m == current else ""
            console.print(f"  [#c44e00]{m}[/]{marker}")
        console.print(f"\n  用法：/model <模型名>")
        return
    new_model = parts[1]
    cfg["api"]["model"] = new_model
    console.print(f"[bold #c44e00]已切换至 {new_model}[/]")

def _handle_mode(parts: list[str], cfg: dict):
    modes = cfg.get("persona", {}).get("modes", {})
    file_modes = _list_file_modes(cfg)
    # 合并 toml 定义 + 文件模式，文件模式优先（去重）
    valid = list(dict.fromkeys(file_modes + list(modes.keys())))

    # /mode create <name> [<描述>]
    if len(parts) >= 3 and parts[1] == "create":
        mode_name = parts[2]
        modes_dir = cfg.get("persona", {}).get("modes_dir", "")
        if not modes_dir:
            console.print("[yellow]archer.toml 未配置 modes_dir，无法创建模式文件[/yellow]")
            return
        mode_file = Path(modes_dir).expanduser() / f"{mode_name}.md"
        if mode_file.exists():
            console.print(f"[yellow]模式 {mode_name} 已存在：{mode_file}[/yellow]")
            return
        template = f"""[模式：{mode_name}]

核心任务：（填写这个模式的核心目标）

在场风格：
-

禁止：
-

换挡信号：
（描述何时切换到这个模式）
"""
        mode_file.write_text(template, encoding="utf-8")
        console.print(f"[green]已创建模式文件：{mode_file}[/green]")
        console.print(f"[dim]编辑该文件后，用 /mode {mode_name} 切换[/dim]")
        return

    # /mode auto —— 恢复每轮自动选择姿态
    if len(parts) >= 2 and parts[1] == "auto":
        cfg["persona"]["mode_auto"] = True
        _persist_mode_auto(True)
        console.print("[dim]已开启自动姿态：每轮按对话内容自动选择 mode。[/dim]")
        return

    if len(parts) < 2 or parts[1] not in valid:
        auto = cfg["persona"].get("mode_auto", True)
        current = cfg["persona"].get("current_mode", cfg["persona"].get("default_mode", "coach"))
        if auto:
            console.print(f"  当前模式：[bold #c44e00]自动[/]  [dim]（基线 {cfg['persona'].get('default_mode', 'listener')}）[/dim]")
        else:
            console.print(f"  当前模式：[bold #c44e00]{current}[/]  [dim]（已锁定）[/dim]")
        mode_labels = []
        for k in valid:
            if k in modes:
                label = f"[cyan]{k}[/cyan]（{modes[k].get('name', k)}）"
            else:
                label = f"[cyan]{k}[/cyan]（文件）"
            mode_labels.append(label)
        console.print(f"  可用模式：{'  '.join(mode_labels)}")
        console.print(f"  [dim]/mode <名称>  锁定模式   ·   /mode auto  恢复自动   ·   /mode create <名称>  新建[/dim]")
        return

    mode = parts[1]
    cfg["persona"]["current_mode"] = mode
    cfg["persona"]["mode_auto"] = False
    mode_name_label = modes[mode].get("name", mode) if mode in modes else mode
    console.print(f"[dim]已锁定至 {mode_name_label} 模式（/mode auto 可恢复自动）[/dim]")
    _persist_mode(mode)
    _persist_mode_auto(False)

def _handle_doctor(parts: list[str], cfg: dict, skills: dict):
    from core.doctor import run_checks, apply_fixes, Level

    do_fix = len(parts) > 1 and parts[1] == "--fix"
    from datetime import datetime as _dt
    console.print(f"\n[bold cyan]Archer Doctor Report[/bold cyan]  [dim]{_dt.now().strftime('%Y-%m-%d %H:%M')}[/dim]\n")

    results = run_checks(cfg, skills)

    _STYLE = {
        Level.OK:    ("[green]OK   [/green]",    "green"),
        Level.INFO:  ("[cyan]INFO [/cyan]",       "cyan"),
        Level.WARN:  ("[yellow]WARN [/yellow]",   "yellow"),
        Level.ERROR: ("[red]ERROR[/red]",         "red"),
    }

    for r in results:
        badge, _ = _STYLE[r.level]
        console.print(f"  {badge}  [bold]{r.name:<12}[/bold]{r.message}")

    warns  = sum(1 for r in results if r.level == Level.WARN)
    errors = sum(1 for r in results if r.level == Level.ERROR)
    total  = len(results)

    console.print()
    if errors:
        console.print(f"  [red]✗ {errors} 个错误，{warns} 个警告[/red]（共 {total} 项）")
    elif warns:
        console.print(f"  [yellow]△ {warns} 个警告[/yellow]（共 {total} 项正常）")
    else:
        console.print(f"  [green]✓ 全部 {total} 项检查通过[/green]")

    if do_fix:
        console.print()
        fixes = apply_fixes(results)
        if fixes:
            for msg in fixes:
                console.print(f"  [cyan]{msg}[/cyan]")
        else:
            console.print("  [dim]没有可自动修复的问题。[/dim]")
    elif warns or errors:
        fixable = [r for r in results if r.fix_fn is not None and r.level in (Level.WARN, Level.ERROR)]
        if fixable:
            console.print(f"\n  [dim]运行 /doctor --fix 可自动修复 {len(fixable)} 个问题。[/dim]")

def _handle_login(cfg: dict):
    """archer login: send magic link, wait for token paste, save to archer.toml."""
    import urllib.request
    import urllib.parse

    supabase_url = cfg.get("auth", {}).get("supabase_url", "")
    supabase_key = cfg.get("auth", {}).get("supabase_key", "")
    if not supabase_url or not supabase_key:
        console.print("[red]archer.toml 缺少 [auth] supabase_url / supabase_key，无法登录。[/red]")
        return

    console.print()
    console.print("  [bold cyan]Archer 登录[/bold cyan]")
    console.print("  [dim]通过邮箱 Magic Link 完成身份验证。[/dim]")
    console.print()

    from core.input import prompt as _inp
    console.print("  [dim]邮箱地址：[/dim]")
    email = _inp().strip()
    if not email or "@" not in email:
        console.print("[red]邮箱格式不对。[/red]")
        return

    redirect = "https://www.yivxer.com/auth.html"
    payload = json.dumps({"email": email, "options": {"emailRedirectTo": redirect}}).encode()
    req = urllib.request.Request(
        f"{supabase_url.rstrip('/')}/auth/v1/otp",
        data=payload,
        headers={
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as e:
        console.print(f"[red]发送失败：{e}[/red]")
        return

    console.print(f"  [dim]登录链接已发送到 [bold]{email}[/bold]。[/dim]")
    console.print(f"  [dim]点击邮件中的链接，浏览器会跳转到 auth.html。[/dim]")
    console.print(f"  [dim]复制页面上显示的 Token，粘贴到下方。[/dim]")
    console.print()

    console.print("  [dim]粘贴 Token：[/dim]")
    token = _inp().strip()
    if not token or len(token) < 20:
        console.print("[yellow]Token 看起来不对，已取消。[/yellow]")
        return

    # Validate token and get user info
    try:
        req2 = urllib.request.Request(
            f"{supabase_url.rstrip('/')}/auth/v1/user",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {token}",
            },
        )
        with urllib.request.urlopen(req2, timeout=10) as resp2:
            user_data = json.loads(resp2.read())
        archer_id = user_data.get("id", "")
        user_email = user_data.get("email", email)
    except Exception as e:
        console.print(f"[red]Token 验证失败：{e}[/red]")
        return

    # Save to archer.toml
    try:
        def _set_toml_key(text: str, key: str, value: str) -> str:
            return re.sub(
                rf'^({key}\s*=\s*).*$',
                lambda m: f'{m.group(1)}"{value}"',
                text, flags=re.MULTILINE
            )
        toml_text = _TOML_PATH.read_text(encoding="utf-8")
        toml_text = _set_toml_key(toml_text, "access_token", token)
        toml_text = _set_toml_key(toml_text, "archer_id", archer_id)
        _TOML_PATH.write_text(toml_text, encoding="utf-8")
    except Exception as e:
        console.print(f"[red]写入 archer.toml 失败：{e}[/red]")
        return

    console.print()
    console.print(f"  ✅ [green]登录成功[/green]  {user_email}")
    console.print(f"  [dim]Archer ID: {archer_id[:8]}…[/dim]")
    console.print(f"  [dim]Token 已写入 archer.toml [auth] access_token。[/dim]")
    console.print()

def _persist_mode(mode: str) -> None:
    """将 current_mode 写入 archer.toml，插入或替换 [persona] 段中的对应行。"""
    text = _TOML_PATH.read_text(encoding="utf-8")
    new_line = f'current_mode = "{mode}"'
    if re.search(r'^current_mode\s*=', text, re.MULTILINE):
        text = re.sub(r'^current_mode\s*=.*$', new_line, text, flags=re.MULTILINE)
    else:
        text = re.sub(r'^(default_mode\s*=.*)$', rf'\1\n{new_line}', text, flags=re.MULTILINE)
    _TOML_PATH.write_text(text, encoding="utf-8")


def _persist_mode_auto(flag: bool) -> None:
    """将 mode_auto 写入 archer.toml [persona] 段，控制是否每轮自动选姿态。"""
    text = _TOML_PATH.read_text(encoding="utf-8")
    new_line = f'mode_auto = {"true" if flag else "false"}'
    if re.search(r'^mode_auto\s*=', text, re.MULTILINE):
        text = re.sub(r'^mode_auto\s*=.*$', new_line, text, flags=re.MULTILINE)
    else:
        text = re.sub(r'^(default_mode\s*=.*)$', rf'\1\n{new_line}', text, flags=re.MULTILINE)
    _TOML_PATH.write_text(text, encoding="utf-8")

def _list_file_modes(cfg: dict) -> list[str]:
    """返回 modes_dir 中已存在的 .md 模式文件名（无扩展名）。"""
    modes_dir = cfg.get("persona", {}).get("modes_dir", "")
    if not modes_dir:
        return []
    d = Path(modes_dir).expanduser()
    return [p.stem for p in d.glob("*.md")] if d.is_dir() else []

def _skill_list(skills: dict):
    if not skills:
        console.print("[dim]尚未安装任何技能。[/dim]")
        return
    t = Table(show_header=True, header_style="bold cyan", box=None)
    t.add_column("名称", style="cyan")
    t.add_column("描述")
    t.add_column("版本", style="dim", width=8)
    for name, mod in skills.items():
        meta = mod.SKILL
        t.add_row(name, meta.get("description", ""), meta.get("version", ""))
    console.print(t)

def _skill_info(skills: dict, name: str):
    if not name:
        console.print("[yellow]用法：/skill info <名字>[/yellow]")
        return
    mod = skills.get(name)
    if not mod:
        console.print(f"[yellow]技能不存在：{name}[/yellow]")
        return
    meta = mod.SKILL
    console.print(f"\n  [bold cyan]{meta['name']}[/bold cyan]  v{meta.get('version','?')}")
    console.print(f"  {meta.get('description','')}")
    if meta.get("author"):
        console.print(f"  [dim]作者：{meta['author']}[/dim]")
    schema = mod.schema()["function"]
    params = schema.get("parameters", {}).get("properties", {})
    if params:
        console.print("\n  参数：")
        for k, v in params.items():
            console.print(f"    [cyan]{k}[/cyan]  {v.get('description','')}")


# ── 命令注册 ──────────────────────────────────────────────────────────────────

def _cmd_skill(ctx):
    new_skills = _handle_skill(ctx['parts'], ctx['skills'])
    ctx['state']['skills'] = new_skills


def _cmd_model(ctx):
    _handle_model(ctx['parts'], ctx['cfg'])


def _cmd_mode(ctx):
    _handle_mode(ctx['parts'], ctx['cfg'])


def _cmd_doctor(ctx):
    _handle_doctor(ctx['parts'], ctx['cfg'], ctx['skills'])


def _cmd_login(ctx):
    _handle_login(ctx['cfg'])


register("/skill", _cmd_skill, "管理技能插件")
register("/model", _cmd_model, "查看/切换模型")
register("/mode", _cmd_mode, "切换对话模式")
register("/doctor", _cmd_doctor, "自检系统状态")
register("/login", _cmd_login, "邮箱 Magic Link 登录")
