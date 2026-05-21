import os
import unittest
from unittest.mock import AsyncMock, patch

import requests

from swarn_research_mcp.services import semantic_scholar


class SemanticScholarServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        semantic_scholar.PAPER_DETAIL_CACHE.clear()
        self.original_s2_keys = semantic_scholar.SEMANTIC_SCHOLAR_API_KEYS
        self.original_s2_key_index = semantic_scholar._SEMANTIC_SCHOLAR_API_KEY_INDEX
        self.original_s2_headers = dict(semantic_scholar.HEADERS)
        semantic_scholar.SEMANTIC_SCHOLAR_API_KEYS = ["test-key"]
        semantic_scholar._SEMANTIC_SCHOLAR_API_KEY_INDEX = 0
        semantic_scholar.HEADERS.clear()
        semantic_scholar.HEADERS["x-api-key"] = "test-key"
        self.sleep_patch = patch("swarn_research_mcp.services.semantic_scholar.sleep")
        self.mock_sleep = self.sleep_patch.start()

    def tearDown(self):
        self.sleep_patch.stop()
        semantic_scholar.SEMANTIC_SCHOLAR_API_KEYS = self.original_s2_keys
        semantic_scholar._SEMANTIC_SCHOLAR_API_KEY_INDEX = self.original_s2_key_index
        semantic_scholar.HEADERS.clear()
        semantic_scholar.HEADERS.update(self.original_s2_headers)

    @patch.dict(os.environ, {"S2_KEY": "primary-key", "S2_KEYS": "fallback-1, fallback-2"})
    def test_parse_semantic_scholar_api_keys_keeps_order_and_dedupes(self):
        self.assertEqual(
            semantic_scholar._parse_semantic_scholar_api_keys(),
            ["fallback-1", "fallback-2", "primary-key"],
        )

    @patch("swarn_research_mcp.services.semantic_scholar.http_get")
    def test_semantic_scholar_get_rotates_key_after_rate_limit(self, mock_http_get):
        response = type("Response", (), {"status_code": 429, "headers": {}})()
        seen_headers = []

        def fake_http_get(*args, headers=None, **kwargs):
            seen_headers.append(dict(headers or {}))
            if len(seen_headers) == 1:
                raise requests.HTTPError("rate limited", response=response)
            return {"data": []}

        mock_http_get.side_effect = fake_http_get
        original_keys = semantic_scholar.SEMANTIC_SCHOLAR_API_KEYS
        original_index = semantic_scholar._SEMANTIC_SCHOLAR_API_KEY_INDEX
        original_headers = dict(semantic_scholar.HEADERS)
        try:
            semantic_scholar.SEMANTIC_SCHOLAR_API_KEYS = ["key-a", "key-b"]
            semantic_scholar._SEMANTIC_SCHOLAR_API_KEY_INDEX = 0
            semantic_scholar.HEADERS.clear()
            semantic_scholar.HEADERS["x-api-key"] = "key-a"

            result = semantic_scholar._semantic_scholar_get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={"query": "transformer"},
                headers=semantic_scholar.HEADERS,
            )
        finally:
            semantic_scholar.SEMANTIC_SCHOLAR_API_KEYS = original_keys
            semantic_scholar._SEMANTIC_SCHOLAR_API_KEY_INDEX = original_index
            semantic_scholar.HEADERS.clear()
            semantic_scholar.HEADERS.update(original_headers)

        self.assertEqual(result, {"data": []})
        self.assertEqual(seen_headers[0]["x-api-key"], "key-a")
        self.assertEqual(seen_headers[1]["x-api-key"], "key-b")

    def test_paper_model_serializes_to_json_shape(self):
        paper = semantic_scholar.SemanticScholarPaper(
            arxiv_id="1234.5678",
            scholar_semantic_id="main-paper",
            abstract="main abstract",
            citationCount=10,
            referenceCount=3,
            citations=["2345.6789"],
            references=["1111.2222"],
            citation_details=[
                semantic_scholar.SemanticScholarCitationPaper(
                    arxiv_id="2345.6789",
                    scholar_semantic_id="child-paper",
                    title="Child",
                    year=2025,
                    citationCount=2,
                    referenceCount=7,
                )
            ],
        )

        self.assertEqual(
            paper.to_dict(),
            {
                "arxiv_id": "1234.5678",
                "scholar_semantic_id": "main-paper",
                "abstract": "main abstract",
                "citations": ["2345.6789"],
                "citation_details": [
                    {
                        "arxiv_id": "2345.6789",
                        "scholar_semantic_id": "child-paper",
                        "title": "Child",
                        "year": 2025,
                        "abstract": None,
                        "citations": [],
                        "references": [],
                        "citationCount": 2,
                        "referenceCount": 7,
                        "citation_details": [],
                    }
                ],
                "citationCount": 10,
                "references": ["1111.2222"],
                "referenceCount": 3,
            },
        )

    @patch("swarn_research_mcp.services.semantic_scholar.http_post")
    def test_semantic_scholar_post_retries_after_rate_limit(self, mock_http_post):
        response = type("Response", (), {"status_code": 429})()
        mock_http_post.side_effect = [
            requests.HTTPError("rate limited", response=response),
            {"data": []},
        ]

        result = semantic_scholar._semantic_scholar_post(
            "https://api.semanticscholar.org/graph/v1/paper/batch",
            {"ids": ["paper-id"]},
            params={"fields": semantic_scholar.PAPER_WITH_LINKED_FIELDS},
            headers=semantic_scholar.HEADERS,
        )

        self.assertEqual(result, {"data": []})
        self.assertEqual(mock_http_post.call_count, 2)
        self.assertEqual(self.mock_sleep.call_count, 3)
        self.assertEqual(
            self.mock_sleep.call_args_list[1].args[0],
            semantic_scholar.SEMANTIC_SCHOLAR_RATE_LIMIT_BACKOFF_SECONDS,
        )

    @patch("swarn_research_mcp.services.semantic_scholar.http_post")
    def test_semantic_scholar_post_waits_extra_after_rate_limit(self, mock_http_post):
        response = type("Response", (), {"status_code": 429, "headers": {}})()
        mock_http_post.side_effect = [
            requests.HTTPError("rate limited", response=response),
            {"data": []},
        ]

        result = semantic_scholar._semantic_scholar_post(
            "https://api.semanticscholar.org/graph/v1/paper/batch",
            {"ids": ["paper-id"]},
            params={"fields": semantic_scholar.PAPER_WITH_LINKED_FIELDS},
            headers=semantic_scholar.HEADERS,
        )

        self.assertEqual(result, {"data": []})
        self.assertIn(
            semantic_scholar.SEMANTIC_SCHOLAR_RATE_LIMIT_BACKOFF_SECONDS,
            self.mock_sleep.call_args_list[1].args,
        )

    @patch("swarn_research_mcp.services.semantic_scholar.http_get")
    def test_semantic_scholar_get_retries_after_rate_limit(self, mock_http_get):
        response = type("Response", (), {"status_code": 429})()
        mock_http_get.side_effect = [
            requests.HTTPError("rate limited", response=response),
            {"data": []},
        ]

        result = semantic_scholar._semantic_scholar_get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={"query": "transformer"},
            headers=semantic_scholar.HEADERS,
        )

        self.assertEqual(result, {"data": []})
        self.assertEqual(mock_http_get.call_count, 2)
        self.assertEqual(self.mock_sleep.call_count, 3)
        self.assertEqual(
            self.mock_sleep.call_args_list[1].args[0],
            semantic_scholar.SEMANTIC_SCHOLAR_RATE_LIMIT_BACKOFF_SECONDS,
        )

    @patch("swarn_research_mcp.services.semantic_scholar.http_post")
    @patch("swarn_research_mcp.services.semantic_scholar.http_get")
    async def test_paper_relevance_search_uses_safe_search_fields_parameter(self, mock_http_get, mock_http_post):
        mock_http_get.return_value = {"data": []}

        await semantic_scholar.paper_relevance_search(
            query="transformer language models",
            limit=2,
            start_year=2024,
            end_year=2026,
        )

        params = mock_http_get.call_args.kwargs["params"]
        self.assertIn("abstract,", params["fields"])
        self.assertIn("citationCount", params["fields"])
        self.assertIn("referenceCount", params["fields"])
        self.assertNotIn("citations.abstract", params["fields"])
        self.assertNotIn("references.paperId", params["fields"])
        self.assertNotIn("abstractcitations", params["fields"])
        self.assertEqual(params["year"], "2024-2026")
        self.assertEqual(
            mock_http_get.call_args.kwargs["timeout"],
            semantic_scholar.SEMANTIC_SCHOLAR_TIMEOUT,
        )
        mock_http_post.assert_not_called()

    @patch("swarn_research_mcp.services.semantic_scholar.http_get")
    async def test_paper_relevance_search_caps_limit_at_api_max(self, mock_http_get):
        mock_http_get.return_value = {"data": []}

        await semantic_scholar.paper_relevance_search(
            query="retrieval augmented generation",
            limit=250,
        )

        self.assertEqual(mock_http_get.call_args.kwargs["params"]["limit"], 100)

    @patch("swarn_research_mcp.services.semantic_scholar.http_post")
    @patch("swarn_research_mcp.services.semantic_scholar.http_get")
    async def test_paper_relevance_search_returns_arxiv_abstract_mapping(self, mock_http_get, mock_http_post):
        mock_http_get.return_value = {
            "data": [
                {
                    "paperId": "main-paper",
                    "abstract": "main abstract",
                    "externalIds": {"ArXiv": "1234.5678"},
                    "citationCount": 10,
                    "referenceCount": 1,
                    "citations": [
                        {
                            "paperId": "child-paper",
                            "title": "Child Title",
                            "year": 2025,
                            "externalIds": {"ArXiv": "2345.6789"},
                            "abstract": "child abstract from search",
                            "citationCount": 2,
                            "referenceCount": 1,
                        }
                    ],
                    "references": [
                        {
                            "paperId": "root-reference-paper",
                            "externalIds": {"ArXiv": "9999.0001"},
                        }
                    ],
                }
            ]
        }
        mock_http_post.side_effect = [
            [
                {
                    "paperId": "child-paper",
                    "title": "Child Title",
                    "year": 2025,
                    "externalIds": {"ArXiv": "2345.6789"},
                    "abstract": "child abstract",
                    "citationCount": 2,
                    "referenceCount": 1,
                    "citations": [
                        {
                            "paperId": "grandchild-paper",
                            "title": "Grandchild Title",
                            "year": 2026,
                            "externalIds": {"ArXiv": "3456.7890"},
                            "abstract": "grandchild abstract",
                            "citationCount": 1,
                            "referenceCount": 0,
                        }
                    ],
                    "references": [
                        {
                            "paperId": "child-reference-paper",
                            "externalIds": {"ArXiv": "8888.0001"},
                        }
                    ],
                },
            ],
            {
                "data": [
                    {
                        "paperId": "root-reference-paper",
                        "externalIds": {"ArXiv": "9999.0001"},
                        "abstract": "root reference abstract",
                        "citations": [],
                        "references": [],
                    }
                ]
            },
        ]

        result = await semantic_scholar.paper_relevance_search(
            query="transformer language models",
            limit=1,
            start_year=2024,
            end_year=2026,
            depth=2,
        )

        self.assertEqual(
            result,
            {
                "1234.5678": "main abstract",
                "2345.6789": "child abstract",
                "3456.7890": "grandchild abstract",
                "9999.0001": "root reference abstract",
            },
        )
        self.assertNotIn("8888.0001", result)
        mock_http_post.assert_any_call(
            f"{semantic_scholar.GRAPH_BASE}/paper/batch",
            {"ids": ["child-paper"]},
            params={"fields": semantic_scholar.PAPER_WITH_LINKED_FIELDS},
            headers=semantic_scholar.HEADERS,
            timeout=semantic_scholar.SEMANTIC_SCHOLAR_TIMEOUT,
            direct_retries=1,
            proxy_retries=0,
        )
        mock_http_post.assert_any_call(
            f"{semantic_scholar.GRAPH_BASE}/paper/batch",
            {"ids": ["ArXiv:9999.0001"]},
            params={"fields": semantic_scholar.PAPER_ABSTRACT_FIELDS},
            headers=semantic_scholar.HEADERS,
            timeout=semantic_scholar.SEMANTIC_SCHOLAR_TIMEOUT,
        )

    @patch("swarn_research_mcp.services.semantic_scholar.http_post")
    @patch("swarn_research_mcp.services.semantic_scholar.http_get")
    async def test_paper_relevance_search_limits_results_by_impact_score(self, mock_http_get, mock_http_post):
        mock_http_get.return_value = {
            "data": [
                {
                    "paperId": "main-paper",
                    "year": 2024,
                    "abstract": "main abstract",
                    "externalIds": {"ArXiv": "1234.5678"},
                    "citationCount": 10,
                    "referenceCount": 0,
                    "citations": [
                        {
                            "paperId": "low-child-paper",
                            "title": "Low Child",
                            "year": 2024,
                            "externalIds": {"ArXiv": "1111.1111"},
                            "abstract": "low child abstract",
                            "citationCount": 1,
                            "referenceCount": 0,
                        },
                        {
                            "paperId": "high-child-paper",
                            "title": "High Child",
                            "year": 2026,
                            "externalIds": {"ArXiv": "2222.2222"},
                            "abstract": "high child abstract",
                            "citationCount": 100,
                            "referenceCount": 0,
                        },
                    ],
                    "references": [],
                }
            ]
        }

        result = await semantic_scholar.paper_relevance_search(
            query="transformer language models",
            limit=1,
            start_year=2024,
            end_year=2026,
            max_papers=2,
        )

        self.assertEqual(
            result,
            {
                "2222.2222": "high child abstract",
                "1234.5678": "main abstract",
            },
        )
        mock_http_post.assert_not_called()

    @patch("swarn_research_mcp.services.semantic_scholar.http_post")
    @patch("swarn_research_mcp.services.semantic_scholar.http_get")
    async def test_paper_relevance_search_sorts_all_results_by_descending_impact_score(self, mock_http_get, mock_http_post):
        current_year = semantic_scholar.datetime.datetime.now().year
        mock_http_get.return_value = {
            "data": [
                {
                    "paperId": "main-paper",
                    "year": current_year - 1,
                    "abstract": "main abstract",
                    "externalIds": {"ArXiv": "1234.5678"},
                    "citationCount": 10,
                    "referenceCount": 0,
                    "citations": [
                        {
                            "paperId": "low-child-paper",
                            "title": "Low Child",
                            "year": current_year - 1,
                            "externalIds": {"ArXiv": "1111.1111"},
                            "abstract": "low child abstract",
                            "citationCount": 1,
                            "referenceCount": 0,
                        },
                        {
                            "paperId": "high-child-paper",
                            "title": "High Child",
                            "year": current_year,
                            "externalIds": {"ArXiv": "2222.2222"},
                            "abstract": "high child abstract",
                            "citationCount": 100,
                            "referenceCount": 0,
                        },
                    ],
                    "references": [],
                }
            ]
        }

        result = await semantic_scholar.paper_relevance_search(
            query="transformer language models",
            limit=1,
            start_year=2024,
            end_year=2026,
        )

        self.assertEqual(
            list(result.keys()),
            ["2222.2222", "1234.5678", "1111.1111"],
        )
        mock_http_post.assert_not_called()

    @patch("swarn_research_mcp.services.semantic_scholar.http_post")
    @patch("swarn_research_mcp.services.semantic_scholar.http_get")
    async def test_paper_relevance_search_depth_three_expands_second_level_citations(self, mock_http_get, mock_http_post):
        mock_http_get.side_effect = [
            {
                "data": [
                    {
                        "paperId": "main-paper",
                        "abstract": "main abstract",
                        "externalIds": {"ArXiv": "1234.5678"},
                        "citations": [
                            {
                                "paperId": "child-paper",
                                "title": "Child Title",
                                "year": 2025,
                                "externalIds": {"ArXiv": "2345.6789"},
                                "citationCount": 2,
                                "referenceCount": 7,
                            }
                        ],
                        "references": [],
                        "citationCount": 10,
                        "referenceCount": 3,
                    }
                ]
            },
        ]
        mock_http_post.side_effect = [
            [
                {
                    "paperId": "child-paper",
                    "title": "Child Title",
                    "year": 2025,
                    "externalIds": {"ArXiv": "2345.6789"},
                    "abstract": "child abstract",
                    "citationCount": 8,
                    "referenceCount": 7,
                    "citations": [
                        {
                            "paperId": "grandchild-paper",
                            "title": "Grandchild Title",
                            "year": 2026,
                            "abstract": "grandchild abstract from child batch",
                            "externalIds": {"ArXiv": "3456.7890"},
                            "citationCount": 3,
                            "referenceCount": 4,
                        }
                    ],
                    "references": None,
                },
            ],
            [
                {
                    "paperId": "grandchild-paper",
                    "title": "Grandchild Title",
                    "year": 2026,
                    "externalIds": {"ArXiv": "3456.7890"},
                    "abstract": "grandchild abstract",
                    "citationCount": 3,
                    "referenceCount": 4,
                    "citations": [
                        {
                            "paperId": "great-grandchild-paper",
                            "title": "Great Grandchild Title",
                            "year": 2026,
                            "externalIds": {"ArXiv": "4567.8901"},
                            "citationCount": 1,
                            "referenceCount": 2,
                        }
                    ],
                    "references": [],
                },
            ],
        ]

        models = await semantic_scholar.paper_relevance_search_models(
            query="transformer language models",
            limit=1,
            start_year=2024,
            end_year=2026,
            depth=3,
        )
        result = [paper.to_dict() for paper in models]

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["citationCount"], 10)
        self.assertEqual(result[0]["referenceCount"], 3)
        self.assertEqual(result[0]["citation_details"][0]["scholar_semantic_id"], "child-paper")
        self.assertEqual(result[0]["citation_details"][0]["abstract"], "child abstract")
        self.assertEqual(result[0]["citation_details"][0]["citationCount"], 8)
        self.assertEqual(result[0]["citation_details"][0]["referenceCount"], 7)
        self.assertEqual(result[0]["citation_details"][0]["citations"], ["3456.7890"])
        self.assertEqual(result[0]["citation_details"][0]["references"], [])
        self.assertEqual(
            result[0]["citation_details"][0]["citation_details"][0]["scholar_semantic_id"],
            "grandchild-paper",
        )
        self.assertEqual(mock_http_get.call_count, 1)
        self.assertEqual(mock_http_post.call_count, 2)
        mock_http_post.assert_any_call(
            f"{semantic_scholar.GRAPH_BASE}/paper/batch",
            {"ids": ["child-paper"]},
            params={"fields": semantic_scholar.PAPER_WITH_LINKED_FIELDS},
            headers=semantic_scholar.HEADERS,
            timeout=semantic_scholar.SEMANTIC_SCHOLAR_TIMEOUT,
            direct_retries=1,
            proxy_retries=0,
        )
        mock_http_post.assert_any_call(
            f"{semantic_scholar.GRAPH_BASE}/paper/batch",
            {"ids": ["grandchild-paper"]},
            params={"fields": semantic_scholar.PAPER_WITH_LINKED_FIELDS},
            headers=semantic_scholar.HEADERS,
            timeout=semantic_scholar.SEMANTIC_SCHOLAR_TIMEOUT,
            direct_retries=1,
            proxy_retries=0,
        )
        self.assertEqual(result[0]["citation_details"][0]["citation_details"][0]["abstract"], "grandchild abstract")
        self.assertEqual(result[0]["citation_details"][0]["citation_details"][0]["citationCount"], 3)
        self.assertEqual(result[0]["citation_details"][0]["citation_details"][0]["referenceCount"], 4)
        self.assertEqual(
            result[0]["citation_details"][0]["citation_details"][0]["citation_details"][0]["scholar_semantic_id"],
            "great-grandchild-paper",
        )

    @patch("swarn_research_mcp.services.semantic_scholar.http_post")
    @patch("swarn_research_mcp.services.semantic_scholar.http_get")
    async def test_paper_relevance_search_models_excludes_roots_citations_and_references(self, mock_http_get, mock_http_post):
        mock_http_get.return_value = {
            "data": [
                {
                    "paperId": "excluded-main-paper",
                    "abstract": "excluded main abstract",
                    "externalIds": {"ArXiv": "1111.1111"},
                    "citationCount": 5,
                    "referenceCount": 1,
                    "citations": [],
                    "references": [],
                },
                {
                    "paperId": "main-paper",
                    "abstract": "main abstract",
                    "externalIds": {"ArXiv": "1234.5678"},
                    "citationCount": 10,
                    "referenceCount": 2,
                    "citations": [
                        {
                            "paperId": "excluded-child-paper",
                            "title": "Excluded Child",
                            "year": 2025,
                            "externalIds": {"ArXiv": "2222.2222"},
                            "abstract": "excluded child abstract",
                            "citationCount": 8,
                            "referenceCount": 1,
                        },
                        {
                            "paperId": "child-paper",
                            "title": "Child",
                            "year": 2025,
                            "externalIds": {"ArXiv": "2345.6789"},
                            "abstract": "child abstract",
                            "citationCount": 6,
                            "referenceCount": 1,
                        },
                    ],
                    "references": [
                        {"paperId": "kept-ref", "externalIds": {"ArXiv": "4444.4444"}},
                        {"paperId": "excluded-ref", "externalIds": {"ArXiv": "3333.3333"}},
                    ],
                },
            ]
        }
        mock_http_post.return_value = [
            {
                "paperId": "child-paper",
                "title": "Child",
                "year": 2025,
                "externalIds": {"ArXiv": "2345.6789"},
                "abstract": "child abstract",
                "citationCount": 6,
                "referenceCount": 1,
                "citations": [
                    {
                        "paperId": "excluded-grandchild-paper",
                        "title": "Excluded Grandchild",
                        "year": 2026,
                        "externalIds": {"ArXiv": "5555.5555"},
                        "abstract": "excluded grandchild abstract",
                        "citationCount": 3,
                        "referenceCount": 0,
                    },
                    {
                        "paperId": "grandchild-paper",
                        "title": "Grandchild",
                        "year": 2026,
                        "externalIds": {"ArXiv": "3456.7890"},
                        "abstract": "grandchild abstract",
                        "citationCount": 2,
                        "referenceCount": 0,
                    },
                ],
                "references": [
                    {"paperId": "excluded-child-ref", "externalIds": {"ArXiv": "6666.6666"}},
                    {"paperId": "kept-child-ref", "externalIds": {"ArXiv": "7777.7777"}},
                ],
            }
        ]

        models = await semantic_scholar.paper_relevance_search_models(
            query="transformer language models",
            limit=2,
            start_year=2024,
            end_year=2026,
            depth=2,
            exclude_paper_ids={
                "1111.1111",
                "2222.2222",
                "3333.3333",
                "5555.5555",
                "6666.6666",
            },
        )
        result = [paper.to_dict() for paper in models]

        self.assertEqual([paper["arxiv_id"] for paper in result], ["1234.5678"])
        self.assertEqual(result[0]["citations"], ["2345.6789"])
        self.assertEqual(result[0]["references"], ["4444.4444"])
        self.assertEqual(
            [paper["arxiv_id"] for paper in result[0]["citation_details"]],
            ["2345.6789"],
        )
        self.assertEqual(
            result[0]["citation_details"][0]["citations"],
            ["3456.7890"],
        )
        self.assertEqual(
            result[0]["citation_details"][0]["references"],
            ["7777.7777"],
        )
        self.assertEqual(
            [paper["arxiv_id"] for paper in result[0]["citation_details"][0]["citation_details"]],
            ["3456.7890"],
        )

    @patch("swarn_research_mcp.services.semantic_scholar.http_post")
    @patch("swarn_research_mcp.services.semantic_scholar.http_get")
    async def test_paper_relevance_search_depth_two_keeps_nested_citation_abstracts_from_parent_fields(self, mock_http_get, mock_http_post):
        mock_http_get.return_value = {
            "data": [
                {
                    "paperId": "main-paper",
                    "abstract": "main abstract",
                    "externalIds": {"ArXiv": "1234.5678"},
                    "citationCount": 10,
                    "referenceCount": 3,
                    "citations": [
                        {
                            "paperId": "child-paper",
                            "title": "Child Title",
                            "year": 2025,
                            "externalIds": {"ArXiv": "2345.6789"},
                            "citationCount": 2,
                            "referenceCount": 7,
                        }
                    ],
                    "references": [],
                }
            ]
        }
        mock_http_post.return_value = [
            {
                "paperId": "child-paper",
                "title": "Child Title",
                "year": 2025,
                "externalIds": {"ArXiv": "2345.6789"},
                "abstract": "child abstract",
                "citationCount": 2,
                "referenceCount": 7,
                "citations": [
                    {
                        "paperId": "grandchild-paper",
                        "title": "Grandchild Title",
                        "year": 2026,
                        "abstract": "grandchild abstract from child batch",
                        "externalIds": {"ArXiv": "3456.7890"},
                        "citationCount": 3,
                        "referenceCount": 4,
                    }
                ],
                "references": [],
            },
        ]

        models = await semantic_scholar.paper_relevance_search_models(
            query="transformer language models",
            limit=1,
            start_year=2024,
            end_year=2026,
            depth=2,
        )
        result = [paper.to_dict() for paper in models]

        self.assertEqual(
            result[0]["citation_details"][0]["citation_details"][0]["abstract"],
            "grandchild abstract from child batch",
        )

    @patch("swarn_research_mcp.services.semantic_scholar.http_post")
    @patch("swarn_research_mcp.services.semantic_scholar.http_get")
    async def test_paper_relevance_search_skips_deep_fetch_when_child_below_min_citation_depth(self, mock_http_get, mock_http_post):
        mock_http_get.return_value = {
            "data": [
                {
                    "paperId": "main-paper",
                    "abstract": "main abstract",
                    "externalIds": {"ArXiv": "1234.5678"},
                    "citationCount": 10,
                    "referenceCount": 3,
                    "citations": [
                        {
                            "paperId": "child-paper",
                            "title": "Child Title",
                            "year": 2025,
                            "externalIds": {"ArXiv": "2345.6789"},
                            "citationCount": 1,
                            "referenceCount": 7,
                        }
                    ],
                    "references": [],
                }
            ]
        }

        models = await semantic_scholar.paper_relevance_search_models(
            query="transformer language models",
            limit=1,
            start_year=2024,
            end_year=2026,
            depth=2,
            min_citation_depth=2,
        )
        result = [paper.to_dict() for paper in models]

        self.assertEqual(result[0]["citation_details"], [])
        mock_http_post.assert_not_called()

    @patch("swarn_research_mcp.services.semantic_scholar.http_post")
    @patch("swarn_research_mcp.services.semantic_scholar.http_get")
    async def test_paper_relevance_search_uses_min_citation_count_for_nested_filter_by_default(self, mock_http_get, mock_http_post):
        mock_http_get.return_value = {
            "data": [
                {
                    "paperId": "main-paper",
                    "abstract": "main abstract",
                    "externalIds": {"ArXiv": "1234.5678"},
                    "citationCount": 10,
                    "referenceCount": 3,
                    "citations": [
                        {
                            "paperId": "low-paper",
                            "title": "Low",
                            "year": 2025,
                            "externalIds": {"ArXiv": "1111.1111"},
                            "citationCount": 9,
                            "referenceCount": 7,
                        },
                        {
                            "paperId": "high-paper",
                            "title": "High",
                            "year": 2025,
                            "externalIds": {"ArXiv": "2222.2222"},
                            "citationCount": 10,
                            "referenceCount": 7,
                        },
                    ],
                    "references": [],
                }
            ]
        }
        mock_http_post.return_value = [
            {
                "paperId": "high-paper",
                "title": "High",
                "year": 2025,
                "externalIds": {"ArXiv": "2222.2222"},
                "citationCount": 10,
                "referenceCount": 7,
                "citations": [],
                "references": [],
            },
        ]

        models = await semantic_scholar.paper_relevance_search_models(
            query="transformer language models",
            limit=1,
            start_year=2024,
            end_year=2026,
            min_citation_count=10,
            depth=2,
        )
        result = [paper.to_dict() for paper in models]

        self.assertEqual(
            [paper["scholar_semantic_id"] for paper in result[0]["citation_details"]],
            ["high-paper"],
        )
        mock_http_post.assert_called_once_with(
            f"{semantic_scholar.GRAPH_BASE}/paper/batch",
            {"ids": ["high-paper"]},
            params={"fields": semantic_scholar.PAPER_WITH_LINKED_FIELDS},
            headers=semantic_scholar.HEADERS,
            timeout=semantic_scholar.SEMANTIC_SCHOLAR_TIMEOUT,
            direct_retries=1,
            proxy_retries=0,
        )

    @patch("swarn_research_mcp.services.semantic_scholar.http_get")
    async def test_paper_relevance_search_limits_citation_details_by_highest_citation_count(self, mock_http_get):
        mock_http_get.return_value = {
            "data": [
                {
                    "paperId": "main-paper",
                    "abstract": "main abstract",
                    "externalIds": {"ArXiv": "1234.5678"},
                    "citationCount": 10,
                    "referenceCount": 3,
                    "citations": [
                        {
                            "paperId": "low-paper",
                            "title": "Low",
                            "year": 2025,
                            "externalIds": {"ArXiv": "1111.1111"},
                            "citationCount": 1,
                            "referenceCount": 7,
                        },
                        {
                            "paperId": "high-paper",
                            "title": "High",
                            "year": 2025,
                            "externalIds": {"ArXiv": "2222.2222"},
                            "citationCount": 20,
                            "referenceCount": 7,
                        },
                        {
                            "paperId": "mid-paper",
                            "title": "Mid",
                            "year": 2025,
                            "externalIds": {"ArXiv": "3333.3333"},
                            "citationCount": 5,
                            "referenceCount": 7,
                        },
                    ],
                    "references": [],
                }
            ]
        }

        models = await semantic_scholar.paper_relevance_search_models(
            query="transformer language models",
            limit=1,
            start_year=2024,
            end_year=2026,
            citation_limit_per_level=2,
        )
        result = [paper.to_dict() for paper in models]

        self.assertEqual(
            [paper["scholar_semantic_id"] for paper in result[0]["citation_details"]],
            ["high-paper", "mid-paper"],
        )

    @patch("swarn_research_mcp.services.semantic_scholar.http_post")
    def test_fetch_papers_batch_by_ids_uses_small_linked_field_chunks(self, mock_http_post):
        paper_ids = ["paper-0", "paper-1", "paper-2"]
        mock_http_post.side_effect = [
            [{"paperId": paper_id} for paper_id in paper_ids[:2]],
            [{"paperId": paper_ids[2]}],
        ]

        with patch.object(semantic_scholar, "SEMANTIC_SCHOLAR_LINKED_BATCH_LIMIT", 2):
            result = semantic_scholar._fetch_papers_batch_by_ids(paper_ids)

        self.assertEqual([paper["paperId"] for paper in result], paper_ids)
        self.assertEqual(mock_http_post.call_count, 2)
        self.assertEqual(
            mock_http_post.call_args_list[0].kwargs["params"],
            {"fields": semantic_scholar.PAPER_WITH_LINKED_FIELDS},
        )
        self.assertEqual(
            mock_http_post.call_args_list[0].args[1],
            {"ids": paper_ids[:2]},
        )
        self.assertEqual(
            mock_http_post.call_args_list[1].args[1],
            {"ids": paper_ids[2:]},
        )

    @patch("swarn_research_mcp.services.semantic_scholar.http_post")
    def test_fetch_papers_batch_by_ids_caps_configured_chunk_size(self, mock_http_post):
        paper_ids = [f"paper-{index}" for index in range(501)]
        mock_http_post.side_effect = [
            [{"paperId": paper_id} for paper_id in paper_ids[:500]],
            [{"paperId": paper_ids[500]}],
        ]

        with patch.object(semantic_scholar, "SEMANTIC_SCHOLAR_LINKED_BATCH_LIMIT", 999):
            semantic_scholar._fetch_papers_batch_by_ids(paper_ids)

        self.assertEqual(mock_http_post.call_count, 2)
        self.assertEqual(len(mock_http_post.call_args_list[0].args[1]["ids"]), 500)
        self.assertEqual(len(mock_http_post.call_args_list[1].args[1]["ids"]), 1)

    @patch("swarn_research_mcp.services.semantic_scholar.http_post")
    def test_paper_metadata_simple_batch_chunks_at_api_max(self, mock_http_post):
        arxiv_ids = [f"2501.{index:05d}" for index in range(501)]
        mock_http_post.side_effect = [
            [
                {
                    "paperId": f"paper-{index}",
                    "externalIds": {"ArXiv": arxiv_id},
                    "title": f"Paper {index}",
                }
                for index, arxiv_id in enumerate(arxiv_ids[:500])
            ],
            [
                {
                    "paperId": "paper-500",
                    "externalIds": {"ArXiv": arxiv_ids[500]},
                    "title": "Paper 500",
                }
            ],
        ]

        result = semantic_scholar._paper_metadata_simple_batch_sync(arxiv_ids)

        self.assertEqual(len(result), 501)
        self.assertEqual(mock_http_post.call_count, 2)
        self.assertEqual(len(mock_http_post.call_args_list[0].args[1]["ids"]), 500)
        self.assertEqual(len(mock_http_post.call_args_list[1].args[1]["ids"]), 1)

    @patch("swarn_research_mcp.services.semantic_scholar.http_post")
    def test_fetch_papers_batch_by_ids_splits_bad_request_chunks(self, mock_http_post):
        response = type("Response", (), {"status_code": 400})()
        mock_http_post.side_effect = [
            requests.HTTPError("bad request", response=response),
            [{"paperId": "paper-1"}],
            [{"paperId": "paper-2"}],
        ]

        result = semantic_scholar._fetch_papers_batch_by_ids(["paper-1", "paper-2"])

        self.assertEqual(result, [{"paperId": "paper-1"}, {"paperId": "paper-2"}])
        self.assertEqual(mock_http_post.call_count, 3)
        self.assertEqual(mock_http_post.call_args_list[0].args[1], {"ids": ["paper-1", "paper-2"]})
        self.assertEqual(mock_http_post.call_args_list[1].args[1], {"ids": ["paper-1"]})
        self.assertEqual(mock_http_post.call_args_list[2].args[1], {"ids": ["paper-2"]})

    @patch("swarn_research_mcp.services.semantic_scholar.http_post")
    def test_fetch_papers_batch_by_ids_reuses_cached_paper_details(self, mock_http_post):
        semantic_scholar.PAPER_DETAIL_CACHE.clear()
        mock_http_post.side_effect = [
            [
                {
                    "paperId": "paper-1",
                    "externalIds": {"ArXiv": "1234.5678"},
                    "abstract": "paper abstract",
                    "citations": [],
                    "references": [],
                }
            ],
            [
                {
                    "paperId": "paper-2",
                    "externalIds": {"ArXiv": "2345.6789"},
                    "abstract": "second abstract",
                    "citations": [],
                    "references": [],
                }
            ],
        ]

        first_result = semantic_scholar._fetch_papers_batch_by_ids(["paper-1"])
        second_result = semantic_scholar._fetch_papers_batch_by_ids(["paper-1", "paper-2"])

        self.assertEqual(first_result[0]["paperId"], "paper-1")
        self.assertEqual([paper["paperId"] for paper in second_result], ["paper-1", "paper-2"])
        self.assertEqual(mock_http_post.call_count, 2)
        self.assertEqual(mock_http_post.call_args_list[0].args[1], {"ids": ["paper-1"]})
        self.assertEqual(mock_http_post.call_args_list[1].args[1], {"ids": ["paper-2"]})

    def test_paper_detail_memory_cache_is_bounded(self):
        original_capacity = semantic_scholar.PAPER_DETAIL_CACHE.capacity
        semantic_scholar.PAPER_DETAIL_CACHE.capacity = 2
        try:
            semantic_scholar.PAPER_DETAIL_CACHE.clear()
            semantic_scholar.PAPER_DETAIL_CACHE["p1"] = {"paperId": "p1"}
            semantic_scholar.PAPER_DETAIL_CACHE["p2"] = {"paperId": "p2"}
            semantic_scholar.PAPER_DETAIL_CACHE["p3"] = {"paperId": "p3"}

            self.assertIsNone(semantic_scholar.PAPER_DETAIL_CACHE.get("p1"))
            self.assertEqual(
                semantic_scholar.PAPER_DETAIL_CACHE.get("p2"),
                {"paperId": "p2"},
            )
            self.assertEqual(
                semantic_scholar.PAPER_DETAIL_CACHE.get("p3"),
                {"paperId": "p3"},
            )
        finally:
            semantic_scholar.PAPER_DETAIL_CACHE.capacity = original_capacity
            semantic_scholar.PAPER_DETAIL_CACHE.clear()

    def test_paper_detail_memory_cache_invalid_capacity_falls_back_to_default(self):
        cache = semantic_scholar._BoundedPaperDetailCache("bad")

        self.assertEqual(cache.capacity, 256)

    def test_paper_detail_memory_cache_capacity_counts_papers_not_aliases(self):
        original_capacity = semantic_scholar.PAPER_DETAIL_CACHE.capacity
        paper = {
            "paperId": "paper-1",
            "externalIds": {"ArXiv": "1234.5678"},
        }
        semantic_scholar.PAPER_DETAIL_CACHE.capacity = 1
        try:
            semantic_scholar.PAPER_DETAIL_CACHE.clear()
            with patch.object(semantic_scholar.persistent_cache, "put"):
                semantic_scholar._cache_paper_detail(paper)

            self.assertEqual(
                semantic_scholar.PAPER_DETAIL_CACHE.get("paper-1"),
                paper,
            )
            self.assertEqual(
                semantic_scholar.PAPER_DETAIL_CACHE.get("1234.5678"),
                paper,
            )
            self.assertEqual(
                semantic_scholar.PAPER_DETAIL_CACHE.get("ArXiv:1234.5678"),
                paper,
            )
            self.assertEqual(len(semantic_scholar.PAPER_DETAIL_CACHE), 1)
        finally:
            semantic_scholar.PAPER_DETAIL_CACHE.capacity = original_capacity
            semantic_scholar.PAPER_DETAIL_CACHE.clear()

    @patch("swarn_research_mcp.services.semantic_scholar.http_post")
    async def test_recommendations_multi_sends_seed_ids_directly(self, mock_http_post):
        mock_http_post.return_value = {
            "recommendedPapers": [
                {
                    "paperId": "recommended-s2-id",
                    "externalIds": {"ArXiv": "2604.00001"},
                    "abstract": "recommended abstract",
                    "citationCount": 12,
                    "referenceCount": 3,
                }
            ]
        }

        result = await semantic_scholar.recommendations_multi(
            postitive_ids=["649def34f8be52c8b66281af98ae884c09aef38b"],
            negative_ids=["https://arxiv.org/abs/2604.28178"],
            limit=10,
        )

        self.assertEqual(
            result,
            (
                [
                    {
                        "arxiv_id": "2604.00001",
                        "scholar_semantic_id": "recommended-s2-id",
                        "abstract": "recommended abstract",
                        "citations": [],
                        "citationCount": 12,
                        "references": [],
                        "referenceCount": 3,
                    }
                ],
                {
                    "2604.00001": "recommended abstract",
                },
            ),
        )
        mock_http_post.assert_called_once_with(
            f"{semantic_scholar.RECOMM_BASE}/papers",
            {
                "positivePaperIds": ["649def34f8be52c8b66281af98ae884c09aef38b"],
                "negativePaperIds": ["ArXiv:2604.28178"],
            },
            params={
                "fields": semantic_scholar.RECOMMENDATION_FIELDS,
                "limit": 10,
            },
            headers=semantic_scholar.HEADERS,
            timeout=semantic_scholar.SEMANTIC_SCHOLAR_TIMEOUT,
        )

    @patch("swarn_research_mcp.services.semantic_scholar.http_post")
    async def test_recommendations_multi_caps_limit_at_api_max(self, mock_http_post):
        mock_http_post.return_value = {"recommendedPapers": []}

        await semantic_scholar.recommendations_multi(
            postitive_ids=["649def34f8be52c8b66281af98ae884c09aef38b"],
            limit=800,
        )

        self.assertEqual(mock_http_post.call_args.kwargs["params"]["limit"], 500)

    @patch("swarn_research_mcp.services.semantic_scholar.paper_relevance_search", new_callable=AsyncMock)
    async def test_transformer_language_models_example_uses_expected_defaults(self, mock_search):
        mock_search.return_value = []

        result = await semantic_scholar.search_transformer_language_models_2024_2026(limit=2)

        self.assertEqual(result, [])
        mock_search.assert_called_once_with(
            query="transformer language models",
            limit=2,
            start_year=2024,
            end_year=2026,
            depth=1,
            citation_limit_per_level=100,
            min_citation_depth=None,
        )


if __name__ == "__main__":
    unittest.main()
