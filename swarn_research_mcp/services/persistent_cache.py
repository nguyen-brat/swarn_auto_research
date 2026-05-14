"""Persistent on-disk caches for Semantic Scholar.

Two independent stores live in the same `cache/` directory:

- **Paper-detail cache** (`s2_paper_details.json` + `.log`) — caches the
  raw paper dict returned by `/paper/batch` (with `citations` and
  `references` arrays). 30-day TTL because paper detail is stable but
  citationCount drifts.
- **Search-result cache** (`s2_search_results.json` + `.log`) — caches
  the raw `/paper/search` response keyed by
  `(query, year_range, min_citation_count, limit)`. 7-day TTL because
  search rankings shift faster than detail.

Both stores share the same durability machinery:

- Snapshot file (atomic write via `tempfile.mkstemp` + `os.replace`).
- Append-only journal (`.log`) with one JSONL record per `put`,
  `flush()` + `os.fsync()`'d before the call returns. A crash anywhere
  after that line is on disk does NOT lose the entry.
- Compaction: every `flush_every` puts (or on `flush()` / `atexit`),
  write a fresh snapshot, then truncate the journal.

A crash mid-compaction is safe:
- before snapshot rename: snapshot stays old, journal stays full → next
  load replays the same journal → identical state.
- after snapshot rename, before journal truncate: snapshot has full
  state, journal has duplicates → re-applying duplicates is a no-op
  (last-write-wins on the same key).
- after both: clean state.

Concurrency: per-store locks. Multiple MCP processes writing the same
files would race on the truncate step (POSIX append is atomic for small
records). Use a single MCP server per repo.

## Backward-compatible API

Existing callers use module-level `get(keys)` / `put(keys, paper)` —
those still target the paper-detail cache. New callers use
`get_search(key)` / `put_search(key, result)` for the search cache.
"""

from __future__ import annotations

import atexit
import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_CACHE_PATH = (
    Path(__file__).resolve().parents[1] / "cache" / "s2_paper_details.json"
)
_PAPER_SNAPSHOT_PATH = Path(os.environ.get("SWARN_S2_CACHE_PATH", _DEFAULT_CACHE_PATH))
_SEARCH_SNAPSHOT_PATH = (
    Path(os.environ.get("SWARN_S2_SEARCH_CACHE_PATH", ""))
    if os.environ.get("SWARN_S2_SEARCH_CACHE_PATH")
    else _PAPER_SNAPSHOT_PATH.parent / "s2_search_results.json"
)
_FLUSH_EVERY = int(os.environ.get("SWARN_S2_CACHE_FLUSH_EVERY", "50"))
_PAPER_TTL_DAYS = int(os.environ.get("SWARN_S2_CACHE_TTL_DAYS", "30"))
_SEARCH_TTL_DAYS = int(os.environ.get("SWARN_S2_SEARCH_TTL_DAYS", "7"))
_MAX_PAPER_ENTRIES = int(os.environ.get("SWARN_S2_CACHE_MAX_ENTRIES", "100000"))
_MAX_SEARCH_ENTRIES = int(os.environ.get("SWARN_S2_SEARCH_MAX_ENTRIES", "5000"))
_DISABLED = os.environ.get("SWARN_S2_CACHE_DISABLED", "0") == "1"
_FSYNC = os.environ.get("SWARN_S2_CACHE_FSYNC", "1") == "1"


# ---------------------------------------------------------------------------
# Generic store
# ---------------------------------------------------------------------------

@dataclass
class _Store:
    snapshot_path: Path
    log_path: Path
    ttl_days: int
    max_entries: int
    value_field: str  # "paper" or "result"
    lock: Lock = field(default_factory=Lock)
    data: dict[str, dict] = field(default_factory=dict)
    dirty: int = 0
    loaded: bool = False
    log_fh: Any = None


def _open_log_for_append(store: _Store):
    store.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    return open(store.log_path, "a", encoding="utf-8")


