"""Swarn Auto Research MCP server."""

from __future__ import annotations

import asyncio
import functools
import inspect
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

from swarn_research_mcp.tools.paper_search import (
    bulk_normal_start_search,
    gap_paper_search,
    get_alphaxiv_overview,
    get_paper_markdown,
    get_paper_metadata,
    get_paper_section,
)


MAX_MCP_TOOL_ATTEMPTS = 5
MCP_TOOL_RETRY_DELAY_SECONDS_ENV = "AUTO_RESEARCH_MCP_RETRY_DELAY_SECONDS"


@dataclass(frozen=True)
class MCPToolSpec:
    function: Callable[..., Any]
    description: str
    retry_attempts: int = MAX_MCP_TOOL_ATTEMPTS


MCP_TOOL_SPECS: tuple[MCPToolSpec, ...] = (
    MCPToolSpec(
        function=bulk_normal_start_search,
        description=(
            "Discover research papers across Semantic Scholar, Hugging Face search, "
            "Hugging Face trending, and Semantic Scholar recommendations, then keyword-"
            "filter and topic-validate the results.\n\n"
            "INPUT (all four list params are REQUIRED, all are lists of strings — "
            "DO NOT pass a single newline-joined string; pass a JSON array):\n"
            "  - queries: list[str] — one search topic per element.\n"
            "      example: [\"long context attention\", \"sparse attention LLM\"]\n"
            "  - survey_queries: list[str] — survey/review search topics.\n"
            "      example: [\"survey efficient long-context attention\"]\n"
            "  - positive_keywords: list[str] — kept-paper must mention at least one.\n"
            "      example: [\"long-context\", \"sparse attention\"]\n"
            "  - negative_keywords: list[str] — paper rejected if it matches any.\n"
            "      example: [\"vision only\", \"speech only\"]\n"
            "  - output_dir (optional, str): when set, the final paper-id→abstract "
            "JSON is written to `{output_dir}/bulk_search_results_{ts}.json`.\n\n"
            "OUTPUT: dict with shape\n"
            "  {\n"
            "    \"keywords\": [...],\n"
            "    \"negative_keywords\": [...],\n"
            "    \"total_input\": int,\n"
            "    \"total_kept\": int,\n"
            "    \"papers\": {\"<arxiv_id>\": \"<abstract>\", ...},\n"
            "    \"output_path\": \"...\" (only when output_dir was set)\n"
            "  }\n\n"
            "Each list parameter is auto-coerced if a string slips in (newlines or "
            "commas → list), but DO NOT rely on that — pass arrays."
        ),
        retry_attempts=1,
    ),
    MCPToolSpec(
        function=gap_paper_search,
        description=(
            "Lightweight Stage 6 gap-expansion paper search using Hugging Face "
            "paper search plus alphaXiv paper search. Use this for knowledge-gap "
            "expansion shards instead of bulk_normal_start_search.\n\n"
            "INPUT:\n"
            "  - queries: list[str] — one gap search query per element.\n"
            "  - positive_keywords (optional, list[str]) — kept paper abstracts "
            "must mention at least one term when provided.\n"
            "  - negative_keywords (optional, list[str]) — reject abstracts "
            "matching any term.\n"
            "  - limit_per_query (optional, int, default 30): Hugging Face search "
            "limit for each query. alphaXiv search does not expose a local limit.\n"
            "  - output_dir (optional, str): when set, writes the final "
            "paper-id→abstract JSON to `{output_dir}/gap_search_results_{ts}.json`.\n\n"
            "OUTPUT: dict with shape compatible with bulk_normal_start_search:\n"
            "  {keywords, negative_keywords, total_input, total_kept, papers, "
            "queries, query_audit, output_path?}.\n\n"
            "This tool intentionally does NOT call Semantic Scholar, "
            "recommendations, or Codex relevance validation."
        ),
        retry_attempts=1,
    ),
    MCPToolSpec(
        function=get_paper_markdown,
        description=(
            "Fetch the full Markdown of one arXiv paper via arxiv2md.\n\n"
            "INPUT:\n"
            "  - arxiv_id: str — the arXiv ID (e.g. \"2304.08485\"). Pass ONE id, "
            "not a list, not a URL.\n"
            "  - output_dir (optional, str): when set, the markdown is written to "
            "`{output_dir}/{arxiv_id}.md`.\n\n"
            "OUTPUT (when output_dir is unset): {\"arxiv_id\": str, \"markdown\": str}.\n"
            "OUTPUT (when output_dir is set): {\"arxiv_id\": str, \"output_path\": str}.\n"
            "OUTPUT (on failure): {\"arxiv_id\": str, \"markdown\": \"\", \"error\": "
            "\"<TypeName: msg>\"} — no file is written even if output_dir was set."
        ),
    ),
    MCPToolSpec(
        function=get_paper_section,
        description=(
            "Fetch one Markdown section from an arXiv paper.\n\n"
            "INPUT:\n"
            "  - arxiv_id: str — the arXiv ID. Pass ONE id, not a list.\n"
            "  - section: str — a heading title or slash-delimited heading path.\n"
            "      Heading lookup is case-insensitive and ignores numeric prefixes "
            "(\"1 Introduction\" matches \"introduction\").\n"
            "      example: \"Method\" or \"Model Architecture/Encoder Stacks\"\n"
            "  - output_dir (optional, str): when set, writes the section text to "
            "`{output_dir}/{arxiv_id}__{slug}.md`.\n\n"
            "OUTPUT (no output_dir): {\"arxiv_id\": str, \"section_path\": str, "
            "\"section\": str}.\n"
            "OUTPUT (with output_dir): {\"arxiv_id\": str, \"section_path\": str, "
            "\"output_path\": str}.\n"
            "OUTPUT (failure / heading not found): {\"arxiv_id\": str, "
            "\"section_path\": str, \"section\": \"\", \"error\": \"...\"}."
        ),
    ),
    MCPToolSpec(
        function=get_alphaxiv_overview,
        description=(
            "Fetch the alphaXiv overview Markdown for one arXiv paper. Use during "
            "cheap enrichment before fetching the full paper.\n\n"
            "INPUT:\n"
            "  - arxiv_id: str — the arXiv ID. Pass ONE id, not a list.\n"
            "  - output_dir (optional, str): when set, writes the JSON to "
            "`{output_dir}/{arxiv_id}.json`.\n\n"
            "OUTPUT (no output_dir): {\"arxiv_id\": str, \"markdown\": str}.\n"
            "OUTPUT (with output_dir): {\"arxiv_id\": str, \"output_path\": str}.\n"
            "OUTPUT (failure, including paper has no alphaXiv overview): "
            "{\"arxiv_id\": str, \"markdown\": \"\", \"error\": \"<TypeName: msg>\"}."
        ),
    ),
    MCPToolSpec(
        function=get_paper_metadata,
        description=(
            "Fetch Semantic Scholar metadata for one or more arXiv papers in a "
            "single batched POST. On HTTP 429 the batch is automatically halved "
            "and retried until every sub-batch succeeds.\n\n"
            "INPUT:\n"
            "  - arxiv_ids: list[str] — pass a JSON array of arXiv IDs. A single "
            "string id is accepted for convenience but lists are preferred.\n"
            "      example: [\"2304.08485\", \"2103.00020\"]\n"
            "  - output_dir (optional, str): when set, writes one "
            "`{output_dir}/{arxiv_id}.json` per id.\n\n"
            "OUTPUT: {\"results\": [<row>, <row>, ...]} where each row matches "
            "input order and is one of:\n"
            "  - flat metadata dict: {arxiv_id, scholar_semantic_id, title, year, "
            "abstract, citationCount, referenceCount}\n"
            "  - {arxiv_id, found: false} — not in Semantic Scholar.\n"
            "  - {arxiv_id, found: false, error: \"<TypeName: msg>\"} — transport/HTTP error.\n"
            "When output_dir is set, success rows are replaced with "
            "{arxiv_id, output_path[, found: false]}; error rows stay in-line and "
            "are NOT written to disk."
        ),
    ),
)


