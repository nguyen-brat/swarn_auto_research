# Codex Pipeline Book_style Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the Codex auto-research pipeline with `Book_style.md`, add a verification hard gate, and migrate five single-shot stages to in-process Codex SDK sessions.

**Architecture:** The pipeline is a sequence of 17 stages dispatched by `auto-research-orchestrator/SKILL.md`. Per-stage behavior is defined by a SKILL.md contract plus (currently) a `.codex/agents/{stage}.toml`. Output artifacts under `research_runs/{run_id}/` are validated by `swarn_research_mcp/research_book.py::validate_research_book_run`. We modify SKILL contracts, extend the validator, add a verification gate, and add a small `sdk/codex.py` helper library for one-shot SDK calls — replacing five sub-agents.

**Tech Stack:** Python 3.11 (pytest, asyncio), Codex SDK (`AsyncCodex`), markdown SKILL contracts, JSON outline/manifest artifacts.

**Spec:** `docs/superpowers/specs/2026-05-10-codex-book-style-alignment-design.md`

---

## File Map

**Modify:**
- `.agents/skills/taxonomy-building/SKILL.md` — add `parts` step + singleton merge rule
- `.agents/skills/family-chapter-writing/SKILL.md` — replace 7 headings with Book_style 10
- `.agents/skills/method-chapter-writing/SKILL.md` — rename Example→Worked Example, Software→Practical Guidance
- `.agents/skills/book-section-writing/SKILL.md` — bibliography rule, goals rules, appendices directory
- `.agents/skills/auto-research-orchestrator/SKILL.md` — verification gate, fix_excluded loop, sdk_stages table
- `swarn_research_mcp/research_book.py` — parts validator, no-singleton validator, paper_pool resolver, appendices generator, verification gate
- `sdk/codex.py` — promote demo into library: `run_one_shot`, `run_one_shot_batch`

**Create:**
- `swarn_research_mcp/config/sdk_prompts/query_planner.md`
- `swarn_research_mcp/config/sdk_prompts/knowledge_gap_detector.md`
- `swarn_research_mcp/config/sdk_prompts/paper_ranker.md`
- `swarn_research_mcp/config/sdk_prompts/outline_planner.md`
- `swarn_research_mcp/config/sdk_prompts/chapter_manifest_builder.md`
- `tests/test_research_book_parts.py`
- `tests/test_research_book_singletons.py`
- `tests/test_research_book_bibliography.py`
- `tests/test_research_book_chapter_headings.py`
- `tests/test_research_book_verification_gate.py`
- `tests/test_sdk_run_one_shot.py`

**Delete:**
- `.codex/agents/query_planner.toml`
- `.codex/agents/knowledge_gap_detector.toml`
- `.codex/agents/paper_ranker.toml`
- `.codex/agents/outline_planner.toml`
- `.codex/agents/chapter_manifest_builder.toml`

---

# Wave 1 — Taxonomy: parts + singleton merge

## Task 1.1: Add `parts` field validator to research_book

