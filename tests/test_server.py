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


def test_alphaxiv_overview_returns_structured_error_on_failure(monkeypatch):
    import asyncio
    from swarn_research_mcp.tools import paper_search

    async def failing_overview(arxiv_id: str) -> str:
        raise RuntimeError("404 Not Found")

    monkeypatch.setattr(
        paper_search,
        "get_alphaxiv_overview_markdown",
        failing_overview,
    )

    result = asyncio.run(paper_search.get_alphaxiv_overview("9999.99999"))
    assert result["arxiv_id"] == "9999.99999"
    assert result["markdown"] == ""
    assert result["error"].startswith("RuntimeError: 404")


def test_paper_metadata_tool_registered():
    from swarn_research_mcp.server import MCP_TOOL_SPECS
    names = [spec.function.__name__ for spec in MCP_TOOL_SPECS]
    assert "get_paper_metadata" in names


def test_paper_metadata_returns_flat_dict(monkeypatch):
    import asyncio
    from swarn_research_mcp.tools import paper_search

    async def fake_metadata(arxiv_id):
        assert arxiv_id == "2304.08485"
        return {
            "arxiv_id": "2304.08485",
            "scholar_semantic_id": "abc123",
            "title": "LLaVA",
            "year": 2023,
            "abstract": "We present LLaVA...",
            "citationCount": 1234,
            "referenceCount": 42,
        }

    monkeypatch.setattr(paper_search, "paper_metadata_simple", fake_metadata)

    result = asyncio.run(paper_search.get_paper_metadata("2304.08485"))
    assert result["arxiv_id"] == "2304.08485"
    assert result["scholar_semantic_id"] == "abc123"
    assert result["citationCount"] == 1234
    assert result["abstract"].startswith("We present")


def test_paper_metadata_returns_empty_when_not_found(monkeypatch):
    import asyncio
    from swarn_research_mcp.tools import paper_search

    async def fake_metadata(arxiv_id):
        return {}

    monkeypatch.setattr(paper_search, "paper_metadata_simple", fake_metadata)

    result = asyncio.run(paper_search.get_paper_metadata("9999.99999"))
    assert result == {"arxiv_id": "9999.99999", "found": False}


def test_paper_metadata_returns_structured_error_on_failure(monkeypatch):
    import asyncio
    from swarn_research_mcp.tools import paper_search

    async def failing(arxiv_id):
        raise RuntimeError("400 Bad Request")

    monkeypatch.setattr(paper_search, "paper_metadata_simple", failing)

    result = asyncio.run(paper_search.get_paper_metadata("2304.08485"))
    assert result["arxiv_id"] == "2304.08485"
    assert result["found"] is False
    assert result["error"].startswith("RuntimeError: 400")


def test_paper_markdown_returns_dict_with_markdown(monkeypatch):
    import asyncio
    from swarn_research_mcp.tools import paper_search

    async def fake_md(arxiv_id, remove_toc):
        assert arxiv_id == "2304.08485"
        assert remove_toc is False
        return "## 1 Introduction\n\nWe present LLaVA..."

    monkeypatch.setattr(paper_search, "get_arxiv_markdown", fake_md)

    result = asyncio.run(paper_search.get_paper_markdown("2304.08485"))
    assert result == {
        "arxiv_id": "2304.08485",
        "markdown": "## 1 Introduction\n\nWe present LLaVA...",
    }


def test_paper_markdown_returns_structured_error_on_failure(monkeypatch):
    import asyncio
    from swarn_research_mcp.tools import paper_search

    async def failing(arxiv_id, remove_toc):
        raise RuntimeError("404 Not Found")

    monkeypatch.setattr(paper_search, "get_arxiv_markdown", failing)

    result = asyncio.run(paper_search.get_paper_markdown("9999.99999"))
    assert result["arxiv_id"] == "9999.99999"
    assert result["markdown"] == ""
    assert result["error"].startswith("RuntimeError: 404")


def test_paper_section_returns_dict_with_section(monkeypatch):
    import asyncio
    from swarn_research_mcp.tools import paper_search

    async def fake_md(arxiv_id, remove_toc):
        return "## 1 Introduction\n\nIntro body.\n\n## 2 Method\n\nMethod body."

    monkeypatch.setattr(paper_search, "get_arxiv_markdown", fake_md)

    result = asyncio.run(paper_search.get_paper_section("2304.08485", "Introduction"))
    assert result["arxiv_id"] == "2304.08485"
    assert result["section_path"] == "Introduction"
    assert "Intro body." in result["section"]
    assert "Method body." not in result["section"]


def test_paper_section_returns_structured_error_when_section_missing(monkeypatch):
    import asyncio
    from swarn_research_mcp.tools import paper_search

    async def fake_md(arxiv_id, remove_toc):
        return "## Some heading\n\nContent."

    monkeypatch.setattr(paper_search, "get_arxiv_markdown", fake_md)

    result = asyncio.run(paper_search.get_paper_section("2304.08485", "Nope"))
    assert result["section"] == ""
    assert "section not found" in result["error"]


def test_extract_markdown_section_strips_numeric_prefixes():
    from swarn_research_mcp.services.arxiv import extract_markdown_section

    md = (
        "## 1 Introduction\n"
        "Intro body.\n\n"
        "## 2 Method\n"
        "Method body.\n\n"
        "## 3.1 Subsection\n"
        "Sub body.\n"
    )
    intro = extract_markdown_section(md, "Introduction")
    assert intro.startswith("## 1 Introduction")
    assert "Intro body." in intro
    assert "Method body." not in intro

    sub = extract_markdown_section(md, "Subsection")
    assert "Sub body." in sub


if __name__ == "__main__":
    unittest.main()
