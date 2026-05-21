# Research: fastmcp HTTP Transport, Tool Registration, and Lifecycle

Date: 2026-05-21
Sources: Official MCP Python SDK README.v2.md, fastmcp.com docs, GitHub repos

## 1. Two Different "fastmcp" Implementations

There are **two distinct** Python MCP frameworks with similar names:

### A. Official MCP Python SDK (`mcp` package)
- PyPI: `mcp[cli]`
- v1.x: `from mcp.server.fastmcp import FastMCP`
- v2.x (pre-alpha on main): `from mcp.server.mcpserver import MCPServer`
- Maintained by Anthropic / ModelContextProtocol org
- FastMCP v1.0 was incorporated into the official SDK in 2024

### B. Standalone FastMCP (`fastmcp` package)
- PyPI: `fastmcp`
- `from fastmcp import FastMCP`
- Maintained by Prefect (actively maintained, ~1M downloads/day)
- Richer feature set: Apps/Generative UI, Auth providers, Docket tasks, more integrations
- The PRD says "fastmcp style" — this likely refers to the decorator-based ergonomic API shared by both

**Recommendation for this project**: Use the **standalone `fastmcp`** package because:
- It has better HTTP deployment docs and ASGI helpers (`http_app()`)
- Built-in custom route support (`@mcp.custom_route`)
- The PRD explicitly says "independent from Valyu's official MCP offering"

## 2. HTTP Transport Configuration

### Standalone FastMCP

**Direct run (simplest)**:
```python
from fastmcp import FastMCP
mcp = FastMCP("My Server")

@mcp.tool
def add(a: int, b: int) -> int:
    return a + b

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
```
Default endpoint: `http://localhost:8000/mcp/`

**ASGI app (production)**:
```python
app = mcp.http_app(path="/mcp")
# Then run with: uvicorn app:app --host 0.0.0.0 --port 8000
```

**Environment variables** (auto-loaded from `.env`):
- `FASTMCP_TRANSPORT=http`
- `FASTMCP_HOST=0.0.0.0`
- `FASTMCP_PORT=8000`
- `FASTMCP_STREAMABLE_HTTP_PATH=/mcp`
- `FASTMCP_STATELESS_HTTP=true`   # for multi-worker deployments
- `FASTMCP_JSON_RESPONSE=false`   # set true for JSON instead of SSE

### Official MCP Python SDK v2 (for reference)

```python
from mcp.server.mcpserver import MCPServer
mcp = MCPServer("Demo")

if __name__ == "__main__":
    mcp.run(transport="streamable-http", stateless_http=True, json_response=True)
```

**ASGI mount**:
```python
app = Starlette(
    routes=[
        Mount("/", app=mcp.streamable_http_app(json_response=True)),
    ],
    lifespan=lifespan,
)
```

**Key transport option**: `stateless_http=True` is recommended for production / multi-worker because sessions are NOT stored server-side; each request is fresh.

## 3. Tool Registration Patterns

Both frameworks use the same decorator style:

```python
@mcp.tool
def get_weather(city: str, unit: str = "celsius") -> str:
    """Get weather for a city."""
    return f"Weather in {city}: 22°{unit}"
```

**Structured output** (Pydantic models, TypedDict, dataclasses) is auto-generated from return type annotations.

**Context injection** (official SDK v2):
```python
from mcp.server.mcpserver import Context, MCPServer

@mcp.tool()
async def long_task(task_name: str, ctx: Context, steps: int = 5) -> str:
    await ctx.info(f"Starting: {task_name}")
    await ctx.report_progress(0.5, total=1.0, message="Half done")
    return "Done"
```

Context capabilities:
- `ctx.request_id`
- `ctx.debug(data)`, `ctx.info(data)`, `ctx.warning(data)`, `ctx.error(data)`
- `ctx.report_progress(progress, total, message)`
- `ctx.read_resource(uri)`
- `ctx.request_context.lifespan_context` (custom lifespan data)

## 4. Middleware / Lifecycle Hooks / Request Interception

**No pre-tool-call middleware hook exists** in either framework for intercepting tool execution at the protocol level. The frameworks are designed around explicit tool functions.

**Available hooks**:

1. **Lifespan** (official SDK): `asynccontextmanager` for startup/shutdown with typed context
2. **Custom routes** (standalone FastMCP): `@mcp.custom_route("/health", methods=["GET"])` — good for health checks, but NOT for intercepting tool calls
3. **ASGI middleware** (standalone FastMCP): Wrap `mcp.http_app()` with Starlette middleware (CORS, auth, etc.)
4. **Tool-level wrapper**: Implement key rotation logic inside a shared async helper that every tool calls

**Recommended approach for key rotation**:
- Create a shared `ValyuClient` class that manages the API key pool (round-robin, offline tracking, retry)
- Every tool instantiates or receives this client (via lifespan context or global singleton)
- The client handles selecting the next key, marking keys offline on quota errors, and periodic retry
- No protocol-level middleware needed

## 5. Valyu API Endpoints (from docs sidebar)

From `docs.valyu.ai/api-reference/overview`:

- **Search Tools**
  - `POST /search` — Search
  - `POST /contents` — Contents
  - `GET  /contents/job/{job_id}` — Contents Job Status
  - `POST /answer` — Answer

- **DeepResearch**
  - `POST /deepresearch` — Create Task
  - `GET  /deepresearch/{task_id}` — Get Status
  - `GET  /deepresearch` — List Tasks
  - `POST /deepresearch/{task_id}` — Update Task
  - `POST /deepresearch/{task_id}/respond` — Respond to HITL Checkpoint
  - `POST /deepresearch/{task_id}/cancel` — Cancel Task
  - `DELETE /deepresearch/{task_id}` — Delete Task
  - Batch variants for DeepResearch

- **Datasources**
  - `GET /datasources` — List Datasources
  - `GET /datasources/categories` — List Categories

Authentication appears to use API keys from `platform.valyu.ai/user/account/dashboard`.

## 6. Key Takeaways for Implementation

1. Use `fastmcp` (standalone) package, not `mcp`
2. Run with `mcp.run(transport="http", port=8000)` or create ASGI app with `mcp.http_app()`
3. Expose Valyu endpoints as `@mcp.tool()` functions (Search, Contents, Answer, DeepResearch status, etc.)
4. Implement key pool rotation in a custom `ValyuClient` wrapper, not in MCP middleware
5. The client should:
   - Maintain a list of API keys
   - Round-robin select an active key per request
   - Catch quota-exhaustion responses (need to verify exact HTTP status / error body from Valyu)
   - Mark exhausted keys offline with a timestamp
   - Periodically retry offline keys (e.g., every 5 minutes)
6. Use lifespan context to initialize the ValyuClient on startup
7. Use `FASTMCP_STATELESS_HTTP=true` if planning multi-worker deployment
