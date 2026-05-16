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
                "gap_paper_search",
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

    async def fake_batch(arxiv_ids):
        assert arxiv_ids == ["2304.08485"]
        return [{
            "arxiv_id": "2304.08485",
            "scholar_semantic_id": "abc123",
            "title": "LLaVA",
            "year": 2023,
            "abstract": "We present LLaVA...",
            "citationCount": 1234,
            "referenceCount": 42,
        }]

    monkeypatch.setattr(paper_search, "paper_metadata_simple_batch", fake_batch)

    result = asyncio.run(paper_search.get_paper_metadata("2304.08485"))
    row = result["results"][0]
    assert row["arxiv_id"] == "2304.08485"
    assert row["scholar_semantic_id"] == "abc123"
    assert row["citationCount"] == 1234


def test_paper_metadata_returns_empty_when_not_found(monkeypatch):
    import asyncio
    from swarn_research_mcp.tools import paper_search

    async def fake_batch(arxiv_ids):
        return [{"arxiv_id": arxiv_ids[0], "found": False}]

    monkeypatch.setattr(paper_search, "paper_metadata_simple_batch", fake_batch)

    result = asyncio.run(paper_search.get_paper_metadata("9999.99999"))
    assert result == {"results": [{"arxiv_id": "9999.99999", "found": False}]}


def test_paper_metadata_returns_structured_error_on_failure(monkeypatch):
    import asyncio
    from swarn_research_mcp.tools import paper_search

    async def failing(arxiv_ids):
        raise RuntimeError("400 Bad Request")

    monkeypatch.setattr(paper_search, "paper_metadata_simple_batch", failing)

    result = asyncio.run(paper_search.get_paper_metadata(["2304.08485", "2103.00020"]))
    assert [r["arxiv_id"] for r in result["results"]] == ["2304.08485", "2103.00020"]
    assert all(r["found"] is False for r in result["results"])
    assert all(r["error"].startswith("RuntimeError: 400") for r in result["results"])


def test_paper_metadata_accepts_list_input(monkeypatch):
    import asyncio
    from swarn_research_mcp.tools import paper_search

    async def fake_batch(arxiv_ids):
        assert arxiv_ids == ["2304.08485", "2103.00020", "9999.99999"]
        return [
            {"arxiv_id": "2304.08485", "title": "LLaVA"},
            {"arxiv_id": "2103.00020", "title": "CLIP"},
            {"arxiv_id": "9999.99999", "found": False},
        ]

    monkeypatch.setattr(paper_search, "paper_metadata_simple_batch", fake_batch)

    result = asyncio.run(paper_search.get_paper_metadata(
        ["2304.08485", "2103.00020", "9999.99999"]
    ))
    assert len(result["results"]) == 3
    assert result["results"][0]["title"] == "LLaVA"
    assert result["results"][1]["title"] == "CLIP"
    assert result["results"][2]["found"] is False


def test_paper_metadata_batch_halves_on_429():
    from swarn_research_mcp.services import semantic_scholar as ss

    calls = []

    class Fake429(Exception):
        pass

    def fake_post(arxiv_ids):
        calls.append(list(arxiv_ids))
        if len(arxiv_ids) > 2:
            raise Fake429()
        return [
            {"externalIds": {"ArXiv": arxiv_id}, "paperId": f"sid-{arxiv_id}",
             "title": f"T-{arxiv_id}", "year": 2024, "abstract": "",
             "citationCount": 0, "referenceCount": 0}
            for arxiv_id in arxiv_ids
        ]

    original_post = ss._paper_metadata_simple_post
    original_is_429 = ss._is_rate_limit_error
    ss._paper_metadata_simple_post = fake_post
    ss._is_rate_limit_error = lambda exc: isinstance(exc, Fake429)
    try:
        ids = ["a", "b", "c", "d", "e"]
        result = ss._paper_metadata_simple_batch_sync(ids)
    finally:
        ss._paper_metadata_simple_post = original_post
        ss._is_rate_limit_error = original_is_429

    assert [r["arxiv_id"] for r in result] == ids
    assert calls[0] == ids
    assert any(len(c) <= 2 for c in calls[1:])


