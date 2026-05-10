# Auto Research Shard 02: Heading Lint and Chapter Style Contracts

> **For agentic workers:** Implement this shard only. Do not load or execute the full reviewed source plan unless a referenced section is missing from this shard. Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` for execution.

**Source Material:** `docs/superpowers/plans/2026-05-10-codex-book-style-alignment.md` is the reviewed source plan. This shard copies the relevant task text and adds execution boundaries.

**Goal:** Align chapter heading validation and writer skill contracts with the handbook style.

**Prerequisites:** Shards 00 and 01 completed and committed. Stage 12.5 contracts are in place.

**Exit Criteria:** `pytest tests/test_research_book_chapter_headings.py -v` passes, and writer skill updates are committed.

## Global Invariants

These apply to every shard. Do not weaken them while implementing a later shard.

- Stage 12.5 normalizes `12_taxonomy/outline.json` before Stage 13 builds chapter packs.
- Stage 18 calls `assert_no_singletons(outline)` and refuses raw singleton families.
- `standalone` is the only allowed singleton group; do not create `other_*` catch-all families.
- `standalone` / `is_group` families have no family chapter file and render methods flat under `standalone_methods`.
- `BOOK_FILE_BY_ID["appendices"] == "appendices"`; appendices is a directory, not `99_appendices.md`.
- Missing citation metadata must not block a readable book. It writes an unresolved marker in `references.md` and a `citation/<arxiv_id>` item in `NEEDS_REVIEW.md`.
- Excluded chapters are quarantined: they remain on disk, are omitted from main navigation, and are listed in `16_book/NEEDS_REVIEW.md`.
- Every shard must keep tests focused and run the shard's targeted tests before committing.

---

# Wave 3 — Heading re-anchor with diagnostic lint

## Task 3.1: Heading lint with exact missing/extra/order diagnostics

**Files:**
- Test: `tests/test_research_book_chapter_headings.py` (create)
- Modify: `swarn_research_mcp/research_book.py` (add `_diff_headings`, `FAMILY_REQUIRED_HEADINGS`, `METHOD_REQUIRED_HEADINGS`, allow `## References` as trailing extra)

- [ ] **Step 1: Decision — `## References` allowed as trailing extra**

The audited run appends `## References` after the required Book_style sections. We allow it as a trailing extra (last `##` heading in the file), but reject any other extras.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_research_book_chapter_headings.py
from __future__ import annotations
import pytest
from swarn_research_mcp.research_book import (
    _diff_headings,
    FAMILY_REQUIRED_HEADINGS,
    METHOD_REQUIRED_HEADINGS,
)


def _md(headings):
    out = "# Title\n\n"
    for h in headings:
        out += f"{h}\n\nbody\n\n"
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
    bad = (FAMILY_REQUIRED_HEADINGS[:3] + ["## References"]
           + FAMILY_REQUIRED_HEADINGS[3:])
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
    old = ["## Summary", "## Motivation", "## Intuition", "## Theory", "## Algorithm",
           "## Example", "## Interpretation", "## Strengths", "## Limitations",
           "## Software", "## Related Methods"]
    diff = _diff_headings(_md(old), METHOD_REQUIRED_HEADINGS)
    assert "## Worked Example" in diff["missing"]
    assert "## Practical Guidance" in diff["missing"]
    assert "## Example" in diff["extra"]
    assert "## Software" in diff["extra"]
```

- [ ] **Step 3: Run test**

Run: `pytest tests/test_research_book_chapter_headings.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement `_diff_headings` and constants**

In `swarn_research_mcp/research_book.py`, add near other module-level constants (around line 50):

```python
FAMILY_REQUIRED_HEADINGS = [
    "## Summary", "## Motivation", "## Core Idea", "## Common Pipeline",
    "## Main Variants", "## Representative Methods", "## Strengths",
    "## Limitations", "## When to Use", "## Related Families",
]
METHOD_REQUIRED_HEADINGS = [
    "## Summary", "## Motivation", "## Intuition", "## Theory", "## Algorithm",
    "## Worked Example", "## Interpretation", "## Strengths", "## Limitations",
    "## Practical Guidance", "## Related Methods",
]


def _diff_headings(text: str, required: list[str]) -> dict[str, Any]:
    """Return missing/extra/out_of_order diagnostics. Allows `## References` ONLY as the last `##`."""
    headings = [line.strip() for line in text.splitlines() if line.strip().startswith("## ")]
    if headings and headings[-1] == "## References":
        headings = headings[:-1]
    required_set = set(required)
    missing = [h for h in required if h not in set(headings)]
    extra = [h for h in headings if h not in required_set]
    # Order check: filter headings to required-only and compare to canonical order.
    ordered_observed = [h for h in headings if h in required_set]
    out_of_order = ordered_observed != [h for h in required if h in set(ordered_observed)]
    return {"missing": missing, "extra": extra, "out_of_order": out_of_order}
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_research_book_chapter_headings.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Wire `_diff_headings` into `validate_research_book_run`**

In `validate_research_book_run`, after the parts validator call, add:

