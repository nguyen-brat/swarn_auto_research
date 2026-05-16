# swarn_research_mcp

`swarn_research_mcp` is the MCP-facing research package for Swarn Auto
Research. It exposes paper-discovery and paper-reading tools, then delegates
network calls to service modules for Semantic Scholar, Hugging Face Papers,
arxiv2md, and alphaXiv.

## Purpose

The package is designed to help an MCP client discover relevant research papers
and retrieve paper content. Its main workflow gathers candidate papers from
multiple sources, filters them by topic keywords, validates relevance with a
Codex session, writes selected `arxiv_id -> abstract` results to JSON, and
returns the selected papers plus the output path.

## Public MCP Tools

The MCP server is built in `server.py` and registers three tools:

- `bulk_normal_start_search`: Runs broad paper discovery for normal and survey
  queries. It combines Semantic Scholar relevance searches, Semantic Scholar
  recommendations, Hugging Face paper search, recent Hugging Face trending
  papers, keyword filtering, and Codex-based relevance validation.
- `get_paper_markdown`: Fetches the full Markdown text for an arXiv paper via
  arxiv2md.
- `get_paper_section`: Fetches an arXiv paper as Markdown and returns one
  requested section. Nested section paths use `/` separators.

Each registered MCP tool is wrapped with retry logic. By default, tools get up
to five total attempts, with a retry delay controlled by
`AUTO_RESEARCH_MCP_RETRY_DELAY_SECONDS`.

## Folder Map

```text
swarn_research_mcp/
  __init__.py
  server.py
  tools/
    paper_search.py
    select_paper.py
  services/
    alphaxiv.py
    arxiv.py
    huggingface.py
    semantic_scholar.py
    utils.py
    external/
      get_active_proxy.py
      get_proxy_free.py
      proxy.txt
```

## Module Responsibilities

`server.py` creates the FastMCP server named `swarn-auto-research`, registers
the exported tools, and provides the package entry point used by the
`swarn-auto-research-mcp` console script.

`tools/paper_search.py` contains the main orchestration layer. It searches paper
sources, collects recommendations and trending papers, filters by keywords,
calls Codex to validate final relevance, writes JSON output, and exposes paper
Markdown helpers.

`tools/select_paper.py` contains local filtering logic. It normalizes keyword
lists, excludes papers with negative keywords, keeps papers matching positive
keywords, and drops arXiv papers older than six years when the year can be
derived from the arXiv ID.

`services/semantic_scholar.py` wraps Semantic Scholar Graph and
Recommendations APIs. It supports relevance search, batch paper detail fetches,
recommendations, citation expansion, citation-network building, impact scoring,
simple in-memory detail caching, and rate-limit-aware request serialization.

`services/huggingface.py` wraps Hugging Face paper search and daily papers
endpoints. It requires `HF_TOKEN` and returns paper IDs mapped to summaries.

`services/arxiv.py` fetches Markdown from arxiv2md and extracts requested
Markdown sections by heading path.

`services/alphaxiv.py` contains alphaXiv search, overview, similar-paper, and
preview helpers. These helpers are available in the service layer but are not
currently registered as MCP tools in `server.py`.

`services/utils.py` provides shared blocking-call execution, HTTP GET/POST
helpers with direct retries and proxy fallback, proxy-pool loading, and
`safe_get` for nested dictionary/list access.

`services/external/` contains helper scripts for collecting free proxies,
testing them, and storing the working proxy list used by `services/utils.py`.

## Main Discovery Flow

1. `bulk_normal_start_search` creates the output directory and computes recent
   date windows.
2. For each normal query, it launches Semantic Scholar relevance searches across
   older, middle, and recent windows, searches Hugging Face papers, and uses the
   Hugging Face results as positive seeds for Semantic Scholar recommendations.
3. For each survey query, it runs smaller Semantic Scholar searches over recent
   year windows.
4. It merges monthly Hugging Face trending papers from the last twelve months.
5. `select_papers` filters candidates using positive and negative keywords.
6. Codex relevance validation checks filtered papers in chunks and keeps only
   IDs judged related to the combined query topic.
7. The final `arxiv_id -> abstract` map is written to
   `bulk_search_results_<timestamp>.json` in the requested output directory.

## Configuration

Environment variables used by the package:

- `HF_TOKEN`: Required by Hugging Face paper endpoints.
- `S2_KEY`: Optional Semantic Scholar API key. Without it, public endpoints are
  used with shared rate limits.
- `S2_KEYS`: Optional comma-separated ordered list of Semantic Scholar API
  keys. Use this in `.env` when you have multiple keys, for example
  `S2_KEYS=key_one,key_two`. On HTTP 429 the client rotates to the next key
  before retrying. `S2_KEY` remains supported and is appended after `S2_KEYS`
  when both are set.
- `S2_LINKED_BATCH_LIMIT`: Optional batch size override for Semantic Scholar
  linked-paper detail fetches.
- `S2_RATE_LIMIT_BACKOFF_SECONDS`: Optional extra wait after Semantic Scholar
  returns HTTP 429. Defaults to `30`.
- `AUTO_RESEARCH_MCP_RETRY_DELAY_SECONDS`: Optional retry delay for MCP tool
  wrappers. Defaults to `0.5`.

The package also depends on the local `sdk.codex` module for Codex relevance
validation inside `tools/paper_search.py`.

## Notes and Caveats

- Network access is central to this package. Most service helpers call external
  APIs and can fail due to credentials, rate limits, proxy quality, or upstream
  availability.
- `services/utils.py` loads the proxy pool at import time. If
  `services/external/proxy.txt` is missing, it attempts to fetch and test free
  proxies.
- The currently registered MCP tools are limited to the three functions listed
  in `server.py`; other service helpers are internal or available only through
  direct Python imports.
- Generated `__pycache__` folders are runtime artifacts and are not part of the
  package design.
