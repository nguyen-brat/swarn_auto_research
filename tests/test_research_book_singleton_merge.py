from __future__ import annotations

import json
import multiprocessing as mp

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


def test_merge_singletons_preserves_two_normal_parts_when_all_singletons_match_one_family():
    families = [
        {"id": "fam_main", "title": "Main", "method_ids": ["m_a1", "m_a2"]},
        {"id": "fam_audio", "title": "Audio", "method_ids": ["m_audio"]},
        {"id": "fam_dialogue", "title": "Dialogue", "method_ids": ["m_dialogue"]},
        {"id": "fam_eval", "title": "Evaluation", "method_ids": ["m_eval"]},
    ]
    methods = [
        {"id": "m_a1", "arxiv_id": "1.1", "family_id": "fam_main"},
        {"id": "m_a2", "arxiv_id": "1.2", "family_id": "fam_main"},
        {
            "id": "m_audio",
            "arxiv_id": "1.3",
            "family_id": "fam_audio",
            "neighbor_method_ids": ["m_a1", "m_a2"],
        },
        {
            "id": "m_dialogue",
            "arxiv_id": "1.4",
            "family_id": "fam_dialogue",
            "neighbor_method_ids": ["m_a1", "m_a2"],
        },
        {
            "id": "m_eval",
            "arxiv_id": "1.5",
            "family_id": "fam_eval",
            "neighbor_method_ids": ["m_a1", "m_a2"],
        },
    ]
    parts = [
        {"id": "p_main", "title": "Main", "family_ids": ["fam_main"]},
        {"id": "p_audio", "title": "Audio", "family_ids": ["fam_audio"]},
        {"id": "p_dialogue", "title": "Dialogue", "family_ids": ["fam_dialogue"]},
        {"id": "p_eval", "title": "Evaluation", "family_ids": ["fam_eval"]},
    ]

    merged = merge_singletons(_outline(families, methods, parts))

    normal_parts = [part for part in merged["parts"] if part["id"] != "standalone_methods"]
    assert len(normal_parts) >= 2
    normal_families = [family for family in merged["families"] if family["id"] != "standalone"]
    assert all(len(family["method_ids"]) != 1 for family in normal_families)
    assert any(set(family["method_ids"]) >= {"m_dialogue", "m_eval"} for family in normal_families)


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


def test_merge_singletons_rewrites_arxiv_method_ids_and_references():
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["2301.08653", "m2"]},
        {"id": "fam_b", "title": "B", "method_ids": ["m3", "m4"]},
    ]
    methods = [
        {
            "id": "2301.08653",
            "title": "An Analysis of the Automatic Bug Fixing Performance of ChatGPT",
            "arxiv_id": "2301.08653",
            "family_id": "fam_a",
            "neighbor_method_ids": ["m2", "m3"],
        },
        {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_a", "neighbor_method_ids": ["2301.08653"]},
        {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b", "neighbor_method_ids": ["2301.08653"]},
        {"id": "m4", "arxiv_id": "1.4", "family_id": "fam_b"},
    ]

    after = merge_singletons(_outline(families, methods))

    method_ids = {method["id"] for method in after["methods"]}
    assert "2301.08653" not in method_ids
    assert "analysis-of-the-automatic-bug-fixing-performance-of-chatgpt" in method_ids
    family_by_id = {family["id"]: family for family in after["families"]}
    assert family_by_id["fam_a"]["method_ids"] == [
        "analysis-of-the-automatic-bug-fixing-performance-of-chatgpt",
        "m2",
    ]
    method_by_id = {method["id"]: method for method in after["methods"]}
    assert method_by_id["m2"]["neighbor_method_ids"] == [
        "analysis-of-the-automatic-bug-fixing-performance-of-chatgpt"
    ]
    assert method_by_id["m3"]["neighbor_method_ids"] == [
        "analysis-of-the-automatic-bug-fixing-performance-of-chatgpt"
    ]


def test_merge_singletons_does_not_loop_when_bad_method_title_is_numeric():
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["2509-06216", "m2"]},
        {"id": "fam_b", "title": "B", "method_ids": ["m3", "m4"]},
    ]
    methods = [
        {
            "id": "2509-06216",
            "title": "2509.06216",
            "arxiv_id": "2509.06216",
            "family_id": "fam_a",
            "neighbor_method_ids": ["m2"],
        },
        {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_a", "neighbor_method_ids": ["2509-06216"]},
        {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b"},
        {"id": "m4", "arxiv_id": "1.4", "family_id": "fam_b"},
    ]
    outline = _outline(families, methods)
    queue = mp.Queue()

    def run_merge() -> None:
        queue.put(merge_singletons(outline))

    process = mp.Process(target=run_merge)
    process.start()
    process.join(timeout=2)
    if process.is_alive():
        process.terminate()
        process.join(timeout=2)
        pytest.fail("merge_singletons did not terminate for numeric fallback method title")

    assert process.exitcode == 0
    after = queue.get(timeout=1)
    method_ids = {method["id"] for method in after["methods"]}
    assert "2509-06216" not in method_ids
    assert "method-2509-06216" in method_ids


def test_merge_prunes_invalid_neighbor_links_even_without_singletons():
    families = [
        {
            "id": "fam_a",
            "title": "A",
            "method_ids": ["m1", "m2"],
            "neighbor_family_ids": ["fam_b", "removed_family"],
        },
        {
            "id": "fam_b",
            "title": "B",
            "method_ids": ["m3", "m4"],
            "neighbor_family_ids": ["fam_a", "unknown_family"],
        },
    ]
    methods = [
        {"id": "m1", "arxiv_id": "1.1", "family_id": "fam_a", "neighbor_method_ids": ["m3", "missing_method"]},
        {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_a"},
        {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b", "neighbor_method_ids": ["m1"]},
        {"id": "m4", "arxiv_id": "1.4", "family_id": "fam_b"},
    ]
    after = merge_singletons(_outline(families, methods))
    family_by_id = {f["id"]: f for f in after["families"]}
    method_by_id = {m["id"]: m for m in after["methods"]}

    assert family_by_id["fam_a"]["neighbor_family_ids"] == ["fam_b"]
    assert family_by_id["fam_b"]["neighbor_family_ids"] == ["fam_a"]
    assert method_by_id["m1"]["neighbor_method_ids"] == ["m3"]


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


def test_standalone_only_part_is_valid_for_nano_book():
    from swarn_research_mcp.research_book import _validate_parts

    families = [
        {"id": "standalone", "title": "Standalone", "method_ids": ["m_solo"], "is_group": True}
    ]
    outline = {
        "parts": [
            {
                "id": "standalone_methods",
                "title": "Standalone / Emerging Methods",
                "family_ids": ["standalone"],
            }
        ]
    }

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
