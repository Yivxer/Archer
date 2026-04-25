# ArcherOS · 部署记录

## Phase 1 · MVP（2026-04-25）

### 目标
从终端跑起来。DeepSeek API + SOUL.md 注入 + 会话历史保存。

### 环境
- macOS Darwin 25.4.0
- Python 3.14.3
- DeepSeek API（deepseek-chat）

### 安装步骤

```bash
cd /Users/Yivxer/Projects/Archer

# 安装依赖
pip3 install -r requirements.txt

# 配置
cp archer.toml.example archer.toml
# 编辑 archer.toml，填入 DeepSeek API key 和正确路径

# 运行
python3 archer.py
```

### 文件结构
```
Archer/
├── archer.py              # CLI 主入口
├── archer.toml            # 配置（不进 git）
├── archer.toml.example    # 配置模板
├── requirements.txt
├── core/
│   ├── llm.py             # DeepSeek API 封装（流式）
│   ├── context.py         # SOUL + MEMORY 注入 → system prompt
│   └── session.py         # 会话管理 + 保存
├── memory/
│   └── sessions/          # 每次会话 JSON（不进 git）
└── skills/                # 技能插件（Phase 2）
```

### 可用命令
| 命令 | 说明 |
|------|------|
| `/help` | 查看命令 |
| `/save` | 保存当前会话 |
| `/clear` | 清空对话历史 |
| `/exit` | 退出并保存 |

---

## Phase 2 · 持久记忆（2026-04-25）

- SQLite 跨 session 记忆存储（`memory/archer.db`）
- 对话结束自动提炼关键记忆（LLM 提炼）
- 检索时按相关性注入 system prompt
- `/memory list / search / add / delete`

## Phase 3 · 技能系统（2026-04-25）

### 架构
- `skills/loader.py` — 扫描目录自动加载（有 SKILL + schema + run 即激活）
- `skills/installer.py` — 支持本地路径和 GitHub URL 安装
- `core/llm.py` — `call_with_tools()` 支持 function calling
- Archer 自动判断何时调用技能，无需手动触发

### 内置技能
| 技能 | 说明 |
|------|------|
| shell | 执行终端命令 |
| file_ops | 读写本地文件 |

### 技能命令
| 命令 | 说明 |
|------|------|
| `/skill list` | 列出已安装技能 |
| `/skill install <路径或URL>` | 安装技能（支持 GitHub） |
| `/skill remove <名字>` | 卸载技能 |
| `/skill info <名字>` | 技能详情 |

### 安装第三方技能示例
```bash
# 从 GitHub 安装
/skill install https://github.com/user/archer-skills/blob/main/flomo.py

# 从本地文件安装
/skill install /path/to/my_skill.py
```

### 自定义技能格式
```python
SKILL = {"name": "my_skill", "description": "...", "version": "1.0.0"}

def schema() -> dict:
    return {"type": "function", "function": {"name": "my_skill", "description": "...", "parameters": {...}}}

def run(args: dict) -> str:
    return "结果"
```
