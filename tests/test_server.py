"""Integration-style tests for MCP tool registration and schemas."""

from collections.abc import Generator

import pytest
import respx
from httpx import Response

import valyu_mcp.server as server_module
from valyu_mcp.client import ValyuClient


@pytest.fixture(autouse=True)
def reset_client() -> Generator[None, None, None]:
    """Ensure the global client is fresh for every test."""
    server_module._client = None
    yield
    server_module._client = None


@pytest.fixture
def mock_client() -> Generator[ValyuClient, None, None]:
    client = ValyuClient(api_keys=["test-key"], retry_interval_seconds=3600)
    yield client


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_ok(self, mock_client: ValyuClient) -> None:
        server_module._client = mock_client
        await mock_client.start()
        response = await server_module.health_check()  # type: ignore[call-arg]
        await mock_client.stop()
        import json

        body = json.loads(response.body)
        assert body["status"] == "ok"
        assert body["active_keys"] == 1
        assert body["offline_keys"] == 0


class TestToolsSmoke:
    """Smoke tests that verify each tool calls the correct endpoint with expected params."""

    @pytest.mark.asyncio
    async def test_valyu_search(self, mock_client: ValyuClient) -> None:
        with respx.mock:
            route = respx.post("https://api.valyu.ai/v1/search").mock(
                return_value=Response(200, json={"success": True})
            )
            server_module._client = mock_client
            await mock_client.start()
            result = await server_module.valyu_search(query="Python asyncio")
            await mock_client.stop()

        assert result == {"success": True}
        assert route.call_count == 1
        sent = route.calls.last.request.content
        assert b"Python asyncio" in sent

    @pytest.mark.asyncio
    async def test_valyu_contents(self, mock_client: ValyuClient) -> None:
        with respx.mock:
            route = respx.post("https://api.valyu.ai/v1/contents").mock(
                return_value=Response(200, json={"success": True})
            )
            server_module._client = mock_client
            await mock_client.start()
            result = await server_module.valyu_contents(
                urls=["https://example.com"],
                async_mode=True,
            )
            await mock_client.stop()

        assert result == {"success": True}
        sent = route.calls.last.request.content
        assert b"https://example.com" in sent
        assert b"async" in sent

    @pytest.mark.asyncio
    async def test_valyu_contents_status(self, mock_client: ValyuClient) -> None:
        with respx.mock:
            route = respx.get("https://api.valyu.ai/v1/contents/job/abc123").mock(
                return_value=Response(200, json={"status": "completed"})
            )
            server_module._client = mock_client
            await mock_client.start()
            result = await server_module.valyu_contents_status(job_id="abc123")
            await mock_client.stop()

        assert result == {"status": "completed"}
        assert route.call_count == 1

    @pytest.mark.asyncio
    async def test_valyu_answer(self, mock_client: ValyuClient) -> None:
        with respx.mock:
            route = respx.post("https://api.valyu.ai/v1/answer").mock(
                return_value=Response(200, json={"answer": "42"})
            )
            server_module._client = mock_client
            await mock_client.start()
            result = await server_module.valyu_answer(query="What is 6*7?")
            await mock_client.stop()

        assert result == {"answer": "42"}
        sent = route.calls.last.request.content
        assert b"What is 6*7?" in sent

    @pytest.mark.asyncio
    async def test_valyu_deepresearch_create(self, mock_client: ValyuClient) -> None:
        with respx.mock:
            route = respx.post("https://api.valyu.ai/v1/deepresearch").mock(
                return_value=Response(200, json={"deepresearch_id": "dr-1"})
            )
            server_module._client = mock_client
            await mock_client.start()
            result = await server_module.valyu_deepresearch_create(
                query="AI alignment",
                mode="fast",
            )
            await mock_client.stop()

        assert result == {"deepresearch_id": "dr-1"}
        sent = route.calls.last.request.content
        assert b"AI alignment" in sent
        assert b"fast" in sent

    @pytest.mark.asyncio
    async def test_valyu_deepresearch_status(self, mock_client: ValyuClient) -> None:
        with respx.mock:
            respx.get("https://api.valyu.ai/v1/deepresearch/dr-1").mock(
                return_value=Response(200, json={"status": "queued"})
            )
            server_module._client = mock_client
            await mock_client.start()
            result = await server_module.valyu_deepresearch_status(task_id="dr-1")
            await mock_client.stop()

        assert result == {"status": "queued"}

    @pytest.mark.asyncio
    async def test_valyu_deepresearch_list(self, mock_client: ValyuClient) -> None:
        with respx.mock:
            route = respx.get("https://api.valyu.ai/v1/deepresearch").mock(
                return_value=Response(200, json={"tasks": []})
            )
            server_module._client = mock_client
            await mock_client.start()
            result = await server_module.valyu_deepresearch_list(limit=5)
            await mock_client.stop()

        assert result == {"tasks": []}
        assert "limit=5" in str(route.calls.last.request.url)

    @pytest.mark.asyncio
    async def test_valyu_datasources_list(self, mock_client: ValyuClient) -> None:
        with respx.mock:
            respx.get("https://api.valyu.ai/v1/datasources").mock(
                return_value=Response(200, json={"datasources": []})
            )
            server_module._client = mock_client
            await mock_client.start()
            result = await server_module.valyu_datasources_list()
            await mock_client.stop()

        assert result == {"datasources": []}

    @pytest.mark.asyncio
    async def test_valyu_datasources_categories(self, mock_client: ValyuClient) -> None:
        with respx.mock:
            respx.get("https://api.valyu.ai/v1/datasources/categories").mock(
                return_value=Response(200, json={"categories": []})
            )
            server_module._client = mock_client
            await mock_client.start()
            result = await server_module.valyu_datasources_categories()
            await mock_client.stop()

        assert result == {"categories": []}
