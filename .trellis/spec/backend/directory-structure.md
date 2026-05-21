# Directory Structure

> How backend code is organized in this project.

---

## Overview

<!--
Document your project's backend directory structure here.

Questions to answer:
- How are modules/packages organized?
- Where does business logic live?
- Where are API endpoints defined?
- How are utilities and helpers organized?
-->

(To be filled by the team)

---

## Directory Layout

```
valyu_mcp/          # Package root (flat, no src/ prefix)
├── __init__.py
├── __main__.py      # Entry point: python -m valyu_mcp
├── config.py        # Pydantic-settings env config
├── client.py        # Core business logic (API client, key rotation)
└── server.py        # FastMCP tool definitions + routes
tests/
├── test_client.py   # Unit tests for client logic
└── test_server.py   # Integration tests for MCP tools
pyproject.toml       # Project config, deps, tool settings
README.md
```

---

## Module Organization

## Module Organization

1. **Business logic lives in `client.py`**, not in tool decorators.
2. **Tool functions in `server.py` are thin wrappers** — they build payloads and delegate HTTP to `ValyuClient`.
3. **Configuration in `config.py`** — all env vars loaded via `pydantic-settings` with defaults.
4. **No `src/` prefix** — flat package at repo root for simpler imports and packaging.

## Naming Conventions

- Package names: `snake_case`
- Module files: `snake_case.py`
- Class names: `PascalCase`
- Function / variable names: `snake_case`
- Private helpers: `_leading_underscore`

## Examples

- `valyu_mcp/client.py` — `ValyuClient` class with key-pool rotation
- `valyu_mcp/server.py` — `valyu_search`, `valyu_contents` tool functions
- `tests/test_client.py` — `TestKeyRotation`, `TestIsQuotaError`

---

## Naming Conventions

<!-- File and folder naming rules -->

(To be filled by the team)

---

## Examples

<!-- Link to well-organized modules as examples -->

(To be filled by the team)
