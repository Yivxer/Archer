# P5.8 FastAPI 迁移 — 设计文档

日期：2026-06-13  
状态：阶段二（实现完成）

## 范围

- 新运行时：`terminal/api/fastapi_app.py`（默认）
- 保留：`terminal/archer_api.py` `--legacy` → `BaseHTTPRequestHandler`
- 业务逻辑仍在 `_routes.py` / `_tools.py`；FastAPI 层做路由、鉴权、限流、SSE/WS

## 路由映射

| 旧 dispatch | FastAPI |
|-------------|---------|
| `payload_get(path)` | `GET /{path}` + query |
| `payload_post(path, body)` | `POST /{path}` |
| `/chat/stream` SSE | `POST /chat/stream` → `StreamingResponse` |
| — | `WebSocket /ws/chat` |

## 安全

- Bearer token（`/health` 除外）→ HTTP middleware
- `check_rate_limit()` → middleware（按 client IP + path）
- `MAX_CONTENT_LENGTH` → POST middleware

## 启动

```bash
python terminal/archer_api.py              # FastAPI + uvicorn
python terminal/archer_api.py --legacy     # 旧 ThreadingHTTPServer
```

## 验收

- [x] `tests/test_fastapi_routes.py`
- [x] `tests/test_desktop_api.py` 回归
