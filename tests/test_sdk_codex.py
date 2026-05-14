from __future__ import annotations

import asyncio
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "sdk" / "codex.py"


def load_sdk_codex_module():
    spec = importlib.util.spec_from_file_location("sdk_codex_script", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Could not load module spec from {SCRIPT_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SdkCodexScriptTest(unittest.TestCase):
    def test_sdk_imports_are_vendored_under_sdk_directory(self) -> None:
        module = load_sdk_codex_module()

        self.assertEqual(module.SDK_ROOT, module.REPO_ROOT / "sdk")
        self.assertNotIn("/codex/", str(module.SDK_PACKAGE_ROOT))

    def test_build_config_uses_codex_from_path(self) -> None:
        with patch("shutil.which", return_value="/tmp/fake-codex"):
            module = load_sdk_codex_module()
            config = module.build_config()

        self.assertEqual(config.codex_bin, "/tmp/fake-codex")
        self.assertEqual(config.cwd, str(module.REPO_ROOT))

    def test_resolve_codex_bin_prefers_env_override(self) -> None:
        module = load_sdk_codex_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_codex = Path(tmpdir) / "codex"
            fake_codex.write_text("", encoding="utf-8")
            with patch.dict(os.environ, {"CODEX_BIN": str(fake_codex)}, clear=False):
                with patch("shutil.which", return_value="/tmp/ignored-codex"):
                    self.assertEqual(module.resolve_codex_bin(), str(fake_codex))

    def test_resolve_codex_bin_raises_when_missing(self) -> None:
        module = load_sdk_codex_module()

        with patch.dict(os.environ, {}, clear=True):
            with patch("shutil.which", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "Could not find a `codex` binary"):
                    module.resolve_codex_bin()

    def test_run_one_shot_returns_thread_and_turn_ids(self) -> None:
        module = load_sdk_codex_module()

        class FakeTurn:
            id = "turn-123"

            def stream(self):
                return object()

        class FakeThread:
            id = "thread-abc"

            async def turn(self, prompt, **kwargs):
                self.prompt = prompt
                self.kwargs = kwargs
                return FakeTurn()

        class FakeCodex:
            def __init__(self, config):
                self.config = config
                self.thread = FakeThread()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

            async def thread_start(self, **kwargs):
                self.thread_start_kwargs = kwargs
                return self.thread

        async def fake_collect(_stream, *, turn_id):
            return SimpleNamespace(final_response="done", usage=None, items=[])

        async def go():
            with (
                patch.object(module, "AsyncCodex", FakeCodex),
                patch.object(module, "_collect_async_run_result", side_effect=fake_collect),
            ):
                return await module.run_one_shot(
                    prompt="hello",
                    model="gpt-5.4-mini",
                    cwd=module.REPO_ROOT,
                    timeout=12,
                )

        result = asyncio.run(go())

        self.assertEqual(result.thread_id, "thread-abc")
        self.assertEqual(result.turn_id, "turn-123")
        self.assertEqual(result.final_response, "done")


if __name__ == "__main__":
    unittest.main()
