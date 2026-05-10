from __future__ import annotations

import json

from swarn_research_mcp.research_book import (
    collect_excluded,
    generate_book_artifacts,
    validate_research_book_run,
    write_needs_review,
)


def test_collect_excluded_finds_excluded_chapters(voice_lm_minimal):
    offenders = collect_excluded(voice_lm_minimal)
    assert any(o["id"] == "m_excluded" and o["status"].startswith("excluded_") for o in offenders)


def test_collect_excluded_returns_empty_when_all_passed(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    assert collect_excluded(run) == []


def test_write_needs_review_lists_offenders(voice_lm_minimal):
    offenders = [
        {
            "type": "methods",
            "id": "m_excluded",
            "status": "excluded_unsupported_claims",
            "reason": "claims_unsupported=3",
        }
    ]
    write_needs_review(voice_lm_minimal, offenders)
    text = (voice_lm_minimal / "16_book" / "NEEDS_REVIEW.md").read_text()
    assert "m_excluded" in text
    assert "excluded_unsupported_claims" in text
    assert "claims_unsupported=3" in text


def test_generate_succeeds_with_excluded_chapters(voice_lm_minimal, monkeypatch):
    """Quarantine: excluded chapters do NOT block SUMMARY.md generation."""
    from swarn_research_mcp import research_book as rb

    op = voice_lm_minimal / "12_taxonomy" / "outline.json"
    outline = json.loads(op.read_text())
    outline["families"] = [
        {"id": "fam_flow", "title": "flow matching", "method_ids": ["m_voicebox", "m_excluded"]},
        {
            "id": "standalone",
            "title": "Standalone / Emerging Methods",
            "method_ids": ["m_valle"],
            "is_group": True,
        },
    ]
    outline["methods"][0]["family_id"] = "standalone"
    outline["parts"] = [
        {"id": "generation", "title": "Generation", "family_ids": ["fam_flow"]},
        {
            "id": "standalone_methods",
            "title": "Standalone / Emerging Methods",
            "family_ids": ["standalone"],
        },
    ]
    op.write_text(json.dumps(outline))
    monkeypatch.setattr(rb, "_paper_label", lambda aid, p, pool: f"[arxiv:{aid}] x (2024)")
    rb.generate_book_artifacts(voice_lm_minimal)

    summary = (voice_lm_minimal / "16_book" / "SUMMARY.md").read_text()
    assert "m_excluded" not in summary
    assert "m_valle" in summary

    needs = voice_lm_minimal / "16_book" / "NEEDS_REVIEW.md"
    assert needs.exists()
    assert "m_excluded" in needs.read_text()

    taxonomy_path = voice_lm_minimal / "14_chapters" / "book" / "04_method_taxonomy.md"
    taxonomy_path.write_text(
        taxonomy_path.read_text().replace("../methods/m_voicebox.md", "../methods/m_voicebox_removed.md")
    )

    issues = validate_research_book_run(voice_lm_minimal)
    missing_method_details = [
        issue["detail"] for issue in issues if issue["code"] == "method_taxonomy_missing_method_link"
    ]
    assert any("../methods/m_voicebox.md" in detail for detail in missing_method_details)
    assert not any("../methods/m_excluded.md" in detail for detail in missing_method_details)


def test_excluded_family_keeps_passed_methods_visible(tmp_path):
    """If a family chapter fails verification, passed method chapters stay reachable."""
    from swarn_research_mcp import research_book as rb

    run = tmp_path / "run"
    for sub in (
        "12_taxonomy",
        "07_scoring",
        "16_book",
        "14_chapters/families",
        "14_chapters/methods",
        "14_chapters/book",
        "06_expansion",
    ):
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
            {"id": "fam_a", "title": "Family A", "method_ids": ["m1", "m2"]},
            {"id": "fam_b", "title": "Family B", "method_ids": ["m3", "m4"]},
        ],
        "methods": [
            {"id": f"m{i}", "title": f"M{i}", "arxiv_id": f"1.{i}", "family_id": fam}
            for i, fam in [(1, "fam_a"), (2, "fam_a"), (3, "fam_b"), (4, "fam_b")]
        ],
    }
    (run / "12_taxonomy" / "outline.json").write_text(json.dumps(outline))
    (run / "07_scoring" / "promoted_papers.json").write_text(
        json.dumps({"promoted_papers": [{"arxiv_id": f"1.{i}", "title": f"M{i}", "year": 2024} for i in (1, 2, 3, 4)]})
    )
    (run / "02_paper_pool").mkdir(parents=True, exist_ok=True)
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps([{"arxiv_id": f"1.{i}", "title": f"M{i}", "year": 2024} for i in (1, 2, 3, 4)])
    )
    (run / "06_expansion" / "known_concepts_snapshot.json").write_text('{"known_concepts": []}')
    (run / "14_chapters" / "families" / "fam_a.md").write_text(
        '---\nchapter_id: fam_a\nstatus: excluded_unsupported_claims\nstatus_reason: "x"\n---\n# A\n'
    )
    (run / "14_chapters" / "families" / "fam_b.md").write_text(
        "---\nchapter_id: fam_b\nstatus: passed\n---\n# B\n"
    )
    for mid in ("m1", "m2", "m3", "m4"):
        (run / "14_chapters" / "methods" / f"{mid}.md").write_text(
            f"---\nchapter_id: {mid}\nstatus: passed\n---\n# {mid}\n"
        )

    rb.generate_book_artifacts(run)
    summary = (run / "16_book" / "SUMMARY.md").read_text()
    assert "Family A" not in summary or "../14_chapters/families/fam_a.md" not in summary
    assert "../14_chapters/methods/m1.md" in summary
    assert "../14_chapters/methods/m2.md" in summary
    assert "../14_chapters/families/fam_b.md" in summary

    issues = validate_research_book_run(run)
    missing_family_details = [
        issue["detail"] for issue in issues if issue["code"] == "method_taxonomy_missing_family_link"
    ]
    assert not any("../families/fam_a.md" in detail for detail in missing_family_details)


