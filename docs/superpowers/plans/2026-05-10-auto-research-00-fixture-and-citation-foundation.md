# Auto Research Shard 00: Fixture and Citation Foundation

> **For agentic workers:** Implement this shard only. Do not load or execute the full reviewed source plan unless a referenced section is missing from this shard. Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` for execution.

**Source Material:** `docs/superpowers/plans/2026-05-10-codex-book-style-alignment.md` is the reviewed source plan. This shard copies the relevant task text and adds execution boundaries.

**Goal:** Create the real-shape test fixture and citation lookup foundation that every later shard depends on.

**Prerequisites:** Clean working branch or intentional dirty-tree awareness; no previous shard required.

**Exit Criteria:** `pytest tests/test_research_book_paper_lookup.py -v` and `pytest tests/test_research_book_bibliography.py -v` pass after their tasks are implemented.

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

- [ ] **Step 3: Update callers of `_paper_label` to stop emitting unknown placeholders**

Search for uses: `grep -n "_paper_label(" swarn_research_mcp/research_book.py`. Each caller should stop relying on `<title unknown>` / `<year unknown>` fallback text. At this point, existing callers may still let `MissingCitationError` propagate; Task 4.2 changes appendices generation to record citation issues in `NEEDS_REVIEW.md` while still rendering the book.

```python
label = _paper_label(arxiv_id, promoted, pool)
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_research_book_paper_lookup.py swarn_research_mcp/research_book.py
git commit -m "fix(research-book): _paper_label fails loud instead of emitting <title unknown>"
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
- `method_taxonomy` — deterministic artifact. Always run `python -m swarn_research_mcp.research_book research_runs/{run_id} --generate`. Manual drafting is forbidden because generated references are resolved through `_paper_label` + `resolve_paper_citation`; unresolved citation metadata is surfaced in `16_book/NEEDS_REVIEW.md` rather than silently emitting `<title unknown>` / `<year unknown>` in the reader-facing book.
- `appendices` — deterministic artifact. Always run the generator; output is the directory `appendices/` with `glossary.md`, `notation.md`, `datasets.md`, `software.md`, `references.md` (NOT a single appendices.md file).
```

- [ ] **Step 2: Commit**

```bash
git add .agents/skills/book-section-writing/SKILL.md
git commit -m "docs(book-section-writing): bibliography fails loud; appendices is a directory"
```

---