def _default_retry_delay_seconds() -> float:
    raw_delay = os.environ.get(MCP_TOOL_RETRY_DELAY_SECONDS_ENV, "0.5")
    try:
        return max(0.0, float(raw_delay))
    except ValueError:
        return 0.5


def with_mcp_tool_retries(
    func: Callable[..., Any],
    attempts: int = MAX_MCP_TOOL_ATTEMPTS,
    sleep_seconds: float | None = None,
) -> Callable[..., Any]:
    """Wrap an MCP tool so transient failures get up to five total attempts."""

    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    delay = _default_retry_delay_seconds() if sleep_seconds is None else sleep_seconds

    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapped(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(1, attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception:
                    if attempt == attempts:
                        raise
                    if delay > 0:
                        await asyncio.sleep(delay * attempt)
            raise RuntimeError("unreachable retry state")

        wrapped: Callable[..., Any] = async_wrapped
    else:

        @functools.wraps(func)
        def sync_wrapped(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception:
                    if attempt == attempts:
                        raise
                    if delay > 0:
                        time.sleep(delay * attempt)
            raise RuntimeError("unreachable retry state")

        wrapped = sync_wrapped

    setattr(wrapped, "_auto_research_retry_wrapped", True)
    setattr(wrapped, "_auto_research_retry_attempts", attempts)
    return wrapped


def build_server(server_factory: Callable[[str], Any] | None = None):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        if server_factory is None:
            raise RuntimeError("Install mcp to run the Swarn Auto Research MCP server.") from exc
    else:
        if server_factory is None:
            server_factory = FastMCP

    if server_factory is None:
        raise RuntimeError("Install mcp to run the Swarn Auto Research MCP server.")

    server = server_factory("swarn-auto-research")
    for tool_spec in MCP_TOOL_SPECS:
        if tool_spec.retry_attempts <= 1:
            wrapped = tool_spec.function
        else:
            wrapped = with_mcp_tool_retries(
                tool_spec.function, attempts=tool_spec.retry_attempts
            )
        server.tool(description=tool_spec.description)(wrapped)
    return server


def _redirect_print_to_stderr() -> None:
    """Stdio MCP transport reserves stdout for JSON-RPC. Any stray
    `print()` from services corrupts framing and the client reports
    `Transport closed`. Redirect builtin print to stderr so existing
    diagnostic logs stay visible without breaking the protocol."""
    import builtins
    import sys

    real_print = builtins.print

    def print_to_stderr(*args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("file", sys.stderr)
        real_print(*args, **kwargs)

    builtins.print = print_to_stderr  # type: ignore[assignment]


def main() -> None:
    _redirect_print_to_stderr()
    build_server().run()


if __name__ == "__main__":
    main()