def test_excluded_book_section_omitted_from_summary(tmp_path):
    """If a book chapter fails verification, it is omitted from SUMMARY.md's Book list."""
    from swarn_research_mcp import research_book as rb

    run = tmp_path / "run"
    for sub in (
        "12_taxonomy",
        "07_scoring",
        "16_book",
        "14_chapters/families",
        "14_chapters/methods",
        "14_chapters/book",
        "06_expansion",
        "02_paper_pool",
    ):
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
        json.dumps({"promoted_papers": [{"arxiv_id": f"1.{i}", "title": f"M{i}", "year": 2024} for i in (1, 2, 3, 4)]})
    )
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps([{"arxiv_id": f"1.{i}", "title": f"M{i}", "year": 2024} for i in (1, 2, 3, 4)])
    )
    (run / "06_expansion" / "known_concepts_snapshot.json").write_text('{"known_concepts": []}')
    (run / "14_chapters" / "book" / "02_core_concepts.md").write_text(
        '---\nchapter_id: core_concepts\nstatus: excluded_unsupported_claims\nstatus_reason: "x"\n---\n# CC\n'
    )
    for fname, cid in [
        ("00_preface.md", "preface"),
        ("01_motivating_intro.md", "motivating_intro"),
        ("03_goals.md", "goals"),
        ("04_method_taxonomy.md", "method_taxonomy"),
        ("05_shared_examples.md", "shared_examples"),
        ("98_evaluation_outlook.md", "evaluation_outlook"),
    ]:
        (run / "14_chapters" / "book" / fname).write_text(
            f"---\nchapter_id: {cid}\nstatus: passed\n---\n# {cid}\n"
        )
    for fid in ("fam_a", "fam_b"):
        (run / "14_chapters" / "families" / f"{fid}.md").write_text(
            f"---\nchapter_id: {fid}\nstatus: passed\n---\n# {fid}\n"
        )
    for mid in ("m1", "m2", "m3", "m4"):
        (run / "14_chapters" / "methods" / f"{mid}.md").write_text(
            f"---\nchapter_id: {mid}\nstatus: passed\n---\n# {mid}\n"
        )

    rb.generate_book_artifacts(run)
    summary = (run / "16_book" / "SUMMARY.md").read_text()
    assert "02_core_concepts.md" not in summary
    needs = (run / "16_book" / "NEEDS_REVIEW.md").read_text()
    assert "core_concepts" in needs


def test_excluded_chapters_omitted_from_sidebar(voice_lm_minimal, monkeypatch):
    from swarn_research_mcp import research_book as rb

    op = voice_lm_minimal / "12_taxonomy" / "outline.json"
    outline = json.loads(op.read_text())
    outline["families"] = [
        {"id": "fam_flow", "title": "flow matching", "method_ids": ["m_voicebox", "m_excluded"]},
        {
            "id": "standalone",
            "title": "Standalone / Emerging Methods",
            "method_ids": ["m_valle"],
            "is_group": True,
        },
    ]
    outline["methods"][0]["family_id"] = "standalone"
    outline["parts"] = [
        {"id": "generation", "title": "Generation", "family_ids": ["fam_flow"]},
        {
            "id": "standalone_methods",
            "title": "Standalone / Emerging Methods",
            "family_ids": ["standalone"],
        },
    ]
    op.write_text(json.dumps(outline))
    monkeypatch.setattr(rb, "_paper_label", lambda aid, p, pool: f"[arxiv:{aid}] x (2024)")
    rb.generate_book_artifacts(voice_lm_minimal)
    sidebar = json.loads((voice_lm_minimal / "16_book" / "sidebar.json").read_text())
    titles = json.dumps(sidebar)
    assert "m_excluded" not in titles


def test_missing_citation_metadata_goes_to_needs_review(tmp_path):
    """Missing citation metadata should not block a readable book."""
    from swarn_research_mcp import research_book as rb

    run = tmp_path / "run"
    for sub in ("12_taxonomy", "07_scoring", "16_book", "14_chapters/book"):
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
    (run / "07_scoring" / "promoted_papers.json").write_text(json.dumps({"promoted_papers": [{"arxiv_id": "1.1"}]}))

    rb.generate_book_artifacts(run)

    refs = (run / "14_chapters" / "book" / "appendices" / "references.md").read_text()
    assert "[arxiv:1.1] <citation metadata missing>" in refs
    needs = (run / "16_book" / "NEEDS_REVIEW.md").read_text()
    assert "citation/1.1" in needs
    assert "missing_citation_metadata" in needs
