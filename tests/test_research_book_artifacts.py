from __future__ import annotations

import json
from pathlib import Path

from swarn_research_mcp.research_book import (
    BOOK_FILE_BY_ID,
    generate_book_artifacts,
    validate_research_book_run,
)


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def minimal_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "14_chapters" / "book").mkdir(parents=True)
    (run_dir / "14_chapters" / "families").mkdir(parents=True)
    (run_dir / "14_chapters" / "methods").mkdir(parents=True)
    (run_dir / "16_book").mkdir(parents=True)
    write_json(
        run_dir / "07_scoring" / "promoted_papers.json",
        {
            "promoted_papers": [
                {"arxiv_id": "1111.11111", "title": "First Method", "year": 2024},
                {"arxiv_id": "2222.22222", "title": "Second Method", "year": 2025},
            ]
        },
    )
    write_json(
        run_dir / "02_paper_pool" / "paper_pool.json",
        {
            "1111.11111": {"title": "First Method", "year": 2024},
            "2222.22222": {"title": "Second Method", "year": 2025},
        },
    )
    write_json(
        run_dir / "12_taxonomy" / "outline.json",
        {
            "topic": "long context LLM",
            "book_sections": [
                {"id": "preface", "title": "Preface"},
                {"id": "motivating_intro", "title": "Motivating Introduction"},
                {"id": "core_concepts", "title": "Core Concepts"},
                {"id": "goals", "title": "Goals"},
                {"id": "method_taxonomy", "title": "Method Taxonomy"},
                {"id": "shared_examples", "title": "Shared Examples"},
                {"id": "evaluation_outlook", "title": "Evaluation Outlook"},
                {"id": "appendices", "title": "Appendices"},
            ],
            "families": [
                {
                    "id": "sparse-attention",
                    "title": "Sparse Attention",
                    "method_ids": ["first-method", "first-method-extra"],
                    "neighbor_family_ids": [],
                },
                {
                    "id": "kv-cache",
                    "title": "KV Cache",
                    "method_ids": ["second-method", "second-method-extra"],
                    "neighbor_family_ids": [],
                },
            ],
            "methods": [
                {
                    "id": "first-method",
                    "title": "First Method",
                    "arxiv_id": "1111.11111",
                    "family_id": "sparse-attention",
                    "neighbor_method_ids": [],
                },
                {
                    "id": "second-method",
                    "title": "Second Method",
                    "arxiv_id": "2222.22222",
                    "family_id": "kv-cache",
                    "neighbor_method_ids": [],
                },
                {
                    "id": "first-method-extra",
                    "title": "First Method Extra",
                    "arxiv_id": "3333.33333",
                    "family_id": "sparse-attention",
                    "neighbor_method_ids": [],
                },
                {
                    "id": "second-method-extra",
                    "title": "Second Method Extra",
                    "arxiv_id": "4444.44444",
                    "family_id": "kv-cache",
                    "neighbor_method_ids": [],
                },
            ],
            "parts": [
                {"id": "attention", "title": "Attention", "family_ids": ["sparse-attention"]},
                {"id": "memory", "title": "Memory", "family_ids": ["kv-cache"]},
            ],
        },
    )
    for section_id, filename in BOOK_FILE_BY_ID.items():
        if section_id == "appendices":
            for name in ("glossary.md", "notation.md", "datasets.md", "software.md", "references.md"):
                (run_dir / "14_chapters" / "book" / filename / name).parent.mkdir(
                    parents=True, exist_ok=True
                )
                (run_dir / "14_chapters" / "book" / filename / name).write_text(
                    f"# {name}\n", encoding="utf-8"
                )
            continue
        (run_dir / "14_chapters" / "book" / filename).write_text(
            f"# {section_id}\n", encoding="utf-8"
        )
    for family_id in ("sparse-attention", "kv-cache"):
        (run_dir / "14_chapters" / "families" / f"{family_id}.md").write_text(
            f"# {family_id}\n", encoding="utf-8"
        )
    for method_id in ("first-method", "second-method", "first-method-extra", "second-method-extra"):
        (run_dir / "14_chapters" / "methods" / f"{method_id}.md").write_text(
            f"# {method_id}\n", encoding="utf-8"
        )
    write_json(
        run_dir / "16_book" / "chapters_manifest.json",
        {
            "run_id": "run",
            "topic": "long context LLM",
            "chapters": [
                {
                    "chapter_id": "preface",
                    "chapter_type": "book",
                    "title": "Preface",
                    "file": "14_chapters/book/00_preface.md",
                    "status": "passed",
                },
                {
                    "chapter_id": "method_taxonomy",
                    "chapter_type": "book",
                    "title": "Method Taxonomy",
                    "file": "14_chapters/book/04_method_taxonomy.md",
                    "status": "passed",
                },
                {
                    "chapter_id": "appendices",
                    "chapter_type": "book",
                    "title": "Appendices",
                    "file": "14_chapters/book/appendices",
                    "status": "passed",
                },
                {
                    "chapter_id": "sparse-attention",
                    "chapter_type": "family",
                    "title": "Sparse Attention",
                    "file": "14_chapters/families/sparse-attention.md",
                    "status": "passed",
                    "method_ids": ["first-method"],
                },
                {
                    "chapter_id": "kv-cache",
                    "chapter_type": "family",
                    "title": "KV Cache",
                    "file": "14_chapters/families/kv-cache.md",
                    "status": "passed",
                    "method_ids": ["second-method"],
                },
                {
                    "chapter_id": "first-method",
                    "chapter_type": "method",
                    "title": "First Method",
                    "file": "14_chapters/methods/first-method.md",
                    "status": "passed",
                    "arxiv_id": "1111.11111",
                    "family_id": "sparse-attention",
                },
                {
                    "chapter_id": "second-method",
                    "chapter_type": "method",
                    "title": "Second Method",
                    "file": "14_chapters/methods/second-method.md",
                    "status": "excluded_form_issues",
                    "arxiv_id": "2222.22222",
                    "family_id": "kv-cache",
                },
            ],
        },
    )
    return run_dir


