"""Persistent SQLite caches for Semantic Scholar."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from threading import RLock
from typing import Any


_DEFAULT_CACHE_DB = Path(__file__).resolve().parents[1] / "cache" / "s2_cache.sqlite"
_LEGACY_CACHE_PATH = os.environ.get("SWARN_S2_CACHE_PATH")
_CACHE_DB_PATH = Path(
    os.environ.get(
        "SWARN_S2_CACHE_DB",
        str(Path(_LEGACY_CACHE_PATH).with_suffix(".sqlite"))
        if _LEGACY_CACHE_PATH
        else str(_DEFAULT_CACHE_DB),
    )
)
_PAPER_TTL_DAYS = int(os.environ.get("SWARN_S2_CACHE_TTL_DAYS", "30"))
_SEARCH_TTL_DAYS = int(os.environ.get("SWARN_S2_SEARCH_TTL_DAYS", "7"))
_MAX_PAPER_ENTRIES = int(os.environ.get("SWARN_S2_CACHE_MAX_ENTRIES", "100000"))
_MAX_SEARCH_ENTRIES = int(os.environ.get("SWARN_S2_SEARCH_MAX_ENTRIES", "5000"))
_DISABLED = os.environ.get("SWARN_S2_CACHE_DISABLED", "0") == "1"

_LOCK = RLock()
_CONN: sqlite3.Connection | None = None


def _cache_error_result() -> dict:
    return {
        "backend": "sqlite",
        "disabled": False,
        "db_path": str(_CACHE_DB_PATH),
        "error": "unavailable",
        "papers": {
            "entries": 0,
            "aliases": 0,
            "ttl_days": _PAPER_TTL_DAYS,
            "max_entries": _MAX_PAPER_ENTRIES,
        },
        "searches": {
            "entries": 0,
            "ttl_days": _SEARCH_TTL_DAYS,
            "max_entries": _MAX_SEARCH_ENTRIES,
        },
    }


def _connect() -> sqlite3.Connection:
    global _CONN
    if _DISABLED:
        raise RuntimeError("S2 cache is disabled")
    with _LOCK:
        if _CONN is None:
            _CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(_CACHE_DB_PATH), timeout=30, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            _ensure_schema(conn)
            _CONN = conn
        return _CONN


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS paper_entries (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          canonical_key TEXT UNIQUE NOT NULL,
          paper_json TEXT NOT NULL,
          fetched_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS paper_aliases (
          cache_key TEXT PRIMARY KEY,
          entry_id INTEGER NOT NULL REFERENCES paper_entries(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_paper_entries_fetched_at
          ON paper_entries(fetched_at);

        CREATE INDEX IF NOT EXISTS idx_paper_aliases_entry_id
          ON paper_aliases(entry_id);

        CREATE TABLE IF NOT EXISTS search_results (
          cache_key TEXT PRIMARY KEY,
          result_json TEXT NOT NULL,
          fetched_at REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_search_results_fetched_at
          ON search_results(fetched_at);

        CREATE TABLE IF NOT EXISTS cache_meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO cache_meta(key, value) VALUES (?, ?)",
        ("schema_version", "s2_sqlite_cache_v1"),
    )
    conn.commit()


def _valid_keys(keys: list[str]) -> list[str]:
    return list(dict.fromkeys(k for k in keys if isinstance(k, str) and k))


def _canonical_key(keys: list[str], paper: dict[str, Any]) -> str:
    paper_id = paper.get("paperId")
    if isinstance(paper_id, str) and paper_id:
        return paper_id
    return keys[0]


def _ttl_cutoff(ttl_days: int) -> float:
    return time.time() - ttl_days * 86400


def _evict_papers(conn: sqlite3.Connection) -> None:
    if _MAX_PAPER_ENTRIES <= 0:
        return
    count = conn.execute("SELECT COUNT(*) FROM paper_entries").fetchone()[0]
    if count <= _MAX_PAPER_ENTRIES:
        return
    over = count - _MAX_PAPER_ENTRIES
    rows = conn.execute(
        "SELECT id FROM paper_entries ORDER BY fetched_at ASC, id ASC LIMIT ?",
        (over,),
    ).fetchall()
    conn.executemany("DELETE FROM paper_entries WHERE id = ?", [(row["id"],) for row in rows])


def _evict_searches(conn: sqlite3.Connection) -> None:
    if _MAX_SEARCH_ENTRIES <= 0:
        return
    count = conn.execute("SELECT COUNT(*) FROM search_results").fetchone()[0]
    if count <= _MAX_SEARCH_ENTRIES:
        return
    over = count - _MAX_SEARCH_ENTRIES
    conn.execute(
        """
        DELETE FROM search_results
        WHERE cache_key IN (
          SELECT cache_key FROM search_results
          ORDER BY fetched_at ASC, cache_key ASC
          LIMIT ?
        )
        """,
        (over,),
    )


def get(keys: list[str]) -> dict | None:
    if _DISABLED:
        return None
    valid_keys = _valid_keys(keys)
    if not valid_keys:
        return None
    try:
        with _LOCK:
            conn = _connect()
            for key in valid_keys:
                row = conn.execute(
                    """
                    SELECT e.paper_json
                    FROM paper_aliases a
                    JOIN paper_entries e ON e.id = a.entry_id
                    WHERE a.cache_key = ?
                      AND e.fetched_at >= ?
                    """,
                    (key, _ttl_cutoff(_PAPER_TTL_DAYS)),
                ).fetchone()
                if row is None:
                    continue
                try:
                    return json.loads(row["paper_json"])
                except json.JSONDecodeError:
                    return None
    except (OSError, sqlite3.Error):
        return None
    return None


def put(keys: list[str], paper: dict) -> None:
    if _DISABLED or not paper:
        return
    valid_keys = _valid_keys(keys)
    if not valid_keys:
        return
    try:
        with _LOCK:
            conn = _connect()
            now = time.time()
            canonical_key = _canonical_key(valid_keys, paper)
            paper_json = json.dumps(paper, ensure_ascii=False, separators=(",", ":"))
            with conn:
                conn.execute(
                    """
                    INSERT INTO paper_entries(canonical_key, paper_json, fetched_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(canonical_key) DO UPDATE SET
                      paper_json=excluded.paper_json,
                      fetched_at=excluded.fetched_at
                    """,
                    (canonical_key, paper_json, now),
                )
                entry_id = conn.execute(
                    "SELECT id FROM paper_entries WHERE canonical_key = ?",
                    (canonical_key,),
                ).fetchone()["id"]
                conn.executemany(
                    """
                    INSERT INTO paper_aliases(cache_key, entry_id)
                    VALUES (?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET entry_id=excluded.entry_id
                    """,
                    [(key, entry_id) for key in valid_keys],
                )
                _evict_papers(conn)
    except (OSError, sqlite3.Error):
        return


def get_search(key: str) -> dict | None:
    if _DISABLED or not key:
        return None
    try:
        with _LOCK:
            conn = _connect()
            row = conn.execute(
                """
                SELECT result_json
                FROM search_results
                WHERE cache_key = ?
                  AND fetched_at >= ?
                """,
                (key, _ttl_cutoff(_SEARCH_TTL_DAYS)),
            ).fetchone()
    except (OSError, sqlite3.Error):
        return None
    if row is None:
        return None
    try:
        return json.loads(row["result_json"])
    except json.JSONDecodeError:
        return None


def put_search(key: str, result: dict) -> None:
    if _DISABLED or not key or not result:
        return
    try:
        with _LOCK:
            conn = _connect()
            with conn:
                conn.execute(
                    """
                    INSERT INTO search_results(cache_key, result_json, fetched_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                      result_json=excluded.result_json,
                      fetched_at=excluded.fetched_at
                    """,
                    (key, json.dumps(result, ensure_ascii=False, separators=(",", ":")), time.time()),
                )
                _evict_searches(conn)
    except (OSError, sqlite3.Error):
        return


def flush() -> None:
    try:
        with _LOCK:
            if _CONN is not None:
                _CONN.commit()
    except sqlite3.Error:
        return


def clear() -> None:
    if _DISABLED:
        return
    try:
        with _LOCK:
            conn = _connect()
            with conn:
                conn.execute("DELETE FROM paper_aliases")
                conn.execute("DELETE FROM paper_entries")
                conn.execute("DELETE FROM search_results")
    except (OSError, sqlite3.Error):
        return


def close() -> None:
    global _CONN
    with _LOCK:
        if _CONN is not None:
            _CONN.close()
            _CONN = None


def stats() -> dict:
    if _DISABLED:
        return {
            "backend": "sqlite",
            "disabled": True,
            "db_path": str(_CACHE_DB_PATH),
            "papers": {
                "entries": 0,
                "aliases": 0,
                "ttl_days": _PAPER_TTL_DAYS,
                "max_entries": _MAX_PAPER_ENTRIES,
            },
            "searches": {
                "entries": 0,
                "ttl_days": _SEARCH_TTL_DAYS,
                "max_entries": _MAX_SEARCH_ENTRIES,
            },
        }
    with _LOCK:
        try:
            conn = _connect()
            paper_entries = conn.execute("SELECT COUNT(*) FROM paper_entries").fetchone()[0]
            paper_aliases = conn.execute("SELECT COUNT(*) FROM paper_aliases").fetchone()[0]
            search_entries = conn.execute("SELECT COUNT(*) FROM search_results").fetchone()[0]
            wal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        except (OSError, sqlite3.Error):
            return _cache_error_result()
    return {
        "backend": "sqlite",
        "disabled": False,
        "db_path": str(_CACHE_DB_PATH),
        "wal_mode": wal_mode,
        "papers": {
            "entries": paper_entries,
            "aliases": paper_aliases,
            "ttl_days": _PAPER_TTL_DAYS,
            "max_entries": _MAX_PAPER_ENTRIES,
        },
        "searches": {
            "entries": search_entries,
            "ttl_days": _SEARCH_TTL_DAYS,
            "max_entries": _MAX_SEARCH_ENTRIES,
        },
    }
