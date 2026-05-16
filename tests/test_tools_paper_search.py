import tempfile
import unittest
import importlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from swarn_research_mcp.tools import paper_search


class PaperSearchToolTest(unittest.IsolatedAsyncioTestCase):
    def test_codex_relevance_session_limit_uses_env(self):
        original = os.environ.get("SWARN_CODEX_RELEVANCE_SESSION_LIMIT")
        try:
            os.environ["SWARN_CODEX_RELEVANCE_SESSION_LIMIT"] = "3"
            importlib.reload(paper_search)
            self.assertEqual(paper_search.CODEX_RELEVANCE_SESSION_LIMIT, 3)
        finally:
            if original is None:
                os.environ.pop("SWARN_CODEX_RELEVANCE_SESSION_LIMIT", None)
            else:
                os.environ["SWARN_CODEX_RELEVANCE_SESSION_LIMIT"] = original
            importlib.reload(paper_search)

    def test_codex_relevance_session_limit_defaults_to_one_in_mcp_server(self):
        original = os.environ.get("SWARN_CODEX_RELEVANCE_SESSION_LIMIT")
        try:
            os.environ.pop("SWARN_CODEX_RELEVANCE_SESSION_LIMIT", None)
            with patch.object(sys, "argv", ["swarn-auto-research-mcp"]):
                importlib.reload(paper_search)
                self.assertEqual(paper_search.CODEX_RELEVANCE_SESSION_LIMIT, 1)
        finally:
            if original is None:
                os.environ.pop("SWARN_CODEX_RELEVANCE_SESSION_LIMIT", None)
            else:
                os.environ["SWARN_CODEX_RELEVANCE_SESSION_LIMIT"] = original
            importlib.reload(paper_search)

    @patch("swarn_research_mcp.tools.paper_search.build_config")
    @patch("swarn_research_mcp.tools.paper_search.AsyncCodex")
    async def test_codex_relevance_validation_uses_extended_sdk_timeout(
        self,
        mock_async_codex,
        mock_build_config,
    ):
        observed = {}

        class FakeThread:
            async def run(self, prompt, **kwargs):
                observed["prompt"] = prompt
                observed["kwargs"] = kwargs
                return SimpleNamespace(final_response="['2501.00001']")

        class FakeCodexContext:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def thread_start(self, model):
                observed["model"] = model
                return FakeThread()

        mock_build_config.return_value = object()
        mock_async_codex.return_value = FakeCodexContext()

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"SWARN_CODEX_RELEVANCE_CWD": temp_dir}):
                related_ids = await paper_search._validate_related_paper_chunk_with_codex(
                    "coding agents",
                    {"2501.00001": "coding agent abstract"},
                    paper_search.asyncio.Semaphore(1),
                )

        self.assertEqual(related_ids, ["2501.00001"])
        mock_build_config.assert_called_once_with(cwd=Path(temp_dir))
        self.assertEqual(observed["model"], "gpt-5.4-mini")
        self.assertEqual(
            observed["kwargs"]["notification_timeout_s"],
            paper_search.CODEX_RELEVANCE_TIMEOUT_SECONDS,
        )

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
        mock_validate_related_papers_with_codex.return_value = ["old", "middle", "fresh", "recent"]
        mock_select_papers.return_value = {"papers": {}}
        mock_paper_relevance_search.side_effect = [
            {"old": "old abstract"},
            {"middle": "middle abstract"},
            {"fresh": "fresh abstract"},
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
        self.assertEqual(len(calls), 4)
        self.assertEqual(
            [call.kwargs["start_year"] for call in calls],
            ["2022", "2024", "2025", "2025"],
        )
        self.assertEqual(
            [call.kwargs.get("end_year") for call in calls],
            ["2024", "2025", None, None],
        )
        self.assertEqual(
            [call.kwargs["min_citation_count"] for call in calls],
            [50, 30, 5, 10],
        )
        self.assertEqual(
            [call.kwargs["depth"] for call in calls],
            [1, 1, 1, 2],
        )
        self.assertEqual(
            [call.kwargs["citation_limit_per_level"] for call in calls],
            [15, 20, 10, 15],
        )
        self.assertEqual(
            [call.kwargs["min_citation_depth"] for call in calls],
            [30, 20, 5, 10],
        )
        self.assertEqual(
            [call.kwargs["max_papers"] for call in calls],
            [60, 60, 40, 80],
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
                call.kwargs["limit"] == 40
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

    @patch("swarn_research_mcp.tools.paper_search.datetime.datetime")
    @patch("swarn_research_mcp.tools.paper_search.validate_related_papers_with_codex", new_callable=AsyncMock)
    @patch("swarn_research_mcp.tools.paper_search.select_papers")
    @patch("swarn_research_mcp.tools.paper_search.collect_huggingface_trending_papers", new_callable=AsyncMock)
    @patch("swarn_research_mcp.tools.paper_search.recommendations_multi", new_callable=AsyncMock)
    @patch("swarn_research_mcp.tools.paper_search.search_huggingface_papers", new_callable=AsyncMock)
    @patch("swarn_research_mcp.tools.paper_search.paper_relevance_search", new_callable=AsyncMock)
    async def test_bulk_normal_start_search_continues_when_recommendations_rate_limit(
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
        mock_paper_relevance_search.return_value = {"search-paper": "coding agent abstract"}
        mock_search_huggingface_papers.return_value = {}
        mock_recommendations_multi.side_effect = RuntimeError("Semantic Scholar 429")
        mock_collect_huggingface_trending_papers.return_value = {}
        mock_validate_related_papers_with_codex.return_value = ["search-paper"]
        mock_select_papers.return_value = {
            "total_input": 1,
            "total_kept": 1,
            "papers": {"search-paper": "coding agent abstract"},
        }

        result = await paper_search.bulk_normal_start_search(
            ["coding agent"],
            [],
            positive_keywords=["agent"],
            negative_keywords=["robotics"],
        )

        mock_recommendations_multi.assert_awaited_once()
        mock_select_papers.assert_called_once()
        self.assertIn("search-paper", mock_select_papers.call_args.kwargs["papers"])
        self.assertEqual(result["papers"], {"search-paper": "coding agent abstract"})
        self.assertEqual(result["total_kept"], 1)

    @patch("swarn_research_mcp.tools.paper_search.validate_related_papers_with_codex", new_callable=AsyncMock)
    @patch("swarn_research_mcp.tools.paper_search.collect_huggingface_trending_papers", new_callable=AsyncMock)
    @patch("swarn_research_mcp.tools.paper_search.recommendations_multi", new_callable=AsyncMock)
    @patch("swarn_research_mcp.tools.paper_search.paper_relevance_search", new_callable=AsyncMock)
    @patch("swarn_research_mcp.tools.paper_search.search_alphaxiv_papers", new_callable=AsyncMock)
    @patch("swarn_research_mcp.tools.paper_search.search_huggingface_papers", new_callable=AsyncMock)
    async def test_gap_paper_search_combines_huggingface_and_alphaxiv_and_filters_results(
        self,
        mock_search_huggingface_papers,
        mock_search_alphaxiv_papers,
        mock_paper_relevance_search,
        mock_recommendations_multi,
        mock_collect_huggingface_trending_papers,
        mock_validate_related_papers_with_codex,
    ):
        mock_search_huggingface_papers.side_effect = [
            {
                "2501.00001": "Coding agent benchmark for repository tasks.",
                "2501.00002": "Robotics benchmark unrelated to software agents.",
            },
            {
                "2501.00001": "Duplicate should keep first abstract.",
                "2501.00003": "Agent orchestration survey for coding workflows.",
            },
        ]
        mock_search_alphaxiv_papers.side_effect = [
            [
                {
                    "universal_paper_id": "2107.03374",
                    "abstract": "HumanEval benchmark introduced for evaluating a coding agent.",
                    "paper_summary": {"summary": "HumanEval summary."},
                },
                {
                    "universal_paper_id": "2501.00002",
                    "abstract": "Robotics benchmark unrelated to software agents.",
                },
            ],
            [
                {
                    "universal_paper_id": "2501.00003",
                    "abstract": "AlphaXiv duplicate should not replace Hugging Face.",
                },
            ],
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await paper_search.gap_paper_search(
                ["coding agent benchmark", "agent orchestration"],
                positive_keywords=["agent"],
                negative_keywords=["robotics"],
                limit_per_query=7,
                output_dir=temp_dir,
            )
            output_path = Path(result["output_path"])
            output_exists = output_path.is_file()
            output_json = json.loads(output_path.read_text())

        self.assertEqual(mock_search_huggingface_papers.await_count, 2)
        self.assertEqual(mock_search_alphaxiv_papers.await_count, 2)
        self.assertEqual(
            [call.kwargs["query"] for call in mock_search_huggingface_papers.await_args_list],
            ["coding agent benchmark", "agent orchestration"],
        )
        self.assertEqual(
            [call.kwargs["query"] for call in mock_search_alphaxiv_papers.await_args_list],
            ["coding agent benchmark", "agent orchestration"],
        )
        self.assertTrue(
            all(
                call.kwargs["limit"] == 7
                for call in mock_search_huggingface_papers.await_args_list
            )
        )
        mock_paper_relevance_search.assert_not_awaited()
        mock_recommendations_multi.assert_not_awaited()
        mock_collect_huggingface_trending_papers.assert_not_awaited()
        mock_validate_related_papers_with_codex.assert_not_awaited()
        self.assertEqual(result["total_input"], 4)
        self.assertEqual(result["total_kept"], 3)
        self.assertEqual(
            result["papers"],
            {
                "2501.00001": "Coding agent benchmark for repository tasks.",
                "2501.00003": "Agent orchestration survey for coding workflows.",
                "2107.03374": "HumanEval benchmark introduced for evaluating a coding agent.",
            },
        )
        self.assertIn("output_path", result)
        self.assertTrue(output_exists)
        self.assertEqual(output_json, result["papers"])

    @patch("swarn_research_mcp.tools.paper_search.search_alphaxiv_papers", new_callable=AsyncMock)
    @patch("swarn_research_mcp.tools.paper_search.search_huggingface_papers", new_callable=AsyncMock)
    async def test_gap_paper_search_continues_when_one_lightweight_source_fails(
        self,
        mock_search_huggingface_papers,
        mock_search_alphaxiv_papers,
    ):
        mock_search_huggingface_papers.side_effect = ValueError("HF_TOKEN is not set")
        mock_search_alphaxiv_papers.return_value = [
            {
                "universal_paper_id": "2107.03374",
                "abstract": "HumanEval benchmark for a coding agent.",
            }
        ]

        result = await paper_search.gap_paper_search(
            ["HumanEval benchmark"],
            positive_keywords=["agent"],
        )

        self.assertEqual(result["papers"], {
            "2107.03374": "HumanEval benchmark for a coding agent.",
        })
        self.assertEqual(result["query_audit"][0]["huggingface_error"], "ValueError: HF_TOKEN is not set")
        self.assertEqual(result["query_audit"][0]["alphaxiv_candidate_count"], 1)

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
