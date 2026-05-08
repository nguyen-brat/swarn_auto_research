from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
