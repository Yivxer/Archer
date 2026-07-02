# Archer 项目 CLAUDE.md

## 项目概况

Archer：本地优先的个人 AI 智能体，支持长期记忆、灵魂档案、技能插件与安全边界。
规模：~75K 行 Python + ~8K 行 TS，103+ Python 测试，71+ TS 测试，43 Python 技能，12 对话模式。

## 三端架构

| 端 | 路径 | 技术栈 | 启动方式 |
|----|------|--------|----------|
| 终端（核心） | `~/Projects/Archer/` | Python + Rich + prompt_toolkit | `python archer.py` |
| 桌面客户端 | `~/Projects/Archer/desktop/` | Electron 39 + React 19 + TS 5.9 | `./install-client.sh` |
| 网页端 | `~/Projects/archer-site/public/` | 纯静态 HTML/CSS/JS | 线上 www.yivxer.com |

终端是核心，桌面和网页是"皮肤"。本地 API 桥接（端口 8765），不走云。

## 核心文件

| 文件 | 用途 |
|------|------|
| `archer.py` | 主入口 |
| `archer.toml` | 配置文件（运行时读取） |
| `archer_api.py` | 本地 HTTP API（端口 8765） |
| `core/tool_loop.py` | 工具循环，max_rounds 读 `cfg.tools.max_runes` |
| `memory/` | 长期记忆（SQLite + 向量检索） |
| `skills/` | 技能插件目录 |
| `modes/` | 对话模式目录 |
| `templates/` | 模板文件 |
| `COVENANT.md` | 行为边界契约（不可自动修改） |
| `PRESENCE.md` | 回应节奏和语气（不可自动修改） |

## 品牌

- Archer Ring 五色 conic-gradient
- 主色 #4dd9d4 流云青
- 字体 Comfortaa + LXGW WenKai
- 设计人格：安静/敏锐/克制/稳步生长

## 开发命令

```bash
# 终端启动
python archer.py

# 运行测试
bash run_tests.sh

# 桌面客户端安装
./install-client.sh

# API 启动
python archer_api.py
```

## 协作规则

- 终端是核心，修改终端逻辑时注意桌面端 API 调用是否受影响
- COVENANT.md 和 PRESENCE.md 不可在会话中自动修改，需人工审阅
- 记忆写入必须经审阅，不自动写入
- Shell 命令分级确认，危险命令直接拒绝
- 修改 Python 核心后运行 `bash run_tests.sh` 验证
- 修改桌面端后检查 TS 编译和 API 对接
- 人格边界：不替枫弋写代码，但可委派外部 AI

## 本地工具优先级

- 搜索文件名：fd
- 搜索代码/文本：rg
- 处理 JSON：jq
- 批量脚本：python3
- Git 操作：git / gh
- 图片处理：magick
- 文档转换：pandoc
