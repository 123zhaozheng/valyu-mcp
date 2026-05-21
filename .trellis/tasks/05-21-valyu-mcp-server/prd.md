# Valyu MCP Server with Multi-Key Rotation and Quota Management

## Goal

Build a custom MCP (Model Context Protocol) server for Valyu API using fastmcp style. The server must:
- Support multiple API keys with round-robin rotation
- Automatically offline keys that have exhausted their quota
- Use HTTP transport format (not stdio)
- Be independent from Valyu's official MCP offering

## Research References

- [`research/valyu-api.md`](research/valyu-api.md) — Valyu API endpoints, auth, error formats
- [`research/fastmcp-http.md`](research/fastmcp-http.md) — fastmcp HTTP transport, tool registration, ASGI patterns

## Technical Approach

**Framework**: standalone `fastmcp` package (Prefect-maintained)
**Transport**: HTTP via `mcp.run(transport="http")` or ASGI `mcp.http_app()`
**Key rotation**: Shared `ValyuClient` class managing key pool — round-robin selection, offline marking on quota errors, periodic retry

## Decision (ADR-lite)

**Context**: Need HTTP transport + multi-key rotation + independence from official MCP
**Decision**: Use standalone `fastmcp` (not `mcp` SDK); implement key pool in a custom async `ValyuClient` wrapper called by each tool; expose standard Valyu tools (Search, Contents, Answer, DeepResearch core)
**Consequences**: No pre-tool middleware available — rotation logic lives in the client layer; ASGI app supports multi-worker with `FASTMCP_STATELESS_HTTP=true`

## Requirements

1. **HTTP MCP Server**: Use `fastmcp` with HTTP transport, port 8000 by default
2. **Multi-key rotation**: Accept comma-separated `VALYU_API_KEYS` env var; round-robin select active key per request
3. **Auto-offline exhausted keys**: On HTTP 403/429 or `success: false` with quota-related error message, mark key offline
4. **Periodic retry**: Every 5 minutes, attempt to bring offline keys back online
5. **Exposed tools** (standard set):
   - `valyu_search` — `POST /search`
   - `valyu_contents` — `POST /contents`
   - `valyu_contents_status` — `GET /contents/job/{id}`
   - `valyu_answer` — `POST /answer`
   - `valyu_deepresearch_create` — `POST /deepresearch`
   - `valyu_deepresearch_status` — `GET /deepresearch/{id}`
   - `valyu_deepresearch_list` — `GET /deepresearch`
   - `valyu_datasources_list` — `GET /datasources`
   - `valyu_datasources_categories` — `GET /datasources/categories`
6. **Health check endpoint**: Custom route `/health` for deployment monitoring
7. **Logging**: Key rotation events, offline/online transitions logged at INFO level

## Acceptance Criteria

- [ ] Server starts and exposes Valyu tools via HTTP MCP
- [ ] Multiple keys rotate correctly (round-robin)
- [ ] Exhausted keys (quota/403/429) are taken offline
- [ ] Offline keys are retried periodically and brought back online if quota restored
- [ ] Health check endpoint responds
- [ ] All tools map correct request/response schemas from Valyu API docs
- [ ] Lint / typecheck green
- [ ] README with setup and env var instructions

## Definition of Done

- Tests added/updated (unit tests for key pool, integration-style tests for tool schemas)
- Lint / typecheck green (ruff + mypy/pyright)
- Docs updated (README, env vars)

## Out of Scope

- Valyu official MCP integration
- stdio transport mode
- DeepResearch batch operations, HITL respond, cancel/delete/update (advanced research lifecycle)
- Streaming / SSE answer output
- Custom MCP tools beyond Valyu API surface
- Rate-limit headers parsing (no observed X-RateLimit-* headers in Valyu docs)

## Technical Notes

- Valyu auth: `x-api-key` header, plain string
- Base URL: `https://api.valyu.ai/v1`
- Quota exhaustion signal: likely HTTP 403 or 429 with JSON `{"error": "...", "message": "..."}` — detect via status code + error message heuristics
- fastmcp HTTP: `mcp.run(transport="http", host="0.0.0.0", port=8000)` or `app = mcp.http_app()`
- Stateless mode: `FASTMCP_STATELESS_HTTP=true` for multi-worker
