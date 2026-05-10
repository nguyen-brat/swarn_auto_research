# Codex Pipeline Book_style Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a reader-oriented handbook structure inspired by `Book_style.md`. Always ship a readable, trustworthy synthesis; quarantine failed material rather than blocking the whole book. The pipeline is judged on **reader experience** (parts visible in navigation, passing chapters always reachable, failed material clearly marked) — not on formal conformance.

**Architecture:** SKILL contracts under `.agents/skills/` define the per-stage behavior. `swarn_research_mcp/research_book.py` provides validators, deterministic post-processors, and the book-artifact generator. Verification produces a **quarantine** (passed → main navigation; excluded → `NEEDS_REVIEW.md`), not a hard gate. Singletons stay as method chapters under a "Standalone / Emerging Methods" group when they lack strong graph evidence; only well-connected singletons merge into existing families.

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
- `swarn_research_mcp/research_book.py` — multi-shape `_paper_lookup`, strict `resolve_paper_citation`, `merge_singletons` + standalone group, `collect_excluded` + `write_needs_review` (quarantine, never raises), `appendices/` directory builder with `references.md`, parts-aware `_build_summary` / `_build_sidebar` / `_build_method_taxonomy`, heading lint with diagnostics

**Create:**
- `tests/fixtures/voice_lm_minimal/` — real-shape fixture mirroring the audited run's quirks (list-shaped paper_pool, semantic_scholar metadata-only, mixed status chapters)
- `tests/test_research_book_paper_lookup.py`
- `tests/test_research_book_parts.py`
- `tests/test_research_book_singleton_merge.py`
- `tests/test_research_book_bibliography.py`
- `tests/test_research_book_chapter_headings.py`
- `tests/test_research_book_verification_quarantine.py`
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
  {"arxiv_id": "2406.18009"},
  {"arxiv_id": "2410.06885"}
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

Write `tests/fixtures/voice_lm_minimal/03_overviews/semantic_scholar/2410.06885.json`:
```json
{"arxiv_id": "2410.06885", "title": "F5-TTS", "year": 2024}
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
    {"id": "m_excluded", "title": "Broken Method", "arxiv_id": "2410.06885", "family_id": "fam_flow", "neighbor_method_ids": []}
  ]
}
```

(Note: `fam_codec` is a singleton; each method has a distinct `arxiv_id` so duplicate-detection logic does not fire on this fixture. Add a separate small fixture in any test that specifically exercises duplicate-arxiv handling.)

- [ ] **Step 6: Write promoted_papers.json**

Write `tests/fixtures/voice_lm_minimal/07_scoring/promoted_papers.json`:
```json
{"promoted_papers": [
  {"arxiv_id": "2301.02111"},
  {"arxiv_id": "2406.18009"},
  {"arxiv_id": "2410.06885"}
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
    # Add a 3rd dummy family so the second part can hold something and we test only the "unassigned" path.
    outline["families"].append({"id": "fam_dummy", "title": "Dummy", "method_ids": ["m_dummy_a", "m_dummy_b"]})
    outline["methods"].extend([
        {"id": "m_dummy_a", "title": "DA", "arxiv_id": "0001.0001", "family_id": "fam_dummy"},
        {"id": "m_dummy_b", "title": "DB", "arxiv_id": "0001.0002", "family_id": "fam_dummy"},
    ])
    _set_outline(voice_lm_minimal, _add_parts(outline, [
        {"id": "p1", "title": "P1", "family_ids": ["fam_codec"]},
        {"id": "p2", "title": "P2", "family_ids": ["fam_dummy"]},
    ]))
    issues = validate_research_book_run(voice_lm_minimal)
    assert any(i["code"] == "family_unassigned_to_part" and "fam_flow" in i["detail"] for i in issues)


def test_empty_part_is_error(voice_lm_minimal):
    outline = json.loads((voice_lm_minimal / "12_taxonomy" / "outline.json").read_text())
    _set_outline(voice_lm_minimal, _add_parts(outline, [
        {"id": "p1", "title": "P1", "family_ids": ["fam_codec", "fam_flow"]},
        {"id": "p2", "title": "P2", "family_ids": []},
    ]))
    issues = validate_research_book_run(voice_lm_minimal)
    assert any(i["code"] == "empty_part" and "p2" in i["detail"] for i in issues)


def test_valid_parts(voice_lm_minimal):
    outline = json.loads((voice_lm_minimal / "12_taxonomy" / "outline.json").read_text())
    _set_outline(voice_lm_minimal, _add_parts(outline, [
        {"id": "p1", "title": "P1", "family_ids": ["fam_codec"]},
        {"id": "p2", "title": "P2", "family_ids": ["fam_flow"]},
    ]))
    issues = validate_research_book_run(voice_lm_minimal)
    parts_codes = {"missing_parts", "parts_count_out_of_range",
                   "family_in_multiple_parts", "family_unassigned_to_part", "empty_part"}
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
        fids = part.get("family_ids", []) or []
        if not fids:
            issues.append({"severity": "error", "code": "empty_part",
                           "detail": f"part {pid} has no families"})
        for fid in fids:
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
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_research_book_parts.py swarn_research_mcp/research_book.py
git commit -m "feat(research-book): validate outline.json parts (2..5, exclusive coverage of families)"
```

---

## Task 1.4: Singleton policy — merge with evidence, otherwise standalone

This is a **named Stage 12.5 contract** running between Stages 12 and 13.

**Policy:**
- A singleton **merges** into its nearest non-singleton family iff there is **strong graph evidence**: at least 2 of the singleton-method's `neighbor_method_ids` live in the candidate family, OR the candidate's id appears in the singleton's `neighbor_family_ids` AND at least 1 method overlap exists.
- Otherwise the singleton is **kept as a standalone method chapter** (no family chapter wrapper). Its family record is replaced with a marker `{"id": "standalone", "title": "Standalone / Emerging Methods", "method_ids": [...], "is_group": true}` — one such record per book, accumulating all weak singletons. The `standalone` group lives in its own part `standalone_methods` (auto-added if any standalone methods exist).
- `assert_no_singletons` (Stage 18) treats the `standalone` group as valid (i.e. allows `len(method_ids) >= 1` for `id == "standalone"` and for `id.startswith("other_")`).

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


