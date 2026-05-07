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


MCP_TOOL_SPECS: tuple[MCPToolSpec, ...] = (
    MCPToolSpec(
        function=bulk_normal_start_search,
        description=(
            "Run a broad research-paper discovery workflow for one or more topic queries. "
            "Searches Semantic Scholar, Hugging Face paper search, recommendations, and recent "
            "Hugging Face trending papers, filters by positive and negative keywords, validates "
            "topic relevance, writes the final arXiv-id-to-abstract JSON file to output_dir, and "
            "returns the selected papers plus the output path."
        ),
    ),
    MCPToolSpec(
        function=get_paper_markdown,
        description=(
            "Fetch the full Markdown text for an arXiv paper by arXiv ID using arxiv2md. "
            "Use this when the caller needs the complete paper content for reading or later "
            "section extraction."
        ),
    ),
    MCPToolSpec(
        function=get_paper_section,
        description=(
            "Fetch an arXiv paper and return only one requested Markdown section. "
            "The section path can target nested headings with slash separators, for example "
            "'Model Architecture/Encoder and Decoder Stacks/Encoder:'."
        ),
    ),
    MCPToolSpec(
        function=get_alphaxiv_overview,
        description=(
            "Fetch the alphaXiv overview Markdown for an arXiv paper by arXiv ID. "
            "Returns a dict with arxiv_id and markdown. Use during cheap enrichment "
            "before fetching the full paper."
        ),
    ),
    MCPToolSpec(
        function=get_paper_metadata,
        description=(
            "Fetch Semantic Scholar metadata for one arXiv paper by arXiv ID. "
            "Returns abstract, citationCount, referenceCount, and arxiv IDs of "
            "direct citations and references. Returns {arxiv_id, found: false} "
            "when the paper is not in Semantic Scholar."
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
        server.tool(description=tool_spec.description)(
            with_mcp_tool_retries(tool_spec.function)
        )
    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
