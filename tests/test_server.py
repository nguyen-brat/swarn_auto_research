import unittest

from swarn_research_mcp import server


class FakeFastMCP:
    def __init__(self, name):
        self.name = name
        self.tools = []

    def tool(self, **kwargs):
        def register(func):
            self.tools.append((func, kwargs))
            return func

        return register


class ServerToolRegistrationTest(unittest.TestCase):
    def test_build_server_registers_only_current_public_tools(self):
        fake_server = server.build_server(server_factory=FakeFastMCP)

        self.assertEqual(fake_server.name, "swarn-auto-research")
        self.assertEqual(
            [tool_func.__name__ for tool_func, _kwargs in fake_server.tools],
            [
                "bulk_normal_start_search",
                "get_paper_markdown",
                "get_paper_section",
                "get_alphaxiv_overview",
                "get_paper_metadata",
            ],
        )
        self.assertTrue(
            all(kwargs.get("description") for _tool_func, kwargs in fake_server.tools)
        )


def test_alphaxiv_overview_tool_registered():
    from swarn_research_mcp.server import MCP_TOOL_SPECS
    names = [spec.function.__name__ for spec in MCP_TOOL_SPECS]
    assert "get_alphaxiv_overview" in names


def test_alphaxiv_overview_returns_arxiv_id_and_markdown(monkeypatch):
    import asyncio
    from swarn_research_mcp.tools import paper_search

    async def fake_overview(arxiv_id: str) -> str:
        assert arxiv_id == "2304.08485"
        return "# LLaVA overview\n\nVisual instruction tuning."

    monkeypatch.setattr(
        paper_search,
        "get_alphaxiv_overview_markdown",
        fake_overview,
    )

    result = asyncio.run(paper_search.get_alphaxiv_overview("2304.08485"))
    assert result == {
        "arxiv_id": "2304.08485",
        "markdown": "# LLaVA overview\n\nVisual instruction tuning.",
    }


def test_paper_metadata_tool_registered():
    from swarn_research_mcp.server import MCP_TOOL_SPECS
    names = [spec.function.__name__ for spec in MCP_TOOL_SPECS]
    assert "get_paper_metadata" in names


def test_paper_metadata_returns_flat_dict(monkeypatch):
    import asyncio
    from swarn_research_mcp.tools import paper_search

    async def fake_paper_batch(paper_ids):
        assert paper_ids == ["2304.08485"]
        return [{
            "arxiv_id": "2304.08485",
            "scholar_semantic_id": "abc123",
            "abstract": "We present LLaVA...",
            "citations": ["2103.00020"],
            "citationCount": 1234,
            "references": [],
            "referenceCount": 0,
        }]

    monkeypatch.setattr(paper_search, "paper_batch", fake_paper_batch)

    result = asyncio.run(paper_search.get_paper_metadata("2304.08485"))
    assert result["arxiv_id"] == "2304.08485"
    assert result["scholar_semantic_id"] == "abc123"
    assert result["citationCount"] == 1234
    assert result["abstract"].startswith("We present")


def test_paper_metadata_returns_empty_when_not_found(monkeypatch):
    import asyncio
    from swarn_research_mcp.tools import paper_search

    async def fake_paper_batch(paper_ids):
        return []

    monkeypatch.setattr(paper_search, "paper_batch", fake_paper_batch)

    result = asyncio.run(paper_search.get_paper_metadata("9999.99999"))
    assert result == {"arxiv_id": "9999.99999", "found": False}


if __name__ == "__main__":
    unittest.main()
