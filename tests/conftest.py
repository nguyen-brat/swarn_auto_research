"""Pytest session-wide configuration.

Redirects the persistent Semantic Scholar paper-detail cache at a
per-session temp directory so tests never read or mutate the developer's
real cache file at `swarn_research_mcp/cache/s2_paper_details.json`.
"""
from __future__ import annotations

import importlib
import os
import shutil
import tempfile
from pathlib import Path

import pytest


def pytest_configure(config):
    """Disable the persistent S2 cache during the test session.

    Tests rely on mocked HTTP calls — a warm persistent cache short-
    circuits those mocks and produces stale results. Tests that
    specifically exercise the persistent cache module re-enable it via
    `monkeypatch.setenv("SWARN_S2_CACHE_DISABLED", "0")` and reload.
    """
    os.environ["SWARN_S2_CACHE_DISABLED"] = "1"
    # Point at a throwaway path so even if a test re-enables the cache
    # without an explicit override, nothing touches the developer's real
    # cache files.
    tmp_dir = Path(tempfile.mkdtemp(prefix="swarn-s2-cache-"))
    os.environ["SWARN_S2_CACHE_PATH"] = str(tmp_dir / "s2_paper_details.json")
    os.environ["SWARN_S2_SEARCH_CACHE_PATH"] = str(tmp_dir / "s2_search_results.json")

    try:
        from swarn_research_mcp.services import persistent_cache
        importlib.reload(persistent_cache)
    except ImportError:
        pass


def pytest_unconfigure(config):
    # Best-effort teardown: don't fail the session if cleanup misses.
    cache_dir = os.environ.get("SWARN_S2_CACHE_PATH")
    if cache_dir:
        path = Path(cache_dir)
        try:
            if path.is_file():
                path.unlink()
            if path.parent.is_dir() and path.parent.name.startswith("swarn-s2-cache-"):
                path.parent.rmdir()
        except OSError:
            pass


@pytest.fixture
def voice_lm_minimal(tmp_path):
    """Copy the voice_lm_minimal fixture to a tmp dir; tests can mutate freely."""
    src = Path(__file__).parent / "fixtures" / "voice_lm_minimal"
    dst = tmp_path / "run"
    shutil.copytree(src, dst)
    return dst
