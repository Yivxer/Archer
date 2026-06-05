# Archer 整体结构说明

> 更新日期：2026-05-08  
> 当前定位：一个项目根目录内维护三个使用端口：网页端、终端端、桌面客户端。共享能力层保留在根目录，避免三端重复实现。

## 一句话结构

```text
/Users/Yivxer/Projects/Archer/
├── terminal/          # 终端入口与本地 API 服务
├── client/desktop/    # 桌面客户端 Electron + React
├── web/               # 官网/网页端静态站点
├── core/              # 三端共用的核心能力
├── memory/            # 长期记忆、项目、任务、反馈等 SQLite 逻辑
├── skills/            # 终端/客户端可调用的工具技能
├── workflows/         # 可复用工作流
├── modes/             # 终端对话模式提示词
├── templates/         # 初始化模板
├── docs/              # 工程说明文档
└── tests/             # 自动化测试
```

根目录现在不是单一端口目录，而是 Archer 的总工作区。三个端口分别放在 `terminal/`、`client/desktop/`、`web/`，共享模块继续放在根目录的 `core/ memory/ skills/ workflows/`。

## 三个端口

| 端口 | 当前目录 | 主要用途 | 主要入口 |
|---|---|---|---|
| 终端端 | `/Users/Yivxer/Projects/Archer/terminal/` | 终端对话、记忆、技能、工作流、项目管理 | `terminal/archer.py` |
| 客户端 | `/Users/Yivxer/Projects/Archer/client/desktop/` | macOS 桌面客户端，调用本地 API | `client/desktop/src/main/index.ts` |
| 网页端 | `/Users/Yivxer/Projects/Archer/web/` | 官网、登录页、Soul 建档入口、静态部署 | `web/public/*.html` + `web/deploy.sh` |

根目录保留两个兼容入口：

```text
/Users/Yivxer/Projects/Archer/archer.py
/Users/Yivxer/Projects/Archer/archer_api.py
```

它们只是转发到 `terminal/` 下的真实实现。这样旧命令或旧测试不容易断，但后续修改真实代码时应优先改 `terminal/archer.py` 和 `terminal/archer_api.py`。

## 终端端状态

终端端是真正的 Archer 核心体验。

主要文件：

```text
terminal/archer.py        # 终端 REPL 主入口，处理 /memory /project /skill /work 等命令
terminal/archer_api.py    # 本地 HTTP API，供桌面客户端调用，默认端口 8765
archer.toml               # 本地配置，含模型、路径、账号、MCP、权限等
COVENANT.md               # 根契约，运行时会读取
PRESENCE.md               # 当前在场方式，运行时会读取
```

启动终端：

```bash
cd /Users/Yivxer/Projects/Archer
.venv/bin/python terminal/archer.py
```

或使用根目录兼容入口：

```bash
.venv/bin/python archer.py
```

启动客户端 API：

```bash
cd /Users/Yivxer/Projects/Archer
.venv/bin/python terminal/archer_api.py --port 8765
```

不要把 `COVENANT.md`、`PRESENCE.md` 当普通说明文档删除。当前 `archer.toml` 的 persona 配置会读取它们。

## 客户端状态

客户端是 Electron + React 桌面应用。它本身不重新实现记忆和技能，而是通过本地 API 连接终端能力层。

主要文件：

```text
client/desktop/package.json              # 客户端脚本、依赖、打包配置
client/desktop/src/main/index.ts         # Electron 主进程，负责启动窗口和 archer_api.py
client/desktop/src/preload/              # Electron preload
client/desktop/src/renderer/             # React UI
client/desktop/resources/                # App 图标等资源
client/desktop/out/                      # 构建产物，可再生成
client/desktop/release/                  # DMG 安装包，可再生成
```

