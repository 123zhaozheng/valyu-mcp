# Valyu API Research Findings

## Base URL
```
https://api.valyu.ai/v1
```

## Authentication
- **Header name**: `x-api-key`
- **Format**: Plain string (no `Bearer` prefix)
- **Source**: `VALYU_API_KEY` environment variable, or passed directly to client constructor
- The SDK also sends additional headers for telemetry but only `x-api-key` is required for auth:
  - `Content-Type: application/json`
  - `User-Agent: valyu-py/{version} python/{pyversion}`
  - `X-Valyu-SDK: valyu-py`
  - `X-Valyu-SDK-Version: {version}`

## Error Response Format
All API errors return JSON with these fields:
```json
{
  "error": "ErrorType",
  "message": "Human-readable description"
}
```

Observed examples:
- Missing/invalid key: `HTTP 401` → `{"error": "Unauthorized", "message": "API key is missing or invalid"}`
- Invalid/disabled key: `HTTP 403` → `{"error": "Forbidden", "message": "Access denied - API key is invalid, disabled, or revoked"}`

The Python SDK wraps HTTP errors into its own response models (e.g., `SearchResponse`, `ContentsResponse`) with:
- `success: false`
- `error: <message>`
- `tx_id: <transaction id or error code>`

**Open question — quota / rate limits**: No explicit `X-RateLimit-*` or `Retry-After` headers were observed in limited probing. Quota exhaustion likely signals through the standard JSON error format with `HTTP 403` or possibly `HTTP 429`. This should be confirmed with live traffic or Valyu support.

## Available Endpoints

### 1. Search
- **Method**: `POST /search`
- **Request body** (all fields optional unless marked required):
  - `query` *(required)* — search string
  - `search_type` — `"all"` (default), `"web"`, `"proprietary"`, `"news"`
  - `max_num_results` — int, 1-100, default 10
  - `is_tool_call` — bool, default true
  - `relevance_threshold` — float 0-1, default 0.5
  - `max_price` — int, max price per thousand queries (CPM)
  - `included_sources` — list of source strings (domain, URL path, or `provider/dataset-name`)
  - `excluded_sources` — same format as included
  - `country_code` — 2-letter ISO code or `"ALL"`
  - `response_length` — `"short"`, `"medium"`, `"large"`, `"max"`, or integer char count
  - `category` — natural language category phrase
  - `start_date` / `end_date` — `YYYY-MM-DD`
  - `fast_mode` — bool, faster but shorter results
  - `url_only` — bool, return snippets only
  - `source_biases` — dict of source → int (-5 to +5)
  - `instructions` — string, max 500 chars, natural language ranking guidance
- **Response**: `SearchResponse`
  ```json
  {
    "success": true,
    "error": null,
    "tx_id": "...",
    "query": "...",
    "results": [ /* SearchResult objects */ ],
    "results_by_source": { "web": 5, "proprietary": 3 },
    "total_deduction_dollars": 0.01,
    "total_characters": 15000
  }
  ```

### 2. Contents (URL extraction)
- **Method**: `POST /contents`
- **Request body**:
  - `urls` *(required)* — list of strings, 1-50
  - `summary` — `false`/`null` (no AI), `true` (basic summary), string (custom instructions ≤500 chars), or JSON schema object
  - `extract_effort` — `"normal"`, `"high"`, `"auto"`
  - `response_length` — `"short"` (25k), `"medium"` (50k), `"large"` (100k), `"max"`, or integer
  - `max_price_dollars` — float
  - `screenshot` — bool
  - `async` — bool (required when `urls` > 10)
  - `webhook_url` — string (HTTPS, async only)
- **Response (sync)**: `ContentsResponse`
  ```json
  {
    "success": true,
    "error": null,
    "tx_id": "...",
    "urls_requested": 2,
    "urls_processed": 2,
    "urls_failed": 0,
    "results": [ /* ContentsResultSuccess | ContentsResultFailed */ ],
    "total_cost_dollars": 0.005,
    "total_characters": 8000
  }
  ```
- **Response (async, 202 Accepted)**: `ContentsJobCreateResponse`
  ```json
  {
    "success": true,
    "job_id": "...",
    "status": "pending",
    "urls_total": 20,
    "poll_url": "...",
    "webhook_secret": "..."
  }
  ```

### 3. Contents Job Status
- **Method**: `GET /contents/job/{job_id}`
- **Response**: `ContentsJobStatus`
  ```json
  {
    "success": true,
    "job_id": "...",
    "status": "pending" | "processing" | "completed" | "partial" | "failed",
    "urls_total": 20,
    "urls_processed": 10,
    "urls_failed": 0,
    "results": [ ... ],
    "actual_cost_dollars": 0.05,
    "error": null
  }
  ```