def test_validate_research_book_run_reports_contract_issues(tmp_path: Path):
    run_dir = minimal_run(tmp_path)
    outline = json.loads((run_dir / "12_taxonomy" / "outline.json").read_text())
    outline["families"].append(
        {
            "id": "full-attention-copy",
            "title": "Sparse Attention",
            "method_ids": [],
            "neighbor_family_ids": [],
        }
    )
    outline["methods"] = outline["methods"][:1]
    write_json(run_dir / "12_taxonomy" / "outline.json", outline)
    (run_dir / "14_chapters" / "book" / "04_method_taxonomy.md").write_text(
        "# Method Taxonomy\n\n[Sparse Attention](../families/sparse-attention.md)\n",
        encoding="utf-8",
    )
    (run_dir / "14_chapters" / "book" / "appendices" / "references.md").write_text(
        "# References\n\n- [arxiv:1111.11111] First Method (2024)\n", encoding="utf-8"
    )

    issues = validate_research_book_run(run_dir)

    codes = {issue["code"] for issue in issues}
    assert "promoted_paper_without_method" in codes
    assert "duplicate_family_title" in codes
    assert "method_taxonomy_missing_family_link" in codes


def test_validate_research_book_run_normalizes_family_title_punctuation(tmp_path: Path):
    run_dir = minimal_run(tmp_path)
    outline = json.loads((run_dir / "12_taxonomy" / "outline.json").read_text())
    outline["families"][1]["title"] = "Sparse-Attention"
    write_json(run_dir / "12_taxonomy" / "outline.json", outline)

    issues = validate_research_book_run(run_dir)

    assert "duplicate_family_title" in {issue["code"] for issue in issues}