def test_singleton_with_strong_evidence_merges():
    """≥2 shared neighbor methods OR (neighbor_family_id + ≥1 shared method) triggers merge."""
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["m1"], "neighbor_family_ids": ["fam_b"]},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"], "neighbor_family_ids": ["fam_a"]},
    ]
    methods = [
        # m1 has 2 shared neighbors in fam_b → strong evidence → merge.
        {"id": "m1", "arxiv_id": "1.1", "family_id": "fam_a", "neighbor_method_ids": ["m2", "m3"]},
        {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b", "neighbor_method_ids": ["m1", "m3"]},
        {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b", "neighbor_method_ids": ["m2"]},
    ]
    merged = merge_singletons(_outline(families, methods))
    family_by_id = {f["id"]: f for f in merged["families"]}
    assert "fam_a" not in family_by_id
    assert sorted(family_by_id["fam_b"]["method_ids"]) == ["m1", "m2", "m3"]


def test_singleton_with_weak_evidence_goes_to_standalone():
    """1 shared neighbor without neighbor_family link → weak → standalone."""
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


def test_no_op_when_all_families_have_two_methods():
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["m1", "m2"]},
        {"id": "fam_b", "title": "B", "method_ids": ["m3", "m4"]},
    ]
    methods = [{"id": f"m{i}", "arxiv_id": f"1.{i}", "family_id": fam} for i, fam in [(1,"fam_a"),(2,"fam_a"),(3,"fam_b"),(4,"fam_b")]]
    before = _outline(families, methods)
    after = merge_singletons(before)
    assert after == before


