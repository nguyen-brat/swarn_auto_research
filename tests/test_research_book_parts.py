from __future__ import annotations

import json

from swarn_research_mcp.research_book import validate_research_book_run


def _set_outline(run_dir, outline):
    (run_dir / "12_taxonomy" / "outline.json").write_text(json.dumps(outline))


def _add_parts(outline, parts):
    outline["parts"] = parts
    return outline


def test_missing_parts_field_is_error(voice_lm_minimal):
    # voice_lm_minimal outline has no parts field
    issues = validate_research_book_run(voice_lm_minimal)
    assert any(i["code"] == "missing_parts" for i in issues)


def test_parts_count_too_low(voice_lm_minimal):
    outline = json.loads((voice_lm_minimal / "12_taxonomy" / "outline.json").read_text())
    _set_outline(
        voice_lm_minimal,
        _add_parts(
            outline,
            [
                {"id": "p1", "title": "P1", "family_ids": ["fam_codec", "fam_flow"]},
            ],
        ),
    )
    issues = validate_research_book_run(voice_lm_minimal)
    assert any(i["code"] == "parts_count_out_of_range" for i in issues)


def test_family_in_two_parts(voice_lm_minimal):
    outline = json.loads((voice_lm_minimal / "12_taxonomy" / "outline.json").read_text())
    _set_outline(
        voice_lm_minimal,
        _add_parts(
            outline,
            [
                {"id": "p1", "title": "P1", "family_ids": ["fam_codec", "fam_flow"]},
                {"id": "p2", "title": "P2", "family_ids": ["fam_flow"]},
            ],
        ),
    )
    issues = validate_research_book_run(voice_lm_minimal)
    assert any(i["code"] == "family_in_multiple_parts" and "fam_flow" in i["detail"] for i in issues)


def test_family_unassigned_to_part(voice_lm_minimal):
    outline = json.loads((voice_lm_minimal / "12_taxonomy" / "outline.json").read_text())
    # Add a 3rd dummy family so the second part can hold something and we test only the "unassigned" path.
    outline["families"].append({"id": "fam_dummy", "title": "Dummy", "method_ids": ["m_dummy_a", "m_dummy_b"]})
    outline["methods"].extend(
        [
            {"id": "m_dummy_a", "title": "DA", "arxiv_id": "0001.0001", "family_id": "fam_dummy"},
            {"id": "m_dummy_b", "title": "DB", "arxiv_id": "0001.0002", "family_id": "fam_dummy"},
        ]
    )
    _set_outline(
        voice_lm_minimal,
        _add_parts(
            outline,
            [
                {"id": "p1", "title": "P1", "family_ids": ["fam_codec"]},
                {"id": "p2", "title": "P2", "family_ids": ["fam_dummy"]},
            ],
        ),
    )
    issues = validate_research_book_run(voice_lm_minimal)
    assert any(i["code"] == "family_unassigned_to_part" and "fam_flow" in i["detail"] for i in issues)


def test_empty_part_is_error(voice_lm_minimal):
    outline = json.loads((voice_lm_minimal / "12_taxonomy" / "outline.json").read_text())
    _set_outline(
        voice_lm_minimal,
        _add_parts(
            outline,
            [
                {"id": "p1", "title": "P1", "family_ids": ["fam_codec", "fam_flow"]},
                {"id": "p2", "title": "P2", "family_ids": []},
            ],
        ),
    )
    issues = validate_research_book_run(voice_lm_minimal)
    assert any(i["code"] == "empty_part" and "p2" in i["detail"] for i in issues)


def test_valid_parts(voice_lm_minimal):
    outline = json.loads((voice_lm_minimal / "12_taxonomy" / "outline.json").read_text())
    _set_outline(
        voice_lm_minimal,
        _add_parts(
            outline,
            [
                {"id": "p1", "title": "P1", "family_ids": ["fam_codec"]},
                {"id": "p2", "title": "P2", "family_ids": ["fam_flow"]},
            ],
        ),
    )
    issues = validate_research_book_run(voice_lm_minimal)
    parts_codes = {
        "missing_parts",
        "parts_count_out_of_range",
        "family_in_multiple_parts",
        "family_unassigned_to_part",
        "empty_part",
    }
    assert not any(i["code"] in parts_codes for i in issues)
