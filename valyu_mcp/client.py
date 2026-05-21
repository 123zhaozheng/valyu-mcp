"""Async Valyu API client with multi-key rotation and quota management."""

import asyncio
import contextlib
import logging
from typing import Any

import httpx

from valyu_mcp.config import settings

logger = logging.getLogger(__name__)

# Heuristic keywords used to detect quota-exhaustion messages.
_QUOTA_KEYWORDS = [
    "quota",
    "rate limit",
    "rate-limit",
    "too many requests",
    "credits",
    "exhausted",
    "limit exceeded",
    "usage limit",
]


def _is_quota_error(status_code: int, response_body: dict[str, Any]) -> bool:
    """Detect whether an HTTP/API response signals quota exhaustion."""
    if status_code in (429, 403):
        return True

    msg = str(response_body.get("message", "")).lower()
    err = str(response_body.get("error", "")).lower()
    combined = f"{err} {msg}"
    return any(kw in combined for kw in _QUOTA_KEYWORDS)


class _KeyState:
    """Internal mutable state for a single API key."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.offline = False
        self.offline_since: float | None = None


class ValyuClient:
    """Async client that rotates through multiple API keys and offlines exhausted ones."""

    def __init__(
        self,
        api_keys: list[str] | None = None,
        base_url: str | None = None,
        retry_interval_seconds: int | None = None,
        timeout: float | None = None,
    ) -> None:
        self._base_url = (base_url or settings.valyu_base_url).rstrip("/")
        self._retry_interval = retry_interval_seconds or settings.key_retry_interval_seconds
        self._timeout = timeout or settings.request_timeout_seconds

        keys = api_keys or settings.api_keys
        if not keys:
            raise ValueError("At least one Valyu API key is required.")

        self._states = [_KeyState(k) for k in keys]
        self._index = 0
        self._lock = asyncio.Lock()
        self._http: httpx.AsyncClient | None = None
        self._retry_task: asyncio.Task[None] | None = None

    @property
    def _active_states(self) -> list[_KeyState]:
        """Return currently online key states."""
        return [s for s in self._states if not s.offline]

    @property
    def active_keys_count(self) -> int:
        """Number of keys currently considered active."""
        return len(self._active_states)

    @property
    def offline_keys_count(self) -> int:
        """Number of keys currently offline."""
        return len([s for s in self._states if s.offline])

    async def start(self) -> None:
        """Initialize the HTTP client and background retry loop."""
        if self._http is not None:
            return
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout),
            headers={"Content-Type": "application/json"},
        )
        self._retry_task = asyncio.create_task(self._retry_loop())
        logger.info(
            "ValyuClient started with %d key(s) (%d active, %d offline).",
            len(self._states),
            self.active_keys_count,
            self.offline_keys_count,
        )

    async def stop(self) -> None:
        """Gracefully shut down the HTTP client and background task."""
        if self._retry_task is not None:
            self._retry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._retry_task
            self._retry_task = None
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        logger.info("ValyuClient stopped.")

    async def _retry_loop(self) -> None:
        """Periodically attempt to bring offline keys back online."""
        while True:
            try:
                await asyncio.sleep(self._retry_interval)
            except asyncio.CancelledError:
                raise

            offline_states = [s for s in self._states if s.offline]
            if not offline_states:
                continue

            logger.info("Retrying %d offline key(s)...", len(offline_states))
            for state in offline_states:
                ok = await self._probe_key(state.key)
                if ok:
                    async with self._lock:
                        state.offline = False
                        state.offline_since = None
                    logger.info(
                        "Key %s... is back online.",
                        state.key[:8],
                    )
                else:
                    logger.info(
                        "Key %s... still offline.",
                        state.key[:8],
                    )

    async def _probe_key(self, key: str) -> bool:
        """Send a lightweight request to verify a key is usable again."""
        if self._http is None:
            return False
        try:
            resp = await self._http.get(
                f"{self._base_url}/datasources",
                headers={"x-api-key": key},
            )
            return resp.status_code == 200
        except Exception:
            return False

    def _next_key(self) -> str:
        """Round-robin select the next active key (callers must hold _lock)."""
        active = [s for s in self._states if not s.offline]
        if not active:
            raise RuntimeError("All Valyu API keys are offline (quota exhausted).")
        key = active[self._index % len(active)].key
        self._index = (self._index + 1) % len(active)
        return key

    async def request(
        self,
        method: str,
        endpoint: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send an HTTP request to Valyu, rotating keys on quota errors.

        Args:
            method: HTTP method (GET, POST, etc.).
            endpoint: API endpoint path (e.g. '/search').
            json_body: Optional JSON payload.
            params: Optional query parameters.

        Returns:
            Parsed JSON response from Valyu.

        Raises:
            RuntimeError: If all keys are offline or a non-quota error occurs.
            httpx.HTTPStatusError: For unexpected HTTP errors after key exhaustion.
        """
        if self._http is None:
            raise RuntimeError("Client has not been started. Call start() first.")

        url = f"{self._base_url}{endpoint}"
        attempted: set[str] = set()

        while True:
            async with self._lock:
                active = [s for s in self._states if not s.offline]
                remaining = [s for s in active if s.key not in attempted]
                if not remaining:
                    break
                key = self._next_key()
                while key in attempted:
                    key = self._next_key()
                attempted.add(key)

            logger.debug("Using key %s... for %s %s", key[:8], method, endpoint)
            try:
                resp = await self._http.request(
                    method=method.upper(),
                    url=url,
                    headers={"x-api-key": key},
                    json=json_body,
                    params=params,
                )
            except httpx.HTTPError as exc:
                # Network-level error — treat as non-quota and fail fast.
                raise RuntimeError(f"Valyu API request failed: {exc}") from exc

            body: dict[str, Any] = {}
            try:
                body = resp.json()
            except Exception:
                body = {"_raw": resp.text}

            if _is_quota_error(resp.status_code, body):
                logger.warning(
                    "Key %s... hit quota (%d). Body: %s",
                    key[:8],
                    resp.status_code,
                    body,
                )
                async with self._lock:
                    for state in self._states:
                        if state.key == key:
                            if not state.offline:
                                state.offline = True
                                state.offline_since = asyncio.get_event_loop().time()
                                logger.info(
                                    "Key %s... marked offline.",
                                    key[:8],
                                )
                            break
                continue

            # For any other HTTP error status, raise immediately.
            if not resp.is_success:
                raise httpx.HTTPStatusError(
                    f"Valyu API error: {resp.status_code} — {body}",
                    request=resp.request,
                    response=resp,
                )

            return body

        raise RuntimeError(
            "All Valyu API keys are offline (quota exhausted). "
            "No key available to satisfy the request."
        )