def test_assert_no_singletons_raises_on_unmerged_outline():
    from swarn_research_mcp.research_book import assert_no_singletons
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["m1"]},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"]},
    ]
    methods = [{"id": "m1", "arxiv_id": "1.1", "family_id": "fam_a"},
               {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b"},
               {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b"}]
    with pytest.raises(RuntimeError, match="singleton"):
        assert_no_singletons(_outline(families, methods))


def test_assert_no_singletons_allows_standalone_group_with_one_method():
    from swarn_research_mcp.research_book import assert_no_singletons
    families = [
        {"id": "standalone", "title": "Standalone / Emerging Methods", "method_ids": ["m1"], "is_group": True},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"]},
    ]
    methods = [{"id": "m1", "arxiv_id": "1.1", "family_id": "standalone"},
               {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b"},
               {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b"}]
    assert_no_singletons(_outline(families, methods))  # no raise
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_research_book_singleton_merge.py -v`
Expected: FAIL — `merge_singletons` does not exist.

- [ ] **Step 3: Implement `merge_singletons`**

In `swarn_research_mcp/research_book.py`, add (place after `_method_by_id`, around line 528):

```python
import copy as _copy


STANDALONE_GROUP_ID = "standalone"
STANDALONE_PART_ID = "standalone_methods"


def _has_strong_graph_evidence(singleton: dict, candidate: dict, method_by_id: dict) -> bool:
    s_method = method_by_id[singleton["method_ids"][0]]
    s_neighbor_methods = set(s_method.get("neighbor_method_ids", []) or [])
    s_neighbor_families = set(singleton.get("neighbor_family_ids", []) or [])
    cand_methods = set(candidate.get("method_ids", []) or [])
    shared = len(s_neighbor_methods & cand_methods)
    if shared >= 2:
        return True
    if candidate["id"] in s_neighbor_families and shared >= 1:
        return True
    return False


def merge_singletons(outline: dict[str, Any]) -> dict[str, Any]:
    """Stage 12.5 post-processor.

    For each original singleton family:
      - If a non-singleton family has STRONG graph evidence (≥2 shared neighbor methods,
        OR neighbor_family + ≥1 shared method): merge into it.
      - Otherwise: drop the singleton family; the method becomes a member of the
        `standalone` group (a family marked `is_group=True`) under a new
        `standalone_methods` part. No family chapter is rendered for the group.

    Catch-all `other_*` families are NEVER created. The standalone group replaces them.
    """
    out = _copy.deepcopy(outline)
    families: list[dict[str, Any]] = out["families"]
    methods: list[dict[str, Any]] = out["methods"]
    method_by_id = {m["id"]: m for m in methods}
    parts = out.get("parts") or []

    original_singletons = sorted(
        (f for f in families
         if len(f.get("method_ids", [])) == 1
         and f["id"] != STANDALONE_GROUP_ID),
        key=lambda f: f["id"],
    )
    if not original_singletons:
        return out

    for singleton in original_singletons:
        sid = singleton["id"]
        if not any(f["id"] == sid for f in families):
            continue
        s_method_id = singleton["method_ids"][0]

        candidates = [
            f for f in families
            if f["id"] != sid
            and f["id"] != STANDALONE_GROUP_ID
            and len(f.get("method_ids", [])) >= 2
        ]

        # Pick the strongest-evidence candidate; on tie, lexicographically smaller id wins.
        winner = None
        for cand in sorted(candidates, key=lambda f: f["id"]):
            if _has_strong_graph_evidence(singleton, cand, method_by_id):
                winner = cand
                break

        if winner is not None:
            winner["method_ids"] = list(winner["method_ids"]) + [s_method_id]
            method_by_id[s_method_id]["family_id"] = winner["id"]
        else:
            standalone = next((f for f in families if f["id"] == STANDALONE_GROUP_ID), None)
            if standalone is None:
                standalone = {
                    "id": STANDALONE_GROUP_ID,
                    "title": "Standalone / Emerging Methods",
                    "method_ids": [],
                    "neighbor_family_ids": [],
                    "is_group": True,
                }
                families.append(standalone)
                if not any(p["id"] == STANDALONE_PART_ID for p in parts):
                    parts.append({
                        "id": STANDALONE_PART_ID,
                        "title": "Standalone / Emerging Methods",
                        "family_ids": [STANDALONE_GROUP_ID],
                    })
                else:
                    sp = next(p for p in parts if p["id"] == STANDALONE_PART_ID)
                    if STANDALONE_GROUP_ID not in (sp.get("family_ids") or []):
                        sp.setdefault("family_ids", []).append(STANDALONE_GROUP_ID)
            standalone["method_ids"] = list(standalone["method_ids"]) + [s_method_id]
            method_by_id[s_method_id]["family_id"] = STANDALONE_GROUP_ID

        families = [f for f in families if f["id"] != sid]
        for part in parts:
            fids = part.get("family_ids", []) or []
            part["family_ids"] = [fid for fid in fids if fid != sid]

    # Cap parts at 5 — if standalone push us over 5, this is acceptable per topic-adaptive rule.
    out["families"] = families
    out["parts"] = parts
    return out


def assert_no_singletons(outline: dict[str, Any]) -> None:
    """Stage 18 precondition: every family with len(method_ids)==1 must be the standalone group."""
    bad = [f["id"] for f in outline.get("families", [])
           if len(f.get("method_ids", [])) == 1 and f["id"] != STANDALONE_GROUP_ID]
    if bad:
        raise RuntimeError(
            f"outline.json has singleton families {bad}; run --normalize-outline "
            "(stage 12.5) before generate_book_artifacts."
        )
```

- [ ] **Step 4: Add `pytest` import to the test file**

At the top of `tests/test_research_book_singleton_merge.py`, ensure `import pytest` is present (added implicitly by the new tests above).

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_research_book_singleton_merge.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add tests/test_research_book_singleton_merge.py swarn_research_mcp/research_book.py
git commit -m "feat(research-book): merge_singletons + assert_no_singletons (Stage 12.5)"
```

---

## Task 1.5: Stage 12.5 CLI entry point + Stage 18 assertion

Stage 12.5 normalizes `outline.json` ONCE, immediately after Stage 12 emits it and BEFORE Stage 13 builds packs. `generate_book_artifacts` (Stage 18) only ASSERTS — no late mutation.

**Files:**
- Modify: `swarn_research_mcp/research_book.py:651` (`main` CLI), `:638` (`generate_book_artifacts`)
- Modify: `.agents/skills/auto-research-orchestrator/SKILL.md` (Stage 12.5 row in stage table)

- [ ] **Step 1: Add `--normalize-outline` flag to the CLI**

In `main` (around line 651), add to the argparse setup:

```python
    parser.add_argument(
        "--normalize-outline",
        action="store_true",
        help="Stage 12.5: read 12_taxonomy/outline.json, run merge_singletons, write back if changed.",
    )
```

In `main`'s body, BEFORE the `--generate` branch:

```python
    if args.normalize_outline:
        run_path = Path(args.run_dir)
        outline = _outline(run_path)
        normalized = merge_singletons(outline)
        if normalized != outline:
            _write_json(run_path / "12_taxonomy" / "outline.json", normalized)
            print(f"normalized: families {len(outline['families'])} -> {len(normalized['families'])}")
        else:
            print("normalized: no singletons to merge")
        return
```

- [ ] **Step 2: Add the assertion inside `generate_book_artifacts`**

In `generate_book_artifacts`, after `outline = _outline(run_path)` (line 640), add:

```python
    assert_no_singletons(outline)
```

NO mutation. Stage 12.5 is responsible for normalizing.

- [ ] **Step 3: Add tests**

Append to `tests/test_research_book_singleton_merge.py`:

```python
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
    monkeypatch.setattr(rb, "verification_gate", lambda _: None)
    with pytest.raises(RuntimeError, match="singleton"):
        rb.generate_book_artifacts(voice_lm_minimal)
```

- [ ] **Step 4: Update orchestrator SKILL stage table — add Stage 12.5**

In `.agents/skills/auto-research-orchestrator/SKILL.md`, find the stage/artifact table. Insert AFTER the Stage 12 row:

```markdown
| 12.5 | `12_taxonomy/outline.json` (normalized — `python -m swarn_research_mcp.research_book {run_dir} --normalize-outline`) |
```

In the same file, document Stage 12.5 in the body:

```markdown
## Stage 12.5 — Normalize outline (deterministic)
After Stage 12 writes `outline.json` and BEFORE Stage 13 builds packs, run:

  `python -m swarn_research_mcp.research_book research_runs/{run_id} --normalize-outline`

This calls `merge_singletons`, which deterministically merges every single-method family into its nearest non-singleton family (or into a `other_{part_id}` catch-all if no graph connection exists). Stage 13's pack-building reads the normalized outline; Stage 18's `generate_book_artifacts` asserts the outline is normalized and refuses to render otherwise.
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_research_book_singleton_merge.py -v`
Expected: PASS (9 tests).

- [ ] **Step 6: Commit**

```bash
git add tests/test_research_book_singleton_merge.py swarn_research_mcp/research_book.py .agents/skills/auto-research-orchestrator/SKILL.md
git commit -m "feat(stage-12.5): CLI normalizer + Stage 18 assertion (no late outline mutation)"
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
- `appendices` — deterministic artifact. Always run the generator; output is the directory `appendices/` with `glossary.md`, `notation.md`, `datasets.md`, `software.md`, `references.md` (NOT a single appendices.md file).
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

**Decision (Stage 16 behavior for appendices):** The `appendices` directory contains four reference files (`glossary.md`, `notation.md`, `datasets.md`, `software.md`) generated deterministically by `_build_appendices_dir`. None of them carry chapter front matter, none receive a verification status, and none participate in the chapter manifest. The orchestrator skill MUST exclude `book:appendices` from the chapter-manifest target list in Stage 16; manifest rows for appendices are not written.

**Files:**
- Test: `tests/test_research_book_appendices_dir.py` (create)
- Modify: `swarn_research_mcp/research_book.py` (`BOOK_FILE_BY_ID`, validator, summary, sidebar, generate)
- Modify: `.agents/skills/chapter-manifest/SKILL.md` and `.agents/skills/auto-research-orchestrator/SKILL.md` — exclude `book:appendices` from manifest targets

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
    assert BOOK_FILE_BY_ID["appendices"] == "appendices"  # directory name, no .md


def test_build_appendices_dir_creates_five_files(voice_lm_minimal):
    outline = json.loads((voice_lm_minimal / "12_taxonomy" / "outline.json").read_text())
    _build_appendices_dir(voice_lm_minimal, outline)
    out = voice_lm_minimal / "14_chapters" / "book" / "appendices"
    assert out.is_dir()
    for name in ("glossary.md", "notation.md", "datasets.md", "software.md", "references.md"):
        assert (out / name).exists(), f"missing {name}"


def test_appendices_references_uses_paper_pool(voice_lm_minimal):
    outline = json.loads((voice_lm_minimal / "12_taxonomy" / "outline.json").read_text())
    _build_appendices_dir(voice_lm_minimal, outline)
    refs = (voice_lm_minimal / "14_chapters" / "book" / "appendices" / "references.md").read_text()
    assert "VALL-E" in refs  # title resolved via semantic_scholar
    assert "(2023)" in refs
    assert "<title unknown>" not in refs


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
    assert (voice_lm_minimal / "14_chapters" / "book" / "appendices" / "glossary.md").exists()


def test_validator_rejects_missing_appendices_directory(voice_lm_minimal):
    issues = validate_research_book_run(voice_lm_minimal)
    # Fixture has no appendices/ directory yet.
    codes = [i["code"] for i in issues]
    assert "missing_book_chapter" in codes
    detail = next(i["detail"] for i in issues if i["code"] == "missing_book_chapter" and "appendices" in i["detail"])
    assert "appendices" in detail
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_research_book_appendices_dir.py -v`
Expected: FAIL.

- [ ] **Step 3: Update `BOOK_FILE_BY_ID`**

In `swarn_research_mcp/research_book.py`, change line 18:
```python
    "appendices": "appendices",
```

- [ ] **Step 4: Update appendices existence check in validator**

Find the loop in `validate_research_book_run` that checks `(run_path / "14_chapters" / "book" / filename).exists()` (around line 352). Replace with:

```python
    for section_id, filename in BOOK_FILE_BY_ID.items():
        target = run_path / "14_chapters" / "book" / filename
        if section_id == "appendices":
            ok = target.is_dir() and all(
                (target / sub).exists()
                for sub in ("glossary.md", "notation.md", "datasets.md", "software.md", "references.md")
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
    out_dir = run_dir / "14_chapters" / "book" / "appendices"
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

    # references.md — every promoted paper, sorted by arxiv_id, resolved via paper_pool/semantic_scholar.
    refs = ["# References", ""]
    promoted_path = run_dir / "07_scoring" / "promoted_papers.json"
    if promoted_path.exists():
        promoted = _load_json(promoted_path).get("promoted_papers") or []
        for entry in sorted(promoted, key=lambda e: e.get("arxiv_id", "")):
            aid = entry.get("arxiv_id", "")
            if not aid:
                continue
            try:
                cite = resolve_paper_citation(run_dir, aid)
                refs.append(f"- [arxiv:{cite['arxiv_id']}] {cite['title']} ({cite['year']})")
            except MissingCitationError as exc:
                raise MissingCitationError(
                    f"references.md generation blocked: {exc}"
                ) from exc
    (out_dir / "references.md").write_text("\n".join(refs) + "\n", encoding="utf-8")
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

In `_build_summary` (line 595), the loop appends `[Title](../14_chapters/book/{filename})`. For `appendices` the target is a directory; link to `../14_chapters/book/appendices/glossary.md` as the entry point. Add a special case:

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
Expected: existing tests still pass (any that asserted `appendices.md` should now be updated to assert the directory).

- [ ] **Step 9: Update existing artifact tests if they mention `appendices.md`**

Run: `grep -n "appendices.md" tests/`. For each hit, update to `appendices` (directory) or to a specific sub-file. If the assertion was on the file existing, change to `(... / "appendices" / "glossary.md").exists()`.

Run: `pytest tests/ -v`
Expected: PASS.

- [ ] **Step 10: Update `chapter-manifest` SKILL — exclude `book:appendices`**

In `.agents/skills/chapter-manifest/SKILL.md`, find the section that enumerates `chapter_targets` (`book:{id}` / `family:{id}` / `method:{id}`). Add a hard rule:

```markdown
## Hard rules
- `book:appendices` is NOT a manifest target. The appendices directory is generated deterministically (`appendices/`) and contains reference files without chapter front matter or verification status. Skip any `book:appendices` target passed to this stage and log `skipped: appendices is directory`.
```

- [ ] **Step 11: Update orchestrator SKILL — Stage 16 target list**

In `.agents/skills/auto-research-orchestrator/SKILL.md`, find Stage 16 description. Add:

```markdown
Stage 16 chapter_targets EXCLUDE `book:appendices` — the appendices directory is generated by `_build_appendices_dir` (Stage 18) and has no per-file front matter. Do not dispatch `chapter_manifest_builder` for `book:appendices`.
```

- [ ] **Step 12: Commit**

```bash
git add tests/ swarn_research_mcp/research_book.py .agents/skills/chapter-manifest/SKILL.md .agents/skills/auto-research-orchestrator/SKILL.md
git commit -m "feat(research-book): hard-switch appendices to appendices/ directory; exclude from manifest"
```

---

## Task 4.3: Update `book-section-writing` SKILL appendices row

**Files:**
- Modify: `.agents/skills/book-section-writing/SKILL.md`

- [ ] **Step 1: Update the table and per-section text**

In `## Output filenames`, change the appendices row to:
```markdown
| `appendices`         | `appendices/` (directory)   | n/a (deterministic)  |
```

In `## Per-section structure`, the appendices row was already updated in Task 2.2 to mention the directory. Verify it reads:
```markdown
- `appendices` — deterministic artifact. Always run the generator; output is the directory `appendices/` with `glossary.md`, `notation.md`, `datasets.md`, `software.md`, `references.md`.
```

- [ ] **Step 2: Commit**

```bash
git add .agents/skills/book-section-writing/SKILL.md
git commit -m "docs(book-section-writing): appendices output is a directory, no .md file"
```

---

## Task 4.4: Render parts in SUMMARY.md, sidebar.json, and method_taxonomy.md

Parts must be **reader-visible**. The current `_build_summary` lists families flat under "## Families and Methods"; readers cannot see that the book is organized into parts. Same for `_build_sidebar` and `_build_method_taxonomy`.

**Files:**
- Test: extend `tests/test_research_book_artifacts.py`
- Modify: `swarn_research_mcp/research_book.py:532` (`_build_method_taxonomy`), `:595` (`_build_summary`), `:614` (`_build_sidebar`)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_research_book_artifacts.py`:

```python
def test_summary_groups_families_under_parts(voice_lm_minimal, monkeypatch):
    import json
    from swarn_research_mcp import research_book as rb
    op = voice_lm_minimal / "12_taxonomy" / "outline.json"
    outline = json.loads(op.read_text())
    # Manually merge fam_codec into fam_flow so we have two families to spread across parts.
    outline["families"] = [
        {"id": "fam_flow", "title": "flow matching", "method_ids": ["m_voicebox", "m_excluded", "m_valle"]},
        {"id": "fam_codec_b", "title": "discrete codec B", "method_ids": ["m_b1", "m_b2"]},
    ]
    outline["methods"].extend([
        {"id": "m_b1", "title": "B1", "arxiv_id": "0009.0001", "family_id": "fam_codec_b"},
        {"id": "m_b2", "title": "B2", "arxiv_id": "0009.0002", "family_id": "fam_codec_b"},
    ])
    outline["methods"][0]["family_id"] = "fam_flow"  # m_valle now under flow
    outline["parts"] = [
        {"id": "generation", "title": "Generation", "family_ids": ["fam_flow"]},
        {"id": "tokenization", "title": "Tokenization", "family_ids": ["fam_codec_b"]},
    ]
    op.write_text(json.dumps(outline))
    monkeypatch.setattr(rb, "verification_gate", lambda _: None)
    monkeypatch.setattr(rb, "_paper_label", lambda aid, p, pool: f"[arxiv:{aid}] x (2024)")
    rb.generate_book_artifacts(voice_lm_minimal)
    summary = (voice_lm_minimal / "16_book" / "SUMMARY.md").read_text()
    assert "## Part 1: Generation" in summary
    assert "## Part 2: Tokenization" in summary
    # Family sits under its part heading.
    assert summary.index("## Part 1: Generation") < summary.index("flow matching")
    assert summary.index("flow matching") < summary.index("## Part 2: Tokenization")


def test_sidebar_groups_families_under_parts(voice_lm_minimal, monkeypatch):
    import json
    from swarn_research_mcp import research_book as rb
    op = voice_lm_minimal / "12_taxonomy" / "outline.json"
    outline = json.loads(op.read_text())
    outline["families"] = [
        {"id": "fam_flow", "title": "flow matching", "method_ids": ["m_voicebox", "m_excluded", "m_valle"]},
        {"id": "fam_codec_b", "title": "discrete codec B", "method_ids": ["m_b1", "m_b2"]},
    ]
    outline["methods"].extend([
        {"id": "m_b1", "title": "B1", "arxiv_id": "0009.0001", "family_id": "fam_codec_b"},
        {"id": "m_b2", "title": "B2", "arxiv_id": "0009.0002", "family_id": "fam_codec_b"},
    ])
    outline["methods"][0]["family_id"] = "fam_flow"
    outline["parts"] = [
        {"id": "generation", "title": "Generation", "family_ids": ["fam_flow"]},
        {"id": "tokenization", "title": "Tokenization", "family_ids": ["fam_codec_b"]},
    ]
    op.write_text(json.dumps(outline))
    monkeypatch.setattr(rb, "verification_gate", lambda _: None)
    monkeypatch.setattr(rb, "_paper_label", lambda aid, p, pool: f"[arxiv:{aid}] x (2024)")
    rb.generate_book_artifacts(voice_lm_minimal)
    sidebar = json.loads((voice_lm_minimal / "16_book" / "sidebar.json").read_text())
    titles = [item["title"] for item in sidebar["items"]]
    assert "Generation" in titles
    assert "Tokenization" in titles
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_research_book_artifacts.py -v`
Expected: FAIL — current builders produce flat structure.

- [ ] **Step 3: Rewrite `_build_summary` to group by part**

In `swarn_research_mcp/research_book.py`, replace the body of `_build_summary` (lines 595–611) with:

```python
def _build_summary(outline: dict[str, Any]) -> str:
    methods = _method_by_id(outline)
    family_by_id = {f["id"]: f for f in outline.get("families", [])}
    lines = ["# Summary", "", "## Book", ""]
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

    parts = outline.get("parts", []) or []
    for idx, part in enumerate(parts, start=1):
        lines.extend(["", f"## Part {idx}: {part['title']}", ""])
        for fid in part.get("family_ids", []) or []:
            family = family_by_id.get(fid)
            if not family:
                continue
            if family.get("is_group"):
                # Standalone group: list methods directly, no family chapter link.
                for method_id in family.get("method_ids", []):
                    method = methods.get(method_id)
                    if method:
                        lines.append(f"- [{method['title']}](../14_chapters/methods/{method_id}.md)")
            else:
                lines.append(f"- [{family['title']}](../14_chapters/families/{fid}.md)")
                for method_id in family.get("method_ids", []):
                    method = methods.get(method_id)
                    if method:
                        lines.append(f"  - [{method['title']}](../14_chapters/methods/{method_id}.md)")
    return "\n".join(lines)
```

- [ ] **Step 4: Rewrite `_build_sidebar` similarly**

Replace the body of `_build_sidebar` (lines 614–637) with:

```python
def _build_sidebar(outline: dict[str, Any]) -> dict[str, Any]:
    methods = _method_by_id(outline)
    family_by_id = {f["id"]: f for f in outline.get("families", [])}
    book_items = []
    for section in outline.get("book_sections", []):
        filename = BOOK_FILE_BY_ID.get(section["id"])
        if not filename:
            continue
        path = (f"14_chapters/book/{filename}/glossary.md"
                if section["id"] == "appendices" else f"14_chapters/book/{filename}")
        book_items.append({"title": section["title"], "path": path})

    part_items = []
    for part in outline.get("parts", []) or []:
        children = []
        for fid in part.get("family_ids", []) or []:
            family = family_by_id.get(fid)
            if not family:
                continue
            if family.get("is_group"):
                for mid in family.get("method_ids", []) or []:
                    m = methods.get(mid)
                    if m:
                        children.append({"title": m["title"], "path": f"14_chapters/methods/{mid}.md"})
            else:
                method_kids = []
                for mid in family.get("method_ids", []) or []:
                    m = methods.get(mid)
                    if m:
                        method_kids.append({"title": m["title"], "path": f"14_chapters/methods/{mid}.md"})
                children.append({
                    "title": family["title"],
                    "path": f"14_chapters/families/{fid}.md",
                    "children": method_kids,
                })
        part_items.append({"title": part["title"], "children": children})

    return {"items": [{"title": "Book", "children": book_items}] + part_items}
```

- [ ] **Step 5: Rewrite `_build_method_taxonomy` to render parts**

In `swarn_research_mcp/research_book.py:532`, replace `_build_method_taxonomy(outline)` with:

```python
def _build_method_taxonomy(outline: dict[str, Any]) -> str:
    methods = _method_by_id(outline)
    family_by_id = {f["id"]: f for f in outline.get("families", [])}
    lines = ["# Method Taxonomy", "",
             "This taxonomy is generated from `12_taxonomy/outline.json` so it stays complete and navigable.",
             ""]
    for idx, part in enumerate(outline.get("parts", []) or [], start=1):
        lines.extend(["", f"## Part {idx}: {part['title']}", ""])
        for fid in part.get("family_ids", []) or []:
            family = family_by_id.get(fid)
            if not family:
                continue
            if family.get("is_group"):
                for mid in family.get("method_ids", []) or []:
                    m = methods.get(mid)
                    if m:
                        lines.append(f"- [{m['title']}](../methods/{mid}.md) [arxiv:{m.get('arxiv_id', '')}]")
            else:
                lines.append(f"- [{family['title']}](../families/{fid}.md)")
                for mid in family.get("method_ids", []) or []:
                    m = methods.get(mid)
                    if m:
                        lines.append(f"  - [{m['title']}](../methods/{mid}.md) [arxiv:{m.get('arxiv_id', '')}]")
    return "\n".join(lines)
```

- [ ] **Step 6: Update existing flat-summary tests**

Run: `grep -n "Families and Methods" tests/`. For each hit, update expectations to match the new `## Part N: <title>` heading structure.

- [ ] **Step 7: Run tests**

Run: `pytest tests/ -v`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add tests/ swarn_research_mcp/research_book.py
git commit -m "feat(research-book): SUMMARY/sidebar/method_taxonomy group families under parts (reader-visible)"
```

---

# Wave 5 — Verification quarantine (passed → main nav, failed → NEEDS_REVIEW.md)

## Task 5.1: Verification quarantine — collect excluded, emit `NEEDS_REVIEW.md`, never raise

The product behavior: `generate_book_artifacts` always succeeds when prerequisites are met. Excluded chapters are quarantined — they stay on disk but are NOT linked from `SUMMARY.md` or `sidebar.json`. A separate `16_book/NEEDS_REVIEW.md` lists every excluded chapter with its `status` and `reason`. Readers always get a working book.

**Files:**
- Test: `tests/test_research_book_verification_quarantine.py` (create)
- Modify: `swarn_research_mcp/research_book.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_research_book_verification_quarantine.py
from __future__ import annotations
import json
import pytest
from swarn_research_mcp.research_book import (
    collect_excluded,
    write_needs_review,
    generate_book_artifacts,
)


def test_collect_excluded_finds_excluded_chapters(voice_lm_minimal):
    offenders = collect_excluded(voice_lm_minimal)
    assert any(o["id"] == "m_excluded" and o["status"].startswith("excluded_")
               for o in offenders)


def test_collect_excluded_returns_empty_when_all_passed(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    assert collect_excluded(run) == []


def test_write_needs_review_lists_offenders(voice_lm_minimal):
    offenders = [{"type": "methods", "id": "m_excluded",
                  "status": "excluded_unsupported_claims",
                  "reason": "claims_unsupported=3"}]
    write_needs_review(voice_lm_minimal, offenders)
    text = (voice_lm_minimal / "16_book" / "NEEDS_REVIEW.md").read_text()
    assert "m_excluded" in text
    assert "excluded_unsupported_claims" in text
    assert "claims_unsupported=3" in text


def test_generate_succeeds_with_excluded_chapters(voice_lm_minimal, monkeypatch):
    """Quarantine: excluded chapters do NOT block SUMMARY.md generation."""
    from swarn_research_mcp import research_book as rb
    op = voice_lm_minimal / "12_taxonomy" / "outline.json"
    outline = json.loads(op.read_text())
    # Pre-normalize the singleton via the standalone group so assertion passes.
    outline["families"] = [
        {"id": "fam_flow", "title": "flow matching", "method_ids": ["m_voicebox", "m_excluded"]},
        {"id": "standalone", "title": "Standalone / Emerging Methods",
         "method_ids": ["m_valle"], "is_group": True},
    ]
    outline["methods"][0]["family_id"] = "standalone"  # m_valle
    outline["parts"] = [
        {"id": "generation", "title": "Generation", "family_ids": ["fam_flow"]},
        {"id": "standalone_methods", "title": "Standalone / Emerging Methods",
         "family_ids": ["standalone"]},
    ]
    op.write_text(json.dumps(outline))
    monkeypatch.setattr(rb, "_paper_label", lambda aid, p, pool: f"[arxiv:{aid}] x (2024)")
    rb.generate_book_artifacts(voice_lm_minimal)  # MUST NOT raise

    summary = (voice_lm_minimal / "16_book" / "SUMMARY.md").read_text()
    assert "m_excluded" not in summary  # quarantined out
    assert "m_valle" in summary  # standalone method visible

    needs = voice_lm_minimal / "16_book" / "NEEDS_REVIEW.md"
    assert needs.exists()
    assert "m_excluded" in needs.read_text()


def test_excluded_chapters_omitted_from_sidebar(voice_lm_minimal, monkeypatch):
    from swarn_research_mcp import research_book as rb
    op = voice_lm_minimal / "12_taxonomy" / "outline.json"
    outline = json.loads(op.read_text())
    outline["families"] = [
        {"id": "fam_flow", "title": "flow matching", "method_ids": ["m_voicebox", "m_excluded"]},
        {"id": "standalone", "title": "Standalone / Emerging Methods",
         "method_ids": ["m_valle"], "is_group": True},
    ]
    outline["methods"][0]["family_id"] = "standalone"
    outline["parts"] = [
        {"id": "generation", "title": "Generation", "family_ids": ["fam_flow"]},
        {"id": "standalone_methods", "title": "Standalone / Emerging Methods",
         "family_ids": ["standalone"]},
    ]
    op.write_text(json.dumps(outline))
    monkeypatch.setattr(rb, "_paper_label", lambda aid, p, pool: f"[arxiv:{aid}] x (2024)")
    rb.generate_book_artifacts(voice_lm_minimal)
    sidebar = json.loads((voice_lm_minimal / "16_book" / "sidebar.json").read_text())
    titles = json.dumps(sidebar)
    assert "m_excluded" not in titles
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_research_book_verification_quarantine.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `collect_excluded` and `write_needs_review`**

In `swarn_research_mcp/research_book.py`, add (note: NO `VerificationGateError` — quarantine never raises):

```python
def collect_excluded(run_dir: Path | str) -> list[dict[str, str]]:
    """Walk 14_chapters/ and return every chapter with front-matter status starting 'excluded_'."""
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
                offenders.append({"type": sub, "id": path.stem,
                                  "status": status, "reason": reason})
    return offenders


def write_needs_review(run_dir: Path | str, offenders: list[dict[str, str]]) -> None:
    """Emit 16_book/NEEDS_REVIEW.md listing quarantined chapters."""
    out = Path(run_dir) / "16_book" / "NEEDS_REVIEW.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Needs Review", "",
             "These chapters did not pass verification and are NOT linked from SUMMARY.md.",
             "They remain on disk under `14_chapters/` and can be re-attempted with",
             "`phase=write fix_excluded=true`.",
             "", "## Quarantined chapters", ""]
    if not offenders:
        lines.append("_(none — every chapter passed)_")
    for o in offenders:
        lines.append(f"- **{o['type']}/{o['id']}** — `{o['status']}` ({o['reason']})")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
```

- [ ] **Step 4: Update `_build_summary`, `_build_sidebar`, `_build_method_taxonomy` to skip excluded methods/families**

Add a helper at the top of `research_book.py`:

```python
def _excluded_ids(run_dir: Path) -> set[str]:
    return {o["id"] for o in collect_excluded(run_dir)}
```

Modify each builder's signature to accept an optional `excluded: set[str]` parameter and skip any family/method whose id is in that set:

```python
def _build_summary(outline: dict[str, Any], excluded: set[str] | None = None) -> str:
    excluded = excluded or set()
    methods = _method_by_id(outline)
    family_by_id = {f["id"]: f for f in outline.get("families", [])}
    lines = ["# Summary", "", "## Book", ""]
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

    for idx, part in enumerate(outline.get("parts", []) or [], start=1):
        lines.extend(["", f"## Part {idx}: {part['title']}", ""])
        for fid in part.get("family_ids", []) or []:
            if fid in excluded:
                continue
            family = family_by_id.get(fid)
            if not family:
                continue
            if family.get("is_group"):
                for method_id in family.get("method_ids", []):
                    if method_id in excluded:
                        continue
                    method = methods.get(method_id)
                    if method:
                        lines.append(f"- [{method['title']}](../14_chapters/methods/{method_id}.md)")
            else:
                lines.append(f"- [{family['title']}](../14_chapters/families/{fid}.md)")
                for method_id in family.get("method_ids", []):
                    if method_id in excluded:
                        continue
                    method = methods.get(method_id)
                    if method:
                        lines.append(f"  - [{method['title']}](../14_chapters/methods/{method_id}.md)")
    return "\n".join(lines)
```

Apply the same `excluded` filtering to `_build_sidebar` and `_build_method_taxonomy`.

- [ ] **Step 5: Wire it all into `generate_book_artifacts` (quarantine, no raise)**

Replace `generate_book_artifacts` body (around line 638) with:

```python
def generate_book_artifacts(run_dir: Path | str) -> dict[str, int]:
    run_path = Path(run_dir)
    outline = _outline(run_path)
    assert_no_singletons(outline)

    offenders = collect_excluded(run_path)
    write_needs_review(run_path, offenders)
    excluded_ids = {o["id"] for o in offenders}

    taxonomy_path = run_path / "14_chapters" / "book" / BOOK_FILE_BY_ID["method_taxonomy"]
    _write_markdown_preserving_front_matter(
        taxonomy_path, _build_method_taxonomy(outline, excluded_ids)
    )
    _build_appendices_dir(run_path, outline)

    (run_path / "16_book").mkdir(parents=True, exist_ok=True)
    (run_path / "16_book" / "SUMMARY.md").write_text(
        _build_summary(outline, excluded_ids) + "\n", encoding="utf-8"
    )
    _write_json(run_path / "16_book" / "sidebar.json",
                _build_sidebar(outline, excluded_ids))
    return {
        "families": len(outline.get("families", [])),
        "methods": len(outline.get("methods", [])),
        "quarantined": len(offenders),
    }
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_research_book_verification_quarantine.py -v`
Expected: PASS (5 tests).

- [ ] **Step 7: Update earlier task tests that monkeypatched `verification_gate`**

In `tests/test_research_book_singleton_merge.py`, replace any `monkeypatch.setattr(rb, "verification_gate", lambda _: None)` with no-op (the function no longer exists or is no longer raising). Run `pytest tests/ -v` and fix mismatches.

- [ ] **Step 8: Commit**

```bash
git add tests/ swarn_research_mcp/research_book.py
git commit -m "feat(research-book): quarantine excluded chapters from SUMMARY/sidebar; never block the book"
```

---

## Task 5.2: Update orchestrator SKILL with quarantine + fix_excluded loop

**Files:**
- Modify: `.agents/skills/auto-research-orchestrator/SKILL.md`

- [ ] **Step 1: Document quarantine at stage 18**

Find the Stage table row for stage 18 (`SUMMARY.md`...). Append AFTER the table:

```markdown
## Stage 18 verification quarantine
At stage 18, `generate_book_artifacts` ALWAYS produces `SUMMARY.md`, `sidebar.json`, `04_method_taxonomy.md`, and `appendices/` (assuming Stage 12.5 normalized the outline). Chapters whose front-matter `status` starts with `excluded_` are **quarantined** — they remain on disk under `14_chapters/` but are NOT linked from main navigation. The list of quarantined chapters is written to `16_book/NEEDS_REVIEW.md`, which always exists (even if empty).
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
4. Re-run stage 18 (`generate_book_artifacts`); chapters now passing get added to main navigation, the rest stay quarantined in `NEEDS_REVIEW.md`. No retry budget — a single attempt per offender per invocation.
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

- [ ] **Step 3: Verify quarantine on the audited run**

Run:
```bash
python -c "
from swarn_research_mcp.research_book import collect_excluded
offenders = collect_excluded('research_runs/voice-language-model-text-speech-io-20260509-222749')
print(f'quarantined: {len(offenders)} chapters')
for o in offenders[:10]:
    print(f'  {o[\"type\"]}/{o[\"id\"]}: {o[\"status\"]} ({o[\"reason\"]})')
"
```

Expected: a non-zero count with several `excluded_unsupported_claims` and `excluded_gaps_missing` entries.

- [ ] **Step 4: Commit any stray changes (if any)**

```bash
git status
# if clean, skip
```

---

# Self-Review

**Spec coverage:**
- §1 parts (validator + reader-visible) → Task 1.3 (validator + empty_part), 4.4 (render in SUMMARY/sidebar/method_taxonomy), 1.6 (skill)
- §2 singleton policy (evidence-based merge, otherwise standalone group) → Task 1.4, 1.5, 1.6
- §3 family headings → Task 3.1 (lint), 3.2 (skill)
- §4 method headings → Task 3.1 (lint), 3.3 (skill)
- §5 verification quarantine (no hard gate) → Task 5.1, 5.2
- §6a bibliography bug → Task 1.1 (multi-shape lookup), 1.2 (loud `_paper_label`), 2.1 (regression), 2.2 (skill)
- §6b goals → Task 4.1
- §6c appendices (`appendices/` directory, glossary + notation + datasets + software + references) → Task 4.2, 4.3
- §7 SDK migration → **deferred to separate plan** `2026-05-10-codex-sdk-context-relief-pilot.md`

**Type consistency:**
- `MissingCitationError` defined in Task 1.1, used in 1.2, 2.1, 4.2 (references.md)
- `collect_excluded` + `write_needs_review` defined in Task 5.1, used by `generate_book_artifacts` (no exception type — quarantine never raises)
- `merge_singletons` + `assert_no_singletons` defined in Task 1.4, called in 1.5
- `STANDALONE_GROUP_ID = "standalone"` and `STANDALONE_PART_ID = "standalone_methods"` are stable identifiers used in 1.4, 4.4, and all rendering tests
- `BOOK_FILE_BY_ID["appendices"]` is `"appendices"` (no `.md`, no leading `99_`) after Task 4.2
- `_diff_headings` returns `{missing, extra, out_of_order}` everywhere; `## References` allowed only as last `##`
- All rendering helpers (`_build_summary`, `_build_sidebar`, `_build_method_taxonomy`) accept `excluded: set[str] | None` and skip excluded ids

**Real-shape coverage:**
- Wave 0 fixture has list-shaped paper_pool (no titles), semantic_scholar metadata, mixed pass/excluded chapters, old skill heading shapes
- Tasks 1.1, 2.1, 3.1, 4.2, 4.4, 5.1 all run against the fixture
- Quarantine model verified end-to-end in Task 5.1 (excluded chapter remains on disk; SUMMARY does not link to it; NEEDS_REVIEW.md lists it)
