# Valyu MCP Server

A custom [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server for the [Valyu](https://valyu.ai) API. Built with the standalone `fastmcp` framework and served over **HTTP** (not stdio).

## Features

- **Multi-key rotation** — automatically rotates across multiple API keys (round-robin).
- **Auto-offline on quota exhaustion** — keys that hit `403` / `429` or quota-related errors are temporarily removed from the pool.
- **Periodic retry** — offline keys are probed every 5 minutes and brought back online when quota is restored.
- **Health endpoint** — `GET /health` returns active/offline key counts for monitoring.
- **9 Valyu tools exposed** via MCP:
  - `valyu_search`
  - `valyu_contents`
  - `valyu_contents_status`
  - `valyu_answer`
  - `valyu_deepresearch_create`
  - `valyu_deepresearch_status`
  - `valyu_deepresearch_list`
  - `valyu_datasources_list`
  - `valyu_datasources_categories`

## Requirements

- Python 3.11+
- `fastmcp`, `httpx`, `pydantic`, `pydantic-settings`

## Installation (uv)

```bash
uv sync
```

> Uses `uv` for dependency management. `default-groups = ["dev"]` in `pyproject.toml` auto-installs dev deps.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VALYU_API_KEYS` | **Yes** | — | Comma-separated list of Valyu API keys |
| `VALYU_BASE_URL` | No | `https://api.valyu.ai/v1` | Valyu API base URL |
| `KEY_RETRY_INTERVAL_SECONDS` | No | `300` | Seconds between offline-key retry attempts |
| `REQUEST_TIMEOUT_SECONDS` | No | `120` | HTTP timeout for Valyu API calls |
| `FASTMCP_HOST` | No | `0.0.0.0` | MCP HTTP server host |
| `FASTMCP_PORT` | No | `8000` | MCP HTTP server port |
| `LOG_LEVEL` | No | `INFO` | Python logging level |

## Running the Server

### Direct (development)

```bash
export VALYU_API_KEYS="key1,key2,key3"
uv run python -m valyu_mcp
```

The MCP endpoint will be available at `http://localhost:8000/mcp/` and the health check at `http://localhost:8000/health`.

### With uvicorn (production / ASGI)

```bash
export FASTMCP_STATELESS_HTTP=true
uv run uvicorn "valyu_mcp.server:mcp.http_app(path='/mcp')" --host 0.0.0.0 --port 8000
```

> Set `FASTMCP_STATELESS_HTTP=true` for multi-worker deployments so that sessions are not stored server-side.

## Testing

```bash
uv run pytest tests/ -v
```

## Lint & Type Check

```bash
uv run ruff check valyu_mcp tests
uv run ruff format valyu_mcp tests
uv run pyright
```

## Architecture

- **`valyu_mcp/client.py`** — `ValyuClient` manages the key pool, rotation, offline logic, and background retry loop.
- **`valyu_mcp/server.py`** — FastMCP tool definitions and custom `/health` route.
- **`valyu_mcp/config.py`** — Pydantic-settings configuration.

## License

MIT