### 4. Answer
- **Method**: `POST /answer`
- **Request body**:
  - `query` *(required)* — string
  - `search_type` — `"all"`, `"web"`, `"proprietary"`, `"news"`
  - `data_max_price` — float > 0, default 1.0
  - `fast_mode` — bool
  - `country_code` — string
  - `included_sources` / `excluded_sources` — list of strings
  - `start_date` / `end_date` — `YYYY-MM-DD`
  - `structured_output` — JSON schema object
  - `system_instructions` — string ≤ 2000 chars
- **Response**: `AnswerSuccessResponse` or `AnswerErrorResponse`
  - `success: true` → `contents` (AI answer), `search_results` (citations), `search_metadata`, `ai_usage`, `cost_breakdown`
  - `success: false` → `error`, `tx_id`
- **Streaming**: supported via SSE (server-sent events); chunks are `AnswerStreamChunk`

### 5. DeepResearch
- **Method**: `POST /deepresearch`
- **Request body**:
  - `query` *(required)* — research task description, max 25,000 chars
  - `mode` — `"fast"`, `"standard"`, `"heavy"`, `"max"`
  - `output_formats` — list: `["markdown"]`, `["markdown", "pdf"]`, or JSON schema object
  - `research_strategy` — natural language strategy, max 15,000 chars combined with `report_format`
  - `report_format` — natural language output format instructions
  - `search` — `SearchConfig` dict (`search_type`, `included_sources`, `excluded_sources`, `start_date`, `end_date`, `category`, `country_code`, `source_biases`)
  - `urls` — list of URLs to extract and analyze
  - `files` — list of `FileAttachment` objects (base64 data, filename, mediaType, optional context ≤10k chars)
  - `deliverables` — list of deliverable configs (CSV, XLSX, PPTX, DOCX, PDF), max 10
  - `mcp_servers` — list of `MCPServerConfig` objects
  - `tools` — dict of tool configs (`browser_use`, `screenshots`, `code_execution`)
  - `previous_reports` — list of report IDs, max 3
  - `webhook_url` — HTTPS URL
  - `alert_email` — string email or `AlertEmailConfig` dict
  - `brand_collection_id` — string
  - `hitl` — `HitlConfig` dict (checkpoints: `planning_questions`, `plan_review`, `source_review`, `outline_review`)
  - `metadata` — dict of custom key-value pairs
- **Response**: `DeepResearchCreateResponse`
  ```json
  {
    "success": true,
    "deepresearch_id": "...",
    "status": "queued",
    "message": "Research task created successfully"
  }
  ```

### 6. DeepResearch Status
- **Method**: `GET /deepresearch/{task_id}`
- **Response**: `DeepResearchStatusResponse`
  - Fields: `success`, `deepresearch_id`, `status`, `progress` (`current_step`, `total_steps`), `output`, `pdf_url`, `error`, etc.

### 7. DeepResearch Update
- **Method**: `POST /deepresearch/{task_id}/update`
- **Body**: `{ "instruction": "..." }`
- **Response**: `DeepResearchUpdateResponse`

### 8. DeepResearch Cancel
- **Method**: `POST /deepresearch/{task_id}/cancel`
- **Response**: `DeepResearchCancelResponse`

### 9. DeepResearch Delete
- **Method**: `DELETE /deepresearch/{task_id}`
- **Response**: `DeepResearchDeleteResponse`

### 10. DeepResearch Toggle Public
- **Method**: `POST /deepresearch/{task_id}/public`
- **Body**: `{ "is_public": true/false }`
- **Response**: `DeepResearchTogglePublicResponse`

### 11. DeepResearch Respond (HITL)
- **Method**: `POST /deepresearch/{task_id}/respond`
- **Body**: `{ "response": "..." }`
- **Response**: `DeepResearchRespondResponse`

### 12. DeepResearch List
- **Method**: `GET /deepresearch`
- **Query params**: `api_key_id`, `limit`
- **Response**: `DeepResearchListResponse`

### 13. DeepResearch Batch — Create
- **Method**: `POST /deepresearch/batches`
- **Body**: `name`, `mode`, `output_formats`, `search`, `webhook_url`, `brand_collection_id`, `metadata`
- **Response**: `BatchCreateResponse`

### 14. DeepResearch Batch — Status
- **Method**: `GET /deepresearch/batches/{batch_id}`
- **Response**: `BatchStatusResponse`

### 15. DeepResearch Batch — Add Tasks
- **Method**: `POST /deepresearch/batches/{batch_id}/tasks`
- **Body**: `{ "tasks": [ { "query": "...", ... }, ... ] }`
- **Response**: `BatchAddTasksResponse`

