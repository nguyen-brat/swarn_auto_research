from __future__ import annotations

import json

import pytest

from swarn_research_mcp.research_book import (
    MissingCitationError,
    _paper_lookup,
    resolve_paper_citation,
)


def _scaffold(tmp_path, pool_payload, ss_records=None):
    run = tmp_path / "run"
    (run / "02_paper_pool").mkdir(parents=True)
    (run / "02_paper_pool" / "paper_pool.json").write_text(json.dumps(pool_payload))
    if ss_records:
        (run / "03_overviews" / "semantic_scholar").mkdir(parents=True)
        for rec in ss_records:
            (run / "03_overviews" / "semantic_scholar" / f"{rec['arxiv_id']}.json").write_text(
                json.dumps(rec)
            )
    return run


def test_paper_lookup_handles_dict_shape(tmp_path):
    run = _scaffold(tmp_path, {"2301.02111": {"title": "VALL-E", "year": 2023}})
    assert _paper_lookup(run)["2301.02111"]["title"] == "VALL-E"


def test_paper_lookup_handles_list_shape(tmp_path):
    run = _scaffold(
        tmp_path,
        [
            {"arxiv_id": "2301.02111", "title": "VALL-E", "year": 2023},
        ],
    )
    assert _paper_lookup(run)["2301.02111"]["title"] == "VALL-E"


def test_paper_lookup_handles_papers_key_shape(tmp_path):
    run = _scaffold(
        tmp_path,
        {
            "papers": [
                {"arxiv_id": "2301.02111", "title": "VALL-E", "year": 2023},
            ]
        },
    )
    assert _paper_lookup(run)["2301.02111"]["title"] == "VALL-E"


def test_paper_lookup_falls_back_to_semantic_scholar(tmp_path):
    """List pool with no title/year; semantic_scholar provides them."""
    run = _scaffold(
        tmp_path,
        [{"arxiv_id": "2301.02111"}],
        ss_records=[{"arxiv_id": "2301.02111", "title": "VALL-E", "year": 2023}],
    )
    pool = _paper_lookup(run)
    assert pool["2301.02111"]["title"] == "VALL-E"
    assert pool["2301.02111"]["year"] == 2023


def test_resolve_paper_citation_returns_full_record(voice_lm_minimal):
    cite = resolve_paper_citation(voice_lm_minimal, "2301.02111")
    assert cite["title"] == "VALL-E: Neural Codec Language Models"
    assert cite["year"] == 2023


def test_resolve_paper_citation_raises_on_unknown_arxiv(voice_lm_minimal):
    with pytest.raises(MissingCitationError, match="9999.99999"):
        resolve_paper_citation(voice_lm_minimal, "9999.99999")


def test_resolve_paper_citation_raises_on_missing_title(tmp_path):
    run = _scaffold(tmp_path, [{"arxiv_id": "2301.02111", "year": 2023}])
    with pytest.raises(MissingCitationError, match="title"):
        resolve_paper_citation(run, "2301.02111")


def test_paper_label_raises_on_missing_title(tmp_path):
    from swarn_research_mcp.research_book import _paper_label

    pool = {"2301.02111": {"arxiv_id": "2301.02111"}}
    with pytest.raises(MissingCitationError):
        _paper_label("2301.02111", promoted={}, pool=pool)
