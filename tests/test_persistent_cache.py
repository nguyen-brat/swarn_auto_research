"""Tests for the persistent Semantic Scholar paper-detail cache.

Covers the snapshot + journal durability model:
- a `put` is recoverable from the journal even if the snapshot is stale
- compaction merges the journal into a fresh snapshot and truncates the log
- malformed / partial journal lines are skipped on load
- a crashed compaction does not lose data
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def reload_pc(monkeypatch, tmp_path):
    """Factory that reloads persistent_cache with isolated env vars."""
    def _factory(max_entries: int = 100, flush_every: int = 1_000_000, fsync: str = "1"):
        cache_path = tmp_path / "s2_paper_details.json"
        log_path = tmp_path / "s2_paper_details.json.log"
        search_path = tmp_path / "s2_search_results.json"
        monkeypatch.setenv("SWARN_S2_CACHE_DISABLED", "0")
        monkeypatch.setenv("SWARN_S2_CACHE_PATH", str(cache_path))
        monkeypatch.setenv("SWARN_S2_SEARCH_CACHE_PATH", str(search_path))
        monkeypatch.setenv("SWARN_S2_CACHE_FLUSH_EVERY", str(flush_every))
        monkeypatch.setenv("SWARN_S2_CACHE_TTL_DAYS", "30")
        monkeypatch.setenv("SWARN_S2_SEARCH_TTL_DAYS", "7")
        monkeypatch.setenv("SWARN_S2_CACHE_MAX_ENTRIES", str(max_entries))
        monkeypatch.setenv("SWARN_S2_SEARCH_MAX_ENTRIES", "1000")
        monkeypatch.setenv("SWARN_S2_CACHE_FSYNC", fsync)
        from swarn_research_mcp.services import persistent_cache
        importlib.reload(persistent_cache)
        return persistent_cache, cache_path, log_path
    yield _factory
    # Teardown: reset BOTH stores explicitly. monkeypatch's env-var
    # restore happens after this code runs, so we can't trust a reload.
    from swarn_research_mcp.services import persistent_cache
    for store in (persistent_cache._PAPER_STORE, persistent_cache._SEARCH_STORE):
        if store.log_fh is not None:
            try:
                store.log_fh.close()
            except OSError:
                pass
            store.log_fh = None
        store.data.clear()
        store.dirty = 0
        store.loaded = True
    persistent_cache._DISABLED = True


def test_put_and_get_round_trip(reload_pc):
    pc, _, _ = reload_pc()
    paper = {"paperId": "p1", "externalIds": {"ArXiv": "2502.11089"}}
    pc.put(["p1", "ArXiv:2502.11089", "2502.11089"], paper)
    assert pc.get(["p1"]) == paper
    assert pc.get(["2502.11089"]) == paper
    assert pc.get(["does-not-exist"]) is None


def test_journal_persists_put_before_compaction(reload_pc):
    """A put must be durable on disk before it returns — even with no compaction."""
    pc, snapshot_path, log_path = reload_pc(flush_every=1_000_000)
    pc.put(["p1"], {"paperId": "p1"})
    pc.put(["p2"], {"paperId": "p2"})

    # No compaction yet: snapshot may not exist, journal must.
    assert log_path.is_file()
    log_lines = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    assert any(rec["paper"]["paperId"] == "p1" for rec in log_lines)
    assert any(rec["paper"]["paperId"] == "p2" for rec in log_lines)


def test_reload_after_crash_recovers_uncompacted_journal(reload_pc):
    """Simulate hard kill before compaction: journal alone must rebuild state."""
    pc, _, _ = reload_pc(flush_every=1_000_000)
    pc.put(["p1"], {"paperId": "p1"})
    pc.put(["p2"], {"paperId": "p2"})

    # Reload (no flush/compact) — just like a crashed process restarting.
    pc2, _, _ = reload_pc(flush_every=1_000_000)
    assert pc2.get(["p1"]) == {"paperId": "p1"}
    assert pc2.get(["p2"]) == {"paperId": "p2"}


def test_compaction_merges_journal_into_snapshot_and_truncates_log(reload_pc):
    pc, snapshot_path, log_path = reload_pc(flush_every=2)  # compact after 2 puts
    pc.put(["p1"], {"paperId": "p1"})
    pc.put(["p2"], {"paperId": "p2"})  # triggers compaction

    assert snapshot_path.is_file()
    on_disk = json.loads(snapshot_path.read_text())
    assert "p1" in on_disk and "p2" in on_disk

    # Journal should be empty (truncated) after compaction.
    assert log_path.read_text().strip() == ""


def test_compaction_followed_by_more_puts_uses_journal_again(reload_pc):
    pc, snapshot_path, log_path = reload_pc(flush_every=2)
    pc.put(["p1"], {"paperId": "p1"})
    pc.put(["p2"], {"paperId": "p2"})  # snapshot written, journal truncated
    pc.put(["p3"], {"paperId": "p3"})  # journaled but not compacted

    # Snapshot does NOT have p3 yet.
    on_disk = json.loads(snapshot_path.read_text())
    assert "p3" not in on_disk
    # Journal does.
    log_lines = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    assert any(rec["paper"]["paperId"] == "p3" for rec in log_lines)

    # Reload — combined view must include all three.
    pc2, _, _ = reload_pc(flush_every=2)
    assert pc2.get(["p1"]) == {"paperId": "p1"}
    assert pc2.get(["p2"]) == {"paperId": "p2"}
    assert pc2.get(["p3"]) == {"paperId": "p3"}


def test_corrupt_journal_line_does_not_block_replay(reload_pc):
    pc, _, log_path = reload_pc()
    pc.put(["p1"], {"paperId": "p1"})
    pc.flush()  # force snapshot, drop journal

    # Manually append a corrupt line then a valid one (simulate partial write).
    with open(log_path, "a", encoding="utf-8") as f:
        f.write('{"keys": ["p2"], "paper": {"paperId": "p2"}, "fetched_at": ' + str(__import__("time").time()) + "}\n")
        f.write("{not valid json\n")  # truncated mid-write
        f.write('{"keys": ["p3"], "paper": {"paperId": "p3"}, "fetched_at": ' + str(__import__("time").time()) + "}\n")

    pc2, _, _ = reload_pc()
    assert pc2.get(["p1"]) == {"paperId": "p1"}
    assert pc2.get(["p2"]) == {"paperId": "p2"}
    assert pc2.get(["p3"]) == {"paperId": "p3"}


def test_failed_snapshot_keeps_journal_intact(reload_pc, monkeypatch):
    """If os.replace fails mid-compact, journal must survive untouched."""
    pc, snapshot_path, log_path = reload_pc(flush_every=2)
    pc.put(["p1"], {"paperId": "p1"})
    pc.put(["p2"], {"paperId": "p2"})  # successful compaction; baseline.

    # Now break os.replace and try to compact again.
    monkeypatch.setattr(
        "os.replace",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
    )
    pc.put(["p3"], {"paperId": "p3"})
    pc.put(["p4"], {"paperId": "p4"})  # would compact but replace fails

    # Snapshot keeps the pre-failure state.
    on_disk = json.loads(snapshot_path.read_text())
    assert "p1" in on_disk and "p2" in on_disk and "p3" not in on_disk
    # Journal still holds p3, p4.
    log_records = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    journaled_ids = {rec["paper"]["paperId"] for rec in log_records}
    assert {"p3", "p4"}.issubset(journaled_ids)


def test_eviction_drops_oldest_when_oversized(reload_pc):
    pc, _, _ = reload_pc(max_entries=5)
    for i in range(8):
        pc.put([f"p{i}"], {"paperId": f"p{i}"})
    assert pc.stats()["papers"]["entries"] <= 5


def test_disabled_mode_skips_disk_io_entirely(reload_pc, monkeypatch):
    monkeypatch.setenv("SWARN_S2_CACHE_DISABLED", "1")
    from swarn_research_mcp.services import persistent_cache
    importlib.reload(persistent_cache)
    pc = persistent_cache
    pc.put(["p1"], {"paperId": "p1"})
    assert pc.get(["p1"]) is None
    pc.put_search("query|2024", {"data": []})
    assert pc.get_search("query|2024") is None


def test_search_cache_round_trip_and_isolation_from_paper_cache(reload_pc, tmp_path):
    pc, _, _ = reload_pc()
    pc.put(["p1"], {"paperId": "p1"})
    pc.put_search("transformer|2024-2026|10|10", {"data": [{"paperId": "x"}]})
    assert pc.get(["p1"]) == {"paperId": "p1"}
    assert pc.get_search("transformer|2024-2026|10|10") == {"data": [{"paperId": "x"}]}
    assert pc.get_search("p1") is None  # paper key must not leak into search cache
    assert pc.get(["transformer|2024-2026|10|10"]) is None  # vice versa


def test_search_cache_persists_across_reload(reload_pc):
    pc, _, _ = reload_pc()
    pc.put_search("k1", {"data": [{"paperId": "a"}]})
    pc.put_search("k2", {"data": [{"paperId": "b"}]})

    pc2, _, _ = reload_pc()
    assert pc2.get_search("k1") == {"data": [{"paperId": "a"}]}
    assert pc2.get_search("k2") == {"data": [{"paperId": "b"}]}


def test_search_cache_uses_separate_files(reload_pc, tmp_path):
    pc, paper_snapshot, _ = reload_pc()
    pc.put_search("k1", {"data": []})
    pc.flush()
    search_snapshot = tmp_path / "s2_search_results.json"
    assert search_snapshot.is_file()
    assert search_snapshot != paper_snapshot
    # Search snapshot should not contain paper-detail entries.
    paper_blob = paper_snapshot.read_text() if paper_snapshot.is_file() else ""
    search_blob = search_snapshot.read_text()
    assert '"k1"' in search_blob
    assert '"paper-1"' not in search_blob
