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
        captured_thread = None

        class FakeTurn:
            id = "turn-123"

            def __init__(self):
                self.notification_timeout_s = None

            def stream(self, notification_timeout_s=None):
                self.notification_timeout_s = notification_timeout_s
                return object()

        class FakeThread:
            id = "thread-abc"

            def __init__(self):
                self.fake_turn = FakeTurn()

            async def turn(self, prompt, **kwargs):
                self.prompt = prompt
                self.kwargs = kwargs
                return self.fake_turn

        class FakeCodex:
            def __init__(self, config):
                nonlocal captured_thread
                self.config = config
                self.thread = FakeThread()
                captured_thread = self.thread

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
        self.assertIsNotNone(captured_thread)
        self.assertEqual(captured_thread.fake_turn.notification_timeout_s, 12)

    def test_run_one_shot_accepts_stable_artifact_and_interrupts_turn(self) -> None:
        module = load_sdk_codex_module()
        captured_turn = None

        class FakeStream:
            def __init__(self):
                self.closed = False

            async def aclose(self):
                self.closed = True

        class FakeTurn:
            id = "turn-artifact"

            def __init__(self):
                self.stream_obj = FakeStream()
                self.interrupted = False

            def stream(self, notification_timeout_s=None):
                return self.stream_obj

            async def interrupt(self):
                self.interrupted = True

        class FakeThread:
            id = "thread-artifact"

            def __init__(self):
                self.fake_turn = FakeTurn()

            async def turn(self, prompt, **kwargs):
                return self.fake_turn

        class FakeCodex:
            def __init__(self, config):
                nonlocal captured_turn
                self.thread = FakeThread()
                captured_turn = self.thread.fake_turn

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

            async def thread_start(self, **kwargs):
                return self.thread

        async def fake_collect(_stream, *, turn_id):
            await asyncio.sleep(30)

        async def go():
            with (
                patch.object(module, "AsyncCodex", FakeCodex),
                patch.object(module, "_collect_async_run_result", side_effect=fake_collect),
            ):
                return await module.run_one_shot(
                    prompt="hello",
                    model="gpt-5.4-mini",
                    cwd=module.REPO_ROOT,
                    timeout=1,
                    artifact_signature=lambda: ("stable",),
                    artifact_settle_seconds=0.01,
                    artifact_interrupt_timeout=0.01,
                )

        result = asyncio.run(go())

        self.assertEqual(result.thread_id, "thread-artifact")
        self.assertEqual(result.turn_id, "turn-artifact")
        self.assertTrue(result.completed_by_artifact)
        self.assertIsNotNone(captured_turn)
        self.assertTrue(captured_turn.interrupted)
        self.assertTrue(captured_turn.stream_obj.closed)

    def test_run_one_shot_waits_for_artifact_signature_to_stabilize(self) -> None:
        module = load_sdk_codex_module()
        signatures = iter([("partial",), ("larger",), ("larger",), ("larger",)])
        observed = []

        class FakeStream:
            async def aclose(self):
                pass

        class FakeTurn:
            id = "turn-stable"

            def stream(self, notification_timeout_s=None):
                return FakeStream()

            async def interrupt(self):
                pass

        class FakeThread:
            id = "thread-stable"

            async def turn(self, prompt, **kwargs):
                return FakeTurn()

        class FakeCodex:
            def __init__(self, config):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

            async def thread_start(self, **kwargs):
                return FakeThread()

        def artifact_signature():
            try:
                signature = next(signatures)
            except StopIteration:
                signature = ("larger",)
            observed.append(signature)
            return signature

        async def fake_collect(_stream, *, turn_id):
            await asyncio.sleep(30)

        async def go():
            with (
                patch.object(module, "AsyncCodex", FakeCodex),
                patch.object(module, "_collect_async_run_result", side_effect=fake_collect),
            ):
                return await module.run_one_shot(
                    prompt="hello",
                    model="gpt-5.4-mini",
                    cwd=module.REPO_ROOT,
                    timeout=1,
                    artifact_signature=artifact_signature,
                    artifact_settle_seconds=0.02,
                    artifact_interrupt_timeout=0.01,
                )

        result = asyncio.run(go())

        self.assertTrue(result.completed_by_artifact)
        self.assertGreaterEqual(len(observed), 3)
        self.assertIn(("partial",), observed)
        self.assertIn(("larger",), observed)

    def test_run_one_shot_artifact_acceptance_does_not_block_on_interrupt(self) -> None:
        module = load_sdk_codex_module()

        class FakeStream:
            async def aclose(self):
                pass

        class FakeTurn:
            id = "turn-slow-interrupt"

            def stream(self, notification_timeout_s=None):
                return FakeStream()

            async def interrupt(self):
                await asyncio.sleep(30)

        class FakeThread:
            id = "thread-slow-interrupt"

            async def turn(self, prompt, **kwargs):
                return FakeTurn()

        class FakeCodex:
            def __init__(self, config):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

            async def thread_start(self, **kwargs):
                return FakeThread()

        async def fake_collect(_stream, *, turn_id):
            await asyncio.sleep(30)

        async def go():
            with (
                patch.object(module, "AsyncCodex", FakeCodex),
                patch.object(module, "_collect_async_run_result", side_effect=fake_collect),
            ):
                return await module.run_one_shot(
                    prompt="hello",
                    model="gpt-5.4-mini",
                    cwd=module.REPO_ROOT,
                    timeout=1,
                    artifact_signature=lambda: ("stable",),
                    artifact_settle_seconds=0.01,
                    artifact_interrupt_timeout=0.01,
                )

        result = asyncio.run(go())

        self.assertTrue(result.completed_by_artifact)

    def test_run_one_shot_attaches_sdk_meta_to_collect_errors(self) -> None:
        module = load_sdk_codex_module()

        class FakeTurn:
            id = "turn-error"

            def stream(self, notification_timeout_s=None):
                return object()

        class FakeThread:
            id = "thread-error"

            async def turn(self, prompt, **kwargs):
                return FakeTurn()

        class FakeCodex:
            def __init__(self, config):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

            async def thread_start(self, **kwargs):
                return FakeThread()

        async def fake_collect(_stream, *, turn_id):
            raise TimeoutError("boom")

        async def go():
            with (
                patch.object(module, "AsyncCodex", FakeCodex),
                patch.object(module, "_collect_async_run_result", side_effect=fake_collect),
            ):
                return await module.run_one_shot(
                    prompt="hello",
                    model="gpt-5.4-mini",
                    cwd=module.REPO_ROOT,
                    timeout=1,
                )

        with self.assertRaises(TimeoutError) as raised:
            asyncio.run(go())

        self.assertEqual(
            raised.exception.sdk_meta,
            {"thread_id": "thread-error", "turn_id": "turn-error"},
        )


if __name__ == "__main__":
    unittest.main()
