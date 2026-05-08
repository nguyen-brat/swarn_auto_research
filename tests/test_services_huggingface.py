import unittest
from unittest.mock import patch

from swarn_research_mcp.services import huggingface


class HuggingFaceServiceTest(unittest.IsolatedAsyncioTestCase):
    @patch.object(huggingface, "HF_TOKEN", "test-token")
    @patch("swarn_research_mcp.services.huggingface.http_get")
    async def test_search_huggingface_papers_returns_paper_id_to_summary_map_sorted_by_upvotes(self, mock_http_get):
        mock_http_get.return_value = [
            {
                "paper": {
                    "id": "2409.14993",
                    "summary": "paper summary",
                    "upvotes": 1,
                },
                "summary": "top level summary",
                "upvotes": 99,
            },
            {
                "paper": {
                    "id": "2601.02346",
                    "upvotes": 20,
                },
                "summary": "fallback summary",
            },
            {
                "paper": {
                    "id": "2501.00001",
                    "summary": "most upvoted summary",
                    "upvotes": 50,
                },
                "summary": "unused fallback summary",
            },
        ]

        result = await huggingface.search_huggingface_papers("multimodal", limit=2)

        self.assertEqual(
            list(result.items()),
            [
                ("2501.00001", "most upvoted summary"),
                ("2601.02346", "fallback summary"),
                ("2409.14993", "paper summary"),
            ],
        )
        mock_http_get.assert_called_once_with(
            huggingface.HF_PAPERS_SEARCH_URL,
            params={"q": "multimodal", "limit": 2},
            headers={"Authorization": "Bearer test-token"},
        )

    @patch.object(huggingface, "HF_TOKEN", "test-token")
    @patch("swarn_research_mcp.services.huggingface.http_get")
    async def test_collect_huggingface_trending_papers_uses_daily_papers_month_filter(self, mock_http_get):
        mock_http_get.return_value = [
            {
                "paper": {
                    "id": "2601.02346",
                    "summary": "daily paper summary",
                },
                "publishedAt": "2026-01-15T00:00:00.000Z",
            },
            {
                "paper": {
                    "id": "2601.12345",
                },
                "summary": "fallback daily summary",
            },
        ]

        result = await huggingface.collect_huggingface_trending_papers(month="1", year="2026", limit=50)

        self.assertEqual(
            result,
            {
                "2601.02346": "daily paper summary",
                "2601.12345": "fallback daily summary",
            },
        )
        mock_http_get.assert_called_once_with(
            huggingface.HF_DAILY_PAPERS_URL,
            params={
                "p": 0,
                "limit": 50,
                "month": "2026-01",
                "sort": "publishedAt",
            },
            headers={"Authorization": "Bearer test-token"},
        )

    @patch.object(huggingface, "HF_TOKEN", "test-token")
    @patch("swarn_research_mcp.services.huggingface.http_get")
    async def test_collect_huggingface_trending_papers_uses_year_month_input(self, mock_http_get):
        mock_http_get.return_value = []

        result = await huggingface.collect_huggingface_trending_papers(month="2025-06", limit=5)

        self.assertEqual(result, {})
        mock_http_get.assert_called_once_with(
            huggingface.HF_DAILY_PAPERS_URL,
            params={
                "p": 0,
                "limit": 5,
                "month": "2025-06",
                "sort": "publishedAt",
            },
            headers={"Authorization": "Bearer test-token"},
        )

    async def test_collect_huggingface_trending_papers_requires_year_for_short_month(self):
        with self.assertRaisesRegex(ValueError, "year is required"):
            await huggingface.collect_huggingface_trending_papers(month="6", limit=5)


if __name__ == "__main__":
    unittest.main()
