from __future__ import annotations

import json

import pytest

from swarn_research_mcp.research_book import merge_singletons


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


def _outline(families, methods, parts=None):
    return {
        "topic": "t",
        "book_sections": BOOK_SECTIONS,
        "families": families,
        "methods": methods,
        "parts": parts
        or [
            {"id": "p1", "title": "P1", "family_ids": [f["id"] for f in families]},
            {"id": "p2", "title": "P2", "family_ids": []},
        ],
    }


def test_singleton_with_strong_evidence_merges():
    """Two shared neighbor methods OR (neighbor_family_id + one shared method) triggers merge."""
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["m1"], "neighbor_family_ids": ["fam_b"]},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"], "neighbor_family_ids": ["fam_a"]},
    ]
    methods = [
        # m1 has 2 shared neighbors in fam_b -> strong evidence -> merge.
        {"id": "m1", "arxiv_id": "1.1", "family_id": "fam_a", "neighbor_method_ids": ["m2", "m3"]},
        {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b", "neighbor_method_ids": ["m1", "m3"]},
        {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b", "neighbor_method_ids": ["m2"]},
    ]
    merged = merge_singletons(_outline(families, methods))
    family_by_id = {f["id"]: f for f in merged["families"]}
    assert "fam_a" not in family_by_id
    assert sorted(family_by_id["fam_b"]["method_ids"]) == ["m1", "m2", "m3"]


def test_singleton_with_weak_evidence_goes_to_standalone():
    """1 shared neighbor without neighbor_family link -> weak -> standalone."""
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["m1"], "neighbor_family_ids": []},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"], "neighbor_family_ids": []},
    ]
    methods = [
        {"id": "m1", "arxiv_id": "1.1", "family_id": "fam_a", "neighbor_method_ids": ["m2"]},
        {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b", "neighbor_method_ids": ["m1", "m3"]},
        {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b", "neighbor_method_ids": ["m2"]},
    ]
    merged = merge_singletons(_outline(families, methods))
    family_by_id = {f["id"]: f for f in merged["families"]}
    assert "fam_a" not in family_by_id
    standalone = family_by_id["standalone"]
    assert standalone["is_group"] is True
    assert standalone["method_ids"] == ["m1"]
    parts_by_id = {p["id"]: p for p in merged["parts"]}
    assert "standalone" in parts_by_id["standalone_methods"]["family_ids"]


def test_singleton_with_no_evidence_goes_to_standalone():
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["m1"], "neighbor_family_ids": []},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"], "neighbor_family_ids": []},
    ]
    methods = [
        {"id": "m1", "arxiv_id": "1.1", "family_id": "fam_a", "neighbor_method_ids": []},
        {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b", "neighbor_method_ids": ["m3"]},
        {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b", "neighbor_method_ids": ["m2"]},
    ]
    merged = merge_singletons(_outline(families, methods))
    standalone = next(f for f in merged["families"] if f["id"] == "standalone")
    assert standalone["method_ids"] == ["m1"]


def test_method_family_id_updated_to_winner():
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["m1"], "neighbor_family_ids": ["fam_b"]},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"], "neighbor_family_ids": ["fam_a"]},
    ]
    methods = [
        {"id": "m1", "arxiv_id": "1.1", "family_id": "fam_a", "neighbor_method_ids": ["m2", "m3"]},
        {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b", "neighbor_method_ids": ["m1"]},
        {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b", "neighbor_method_ids": []},
    ]
    merged = merge_singletons(_outline(families, methods))
    method_by_id = {m["id"]: m for m in merged["methods"]}
    assert method_by_id["m1"]["family_id"] == "fam_b"


def test_singleton_picks_candidate_with_more_shared_neighbors():
    """If multiple candidates pass, choose the strongest graph evidence, not first id."""
    families = [
        {"id": "fam_single", "title": "Single", "method_ids": ["m1"], "neighbor_family_ids": []},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"], "neighbor_family_ids": []},
        {"id": "fam_c", "title": "C", "method_ids": ["m4", "m5", "m6"], "neighbor_family_ids": []},
    ]
    methods = [
        {
            "id": "m1",
            "arxiv_id": "1.1",
            "family_id": "fam_single",
            "neighbor_method_ids": ["m2", "m3", "m4", "m5", "m6"],
        },
        {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b"},
        {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b"},
        {"id": "m4", "arxiv_id": "1.4", "family_id": "fam_c"},
        {"id": "m5", "arxiv_id": "1.5", "family_id": "fam_c"},
        {"id": "m6", "arxiv_id": "1.6", "family_id": "fam_c"},
    ]
    merged = merge_singletons(_outline(families, methods))
    method_by_id = {m["id"]: m for m in merged["methods"]}
    family_by_id = {f["id"]: f for f in merged["families"]}
    assert method_by_id["m1"]["family_id"] == "fam_c"
    assert "m1" in family_by_id["fam_c"]["method_ids"]
    assert "m1" not in family_by_id["fam_b"]["method_ids"]


def test_no_op_when_all_families_have_two_methods():
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["m1", "m2"]},
        {"id": "fam_b", "title": "B", "method_ids": ["m3", "m4"]},
    ]
    methods = [
        {"id": f"m{i}", "arxiv_id": f"1.{i}", "family_id": fam}
        for i, fam in [(1, "fam_a"), (2, "fam_a"), (3, "fam_b"), (4, "fam_b")]
    ]
    before = _outline(families, methods)
    after = merge_singletons(before)
    assert after == before


def test_assert_no_singletons_raises_on_unmerged_outline():
    from swarn_research_mcp.research_book import assert_no_singletons

    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["m1"]},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"]},
    ]
    methods = [
        {"id": "m1", "arxiv_id": "1.1", "family_id": "fam_a"},
        {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b"},
        {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b"},
    ]
    with pytest.raises(RuntimeError, match="singleton"):
        assert_no_singletons(_outline(families, methods))


def test_merge_prunes_empty_parts():
    """If a singleton was the only family in its part, the empty part is pruned."""
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["m1"], "neighbor_family_ids": ["fam_b"]},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"], "neighbor_family_ids": ["fam_a"]},
    ]
    methods = [
        {"id": "m1", "arxiv_id": "1.1", "family_id": "fam_a", "neighbor_method_ids": ["m2", "m3"]},
        {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b", "neighbor_method_ids": ["m1"]},
        {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b", "neighbor_method_ids": ["m1"]},
    ]
    parts = [
        {"id": "p_lone", "title": "Lone", "family_ids": ["fam_a"]},
        {"id": "p_main", "title": "Main", "family_ids": ["fam_b"]},
    ]
    merged = merge_singletons(_outline(families, methods, parts))
    part_ids = {p["id"] for p in merged["parts"]}
    assert "p_lone" not in part_ids  # pruned (was empty after merge)
    assert "p_main" in part_ids


def test_standalone_part_does_not_count_against_5_cap():
    """6 total parts is OK iff one of them is standalone_methods."""
    from swarn_research_mcp.research_book import _validate_parts

    families = [
        {"id": f"fam_{c}", "title": c, "method_ids": [f"m_{c}1", f"m_{c}2"]} for c in "abcde"
    ] + [{"id": "standalone", "title": "Standalone", "method_ids": ["m_solo"], "is_group": True}]
    parts = [{"id": f"p{i}", "title": f"P{i}", "family_ids": [f"fam_{c}"]} for i, c in enumerate("abcde", 1)]
    parts.append({"id": "standalone_methods", "title": "Standalone", "family_ids": ["standalone"]})
    outline = {"parts": parts}
    issues = _validate_parts(outline, families)
    assert not any(i["code"] == "parts_count_out_of_range" for i in issues)


def test_assert_no_singletons_allows_standalone_group_with_one_method():
    from swarn_research_mcp.research_book import assert_no_singletons

    families = [
        {"id": "standalone", "title": "Standalone / Emerging Methods", "method_ids": ["m1"], "is_group": True},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"]},
    ]
    methods = [
        {"id": "m1", "arxiv_id": "1.1", "family_id": "standalone"},
        {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b"},
        {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b"},
    ]
    assert_no_singletons(_outline(families, methods))  # no raise


def test_cli_normalize_outline(voice_lm_minimal, capsys, monkeypatch):
    """Stage 12.5 CLI: --normalize-outline merges singletons and rewrites outline.json."""
    from swarn_research_mcp import research_book as rb

    op = voice_lm_minimal / "12_taxonomy" / "outline.json"
    monkeypatch.setattr("sys.argv", ["research_book", str(voice_lm_minimal), "--normalize-outline"])
    rb.main()
    after = json.loads(op.read_text())
    fids = {f["id"] for f in after["families"]}
    assert "fam_codec" not in fids  # singleton fam_codec merged into fam_flow


def test_generate_book_artifacts_asserts_unnormalized_outline(voice_lm_minimal, monkeypatch):
    """generate_book_artifacts MUST refuse to render a non-normalized outline."""
    from swarn_research_mcp import research_book as rb

    op = voice_lm_minimal / "12_taxonomy" / "outline.json"
    outline = json.loads(op.read_text())
    outline["parts"] = [
        {"id": "p1", "title": "P1", "family_ids": ["fam_codec"]},
        {"id": "p2", "title": "P2", "family_ids": ["fam_flow"]},
    ]
    op.write_text(json.dumps(outline))
    with pytest.raises(RuntimeError, match="singleton"):
        rb.generate_book_artifacts(voice_lm_minimal)