```python
    chapters_dir = run_path / "14_chapters"
    for family in families:
        fid = family.get("id")
        if family.get("is_group"):
            # Standalone group has no family chapter file; skip heading and existence checks.
            continue
        path = chapters_dir / "families" / f"{fid}.md"
        if not path.exists():
            continue
        diff = _diff_headings(path.read_text(encoding="utf-8"), FAMILY_REQUIRED_HEADINGS)
        if diff["missing"] or diff["extra"] or diff["out_of_order"]:
            issues.append({"severity": "error", "code": "wrong_chapter_headings",
                           "detail": f"family/{fid}: missing={diff['missing']} extra={diff['extra']} out_of_order={diff['out_of_order']}"})
    for method in methods:
        mid = method.get("id")
        path = chapters_dir / "methods" / f"{mid}.md"
        if not path.exists():
            continue
        diff = _diff_headings(path.read_text(encoding="utf-8"), METHOD_REQUIRED_HEADINGS)
        if diff["missing"] or diff["extra"] or diff["out_of_order"]:
            issues.append({"severity": "error", "code": "wrong_chapter_headings",
                           "detail": f"method/{mid}: missing={diff['missing']} extra={diff['extra']} out_of_order={diff['out_of_order']}"})
```

- [ ] **Step 7: Add an integration test against the fixture**

Append to `tests/test_research_book_chapter_headings.py`:

```python
def test_voice_lm_fixture_flags_old_headings(voice_lm_minimal):
    """fam_codec uses 'What this family is' (old skill); m_valle uses 'Example'/'Software'."""
    from swarn_research_mcp.research_book import validate_research_book_run
    # Fix parts so other validators don't drown out the heading errors we want.
    import json
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
```

Run: `pytest tests/test_research_book_chapter_headings.py -v`
Expected: PASS (8 tests).

- [ ] **Step 8: Commit**

```bash
git add tests/test_research_book_chapter_headings.py swarn_research_mcp/research_book.py
git commit -m "feat(research-book): heading diagnostics with missing/extra/order; allow trailing ## References"
```

---

## Task 3.2: Update `family-chapter-writing` SKILL to Book_style 10 sections

**Files:**
- Modify: `.agents/skills/family-chapter-writing/SKILL.md`

- [ ] **Step 1: Replace `## Required sections` block**

Find `## Required sections (exact \`##\` headings, in order)` and replace with:

```markdown
## Required sections (exact `##` headings, in order)
1. `## Summary` — define the family in 2–4 sentences.
2. `## Motivation` — why this family exists; cite pack's problem framing.
3. `## Core Idea` — shared intuition.
4. `## Common Pipeline` — shared workflow / architecture: inputs, representation, training/inference choice, system bottleneck.
5. `## Main Variants` — compare important variants. **MUST include a Markdown table** with header `Method | Core mechanism | When it helps | When it hurts | Cite`, one row per `pack.method_ids`. Values verbatim from `pack.comparison_rows`. Cite is `[arxiv:ID, node_id]`.
6. `## Representative Methods` — bulleted list, each entry: `- [Method Title](../methods/{method_id}.md) — one-line tagline.`
7. `## Strengths` — 3–6 bullets, each ending with citation.
8. `## Limitations` — 3–6 bullets, each ending with citation.
9. `## When to Use` — practical decision guidance.
10. `## Related Families` — one paragraph per `neighbor_family_id` with citations on boundary claims; include cross-family overlap notes.

A trailing `## References` is allowed but not required.
```

- [ ] **Step 2: Update Hard rules block**

Replace `## Hard rules` content with:
```markdown
## Hard rules
- Defer method-level details to method chapters.
- `## Main Variants` contains a comparison table; every row cites a node.
- Every `## Related Families` boundary claim cites a node.
- Method links use relative path `../methods/{method_id}.md`.
```

- [ ] **Step 3: Update Success block**

Replace `## Success` with:
```markdown
## Success
- File starts with `# `; all 10 `##` sections present in exact order.
- `## Main Variants` contains a comparison table with ≥ 1 row per method.
- `## Strengths` and `## Limitations` each have ≥ 3 bullets.
- Word count 1000–1800.
```

- [ ] **Step 4: Commit**

```bash
git add .agents/skills/family-chapter-writing/SKILL.md
git commit -m "docs(family-chapter-writing): align headings to Book_style 10-section template"
```

---

## Task 3.3: Update `method-chapter-writing` SKILL renames

**Files:**
- Modify: `.agents/skills/method-chapter-writing/SKILL.md`

- [ ] **Step 1: Rename Example → Worked Example**

Find `6. \`## Example\`` and replace with:
```markdown
6. `## Worked Example` — concrete numbers from `pack.structured.hyperparameters` and the pack's `example` section.
```

- [ ] **Step 2: Rename Software → Practical Guidance**

Find the `## Software` numbered item and replace with:
```markdown
10. `## Practical Guidance` — lead with **when to use / when not to use** (1–2 cited paragraphs). Then a sub-bullet list of artifacts (libraries, models, codebases). Every artifact MUST appear in the pack. If none, write the literal phrase "no concrete artifacts" (or "none were available") + lookup pointers.
```

- [ ] **Step 3: Sync Success block**

In `## Success`, replace any `## Example` reference with `## Worked Example`, and `## Software` with `## Practical Guidance`. The "all 11 `##` sections" line stays.

- [ ] **Step 4: Commit**

```bash
git add .agents/skills/method-chapter-writing/SKILL.md
git commit -m "docs(method-chapter-writing): rename Example→Worked Example and Software→Practical Guidance"
```

---
