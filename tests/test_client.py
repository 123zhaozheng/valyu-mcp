"""Unit tests for ValyuClient key rotation and quota management."""

import asyncio

import httpx
import pytest
import respx
from httpx import Response

from valyu_mcp.client import ValyuClient, _is_quota_error


class TestIsQuotaError:
    def test_429_is_quota(self) -> None:
        assert _is_quota_error(429, {"message": "ok"}) is True

    def test_403_is_quota(self) -> None:
        assert _is_quota_error(403, {"message": "ok"}) is True

    def test_401_is_not_quota(self) -> None:
        assert _is_quota_error(401, {"message": "unauthorized"}) is False

    def test_keyword_quota(self) -> None:
        assert _is_quota_error(200, {"message": "Quota exceeded"}) is True

    def test_keyword_rate_limit(self) -> None:
        assert _is_quota_error(200, {"message": "Rate limit reached"}) is True

    def test_keyword_credits(self) -> None:
        assert _is_quota_error(200, {"error": "Credits exhausted"}) is True

    def test_no_keyword_no_special_status(self) -> None:
        assert _is_quota_error(200, {"message": "Not found"}) is False


class TestKeyRotation:
    @pytest.fixture
    def client(self) -> ValyuClient:
        return ValyuClient(
            api_keys=["key-a", "key-b", "key-c"],
            base_url="https://api.valyu.ai/v1",
            retry_interval_seconds=1,
        )

    @pytest.mark.asyncio
    async def test_round_robin(self, client: ValyuClient) -> None:
        with respx.mock:
            route = respx.post("https://api.valyu.ai/v1/search").mock(
                side_effect=[
                    Response(200, json={"ok": True}),
                    Response(200, json={"ok": True}),
                    Response(200, json={"ok": True}),
                ]
            )
            await client.start()
            await client.request("POST", "/search", json_body={"query": "x"})
            await client.request("POST", "/search", json_body={"query": "x"})
            await client.request("POST", "/search", json_body={"query": "x"})
            await client.stop()

        assert route.call_count == 3
        headers = [c.request.headers["x-api-key"] for c in route.calls]
        assert headers == ["key-a", "key-b", "key-c"]

    @pytest.mark.asyncio
    async def test_offline_on_429(self, client: ValyuClient) -> None:
        with respx.mock:
            route = respx.post("https://api.valyu.ai/v1/search").mock(
                side_effect=[
                    Response(429, json={"message": "Rate limit"}),
                    Response(200, json={"ok": True}),
                ]
            )
            await client.start()
            body = await client.request("POST", "/search", json_body={"query": "x"})
            await client.stop()

        assert body == {"ok": True}
        assert route.call_count == 2
        # first key marked offline, second used
        assert client.offline_keys_count == 1
        assert client.active_keys_count == 2

    @pytest.mark.asyncio
    async def test_offline_on_quota_message(self, client: ValyuClient) -> None:
        with respx.mock:
            route = respx.post("https://api.valyu.ai/v1/search").mock(
                side_effect=[
                    Response(200, json={"success": False, "message": "Quota exceeded"}),
                    Response(200, json={"ok": True}),
                ]
            )
            await client.start()
            body = await client.request("POST", "/search", json_body={"query": "x"})
            await client.stop()

        assert body == {"ok": True}
        assert route.call_count == 2
        assert client.offline_keys_count == 1

    @pytest.mark.asyncio
    async def test_all_keys_offline_raises(self, client: ValyuClient) -> None:
        with respx.mock:
            respx.post("https://api.valyu.ai/v1/search").mock(
                side_effect=[
                    Response(429, json={"message": "Rate limit"}),
                    Response(429, json={"message": "Rate limit"}),
                    Response(429, json={"message": "Rate limit"}),
                ]
            )
            await client.start()
            with pytest.raises(RuntimeError, match="All Valyu API keys are offline"):
                await client.request("POST", "/search", json_body={"query": "x"})
            await client.stop()

        assert client.active_keys_count == 0
        assert client.offline_keys_count == 3

    @pytest.mark.asyncio
    async def test_non_quota_http_error_raises(self, client: ValyuClient) -> None:
        with respx.mock:
            respx.post("https://api.valyu.ai/v1/search").mock(
                return_value=Response(500, json={"error": "Internal"})
            )
            await client.start()
            with pytest.raises(httpx.HTTPStatusError):
                await client.request("POST", "/search", json_body={"query": "x"})
            await client.stop()

    @pytest.mark.asyncio
    async def test_retry_loop_brings_key_back(self, client: ValyuClient) -> None:
        with respx.mock:
            respx.post("https://api.valyu.ai/v1/search").mock(
                side_effect=[
                    Response(429, json={"message": "Rate limit"}),
                    Response(429, json={"message": "Rate limit"}),
                    Response(429, json={"message": "Rate limit"}),
                    Response(200, json={"ok": True}),
                ]
            )
            # probe uses GET /datasources
            probe_route = respx.get("https://api.valyu.ai/v1/datasources").mock(
                side_effect=[
                    Response(200, json={"datasources": []}),
                ]
            )
            await client.start()
            # exhaust all three keys
            with pytest.raises(RuntimeError, match="All Valyu API keys are offline"):
                await client.request("POST", "/search", json_body={"query": "x"})

            assert client.offline_keys_count == 3

            # wait for retry loop (interval is 1s in fixture)
            await asyncio.sleep(1.5)

            # now first key should be back online
            body = await client.request("POST", "/search", json_body={"query": "x"})
            await client.stop()

        assert body == {"ok": True}
        assert client.active_keys_count >= 1
        assert probe_route.call_count >= 1


class TestClientInit:
    def test_no_keys_raises(self) -> None:
        with pytest.raises(ValueError, match="At least one Valyu API key is required"):
            ValyuClient(api_keys=[])

    def test_single_key_ok(self) -> None:
        c = ValyuClient(api_keys=["only-one"])
        assert c.active_keys_count == 1