### 16. DeepResearch Batch — List Tasks
- **Method**: `GET /deepresearch/batches/{batch_id}/tasks`
- **Response**: `BatchTasksListResponse`

### 17. DeepResearch Batch — Cancel
- **Method**: `POST /deepresearch/batches/{batch_id}/cancel`
- **Response**: `BatchCancelResponse`

### 18. List Batches
- **Method**: `GET /deepresearch/batches`
- **Response**: `BatchListResponse`

### 19. Datasources List
- **Method**: `GET /datasources`
- **Response**: `DatasourcesResponse`
  ```json
  {
    "success": true,
    "datasources": [
      {
        "id": "valyu/valyu-pubmed",
        "name": "PubMed",
        "description": "...",
        "category": "healthcare",
        "type": "...",
        "modality": ["text"],
        "topics": [...],
        "languages": [...],
        "source": "...",
        "example_queries": [...],
        "pricing": { "cpm": 0.5 },
        "response_schema": { ... },
        "update_frequency": "daily",
        "size": 1000000,
        "coverage": { "start_date": "...", "end_date": "..." }
      }
    ]
  }
  ```

### 20. Datasources Categories
- **Method**: `GET /datasources/categories`
- **Response**: `DatasourceCategoriesResponse`
  ```json
  {
    "success": true,
    "categories": [
      { "id": "research", "name": "Research", "description": "...", "dataset_count": 10 }
    ]
  }
  ```

## Data Types Summary

### SearchResult
| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Result title |
| `url` | string | Source URL |
| `content` | string / list / dict | Main content (can be structured) |
| `description` | string | Short description |
| `source` | string | Source identifier |
| `price` | float | Cost in USD |
| `length` | int | Character count |
| `image_url` | dict | Image URL object |
| `relevance_score` | float | 0-1 relevance |
| `data_type` | `"structured"` / `"unstructured"` | Content type |
| `source_type` | string | Source type label |
| `publication_date` | string | ISO date |
| `id` | string | Unique result ID |
| `abstract` | string | Abstract text |
| `doi` | string | DOI identifier |
| `citation` | string | Citation string |
| `citation_count` | int | Citation count |
| `authors` | list of strings | Author names |
| `references` | string | Reference info |
| `metadata` | dict | Extra metadata |

### SearchType
Literal: `"web"`, `"proprietary"`, `"all"`, `"news"`

### ContentsResultSuccess
| Field | Type | Description |
|-------|------|-------------|
| `url` | string | Original URL |
| `status` | `"success"` | Fixed literal |
| `title` | string | Page title |
| `content` | string / number | Extracted content |
| `length` | int | Character count |
| `source` | string | Source domain |
| `source_type` | string | Type label |
| `screenshot_url` | string | Pre-signed S3 URL |
| `summary` | string / dict | AI summary or structured extraction |
| `publication_date` | string | Date |

### ContentsResultFailed
| Field | Type | Description |
|-------|------|-------------|
| `url` | string | Original URL |
| `status` | `"failed"` | Fixed literal |
| `error` | string | Error message |

## Official MCP Server Reference
- **Repo**: `https://github.com/valyuAI/valyu-mcp`
- **Framework**: `fastmcp` (Python MCP SDK)
- **Transport**: `stdio` (official server only supports stdio)
- **Exposed tools**: `valyu_context` (search only — calls `valyu.context()` with `query`, `search_type="all"`, `max_num_results`, `max_price=10`, `query_rewrite=False`)
- **Key limitation**: Official server is stdio-only and exposes only a single search tool with limited parameters

## SDK Behavior Notes
- The sync client uses `requests.Session` with `HTTPAdapter(pool_connections=max_connections, pool_maxsize=max_connections, max_retries=0)` — **no automatic retries**
- Timeout defaults to 600 seconds
- The async client uses `httpx.AsyncClient` with the same timeout
- All endpoints return Pydantic v2 models with `success` boolean, `error` nullable string, and `tx_id` string
- The SDK never raises on API errors; it catches exceptions and returns error response objects

## Gaps / To Be Confirmed During Implementation
1. **Quota exhaustion signal**: Need to observe actual `HTTP 429` or `403` response with `{"error": "...", "message": "..."}` when credits run out. No dedicated rate-limit headers were observed in limited probing.
2. **Rate limit headers**: Whether `X-RateLimit-*` or `Retry-After` headers are returned on `429` responses.
3. **Exact HTTP transport for fastmcp**: Need to verify `fastmcp` HTTP/SSE transport setup pattern (docs needed).
