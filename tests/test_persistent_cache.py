from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib
import sqlite3

import pytest


@pytest.fixture
def reload_pc(monkeypatch, tmp_path):
    def _factory(
        *,
        max_entries: int = 100,
        search_max_entries: int = 1000,
        paper_ttl_days: int = 30,
        search_ttl_days: int = 7,
        disabled: str = "0",
    ):
        db_path = tmp_path / "s2_cache.sqlite"
        monkeypatch.setenv("SWARN_S2_CACHE_DISABLED", disabled)
        monkeypatch.setenv("SWARN_S2_CACHE_DB", str(db_path))
        monkeypatch.setenv("SWARN_S2_CACHE_TTL_DAYS", str(paper_ttl_days))
        monkeypatch.setenv("SWARN_S2_SEARCH_TTL_DAYS", str(search_ttl_days))
        monkeypatch.setenv("SWARN_S2_CACHE_MAX_ENTRIES", str(max_entries))
        monkeypatch.setenv("SWARN_S2_SEARCH_MAX_ENTRIES", str(search_max_entries))
        from swarn_research_mcp.services import persistent_cache

        importlib.reload(persistent_cache)
        return persistent_cache, db_path

    yield _factory

    from swarn_research_mcp.services import persistent_cache

    close = getattr(persistent_cache, "close", None)
    if close:
        close()


def test_put_and_get_round_trip_with_aliases(reload_pc):
    pc, db_path = reload_pc()
    paper = {"paperId": "p1", "externalIds": {"ArXiv": "2502.11089"}}

    pc.put(["p1", "ArXiv:2502.11089", "2502.11089"], paper)

    assert pc.get(["p1"]) == paper
    assert pc.get(["2502.11089"]) == paper
    assert pc.get(["does-not-exist"]) is None
    assert db_path.is_file()


def test_aliases_do_not_duplicate_paper_json(reload_pc):
    pc, db_path = reload_pc()
    paper = {"paperId": "p1", "externalIds": {"ArXiv": "2502.11089"}}

    pc.put(["p1", "ArXiv:2502.11089", "2502.11089"], paper)

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM paper_entries").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM paper_aliases").fetchone()[0] == 3


def test_cache_persists_across_reload(reload_pc):
    pc, _ = reload_pc()
    pc.put(["p1"], {"paperId": "p1"})

    pc2, _ = reload_pc()

    assert pc2.get(["p1"]) == {"paperId": "p1"}


def test_search_cache_round_trip_and_isolation_from_paper_cache(reload_pc):
    pc, _ = reload_pc()
    pc.put(["p1"], {"paperId": "p1"})
    pc.put_search("transformer|2024-2026|10|10", {"data": [{"paperId": "x"}]})

    assert pc.get(["p1"]) == {"paperId": "p1"}
    assert pc.get_search("transformer|2024-2026|10|10") == {"data": [{"paperId": "x"}]}
    assert pc.get_search("p1") is None
    assert pc.get(["transformer|2024-2026|10|10"]) is None


def test_search_cache_persists_across_reload(reload_pc):
    pc, _ = reload_pc()
    pc.put_search("k1", {"data": [{"paperId": "a"}]})
    pc.put_search("k2", {"data": [{"paperId": "b"}]})

    pc2, _ = reload_pc()

    assert pc2.get_search("k1") == {"data": [{"paperId": "a"}]}
    assert pc2.get_search("k2") == {"data": [{"paperId": "b"}]}


def test_disabled_mode_skips_disk_io_entirely(reload_pc):
    pc, db_path = reload_pc(disabled="1")

    pc.put(["p1"], {"paperId": "p1"})
    pc.put_search("query|2024", {"data": []})

    assert pc.get(["p1"]) is None
    assert pc.get_search("query|2024") is None
    assert not db_path.exists()


def test_ttl_expires_paper_entries(reload_pc, monkeypatch):
    pc, _ = reload_pc(paper_ttl_days=1)
    now = 1_700_000_000.0
    monkeypatch.setattr(pc.time, "time", lambda: now)
    pc.put(["p1"], {"paperId": "p1"})

    monkeypatch.setattr(pc.time, "time", lambda: now + 2 * 86400)

    assert pc.get(["p1"]) is None


