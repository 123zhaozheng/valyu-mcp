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


def _truncate_text(val: Any, max_chars: int = 1200) -> Any:
    """Truncate long string fields to avoid bloating LLM context."""
    if isinstance(val, str) and len(val) > max_chars:
        return val[:max_chars] + " ... [truncated]"
    return val


def _truncate_result_items(result: dict[str, Any]) -> dict[str, Any]:
    """Walk search/contents results: cap item count + truncate text fields."""
    items = result.get("results")
    if not isinstance(items, list):
        return result
    # Keep only the top-5 results to avoid context explosion.
    # Valyu sorts by relevance, so the first few are the most useful.
    kept, dropped = items[:5], items[5:]
    if dropped:
        result["results"] = kept
        result["_truncated"] = {"dropped_results": len(dropped)}
    for item in kept:
        if not isinstance(item, dict):
            continue
        item["content"] = _truncate_text(item.get("content"), max_chars=2000)
        item["description"] = _truncate_text(item.get("description"), max_chars=500)
        item["abstract"] = _truncate_text(item.get("abstract"), max_chars=2000)
        item["summary"] = _truncate_text(item.get("summary"), max_chars=2000)
        item["references"] = _truncate_text(item.get("references"), max_chars=500)
    return result


def _truncate_answer_response(result: dict[str, Any]) -> dict[str, Any]:
    """Truncate valyu_answer response.

    Strategy: keep the AI-generated 'contents' fully intact (it's already
    condensed), but aggressively trim raw source text in citations and
    cap citation count.
    """
    citations = result.get("search_results")
    if isinstance(citations, list):
        kept, dropped = citations[:5], citations[5:]
        if dropped:
            result["search_results"] = kept
            result.setdefault("_truncated", {})["dropped_citations"] = len(dropped)
        for cite in kept:
            if isinstance(cite, dict):
                cite["content"] = _truncate_text(cite.get("content"), max_chars=500)
                cite["description"] = _truncate_text(cite.get("description"), max_chars=500)
    return result


