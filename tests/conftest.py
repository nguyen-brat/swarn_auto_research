"""Pytest session-wide configuration.

Redirects the persistent Semantic Scholar cache at a per-session temp
directory so tests never read or mutate the developer's real cache files
under `swarn_research_mcp/cache`.
"""
from __future__ import annotations

import importlib
import os
import shutil
import tempfile
from pathlib import Path

import pytest


def _reload_persistent_cache():
    try:
        from swarn_research_mcp.services import persistent_cache
    except ImportError:
        return None
    persistent_cache.close()
    return importlib.reload(persistent_cache)


def _remove_session_cache_db(config):
    cache_db = getattr(config, "_swarn_s2_cache_db", None)
    if not cache_db:
        return
    path = Path(cache_db)
    try:
        if not (path.parent.is_dir() and path.parent.name.startswith("swarn-s2-cache-")):
            return
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(path) + suffix)
            if candidate.is_file():
                candidate.unlink()
    except OSError:
        pass


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
    cache_db = tmp_dir / "s2_cache.sqlite"
    config._swarn_s2_cache_db = cache_db
    os.environ["SWARN_S2_CACHE_DB"] = str(cache_db)
    os.environ["SWARN_S2_CACHE_PATH"] = str(tmp_dir / "s2_paper_details.json")
    os.environ["SWARN_S2_SEARCH_CACHE_PATH"] = str(tmp_dir / "s2_search_results.json")
    os.environ.setdefault("HANDBOOK_PUBLISH_ENABLED", "0")

    _reload_persistent_cache()


@pytest.fixture(autouse=True)
def _reset_s2_cache_state(request):
    yield
    persistent_cache = _reload_persistent_cache()
    _remove_session_cache_db(request.config)
    if persistent_cache is None:
        return
    try:
        from swarn_research_mcp.services import semantic_scholar
    except ImportError:
        return
    semantic_scholar.PAPER_DETAIL_CACHE.clear()


def pytest_unconfigure(config):
    # Best-effort teardown: don't fail the session if cleanup misses.
    _remove_session_cache_db(config)
    cache_db = getattr(config, "_swarn_s2_cache_db", None)
    if cache_db:
        try:
            path = Path(cache_db)
            if not path.parent.name.startswith("swarn-s2-cache-"):
                return
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
