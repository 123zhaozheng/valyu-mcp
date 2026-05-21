"""FastMCP HTTP server exposing Valyu API tools with multi-key rotation."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP
from starlette.responses import JSONResponse

from valyu_mcp.client import ValyuClient

logger = logging.getLogger(__name__)

# Shared client instance (rotates across keys).
_client: ValyuClient | None = None


def _get_client() -> ValyuClient:
    """Return the shared ValyuClient, creating it if necessary."""
    global _client
    if _client is None:
        _client = ValyuClient()
    return _client


@asynccontextmanager
async def app_lifespan(app: FastMCP) -> AsyncGenerator[None, None]:
    """FastMCP lifespan — start the shared client and its retry loop."""
    client = _get_client()
    await client.start()
    logger.info("Valyu MCP server started (%d active keys).", client.active_keys_count)
    try:
        yield
    finally:
        await client.stop()
        logger.info("Valyu MCP server stopped.")


mcp = FastMCP("valyu-mcp", lifespan=app_lifespan)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Any = None) -> JSONResponse:
    """Deployment health check."""
    del request  # unused, required by Starlette route signature
    client = _get_client()
    return JSONResponse(
        {
            "status": "ok",
            "active_keys": client.active_keys_count,
            "offline_keys": client.offline_keys_count,
        }
    )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
@mcp.tool()
async def valyu_search(
    query: str,
    search_type: str = "all",
    max_num_results: int = 10,
    is_tool_call: bool = True,
    relevance_threshold: float = 0.5,
    max_price: int | None = None,
    included_sources: list[str] | None = None,
    excluded_sources: list[str] | None = None,
    country_code: str | None = None,
    response_length: str | int | None = None,
    category: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    fast_mode: bool | None = None,
    url_only: bool | None = None,
    source_biases: dict[str, int] | None = None,
    instructions: str | None = None,
) -> dict[str, Any]:
    """Search Valyu's indexed sources (web, proprietary, news).

    Args:
        query: Search string (required).
        search_type: 'all' (default), 'web', 'proprietary', or 'news'.
        max_num_results: Max results (1-100, default 10).
        is_tool_call: Whether the call originates from an MCP tool (default true).
        relevance_threshold: Float 0-1 (default 0.5).
        max_price: Max price per thousand queries (CPM).
        included_sources: Source strings to include.
        excluded_sources: Source strings to exclude.
        country_code: 2-letter ISO code or 'ALL'.
        response_length: 'short', 'medium', 'large', 'max', or integer char count.
        category: Natural language category phrase.
        start_date: YYYY-MM-DD.
        end_date: YYYY-MM-DD.
        fast_mode: Faster but shorter results.
        url_only: Return snippets only.
        source_biases: Dict of source -> int (-5 to +5).
        instructions: Natural language ranking guidance (max 500 chars).
    """
    payload: dict[str, Any] = {"query": query}
    for key, value in [
        ("search_type", search_type),
        ("max_num_results", max_num_results),
        ("is_tool_call", is_tool_call),
        ("relevance_threshold", relevance_threshold),
        ("max_price", max_price),
        ("included_sources", included_sources),
        ("excluded_sources", excluded_sources),
        ("country_code", country_code),
        ("response_length", response_length),
        ("category", category),
        ("start_date", start_date),
        ("end_date", end_date),
        ("fast_mode", fast_mode),
        ("url_only", url_only),
        ("source_biases", source_biases),
        ("instructions", instructions),
    ]:
        if value is not None:
            payload[key] = value

    return await _get_client().request("POST", "/search", json_body=payload)


# ---------------------------------------------------------------------------
# Contents
# ---------------------------------------------------------------------------
@mcp.tool()
async def valyu_contents(
    urls: list[str],
    summary: bool | str | dict[str, Any] | None = None,
    extract_effort: str | None = None,
    response_length: str | int | None = None,
    max_price_dollars: float | None = None,
    screenshot: bool | None = None,
    async_mode: bool | None = None,
    webhook_url: str | None = None,
) -> dict[str, Any]:
    """Extract contents from one or more URLs.

    Args:
        urls: List of URLs to extract (1-50, required).
        summary: False/null (no AI), True (basic summary), string (custom
            instructions <=500 chars), or JSON schema object.
        extract_effort: 'normal', 'high', or 'auto'.
        response_length: 'short' (25k), 'medium' (50k), 'large' (100k), 'max',
            or integer.
        max_price_dollars: Maximum cost in USD.
        screenshot: Whether to capture a screenshot.
        async_mode: Required when urls > 10. Use async_mode instead of async
            because async is a reserved keyword.
        webhook_url: HTTPS webhook (async only).
    """
    payload: dict[str, Any] = {"urls": urls}
    for key, value in [
        ("summary", summary),
        ("extract_effort", extract_effort),
        ("response_length", response_length),
        ("max_price_dollars", max_price_dollars),
        ("screenshot", screenshot),
        ("async", async_mode),
        ("webhook_url", webhook_url),
    ]:
        if value is not None:
            payload[key] = value

    return await _get_client().request("POST", "/contents", json_body=payload)


@mcp.tool()
async def valyu_contents_status(job_id: str) -> dict[str, Any]:
    """Check the status of an async contents extraction job.

    Args:
        job_id: The job ID returned by valyu_contents.
    """
    return await _get_client().request("GET", f"/contents/job/{job_id}")


# ---------------------------------------------------------------------------
# Answer
# ---------------------------------------------------------------------------
@mcp.tool()
async def valyu_answer(
    query: str,
    search_type: str = "all",
    data_max_price: float = 1.0,
    fast_mode: bool | None = None,
    country_code: str | None = None,
    included_sources: list[str] | None = None,
    excluded_sources: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    structured_output: dict[str, Any] | None = None,
    system_instructions: str | None = None,
) -> dict[str, Any]:
    """Ask a question and receive an AI-generated answer backed by Valyu search.

    Args:
        query: The question (required).
        search_type: 'all', 'web', 'proprietary', or 'news'.
        data_max_price: Max data cost (default 1.0).
        fast_mode: Faster but potentially less thorough.
        country_code: 2-letter ISO code.
        included_sources: Source strings to include.
        excluded_sources: Source strings to exclude.
        start_date: YYYY-MM-DD.
        end_date: YYYY-MM-DD.
        structured_output: JSON schema object for structured responses.
        system_instructions: System prompt (max 2000 chars).
    """
    payload: dict[str, Any] = {"query": query}
    for key, value in [
        ("search_type", search_type),
        ("data_max_price", data_max_price),
        ("fast_mode", fast_mode),
        ("country_code", country_code),
        ("included_sources", included_sources),
        ("excluded_sources", excluded_sources),
        ("start_date", start_date),
        ("end_date", end_date),
        ("structured_output", structured_output),
        ("system_instructions", system_instructions),
    ]:
        if value is not None:
            payload[key] = value

    return await _get_client().request("POST", "/answer", json_body=payload)


# ---------------------------------------------------------------------------
# DeepResearch
# ---------------------------------------------------------------------------
@mcp.tool()
async def valyu_deepresearch_create(
    query: str,
    mode: str = "standard",
    output_formats: list[str] | None = None,
    research_strategy: str | None = None,
    report_format: str | None = None,
    search: dict[str, Any] | None = None,
    urls: list[str] | None = None,
    files: list[dict[str, Any]] | None = None,
    deliverables: list[dict[str, Any]] | None = None,
    mcp_servers: list[dict[str, Any]] | None = None,
    tools: dict[str, Any] | None = None,
    previous_reports: list[str] | None = None,
    webhook_url: str | None = None,
    alert_email: str | dict[str, Any] | None = None,
    brand_collection_id: str | None = None,
    hitl: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a deep-research task.

    Args:
        query: Research task description (max 25,000 chars, required).
        mode: 'fast', 'standard', 'heavy', or 'max'.
        output_formats: e.g. ['markdown'] or ['markdown', 'pdf'].
        research_strategy: Natural language strategy (max 15,000 chars combined
            with report_format).
        report_format: Natural language output format instructions.
        search: SearchConfig dict.
        urls: URLs to extract and analyze.
        files: List of FileAttachment objects.
        deliverables: Deliverable configs (CSV, XLSX, PPTX, DOCX, PDF), max 10.
        mcp_servers: List of MCPServerConfig objects.
        tools: Dict of tool configs (browser_use, screenshots, code_execution).
        previous_reports: List of report IDs, max 3.
        webhook_url: HTTPS webhook URL.
        alert_email: Email string or AlertEmailConfig dict.
        brand_collection_id: Brand collection ID.
        hitl: HitlConfig dict.
        metadata: Custom key-value pairs.
    """
    payload: dict[str, Any] = {"query": query, "mode": mode}
    for key, value in [
        ("output_formats", output_formats),
        ("research_strategy", research_strategy),
        ("report_format", report_format),
        ("search", search),
        ("urls", urls),
        ("files", files),
        ("deliverables", deliverables),
        ("mcp_servers", mcp_servers),
        ("tools", tools),
        ("previous_reports", previous_reports),
        ("webhook_url", webhook_url),
        ("alert_email", alert_email),
        ("brand_collection_id", brand_collection_id),
        ("hitl", hitl),
        ("metadata", metadata),
    ]:
        if value is not None:
            payload[key] = value

    return await _get_client().request("POST", "/deepresearch", json_body=payload)


@mcp.tool()
async def valyu_deepresearch_status(task_id: str) -> dict[str, Any]:
    """Get the status of a deep-research task.

    Args:
        task_id: The deep-research task ID.
    """
    return await _get_client().request("GET", f"/deepresearch/{task_id}")


@mcp.tool()
async def valyu_deepresearch_list(limit: int | None = None) -> dict[str, Any]:
    """List deep-research tasks.

    Args:
        limit: Maximum number of tasks to return.
    """
    params: dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    return await _get_client().request("GET", "/deepresearch", params=params)


# ---------------------------------------------------------------------------
# Datasources
# ---------------------------------------------------------------------------
@mcp.tool()
async def valyu_datasources_list() -> dict[str, Any]:
    """List available Valyu datasources."""
    return await _get_client().request("GET", "/datasources")


@mcp.tool()
async def valyu_datasources_categories() -> dict[str, Any]:
    """List datasource categories."""
    return await _get_client().request("GET", "/datasources/categories")
