from __future__ import annotations

import json

import pytest

from swarn_research_mcp.research_book import (
    MissingCitationError,
    _paper_label,
    _paper_lookup,
    resolve_paper_citation,
)


def _promoted(run):
    return {
        paper["arxiv_id"]: paper
        for paper in json.loads((run / "07_scoring" / "promoted_papers.json").read_text())["promoted_papers"]
    }


def test_voice_lm_fixture_resolves_via_semantic_scholar(voice_lm_minimal):
    """List-shaped pool with no titles; semantic_scholar carries title/year."""
    cite = resolve_paper_citation(voice_lm_minimal, "2301.02111")
    assert "VALL-E" in cite["title"]
    assert cite["year"] == 2023


def test_paper_label_renders_full_reference_for_voice_lm(voice_lm_minimal):
    pool = _paper_lookup(voice_lm_minimal)
    promoted = _promoted(voice_lm_minimal)
    label = _paper_label("2301.02111", promoted, pool)
    assert label.startswith("[arxiv:2301.02111]")
    assert "<title unknown>" not in label
    assert "<year unknown>" not in label
    assert "(2023)" in label


def test_paper_label_failure_message_names_arxiv_id(tmp_path):
    pool = {"9999.99999": {"arxiv_id": "9999.99999"}}
    with pytest.raises(MissingCitationError, match="9999.99999"):
        _paper_label("9999.99999", promoted={}, pool=pool)
