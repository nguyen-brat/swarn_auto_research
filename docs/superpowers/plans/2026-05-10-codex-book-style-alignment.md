# Codex Pipeline Book_style Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring auto-research pipeline output into structural agreement with `Book_style.md`, deterministically normalize the taxonomy, fix the `<title unknown>` bibliography bug, and enforce verification as a hard gate (with a `NEEDS_REVIEW.md` fallback artifact).

**Architecture:** SKILL contracts under `.agents/skills/` define the per-stage behavior. `swarn_research_mcp/research_book.py` provides validators, deterministic post-processors, and the book-artifact generator. We tighten the SKILL contracts and add deterministic Python that runs in `generate_book_artifacts` so the agent's output is normalized regardless of small contract drift.

**Tech Stack:** Python 3.11 (pytest), markdown SKILL contracts, JSON artifacts under `research_runs/{run_id}/`.

**Spec:** `docs/superpowers/specs/2026-05-10-codex-book-style-alignment-design.md`

**Out of scope (separate plan):** SDK session migration. See `2026-05-10-codex-sdk-context-relief-pilot.md`.

---

## File Map

**Modify:**
- `.agents/skills/taxonomy-building/SKILL.md` — parts step + singleton-merge rule (deterministic post-processor backs it up)
- `.agents/skills/family-chapter-writing/SKILL.md` — Book_style 10-section template
- `.agents/skills/method-chapter-writing/SKILL.md` — rename Example→Worked Example, Software→Practical Guidance
- `.agents/skills/book-section-writing/SKILL.md` — bibliography rule, goals rules, appendices directory
- `.agents/skills/auto-research-orchestrator/SKILL.md` — verification gate, fix_excluded loop
- `swarn_research_mcp/research_book.py` — multi-shape `_paper_lookup`, strict `resolve_paper_citation`, deterministic `merge_singletons`, `verification_gate` + `NEEDS_REVIEW.md` emitter, appendices directory builder, `BOOK_FILE_BY_ID` switch, heading lint with diagnostics

**Create:**
- `tests/fixtures/voice_lm_minimal/` — real-shape fixture mirroring the audited run's quirks (list-shaped paper_pool, semantic_scholar metadata-only, mixed status chapters)
- `tests/test_research_book_paper_lookup.py`
- `tests/test_research_book_parts.py`
- `tests/test_research_book_singleton_merge.py`
- `tests/test_research_book_bibliography.py`
- `tests/test_research_book_chapter_headings.py`
- `tests/test_research_book_verification_gate.py`
- `tests/test_research_book_appendices_dir.py`

**Delete:**
- nothing in this plan (`.toml` deletions are deferred to the SDK pilot plan)

---

# Wave 0 — Real-shape test fixture

The audit found that `_paper_lookup` silently ignores list-shaped `paper_pool.json`, that the audited run kept titles only in `03_overviews/semantic_scholar/`, and that several chapter files have `status: excluded_*`. Subsequent waves need a fixture mirroring these quirks.

## Task 0.1: Build the `voice_lm_minimal` fixture

**Files:**
- Create: `tests/fixtures/voice_lm_minimal/{02_paper_pool/paper_pool.json,03_overviews/semantic_scholar/2301.02111.json,04_weak_evidence/2301.02111.json,06_expansion/known_concepts_snapshot.json,07_scoring/promoted_papers.json,12_taxonomy/outline.json,13_chapter_packs/methods/m_valle_pack.json,14_chapters/book/00_preface.md,14_chapters/book/04_method_taxonomy.md,14_chapters/families/fam_codec.md,14_chapters/methods/m_valle.md,14_chapters/methods/m_excluded.md,15_verification/methods/m_excluded_verification.json}`

- [ ] **Step 1: Create the fixture directory tree**

```bash
mkdir -p tests/fixtures/voice_lm_minimal/{02_paper_pool,03_overviews/semantic_scholar,04_weak_evidence,06_expansion,07_scoring,12_taxonomy,13_chapter_packs/methods,14_chapters/book,14_chapters/families,14_chapters/methods,15_verification/methods,16_book}
```

