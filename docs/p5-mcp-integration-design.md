# P5.11 MCP 深度集成 — 设计文档

日期：2026-06-13  
状态：阶段二（实现完成）

## 配置格式（`archer.toml`）

```toml
[mcp]
enabled = true
reconnect_attempts = 2

# 本地 stdio（默认 transport=stdio）
[[mcp.servers]]
name = "filesystem"
enabled = true
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
permissions = { tools = { read_file = "read", write_file = "write" } }

# 远程 streamable HTTP
[[mcp.servers]]
name = "remote"
enabled = true
transport = "streamable_http"
url = "https://mcp.example.com/mcp"
auth_type = "bearer"              # bearer | header | none
auth_token_env = "ARCHER_MCP_TOKEN"
headers = { "X-Team" = "archer" }
reconnect = true
permissions = { tools = { search = "read", publish = "write" }, allowed_domains = ["mcp.example.com"] }
```

权限采用拒绝优先：server 必须显式启用，工具必须声明为 `read` 或 `write`，HTTP(S) 参数与远程 endpoint 必须命中域名白名单。`write` 能力始终进入用户确认流程；连接后未授权的工具不会进入 Archer 技能注册表，执行前仍会再次复核权限和域名。

## 传输

| transport | 实现 |
|-----------|------|
| `stdio`（默认） | `mcp.client.stdio.stdio_client` |
| `streamable_http` | `mcp.client.streamable_http.streamable_http_client` + 可选 Bearer/header auth |

`connect_remote_mcp(url, auth=...)` 为单服务器快捷入口。

## Deferred Loading（P5.5）

- 连接时只 `list_tools` 注册 meta（`MCPDeferredSkillRegistry`）
- 首次 `registry[name]` / `get_tools` 命中时才 `_make_module`
- CLI 注入 MCP 工具时用 `ChainSkillRegistry`，避免 `{**mcp_skills}`  eager 加载全部模块

## 断线重连

`call_tool` 失败且 server 配置 `reconnect != false` 时，按 `reconnect_attempts` 重连并重试一次。

## 验收

- [x] `tests/test_mcp_remote.py`
- [x] `tests/test_mcp.py` 回归