def _truncate_deepresearch_status(result: dict[str, Any]) -> dict[str, Any]:
    """Truncate deepresearch status output (markdown report can be huge)."""
    if isinstance(result.get("output"), str):
        result["output"] = _truncate_text(result["output"], max_chars=6000)
    return result


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
    """搜索引擎模式 — 返回原始搜索结果列表，每条含标题/URL/内容片段。

    WHAT IT RETURNS (vs valyu_answer):
    ┌─────────────────┬──────────────────────────────┬──────────────────────────────┐
    │                 │ valyu_search                 │ valyu_answer                 │
    ├─────────────────┼──────────────────────────────┼──────────────────────────────┤
    │ 返回类型         │ 原始搜索结果列表 (results[])   │ AI 综合后的单段答案 (contents)│
    │ 每条结果         │ title + url + content + desc  │ 整段回答 + 轻量引用列表       │
    │ 结果数量         │ 最多 8 条（服务端截断）        │ 5 条引用（服务端截断）         │
    │ 上下文占用       │ ~6000 字符（8 条 x 多字段）    │ ~3000 字符（单段答案 + 引用）   │
    │ 适用场景         │ "搜一下相关资料"、"有哪些文章"  │ "什么是..."、"怎么实现..."     │
    │ 需要自己整合     │ ✅ 是 — 你需要自己读列表、总结  │ ❌ 否 — AI 已经帮你综合好了     │
    └─────────────────┴──────────────────────────────┴──────────────────────────────┘

    WHEN TO USE THIS (valyu_search):
    - 用户说"搜一下"、"找相关资料"、"有哪些文章讨论 X"
    - 你需要自己挑选、对比多个来源
    - 后续要对某个 URL 深入精读 → 拿到 URL 后用 valyu_contents

    WHEN NOT TO USE — 改用 valyu_answer:
    - 用户直接问问题："什么是 X"、"How to do Y"、"A 和 B 有什么区别"
    - 用户要一个综合答案，而不是原始搜索结果列表

    SERVER TRUNCATION (already applied):
    - Only top 8 results kept; each content capped at 400 chars, description at 200.
    - Dropped results count shown in _truncated field.

    RECOMMENDED PARAMETERS:
    - max_num_results=5          # 限制返回条数
    - url_only=true              # 只返回 snippet，不返回全文（最省 context）
    - response_length="short"     # 结果更精简
    - start_date="2025-01-01"   # 技术内容优先近 1 年

    CROSS-VERIFICATION TIPS:
    - 官方来源：included_sources=["docs.*", "github.com/*/releases*", "*.dev"]
    - 社区验证：included_sources=["reddit.com/r/*", "news.ycombinator.com", "stackoverflow.com"]
    - 先用 url_only=true 快速扫，对关键链接再用 valyu_contents 精读

    Args:
        query: Search string (required).
        search_type: 'all' (default), 'web', 'proprietary', or 'news'.
        max_num_results: Max results (1-100, default 10). RECOMMEND 5.
        is_tool_call: Whether the call originates from an MCP tool (default true).
        relevance_threshold: Float 0-1 (default 0.5).
        max_price: Max price per thousand queries (CPM).
        included_sources: Source strings to include. Use to target official/community sites.
        excluded_sources: Source strings to exclude.
        country_code: 2-letter ISO code or 'ALL'.
        response_length: 'short', 'medium', 'large', 'max', or integer char count. RECOMMEND 'short'.
        category: Natural language category phrase.
        start_date: YYYY-MM-DD. RECOMMEND '2025-01-01' for tech/AI topics.
        end_date: YYYY-MM-DD.
        fast_mode: Faster but shorter results.
        url_only: Return snippets only. RECOMMEND true to save context.
            **REQUIRES search_type='web' or 'news'.** If set with 'all' or
            'proprietary', the API returns 400 — the tool will auto-correct to
            'web' and log a warning.
            NOTE: For direct Q&A use valyu_answer instead; it returns a
            single concise answer with citations and uses far less context.
        source_biases: Dict of source -> int (-5 to +5).
        instructions: Natural language ranking guidance (max 500 chars).
    """
    payload: dict[str, Any] = {"query": query}
    # Guard: url_only is only valid with 'web' or 'news'.
    if url_only and search_type not in ("web", "news"):
        logger.warning(
            "url_only=True requires search_type='web' or 'news'; "
            "got '%s'. Auto-correcting to 'web'.",
            search_type,
        )
        search_type = "web"

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

    result = await _get_client().request("POST", "/search", json_body=payload)
    return _truncate_result_items(result)


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
    """Extract full contents from specific URLs.

    WHEN TO USE:
    - 已从 valyu_search 获取到关键 URL，需要深入阅读具体内容
    - 要验证某个页面的原文、API 文档、Release Notes
    - 单篇/少量文章精读场景

    WHEN NOT TO USE:
    - 不要一上来就用它 — 先用 valyu_search(url_only=true) 筛选出关键 URL
    - 不要一次给 50 个 URL，上下文会爆

    RECOMMENDED PARAMETERS:
    - urls=["https://..."]  # 1-3 个关键 URL，不要超过 5 个
    - summary=true          # ← 默认已设为 true！让 Valyu AI 自己生成摘要，不是返回原始全文
    - response_length="short" # 只提取短内容
    - extract_effort="auto"   # 自动判断提取深度

    Args:
        urls: List of URLs to extract (1-50, required). RECOMMEND 1-3 URLs per call.
        summary: False/null (no AI), True (basic summary), string (custom
            instructions <=500 chars), or JSON schema object. DEFAULTS to True
            to return AI-generated summaries instead of raw full text.
        extract_effort: 'normal', 'high', or 'auto'. RECOMMEND 'auto'.
        response_length: 'short' (25k), 'medium' (50k), 'large' (100k), 'max',
            or integer. RECOMMEND 'short'.
        max_price_dollars: Maximum cost in USD.
        screenshot: Whether to capture a screenshot.
        async_mode: Required when urls > 10. Use async_mode instead of async
            because async is a reserved keyword. RECOMMEND staying under 10 URLs.
        webhook_url: HTTPS webhook (async only).
    """
    # Default summary=True so Valyu returns AI-generated summaries
    # instead of raw full text, saving huge context tokens.
    effective_summary = True if summary is None else summary
    payload: dict[str, Any] = {"urls": urls, "summary": effective_summary}
    for key, value in [
        ("extract_effort", extract_effort),
        ("response_length", response_length),
        ("max_price_dollars", max_price_dollars),
        ("screenshot", screenshot),
        ("async", async_mode),
        ("webhook_url", webhook_url),
    ]:
        if value is not None:
            payload[key] = value

    result = await _get_client().request("POST", "/contents", json_body=payload)
    return result  # No truncation — user explicitly wants full extracted content


