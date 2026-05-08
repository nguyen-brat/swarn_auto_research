import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import requests

from swarn_research_mcp.services import utils


class DummyResponse:
    def __init__(self, status_code=200, json_data=None, text="ok", url="https://example.com"):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        return self._json_data


class HttpProxyFallbackTest(unittest.TestCase):
    @patch("swarn_research_mcp.services.utils.get_working_proxies", create=True)
    @patch("swarn_research_mcp.services.utils.fetch_free_proxies", create=True)
    def test_load_proxy_pool_bootstraps_missing_proxy_file(self, mock_fetch_free_proxies, mock_get_working_proxies):
        mock_fetch_free_proxies.return_value = ["http://free-1:8080", "http://free-2:8080"]
        mock_get_working_proxies.return_value = ["http://working-1:8080", "http://working-2:8080"]

        with TemporaryDirectory() as temp_dir:
            proxy_path = Path(temp_dir) / "proxy.txt"
            with patch.object(utils, "PROXY_FILE", proxy_path):
                result = utils._load_proxy_pool()
                written = proxy_path.read_text(encoding="utf-8")

        self.assertEqual(result, ["http://working-1:8080", "http://working-2:8080"])
        self.assertEqual(written, "http://working-1:8080\nhttp://working-2:8080\n")
        mock_fetch_free_proxies.assert_called_once_with()
        mock_get_working_proxies.assert_called_once_with(["http://free-1:8080", "http://free-2:8080"])

    @patch("swarn_research_mcp.services.utils.random.choice", return_value="http://proxy.test:8080")
    @patch("swarn_research_mcp.services.utils.requests.get")
    def test_http_get_uses_proxy_after_direct_retries_fail(self, mock_get, _mock_choice):
        direct_error = requests.exceptions.ConnectionError("blocked")
        mock_get.side_effect = [
            direct_error,
            direct_error,
            DummyResponse(json_data={"source": "proxy"}),
        ]

        result = utils.http_get("https://example.com/data", timeout=5)

        self.assertEqual(result, {"source": "proxy"})
        self.assertEqual(mock_get.call_count, 3)
        self.assertNotIn("proxies", mock_get.call_args_list[0].kwargs)
        self.assertNotIn("proxies", mock_get.call_args_list[1].kwargs)
        self.assertEqual(
            mock_get.call_args_list[2].kwargs["proxies"],
            {"http": "http://proxy.test:8080", "https": "http://proxy.test:8080"},
        )

    @patch("swarn_research_mcp.services.utils.random.choice", return_value="http://proxy.test:8080")
    @patch("swarn_research_mcp.services.utils.requests.post")
    def test_http_post_uses_proxy_after_direct_retries_fail(self, mock_post, _mock_choice):
        direct_error = requests.exceptions.Timeout("blocked")
        mock_post.side_effect = [
            direct_error,
            direct_error,
            DummyResponse(json_data={"source": "proxy"}),
        ]

        result = utils.http_post("https://example.com/data", {"key": "value"}, timeout=5)

        self.assertEqual(result, {"source": "proxy"})
        self.assertEqual(mock_post.call_count, 3)
        self.assertNotIn("proxies", mock_post.call_args_list[0].kwargs)
        self.assertNotIn("proxies", mock_post.call_args_list[1].kwargs)
        self.assertEqual(
            mock_post.call_args_list[2].kwargs["proxies"],
            {"http": "http://proxy.test:8080", "https": "http://proxy.test:8080"},
        )

    @patch("swarn_research_mcp.services.utils.requests.post")
    def test_http_post_does_not_use_proxy_after_rate_limit(self, mock_post):
        mock_post.return_value = DummyResponse(status_code=429)

        with self.assertRaises(requests.HTTPError):
            utils.http_post("https://example.com/data", {"key": "value"}, timeout=300)

        self.assertEqual(mock_post.call_count, 1)
        self.assertNotIn("proxies", mock_post.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