def test_paper_metadata_batch_records_error_when_single_id_429s():
    from swarn_research_mcp.services import semantic_scholar as ss

    class Fake429(Exception):
        pass

    def always_429(arxiv_ids):
        raise Fake429()

    original_post = ss._paper_metadata_simple_post
    original_is_429 = ss._is_rate_limit_error
    ss._paper_metadata_simple_post = always_429
    ss._is_rate_limit_error = lambda exc: isinstance(exc, Fake429)
    try:
        result = ss._paper_metadata_simple_batch_sync(["a", "b"])
    finally:
        ss._paper_metadata_simple_post = original_post
        ss._is_rate_limit_error = original_is_429

    assert [r["arxiv_id"] for r in result] == ["a", "b"]
    assert all(r["found"] is False for r in result)
    assert all("Fake429" in r["error"] for r in result)


def test_paper_abstract_batch_halves_on_429():
    from swarn_research_mcp.services import semantic_scholar as ss

    calls = []

    class Fake429(Exception):
        pass

    def fake_post(url, payload, params=None, headers=None):
        ids = list(payload["ids"])
        calls.append(ids)
        if len(ids) > 2:
            raise Fake429()
        return [
            {
                "paperId": f"sid-{paper_id}",
                "externalIds": {"ArXiv": paper_id.removeprefix("ArXiv:")},
                "abstract": f"abstract-{paper_id}",
            }
            for paper_id in ids
        ]

    original_post = ss._semantic_scholar_post
    original_is_429 = ss._is_rate_limit_error
    ss._semantic_scholar_post = fake_post
    ss._is_rate_limit_error = lambda exc: isinstance(exc, Fake429)
    try:
        result = ss._fetch_paper_abstracts_batch_by_arxiv_ids(["a", "b", "c", "d", "e"])
    finally:
        ss._semantic_scholar_post = original_post
        ss._is_rate_limit_error = original_is_429

    assert [paper["externalIds"]["ArXiv"] for paper in result] == ["a", "b", "c", "d", "e"]
    assert calls[0] == ["ArXiv:a", "ArXiv:b", "ArXiv:c", "ArXiv:d", "ArXiv:e"]
    assert any(len(call) <= 2 for call in calls[1:])


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


def test_paper_markdown_writes_file_when_output_dir_set(monkeypatch, tmp_path):
    import asyncio
    from swarn_research_mcp.tools import paper_search

    async def fake_md(arxiv_id, remove_toc):
        return "# Hello\n\nBody."

    monkeypatch.setattr(paper_search, "get_arxiv_markdown", fake_md)

    result = asyncio.run(paper_search.get_paper_markdown(
        "2304.08485", output_dir=str(tmp_path)
    ))
    assert "markdown" not in result
    assert result["arxiv_id"] == "2304.08485"
    output_path = tmp_path / "2304.08485.md"
    assert result["output_path"] == str(output_path)
    assert output_path.read_text() == "# Hello\n\nBody."


def test_paper_markdown_does_not_write_on_error(monkeypatch, tmp_path):
    import asyncio
    from swarn_research_mcp.tools import paper_search

    async def failing(arxiv_id, remove_toc):
        raise RuntimeError("404 Not Found")

    monkeypatch.setattr(paper_search, "get_arxiv_markdown", failing)

    result = asyncio.run(paper_search.get_paper_markdown(
        "9999.99999", output_dir=str(tmp_path)
    ))
    assert "output_path" not in result
    assert result["error"].startswith("RuntimeError: 404")
    assert list(tmp_path.iterdir()) == []


def test_paper_section_writes_slugged_file(monkeypatch, tmp_path):
    import asyncio
    from swarn_research_mcp.tools import paper_search

    async def fake_md(arxiv_id, remove_toc):
        return "## 1 Introduction\n\nIntro body.\n\n## 2 Method\n\nMethod body."

    monkeypatch.setattr(paper_search, "get_arxiv_markdown", fake_md)

    result = asyncio.run(paper_search.get_paper_section(
        "2304.08485", "Introduction", output_dir=str(tmp_path)
    ))
    assert "section" not in result
    output_path = tmp_path / "2304.08485__introduction.md"
    assert result["output_path"] == str(output_path)
    assert "Intro body." in output_path.read_text()


