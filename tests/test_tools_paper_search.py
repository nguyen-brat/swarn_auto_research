import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from swarn_research_mcp.tools import paper_search


class PaperSearchToolTest(unittest.IsolatedAsyncioTestCase):
    @patch("swarn_research_mcp.tools.paper_search.datetime.datetime")
    @patch("swarn_research_mcp.tools.paper_search.validate_related_papers_with_codex", new_callable=AsyncMock)
    @patch("swarn_research_mcp.tools.paper_search.select_papers")
    @patch("swarn_research_mcp.tools.paper_search.collect_huggingface_trending_papers", new_callable=AsyncMock)
    @patch("swarn_research_mcp.tools.paper_search.recommendations_multi", new_callable=AsyncMock)
    @patch("swarn_research_mcp.tools.paper_search.search_huggingface_papers", new_callable=AsyncMock)
    @patch("swarn_research_mcp.tools.paper_search.paper_relevance_search", new_callable=AsyncMock)
    async def test_bulk_normal_start_search_uses_year_specific_influence_settings(
        self,
        mock_paper_relevance_search,
        mock_search_huggingface_papers,
        mock_recommendations_multi,
        mock_collect_huggingface_trending_papers,
        mock_select_papers,
        mock_validate_related_papers_with_codex,
        mock_datetime,
    ):
        mock_datetime.now.return_value.year = 2026
        mock_datetime.now.return_value.month = 5
        mock_search_huggingface_papers.return_value = {}
        mock_collect_huggingface_trending_papers.return_value = {}
        mock_recommendations_multi.return_value = ([], {})
        mock_validate_related_papers_with_codex.return_value = ["old", "middle", "recent"]
        mock_select_papers.return_value = {"papers": {}}
        mock_paper_relevance_search.side_effect = [
            {"old": "old abstract"},
            {"middle": "middle abstract"},
            {"recent": "recent abstract"},
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            await paper_search.bulk_normal_start_search(
                ["transformer"],
                [],
                positive_keywords=["transformer"],
                negative_keywords=["robotics"],
                output_dir=Path(temp_dir),
            )

        calls = mock_paper_relevance_search.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertEqual(
            [call.kwargs["start_year"] for call in calls],
            ["2022", "2024", "2025"],
        )
        self.assertEqual(
            [call.kwargs.get("end_year") for call in calls],
            ["2024", "2025", None],
        )
        self.assertEqual(
            [call.kwargs["depth"] for call in calls],
            [1, 1, 2],
        )
        self.assertEqual(
            [call.kwargs["citation_limit_per_level"] for call in calls],
            [15, 20, 15],
        )
        self.assertEqual(
            [call.kwargs["min_citation_depth"] for call in calls],
            [30, 20, 10],
        )

    @patch("swarn_research_mcp.tools.paper_search.datetime.datetime")
    @patch("swarn_research_mcp.tools.paper_search.validate_related_papers_with_codex", new_callable=AsyncMock)
    @patch("swarn_research_mcp.tools.paper_search.select_papers")
    @patch("swarn_research_mcp.tools.paper_search.collect_huggingface_trending_papers", new_callable=AsyncMock)
    @patch("swarn_research_mcp.tools.paper_search.recommendations_multi", new_callable=AsyncMock)
    @patch("swarn_research_mcp.tools.paper_search.search_huggingface_papers", new_callable=AsyncMock)
    @patch("swarn_research_mcp.tools.paper_search.paper_relevance_search", new_callable=AsyncMock)
    async def test_bulk_normal_start_search_collects_last_12_months_and_filters_final_result(
        self,
        mock_paper_relevance_search,
        mock_search_huggingface_papers,
        mock_recommendations_multi,
        mock_collect_huggingface_trending_papers,
        mock_select_papers,
        mock_validate_related_papers_with_codex,
        mock_datetime,
    ):
        mock_datetime.now.return_value.year = 2026
        mock_datetime.now.return_value.month = 5
        mock_paper_relevance_search.return_value = {}
        mock_search_huggingface_papers.return_value = {"search-paper": "Transformer search abstract"}
        mock_recommendations_multi.return_value = ([], {})
        mock_collect_huggingface_trending_papers.side_effect = [
            {f"trend-{index}": f"Transformer trending abstract {index}"}
            for index in range(12)
        ]
        mock_validate_related_papers_with_codex.return_value = ["search-paper"]
        keyword_filtered_papers = {
            "search-paper": "Transformer search abstract",
            "trend-0": "Transformer trending abstract 0",
        }
        mock_select_papers.return_value = {
            "total_input": 13,
            "total_kept": 2,
            "papers": keyword_filtered_papers,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await paper_search.bulk_normal_start_search(
                ["transformer"],
                [],
                positive_keywords=["transformer"],
                negative_keywords=["robotics"],
                output_dir=Path(temp_dir),
            )

        self.assertEqual(mock_collect_huggingface_trending_papers.await_count, 12)
        self.assertEqual(
            [
                call.kwargs["month"]
                for call in mock_collect_huggingface_trending_papers.await_args_list
            ],
            [
                "2025-06",
                "2025-07",
                "2025-08",
                "2025-09",
                "2025-10",
                "2025-11",
                "2025-12",
                "2026-01",
                "2026-02",
                "2026-03",
                "2026-04",
                "2026-05",
            ],
        )
        self.assertTrue(
            all(
                call.kwargs["limit"] == 30
                for call in mock_collect_huggingface_trending_papers.await_args_list
            )
        )
        mock_validate_related_papers_with_codex.assert_awaited_once()
        self.assertEqual(
            mock_validate_related_papers_with_codex.await_args.kwargs["query_topic"],
            "transformer",
        )
        self.assertIn(
            "search-paper",
            mock_validate_related_papers_with_codex.await_args.kwargs["papers"],
        )
        self.assertIn(
            "trend-0",
            mock_validate_related_papers_with_codex.await_args.kwargs["papers"],
        )
        mock_select_papers.assert_called_once()
        self.assertEqual(mock_select_papers.call_args.kwargs["keywords"], ["transformer"])
        self.assertEqual(mock_select_papers.call_args.kwargs["negative_keywords"], ["robotics"])
        self.assertIn("search-paper", mock_select_papers.call_args.kwargs["papers"])
        self.assertIn("trend-0", mock_select_papers.call_args.kwargs["papers"])
        self.assertEqual(
            mock_validate_related_papers_with_codex.await_args.kwargs["papers"],
            keyword_filtered_papers,
        )
        self.assertEqual(
            result["papers"],
            {"search-paper": "Transformer search abstract"},
        )
        self.assertEqual(result["total_kept"], 1)

    @patch("swarn_research_mcp.tools.paper_search.build_config")
    @patch("swarn_research_mcp.tools.paper_search.AsyncCodex")
    async def test_validate_related_papers_with_codex_chunks_and_parses_ids(self, mock_async_codex, mock_build_config):
        mock_build_config.return_value = "config"
        sessions = []

        class FakeThread:
            def __init__(self, final_response):
                self.final_response = final_response
                self.prompts = []

            async def run(self, prompt, **kwargs):
                self.prompts.append((prompt, kwargs))
                return type("Result", (), {"final_response": self.final_response})()

        class FakeCodexSession:
            def __init__(self, final_response):
                self.thread = FakeThread(final_response)
                sessions.append(self)

            async def __aenter__(self):
                return self

            async def __aexit__(self, _exc_type, _exc, _tb):
                return None

            async def thread_start(self, **kwargs):
                self.thread_start_kwargs = kwargs
                return self.thread

        mock_async_codex.side_effect = [
            FakeCodexSession("['2401.00000', '2401.00001']"),
            FakeCodexSession("['2401.00050']"),
        ]
        papers = {
            f"2401.{index:05d}": f"Transformer language model abstract {index}"
            for index in range(51)
        }

        result = await paper_search.validate_related_papers_with_codex(
            papers=papers,
            query_topic="transformer language models",
        )

        self.assertEqual(result, ["2401.00000", "2401.00001", "2401.00050"])
        self.assertEqual(mock_async_codex.call_count, 2)
        self.assertEqual(sessions[0].thread_start_kwargs["model"], "gpt-5.4-mini")
        self.assertEqual(sessions[1].thread_start_kwargs["model"], "gpt-5.4-mini")
        first_prompt = sessions[0].thread.prompts[0][0]
        second_prompt = sessions[1].thread.prompts[0][0]
        self.assertIn("transformer language models", first_prompt)
        self.assertIn("2401.00000", first_prompt)
        self.assertIn("2401.00049", first_prompt)
        self.assertNotIn("2401.00050", first_prompt)
        self.assertIn("2401.00050", second_prompt)
        self.assertIn("Return only a Python list string", first_prompt)

    async def test_parse_codex_related_ids_ignores_invalid_or_unknown_ids(self):
        result = paper_search._parse_codex_related_ids(
            "Here is the result: ['2401.00001', 'bad-id', '2401.00002']",
            allowed_ids={"2401.00001", "2401.00002"},
        )

        self.assertEqual(result, ["2401.00001", "2401.00002"])


if __name__ == "__main__":
    unittest.main()