@mcp.tool()
async def valyu_contents_status(job_id: str) -> dict[str, Any]:
    """Check the status of an async contents extraction job.

    WHEN TO USE:
    - 仅在之前调用 valyu_contents 时返回了 job_id（async_mode 或 URLs > 10）
    - 轮询检查进度直到 status="completed"

    WHEN NOT TO USE:
    - 同步调用 valyu_contents 时不会返回 job_id，无需调用

    Args:
        job_id: The job ID returned by valyu_contents.
    """
    result = await _get_client().request("GET", f"/contents/job/{job_id}")
    return result  # No truncation — user explicitly wants full extracted content


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
    """问答模式 — 返回一段 AI 综合后的完整答案 + 引用来源。

    WHAT IT RETURNS (vs valyu_search):
    ┌─────────────────┬──────────────────────────────┬──────────────────────────────┐
    │                 │ valyu_answer                 │ valyu_search                 │
    ├─────────────────┼──────────────────────────────┼──────────────────────────────┤
    │ 返回类型         │ AI 综合后的单段答案 (contents) │ 原始搜索结果列表 (results[])   │
    │ 每条结果         │ 整段回答 + 轻量引用列表         │ title + url + content + desc  │
    │ 结果数量         │ 5 条引用（服务端截断）          │ 最多 8 条（服务端截断）         │
    │ 上下文占用       │ ~3000 字符（单段答案 + 引用）   │ ~6000 字符（8 条 x 多字段）     │
    │ 适用场景         │ "什么是..."、"怎么实现..."       │ "搜一下相关资料"、"有哪些文章"  │
    │ 需要自己整合     │ ❌ 否 — AI 已经帮你综合好了     │ ✅ 是 — 你需要自己读列表、总结  │
    └─────────────────┴──────────────────────────────┴──────────────────────────────┘

    WHEN TO USE THIS (valyu_answer):
    - 用户直接问问题："什么是 X"、"How to do Y"、"A 和 B 有什么区别"
    - 需要一个综合答案，不想自己翻搜索结果列表
    - 上下文紧张，需要最精简的信息获取方式

    WHEN NOT TO USE — 改用 valyu_search:
    - 用户说"搜一下"、"找相关资料"、"给我一些参考文章"
    - 你需要自己挑选、对比多个原始来源

    SERVER TRUNCATION (already applied):
    - Only top 5 citations kept; each citation content/description capped
      at 400/200 chars. The AI-generated 'contents' answer is preserved intact.

    RECOMMENDED PARAMETERS:
    - start_date="2025-01-01"  # 技术/AI 问题优先近 1 年
    - data_max_price=0.5       # 控制成本
    - fast_mode=true           # 更快，通常够用了

    Args:
        query: The question (required).
        search_type: 'all', 'web', 'proprietary', or 'news'.
        data_max_price: Max data cost (default 1.0). RECOMMEND 0.5 for routine queries.
        fast_mode: Faster but potentially less thorough. RECOMMEND true for speed.
        country_code: 2-letter ISO code.
        included_sources: Source strings to include.
        excluded_sources: Source strings to exclude.
        start_date: YYYY-MM-DD. RECOMMEND '2025-01-01' for tech/AI topics.
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

    result = await _get_client().request("POST", "/answer", json_body=payload)
    return _truncate_answer_response(result)


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
    """Create an async deep-research task for complex multi-dimensional research.

    WHEN TO USE:
    - 用户要求"深度调研"、"写一份报告"、"全面分析 X"
    - 需要跨多个来源、多轮搜索、自动分析的综合研究
    - 问题维度多（技术 + 市场 + 竞品 + 趋势），单次搜索搞不定

    WHEN NOT TO USE:
    - 简单事实查询 → 用 valyu_answer（更快）
    - 只需要搜索结果列表 → 用 valyu_search
    - 需要立即拿到结果 → 这是异步任务，需要轮询 valyu_deepresearch_status

    RECOMMENDED PARAMETERS:
    - mode="standard"           # fast=快但浅, standard=平衡, heavy/max=最深入
    - output_formats=["markdown"] # 最常用格式
    - query 越详细越好，说明研究目标和范围

    WORKFLOW:
    1. 调用 create → 获得 deepresearch_id
    2. 轮询 valyu_deepresearch_status(deepresearch_id) 直到完成
    3. 返回的结果中包含 output（markdown/pdf 内容）

    Args:
        query: Research task description (max 25,000 chars, required). Be detailed.
        mode: 'fast', 'standard', 'heavy', or 'max'. RECOMMEND 'standard'.
        output_formats: e.g. ['markdown'] or ['markdown', 'pdf']. RECOMMEND ['markdown'].
        research_strategy: Natural language strategy (max 15,000 chars combined
            with report_format).
        report_format: Natural language output format instructions.
        search: SearchConfig dict. Optional fine-tuning of search behavior.
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
    """Poll the status of an async deep-research task.

    WHEN TO USE:
    - 调用 valyu_deepresearch_create 后，轮询检查进度
    - status 可能是: queued → processing → completed / failed
    - completed 时 output 字段包含研究成果

    WHEN NOT TO USE:
    - 不要在没有创建任务前调用

    Args:
        task_id: The deep-research task ID returned by valyu_deepresearch_create.
    """
    result = await _get_client().request("GET", f"/deepresearch/{task_id}")
    return _truncate_deepresearch_status(result)