常用命令：

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
npm run dev
npm run build
npm run build:mac
```

快捷安装入口已经放到项目根目录：

```bash
cd /Users/Yivxer/Projects/Archer
./install-client.sh
```

只构建安装包不安装：

```bash
./install-client.sh --build-only
```

客户端启动 API 的路径已经调整为：

```text
/Users/Yivxer/Projects/Archer/terminal/archer_api.py
```

所以后续如果客户端连不上，优先检查：

1. `client/desktop/src/main/index.ts` 里的 `apiScript` 和 `pythonBin`
2. `terminal/archer_api.py` 是否能单独启动
3. `archer.toml` 的 `[auth]`、`[memory]`、`[persona]` 路径是否正常

## 网页端状态

网页端现在已经并入 Archer 总目录：

```text
/Users/Yivxer/Projects/Archer/web/
```

主要文件：

```text
web/public/index.html       # 官网首页
web/public/archer.html      # Archer 网页入口原型：Soul 建档 + 首次回应
web/public/soul.html        # Soul 模型说明页
web/public/login.html       # Magic Link 登录页
web/public/auth.html        # 登录回调页
web/public/privacy.html     # 隐私政策
web/public/terms.html       # 用户协议
web/public/fonts/           # 字体资源
web/deploy.sh               # 静态站部署脚本
web/README.md               # 网页端维护说明
web/.impeccable.md          # 网页端设计上下文
```

部署命令：

```bash
cd /Users/Yivxer/Projects/Archer/web
./deploy.sh
```

部署脚本用自身位置计算 `public/`，所以现在移动到 `web/` 后仍然有效：

```bash
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUBLIC_DIR="$ROOT_DIR/public"
```

线上位置仍然是：

```text
https://www.yivxer.com
/var/www/archer/
ssh alias: archer
```

## 共享能力层

这些目录不属于某一个端口，而是终端和客户端共享的核心能力。网页端目前主要是静态站，不直接调用这些 Python 模块。

```text
core/        # LLM 调用、上下文构建、权限策略、工具循环、MCP、doctor、自检等
memory/      # SQLite 记忆、pending memories、项目、任务、反馈、主题、向量检索等
skills/      # 工具技能：shell、文件、网页、Obsidian、图片、文档、GitHub 等
workflows/   # 项目简报、URL 阅读笔记、语音日记、周报等复用流程
modes/       # coach / mirror / critic / operator 模式提示词
templates/   # SOUL / MEMORY / COVENANT / PRESENCE / archer.toml 模板
tests/       # Python 测试
```

## 修改时看哪里

| 想改什么 | 优先看哪里 |
|---|---|
| 终端命令、REPL 行为 | `terminal/archer.py` |
| 桌面客户端 API 返回值 | `terminal/archer_api.py` |
| 桌面窗口、自动启动 API | `client/desktop/src/main/index.ts` |
| 桌面 UI 页面 | `client/desktop/src/renderer/src/` |
| 官网首页和网页入口 | `web/public/index.html`、`web/public/archer.html` |
| 部署官网 | `web/deploy.sh` |
| 记忆数据库结构 | `memory/store.py` |
| 记忆检索 | `memory/retrieve.py`、`memory/vector_store.py` |
| 技能加载 | `skills/loader.py`、`skills/*.py` |
| 工具权限 | `core/policy.py`、`core/tool_loop.py` |
| 上下文注入 | `core/context.py` |
| 配置路径 | `archer.toml`、`core/paths.py` |

## 旧路径对照

| 旧路径 | 新路径 |
|---|---|
| `/Users/Yivxer/Projects/archer-site/` | `/Users/Yivxer/Projects/Archer/web/` |
| `/Users/Yivxer/Projects/archer-site/public/` | `/Users/Yivxer/Projects/Archer/web/public/` |
| `/Users/Yivxer/Projects/archer-site/deploy.sh` | `/Users/Yivxer/Projects/Archer/web/deploy.sh` |
| `/Users/Yivxer/Projects/Archer/desktop/` | `/Users/Yivxer/Projects/Archer/client/desktop/` |
| `/Users/Yivxer/Projects/Archer/desktop/release/` | `/Users/Yivxer/Projects/Archer/client/desktop/release/` |
| `/Users/Yivxer/Projects/Archer/desktop/resources/` | `/Users/Yivxer/Projects/Archer/client/desktop/resources/` |
| `/Users/Yivxer/Projects/Archer/archer.py` | `/Users/Yivxer/Projects/Archer/terminal/archer.py`（根目录保留兼容入口） |
| `/Users/Yivxer/Projects/Archer/archer_api.py` | `/Users/Yivxer/Projects/Archer/terminal/archer_api.py`（根目录保留兼容入口） |

## 可清理与不可清理

可以再生成，空间大但删除后需要重装/重构建：

```text
.venv/                         # Python 环境
client/desktop/node_modules/    # Node 依赖
client/desktop/out/             # 客户端构建产物
client/desktop/release/         # DMG 安装包
```

不要随便删除：

```text
archer.toml
COVENANT.md
PRESENCE.md
memory/archer.db
memory/sessions/
.artifacts/
web/public/
client/desktop/resources/
```

## 推荐后续整理规则

1. 新说明文档优先放 `docs/`，不要再散落到根目录。
2. 运行时人格/边界文件只保留根目录 `COVENANT.md`、`PRESENCE.md`，模板放 `templates/`。
3. 终端相关改动写到 `terminal/`、`core/`、`memory/`、`skills/`。
4. 客户端相关改动写到 `client/desktop/`。
5. 网页端相关改动写到 `web/`。
6. Obsidian 里的历史日志可以保留，但以后以这份结构说明作为当前路径基准。
