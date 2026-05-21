from __future__ import annotations

import json
from pathlib import Path

from scripts.auto_research_runner.paper_pool import (
    load_final_candidate_promoted_arxiv_ids,
    read_promoted_arxiv_ids,
)
from scripts.auto_research_runner.validation import normalize_outline_to_verified_papers


BOOK_SECTIONS = [
    {"id": "preface", "title": "Preface"},
    {"id": "motivating_intro", "title": "Motivating Introduction"},
    {"id": "core_concepts", "title": "Core Concepts"},
    {"id": "goals", "title": "Goals"},
    {"id": "method_taxonomy", "title": "Method Taxonomy"},
    {"id": "shared_examples", "title": "Shared Examples"},
    {"id": "evaluation_outlook", "title": "Evaluation Outlook"},
    {"id": "appendices", "title": "Appendices"},
]


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_promoted(run_dir: Path, arxiv_ids: list[str]) -> None:
    _write_json(
        run_dir / "07_scoring" / "promoted_papers.json",
        {"promoted_papers": [{"arxiv_id": arxiv_id} for arxiv_id in arxiv_ids]},
    )


def _write_verified_fulltext(run_dir: Path, arxiv_id: str, *, title: str) -> None:
    (run_dir / "08_full_markdown").mkdir(parents=True, exist_ok=True)
    (run_dir / "08_full_markdown" / f"{arxiv_id}.md").write_text(f"# {title}\n", encoding="utf-8")
    _write_json(
        run_dir / "09_pageindex" / "trees" / f"{arxiv_id}.tree.json",
        {
            "root": {
                "id": "s.00",
                "title": "(root)",
                "children": [
                    {
                        "id": "s.01",
                        "title": title,
                        "level": 1,
                        "start_line": 1,
                        "end_line": 1,
                        "parent_id": "s.00",
                        "summary": title,
                        "children": [],
                    }
                ],
            }
        },
    )
    _write_json(
        run_dir / "09_pageindex" / "nodes" / f"{arxiv_id}.nodes.json",
        {
            "s.01": {
                "id": "s.01",
                "title": title,
                "level": 1,
                "start_line": 1,
                "end_line": 1,
                "parent_id": "s.00",
                "summary": title,
            }
        },
    )
    _write_json(
        run_dir / "10_verified_evidence" / f"{arxiv_id}.json",
        {"claims": [{"source_node_id": "s.01", "source_lines": [1]}]},
    )


def test_final_candidate_loader_excludes_surveys_but_keeps_code_review(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_promoted(run_dir, ["2501.00001", "2501.00002"])
    _write_verified_fulltext(run_dir, "2501.00001", title="A Survey of Coding Agents")
    _write_verified_fulltext(run_dir, "2501.00002", title="Code Review Agent Benchmark")
    _write_json(
        run_dir / "03_overviews" / "semantic_scholar" / "2501.00001.json",
        {"arxiv_id": "2501.00001", "title": "A Survey of Coding Agents", "year": 2025},
    )
    _write_json(
        run_dir / "03_overviews" / "semantic_scholar" / "2501.00002.json",
        {"arxiv_id": "2501.00002", "title": "Code Review Agent Benchmark", "year": 2025},
    )

    assert read_promoted_arxiv_ids(run_dir) == ["2501.00001", "2501.00002"]
    assert load_final_candidate_promoted_arxiv_ids(run_dir) == ["2501.00002"]


def test_stage_12_normalization_drops_surveys_and_canonicalizes_placeholder_ids(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_promoted(run_dir, ["2509.06216", "2504.19678"])
    _write_verified_fulltext(
        run_dir,
        "2509.06216",
        title="Agentic Software Engineering: Foundational Pillars and a Research Roadmap",
    )
    _write_verified_fulltext(
        run_dir,
        "2504.19678",
        title="From LLM Reasoning to Autonomous AI Agents: A Comprehensive Review",
    )
    _write_json(
        run_dir / "03_overviews" / "semantic_scholar" / "2509.06216.json",
        {
            "arxiv_id": "2509.06216",
            "title": "Agentic Software Engineering: Foundational Pillars and a Research Roadmap",
            "year": 2025,
        },
    )
    _write_json(
        run_dir / "03_overviews" / "semantic_scholar" / "2504.19678.json",
        {
            "arxiv_id": "2504.19678",
            "title": "From LLM Reasoning to Autonomous AI Agents: A Comprehensive Review",
            "year": 2025,
        },
    )
    _write_json(
        run_dir / "12_taxonomy" / "outline.json",
        {
            "book_sections": BOOK_SECTIONS,
            "families": [
                {
                    "id": "agentic-se",
                    "title": "Agentic SE",
                    "method_ids": ["method-2509-06216", "survey-review"],
                }
            ],
            "methods": [
                {
                    "id": "method-2509-06216",
                    "title": "2509.06216",
                    "arxiv_id": "2509.06216",
                    "family_id": "agentic-se",
                    "neighbor_method_ids": ["survey-review"],
                },
                {
                    "id": "survey-review",
                    "title": "From LLM Reasoning to Autonomous AI Agents: A Comprehensive Review",
                    "arxiv_id": "2504.19678",
                    "family_id": "agentic-se",
                    "neighbor_method_ids": ["method-2509-06216"],
                },
            ],
        },
    )

    stats = normalize_outline_to_verified_papers(run_dir)

    outline = json.loads((run_dir / "12_taxonomy" / "outline.json").read_text(encoding="utf-8"))
    assert stats["dropped_context_only_methods"] == 1
    assert outline["methods"] == [
        {
            "arxiv_id": "2509.06216",
            "family_id": "agentic-se",
            "id": "agentic-software-engineering-foundational-pillars-and-a-research-roadmap",
            "knowledge_gaps_to_explain": [],
            "known_concepts_assumed": [],
            "neighbor_method_ids": [],
            "title": "Agentic Software Engineering: Foundational Pillars and a Research Roadmap",
        }
    ]
    assert outline["families"][0]["method_ids"] == [
        "agentic-software-engineering-foundational-pillars-and-a-research-roadmap"
    ]