def test_validate_research_book_run_requires_each_promoted_paper_once(tmp_path: Path):
    run_dir = minimal_run(tmp_path)
    outline = json.loads((run_dir / "12_taxonomy" / "outline.json").read_text())
    outline["methods"].append(
        {
            "id": "second-method-copy",
            "title": "Second Method Copy",
            "arxiv_id": "2222.22222",
            "family_id": "kv-cache",
            "neighbor_method_ids": [],
        }
    )
    write_json(run_dir / "12_taxonomy" / "outline.json", outline)

    issues = validate_research_book_run(run_dir)

    assert "promoted_paper_with_multiple_methods" in {issue["code"] for issue in issues}


def test_validate_research_book_run_reports_noisy_family_and_section_heading_method_id(
    tmp_path: Path,
):
    run_dir = minimal_run(tmp_path)
    outline = json.loads((run_dir / "12_taxonomy" / "outline.json").read_text())
    outline["families"][0]["title"] = "TidalDecode reports up to 5.56x speed-up."
    outline["methods"][0]["id"] = "2-related-work-and-problem-formulation"
    write_json(run_dir / "12_taxonomy" / "outline.json", outline)

    issues = validate_research_book_run(run_dir)

    codes = {issue["code"] for issue in issues}
    assert "noisy_family_title" in codes
    assert "section_heading_method_id" in codes


def test_validate_research_book_run_allows_evaluation_benchmark_family_title(
    tmp_path: Path,
):
    run_dir = minimal_run(tmp_path)
    outline = json.loads((run_dir / "12_taxonomy" / "outline.json").read_text())
    outline["families"][0]["title"] = "Evaluation and Benchmarks"
    write_json(run_dir / "12_taxonomy" / "outline.json", outline)

    issues = validate_research_book_run(run_dir)

    assert "noisy_family_title" not in {issue["code"] for issue in issues}


def test_validate_research_book_run_requires_method_family_consistency(tmp_path: Path):
    run_dir = minimal_run(tmp_path)
    outline = json.loads((run_dir / "12_taxonomy" / "outline.json").read_text())
    outline["methods"][0]["family_id"] = "missing-family"
    outline["families"][1]["method_ids"].append("first-method")
    outline["families"][1]["method_ids"].append("missing-method")
    write_json(run_dir / "12_taxonomy" / "outline.json", outline)

    issues = validate_research_book_run(run_dir)

    codes = {issue["code"] for issue in issues}
    assert "method_family_id_missing" in codes
    assert "method_listed_in_multiple_families" in codes
    assert "family_references_missing_method" in codes


def test_validate_research_book_run_requires_complete_markdown_and_taxonomy_links(
    tmp_path: Path,
):
    run_dir = minimal_run(tmp_path)
    (run_dir / "14_chapters" / "book" / "04_method_taxonomy.md").write_text(
        "# Method Taxonomy\n\n[Sparse Attention](../families/sparse-attention.md)\n",
        encoding="utf-8",
    )
    (run_dir / "14_chapters" / "methods" / "second-method.md").unlink()

    issues = validate_research_book_run(run_dir)

    codes = {issue["code"] for issue in issues}
    assert "method_taxonomy_missing_method_link" in codes
    assert "missing_method_chapter" in codes


def test_validate_research_book_run_rejects_empty_method_pack_and_thin_method_chapter(
    tmp_path: Path,
):
    run_dir = minimal_run(tmp_path)
    write_json(
        run_dir / "13_chapter_packs" / "methods" / "first-method_pack.json",
        {
            "pack_type": "method",
            "method_id": "first-method",
            "arxiv_id": "1111.11111",
            "section_plan": [],
            "structured": {"equations": [], "algorithms": [], "hyperparameters": []},
        },
    )
    (run_dir / "14_chapters" / "methods" / "first-method.md").write_text(
        "# First Method\n\n## Summary\n\nToo thin.\n",
        encoding="utf-8",
    )

    issues = validate_research_book_run(run_dir)

    codes = {issue["code"] for issue in issues}
    assert "method_pack_missing_required_section_text" in codes
    assert "method_chapter_word_count_low" in codes


