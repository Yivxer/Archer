# 初衍 Archer

> 本地优先的个人终端 AI 智能体。  
> 支持长期记忆、灵魂档案、技能插件与安全边界。

Archer 是一个运行在 macOS 终端中的个人 AI 智能体。  
它不是一次性问答工具，而是围绕**长期记忆、人格档案和技能系统**构建的本地 AI 伙伴——它记得你上次说了什么，知道你现在在做什么，并且在边界之内帮你思考和执行。

---

## Archer 是什么

Archer 的核心由四个部分组成：

- **长期记忆** — 使用 SQLite + 向量检索跨会话保存记忆，记忆需经你审阅后才会写入
- **灵魂档案** — 通过 `SOUL.md` 定义你是谁、你的价值观和工作方式，Archer 在决策类对话中读取它
- **根契约与在场方式** — `COVENANT.md` 约束行为边界，`PRESENCE.md` 定义 Archer 的回应节奏和语气，均不可自动修改
- **技能系统** — 内置 18 个技能（Shell、文件操作、Obsidian、网页抓取、PDF、OCR、GitHub 等），支持第三方插件和 MCP 服务器

---

## 设计原则

- **本地优先** — 数据默认留在你的机器上，不经过任何 Archer 服务器
- **记忆可审阅** — 所有记忆提案由你接受或拒绝，绝不自动写入
- **边界不可绕过** — COVENANT 和 PRESENCE 不可在会话中自动修改
- **命令分级确认** — 高风险 Shell 命令需要确认，危险命令直接拒绝
- **你拥有你的文件** — 配置、记忆、灵魂档案完全在你控制之下

---

## 你需要自己配置什么

Archer 不附带任何作者的私人数据。以下文件由你创建并填写：

| 文件 | 用途 |
|------|------|
| `SOUL.md` | 你是谁——价值观、工作模式、如何与 AI 协作 |
| `MEMORY.md` | 你现在在哪里——当前项目、关注点、开放问题 |
| `COVENANT.md` | Archer 不应越过的行为边界 |
| `PRESENCE.md` | Archer 与你互动的语气、节奏和回应方式 |
| `archer.toml` | API Key、路径和功能配置（本地保存，不提交 Git） |

所有文件的模板都在 `templates/` 目录下，安装脚本会自动复制到 `~/.archer/`。

---

## 环境要求

- Python 3.11+
- macOS（Linux 应该可以运行，Windows 未测试）
- 任何兼容 OpenAI 接口的 LLM API Key

可选（向量检索，推荐安装）：
- `sentence-transformers` — 语义记忆检索
- `sqlite-vec` — 向量 KNN 存储

可选（MCP 工具服务器）：
- `mcp` Python 包

---

## 安装

```bash
git clone https://github.com/Yivxer/Archer.git
cd Archer
bash install.sh
```

安装脚本会自动完成：
1. 创建 `~/.archer/` 并复制灵魂/记忆/契约/在场模板文件
2. 生成 `archer.toml`，路径预填（你补充 API Key）
3. 创建 Python 虚拟环境并安装依赖
4. 将 `archer` 命令安装到 `/usr/local/bin/`

如果 `~/.archer/` 下已有文件，安装脚本**不会覆盖**，只会提示跳过。

### 手动安装

```bash
cd Archer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp templates/archer.example.toml archer.toml
mkdir -p ~/.archer
cp templates/SOUL.template.md     ~/.archer/SOUL.md
cp templates/MEMORY.template.md   ~/.archer/MEMORY.md
cp templates/COVENANT.template.md ~/.archer/COVENANT.md
cp templates/PRESENCE.template.md ~/.archer/PRESENCE.md

# 编辑 archer.toml，填入 API Key 和路径
```

安装完成后目录结构如下：

```
~/.archer/
├── SOUL.md
├── MEMORY.md
├── COVENANT.md
├── PRESENCE.md
├── archer.toml
├── archer.db
├── sessions/
└── artifacts/
```

---

## 启动

```bash
archer
```

或直接用 Python：

```bash
python archer.py
```

启动后输入任何内容开始对话，用 `/help` 查看所有命令。

---