@mcp.tool()
async def valyu_deepresearch_list(limit: int | None = None) -> dict[str, Any]:
    """List all async deep-research tasks.

    WHEN TO USE:
    - 查看之前创建过哪些研究任务
    - 找之前任务的 task_id 来查状态

    WHEN NOT TO USE:
    - 已知 task_id 时直接调 valyu_deepresearch_status，不用 list

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
    """List available Valyu datasources (what Valyu can search).

    WHEN TO USE:
    - 想知道 Valyu 支持哪些数据库/来源（PubMed、新闻、专利等）
    - 要定向搜索某个专业领域时，先看有什么数据源

    WHEN NOT TO USE:
    - 一般搜索不需要先调这个，直接用 valyu_search 即可
    - 除非用户明确问"你们支持搜什么"
    """
    return await _get_client().request("GET", "/datasources")


@mcp.tool()
async def valyu_datasources_categories() -> dict[str, Any]:
    """List datasource categories (healthcare, finance, tech, etc.).

    WHEN TO USE:
    - 想了解 Valyu 数据源按什么领域分类
    - 配合 valyu_datasources_list 一起看有哪些专业领域

    WHEN NOT TO USE:
    - 一般搜索不需要先调这个
    """
    return await _get_client().request("GET", "/datasources/categories")