def _ensure_loaded(store: _Store) -> None:
    """Lazy-load: read snapshot, then replay journal lines on top."""
    if store.loaded:
        return
    with store.lock:
        if store.loaded:
            return
        store.loaded = True
        ttl_cutoff = time.time() - store.ttl_days * 86400

        # 1) Snapshot.
        if store.snapshot_path.is_file():
            try:
                snap = json.loads(store.snapshot_path.read_text(encoding="utf-8"))
                if isinstance(snap, dict):
                    for key, entry in snap.items():
                        if not isinstance(entry, dict):
                            continue
                        if entry.get("fetched_at", 0) < ttl_cutoff:
                            continue
                        store.data[key] = entry
            except (OSError, json.JSONDecodeError):
                pass

        # 2) Replay journal. Tolerate corrupt last line.
        if store.log_path.is_file():
            try:
                with open(store.log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        keys = record.get("keys")
                        value = record.get(store.value_field)
                        fetched_at = record.get("fetched_at", 0)
                        if not (isinstance(keys, list) and isinstance(value, dict)):
                            continue
                        if fetched_at < ttl_cutoff:
                            continue
                        entry = {store.value_field: value, "fetched_at": fetched_at}
                        for key in keys:
                            if isinstance(key, str) and key:
                                store.data[key] = entry
            except OSError:
                pass

        try:
            store.log_fh = _open_log_for_append(store)
        except OSError:
            store.log_fh = None


def _evict_if_oversized(store: _Store) -> None:
    if len(store.data) <= store.max_entries:
        return
    over = len(store.data) - store.max_entries + (store.max_entries // 10)
    victims = sorted(store.data.items(), key=lambda kv: kv[1].get("fetched_at", 0))[:over]
    for key, _ in victims:
        store.data.pop(key, None)


def _journal_append_locked(store: _Store, keys: list[str], value: dict, fetched_at: float) -> None:
    if store.log_fh is None:
        try:
            store.log_fh = _open_log_for_append(store)
        except OSError:
            return
    line = json.dumps(
        {"keys": keys, store.value_field: value, "fetched_at": fetched_at},
        ensure_ascii=False,
    )
    try:
        store.log_fh.write(line + "\n")
        store.log_fh.flush()
        if _FSYNC:
            os.fsync(store.log_fh.fileno())
    except OSError:
        try:
            store.log_fh.close()
        except OSError:
            pass
        try:
            store.log_fh = _open_log_for_append(store)
        except OSError:
            store.log_fh = None


def _compact_locked(store: _Store) -> None:
    if store.dirty <= 0:
        return
    store.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".s2_cache.", suffix=".tmp", dir=str(store.snapshot_path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(store.data, f, ensure_ascii=False)
            f.flush()
            if _FSYNC:
                os.fsync(f.fileno())
        os.replace(tmp_path, store.snapshot_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return

    try:
        if store.log_fh is not None:
            store.log_fh.close()
    except OSError:
        pass
    try:
        if store.log_path.is_file():
            with open(store.log_path, "w", encoding="utf-8") as f:
                f.truncate(0)
                if _FSYNC:
                    os.fsync(f.fileno())
        store.log_fh = _open_log_for_append(store)
    except OSError:
        store.log_fh = None
    store.dirty = 0


def _store_get(store: _Store, keys: list[str]) -> dict | None:
    if _DISABLED:
        return None
    _ensure_loaded(store)
    with store.lock:
        for key in keys:
            entry = store.data.get(key)
            if entry:
                return entry.get(store.value_field)
    return None


def _store_put(store: _Store, keys: list[str], value: dict) -> None:
    if _DISABLED or not value or not keys:
        return
    _ensure_loaded(store)
    valid_keys = [k for k in keys if isinstance(k, str) and k]
    if not valid_keys:
        return
    now = time.time()
    with store.lock:
        entry = {store.value_field: value, "fetched_at": now}
        for key in valid_keys:
            store.data[key] = entry
        _journal_append_locked(store, valid_keys, value, now)
        store.dirty += 1
        _evict_if_oversized(store)
        if store.dirty >= _FLUSH_EVERY:
            _compact_locked(store)


def _store_flush(store: _Store) -> None:
    with store.lock:
        _compact_locked(store)


# ---------------------------------------------------------------------------
# Two stores: paper-detail (existing) and search-result (new)
# ---------------------------------------------------------------------------

_PAPER_STORE = _Store(
    snapshot_path=_PAPER_SNAPSHOT_PATH,
    log_path=_PAPER_SNAPSHOT_PATH.with_suffix(_PAPER_SNAPSHOT_PATH.suffix + ".log"),
    ttl_days=_PAPER_TTL_DAYS,
    max_entries=_MAX_PAPER_ENTRIES,
    value_field="paper",
)

_SEARCH_STORE = _Store(
    snapshot_path=_SEARCH_SNAPSHOT_PATH,
    log_path=_SEARCH_SNAPSHOT_PATH.with_suffix(_SEARCH_SNAPSHOT_PATH.suffix + ".log"),
    ttl_days=_SEARCH_TTL_DAYS,
    max_entries=_MAX_SEARCH_ENTRIES,
    value_field="result",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Paper-detail cache (existing API kept verbatim).

def get(keys: list[str]) -> dict | None:
    """Paper-detail cache: return the first paper matching any of `keys`."""
    return _store_get(_PAPER_STORE, keys)


def put(keys: list[str], paper: dict) -> None:
    """Paper-detail cache: store `paper` under every key. Durably journaled."""
    _store_put(_PAPER_STORE, keys, paper)


# Search-result cache (new).

def get_search(key: str) -> dict | None:
    """Search-result cache: return the cached `/paper/search` response or None."""
    return _store_get(_SEARCH_STORE, [key])


def put_search(key: str, result: dict) -> None:
    """Search-result cache: store the raw `/paper/search` response under `key`."""
    _store_put(_SEARCH_STORE, [key], result)


# Maintenance.

def flush() -> None:
    """Force snapshot compaction on both stores."""
    _store_flush(_PAPER_STORE)
    _store_flush(_SEARCH_STORE)


def clear() -> None:
    """Drop every entry in both stores. Test helper."""
    for store in (_PAPER_STORE, _SEARCH_STORE):
        with store.lock:
            store.data.clear()
            store.dirty = 1
            _compact_locked(store)


def stats() -> dict:
    _ensure_loaded(_PAPER_STORE)
    _ensure_loaded(_SEARCH_STORE)
    with _PAPER_STORE.lock, _SEARCH_STORE.lock:
        return {
            "papers": {
                "entries": len(_PAPER_STORE.data),
                "dirty": _PAPER_STORE.dirty,
                "snapshot_path": str(_PAPER_STORE.snapshot_path),
                "journal_path": str(_PAPER_STORE.log_path),
                "ttl_days": _PAPER_STORE.ttl_days,
            },
            "searches": {
                "entries": len(_SEARCH_STORE.data),
                "dirty": _SEARCH_STORE.dirty,
                "snapshot_path": str(_SEARCH_STORE.snapshot_path),
                "journal_path": str(_SEARCH_STORE.log_path),
                "ttl_days": _SEARCH_STORE.ttl_days,
            },
            "fsync": _FSYNC,
        }


# ---------------------------------------------------------------------------
# Back-compat shims for the test suite that mutates module globals.
# The fixture in tests/test_persistent_cache.py touches _STORE / _LOG_FH /
# _DIRTY / _LOADED / _DISABLED to reset state. Expose those names as
# proxies on the paper store so existing tests keep working.
# ---------------------------------------------------------------------------

class _ModuleGlobalsProxy:
    """Routes legacy module-global access to the paper store fields."""

    def __getattr__(self, name):
        if name == "_STORE":
            return _PAPER_STORE.data
        if name == "_LOG_FH":
            return _PAPER_STORE.log_fh
        if name == "_DIRTY":
            return _PAPER_STORE.dirty
        if name == "_LOADED":
            return _PAPER_STORE.loaded
        raise AttributeError(name)


# Expose legacy attribute names on the module via __getattr__ + setters.
def __getattr__(name):
    if name == "_STORE":
        return _PAPER_STORE.data
    if name == "_LOG_FH":
        return _PAPER_STORE.log_fh
    if name == "_DIRTY":
        return _PAPER_STORE.dirty
    if name == "_LOADED":
        return _PAPER_STORE.loaded
    if name == "_CACHE_PATH":
        return _PAPER_STORE.snapshot_path
    if name == "_LOG_PATH":
        return _PAPER_STORE.log_path
    raise AttributeError(name)


atexit.register(flush)