def test_validate_research_book_run_rejects_thin_family_chapter_marked_passed(
    tmp_path: Path,
):
    run_dir = minimal_run(tmp_path)
    (run_dir / "14_chapters" / "families" / "sparse-attention.md").write_text(
        "# Sparse Attention\n\nThis is only a placeholder.\n",
        encoding="utf-8",
    )

    issues = validate_research_book_run(run_dir)

    assert "family_chapter_word_count_low" in {issue["code"] for issue in issues}


def test_validate_research_book_run_rejects_passed_manifest_with_thin_chapter(
    tmp_path: Path,
):
    run_dir = minimal_run(tmp_path)
    manifest = json.loads((run_dir / "16_book" / "chapters_manifest.json").read_text())
    manifest["chapters"][-1]["status"] = "passed"
    manifest["chapters"][-1]["word_count"] = 259
    write_json(run_dir / "16_book" / "chapters_manifest.json", manifest)
    (run_dir / "14_chapters" / "methods" / "second-method.md").write_text(
        "# Second Method\n\n## Summary\n\nStill too thin.\n",
        encoding="utf-8",
    )

    issues = validate_research_book_run(run_dir)

    assert "passed_method_chapter_word_count_low" in {issue["code"] for issue in issues}


def test_generate_book_artifacts_writes_complete_navigation_and_appendices(tmp_path: Path):
    run_dir = minimal_run(tmp_path)

    result = generate_book_artifacts(run_dir)

    taxonomy = (run_dir / "14_chapters" / "book" / "04_method_taxonomy.md").read_text(
        encoding="utf-8"
    )
    references = (run_dir / "14_chapters" / "book" / "appendices" / "references.md").read_text(
        encoding="utf-8"
    )
    summary = (run_dir / "16_book" / "SUMMARY.md").read_text(encoding="utf-8")
    sidebar = json.loads((run_dir / "16_book" / "sidebar.json").read_text())

    assert result["families"] == 2
    assert result["methods"] == 4
    assert "[Sparse Attention](../families/sparse-attention.md)" in taxonomy
    assert "[Second Method](../methods/second-method.md)" in taxonomy
    assert "[arxiv:1111.11111] First Method (2024)" in references
    assert "[arxiv:2222.22222] Second Method (2025)" in references
    assert "- [KV Cache](../14_chapters/families/kv-cache.md)" in summary
    assert sidebar["items"][2]["children"][0]["title"] == "KV Cache"


def test_summary_method_label_includes_slug_when_title_and_id_differ(tmp_path: Path):
    run_dir = minimal_run(tmp_path)
    outline = json.loads((run_dir / "12_taxonomy" / "outline.json").read_text())
    outline["methods"][0]["title"] = "Attention Routing"
    write_json(run_dir / "12_taxonomy" / "outline.json", outline)

    generate_book_artifacts(run_dir)

    summary = (run_dir / "16_book" / "SUMMARY.md").read_text(encoding="utf-8")
    assert "- [Attention Routing (first-method)](../14_chapters/methods/first-method.md)" in summary
    assert "../14_chapters/methods/attention-routing.md" not in summary


def test_sidebar_method_label_includes_slug_when_title_and_id_differ(tmp_path: Path):
    run_dir = minimal_run(tmp_path)
    outline = json.loads((run_dir / "12_taxonomy" / "outline.json").read_text())
    outline["methods"][0]["title"] = "Attention Routing"
    write_json(run_dir / "12_taxonomy" / "outline.json", outline)

    generate_book_artifacts(run_dir)

    sidebar = json.loads((run_dir / "16_book" / "sidebar.json").read_text())
    method_item = sidebar["items"][1]["children"][0]["children"][0]
    assert method_item == {
        "title": "Attention Routing (first-method)",
        "path": "14_chapters/methods/first-method.md",
    }