def test_paper_metadata_writes_per_id_files(monkeypatch, tmp_path):
    import asyncio
    import json
    from swarn_research_mcp.tools import paper_search

    async def fake_batch(arxiv_ids):
        return [
            {"arxiv_id": "2304.08485", "title": "LLaVA"},
            {"arxiv_id": "9999.99999", "found": False},
        ]

    monkeypatch.setattr(paper_search, "paper_metadata_simple_batch", fake_batch)

    result = asyncio.run(paper_search.get_paper_metadata(
        ["2304.08485", "9999.99999"], output_dir=str(tmp_path)
    ))
    paths = [r["output_path"] for r in result["results"]]
    assert paths == [
        str(tmp_path / "2304.08485.json"),
        str(tmp_path / "9999.99999.json"),
    ]
    assert json.loads((tmp_path / "2304.08485.json").read_text())["title"] == "LLaVA"
    assert json.loads((tmp_path / "9999.99999.json").read_text())["found"] is False


def test_paper_metadata_error_row_not_written(monkeypatch, tmp_path):
    import asyncio
    from swarn_research_mcp.tools import paper_search

    async def failing(arxiv_ids):
        raise RuntimeError("400 Bad Request")

    monkeypatch.setattr(paper_search, "paper_metadata_simple_batch", failing)

    result = asyncio.run(paper_search.get_paper_metadata(
        ["2304.08485"], output_dir=str(tmp_path)
    ))
    assert "output_path" not in result["results"][0]
    assert result["results"][0]["error"].startswith("RuntimeError: 400")
    assert list(tmp_path.iterdir()) == []


def test_alphaxiv_overview_writes_file(monkeypatch, tmp_path):
    import asyncio
    import json
    from swarn_research_mcp.tools import paper_search

    async def fake_overview(arxiv_id):
        return "# Overview\n\nBody."

    monkeypatch.setattr(
        paper_search, "get_alphaxiv_overview_markdown", fake_overview
    )

    result = asyncio.run(paper_search.get_alphaxiv_overview(
        "2304.08485", output_dir=str(tmp_path)
    ))
    assert "markdown" not in result
    output_path = tmp_path / "2304.08485.json"
    assert result["output_path"] == str(output_path)
    saved = json.loads(output_path.read_text())
    assert saved["markdown"] == "# Overview\n\nBody."


def test_coerce_string_list_handles_list():
    from swarn_research_mcp.tools.paper_search import _coerce_string_list
    assert _coerce_string_list(["a", "b"], field_name="x") == ["a", "b"]


def test_coerce_string_list_splits_newlines():
    from swarn_research_mcp.tools.paper_search import _coerce_string_list
    raw = "alpha\nbeta\ngamma"
    assert _coerce_string_list(raw, field_name="x") == ["alpha", "beta", "gamma"]


def test_coerce_string_list_drops_blank_lines():
    """The original Hugging Face 400 came from blank queries
    becoming q=' '. This guards against that regression."""
    from swarn_research_mcp.tools.paper_search import _coerce_string_list
    raw = "\nalpha\n\n  \nbeta\n"
    assert _coerce_string_list(raw, field_name="x") == ["alpha", "beta"]


def test_coerce_string_list_falls_back_to_comma_split():
    from swarn_research_mcp.tools.paper_search import _coerce_string_list
    raw = "long-context, attention, sparse attention"
    assert _coerce_string_list(raw, field_name="x") == [
        "long-context", "attention", "sparse attention"
    ]


def test_coerce_string_list_rejects_unknown_type():
    import pytest
    from swarn_research_mcp.tools.paper_search import _coerce_string_list
    with pytest.raises(TypeError):
        _coerce_string_list(123, field_name="x")


def test_bulk_normal_start_search_rejects_empty_queries():
    """Empty queries used to silently send q=' ' to Hugging Face."""
    import asyncio
    import pytest
    from swarn_research_mcp.tools import paper_search

    with pytest.raises(ValueError):
        asyncio.run(paper_search.bulk_normal_start_search(
            queries="",
            survey_queries=["s"],
            positive_keywords=["k"],
            negative_keywords=[],
        ))


if __name__ == "__main__":
    unittest.main()