- [ ] **Step 2: Write `paper_pool.json` as a LIST (the audited run's actual shape)**

Write `tests/fixtures/voice_lm_minimal/02_paper_pool/paper_pool.json`:
```json
[
  {"arxiv_id": "2301.02111"},
  {"arxiv_id": "2406.18009"}
]
```

(No title/year — exactly the gap that produced `<title unknown>`.)

- [ ] **Step 3: Write semantic_scholar metadata files**

Write `tests/fixtures/voice_lm_minimal/03_overviews/semantic_scholar/2301.02111.json`:
```json
{"arxiv_id": "2301.02111", "title": "VALL-E: Neural Codec Language Models", "year": 2023}
```

Write `tests/fixtures/voice_lm_minimal/03_overviews/semantic_scholar/2406.18009.json`:
```json
{"arxiv_id": "2406.18009", "title": "Voicebox", "year": 2024}
```

- [ ] **Step 4: Write weak evidence (alternate metadata source)**

Write `tests/fixtures/voice_lm_minimal/04_weak_evidence/2301.02111.json`:
```json
{"arxiv_id": "2301.02111", "title": "VALL-E", "year": 2023, "paper_type": "method", "importance_score": 0.9}
```

- [ ] **Step 5: Write outline.json — has a singleton family AND no `parts` field**

Write `tests/fixtures/voice_lm_minimal/12_taxonomy/outline.json`:
```json
{
  "topic": "voice language models",
  "book_sections": [
    {"id": "preface", "title": "Preface"},
    {"id": "motivating_intro", "title": "Motivating Introduction"},
    {"id": "core_concepts", "title": "Core Concepts"},
    {"id": "goals", "title": "Goals"},
    {"id": "method_taxonomy", "title": "Method Taxonomy"},
    {"id": "shared_examples", "title": "Shared Examples"},
    {"id": "evaluation_outlook", "title": "Evaluation and Outlook"},
    {"id": "appendices", "title": "Appendices"}
  ],
  "families": [
    {"id": "fam_codec", "title": "discrete codec tokens", "method_ids": ["m_valle"], "neighbor_family_ids": ["fam_flow"]},
    {"id": "fam_flow", "title": "flow matching", "method_ids": ["m_voicebox", "m_excluded"], "neighbor_family_ids": ["fam_codec"]}
  ],
  "methods": [
    {"id": "m_valle", "title": "VALL-E", "arxiv_id": "2301.02111", "family_id": "fam_codec", "neighbor_method_ids": ["m_voicebox"]},
    {"id": "m_voicebox", "title": "Voicebox", "arxiv_id": "2406.18009", "family_id": "fam_flow", "neighbor_method_ids": ["m_valle"]},
    {"id": "m_excluded", "title": "Broken Method", "arxiv_id": "2301.02111", "family_id": "fam_flow", "neighbor_method_ids": []}
  ]
}
```

(Note: `fam_codec` is a singleton; `m_excluded` shares an arxiv_id with `m_valle` to test duplicate detection.)

- [ ] **Step 6: Write promoted_papers.json**

Write `tests/fixtures/voice_lm_minimal/07_scoring/promoted_papers.json`:
```json
{"promoted_papers": [
  {"arxiv_id": "2301.02111"},
  {"arxiv_id": "2406.18009"}
]}
```

- [ ] **Step 7: Write known_concepts_snapshot.json**

Write `tests/fixtures/voice_lm_minimal/06_expansion/known_concepts_snapshot.json`:
```json
{"known_concepts": [
  {"name": "transformer", "definition": "stack of self-attention blocks"},
  {"name": "tokenizer", "definition": "discretizer mapping signal to symbols"}
]}
```

- [ ] **Step 8: Write a method pack with structured fields for appendices testing**

Write `tests/fixtures/voice_lm_minimal/13_chapter_packs/methods/m_valle_pack.json`:
```json
{
  "method_id": "m_valle",
  "structured": {
    "equations": [{"latex": "p(c|x)", "symbols": [{"name": "c", "description": "codec token"}]}],
    "datasets": [{"name": "LibriSpeech"}],
    "artifacts": [{"name": "EnCodec"}, {"name": "WavLM-TDNN"}]
  }
}
```

- [ ] **Step 9: Write chapter files with mixed statuses and mixed heading shapes**

Write `tests/fixtures/voice_lm_minimal/14_chapters/families/fam_codec.md`:
```markdown
---
chapter_id: fam_codec
chapter_type: family
status: passed
---
# discrete codec tokens

## What this family is
Old skill heading; the lint should flag this.

## Core design pattern
text
```

Write `tests/fixtures/voice_lm_minimal/14_chapters/methods/m_valle.md`:
```markdown
---
chapter_id: m_valle
chapter_type: method
status: passed
---
# VALL-E

## Summary
text

## Motivation
text

## Intuition
text

## Theory
text

## Algorithm
text

## Example
old heading

## Interpretation
text

## Strengths
text

## Limitations
text

## Software
old heading

## Related Methods
text
```

Write `tests/fixtures/voice_lm_minimal/14_chapters/methods/m_excluded.md`:
```markdown
---
chapter_id: m_excluded
chapter_type: method
status: excluded_unsupported_claims
status_reason: "claims_unsupported=3"
---
# Broken Method

## Summary
text
```

Write `tests/fixtures/voice_lm_minimal/14_chapters/book/00_preface.md`:
```markdown
---
chapter_id: preface
chapter_type: book
status: passed
---
# Preface

text
```

Write `tests/fixtures/voice_lm_minimal/14_chapters/book/04_method_taxonomy.md`:
```markdown
# Method Taxonomy

placeholder; replaced by deterministic generator in tests
```

- [ ] **Step 10: Write a verification artifact for the excluded chapter**

Write `tests/fixtures/voice_lm_minimal/15_verification/methods/m_excluded_verification.json`:
```json
{"chapter_id": "m_excluded", "status": "excluded_unsupported_claims", "claims_unsupported": 3, "form_issues": []}
```

- [ ] **Step 11: Add a fixture loader to conftest**

In `tests/conftest.py`, append:
```python
import shutil
from pathlib import Path
import pytest


@pytest.fixture
def voice_lm_minimal(tmp_path):
    """Copy the voice_lm_minimal fixture to a tmp dir; tests can mutate freely."""
    src = Path(__file__).parent / "fixtures" / "voice_lm_minimal"
    dst = tmp_path / "run"
    shutil.copytree(src, dst)
    return dst
```

- [ ] **Step 12: Commit**

```bash
git add tests/fixtures/voice_lm_minimal tests/conftest.py
git commit -m "test(fixture): voice_lm_minimal mirrors real run quirks (list paper_pool, ss metadata, excluded chapter)"
```

---

# Wave 1 — Taxonomy: parts + deterministic singleton merge

## Task 1.1: Multi-shape `_paper_lookup` + strict `resolve_paper_citation`

**Files:**
- Test: `tests/test_research_book_paper_lookup.py` (create)
- Modify: `swarn_research_mcp/research_book.py:80-101` (`_paper_lookup`), add `resolve_paper_citation` + `MissingCitationError`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_research_book_paper_lookup.py
from __future__ import annotations
import json
from pathlib import Path
import pytest
from swarn_research_mcp.research_book import (
    _paper_lookup,
    resolve_paper_citation,
    MissingCitationError,
)


def _scaffold(tmp_path, pool_payload, ss_records=None):
    run = tmp_path / "run"
    (run / "02_paper_pool").mkdir(parents=True)
    (run / "02_paper_pool" / "paper_pool.json").write_text(json.dumps(pool_payload))
    if ss_records:
        (run / "03_overviews" / "semantic_scholar").mkdir(parents=True)
        for rec in ss_records:
            (run / "03_overviews" / "semantic_scholar" / f"{rec['arxiv_id']}.json").write_text(json.dumps(rec))
    return run


def test_paper_lookup_handles_dict_shape(tmp_path):
    run = _scaffold(tmp_path, {"2301.02111": {"title": "VALL-E", "year": 2023}})
    assert _paper_lookup(run)["2301.02111"]["title"] == "VALL-E"


def test_paper_lookup_handles_list_shape(tmp_path):
    run = _scaffold(tmp_path, [
        {"arxiv_id": "2301.02111", "title": "VALL-E", "year": 2023},
    ])
    assert _paper_lookup(run)["2301.02111"]["title"] == "VALL-E"


def test_paper_lookup_handles_papers_key_shape(tmp_path):
    run = _scaffold(tmp_path, {"papers": [
        {"arxiv_id": "2301.02111", "title": "VALL-E", "year": 2023},
    ]})
    assert _paper_lookup(run)["2301.02111"]["title"] == "VALL-E"


def test_paper_lookup_falls_back_to_semantic_scholar(tmp_path):
    """List pool with no title/year — semantic_scholar provides them."""
    run = _scaffold(
        tmp_path,
        [{"arxiv_id": "2301.02111"}],
        ss_records=[{"arxiv_id": "2301.02111", "title": "VALL-E", "year": 2023}],
    )
    pool = _paper_lookup(run)
    assert pool["2301.02111"]["title"] == "VALL-E"
    assert pool["2301.02111"]["year"] == 2023


def test_resolve_paper_citation_returns_full_record(voice_lm_minimal):
    cite = resolve_paper_citation(voice_lm_minimal, "2301.02111")
    assert cite["title"] == "VALL-E: Neural Codec Language Models"
    assert cite["year"] == 2023


def test_resolve_paper_citation_raises_on_unknown_arxiv(voice_lm_minimal):
    with pytest.raises(MissingCitationError, match="9999.99999"):
        resolve_paper_citation(voice_lm_minimal, "9999.99999")


def test_resolve_paper_citation_raises_on_missing_title(tmp_path):
    run = _scaffold(tmp_path, [{"arxiv_id": "2301.02111", "year": 2023}])
    with pytest.raises(MissingCitationError, match="title"):
        resolve_paper_citation(run, "2301.02111")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_research_book_paper_lookup.py -v`
Expected: FAIL — list/papers shape ignored; `resolve_paper_citation` doesn't exist.

- [ ] **Step 3: Update `_paper_lookup` to accept all three shapes**

In `swarn_research_mcp/research_book.py`, replace the body of `_paper_lookup` (lines 80–101) with:

```python
def _paper_lookup(run_dir: Path) -> dict[str, dict[str, Any]]:
    path = run_dir / "02_paper_pool" / "paper_pool.json"
    lookup: dict[str, dict[str, Any]] = {}
    if path.exists():
        data = _load_json(path)
        records: list[dict[str, Any]] = []
        if isinstance(data, dict):
            if isinstance(data.get("papers"), list):
                records = [r for r in data["papers"] if isinstance(r, dict)]
            else:
                # legacy {arxiv_id: {...}} shape
                for arxiv_id, record in data.items():
                    if isinstance(record, dict):
                        merged = dict(record)
                        merged.setdefault("arxiv_id", arxiv_id)
                        records.append(merged)
        elif isinstance(data, list):
            records = [r for r in data if isinstance(r, dict)]
        for record in records:
            arxiv_id = record.get("arxiv_id")
            if not arxiv_id:
                continue
            lookup[arxiv_id] = dict(record)
    for directory in (run_dir / "03_overviews" / "semantic_scholar", run_dir / "04_weak_evidence"):
        if not directory.exists():
            continue
        for metadata_path in directory.glob("*.json"):
            record = _load_json(metadata_path)
            if not isinstance(record, dict):
                continue
            arxiv_id = record.get("arxiv_id") or metadata_path.stem
            merged = dict(lookup.get(arxiv_id, {}))
            for key in ("title", "year"):
                if record.get(key) and not merged.get(key):
                    merged[key] = record[key]
            lookup[arxiv_id] = merged
    return lookup
```

- [ ] **Step 4: Add `MissingCitationError` and `resolve_paper_citation`**

After `_paper_label` (around line 106), append:

```python
class MissingCitationError(LookupError):
    """Raised when a cited arxiv_id cannot be resolved to title+year."""


def resolve_paper_citation(run_dir: Path | str, arxiv_id: str) -> dict[str, Any]:
    """Resolve {arxiv_id, title, year} from paper_pool + semantic_scholar + weak_evidence.

    Raises MissingCitationError if any of the sources lack a non-empty title or year.
    """
    pool = _paper_lookup(Path(run_dir))
    record = pool.get(arxiv_id)
    if record is None:
        raise MissingCitationError(f"arxiv_id {arxiv_id} not found in paper_pool / overviews / weak_evidence")
    title = record.get("title") or ""
    year = record.get("year")
    if not title or year in (None, "", 0):
        raise MissingCitationError(
            f"arxiv_id {arxiv_id} missing title or year (title={title!r}, year={year!r})"
        )
    return {"arxiv_id": arxiv_id, "title": title, "year": year}
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_research_book_paper_lookup.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add tests/test_research_book_paper_lookup.py swarn_research_mcp/research_book.py
git commit -m "fix(research-book): _paper_lookup handles list/dict/papers shapes; add resolve_paper_citation"
```

---

## Task 1.2: Update `_paper_label` + bibliography paths to use strict resolver

**Files:**
- Modify: `swarn_research_mcp/research_book.py:103` (`_paper_label`)

- [ ] **Step 1: Tighten `_paper_label` to fail loud rather than emit `<title unknown>`**

Replace `_paper_label` (lines 103–108) with:

```python
def _paper_label(arxiv_id: str, promoted: dict[str, dict[str, Any]], pool: dict[str, dict[str, Any]]) -> str:
    promoted_record = promoted.get(arxiv_id) or {}
    pool_record = pool.get(arxiv_id) or {}
    title = promoted_record.get("title") or pool_record.get("title")
    year = promoted_record.get("year") or pool_record.get("year")
    if not title or year in (None, "", 0):
        raise MissingCitationError(
            f"_paper_label cannot render {arxiv_id}: title={title!r}, year={year!r}. "
            "Add title/year to paper_pool, semantic_scholar overviews, or weak_evidence."
        )
    return f"[arxiv:{arxiv_id}] {title} ({year})"
```

- [ ] **Step 2: Add a test asserting the loud failure**

Append to `tests/test_research_book_paper_lookup.py`:

```python
def test_paper_label_raises_on_missing_title(tmp_path):
    from swarn_research_mcp.research_book import _paper_label
    pool = {"2301.02111": {"arxiv_id": "2301.02111"}}  # no title/year
    with pytest.raises(MissingCitationError):
        _paper_label("2301.02111", promoted={}, pool=pool)
```

Run: `pytest tests/test_research_book_paper_lookup.py -v`
Expected: PASS (8 tests).

- [ ] **Step 3: Update callers of `_paper_label` to surface the error context**

Search for uses: `grep -n "_paper_label(" swarn_research_mcp/research_book.py`. Each caller should let `MissingCitationError` propagate. If any caller previously expected a string fallback, wrap with a helpful message:

```python
try:
    label = _paper_label(arxiv_id, promoted, pool)
except MissingCitationError as exc:
    raise MissingCitationError(f"appendices/references generation blocked: {exc}") from exc
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_research_book_paper_lookup.py swarn_research_mcp/research_book.py
git commit -m "fix(research-book): _paper_label fails loud instead of emitting <title unknown>"
```

---

## Task 1.3: Add `parts` validator

**Files:**
- Test: `tests/test_research_book_parts.py` (create)
- Modify: `swarn_research_mcp/research_book.py` (extend `validate_research_book_run`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_research_book_parts.py
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
    _set_outline(voice_lm_minimal, _add_parts(outline, [
        {"id": "p1", "title": "P1", "family_ids": ["fam_codec", "fam_flow"]},
    ]))
    issues = validate_research_book_run(voice_lm_minimal)
    assert any(i["code"] == "parts_count_out_of_range" for i in issues)


def test_family_in_two_parts(voice_lm_minimal):
    outline = json.loads((voice_lm_minimal / "12_taxonomy" / "outline.json").read_text())
    _set_outline(voice_lm_minimal, _add_parts(outline, [
        {"id": "p1", "title": "P1", "family_ids": ["fam_codec", "fam_flow"]},
        {"id": "p2", "title": "P2", "family_ids": ["fam_flow"]},
    ]))
    issues = validate_research_book_run(voice_lm_minimal)
    assert any(i["code"] == "family_in_multiple_parts" and "fam_flow" in i["detail"] for i in issues)


def test_family_unassigned_to_part(voice_lm_minimal):
    outline = json.loads((voice_lm_minimal / "12_taxonomy" / "outline.json").read_text())
    _set_outline(voice_lm_minimal, _add_parts(outline, [
        {"id": "p1", "title": "P1", "family_ids": ["fam_codec"]},
        {"id": "p2", "title": "P2", "family_ids": []},
    ]))
    issues = validate_research_book_run(voice_lm_minimal)
    assert any(i["code"] == "family_unassigned_to_part" and "fam_flow" in i["detail"] for i in issues)


def test_valid_parts(voice_lm_minimal):
    outline = json.loads((voice_lm_minimal / "12_taxonomy" / "outline.json").read_text())
    _set_outline(voice_lm_minimal, _add_parts(outline, [
        {"id": "p1", "title": "P1", "family_ids": ["fam_codec"]},
        {"id": "p2", "title": "P2", "family_ids": ["fam_flow"]},
    ]))
    issues = validate_research_book_run(voice_lm_minimal)
    parts_codes = {"missing_parts", "parts_count_out_of_range",
                   "family_in_multiple_parts", "family_unassigned_to_part"}
    assert not any(i["code"] in parts_codes for i in issues)
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_research_book_parts.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `_validate_parts`**

In `swarn_research_mcp/research_book.py`, add above `validate_research_book_run` (around line 175):

```python
def _validate_parts(outline: dict[str, Any], families: list[dict[str, Any]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    parts = outline.get("parts")
    if parts is None:
        issues.append({"severity": "error", "code": "missing_parts",
                       "detail": "outline.json must define a 'parts' array (2..5 entries)"})
        return issues
    if not isinstance(parts, list) or not (2 <= len(parts) <= 5):
        n = len(parts) if isinstance(parts, list) else "non-list"
        issues.append({"severity": "error", "code": "parts_count_out_of_range",
                       "detail": f"parts must have 2..5 entries, got {n}"})
        return issues
    family_ids = {f.get("id") for f in families if f.get("id")}
    seen_in: dict[str, str] = {}
    for part in parts:
        pid = part.get("id", "")
        for fid in part.get("family_ids", []) or []:
            if fid in seen_in:
                issues.append({"severity": "error", "code": "family_in_multiple_parts",
                               "detail": f"family {fid} appears in parts {seen_in[fid]} and {pid}"})
            else:
                seen_in[fid] = pid
    for fid in family_ids:
        if fid not in seen_in:
            issues.append({"severity": "error", "code": "family_unassigned_to_part",
                           "detail": f"family {fid} is not in any part"})
    return issues
```

In `validate_research_book_run`, after `families = outline.get("families", [])` (around line 185), append:
```python
    issues.extend(_validate_parts(outline, families))
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_research_book_parts.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_research_book_parts.py swarn_research_mcp/research_book.py
git commit -m "feat(research-book): validate outline.json parts (2..5, exclusive coverage of families)"
```

---

## Task 1.4: Deterministic singleton-merge post-processor

**Files:**
- Test: `tests/test_research_book_singleton_merge.py` (create)
- Modify: `swarn_research_mcp/research_book.py` (add `merge_singletons`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_research_book_singleton_merge.py
from __future__ import annotations
import json
from swarn_research_mcp.research_book import merge_singletons


BOOK_SECTIONS = [{"id": k, "title": k} for k in
    ["preface", "motivating_intro", "core_concepts", "goals", "method_taxonomy",
     "shared_examples", "evaluation_outlook", "appendices"]]


def _outline(families, methods, parts=None):
    return {"topic": "t", "book_sections": BOOK_SECTIONS,
            "families": families, "methods": methods,
            "parts": parts or [{"id": "p1", "title": "P1", "family_ids": [f["id"] for f in families]},
                                {"id": "p2", "title": "P2", "family_ids": []}]}


def test_singleton_merges_into_neighbor_with_shared_neighbor():
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["m1"], "neighbor_family_ids": ["fam_b"]},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"], "neighbor_family_ids": ["fam_a"]},
    ]
    methods = [
        {"id": "m1", "arxiv_id": "1.1", "family_id": "fam_a", "neighbor_method_ids": ["m2"]},
        {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b", "neighbor_method_ids": ["m1", "m3"]},
        {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b", "neighbor_method_ids": ["m2"]},
    ]
    merged = merge_singletons(_outline(families, methods))
    family_by_id = {f["id"]: f for f in merged["families"]}
    assert "fam_a" not in family_by_id
    assert sorted(family_by_id["fam_b"]["method_ids"]) == ["m1", "m2", "m3"]


def test_singleton_with_no_neighbors_lands_in_catchall():
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["m1"], "neighbor_family_ids": []},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"], "neighbor_family_ids": []},
    ]
    methods = [
        {"id": "m1", "arxiv_id": "1.1", "family_id": "fam_a", "neighbor_method_ids": []},
        {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b", "neighbor_method_ids": ["m3"]},
        {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b", "neighbor_method_ids": ["m2"]},
    ]
    parts = [{"id": "p1", "title": "P1", "family_ids": ["fam_a"]},
             {"id": "p2", "title": "P2", "family_ids": ["fam_b"]}]
    merged = merge_singletons(_outline(families, methods, parts))
    assert any(f["id"] == "other_p1" and f["method_ids"] == ["m1"] for f in merged["families"])
    parts_lookup = {p["id"]: p for p in merged["parts"]}
    assert "other_p1" in parts_lookup["p1"]["family_ids"]


def test_method_family_id_updated_after_merge():
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["m1"], "neighbor_family_ids": ["fam_b"]},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"], "neighbor_family_ids": ["fam_a"]},
    ]
    methods = [
        {"id": "m1", "arxiv_id": "1.1", "family_id": "fam_a", "neighbor_method_ids": ["m2"]},
        {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b", "neighbor_method_ids": ["m1"]},
        {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b", "neighbor_method_ids": []},
    ]
    merged = merge_singletons(_outline(families, methods))
    method_by_id = {m["id"]: m for m in merged["methods"]}
    assert method_by_id["m1"]["family_id"] == "fam_b"


def test_no_op_when_all_families_have_two_methods():
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["m1", "m2"]},
        {"id": "fam_b", "title": "B", "method_ids": ["m3", "m4"]},
    ]
    methods = [{"id": f"m{i}", "arxiv_id": f"1.{i}", "family_id": fam} for i, fam in [(1,"fam_a"),(2,"fam_a"),(3,"fam_b"),(4,"fam_b")]]
    before = _outline(families, methods)
    after = merge_singletons(before)
    assert after == before
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_research_book_singleton_merge.py -v`
Expected: FAIL — `merge_singletons` does not exist.

- [ ] **Step 3: Implement `merge_singletons`**

In `swarn_research_mcp/research_book.py`, add (place after `_method_by_id`, around line 528):

```python
import copy as _copy


def merge_singletons(outline: dict[str, Any]) -> dict[str, Any]:
    """Deterministic post-processor: merge every single-method family into its nearest non-singleton family.

    Algorithm:
      1. Score candidate non-singleton families by graph proximity to the singleton's method.
         Primary: count of singleton's neighbor_method_ids that live in the candidate family.
         Tiebreaker: presence of candidate.id in singleton.neighbor_family_ids.
         Final tiebreaker: lexicographic family_id (deterministic).
      2. Best candidate wins; the singleton method joins it; family_id is rewritten on the method.
      3. If no non-singleton candidate has any graph connection AND no neighbor_family_ids match,
         the singleton method goes into a catch-all family `other_{part_id}` (one per part as needed).
    """
    out = _copy.deepcopy(outline)
    families = out["families"]
    methods = out["methods"]
    method_by_id = {m["id"]: m for m in methods}

    parts = out.get("parts") or []
    family_to_part: dict[str, str] = {}
    for part in parts:
        for fid in part.get("family_ids", []) or []:
            family_to_part[fid] = part["id"]

    while True:
        singletons = [f for f in families if len(f.get("method_ids", [])) == 1]
        if not singletons:
            break

        # Sort to make merge order deterministic.
        singleton = sorted(singletons, key=lambda f: f["id"])[0]
        s_method_id = singleton["method_ids"][0]
        s_method = method_by_id[s_method_id]
        s_neighbor_methods = set(s_method.get("neighbor_method_ids", []) or [])
        s_neighbor_families = set(singleton.get("neighbor_family_ids", []) or [])

        candidates = [f for f in families if f["id"] != singleton["id"] and len(f.get("method_ids", [])) >= 2]

        def score(f):
            shared = sum(1 for mid in f.get("method_ids", []) if mid in s_neighbor_methods)
            neighbor_bonus = 1 if f["id"] in s_neighbor_families else 0
            return (shared, neighbor_bonus, -ord(f["id"][0]) if f["id"] else 0)

        best = None
        best_score = (0, 0, 0)
        for cand in candidates:
            sc = score(cand)
            if sc > best_score:
                best_score = sc
                best = cand
        if best is None or best_score == (0, 0, best_score[2]):
            best = None  # no graph connection at all

        if best is not None:
            best["method_ids"] = list(best["method_ids"]) + [s_method_id]
            s_method["family_id"] = best["id"]
            families = [f for f in families if f["id"] != singleton["id"]]
            for part in parts:
                fids = part.get("family_ids", []) or []
                part["family_ids"] = [fid for fid in fids if fid != singleton["id"]]
        else:
            part_id = family_to_part.get(singleton["id"]) or (parts[0]["id"] if parts else "p1")
            catchall_id = f"other_{part_id}"
            catchall = next((f for f in families if f["id"] == catchall_id), None)
            if catchall is None:
                catchall = {"id": catchall_id, "title": f"Other ({part_id})",
                            "method_ids": [], "neighbor_family_ids": []}
                families.append(catchall)
                for part in parts:
                    if part["id"] == part_id and catchall_id not in (part.get("family_ids") or []):
                        part.setdefault("family_ids", []).append(catchall_id)
            catchall["method_ids"] = list(catchall["method_ids"]) + [s_method_id]
            s_method["family_id"] = catchall_id
            families = [f for f in families if f["id"] != singleton["id"]]
            for part in parts:
                fids = part.get("family_ids", []) or []
                part["family_ids"] = [fid for fid in fids if fid != singleton["id"]]

    out["families"] = families
    out["parts"] = parts
    return out
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_research_book_singleton_merge.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_research_book_singleton_merge.py swarn_research_mcp/research_book.py
git commit -m "feat(research-book): merge_singletons deterministic post-processor"
```

---

## Task 1.5: Wire `merge_singletons` into `generate_book_artifacts`

**Files:**
- Modify: `swarn_research_mcp/research_book.py:638` (`generate_book_artifacts`)

- [ ] **Step 1: Add the call + persist normalized outline**

In `generate_book_artifacts`, after `outline = _outline(run_path)` (line 640), add:

```python
    normalized = merge_singletons(outline)
    if normalized != outline:
        _write_json(run_path / "12_taxonomy" / "outline.json", normalized)
        outline = normalized
```

- [ ] **Step 2: Add an integration test**

Append to `tests/test_research_book_singleton_merge.py`:

```python
def test_generate_book_artifacts_normalizes_outline_in_place(voice_lm_minimal, monkeypatch):
    """voice_lm_minimal has fam_codec singleton; after generate_book_artifacts it should be merged."""
    # Add parts so the run is otherwise valid.
    outline_path = voice_lm_minimal / "12_taxonomy" / "outline.json"
    outline = json.loads(outline_path.read_text())
    outline["parts"] = [
        {"id": "p1", "title": "P1", "family_ids": ["fam_codec", "fam_flow"]},
        {"id": "p2", "title": "P2", "family_ids": []},
    ]
    outline_path.write_text(json.dumps(outline))

    # Stub verification_gate so it doesn't trip on the m_excluded chapter.
    from swarn_research_mcp import research_book as rb
    monkeypatch.setattr(rb, "verification_gate", lambda _: None)
    monkeypatch.setattr(rb, "_paper_label",
                        lambda aid, promoted, pool: f"[arxiv:{aid}] x (2024)")

    rb.generate_book_artifacts(voice_lm_minimal)

    after = json.loads(outline_path.read_text())
    family_ids = {f["id"] for f in after["families"]}
    assert "fam_codec" not in family_ids  # singleton merged away
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_research_book_singleton_merge.py -v`
Expected: PASS (5 tests).

- [ ] **Step 4: Commit**

```bash
git add tests/test_research_book_singleton_merge.py swarn_research_mcp/research_book.py
git commit -m "feat(research-book): generate_book_artifacts auto-normalizes singletons before rendering"
```

---

## Task 1.6: Update `taxonomy-building` SKILL.md (parts + singleton notes)

**Files:**
- Modify: `.agents/skills/taxonomy-building/SKILL.md`

- [ ] **Step 1: Add parts section**

In `.agents/skills/taxonomy-building/SKILL.md`, find `## Family clustering` and AFTER its bullet list, insert:

```markdown
## Parts (topic-adaptive grouping)
After clustering, assign every family to exactly one part.

Default labels (Book_style.md): `interpretable`, `local`, `global`, `model_specific`, `evaluation_outlook`. You MAY rename, merge, or drop default parts when the topic fits a different shape.

Hard rules (self-validate):
- 2 ≤ len(parts) ≤ 5
- Every family appears in exactly one part
- Every part contains ≥ 1 family

Emit as `parts: [{id, title, family_ids[]}]` in `outline.json`.

## Singleton handling
If clustering produces a singleton family (`len(method_ids) == 1`), prefer to merge it into the nearest non-singleton family by shared verified-graph edges. The deterministic post-processor `merge_singletons` in `swarn_research_mcp.research_book` will normalize the outline at stage 18 even if you ship a singleton, but emitting clean output reduces churn. Catch-all `other_{part_id}` families are reserved for methods with no graph connections.
```

- [ ] **Step 2: Update outline.json schema**

Find the `outline.json schema` JSON block and add `parts` after `book_sections`:
```json
  "parts": [{"id": "interpretable", "title": "Interpretable Methods", "family_ids": ["fam_a"]}],
```

- [ ] **Step 3: Update Hard rules**

Add to `## Hard rules`:
```markdown
- `parts` is present with 2..5 entries; every family belongs to exactly one part.
```

- [ ] **Step 4: Commit**

```bash
git add .agents/skills/taxonomy-building/SKILL.md
git commit -m "docs(taxonomy): document parts + singleton merge contract"
```

---

# Wave 2 — Bibliography in `_build_method_taxonomy` is fine; references rendering needs a tweak

The audit found `<title unknown>` in the audited run's `04_method_taxonomy.md`. Per code inspection, `_build_method_taxonomy` does NOT emit `Title (Year)` lines — it only emits `[arxiv:ID]` inline tags. The `<title unknown>` rendering happens in `_paper_label`, which is called from validators and possibly other consumers (manifest, sidebar). Wave 1 already tightened `_paper_label`. This wave verifies the fix and adds a regression test against the real fixture.

## Task 2.1: Regression test against real-shape fixture

**Files:**
- Test: `tests/test_research_book_bibliography.py` (create)

- [ ] **Step 1: Write the regression test**

```python
# tests/test_research_book_bibliography.py
from __future__ import annotations
import json
import pytest
from swarn_research_mcp.research_book import (
    resolve_paper_citation,
    MissingCitationError,
    _paper_label,
    _paper_lookup,
)


def _promoted(run):
    return {p["arxiv_id"]: p for p in
            json.loads((run / "07_scoring" / "promoted_papers.json").read_text())["promoted_papers"]}


def test_voice_lm_fixture_resolves_via_semantic_scholar(voice_lm_minimal):
    """List-shaped pool with no titles; semantic_scholar carries title/year."""
    cite = resolve_paper_citation(voice_lm_minimal, "2301.02111")
    assert "VALL-E" in cite["title"]
    assert cite["year"] == 2023


def test_paper_label_renders_full_reference_for_voice_lm(voice_lm_minimal):
    pool = _paper_lookup(voice_lm_minimal)
    promoted = _promoted(voice_lm_minimal)
    label = _paper_label("2301.02111", promoted, pool)
    assert label.startswith("[arxiv:2301.02111]")
    assert "<title unknown>" not in label
    assert "<year unknown>" not in label
    assert "(2023)" in label


def test_paper_label_failure_message_names_arxiv_id(tmp_path):
    pool = {"9999.99999": {"arxiv_id": "9999.99999"}}
    with pytest.raises(MissingCitationError, match="9999.99999"):
        _paper_label("9999.99999", promoted={}, pool=pool)
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_research_book_bibliography.py -v`
Expected: PASS (3 tests). If FAIL, return to Wave 1 (the lookup or resolver is still broken on real-shape input).

- [ ] **Step 3: Commit**

```bash
git add tests/test_research_book_bibliography.py
git commit -m "test(bibliography): regression test confirming voice_lm fixture resolves via semantic_scholar"
```

---

## Task 2.2: Update `book-section-writing` SKILL bibliography rule

**Files:**
- Modify: `.agents/skills/book-section-writing/SKILL.md`

- [ ] **Step 1: Tighten the method_taxonomy and appendices rows**

In `.agents/skills/book-section-writing/SKILL.md`, replace the `method_taxonomy` and `appendices` rows in `## Per-section structure` with:

```markdown
- `method_taxonomy` — deterministic artifact. Always run `python -m swarn_research_mcp.research_book research_runs/{run_id} --generate`. Manual drafting is forbidden because reference rendering relies on `_paper_label` + `resolve_paper_citation`, which fail loud rather than emit `<title unknown>` / `<year unknown>`. If a cited arxiv_id has no resolvable title/year, fix `02_paper_pool/paper_pool.json`, `03_overviews/semantic_scholar/`, or `04_weak_evidence/` before re-running.
- `appendices` — deterministic artifact. Always run the generator; output is the directory `99_appendices/` with `glossary.md`, `notation.md`, `datasets.md`, `software.md` (NOT a single 99_appendices.md file).
```

- [ ] **Step 2: Commit**

```bash
git add .agents/skills/book-section-writing/SKILL.md
git commit -m "docs(book-section-writing): bibliography fails loud; appendices is a directory"
```

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
    # Mid-positioned References breaks order.
    assert diff["out_of_order"] is True


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

# Wave 4 — Goals beef-up + Appendices directory hard break

## Task 4.1: `book-section-writing` SKILL — Goals tightening

**Files:**
- Modify: `.agents/skills/book-section-writing/SKILL.md`

- [ ] **Step 1: Tighten the goals row**

In `## Per-section structure`, replace the goals entry with:
```markdown
- `goals` — H1 + ≥ 4 goal categories. Each category has (a) why it matters, (b) which families help (cite via `[Family Name](../families/{id}.md)`), (c) one tradeoff. Min 600 words.
```

- [ ] **Step 2: Update goals word range in the table**

In `## Output filenames`, change goals row to:
```markdown
| `goals`              | `03_goals.md`                  | 600–1200   |
```

- [ ] **Step 3: Commit**

```bash
git add .agents/skills/book-section-writing/SKILL.md
git commit -m "docs(book-section-writing): goals chapter requires 4 categories + family links + 600 words"
```

---

## Task 4.2: Switch `BOOK_FILE_BY_ID["appendices"]` to a directory marker

**Files:**
- Test: `tests/test_research_book_appendices_dir.py` (create)
- Modify: `swarn_research_mcp/research_book.py` (`BOOK_FILE_BY_ID`, validator, summary, sidebar, generate)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_research_book_appendices_dir.py
from __future__ import annotations
import json
from swarn_research_mcp.research_book import (
    BOOK_FILE_BY_ID,
    _build_appendices_dir,
    generate_book_artifacts,
    validate_research_book_run,
)


def test_appendices_constant_points_to_directory():
    assert BOOK_FILE_BY_ID["appendices"] == "99_appendices"  # directory name, no .md


def test_build_appendices_dir_creates_four_files(voice_lm_minimal):
    outline = json.loads((voice_lm_minimal / "12_taxonomy" / "outline.json").read_text())
    _build_appendices_dir(voice_lm_minimal, outline)
    out = voice_lm_minimal / "14_chapters" / "book" / "99_appendices"
    assert out.is_dir()
    for name in ("glossary.md", "notation.md", "datasets.md", "software.md"):
        assert (out / name).exists(), f"missing {name}"


def test_generate_book_artifacts_writes_appendices_dir(voice_lm_minimal, monkeypatch):
    from swarn_research_mcp import research_book as rb
    op = voice_lm_minimal / "12_taxonomy" / "outline.json"
    outline = json.loads(op.read_text())
    outline["parts"] = [
        {"id": "p1", "title": "P1", "family_ids": ["fam_codec"]},
        {"id": "p2", "title": "P2", "family_ids": ["fam_flow"]},
    ]
    op.write_text(json.dumps(outline))
    monkeypatch.setattr(rb, "verification_gate", lambda _: None)
    rb.generate_book_artifacts(voice_lm_minimal)
    assert (voice_lm_minimal / "14_chapters" / "book" / "99_appendices" / "glossary.md").exists()


def test_validator_rejects_missing_appendices_directory(voice_lm_minimal):
    issues = validate_research_book_run(voice_lm_minimal)
    # Fixture has no 99_appendices/ directory yet.
    codes = [i["code"] for i in issues]
    assert "missing_book_chapter" in codes
    detail = next(i["detail"] for i in issues if i["code"] == "missing_book_chapter" and "appendices" in i["detail"])
    assert "99_appendices" in detail
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_research_book_appendices_dir.py -v`
Expected: FAIL.

- [ ] **Step 3: Update `BOOK_FILE_BY_ID`**

In `swarn_research_mcp/research_book.py`, change line 18:
```python
    "appendices": "99_appendices",
```

- [ ] **Step 4: Update appendices existence check in validator**

Find the loop in `validate_research_book_run` that checks `(run_path / "14_chapters" / "book" / filename).exists()` (around line 352). Replace with:

```python
    for section_id, filename in BOOK_FILE_BY_ID.items():
        target = run_path / "14_chapters" / "book" / filename
        if section_id == "appendices":
            ok = target.is_dir() and all(
                (target / sub).exists()
                for sub in ("glossary.md", "notation.md", "datasets.md", "software.md")
            )
        else:
            ok = target.exists()
        if not ok:
            issues.append({
                "severity": "error", "code": "missing_book_chapter",
                "detail": f"14_chapters/book/{filename} is missing for {section_id}",
            })
```

- [ ] **Step 5: Replace `_build_appendices` with `_build_appendices_dir`**

Remove the existing `_build_appendices` function (lines 562–594). Add:

```python
def _build_appendices_dir(run_dir: Path, outline: dict[str, Any]) -> None:
    out_dir = run_dir / "14_chapters" / "book" / "99_appendices"
    out_dir.mkdir(parents=True, exist_ok=True)

    # glossary.md
    snap = run_dir / "06_expansion" / "known_concepts_snapshot.json"
    glossary = ["# Glossary", ""]
    if snap.exists():
        for entry in (_load_json(snap).get("known_concepts") or []):
            name = entry.get("name") or entry.get("id") or ""
            definition = entry.get("definition") or entry.get("summary") or ""
            if name:
                glossary.append(f"- **{name}** — {definition}")
    (out_dir / "glossary.md").write_text("\n".join(glossary) + "\n", encoding="utf-8")

    packs_dir = run_dir / "13_chapter_packs" / "methods"

    def _harvest(field: str, header: str) -> list[str]:
        seen: set[str] = set()
        lines = [f"# {header}", ""]
        if packs_dir.exists():
            for pack_path in sorted(packs_dir.glob("*_pack.json")):
                pack = _load_json(pack_path)
                for entry in (pack.get("structured", {}).get(field) or []):
                    name = entry.get("name") or ""
                    if name and name not in seen:
                        seen.add(name)
                        if field == "equations":
                            for sym in entry.get("symbols", []) or []:
                                sname = sym.get("name") or ""
                                sdesc = sym.get("description") or ""
                                if sname and sname not in seen:
                                    seen.add(sname)
                                    lines.append(f"- `{sname}` — {sdesc}")
                        else:
                            lines.append(f"- {name}")
        return lines

    # notation pulls from equations[].symbols
    notation = ["# Notation", ""]
    seen_n: set[str] = set()
    if packs_dir.exists():
        for pack_path in sorted(packs_dir.glob("*_pack.json")):
            pack = _load_json(pack_path)
            for eq in (pack.get("structured", {}).get("equations") or []):
                for sym in eq.get("symbols", []) or []:
                    sname = sym.get("name") or ""
                    sdesc = sym.get("description") or ""
                    if sname and sname not in seen_n:
                        seen_n.add(sname)
                        notation.append(f"- `{sname}` — {sdesc}")
    (out_dir / "notation.md").write_text("\n".join(notation) + "\n", encoding="utf-8")

    (out_dir / "datasets.md").write_text("\n".join(_harvest("datasets", "Datasets")) + "\n", encoding="utf-8")
    (out_dir / "software.md").write_text("\n".join(_harvest("artifacts", "Software and Artifacts")) + "\n", encoding="utf-8")
```

- [ ] **Step 6: Update `generate_book_artifacts` to call the dir builder**

Find the existing call to `_build_appendices` in `generate_book_artifacts` (around line 645). Replace:
```python
    _write_markdown_preserving_front_matter(appendices_path, _build_appendices(run_path, outline))
```
with:
```python
    _build_appendices_dir(run_path, outline)
```
Also remove the line that constructs `appendices_path` (it referenced `BOOK_FILE_BY_ID["appendices"]` as a file).

- [ ] **Step 7: Update `_build_summary` and `_build_sidebar` to link the directory index**

In `_build_summary` (line 595), the loop appends `[Title](../14_chapters/book/{filename})`. For `appendices` the target is a directory; link to `../14_chapters/book/99_appendices/glossary.md` as the entry point. Add a special case:

```python
    for section in outline.get("book_sections", []):
        section_id = section["id"]
        filename = BOOK_FILE_BY_ID.get(section_id)
        if not filename:
            continue
        if section_id == "appendices":
            href = f"../14_chapters/book/{filename}/glossary.md"
        else:
            href = f"../14_chapters/book/{filename}"
        lines.append(f"- [{section['title']}]({href})")
```

Mirror the same in `_build_sidebar`.

- [ ] **Step 8: Run tests**

Run: `pytest tests/test_research_book_appendices_dir.py -v`
Expected: PASS (4 tests).

Run: `pytest tests/test_research_book_artifacts.py -v`
Expected: existing tests still pass (any that asserted `99_appendices.md` should now be updated to assert the directory).

- [ ] **Step 9: Update existing artifact tests if they mention `99_appendices.md`**

Run: `grep -n "99_appendices.md" tests/`. For each hit, update to `99_appendices` (directory) or to a specific sub-file. If the assertion was on the file existing, change to `(... / "99_appendices" / "glossary.md").exists()`.

Run: `pytest tests/ -v`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add tests/ swarn_research_mcp/research_book.py
git commit -m "feat(research-book): hard-switch appendices to 99_appendices/ directory with 4 files"
```

---

## Task 4.3: Update `book-section-writing` SKILL appendices row

**Files:**
- Modify: `.agents/skills/book-section-writing/SKILL.md`

- [ ] **Step 1: Update the table and per-section text**

In `## Output filenames`, change the appendices row to:
```markdown
| `appendices`         | `99_appendices/` (directory)   | n/a (deterministic)  |
```

In `## Per-section structure`, the appendices row was already updated in Task 2.2 to mention the directory. Verify it reads:
```markdown
- `appendices` — deterministic artifact. Always run the generator; output is the directory `99_appendices/` with `glossary.md`, `notation.md`, `datasets.md`, `software.md`.
```

- [ ] **Step 2: Commit**

```bash
git add .agents/skills/book-section-writing/SKILL.md
git commit -m "docs(book-section-writing): appendices output is a directory, no .md file"
```

---

# Wave 5 — Verification gate + NEEDS_REVIEW.md

## Task 5.1: Add `verification_gate` + `NEEDS_REVIEW.md` emitter

**Files:**
- Test: `tests/test_research_book_verification_gate.py` (create)
- Modify: `swarn_research_mcp/research_book.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_research_book_verification_gate.py
from __future__ import annotations
import pytest
from swarn_research_mcp.research_book import (
    verification_gate,
    VerificationGateError,
    write_needs_review,
)


def test_gate_passes_when_no_excluded(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    verification_gate(run)  # no raise


def test_gate_collects_offenders(voice_lm_minimal):
    with pytest.raises(VerificationGateError) as exc:
        verification_gate(voice_lm_minimal)
    msg = str(exc.value)
    assert "m_excluded" in msg
    assert "excluded_unsupported_claims" in msg


def test_write_needs_review_creates_file(voice_lm_minimal):
    offenders = [{"type": "methods", "id": "m_excluded",
                  "status": "excluded_unsupported_claims",
                  "reason": "claims_unsupported=3"}]
    write_needs_review(voice_lm_minimal, offenders)
    needs = voice_lm_minimal / "16_book" / "NEEDS_REVIEW.md"
    assert needs.exists()
    text = needs.read_text()
    assert "m_excluded" in text
    assert "excluded_unsupported_claims" in text
    assert "claims_unsupported=3" in text
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_research_book_verification_gate.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `verification_gate` and `write_needs_review`**

In `swarn_research_mcp/research_book.py`, add:

```python
class VerificationGateError(RuntimeError):
    """Raised when one or more chapters carry status: excluded_*."""


def _collect_excluded(run_dir: Path) -> list[dict[str, str]]:
    offenders: list[dict[str, str]] = []
    for sub in ("families", "methods", "book"):
        d = run_dir / "14_chapters" / sub
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
                offenders.append({"type": sub, "id": path.stem,
                                  "status": status, "reason": reason})
    return offenders


def write_needs_review(run_dir: Path | str, offenders: list[dict[str, str]]) -> None:
    """Emit 16_book/NEEDS_REVIEW.md so the run still has a navigation artifact when the gate trips."""
    out = Path(run_dir) / "16_book" / "NEEDS_REVIEW.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# NEEDS REVIEW", "",
             "SUMMARY.md was not generated because one or more chapters failed verification.",
             "Re-run with `phase=write fix_excluded=true` to attempt automated fixes.",
             "", "## Offenders", ""]
    for o in offenders:
        lines.append(f"- **{o['type']}/{o['id']}** — `{o['status']}` ({o['reason']})")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def verification_gate(run_dir: Path | str) -> None:
    """Block stage 18 if any chapter has status: excluded_*. Emits NEEDS_REVIEW.md and raises."""
    run_path = Path(run_dir)
    offenders = _collect_excluded(run_path)
    if offenders:
        write_needs_review(run_path, offenders)
        lines = [f"  - {o['type']}/{o['id']}: {o['status']} ({o['reason']})" for o in offenders]
        raise VerificationGateError(
            "verification gate blocked SUMMARY.md generation; offenders:\n"
            + "\n".join(lines)
            + "\n\nSee 16_book/NEEDS_REVIEW.md for the punch list."
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_research_book_verification_gate.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_research_book_verification_gate.py swarn_research_mcp/research_book.py
git commit -m "feat(research-book): verification_gate raises on excluded chapters and emits NEEDS_REVIEW.md"
```

---

## Task 5.2: Wire gate into `generate_book_artifacts`

**Files:**
- Modify: `swarn_research_mcp/research_book.py:638` (`generate_book_artifacts`)

- [ ] **Step 1: Add gate call as the first line**

In `generate_book_artifacts`, before any other code in the function body, add:
```python
    verification_gate(run_dir)
```

- [ ] **Step 2: Add integration test**

Append to `tests/test_research_book_verification_gate.py`:

```python
def test_generate_blocks_on_excluded(voice_lm_minimal):
    from swarn_research_mcp.research_book import generate_book_artifacts, VerificationGateError
    with pytest.raises(VerificationGateError):
        generate_book_artifacts(voice_lm_minimal)
    assert (voice_lm_minimal / "16_book" / "NEEDS_REVIEW.md").exists()
```

Run: `pytest tests/test_research_book_verification_gate.py -v`
Expected: PASS (4 tests).

- [ ] **Step 3: Commit**

```bash
git add tests/test_research_book_verification_gate.py swarn_research_mcp/research_book.py
git commit -m "feat(research-book): generate_book_artifacts blocks on verification_gate; emits NEEDS_REVIEW.md"
```

---

## Task 5.3: Update orchestrator SKILL with gate + fix_excluded loop

**Files:**
- Modify: `.agents/skills/auto-research-orchestrator/SKILL.md`

- [ ] **Step 1: Document the gate at stage 18**

Find the Stage table row for stage 18 (`SUMMARY.md`...). Append AFTER the table:

```markdown
## Stage 18 verification gate
Before generating SUMMARY.md, call `swarn_research_mcp.research_book.verification_gate(run_dir)`. If it raises `VerificationGateError`:
- The run fails the `write` phase.
- `16_book/NEEDS_REVIEW.md` is written with the offender list.
- `SUMMARY.md` and `sidebar.json` are NOT written.
```

- [ ] **Step 2: Add `fix_excluded` retry-loop spec**

Append a new section after `## Two-pass execution`:

```markdown
## phase=write,fix_excluded=true (single retry)
When the operator re-launches with `phase=write fix_excluded=true`:
1. Read offender list from `15_verification/{type}/{id}_verification.json`.
2. For each offender:
   - `gaps_missing` → re-dispatch stage 13 (pack rebuild) for that ID, then stage 14.
   - `claims_unsupported` → re-dispatch stage 14 with a directive to drop or re-cite offending claims.
3. Re-run stage 15 verification on affected chapters.
4. On still-failing chapters after one retry, fail hard with a final exclusion list. No further retries.
5. Each fix attempt logs a row in `run_log.csv`: `stage,chapter_id,attempt,outcome`.
```

- [ ] **Step 3: Commit**

```bash
git add .agents/skills/auto-research-orchestrator/SKILL.md
git commit -m "docs(orchestrator): stage 18 verification gate + fix_excluded retry loop"
```

---

# Final Validation

## Task F.1: Full test suite + audited-run regression check

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: all green.

- [ ] **Step 2: Run validator on the audited voice-LM run**

Run:
```bash
python -c "
from swarn_research_mcp.research_book import validate_research_book_run
import json
issues = validate_research_book_run('research_runs/voice-language-model-text-speech-io-20260509-222749')
print(json.dumps(issues[:20], indent=2))
print(f'total issues: {len(issues)}')
"
```

Expected: surfaces `missing_parts`, `singleton_family` (multiple), `wrong_chapter_headings` (multiple), and the existing run's status flags. Confirms the validator now catches the audit gaps. (We are NOT migrating the existing run.)

- [ ] **Step 3: Verify the gate trips on the audited run**

Run:
```bash
python -c "
from swarn_research_mcp.research_book import verification_gate
try:
    verification_gate('research_runs/voice-language-model-text-speech-io-20260509-222749')
    print('PASSED — unexpected')
except Exception as e:
    print('GATE TRIPPED as expected')
    print(str(e)[:500])
"
```

Expected: GATE TRIPPED message listing several `excluded_*` chapters.

- [ ] **Step 4: Commit any stray changes (if any)**

```bash
git status
# if clean, skip
```

---

# Self-Review

**Spec coverage:**
- §1 parts → Task 1.3 (validator), 1.6 (skill)
- §2 singleton merge → Task 1.4 (deterministic merger), 1.5 (wired into generator), 1.6 (skill text)
- §3 family headings → Task 3.1 (lint), 3.2 (skill)
- §4 method headings → Task 3.1 (lint), 3.3 (skill)
- §5 verification gate → Task 5.1 (gate + NEEDS_REVIEW), 5.2 (wired), 5.3 (skill)
- §6a bibliography bug → Task 1.1 (multi-shape lookup), 1.2 (loud `_paper_label`), 2.1 (regression), 2.2 (skill)
- §6b goals → Task 4.1
- §6c appendices → Task 4.2 (hard break), 4.3 (skill)
- §7 SDK migration → **deferred to separate plan** `2026-05-10-codex-sdk-context-relief-pilot.md`

**Type consistency:**
- `MissingCitationError` defined in Task 1.1, used in 1.2, 2.1
- `VerificationGateError` defined in Task 5.1, used in 5.2
- `merge_singletons` defined in Task 1.4, called in 1.5
- `BOOK_FILE_BY_ID["appendices"]` is `"99_appendices"` (no `.md`) consistently after Task 4.2
- `_diff_headings` returns `{missing, extra, out_of_order}` everywhere; `## References` allowed only as last `##`

**Real-shape coverage:**
- Wave 0 fixture has list-shaped paper_pool (no titles), semantic_scholar metadata, mixed pass/excluded chapters, old skill heading shapes — exactly the audited-run quirks
- Tasks 1.1, 2.1, 3.1, 4.2, 5.1, 5.2 all run against the fixture
