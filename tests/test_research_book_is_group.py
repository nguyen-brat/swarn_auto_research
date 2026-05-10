from __future__ import annotations

import json

from swarn_research_mcp.research_book import validate_research_book_run


BOOK_SECTIONS = [
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
]


def _scaffold(tmp_path):
    run = tmp_path / "run"
    for sub in ("12_taxonomy", "07_scoring", "16_book", "14_chapters/families", "14_chapters/methods", "14_chapters/book"):
        (run / sub).mkdir(parents=True, exist_ok=True)
    outline = {
        "topic": "t",
        "book_sections": BOOK_SECTIONS,
        "parts": [
            {"id": "p1", "title": "P1", "family_ids": ["fam_real"]},
            {"id": "standalone_methods", "title": "Standalone", "family_ids": ["standalone"]},
        ],
        "families": [
            {"id": "fam_real", "title": "Real Fam", "method_ids": ["m1", "m2"]},
            {"id": "standalone", "title": "Standalone / Emerging Methods", "method_ids": ["m_solo"], "is_group": True},
        ],
        "methods": [
            {"id": "m1", "title": "M1", "arxiv_id": "1.1", "family_id": "fam_real"},
            {"id": "m2", "title": "M2", "arxiv_id": "1.2", "family_id": "fam_real"},
            {"id": "m_solo", "title": "Solo", "arxiv_id": "1.3", "family_id": "standalone"},
        ],
    }
    (run / "12_taxonomy" / "outline.json").write_text(json.dumps(outline))
    (run / "07_scoring" / "promoted_papers.json").write_text(
        json.dumps({"promoted_papers": [{"arxiv_id": "1.1"}, {"arxiv_id": "1.2"}, {"arxiv_id": "1.3"}]})
    )
    (run / "16_book" / "chapters_manifest.json").write_text(
        json.dumps({"book": [], "families": ["fam_real"], "methods": ["m1", "m2", "m_solo"]})
    )
    # Real family chapter exists; standalone has NONE.
    (run / "14_chapters" / "families" / "fam_real.md").write_text(
        "---\nstatus: passed\n---\n# Real Fam\n## Summary\nx\n## Motivation\nx\n## Core Idea\nx\n"
        "## Common Pipeline\nx\n## Main Variants\n| a | b | c | d | e |\n|--|--|--|--|--|\n| 1|2|3|4|5|\n"
        "## Representative Methods\nx\n## Strengths\nx\n## Limitations\nx\n## When to Use\nx\n## Related Families\nx\n"
    )
    # method_taxonomy.md: links real family + lists solo method flat (group has no family link).
    (run / "14_chapters" / "book" / "04_method_taxonomy.md").write_text(
        "# Method Taxonomy\n## Part 1: P1\n- [Real Fam](../families/fam_real.md)\n"
        "  - [M1](../methods/m1.md)\n  - [M2](../methods/m2.md)\n"
        "## Part 2: Standalone\n- [Solo](../methods/m_solo.md)\n"
    )
    return run


def test_is_group_does_not_trigger_missing_family_chapter(tmp_path):
    run = _scaffold(tmp_path)
    issues = validate_research_book_run(run)
    assert not any(i["code"] == "missing_family_chapter" and "standalone" in i["detail"] for i in issues)


def test_is_group_does_not_trigger_missing_family_link(tmp_path):
    run = _scaffold(tmp_path)
    issues = validate_research_book_run(run)
    assert not any(
        i["code"] == "method_taxonomy_missing_family_link" and "standalone" in i["detail"]
        for i in issues
    )


def test_is_group_does_not_trigger_wrong_chapter_headings(tmp_path):
    run = _scaffold(tmp_path)
    issues = validate_research_book_run(run)
    assert not any(i["code"] == "wrong_chapter_headings" and "standalone" in i["detail"] for i in issues)
