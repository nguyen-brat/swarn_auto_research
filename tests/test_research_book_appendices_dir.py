from __future__ import annotations

import json

from swarn_research_mcp.research_book import (
    BOOK_FILE_BY_ID,
    _build_appendices_dir,
    generate_book_artifacts,
    validate_research_book_run,
)


def test_appendices_constant_points_to_directory():
    assert BOOK_FILE_BY_ID["appendices"] == "appendices"


def test_build_appendices_dir_creates_five_files(voice_lm_minimal):
    outline = json.loads((voice_lm_minimal / "12_taxonomy" / "outline.json").read_text())
    _build_appendices_dir(voice_lm_minimal, outline)
    out = voice_lm_minimal / "14_chapters" / "book" / "appendices"
    assert out.is_dir()
    for name in ("glossary.md", "notation.md", "datasets.md", "software.md", "references.md"):
        assert (out / name).exists(), f"missing {name}"


def test_appendices_references_uses_paper_pool(voice_lm_minimal):
    outline = json.loads((voice_lm_minimal / "12_taxonomy" / "outline.json").read_text())
    _build_appendices_dir(voice_lm_minimal, outline)
    refs = (voice_lm_minimal / "14_chapters" / "book" / "appendices" / "references.md").read_text()
    assert "VALL-E" in refs
    assert "(2023)" in refs
    assert "<title unknown>" not in refs


def test_generate_book_artifacts_writes_appendices_dir(voice_lm_minimal, monkeypatch):
    from swarn_research_mcp import research_book as rb

    op = voice_lm_minimal / "12_taxonomy" / "outline.json"
    outline = json.loads(op.read_text())
    outline["parts"] = [
        {"id": "p1", "title": "P1", "family_ids": ["fam_codec"]},
        {"id": "p2", "title": "P2", "family_ids": ["fam_flow"]},
    ]
    outline = rb.merge_singletons(outline)
    op.write_text(json.dumps(outline))
    rb.generate_book_artifacts(voice_lm_minimal)
    assert (voice_lm_minimal / "14_chapters" / "book" / "appendices" / "glossary.md").exists()


def test_build_appendices_dir_records_missing_reference_issue(tmp_path):
    run = tmp_path / "run"
    for sub in ("12_taxonomy", "07_scoring", "14_chapters/book"):
        (run / sub).mkdir(parents=True, exist_ok=True)
    outline = {
        "topic": "t",
        "book_sections": [
            {"id": k, "title": k}
            for k in [
                "preface",
                "motivating_intro",
                "core_concepts",
                "goals",
                "method_taxonomy",
                "shared_examples",
                "evaluation_outlook",
                "appendices",
            ]
        ],
        "parts": [
            {"id": "p1", "title": "P1", "family_ids": ["fam_a"]},
            {"id": "p2", "title": "P2", "family_ids": ["fam_b"]},
        ],
        "families": [
            {"id": "fam_a", "title": "A", "method_ids": ["m1", "m2"]},
            {"id": "fam_b", "title": "B", "method_ids": ["m3", "m4"]},
        ],
        "methods": [
            {"id": f"m{i}", "title": f"M{i}", "arxiv_id": f"1.{i}", "family_id": fam}
            for i, fam in [(1, "fam_a"), (2, "fam_a"), (3, "fam_b"), (4, "fam_b")]
        ],
    }
    (run / "12_taxonomy" / "outline.json").write_text(json.dumps(outline))
    (run / "07_scoring" / "promoted_papers.json").write_text(
        json.dumps({"promoted_papers": [{"arxiv_id": "1.1"}]})
    )

    issues = _build_appendices_dir(run, outline)

    refs = (run / "14_chapters" / "book" / "appendices" / "references.md").read_text()
    assert "[arxiv:1.1] <citation metadata missing>" in refs
    assert issues == [
        {
            "type": "citation",
            "id": "1.1",
            "status": "missing_citation_metadata",
            "reason": "arxiv_id 1.1 not found in paper_pool / overviews / weak_evidence",
        }
    ]


def test_validator_rejects_missing_appendices_directory(voice_lm_minimal):
    issues = validate_research_book_run(voice_lm_minimal)
    codes = [i["code"] for i in issues]
    assert "missing_book_chapter" in codes
    detail = next(
        i["detail"]
        for i in issues
        if i["code"] == "missing_book_chapter" and "appendices" in i["detail"]
    )
    assert "appendices" in detail