def test_generate_book_artifacts_resolves_titles_from_semantic_scholar(tmp_path: Path):
    run_dir = minimal_run(tmp_path)
    write_json(
        run_dir / "07_scoring" / "promoted_papers.json",
        {"promoted_papers": [{"arxiv_id": "1111.11111"}]},
    )
    write_json(run_dir / "02_paper_pool" / "paper_pool.json", {"1111.11111": {}})
    write_json(
        run_dir / "03_overviews" / "semantic_scholar" / "1111.11111.json",
        {"arxiv_id": "1111.11111", "title": "Semantic Scholar Title", "year": 2026},
    )

    generate_book_artifacts(run_dir)

    references = (run_dir / "14_chapters" / "book" / "appendices" / "references.md").read_text(
        encoding="utf-8"
    )
    assert "[arxiv:1111.11111] Semantic Scholar Title (2026)" in references


def test_summary_groups_families_under_parts(voice_lm_minimal, monkeypatch):
    from swarn_research_mcp import research_book as rb

    op = voice_lm_minimal / "12_taxonomy" / "outline.json"
    outline = json.loads(op.read_text())
    outline["families"] = [
        {"id": "fam_flow", "title": "flow matching", "method_ids": ["m_voicebox", "m_excluded", "m_valle"]},
        {"id": "fam_codec_b", "title": "discrete codec B", "method_ids": ["m_b1", "m_b2"]},
    ]
    outline["methods"].extend(
        [
            {"id": "m_b1", "title": "B1", "arxiv_id": "0009.0001", "family_id": "fam_codec_b"},
            {"id": "m_b2", "title": "B2", "arxiv_id": "0009.0002", "family_id": "fam_codec_b"},
        ]
    )
    outline["methods"][0]["family_id"] = "fam_flow"
    outline["parts"] = [
        {"id": "generation", "title": "Generation", "family_ids": ["fam_flow"]},
        {"id": "tokenization", "title": "Tokenization", "family_ids": ["fam_codec_b"]},
    ]
    op.write_text(json.dumps(outline))
    monkeypatch.setattr(rb, "_paper_label", lambda aid, p, pool: f"[arxiv:{aid}] x (2024)")
    rb.generate_book_artifacts(voice_lm_minimal)
    summary = (voice_lm_minimal / "16_book" / "SUMMARY.md").read_text()
    assert "## Part 1: Generation" in summary
    assert "## Part 2: Tokenization" in summary
    assert summary.index("## Part 1: Generation") < summary.index("flow matching")
    assert summary.index("flow matching") < summary.index("## Part 2: Tokenization")


def test_sidebar_groups_families_under_parts(voice_lm_minimal, monkeypatch):
    from swarn_research_mcp import research_book as rb

    op = voice_lm_minimal / "12_taxonomy" / "outline.json"
    outline = json.loads(op.read_text())
    outline["families"] = [
        {"id": "fam_flow", "title": "flow matching", "method_ids": ["m_voicebox", "m_excluded", "m_valle"]},
        {"id": "fam_codec_b", "title": "discrete codec B", "method_ids": ["m_b1", "m_b2"]},
    ]
    outline["methods"].extend(
        [
            {"id": "m_b1", "title": "B1", "arxiv_id": "0009.0001", "family_id": "fam_codec_b"},
            {"id": "m_b2", "title": "B2", "arxiv_id": "0009.0002", "family_id": "fam_codec_b"},
        ]
    )
    outline["methods"][0]["family_id"] = "fam_flow"
    outline["parts"] = [
        {"id": "generation", "title": "Generation", "family_ids": ["fam_flow"]},
        {"id": "tokenization", "title": "Tokenization", "family_ids": ["fam_codec_b"]},
    ]
    op.write_text(json.dumps(outline))
    monkeypatch.setattr(rb, "_paper_label", lambda aid, p, pool: f"[arxiv:{aid}] x (2024)")
    rb.generate_book_artifacts(voice_lm_minimal)
    sidebar = json.loads((voice_lm_minimal / "16_book" / "sidebar.json").read_text())
    titles = [item["title"] for item in sidebar["items"]]
    assert "Generation" in titles
    assert "Tokenization" in titles
