from __future__ import annotations

import json

from swarn_research_mcp.research_book import (
    FAMILY_REQUIRED_HEADINGS,
    METHOD_REQUIRED_HEADINGS,
    _diff_headings,
)


def _md(headings):
    out = "# Title\n\n"
    for heading in headings:
        out += f"{heading}\n\nbody\n\n"
    return out


def test_exact_match_returns_empty_diff():
    diff = _diff_headings(_md(FAMILY_REQUIRED_HEADINGS), FAMILY_REQUIRED_HEADINGS)
    assert diff == {"missing": [], "extra": [], "out_of_order": False}


def test_missing_headings_listed():
    short = FAMILY_REQUIRED_HEADINGS[:5]
    diff = _diff_headings(_md(short), FAMILY_REQUIRED_HEADINGS)
    assert diff["missing"] == FAMILY_REQUIRED_HEADINGS[5:]


def test_extra_headings_listed():
    extra = FAMILY_REQUIRED_HEADINGS + ["## Bonus", "## More"]
    diff = _diff_headings(_md(extra), FAMILY_REQUIRED_HEADINGS)
    assert "## Bonus" in diff["extra"]
    assert "## More" in diff["extra"]


def test_references_allowed_as_trailing_extra():
    with_refs = FAMILY_REQUIRED_HEADINGS + ["## References"]
    diff = _diff_headings(_md(with_refs), FAMILY_REQUIRED_HEADINGS)
    assert diff == {"missing": [], "extra": [], "out_of_order": False}


def test_references_in_middle_is_extra():
    bad = FAMILY_REQUIRED_HEADINGS[:3] + ["## References"] + FAMILY_REQUIRED_HEADINGS[3:]
    diff = _diff_headings(_md(bad), FAMILY_REQUIRED_HEADINGS)
    # Only trailing References is allowed; mid-file References is reported as extra.
    assert "## References" in diff["extra"]
    assert diff["out_of_order"] is False


def test_out_of_order_detected():
    swapped = list(FAMILY_REQUIRED_HEADINGS)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    diff = _diff_headings(_md(swapped), FAMILY_REQUIRED_HEADINGS)
    assert diff["out_of_order"] is True


def test_method_template_old_names_caught():
    old = [
        "## Summary",
        "## Motivation",
        "## Intuition",
        "## Theory",
        "## Algorithm",
        "## Example",
        "## Interpretation",
        "## Strengths",
        "## Limitations",
        "## Software",
        "## Related Methods",
    ]
    diff = _diff_headings(_md(old), METHOD_REQUIRED_HEADINGS)
    assert "## Worked Example" in diff["missing"]
    assert "## Practical Guidance" in diff["missing"]
    assert "## Example" in diff["extra"]
    assert "## Software" in diff["extra"]


def test_voice_lm_fixture_flags_old_headings(voice_lm_minimal):
    """fam_codec uses 'What this family is' (old skill); m_valle uses 'Example'/'Software'."""
    from swarn_research_mcp.research_book import validate_research_book_run

    # Fix parts so other validators don't drown out the heading errors we want.
    op = voice_lm_minimal / "12_taxonomy" / "outline.json"
    outline = json.loads(op.read_text())
    outline["parts"] = [
        {"id": "p1", "title": "P1", "family_ids": ["fam_codec"]},
        {"id": "p2", "title": "P2", "family_ids": ["fam_flow"]},
    ]
    op.write_text(json.dumps(outline))
    issues = validate_research_book_run(voice_lm_minimal)
    detail_blob = " ".join(i["detail"] for i in issues if i["code"] == "wrong_chapter_headings")
    assert "fam_codec" in detail_blob
    assert "m_valle" in detail_blob