def test_ttl_expires_search_entries(reload_pc, monkeypatch):
    pc, _ = reload_pc(search_ttl_days=1)
    now = 1_700_000_000.0
    monkeypatch.setattr(pc.time, "time", lambda: now)
    pc.put_search("k1", {"data": []})

    monkeypatch.setattr(pc.time, "time", lambda: now + 2 * 86400)

    assert pc.get_search("k1") is None


def test_eviction_drops_oldest_paper_entries(reload_pc, monkeypatch):
    pc, _ = reload_pc(max_entries=5)
    base = 1_700_000_000.0

    for i in range(8):
        monkeypatch.setattr(pc.time, "time", lambda i=i: base + i)
        pc.put([f"p{i}"], {"paperId": f"p{i}"})

    stats = pc.stats()
    assert stats["papers"]["entries"] <= 5
    assert pc.get(["p0"]) is None
    assert pc.get(["p7"]) == {"paperId": "p7"}


def test_eviction_drops_oldest_search_entries(reload_pc, monkeypatch):
    pc, _ = reload_pc(search_max_entries=2)
    base = 1_700_000_000.0

    for i in range(4):
        monkeypatch.setattr(pc.time, "time", lambda i=i: base + i)
        pc.put_search(f"k{i}", {"data": [{"paperId": f"p{i}"}]})

    stats = pc.stats()
    assert stats["searches"]["entries"] <= 2
    assert pc.get_search("k0") is None
    assert pc.get_search("k3") == {"data": [{"paperId": "p3"}]}


def test_clear_deletes_rows_but_keeps_schema(reload_pc):
    pc, db_path = reload_pc()
    pc.put(["p1"], {"paperId": "p1"})
    pc.put_search("k1", {"data": []})

    pc.clear()

    assert pc.get(["p1"]) is None
    assert pc.get_search("k1") is None
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM paper_entries").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM search_results").fetchone()[0] == 0


def test_stats_reports_sqlite_backend_without_materializing_values(reload_pc):
    pc, db_path = reload_pc()
    pc.put(["p1"], {"paperId": "p1"})
    pc.put_search("k1", {"data": []})

    stats = pc.stats()

    assert stats["backend"] == "sqlite"
    assert stats["db_path"] == str(db_path)
    assert stats["papers"]["entries"] == 1
    assert stats["papers"]["aliases"] == 1
    assert stats["searches"]["entries"] == 1
    assert "snapshot_path" not in stats["papers"]
    assert "journal_path" not in stats["papers"]


def test_concurrent_public_operations_are_serialized(reload_pc):
    pc, _ = reload_pc(max_entries=1000, search_max_entries=1000)
    operation_count = 200
    exceptions = []

    def write_pair(i: int) -> None:
        try:
            pc.put([f"p{i}"], {"paperId": f"p{i}"})
            pc.put_search(f"k{i}", {"data": [{"paperId": f"p{i}"}]})
        except Exception as exc:  # pragma: no cover - failure detail for assertion
            exceptions.append(exc)

    with ThreadPoolExecutor(max_workers=16) as executor:
        list(executor.map(write_pair, range(operation_count)))

    stats = pc.stats()
    assert exceptions == []
    assert stats["papers"]["entries"] == operation_count
    assert stats["papers"]["aliases"] == operation_count
    assert stats["searches"]["entries"] == operation_count


def test_cache_io_failures_degrade_to_miss_or_skipped_write(reload_pc, tmp_path):
    blocked_parent = tmp_path / "not-a-dir"
    blocked_parent.write_text("file blocks cache directory creation", encoding="utf-8")
    pc, _ = reload_pc()
    pc.close()
    pc._CACHE_DB_PATH = blocked_parent / "s2_cache.sqlite"

    assert pc.get(["p1"]) is None
    assert pc.get_search("q1") is None
    pc.put(["p1"], {"paperId": "p1"})
    pc.put_search("q1", {"data": []})
