# Error Handling

> How errors are handled in this project.

---

## Overview

- Use `RuntimeError` for operational failures (all keys offline, client not started).
- Use `httpx.HTTPStatusError` for unexpected upstream HTTP errors (non-quota 4xx/5xx).
- Log key rotation events (offline/online) at `INFO` level.
- Propagate API errors transparently; do not swallow HTTP exceptions from Valyu.

---

## Error Types

No custom exception hierarchy. Reuse standard types:
- `ValueError` — configuration errors (no API keys provided)
- `RuntimeError` — all keys are offline or client not started
- `httpx.HTTPStatusError` — upstream Valyu API returned non-success status
- `httpx.HTTPError` — network-level failure (timeout, connection reset)

---

## Error Handling Patterns

### Quota Exhaustion Detection

Detect via `_is_quota_error(status_code, response_body)`:
- HTTP 429 (Too Many Requests) → quota
- HTTP 403 (Forbidden) → quota or disabled key
- JSON body keywords: `quota`, `rate limit`, `rate-limit`, `too many requests`, `credits`, `exhausted`, `limit exceeded`, `usage limit`

### Key Pool Retry Loop

When a key hits quota:
1. Mark key `offline = True` with `offline_since` timestamp.
2. Try next active key via round-robin.
3. If all keys offline → raise `RuntimeError("All Valyu API keys are offline")`.
4. Background `asyncio.Task` probes offline keys every `KEY_RETRY_INTERVAL_SECONDS` (default 300s).
5. If probe (`GET /datasources`) succeeds, bring key back online.

### Non-Quota HTTP Errors

Any non-success status that is NOT quota-related (e.g., 500, 404) is raised immediately as `httpx.HTTPStatusError` — no key rotation attempted.

---

## API Error Responses

Valyu API returns JSON:
```json
{"error": "ErrorType", "message": "Human-readable description"}
```

The client parses this body and uses it for quota detection. Non-JSON responses fall back to `{"_raw": "<text>"}`.

---

## Common Mistakes

- **Swallowing HTTP errors** — Always re-raise non-quota `HTTPStatusError` so callers know the request failed for a real reason.
- **Retrying too aggressively** — Use a configurable interval (default 5 min) for offline-key probes, not immediate retry.
- **Forgetting `asyncio.Lock`** — Key pool mutation (index increment, offline marking) must be protected to avoid race conditions in concurrent tool calls.