## 核心命令

```
/help                                   查看所有命令
/status                                 当前模型、模式、Token 用量、活跃项目
/mode coach|mirror|critic|operator      切换对话模式
/memory list|search|add                 管理长期记忆
/soul list|accept|reject                管理灵魂演化提议
/covenant view|propose                  查看或提议修改根契约
/presence view|suggest                  查看或调整在场方式
/project list|new|use                   管理项目
/reflect                                复盘当前会话
/doctor [--fix]                         系统自检（11 项检查）
/skill list|install                     管理技能
```

---

## 对话模式

用 `/mode` 切换：

| 模式 | 行为 |
|------|------|
| `coach` | 推动行动，总问"下一步是什么？" |
| `mirror` | 只提问，不给建议 |
| `critic` | 挑战你的假设和盲点 |
| `operator` | 简洁、任务导向，无额外内容 |

---

## 支持的 LLM 提供商

任何兼容 OpenAI 接口的 API 均可使用。在 `archer.toml` 中配置：

```toml
[api]
base_url = "https://api.deepseek.com/v1"
api_key  = "sk-..."
model    = "deepseek-chat"
```

支持：
- **DeepSeek**：`https://api.deepseek.com/v1`
- **OpenAI**：`https://api.openai.com/v1`
- **Ollama**（本地）：`http://localhost:11434/v1`
- **Together AI**、**Groq**、**Mistral** 等兼容端点

---

## 隐私说明

Archer 是本地优先设计：

- 所有记忆保存在本地 `~/.archer/archer.db`（SQLite）
- SOUL / MEMORY / COVENANT / PRESENCE 均在本地磁盘
- 会话记录保存为本地 JSON 文件（`~/.archer/sessions/`）
- 网络请求仅来自你配置的 LLM API 调用
- 没有任何 Archer 服务器，项目不附带作者个人数据

以下文件默认在 `.gitignore` 中，绝不会意外提交：

```
archer.toml   SOUL.md   MEMORY.md   COVENANT.md   PRESENCE.md
.env   *.db   sessions/   .artifacts/
```

详见 [docs/privacy.md](docs/privacy.md)。

---

## 安全模型

Shell 命令分四级风险管控：

| 级别 | 处理方式 | 示例 |
|------|----------|------|
| `low` | 直接执行 | `git status`、`ls`、只读命令 |
| `medium` | 需要确认 | 有副作用的常规命令 |
| `high` | 需要明确确认 + 说明原因 | `sudo`、递归删除、写入 Shell 配置 |
| `critical` | 直接拒绝 | `sudo rm -rf /`、`curl \| sh`、fork bomb |

详见 [docs/security.md](docs/security.md)。

---

## 适合谁

**更适合：**
- 想要本地 AI 长期伙伴的人
- 需要跨会话记忆和项目上下文的人
- 想把 AI 融入终端、Obsidian、本地文件系统工作流的人
- 想自己掌控数据、人格档案和边界的人

**不太适合：**
- 想要开箱即用网页聊天的人
- 不熟悉终端配置的人
- 不希望自己管理 API Key 和本地文件的人

---

## 自定义技能

```python
SKILL = {
    "name": "my_skill",
    "description": "做某件有用的事",
    "version": "1.0.0",
}

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "my_skill",
            "description": "做某件有用的事",
            "parameters": {
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "输入内容"}
                },
                "required": ["input"],
            },
        },
    }

def run(args: dict) -> str:
    return f"结果：{args['input']}"
```

用 `/skill install /path/to/my_skill.py` 安装。

---

## 文档

- [docs/install.md](docs/install.md) — 详细安装说明
- [docs/quickstart.md](docs/quickstart.md) — 第一次使用指引
- [docs/commands.md](docs/commands.md) — 完整命令手册
- [docs/memory-system.md](docs/memory-system.md) — 记忆系统说明
- [docs/soul-system.md](docs/soul-system.md) — 灵魂档案系统说明
- [docs/security.md](docs/security.md) — 安全模型
- [docs/privacy.md](docs/privacy.md) — 隐私说明

英文文档见 [README.en.md](README.en.md)。

---

## License

MIT