**Files:**
- Test: `tests/test_research_book_parts.py` (create)
- Modify: `swarn_research_mcp/research_book.py:177` (extend `validate_research_book_run`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_research_book_parts.py
from __future__ import annotations
import json
from pathlib import Path
import pytest
from swarn_research_mcp.research_book import validate_research_book_run


def _minimal_outline_with_parts(parts):
    return {
        "topic": "t",
        "book_sections": [
            {"id": "preface", "title": "P"},
            {"id": "motivating_intro", "title": "M"},
            {"id": "core_concepts", "title": "C"},
            {"id": "goals", "title": "G"},
            {"id": "method_taxonomy", "title": "T"},
            {"id": "shared_examples", "title": "S"},
            {"id": "evaluation_outlook", "title": "E"},
            {"id": "appendices", "title": "A"},
        ],
        "families": [
            {"id": "fam_a", "title": "Fam A", "method_ids": ["m1", "m2"]},
            {"id": "fam_b", "title": "Fam B", "method_ids": ["m3", "m4"]},
        ],
        "methods": [
            {"id": "m1", "arxiv_id": "1.1", "family_id": "fam_a"},
            {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_a"},
            {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b"},
            {"id": "m4", "arxiv_id": "1.4", "family_id": "fam_b"},
        ],
        "parts": parts,
    }


def _scaffold(tmp_path: Path, outline: dict) -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "12_taxonomy").mkdir(parents=True)
    (run_dir / "07_scoring").mkdir(parents=True)
    (run_dir / "16_book").mkdir(parents=True)
    (run_dir / "12_taxonomy" / "outline.json").write_text(json.dumps(outline))
    (run_dir / "07_scoring" / "promoted_papers.json").write_text(
        json.dumps({"promoted_papers": [
            {"arxiv_id": "1.1", "title": "P1", "year": 2024},
            {"arxiv_id": "1.2", "title": "P2", "year": 2024},
            {"arxiv_id": "1.3", "title": "P3", "year": 2024},
            {"arxiv_id": "1.4", "title": "P4", "year": 2024},
        ]})
    )
    (run_dir / "16_book" / "chapters_manifest.json").write_text(
        json.dumps({"book": [], "families": [], "methods": []})
    )
    return run_dir


def test_missing_parts_field_is_error(tmp_path):
    outline = _minimal_outline_with_parts(parts=None)
    outline.pop("parts")
    run_dir = _scaffold(tmp_path, outline)
    issues = validate_research_book_run(run_dir)
    codes = [i["code"] for i in issues]
    assert "missing_parts" in codes


def test_part_count_out_of_range_is_error(tmp_path):
    outline = _minimal_outline_with_parts(parts=[
        {"id": "only_one", "title": "Only", "family_ids": ["fam_a", "fam_b"]},
    ])
    run_dir = _scaffold(tmp_path, outline)
    issues = validate_research_book_run(run_dir)
    assert any(i["code"] == "parts_count_out_of_range" for i in issues)


def test_family_in_two_parts_is_error(tmp_path):
    outline = _minimal_outline_with_parts(parts=[
        {"id": "p1", "title": "P1", "family_ids": ["fam_a", "fam_b"]},
        {"id": "p2", "title": "P2", "family_ids": ["fam_b"]},
    ])
    run_dir = _scaffold(tmp_path, outline)
    issues = validate_research_book_run(run_dir)
    assert any(i["code"] == "family_in_multiple_parts" for i in issues)


def test_family_unassigned_to_part_is_error(tmp_path):
    outline = _minimal_outline_with_parts(parts=[
        {"id": "p1", "title": "P1", "family_ids": ["fam_a"]},
    ])
    run_dir = _scaffold(tmp_path, outline)
    issues = validate_research_book_run(run_dir)
    assert any(i["code"] == "family_unassigned_to_part" for i in issues)


def test_valid_parts_passes(tmp_path):
    outline = _minimal_outline_with_parts(parts=[
        {"id": "p1", "title": "P1", "family_ids": ["fam_a"]},
        {"id": "p2", "title": "P2", "family_ids": ["fam_b"]},
    ])
    run_dir = _scaffold(tmp_path, outline)
    issues = validate_research_book_run(run_dir)
    assert not any(i["code"].startswith("parts_") or i["code"] in
                   ("missing_parts", "family_in_multiple_parts", "family_unassigned_to_part")
                   for i in issues)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_research_book_parts.py -v`
Expected: FAIL — current validator does not recognize `parts`.

- [ ] **Step 3: Add `_validate_parts` helper + call from `validate_research_book_run`**

In `swarn_research_mcp/research_book.py`, add this function above `validate_research_book_run` (around line 175):

```python
def _validate_parts(outline: dict[str, Any], families: list[dict[str, Any]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    parts = outline.get("parts")
    if parts is None:
        issues.append({"severity": "error", "code": "missing_parts",
                       "detail": "outline.json must define a 'parts' array"})
        return issues

    if not isinstance(parts, list) or not (2 <= len(parts) <= 5):
        issues.append({"severity": "error", "code": "parts_count_out_of_range",
                       "detail": f"parts must have 2..5 entries, got {len(parts) if isinstance(parts, list) else 'non-list'}"})
        return issues

    family_ids = {f.get("id") for f in families if f.get("id")}
    seen: dict[str, str] = {}
    for part in parts:
        pid = part.get("id", "")
        for fid in part.get("family_ids", []) or []:
            if fid in seen:
                issues.append({"severity": "error", "code": "family_in_multiple_parts",
                               "detail": f"family {fid} appears in parts {seen[fid]} and {pid}"})
            else:
                seen[fid] = pid

    for fid in family_ids:
        if fid not in seen:
            issues.append({"severity": "error", "code": "family_unassigned_to_part",
                           "detail": f"family {fid} is not in any part"})

    return issues
```

Then in `validate_research_book_run`, after the `families = outline.get("families", [])` line (around line 185), append:

```python
    issues.extend(_validate_parts(outline, families))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_research_book_parts.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_research_book_parts.py swarn_research_mcp/research_book.py
git commit -m "feat(research-book): validate outline.json parts (2..5, no overlap, full coverage)"
```

---

## Task 1.2: Add singleton-family validator

**Files:**
- Test: `tests/test_research_book_singletons.py` (create)
- Modify: `swarn_research_mcp/research_book.py` (extend validator)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_research_book_singletons.py
from __future__ import annotations
import json
from pathlib import Path
from swarn_research_mcp.research_book import validate_research_book_run

BOOK_SECTIONS = [
    {"id": "preface", "title": "P"}, {"id": "motivating_intro", "title": "M"},
    {"id": "core_concepts", "title": "C"}, {"id": "goals", "title": "G"},
    {"id": "method_taxonomy", "title": "T"}, {"id": "shared_examples", "title": "S"},
    {"id": "evaluation_outlook", "title": "E"}, {"id": "appendices", "title": "A"},
]


def _scaffold(tmp_path: Path, families, methods):
    run_dir = tmp_path / "run"
    (run_dir / "12_taxonomy").mkdir(parents=True)
    (run_dir / "07_scoring").mkdir(parents=True)
    (run_dir / "16_book").mkdir(parents=True)
    family_ids = [f["id"] for f in families]
    parts = [{"id": "p1", "title": "P1", "family_ids": family_ids[:1]},
             {"id": "p2", "title": "P2", "family_ids": family_ids[1:]}] if len(family_ids) >= 2 else \
            [{"id": "p1", "title": "P1", "family_ids": family_ids},
             {"id": "p2", "title": "P2", "family_ids": []}]
    outline = {"topic": "t", "book_sections": BOOK_SECTIONS,
               "families": families, "methods": methods, "parts": parts}
    (run_dir / "12_taxonomy" / "outline.json").write_text(json.dumps(outline))
    promoted = [{"arxiv_id": m["arxiv_id"], "title": m["id"], "year": 2024} for m in methods]
    (run_dir / "07_scoring" / "promoted_papers.json").write_text(
        json.dumps({"promoted_papers": promoted}))
    (run_dir / "16_book" / "chapters_manifest.json").write_text(
        json.dumps({"book": [], "families": [], "methods": []}))
    return run_dir


def test_singleton_family_is_error(tmp_path):
    families = [{"id": "fam_a", "title": "A", "method_ids": ["m1"]},
                {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"]}]
    methods = [{"id": "m1", "arxiv_id": "1.1", "family_id": "fam_a"},
               {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b"},
               {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b"}]
    issues = validate_research_book_run(_scaffold(tmp_path, families, methods))
    assert any(i["code"] == "singleton_family" and "fam_a" in i["detail"] for i in issues)


def test_no_singletons_passes(tmp_path):
    families = [{"id": "fam_a", "title": "A", "method_ids": ["m1", "m2"]},
                {"id": "fam_b", "title": "B", "method_ids": ["m3", "m4"]}]
    methods = [{"id": f"m{i}", "arxiv_id": f"1.{i}", "family_id": fam}
               for i, fam in [(1,"fam_a"),(2,"fam_a"),(3,"fam_b"),(4,"fam_b")]]
    issues = validate_research_book_run(_scaffold(tmp_path, families, methods))
    assert not any(i["code"] == "singleton_family" for i in issues)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_research_book_singletons.py -v`
Expected: FAIL — `singleton_family` code does not exist.

- [ ] **Step 3: Add singleton check**

In `swarn_research_mcp/research_book.py::validate_research_book_run`, find the loop iterating `families` (search for `family.get("method_ids")`) and add inside:

```python
        if len(family.get("method_ids", [])) == 1:
            issues.append({"severity": "error", "code": "singleton_family",
                           "detail": f"family {family.get('id')} has only 1 method; merge into nearest non-singleton family"})
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_research_book_singletons.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_research_book_singletons.py swarn_research_mcp/research_book.py
git commit -m "feat(research-book): reject singleton families in outline.json"
```

---

## Task 1.3: Update `taxonomy-building` SKILL with parts + singleton merge

**Files:**
- Modify: `.agents/skills/taxonomy-building/SKILL.md`

- [ ] **Step 1: Edit the SKILL — add parts step**

In `.agents/skills/taxonomy-building/SKILL.md`, find the section header `## Family clustering` and immediately AFTER its bullet list, add:

```markdown
## Parts (topic-adaptive grouping)
After clustering, assign every family to exactly one part.

Default labels (Book_style.md): `interpretable`, `local`, `global`, `model_specific`, `evaluation_outlook`. You MAY rename, merge, or drop default parts when the topic fits a different shape (e.g. for speech systems: `representation_and_tokenization`, `generation_objectives`, `unified_speech_language_interaction`, `evaluation_and_conversation_control`).

Hard rules:
- 2 ≤ len(parts) ≤ 5
- Every family appears in exactly one part
- Every part contains ≥ 1 family

Emit as `parts: [{id, title, family_ids[]}]` in `outline.json`.
```

- [ ] **Step 2: Add singleton-merge rule**

In the same file, under `## Family clustering`, AFTER the existing bullet `- For singleton fallback communities, choose the nearest clean bucket...`, append a new sub-section:

```markdown
## Singleton merge
After labeling, before emitting `outline.json`, merge any family with `len(method_ids) == 1` into its nearest non-singleton family.

Algorithm:
1. List all singleton families.
2. For each, find the non-singleton family with the most shared verified-graph edges between the singleton's method and the candidate's methods. Tiebreaker: intersection of `neighbor_method_ids`.
3. Append the method to the target family's `method_ids`. The target keeps its title/id.
4. If no non-singleton candidate has any graph connection, place the method into a catch-all family per part: `other_{part_id}`. One catch-all per part is allowed; that catch-all may itself be a singleton only if no other home exists.

Hard rule: after merge, every family has `len(method_ids) ≥ 2` (catch-alls excepted only when no home exists).
```

- [ ] **Step 3: Update outline.json schema example**

In the same file, find the `outline.json schema` JSON block and add `parts` after `book_sections`:

```json
  "parts": [{"id": "interpretable", "title": "Interpretable Methods", "family_ids": ["fam_a"]}],
```

- [ ] **Step 4: Update Hard rules block**

Find the `## Hard rules` list and add three bullets:
```markdown
- `parts` is present with 2..5 entries; every family belongs to exactly one part.
- After singleton merge, every non-catch-all family has ≥ 2 methods.
- Singleton catch-alls are named `other_{part_id}` and only used when no home exists.
```

- [ ] **Step 5: Commit**

```bash
git add .agents/skills/taxonomy-building/SKILL.md
git commit -m "feat(taxonomy): add parts grouping and singleton-merge rule to skill contract"
```

---

# Wave 2 — Bibliography bug fix

## Task 2.1: Test that bibliography rendering uses paper_pool

**Files:**
- Test: `tests/test_research_book_bibliography.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_research_book_bibliography.py
from __future__ import annotations
import json
from pathlib import Path
import pytest
from swarn_research_mcp.research_book import resolve_paper_citation, MissingCitationError


def _scaffold(tmp_path: Path, pool_entries):
    run_dir = tmp_path / "run"
    (run_dir / "02_paper_pool").mkdir(parents=True)
    (run_dir / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps({"papers": pool_entries})
    )
    return run_dir


def test_resolve_returns_title_and_year(tmp_path):
    run = _scaffold(tmp_path, [{"arxiv_id": "2301.02111", "title": "VALL-E", "year": 2023}])
    cite = resolve_paper_citation(run, "2301.02111")
    assert cite == {"arxiv_id": "2301.02111", "title": "VALL-E", "year": 2023}


def test_missing_arxiv_raises(tmp_path):
    run = _scaffold(tmp_path, [{"arxiv_id": "2301.02111", "title": "VALL-E", "year": 2023}])
    with pytest.raises(MissingCitationError) as exc:
        resolve_paper_citation(run, "9999.99999")
    assert "9999.99999" in str(exc.value)


def test_missing_title_or_year_raises(tmp_path):
    run = _scaffold(tmp_path, [{"arxiv_id": "2301.02111", "title": "", "year": None}])
    with pytest.raises(MissingCitationError):
        resolve_paper_citation(run, "2301.02111")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_research_book_bibliography.py -v`
Expected: FAIL — `resolve_paper_citation` and `MissingCitationError` don't exist.

- [ ] **Step 3: Add resolver to research_book.py**

In `swarn_research_mcp/research_book.py`, after `_paper_lookup` (around line 102), add:

```python
class MissingCitationError(LookupError):
    """Raised when a cited arxiv_id cannot be resolved to title+year from paper_pool."""


def resolve_paper_citation(run_dir: Path | str, arxiv_id: str) -> dict[str, Any]:
    """Resolve {arxiv_id, title, year} from 02_paper_pool/paper_pool.json. Raise on missing or empty fields."""
    pool = _paper_lookup(Path(run_dir))
    entry = pool.get(arxiv_id)
    if entry is None:
        raise MissingCitationError(f"arxiv_id {arxiv_id} not found in paper_pool.json")
    title = entry.get("title") or ""
    year = entry.get("year")
    if not title or year in (None, "", 0):
        raise MissingCitationError(
            f"arxiv_id {arxiv_id} has empty title or year in paper_pool.json: title={title!r}, year={year!r}"
        )
    return {"arxiv_id": arxiv_id, "title": title, "year": year}
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_research_book_bibliography.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_research_book_bibliography.py swarn_research_mcp/research_book.py
git commit -m "feat(research-book): add resolve_paper_citation with strict missing-field error"
```

---

## Task 2.2: Wire resolver into method_taxonomy generation

**Files:**
- Modify: `swarn_research_mcp/research_book.py:532` (`_build_method_taxonomy`)

- [ ] **Step 1: Inspect current `_build_method_taxonomy` to see how references are emitted**

Run: `sed -n '530,562p' /home/nguyen/code/swarn_auto_research/swarn_research_mcp/research_book.py`

Note where the function currently writes `[arxiv:ID] Title (Year)` lines.

- [ ] **Step 2: Replace stale-cache title lookup with `resolve_paper_citation`**

In `_build_method_taxonomy` (line 532+), find any line that constructs a reference like `f"[arxiv:{aid}] {title} ({year})"` and replace its title/year source with:

```python
        try:
            cite = resolve_paper_citation(run_dir, aid)
            ref_line = f"[arxiv:{cite['arxiv_id']}] {cite['title']} ({cite['year']})"
        except MissingCitationError as exc:
            raise MissingCitationError(
                f"method_taxonomy bibliography blocked: {exc}. "
                "Fix paper_pool.json before regenerating."
            )
```

If `_build_method_taxonomy` does not currently take `run_dir`, change the signature to `_build_method_taxonomy(run_dir: Path, outline: dict[str, Any]) -> str` and pass `run_dir` from the caller in `generate_book_artifacts` (line 638).

- [ ] **Step 3: Add an integration test**

Append to `tests/test_research_book_bibliography.py`:

```python
def test_build_method_taxonomy_fails_on_missing_pool_entry(tmp_path):
    from swarn_research_mcp.research_book import _build_method_taxonomy
    run = tmp_path / "run"
    (run / "02_paper_pool").mkdir(parents=True)
    (run / "02_paper_pool" / "paper_pool.json").write_text(
        json.dumps({"papers": []})  # empty pool
    )
    outline = {
        "families": [{"id": "fam_a", "title": "A", "method_ids": ["m1"]}],
        "methods": [{"id": "m1", "title": "M1", "arxiv_id": "2301.02111", "family_id": "fam_a"}],
        "parts": [{"id": "p1", "title": "P1", "family_ids": ["fam_a"]}],
    }
    with pytest.raises(MissingCitationError) as exc:
        _build_method_taxonomy(run, outline)
    assert "2301.02111" in str(exc.value)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_research_book_bibliography.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_research_book_bibliography.py swarn_research_mcp/research_book.py
git commit -m "fix(research-book): method_taxonomy bibliography pulls title/year from paper_pool, fails loud on missing"
```

---

## Task 2.3: Update `book-section-writing` SKILL bibliography rule

**Files:**
- Modify: `.agents/skills/book-section-writing/SKILL.md`

- [ ] **Step 1: Add bibliography rule under `method_taxonomy` section**

In `.agents/skills/book-section-writing/SKILL.md`, find the `method_taxonomy` row in the `## Per-section structure` list and replace it with:

```markdown
- `method_taxonomy` — deterministic artifact. Prefer `python -m swarn_research_mcp.research_book research_runs/{run_id} --generate` over free-form writing. If forced to draft manually, every cited paper's title and year must come from `02_paper_pool/paper_pool.json` via `resolve_paper_citation`. **Never emit `<title unknown>` or `<year unknown>`** — if a cited arxiv_id has no resolvable title/year, fail loudly and stop.
```

- [ ] **Step 2: Commit**

```bash
git add .agents/skills/book-section-writing/SKILL.md
git commit -m "docs(book-section-writing): require paper_pool resolution for bibliography, no <title unknown> output"
```

---

# Wave 3 — Heading re-anchor

## Task 3.1: Add chapter-heading lint to validator

**Files:**
- Test: `tests/test_research_book_chapter_headings.py` (create)
- Modify: `swarn_research_mcp/research_book.py` (extend validator)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_research_book_chapter_headings.py
from __future__ import annotations
import json
from pathlib import Path
from swarn_research_mcp.research_book import validate_research_book_run

FAMILY_HEADINGS = [
    "## Summary", "## Motivation", "## Core Idea", "## Common Pipeline",
    "## Main Variants", "## Representative Methods", "## Strengths",
    "## Limitations", "## When to Use", "## Related Families",
]
METHOD_HEADINGS = [
    "## Summary", "## Motivation", "## Intuition", "## Theory", "## Algorithm",
    "## Worked Example", "## Interpretation", "## Strengths", "## Limitations",
    "## Practical Guidance", "## Related Methods",
]

BOOK_SECTIONS = [
    {"id": "preface", "title": "P"}, {"id": "motivating_intro", "title": "M"},
    {"id": "core_concepts", "title": "C"}, {"id": "goals", "title": "G"},
    {"id": "method_taxonomy", "title": "T"}, {"id": "shared_examples", "title": "S"},
    {"id": "evaluation_outlook", "title": "E"}, {"id": "appendices", "title": "A"},
]


def _scaffold(tmp_path, family_body, method_body):
    run_dir = tmp_path / "run"
    for sub in ("12_taxonomy", "07_scoring", "16_book",
                "14_chapters/families", "14_chapters/methods", "14_chapters/book"):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    outline = {
        "topic": "t",
        "book_sections": BOOK_SECTIONS,
        "families": [{"id": "fam_a", "title": "Fam A", "method_ids": ["m1", "m2"]}],
        "methods": [
            {"id": "m1", "title": "M1", "arxiv_id": "1.1", "family_id": "fam_a"},
            {"id": "m2", "title": "M2", "arxiv_id": "1.2", "family_id": "fam_a"},
        ],
        "parts": [{"id": "p1", "title": "P1", "family_ids": ["fam_a"]}],
    }
    (run_dir / "12_taxonomy" / "outline.json").write_text(json.dumps(outline))
    (run_dir / "07_scoring" / "promoted_papers.json").write_text(
        json.dumps({"promoted_papers": [
            {"arxiv_id": "1.1", "title": "M1", "year": 2024},
            {"arxiv_id": "1.2", "title": "M2", "year": 2024},
        ]})
    )
    (run_dir / "16_book" / "chapters_manifest.json").write_text(
        json.dumps({"book": [], "families": ["fam_a"], "methods": ["m1", "m2"]}))
    (run_dir / "14_chapters" / "families" / "fam_a.md").write_text(family_body)
    (run_dir / "14_chapters" / "methods" / "m1.md").write_text(method_body)
    (run_dir / "14_chapters" / "methods" / "m2.md").write_text(method_body)
    return run_dir


def _good_family():
    body = "# Fam A\n\n"
    for h in FAMILY_HEADINGS:
        body += f"{h}\n\nbody text\n\n"
    return body


def _good_method():
    body = "# M\n\n"
    for h in METHOD_HEADINGS:
        body += f"{h}\n\nbody text\n\n"
    return body


def test_correct_headings_pass(tmp_path):
    run = _scaffold(tmp_path, _good_family(), _good_method())
    issues = validate_research_book_run(run)
    assert not any(i["code"] == "wrong_chapter_headings" for i in issues)


def test_wrong_family_headings_fail(tmp_path):
    bad = "# Fam A\n\n## What this family is\n\nbody\n\n## Core design pattern\n\nbody\n"
    run = _scaffold(tmp_path, bad, _good_method())
    issues = validate_research_book_run(run)
    assert any(i["code"] == "wrong_chapter_headings" and "fam_a" in i["detail"] for i in issues)


def test_wrong_method_headings_fail(tmp_path):
    bad = "# M\n\n## Summary\n\n## Example\n\n## Software\n"  # old names
    run = _scaffold(tmp_path, _good_family(), bad)
    issues = validate_research_book_run(run)
    assert any(i["code"] == "wrong_chapter_headings" for i in issues)
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_research_book_chapter_headings.py -v`
Expected: FAIL — no `wrong_chapter_headings` code yet.

- [ ] **Step 3: Add `_validate_chapter_headings` helper**

In `swarn_research_mcp/research_book.py`, add at module scope (near other constants, around line 50):

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


def _check_headings(text: str, required: list[str]) -> list[str]:
    """Return the list of required headings missing or out-of-order in text."""
    found = [line.strip() for line in text.splitlines() if line.strip().startswith("## ")]
    # Filter to only headings the contract cares about; preserve order.
    relevant = [h for h in found if h in required]
    if relevant != required:
        return required  # signal "not exact match"
    return []
```

Inside `validate_research_book_run`, after the existing family/method loops (find the line that processes `families` and `methods`), add:

```python
    chapters_dir = run_path / "14_chapters"
    for family in families:
        fid = family.get("id")
        path = chapters_dir / "families" / f"{fid}.md"
        if path.exists():
            text = path.read_text(encoding="utf-8")
            if _check_headings(text, FAMILY_REQUIRED_HEADINGS):
                issues.append({
                    "severity": "error", "code": "wrong_chapter_headings",
                    "detail": f"family chapter {fid} does not match Book_style 10-section template",
                })
    for method in methods:
        mid = method.get("id")
        path = chapters_dir / "methods" / f"{mid}.md"
        if path.exists():
            text = path.read_text(encoding="utf-8")
            if _check_headings(text, METHOD_REQUIRED_HEADINGS):
                issues.append({
                    "severity": "error", "code": "wrong_chapter_headings",
                    "detail": f"method chapter {mid} does not match Book_style 11-section template",
                })
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_research_book_chapter_headings.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_research_book_chapter_headings.py swarn_research_mcp/research_book.py
git commit -m "feat(research-book): lint family/method chapter headings against Book_style templates"
```

---

## Task 3.2: Update `family-chapter-writing` SKILL to Book_style headings

**Files:**
- Modify: `.agents/skills/family-chapter-writing/SKILL.md`

- [ ] **Step 1: Replace the section list**

In `.agents/skills/family-chapter-writing/SKILL.md`, find `## Required sections (exact \`##\` headings, in order)` and replace its 7-bullet list with:

```markdown
## Required sections (exact `##` headings, in order)
1. `## Summary` — define the family in 2–4 sentences.
2. `## Motivation` — why this family exists (cite pack's problem framing).
3. `## Core Idea` — the shared intuition across the family.
4. `## Common Pipeline` — describe the shared workflow / architecture inputs, representation, training/inference choices, and bottleneck.
5. `## Main Variants` — compare important variants. **MUST contain a Markdown table** with header `Method | Core mechanism | When it helps | When it hurts | Cite`, one row per `pack.method_ids`. Values verbatim from `pack.comparison_rows`. Cite is `[arxiv:ID, node_id]`.
6. `## Representative Methods` — bulleted list, each entry: `- [Method Title](../methods/{method_id}.md) — one-line tagline.`
7. `## Strengths` — 3–6 bullets, each ends with citation.
8. `## Limitations` — 3–6 bullets, each ends with citation.
9. `## When to Use` — practical decision guidance: when this family helps, when it does not.
10. `## Related Families` — one paragraph per `neighbor_family_id` with citations on boundary claims, plus boundary cases that span families.
```

- [ ] **Step 2: Update Hard rules and Success blocks**

Find `## Hard rules` and replace its content with:

```markdown
## Hard rules
- Defer method-level details to method chapters. Do not re-derive.
- `## Main Variants` must contain a comparison table; every row cites a node.
- Every `## Related Families` boundary claim cites a node.
- Method links use relative path `../methods/{method_id}.md`.
```

Find `## Success` and replace with:

```markdown
## Success
- File starts with `# `; all 10 `##` sections present in order with exact Book_style headings.
- `## Main Variants` contains a comparison table with ≥ 1 row per method.
- `## Strengths` and `## Limitations` each have ≥ 3 bullets.
- Word count 1000–1800.
```

- [ ] **Step 3: Commit**

```bash
git add .agents/skills/family-chapter-writing/SKILL.md
git commit -m "docs(family-chapter-writing): re-anchor section headings to Book_style.md 10-section template"
```

---

## Task 3.3: Update `method-chapter-writing` SKILL with renames

**Files:**
- Modify: `.agents/skills/method-chapter-writing/SKILL.md`

- [ ] **Step 1: Rename Example → Worked Example, Software → Practical Guidance**

In `.agents/skills/method-chapter-writing/SKILL.md`, find the numbered list under `## Required sections (in order, exact \`##\` headings)`. Change:

- `6. \`## Example\`` → `6. \`## Worked Example\``
- `10. \`## Software\` — every artifact MUST appear in the pack...` → `10. \`## Practical Guidance\` — lead with **when to use / when not to use** (1–2 paragraphs, cited). Then a sub-bullet list of artifacts (libraries, models, codebases). Every artifact MUST appear in the pack. If none, write the literal phrase "no concrete artifacts" (or "none were available") + lookup pointers.`

- [ ] **Step 2: Update grep-able mentions**

In the same file, replace any other occurrence of `Software` (as a section name) with `Practical Guidance`, and any `Example` (as a required-section reference) with `Worked Example`.

- [ ] **Step 3: Update Success block**

Find `## Success` in this file and verify the section names match. Replace any `Example` / `Software` references with `Worked Example` / `Practical Guidance`.

- [ ] **Step 4: Commit**

```bash
git add .agents/skills/method-chapter-writing/SKILL.md
git commit -m "docs(method-chapter-writing): rename Example→Worked Example and Software→Practical Guidance per Book_style"
```

---

# Wave 4 — Goals + Appendices beef-up

## Task 4.1: Edit `book-section-writing` SKILL for Goals

**Files:**
- Modify: `.agents/skills/book-section-writing/SKILL.md`

- [ ] **Step 1: Tighten the goals row**

In `.agents/skills/book-section-writing/SKILL.md`, find the goals line in `## Per-section structure` and replace with:

```markdown
- `goals` — H1 + ≥ 4 goal categories. Each category includes (a) why it matters, (b) which families help (cite by family link), (c) one tradeoff. Min 600 words.
```

In the `## Output filenames` table, change goals word range:

```markdown
| `goals`              | `03_goals.md`                  | 600–1200   |
```

- [ ] **Step 2: Commit**

```bash
git add .agents/skills/book-section-writing/SKILL.md
git commit -m "docs(book-section-writing): goals chapter requires 4 categories, family links, tradeoffs, 600+ words"
```

---

## Task 4.2: Add appendices directory generator to research_book.py

**Files:**
- Test: extend `tests/test_research_book_artifacts.py`
- Modify: `swarn_research_mcp/research_book.py:562` (`_build_appendices`)

- [ ] **Step 1: Read current `_build_appendices`**

Run: `sed -n '562,594p' /home/nguyen/code/swarn_auto_research/swarn_research_mcp/research_book.py`

Note its current signature and how it's called from `generate_book_artifacts`.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_research_book_artifacts.py` (the existing file):

```python
def test_appendices_directory_has_four_files(tmp_path):
    from swarn_research_mcp.research_book import generate_book_artifacts
    run_dir = minimal_run(tmp_path)
    # ensure required inputs exist
    (run_dir / "06_expansion").mkdir(parents=True, exist_ok=True)
    (run_dir / "06_expansion" / "known_concepts_snapshot.json").write_text(
        json.dumps({"known_concepts": [
            {"name": "transformer", "definition": "self-attention block stack"}
        ]})
    )
    generate_book_artifacts(run_dir)
    appendices = run_dir / "14_chapters" / "book" / "99_appendices"
    assert appendices.is_dir()
    for name in ("glossary.md", "notation.md", "datasets.md", "software.md"):
        assert (appendices / name).exists(), f"missing {name}"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_research_book_artifacts.py::test_appendices_directory_has_four_files -v`
Expected: FAIL.

- [ ] **Step 4: Replace `_build_appendices` with directory builder**

In `swarn_research_mcp/research_book.py`, replace `_build_appendices(run_dir, outline) -> str` with `_build_appendices_dir(run_dir, outline) -> None`:

```python
def _build_appendices_dir(run_dir: Path, outline: dict[str, Any]) -> None:
    out_dir = run_dir / "14_chapters" / "book" / "99_appendices"
    out_dir.mkdir(parents=True, exist_ok=True)

    # glossary.md from known_concepts_snapshot
    snap_path = run_dir / "06_expansion" / "known_concepts_snapshot.json"
    glossary_lines = ["# Glossary", ""]
    if snap_path.exists():
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
        for entry in snap.get("known_concepts", []) or []:
            name = entry.get("name") or entry.get("id") or ""
            definition = entry.get("definition") or entry.get("summary") or ""
            if name:
                glossary_lines.append(f"- **{name}** — {definition}")
    (out_dir / "glossary.md").write_text("\n".join(glossary_lines) + "\n", encoding="utf-8")

    # notation.md — pull symbols from each method pack's structured.equations
    notation_lines = ["# Notation", ""]
    packs_dir = run_dir / "13_chapter_packs" / "methods"
    if packs_dir.exists():
        seen: set[str] = set()
        for pack_path in sorted(packs_dir.glob("*_pack.json")):
            pack = json.loads(pack_path.read_text(encoding="utf-8"))
            for eq in (pack.get("structured", {}).get("equations") or []):
                for sym in eq.get("symbols", []) or []:
                    name = sym.get("name") or ""
                    desc = sym.get("description") or ""
                    if name and name not in seen:
                        seen.add(name)
                        notation_lines.append(f"- `{name}` — {desc}")
    (out_dir / "notation.md").write_text("\n".join(notation_lines) + "\n", encoding="utf-8")

    # datasets.md — pull dataset names from method packs
    datasets_lines = ["# Datasets", ""]
    if packs_dir.exists():
        seen_d: set[str] = set()
        for pack_path in sorted(packs_dir.glob("*_pack.json")):
            pack = json.loads(pack_path.read_text(encoding="utf-8"))
            for ds in (pack.get("structured", {}).get("datasets") or []):
                name = ds.get("name") or ""
                if name and name not in seen_d:
                    seen_d.add(name)
                    datasets_lines.append(f"- {name}")
    (out_dir / "datasets.md").write_text("\n".join(datasets_lines) + "\n", encoding="utf-8")

    # software.md — pull artifact list from method packs
    software_lines = ["# Software and Artifacts", ""]
    if packs_dir.exists():
        seen_s: set[str] = set()
        for pack_path in sorted(packs_dir.glob("*_pack.json")):
            pack = json.loads(pack_path.read_text(encoding="utf-8"))
            for art in (pack.get("structured", {}).get("artifacts") or []):
                name = art.get("name") or ""
                if name and name not in seen_s:
                    seen_s.add(name)
                    software_lines.append(f"- {name}")
    (out_dir / "software.md").write_text("\n".join(software_lines) + "\n", encoding="utf-8")
```

- [ ] **Step 5: Update `generate_book_artifacts` to call new builder**

Find the call to `_build_appendices` inside `generate_book_artifacts` (around line 638-650). Replace the line that writes `99_appendices.md` with:

```python
    _build_appendices_dir(run_path, outline)
```

Remove the old `_build_appendices` function definition.

- [ ] **Step 6: Run test**

Run: `pytest tests/test_research_book_artifacts.py::test_appendices_directory_has_four_files -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/test_research_book_artifacts.py swarn_research_mcp/research_book.py
git commit -m "feat(research-book): emit 99_appendices/ directory with glossary, notation, datasets, software"
```

---

## Task 4.3: Update `book-section-writing` SKILL for appendices directory

**Files:**
- Modify: `.agents/skills/book-section-writing/SKILL.md`

- [ ] **Step 1: Replace appendices row**

In `.agents/skills/book-section-writing/SKILL.md`, find the appendices row in `## Output filenames` and `## Per-section structure`. Replace:

In the table:
```markdown
| `appendices`         | `99_appendices/` (directory)   | no floor   |
```

In `## Per-section structure`:
```markdown
- `appendices` — deterministic artifact. Always run `python -m swarn_research_mcp.research_book research_runs/{run_id} --generate`; this emits a `99_appendices/` directory with `glossary.md`, `notation.md`, `datasets.md`, `software.md`. Do not hand-author the directory.
```

- [ ] **Step 2: Commit**

```bash
git add .agents/skills/book-section-writing/SKILL.md
git commit -m "docs(book-section-writing): appendices is a directory with 4 generated files"
```

---

# Wave 5 — Verification hard gate

## Task 5.1: Add verification gate function

**Files:**
- Test: `tests/test_research_book_verification_gate.py` (create)
- Modify: `swarn_research_mcp/research_book.py` (add `verification_gate`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_research_book_verification_gate.py
from __future__ import annotations
from pathlib import Path
import pytest
from swarn_research_mcp.research_book import verification_gate, VerificationGateError


def _write_chapter(path: Path, status: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nchapter_id: x\nstatus: {status}\nstatus_reason: \"\"\n---\n# X\n",
        encoding="utf-8",
    )


def test_gate_passes_when_all_chapters_passed(tmp_path):
    run = tmp_path / "run"
    _write_chapter(run / "14_chapters/families/fam_a.md", "passed")
    _write_chapter(run / "14_chapters/methods/m1.md", "passed")
    verification_gate(run)  # no raise


def test_gate_fails_on_excluded_family(tmp_path):
    run = tmp_path / "run"
    _write_chapter(run / "14_chapters/families/fam_a.md", "excluded_gaps_missing")
    with pytest.raises(VerificationGateError) as exc:
        verification_gate(run)
    assert "fam_a" in str(exc.value)
    assert "excluded_gaps_missing" in str(exc.value)


def test_gate_fails_on_excluded_method(tmp_path):
    run = tmp_path / "run"
    _write_chapter(run / "14_chapters/methods/m1.md", "excluded_unsupported_claims")
    with pytest.raises(VerificationGateError) as exc:
        verification_gate(run)
    assert "m1" in str(exc.value)


def test_gate_lists_all_excluded(tmp_path):
    run = tmp_path / "run"
    _write_chapter(run / "14_chapters/families/fam_a.md", "excluded_gaps_missing")
    _write_chapter(run / "14_chapters/methods/m1.md", "excluded_unsupported_claims")
    with pytest.raises(VerificationGateError) as exc:
        verification_gate(run)
    msg = str(exc.value)
    assert "fam_a" in msg and "m1" in msg
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_research_book_verification_gate.py -v`
Expected: FAIL.

- [ ] **Step 3: Add gate function**

In `swarn_research_mcp/research_book.py`, add:

```python
class VerificationGateError(RuntimeError):
    """Raised when one or more chapters have status: excluded_*."""


def verification_gate(run_dir: Path | str) -> None:
    """Block stage 18 if any chapter file's front-matter status starts with 'excluded_'.

    Raises VerificationGateError listing every offending {id, type, status, reason}.
    """
    run_path = Path(run_dir)
    offenders: list[dict[str, str]] = []
    for sub in ("families", "methods", "book"):
        d = run_path / "14_chapters" / sub
        if not d.exists():
            continue
        for path in sorted(d.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            front, _ = _split_front_matter(text)
            if not front:
                continue
            status = ""
            reason = ""
            for line in front.splitlines():
                line = line.strip()
                if line.startswith("status:"):
                    status = line.split(":", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("status_reason:"):
                    reason = line.split(":", 1)[1].strip().strip('"').strip("'")
            if status.startswith("excluded_"):
                offenders.append({"type": sub, "id": path.stem, "status": status, "reason": reason})

    if offenders:
        lines = [f"  - {o['type']}/{o['id']}: {o['status']} ({o['reason']})" for o in offenders]
        raise VerificationGateError(
            "verification gate blocked SUMMARY.md generation; excluded chapters:\n" + "\n".join(lines)
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_research_book_verification_gate.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_research_book_verification_gate.py swarn_research_mcp/research_book.py
git commit -m "feat(research-book): verification_gate raises VerificationGateError on excluded chapters"
```

---

## Task 5.2: Wire gate into `generate_book_artifacts`

**Files:**
- Modify: `swarn_research_mcp/research_book.py:638` (`generate_book_artifacts`)
- Test: extend `tests/test_research_book_verification_gate.py`

- [ ] **Step 1: Add gate call to generate_book_artifacts**

In `swarn_research_mcp/research_book.py::generate_book_artifacts` (around line 638), add as the FIRST line of the function body:

```python
    verification_gate(run_dir)
```

- [ ] **Step 2: Add integration test**

Append to `tests/test_research_book_verification_gate.py`:

```python
def test_generate_book_artifacts_blocks_on_excluded(tmp_path):
    from swarn_research_mcp.research_book import generate_book_artifacts
    run = tmp_path / "run"
    _write_chapter(run / "14_chapters/methods/m1.md", "excluded_unsupported_claims")
    with pytest.raises(VerificationGateError):
        generate_book_artifacts(run)
```

- [ ] **Step 3: Run test**

Run: `pytest tests/test_research_book_verification_gate.py -v`
Expected: PASS (5 tests).

- [ ] **Step 4: Commit**

```bash
git add tests/test_research_book_verification_gate.py swarn_research_mcp/research_book.py
git commit -m "feat(research-book): generate_book_artifacts blocks on verification_gate failure"
```

---

## Task 5.3: Update orchestrator SKILL with gate + fix_excluded loop

**Files:**
- Modify: `.agents/skills/auto-research-orchestrator/SKILL.md`

- [ ] **Step 1: Add gate at stage 18**

In `.agents/skills/auto-research-orchestrator/SKILL.md`, find the Stage table row for stage 18 (`16_book/SUMMARY.md`...) and immediately AFTER the table append:

```markdown
## Stage 18 verification gate
Before generating SUMMARY.md, call `verification_gate(run_dir)` (Python helper in `swarn_research_mcp.research_book`). If it raises, the run fails the `write` phase. The error message lists every chapter with `status: excluded_*`.
```

- [ ] **Step 2: Add fix_excluded sub-flag spec**

In the same file, find the `## Two-pass execution` section. Append a new top-level section:

```markdown
## phase=write,fix_excluded=true (retry loop)
When the operator re-launches with `phase=write fix_excluded=true`, the orchestrator:
1. Reads the offender list from the previous run's `15_verification/` outputs.
2. For each offender:
   - If `status_reason` is `gaps_missing`, re-dispatch stage 13 (pack rebuild) for that ID, then stage 14 for that ID.
   - If `status_reason` is `claims_unsupported`, re-dispatch stage 14 only with directive: drop or re-cite the offending claims.
3. Re-runs stage 15 verification on the affected chapters.
4. On still-failing chapters, fail hard with a final exclusion list (no second retry).
5. Records each fix attempt as a `run_log.csv` row: `stage,chapter_id,attempt,outcome`.
```

- [ ] **Step 3: Commit**

```bash
git add .agents/skills/auto-research-orchestrator/SKILL.md
git commit -m "docs(orchestrator): stage 18 verification gate + fix_excluded retry loop"
```

---

# Wave 6 — SDK session migration

## Task 6.1: Add `run_one_shot` to `sdk/codex.py`

**Files:**
- Test: `tests/test_sdk_run_one_shot.py` (create)
- Modify: `sdk/codex.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sdk_run_one_shot.py
from __future__ import annotations
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "sdk" / "codex.py"


def _load():
    spec = importlib.util.spec_from_file_location("sdk_codex_run_one_shot", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeThread:
    def __init__(self, responses):
        self._responses = list(responses)
        self.run = AsyncMock(side_effect=self._next)

    async def _next(self, _prompt):
        result = MagicMock()
        result.final_response = self._responses.pop(0)
        return result


class _FakeCodex:
    def __init__(self, thread):
        self._thread = thread
        self.thread_start = AsyncMock(return_value=thread)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


def test_run_one_shot_returns_string_when_no_schema():
    module = _load()
    fake = _FakeCodex(_FakeThread(["hello world"]))

    async def go():
        with patch.object(module, "AsyncCodex", return_value=fake):
            return await module.run_one_shot(prompt="say hi", model="m", system="be brief")

    out = asyncio.run(go())
    assert out == "hello world"


def test_run_one_shot_parses_json_with_schema():
    module = _load()
    fake = _FakeCodex(_FakeThread(['{"a": 1, "b": "x"}']))
    schema = {"type": "object", "required": ["a", "b"]}

    async def go():
        with patch.object(module, "AsyncCodex", return_value=fake):
            return await module.run_one_shot(prompt="p", model="m", system="s", schema=schema)

    out = asyncio.run(go())
    assert out == {"a": 1, "b": "x"}


def test_run_one_shot_retries_then_succeeds_on_bad_json():
    module = _load()
    fake = _FakeCodex(_FakeThread(["not json", '{"a": 1}']))
    schema = {"type": "object", "required": ["a"]}

    async def go():
        with patch.object(module, "AsyncCodex", return_value=fake):
            return await module.run_one_shot(prompt="p", model="m", system="s",
                                             schema=schema, max_parse_retries=1)

    out = asyncio.run(go())
    assert out == {"a": 1}


def test_run_one_shot_raises_after_max_retries():
    module = _load()
    fake = _FakeCodex(_FakeThread(["nope", "still nope"]))
    schema = {"type": "object", "required": ["a"]}

    async def go():
        with patch.object(module, "AsyncCodex", return_value=fake):
            await module.run_one_shot(prompt="p", model="m", system="s",
                                      schema=schema, max_parse_retries=1)

    with pytest.raises(ValueError, match="failed to parse"):
        asyncio.run(go())
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_sdk_run_one_shot.py -v`
Expected: FAIL — `run_one_shot` does not exist.

- [ ] **Step 3: Implement `run_one_shot` in sdk/codex.py**

In `sdk/codex.py`, after `build_config()` (line 43) and before `async def main`, add:

```python
import json as _json


async def run_one_shot(
    prompt: str,
    *,
    model: str,
    system: str,
    schema: dict | None = None,
    timeout: float = 120.0,
    max_parse_retries: int = 1,
) -> dict | str:
    """One input → one output via a fresh Codex thread.

    If schema is None, returns the model's final_response as a string.
    If schema is provided, parses the response as JSON; retries up to
    max_parse_retries on parse/validation failure, then raises ValueError.
    """
    config = build_config()
    last_err: Exception | None = None
    attempts = max_parse_retries + 1

    async with AsyncCodex(config=config) as codex:
        thread = await codex.thread_start(model=model)
        # Prepend system message into the first user prompt; AsyncCodex API
        # may not support a separate system field on thread_start.
        full_prompt = f"[SYSTEM]\n{system}\n\n[INPUT]\n{prompt}"
        if schema is not None:
            full_prompt += "\n\n[OUTPUT]\nReturn a single JSON object. No prose."

        for attempt in range(attempts):
            result = await asyncio.wait_for(thread.run(full_prompt), timeout=timeout)
            text = result.final_response
            if schema is None:
                return text
            try:
                parsed = _json.loads(text)
            except _json.JSONDecodeError as exc:
                last_err = exc
                full_prompt = (
                    f"[SYSTEM]\n{system}\n\n[INPUT]\n{prompt}\n\n"
                    f"[OUTPUT]\nYour previous response was not valid JSON. "
                    f"Return only a JSON object matching the schema. No prose."
                )
                continue
            # Minimal schema check: required keys present.
            required = schema.get("required", []) if isinstance(schema, dict) else []
            missing = [k for k in required if k not in parsed]
            if missing:
                last_err = ValueError(f"missing required fields: {missing}")
                full_prompt = (
                    f"[SYSTEM]\n{system}\n\n[INPUT]\n{prompt}\n\n"
                    f"[OUTPUT]\nYour previous response was missing required fields {missing}. "
                    f"Return a JSON object with all required fields."
                )
                continue
            return parsed

    raise ValueError(f"run_one_shot failed to parse after {attempts} attempts: {last_err}")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_sdk_run_one_shot.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_sdk_run_one_shot.py sdk/codex.py
git commit -m "feat(sdk): add run_one_shot for schema-validated single input/output Codex sessions"
```

---

## Task 6.2: Add `run_one_shot_batch`

**Files:**
- Test: extend `tests/test_sdk_run_one_shot.py`
- Modify: `sdk/codex.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sdk_run_one_shot.py`:

```python
def test_run_one_shot_batch_returns_results_in_order():
    module = _load()

    async def fake_run(prompt, *, model, system, schema=None, timeout=120, max_parse_retries=1):
        return {"echo": prompt}

    async def go():
        with patch.object(module, "run_one_shot", side_effect=fake_run):
            items = [{"prompt": "a"}, {"prompt": "b"}, {"prompt": "c"}]
            return await module.run_one_shot_batch(items, model="m", system="s",
                                                    schema={"type": "object"}, concurrency=2)

    out = asyncio.run(go())
    assert [r["echo"] for r in out] == ["a", "b", "c"]
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_sdk_run_one_shot.py::test_run_one_shot_batch_returns_results_in_order -v`
Expected: FAIL.

- [ ] **Step 3: Implement `run_one_shot_batch`**

Append to `sdk/codex.py` after `run_one_shot`:

```python
async def run_one_shot_batch(
    items: list[dict],
    *,
    model: str,
    system: str,
    schema: dict | None = None,
    concurrency: int = 4,
    timeout: float = 120.0,
) -> list[dict | str]:
    """Parallel one-shots. Each item must contain a 'prompt' key.

    Replaces sharded sub-agent dispatch for migrated stages. Order is preserved.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _one(item: dict) -> dict | str:
        async with sem:
            return await run_one_shot(
                prompt=item["prompt"],
                model=model,
                system=system,
                schema=schema,
                timeout=timeout,
            )

    return await asyncio.gather(*(_one(it) for it in items))
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_sdk_run_one_shot.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_sdk_run_one_shot.py sdk/codex.py
git commit -m "feat(sdk): add run_one_shot_batch for parallel single-shot Codex sessions"
```

---

## Task 6.3: Extract query_planner prompt to .md, delete .toml

**Files:**
- Create: `swarn_research_mcp/config/sdk_prompts/query_planner.md`
- Delete: `.codex/agents/query_planner.toml`

- [ ] **Step 1: Create the prompt file**

```bash
mkdir -p swarn_research_mcp/config/sdk_prompts
```

Write `swarn_research_mcp/config/sdk_prompts/query_planner.md` with the system body lifted from the TOML's `developer_instructions` field:

```markdown
Follow .agents/skills/query-planning/SKILL.md.

Inputs: run_id, topic, user_queries (optional), user_keywords (optional).

Steps:
1. Identify 4–6 distinct aspects of the topic across method families, architectural enablers, training/adaptation, evaluation, foundational priors, boundary aspects (skip axes that don't apply).
2. Per aspect: 2–3 normal_queries, 1 survey_query, 3–5 positive_keywords, optional negative_keywords.
3. Add global_negative_keywords (3–8) that exclude noise across all aspects.
4. If user_queries / user_keywords were supplied, include them verbatim in the most relevant aspect.
5. Return a JSON object matching the search_plan schema.

Hard rules:
- Aspects are distinct — merge any pair that would share > 50% of queries.
- Total normal_queries ≤ 15 and total survey_queries ≤ 6 across all aspects.
- Plain-phrase queries only (no operators / quotes).
- Never invent specific papers, methods, or numbers.

Return: a single JSON object with keys `aspects` (list) and `global_negative_keywords` (list of strings).
```

- [ ] **Step 2: Delete the TOML**

```bash
git rm .codex/agents/query_planner.toml
```

- [ ] **Step 3: Commit**

```bash
git add swarn_research_mcp/config/sdk_prompts/query_planner.md
git commit -m "refactor(query_planner): move prompt from .toml sub-agent to sdk_prompts/"
```

---

## Task 6.4: Migrate knowledge_gap_detector

**Files:**
- Create: `swarn_research_mcp/config/sdk_prompts/knowledge_gap_detector.md`
- Delete: `.codex/agents/knowledge_gap_detector.toml`

- [ ] **Step 1: Read the TOML to extract instructions**

Run: `cat /home/nguyen/code/swarn_auto_research/.codex/agents/knowledge_gap_detector.toml`

- [ ] **Step 2: Write the prompt .md**

Write `swarn_research_mcp/config/sdk_prompts/knowledge_gap_detector.md` containing the `developer_instructions` block from the TOML, with the closing line replaced by:

```markdown
Return: a single JSON object matching the gap-report schema with keys `gaps` (list) and `expansion_need_queue` (list).
```

- [ ] **Step 3: Delete the TOML and commit**

```bash
git rm .codex/agents/knowledge_gap_detector.toml
git add swarn_research_mcp/config/sdk_prompts/knowledge_gap_detector.md
git commit -m "refactor(knowledge_gap_detector): migrate from sub-agent to sdk_prompts/"
```

---

## Task 6.5: Migrate paper_ranker

**Files:**
- Create: `swarn_research_mcp/config/sdk_prompts/paper_ranker.md`
- Delete: `.codex/agents/paper_ranker.toml`

- [ ] **Step 1: Read the TOML, write the .md, delete the TOML**

```bash
cat /home/nguyen/code/swarn_auto_research/.codex/agents/paper_ranker.toml
```

Write `swarn_research_mcp/config/sdk_prompts/paper_ranker.md` with the `developer_instructions` content. End with:

```markdown
Return: a single JSON object with key `ranked_papers` (list of {arxiv_id, final_score, reasoning}).
```

```bash
git rm .codex/agents/paper_ranker.toml
git add swarn_research_mcp/config/sdk_prompts/paper_ranker.md
git commit -m "refactor(paper_ranker): migrate from sub-agent to sdk_prompts/"
```

---

## Task 6.6: Migrate outline_planner

**Files:**
- Create: `swarn_research_mcp/config/sdk_prompts/outline_planner.md`
- Delete: `.codex/agents/outline_planner.toml`

- [ ] **Step 1: Read TOML, write .md, delete TOML, commit**

```bash
cat /home/nguyen/code/swarn_auto_research/.codex/agents/outline_planner.toml
```

Write `swarn_research_mcp/config/sdk_prompts/outline_planner.md` with `developer_instructions`. End with:

```markdown
Return: a single JSON object matching the outline.json schema in .agents/skills/taxonomy-building/SKILL.md (keys: topic, book_sections, parts, families, methods).
```

```bash
git rm .codex/agents/outline_planner.toml
git add swarn_research_mcp/config/sdk_prompts/outline_planner.md
git commit -m "refactor(outline_planner): migrate from sub-agent to sdk_prompts/"
```

---

## Task 6.7: Migrate chapter_manifest_builder

**Files:**
- Create: `swarn_research_mcp/config/sdk_prompts/chapter_manifest_builder.md`
- Delete: `.codex/agents/chapter_manifest_builder.toml`

- [ ] **Step 1: Read TOML, write .md, delete TOML, commit**

```bash
cat /home/nguyen/code/swarn_auto_research/.codex/agents/chapter_manifest_builder.toml
```

Write `swarn_research_mcp/config/sdk_prompts/chapter_manifest_builder.md`. End with:

```markdown
Return: a single JSON object with keys `book` (list of section_ids), `families` (list of family_ids), `methods` (list of method_ids).
```

```bash
git rm .codex/agents/chapter_manifest_builder.toml
git add swarn_research_mcp/config/sdk_prompts/chapter_manifest_builder.md
git commit -m "refactor(chapter_manifest_builder): migrate from sub-agent to sdk_prompts/"
```

---

## Task 6.8: Update orchestrator SKILL with sdk_stages dispatch table

**Files:**
- Modify: `.agents/skills/auto-research-orchestrator/SKILL.md`

- [ ] **Step 1: Add an SDK-dispatch section**

In `.agents/skills/auto-research-orchestrator/SKILL.md`, after the `## Sharded parallel execution` section, append:

```markdown
## SDK-dispatched stages (in-process, not sub-agent)
The following stages run via `sdk.codex.run_one_shot` (or `run_one_shot_batch` for sharded inputs). Their `.codex/agents/*.toml` files have been deleted; the prompt lives in `swarn_research_mcp/config/sdk_prompts/{stage}.md`.

| Stage | Stage name              | Prompt file                                  | Model         | Sharded? |
|-------|-------------------------|----------------------------------------------|---------------|----------|
| 1     | query_planner           | sdk_prompts/query_planner.md                 | gpt-5.4-mini  | no       |
| 5     | knowledge_gap_detector  | sdk_prompts/knowledge_gap_detector.md        | gpt-5.4-mini  | no       |
| 7     | paper_ranker            | sdk_prompts/paper_ranker.md                  | gpt-5.4-mini  | yes      |
| 12    | outline_planner         | sdk_prompts/outline_planner.md               | gpt-5.4-mini  | no       |
| 16    | chapter_manifest_builder| sdk_prompts/chapter_manifest_builder.md      | gpt-5.4-mini  | no       |

Dispatch contract:
- Read the prompt file as system text.
- Build the input as a JSON object containing only the inputs the stage needs.
- Call `await run_one_shot(prompt=json.dumps(input), model=model, system=prompt_text, schema=stage_schema)`.
- Write the returned JSON to the canonical artifact path.
- The two-pass `phase=draft|write` workaround does NOT apply to SDK-dispatched stages — they pin their own model. Operator may run all SDK stages in either parent session.
```

- [ ] **Step 2: Update Stage table to mark SDK stages**

In the Stage/Primary-artifact table at the top of the file, add a `sdk` column or annotate the SDK-dispatched stages with `(SDK)` after the artifact path. For example:
```markdown
| 1  | `00_input/search_plan.json` and `02_paper_pool/paper_pool.json` (stage 1 part: SDK) |
| 5  | `06_expansion/knowledge_gap_report.json` + `expansion_need_queue.json` (SDK) |
| 7  | `07_scoring/promoted_papers.json` (SDK, sharded) |
| 12 | `12_taxonomy/outline.json` (SDK; three-tier with parts) |
| 16 | every chapter file has YAML front matter + `16_book/chapters_manifest.json` (SDK builds manifest) |
```

- [ ] **Step 3: Commit**

```bash
git add .agents/skills/auto-research-orchestrator/SKILL.md
git commit -m "docs(orchestrator): document SDK-dispatched stages 1, 5, 7, 12, 16"
```

---

## Task 6.9: Smoke test on cheapest migrated stage

**Files:** none modified.

- [ ] **Step 1: Run a real query_planner SDK call**

Operator-run check (not automated): in a Python REPL, run:

```python
import asyncio, json
from sdk.codex import run_one_shot

prompt = open("swarn_research_mcp/config/sdk_prompts/query_planner.md").read()
result = asyncio.run(run_one_shot(
    prompt=json.dumps({"topic": "transformer attention variants"}),
    system=prompt,
    model="gpt-5.4-mini",
    schema={"type": "object", "required": ["aspects", "global_negative_keywords"]},
))
print(json.dumps(result, indent=2))
```

Expected: a JSON object with `aspects` and `global_negative_keywords`.

- [ ] **Step 2: Verify model honoring**

Inspect Codex's debug logs (or `result` metadata if available) to confirm the model used was `gpt-5.4-mini` regardless of the parent shell's model. If the model bug applies, document it in the orchestrator SKILL under `## SDK-dispatched stages` and keep stages in `phase=draft`. If it does not apply, no action.

- [ ] **Step 3: Commit any documentation update**

```bash
git add .agents/skills/auto-research-orchestrator/SKILL.md
git commit -m "docs(orchestrator): note SDK model-honoring observed behavior"
```

(Skip commit if no doc change needed.)

---

# Final Validation

## Task F.1: Run full test suite

- [ ] **Step 1: Run all tests**

Run: `pytest tests/ -v`
Expected: all tests pass; new tests added in this plan are green.

- [ ] **Step 2: Run validator on existing voice-LM run as a regression check**

Run: `python -c "from swarn_research_mcp.research_book import validate_research_book_run; import json; print(json.dumps(validate_research_book_run('research_runs/voice-language-model-text-speech-io-20260509-222749'), indent=2))"`

Expected: surfaces issues (`missing_parts`, `singleton_family`, `wrong_chapter_headings`) — confirming the validator catches all the gaps the audit found. (We are NOT migrating the existing run, only confirming the validator works.)

- [ ] **Step 3: Commit any test fixups**

```bash
git status
# if no changes, skip
```

---

# Self-Review Notes

Spec coverage:
- §1 parts → Task 1.1 (validator), 1.3 (skill)
- §2 singleton merge → Task 1.2 (validator), 1.3 (skill)
- §3 family headings → Task 3.1 (validator), 3.2 (skill)
- §4 method headings → Task 3.1 (validator), 3.3 (skill)
- §5 verification gate → Task 5.1, 5.2, 5.3
- §6a bibliography bug → Task 2.1, 2.2, 2.3
- §6b goals → Task 4.1
- §6c appendices → Task 4.2, 4.3
- §7 SDK migration → Task 6.1–6.9

All seven sections covered.

Type consistency:
- `MissingCitationError` defined in Task 2.1, used in Task 2.2 ✓
- `VerificationGateError` defined in Task 5.1, used in Task 5.2 ✓
- `run_one_shot` signature in Task 6.1 matches usage in Task 6.2's `run_one_shot_batch` and Task 6.9 smoke test ✓
- `_build_appendices_dir` replaces `_build_appendices` cleanly (Task 4.2 step 5 removes the old function) ✓
