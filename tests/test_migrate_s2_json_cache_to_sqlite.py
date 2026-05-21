from __future__ import annotations

import json
import sqlite3
import time

from scripts import migrate_s2_json_cache_to_sqlite as migrate


def test_migrates_snapshots_and_replays_journals(tmp_path):
    paper_snapshot = tmp_path / "s2_paper_details.json"
    paper_log = tmp_path / "s2_paper_details.json.log"
    search_snapshot = tmp_path / "s2_search_results.json"
    search_log = tmp_path / "s2_search_results.json.log"
    db_path = tmp_path / "s2_cache.sqlite"
    now = time.time()

    paper_snapshot.write_text(
        json.dumps(
            {
                "p1": {"paper": {"paperId": "p1", "title": "old"}, "fetched_at": now},
            }
        ),
        encoding="utf-8",
    )
    paper_log.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "keys": ["p1"],
                        "paper": {"paperId": "p1", "title": "new"},
                        "fetched_at": now + 1,
                    }
                ),
                json.dumps(
                    {
                        "keys": ["p2", "ArXiv:1234.5678"],
                        "paper": {
                            "paperId": "p2",
                            "externalIds": {"ArXiv": "1234.5678"},
                        },
                        "fetched_at": now,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    search_snapshot.write_text(
        json.dumps(
            {
                "q1": {
                    "result": {"data": [{"paperId": "s1", "title": "old"}]},
                    "fetched_at": now,
                },
            }
        ),
        encoding="utf-8",
    )
    search_log.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "keys": ["q1"],
                        "result": {"data": [{"paperId": "s1", "title": "new"}]},
                        "fetched_at": now + 1,
                    }
                ),
                json.dumps(
                    {
                        "keys": ["q2"],
                        "result": {"data": [{"paperId": "s2"}]},
                        "fetched_at": now,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = migrate.run_migration(
        paper_snapshot=paper_snapshot,
        paper_log=paper_log,
        search_snapshot=search_snapshot,
        search_log=search_log,
        db_path=db_path,
        dry_run=False,
        force=False,
        include_expired=False,
    )

    assert result.paper_entries == 2
    assert result.paper_aliases == 3
    assert result.search_entries == 2
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM paper_entries").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM paper_aliases").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM search_results").fetchone()[0] == 2
        paper_json = conn.execute(
            "SELECT paper_json FROM paper_entries WHERE canonical_key = 'p1'"
        ).fetchone()[0]
        search_json = conn.execute(
            "SELECT result_json FROM search_results WHERE cache_key = 'q1'"
        ).fetchone()[0]

    assert json.loads(paper_json)["title"] == "new"
    assert json.loads(search_json)["data"][0]["title"] == "new"


def test_corrupt_journal_line_is_skipped(tmp_path):
    paper_log = tmp_path / "s2_paper_details.json.log"
    db_path = tmp_path / "s2_cache.sqlite"
    now = time.time()
    paper_log.write_text(
        "{not-json\n"
        + json.dumps({"keys": ["p1"], "paper": {"paperId": "p1"}, "fetched_at": now})
        + "\n",
        encoding="utf-8",
    )

    result = migrate.run_migration(
        paper_snapshot=tmp_path / "missing-paper.json",
        paper_log=paper_log,
        search_snapshot=tmp_path / "missing-search.json",
        search_log=tmp_path / "missing-search.log",
        db_path=db_path,
        dry_run=False,
        force=False,
        include_expired=False,
    )

    assert result.paper_entries == 1
    assert result.skipped_records == 1


def test_dry_run_does_not_write_final_db(tmp_path):
    paper_snapshot = tmp_path / "s2_paper_details.json"
    db_path = tmp_path / "s2_cache.sqlite"
    paper_snapshot.write_text(
        json.dumps({"p1": {"paper": {"paperId": "p1"}, "fetched_at": time.time()}}),
        encoding="utf-8",
    )

    result = migrate.run_migration(
        paper_snapshot=paper_snapshot,
        paper_log=tmp_path / "missing-paper.log",
        search_snapshot=tmp_path / "missing-search.json",
        search_log=tmp_path / "missing-search.log",
        db_path=db_path,
        dry_run=True,
        force=False,
        include_expired=False,
    )

    assert result.paper_entries == 1
    assert not db_path.exists()


def test_snapshot_value_larger_than_read_chunk_migrates(tmp_path):
    paper_snapshot = tmp_path / "s2_paper_details.json"
    db_path = tmp_path / "s2_cache.sqlite"
    abstract = "x" * 70000
    paper_snapshot.write_text(
        json.dumps(
            {
                "p1": {
                    "paper": {"paperId": "p1", "abstract": abstract},
                    "fetched_at": time.time(),
                },
            }
        ),
        encoding="utf-8",
    )

    result = migrate.run_migration(
        paper_snapshot=paper_snapshot,
        paper_log=tmp_path / "missing-paper.log",
        search_snapshot=tmp_path / "missing-search.json",
        search_log=tmp_path / "missing-search.log",
        db_path=db_path,
        dry_run=False,
        force=False,
        include_expired=False,
    )

    assert result.paper_entries == 1
    assert result.skipped_records == 0
    with sqlite3.connect(db_path) as conn:
        paper_json = conn.execute("SELECT paper_json FROM paper_entries").fetchone()[0]

    assert json.loads(paper_json)["abstract"] == abstract


def test_duplicate_paper_aliases_keep_newest_detail_and_all_aliases(tmp_path):
    paper_snapshot = tmp_path / "s2_paper_details.json"
    db_path = tmp_path / "s2_cache.sqlite"
    now = time.time()
    paper_snapshot.write_text(
        json.dumps(
            {
                "p1": {
                    "paper": {"paperId": "p1", "title": "new"},
                    "fetched_at": now + 10,
                },
                "ArXiv:1234.5678": {
                    "paper": {
                        "paperId": "p1",
                        "title": "old",
                        "externalIds": {"ArXiv": "1234.5678"},
                    },
                    "fetched_at": now,
                },
            }
        ),
        encoding="utf-8",
    )

    result = migrate.run_migration(
        paper_snapshot=paper_snapshot,
        paper_log=tmp_path / "missing-paper.log",
        search_snapshot=tmp_path / "missing-search.json",
        search_log=tmp_path / "missing-search.log",
        db_path=db_path,
        dry_run=False,
        force=False,
        include_expired=False,
    )

    assert result.paper_entries == 1
    assert result.paper_aliases == 2
    with sqlite3.connect(db_path) as conn:
        paper_json = conn.execute(
            "SELECT paper_json FROM paper_entries WHERE canonical_key = 'p1'"
        ).fetchone()[0]
        aliases = {
            row[0]
            for row in conn.execute(
                """
                SELECT a.cache_key
                FROM paper_aliases a
                JOIN paper_entries e ON e.id = a.entry_id
                WHERE e.canonical_key = 'p1'
                """
            )
        }

    assert json.loads(paper_json)["title"] == "new"
    assert aliases == {"p1", "ArXiv:1234.5678"}


def test_expired_records_are_skipped_unless_included(tmp_path):
    paper_snapshot = tmp_path / "s2_paper_details.json"
    db_path = tmp_path / "s2_cache.sqlite"
    expired = time.time() - 31 * 86400
    paper_snapshot.write_text(
        json.dumps({"p1": {"paper": {"paperId": "p1"}, "fetched_at": expired}}),
        encoding="utf-8",
    )

    result = migrate.run_migration(
        paper_snapshot=paper_snapshot,
        paper_log=tmp_path / "missing-paper.log",
        search_snapshot=tmp_path / "missing-search.json",
        search_log=tmp_path / "missing-search.log",
        db_path=db_path,
        dry_run=True,
        force=False,
        include_expired=False,
    )
    included = migrate.run_migration(
        paper_snapshot=paper_snapshot,
        paper_log=tmp_path / "missing-paper.log",
        search_snapshot=tmp_path / "missing-search.json",
        search_log=tmp_path / "missing-search.log",
        db_path=db_path,
        dry_run=True,
        force=False,
        include_expired=True,
    )

    assert result.paper_entries == 0
    assert included.paper_entries == 1
