import unittest
from unittest.mock import patch

from swarn_research_mcp.tools import select_paper


class SelectPaperToolTest(unittest.TestCase):
    @patch("swarn_research_mcp.tools.select_paper.datetime")
    def test_filter_papers_keeps_keyword_matches_and_skips_negative_matches(self, mock_datetime):
        mock_datetime.datetime.now.return_value.year = 2026
        papers = {
            "2401.00001": "Transformer reasoning with chain of thought.",
            "2401.00002": "Robotics control with diffusion policy.",
            "2401.00003": "Inference scaling for transformer reasoning.",
            "1901.00001": "Transformer reasoning from an older paper.",
        }

        kept = select_paper.filter_papers(
            papers,
            keywords=["transformer", "reasoning"],
            negative_keywords=["robotics"],
        )

        self.assertEqual(
            kept,
            {
                "2401.00001": "Transformer reasoning with chain of thought.",
                "2401.00003": "Inference scaling for transformer reasoning.",
            },
        )

    @patch("swarn_research_mcp.tools.select_paper.datetime")
    def test_select_papers_returns_filtered_dictionary(self, mock_datetime):
        mock_datetime.datetime.now.return_value.year = 2026
        papers = {
            "2401.00001": "Transformer reasoning with chain of thought.",
            "2401.00002": "Robotics control with diffusion policy.",
            "2401.00003": "Inference scaling for transformer reasoning.",
            "1801.00001": "Transformer reasoning from an old paper.",
        }

        result = select_paper.select_papers(
            papers=papers,
            keywords=["transformer", "reasoning"],
            negative_keywords=["robotics"],
        )

        self.assertEqual(result["total_input"], 4)
        self.assertEqual(result["total_kept"], 2)
        self.assertEqual(result["papers"]["2401.00001"], "Transformer reasoning with chain of thought.")
        self.assertEqual(result["papers"]["2401.00003"], "Inference scaling for transformer reasoning.")


if __name__ == "__main__":
    unittest.main()
