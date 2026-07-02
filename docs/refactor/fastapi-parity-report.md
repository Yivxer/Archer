# FastAPI Parity Report

Date: 2026-06-20
Scope: P7.3 route parity between the default FastAPI runtime and legacy handler.

## Conclusion

FastAPI is already the default runtime through `terminal/archer_api.py`.

The current FastAPI layer is structurally equivalent to the legacy HTTP handler for normal REST routes because both delegate business logic to the same dispatchers:

- GET routes delegate to `terminal.api._routes.payload_get()`.
- POST routes delegate to `terminal.api._routes.payload_post()`.
- `POST /chat/stream` is implemented separately in both runtimes, but both consume `_iter_chat_chunks()`.

No missing REST route was found in the FastAPI default path.

## Runtime Entries

| Path | FastAPI default | Legacy fallback |
|---|---|---|
| `terminal/archer_api.py` | calls `run_fastapi_server()` by default | `--legacy` starts `ThreadingHTTPServer` |
| `terminal/api/fastapi_app.py` | FastAPI + uvicorn | n/a |
| `terminal/api/_routes.py` | shared route dispatch | shared route dispatch |
| `terminal/api/_tools.py` | shared chat/tool stream generator | shared chat/tool stream generator |

## FastAPI Native Routes

| Route | Status | Notes |
|---|---|---|
| `GET /health` | equivalent | public liveness |
| `GET /ready` | equivalent plus runtime marker | FastAPI returns `runtime=fastapi`; legacy dispatcher returns `runtime=legacy` |
| `POST /chat/stream` | equivalent source generator | FastAPI uses `StreamingResponse`; legacy uses `wfile.write + flush` |
| `WS /ws/chat` | FastAPI only | additional route, not required for legacy parity |
| `GET /openapi.json`, `/docs`, `/redoc` | FastAPI only | framework docs, intentionally absent in legacy |

## Shared GET Dispatcher Routes

All of these are covered by FastAPI wildcard GET forwarding:

```text
/status
/sessions
/sessions/{id}
/memory
/skills
/modes
/experts
/proactive-touch
/reviews
/journal-review
/soul-files
/memory/stats
/memory/groups
/soul-profile
/settings
/jobs
/jobs/{id}
/schedules
```

## Shared POST Dispatcher Routes

All of these are covered by FastAPI wildcard POST forwarding:

```text
/jobs
/jobs/{id}/cancel
/jobs/{id}/retry
/jobs/{id}/approve
/jobs/{id}/spawn
/schedules
/schedules/{id}/disable
/schedules/{id}/remove
/chat
/tool-approvals
/sessions
/sessions/{id}/append
/soul/import
/modes/current
/experts/current
/settings/validate
/settings/save
/settings/test-model
/skills/toggle
/memory/update
/memory/evolve
/memory/pending/{id}/accept
/memory/pending/{id}/reject
```

## Parity Risks

| Risk | Current state | Decision |
|---|---|---|
| SSE flush behavior | FastAPI and legacy use different transport implementations | Keep focused SSE tests and one short manual smoke per API runtime change |
| Sync work inside FastAPI route | `_iter_chat_chunks()` and downstream LLM/DB work are synchronous | Do not rewrite in P7.3; address in later connection/runtime phase if blocking is observed |
| Legacy monkeypatch helpers | Still present in `terminal/archer_api.py` | Isolated to legacy path; clean up only after manual parity smoke stays green |
| OpenAPI docs | FastAPI-only | Intended framework benefit, not a parity gap |
| WebSocket | FastAPI-only | Extra capability, not required for Desktop main SSE path |

## Verification

Automated:

```bash
.venv/bin/python -m pytest -q tests/test_fastapi_routes.py tests/test_desktop_api.py::TestDesktopApiAuth --tb=short
```

Result on 2026-06-20: 18 passed.

Additional test coverage added:

- FastAPI wildcard GET preserves query string and delegates to `payload_get()`.
- FastAPI wildcard POST preserves body and delegates to `payload_post()`.

## P7.3 Status

| Checklist item | Status | Notes |
|---|---|---|
| Compare legacy handler, shared dispatchers, and FastAPI routes | done | no missing REST route found |
| Fill missing routes | not needed | no missing route found in default FastAPI path |
| Independent default API smoke | partially done | `/health`, `/ready`, `/status`, `/chat/stream` first byte covered in P7 baseline |
| FastAPI completeness report | done | this document |
