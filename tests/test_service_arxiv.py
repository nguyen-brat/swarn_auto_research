import unittest
from unittest.mock import patch

from swarn_research_mcp.services import arxiv


class ArxivServiceTest(unittest.IsolatedAsyncioTestCase):
    @patch("swarn_research_mcp.services.arxiv.http_get")
    async def test_get_arxiv_markdown_calls_arxiv2md_api(self, mock_http_get):
        mock_http_get.return_value = "# Attention Is All You Need"

        result = await arxiv.get_arxiv_markdown("1706.03762", remove_toc=False)

        self.assertEqual(result, "# Attention Is All You Need")
        mock_http_get.assert_called_once_with(
            arxiv.ARXIV2MD_MARKDOWN_URL,
            params={"url": "1706.03762", "remove_toc": "false"},
            return_json=False,
        )

    def test_extract_markdown_section_returns_top_level_section(self):
        markdown = """# Attention Is All You Need

## Model Architecture
Architecture intro.

### Encoder and Decoder Stacks
Stack overview.

#### Encoder:
Encoder details.

## Training
Training details.
"""

        result = arxiv.extract_markdown_section(markdown, "Model Architecture")

        self.assertEqual(
            result,
            "## Model Architecture\nArchitecture intro.\n\n### Encoder and Decoder Stacks\nStack overview.\n\n#### Encoder:\nEncoder details."
        )

    def test_extract_markdown_section_returns_nested_subsection(self):
        markdown = """# Attention Is All You Need

## Model Architecture
Architecture intro.

### Encoder and Decoder Stacks
Stack overview.

#### Encoder:
Encoder details.

#### Decoder:
Decoder details.

## Training
Training details.
"""

        result = arxiv.extract_markdown_section(
            markdown,
            "Model Architecture/Encoder and Decoder Stacks/Encoder:",
        )

        self.assertEqual(result, "#### Encoder:\nEncoder details.")


if __name__ == "__main__":
    unittest.main()
