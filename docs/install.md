# 安装说明

## 环境要求

- Python 3.11 或更高版本
- macOS（Linux 应该可以运行；Windows 未测试）
- 任何兼容 OpenAI 接口的 LLM API Key

## 自动安装

```bash
git clone https://github.com/Yivxer/Archer.git
cd Archer
bash install.sh
```

安装脚本会自动完成：

1. 创建 `~/.archer/` 并复制模板文件（SOUL、MEMORY、COVENANT、PRESENCE）
2. 生成 `archer.toml`，路径预填（你补充 API Key）
3. 在 `.venv/` 下创建 Python 虚拟环境
4. 从 `requirements.txt` 安装 Python 依赖
5. 将 `archer` 命令安装到 `/usr/local/bin/`（需要 sudo）

如果 `~/.archer/` 下已有文件，安装脚本**不会覆盖**，只会提示并跳过。

## 手动安装

```bash
cd Archer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 配置文件
cp templates/archer.example.toml archer.toml

# 灵魂档案
mkdir -p ~/.archer
cp templates/SOUL.template.md     ~/.archer/SOUL.md
cp templates/MEMORY.template.md   ~/.archer/MEMORY.md
cp templates/COVENANT.template.md ~/.archer/COVENANT.md
cp templates/PRESENCE.template.md ~/.archer/PRESENCE.md

# 编辑配置
open archer.toml   # 填入 API Key 和正确路径
```

## 配置说明

安装完成后，编辑 `archer.toml`。最少必填字段：

```toml
[api]
api_key  = "sk-你的密钥"
base_url = "https://api.deepseek.com/v1"   # 或任何兼容 OpenAI 接口的 URL
model    = "deepseek-chat"

[persona]
soul_path     = "/Users/你的用户名/.archer/SOUL.md"
memory_path   = "/Users/你的用户名/.archer/MEMORY.md"
covenant_path = "/Users/你的用户名/.archer/COVENANT.md"
presence_path = "/Users/你的用户名/.archer/PRESENCE.md"

[memory]
db_path = "/Users/你的用户名/.archer/archer.db"
```

完整配置选项见 `templates/archer.example.toml`。

## 可选依赖

### 向量检索（推荐）

开启语义记忆检索。未安装时，Archer 回退到全文搜索。

```bash
pip install sentence-transformers sqlite-vec
```

嵌入模型（约 120MB）在首次使用时下载并缓存到本地。

### MCP 工具服务器

通过 Model Context Protocol 连接外部工具服务器。

```bash
pip install mcp
```

然后在 `archer.toml` 中添加服务器配置：

```toml
[mcp]
enabled = true

[[mcp.servers]]
name    = "fetch"
command = "uvx"
args    = ["mcp-server-fetch"]
```

## 更新

```bash
git pull
pip install -r requirements.txt
```

你的 `~/.archer/` 文件和 `archer.toml` 不受更新影响。

## 卸载

```bash
sudo rm /usr/local/bin/archer
rm -rf .venv
# 可选：rm -rf ~/.archer
```
