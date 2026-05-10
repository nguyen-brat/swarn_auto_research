# Auto Research Shard 04: Verification Quarantine and Final Validation

> **For agentic workers:** Implement this shard only. Do not load or execute the full reviewed source plan unless a referenced section is missing from this shard. Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` for execution.

**Source Material:** `docs/superpowers/plans/2026-05-10-codex-book-style-alignment.md` is the reviewed source plan. This shard copies the relevant task text and adds execution boundaries.

**Goal:** Quarantine failed chapters, surface citation issues in NEEDS_REVIEW.md, update orchestrator docs, and run final validation.

**Prerequisites:** Shards 00 through 03 completed and committed. Appendices directory returns citation issues.

**Exit Criteria:** `pytest tests/test_research_book_verification_quarantine.py -v`, `pytest tests/ -v`, and the audited-run validation commands in Task F.1 complete with expected output.

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

# Wave 5 — Verification quarantine (passed → main nav, failed → NEEDS_REVIEW.md)

## Task 5.1: Verification quarantine — collect excluded, emit `NEEDS_REVIEW.md`, never raise

The product behavior: `generate_book_artifacts` always succeeds when prerequisites are met. Excluded chapters are quarantined — they stay on disk but are NOT linked from `SUMMARY.md` or `sidebar.json`. Missing citation metadata is recorded in the same review file while `references.md` still renders an unresolved marker. A separate `16_book/NEEDS_REVIEW.md` lists every excluded chapter and citation issue with its `status` and `reason`. Readers always get a working book.

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


def test_excluded_family_keeps_passed_methods_visible(tmp_path):
    """If a family chapter fails verification but its method chapters passed,
    the methods stay reachable (rendered flat under the part)."""
    from swarn_research_mcp import research_book as rb
    run = tmp_path / "run"
    for sub in ("12_taxonomy", "07_scoring", "16_book",
                "14_chapters/families", "14_chapters/methods", "14_chapters/book",
                "06_expansion"):
        (run / sub).mkdir(parents=True, exist_ok=True)
    outline = {
        "topic": "t",
        "book_sections": [{"id": k, "title": k} for k in
            ["preface", "motivating_intro", "core_concepts", "goals", "method_taxonomy",
             "shared_examples", "evaluation_outlook", "appendices"]],
        "parts": [{"id": "p1", "title": "P1", "family_ids": ["fam_a"]},
                  {"id": "p2", "title": "P2", "family_ids": ["fam_b"]}],
        "families": [
            {"id": "fam_a", "title": "Family A", "method_ids": ["m1", "m2"]},
            {"id": "fam_b", "title": "Family B", "method_ids": ["m3", "m4"]},
        ],
        "methods": [{"id": f"m{i}", "title": f"M{i}", "arxiv_id": f"1.{i}",
                     "family_id": fam} for i, fam in [(1,"fam_a"),(2,"fam_a"),(3,"fam_b"),(4,"fam_b")]],
    }
    (run / "12_taxonomy" / "outline.json").write_text(json.dumps(outline))
    (run / "07_scoring" / "promoted_papers.json").write_text(json.dumps(
        {"promoted_papers": [{"arxiv_id": f"1.{i}", "title": f"M{i}", "year": 2024} for i in (1,2,3,4)]}))
    (run / "02_paper_pool").mkdir(parents=True, exist_ok=True)
    (run / "02_paper_pool" / "paper_pool.json").write_text(json.dumps([
        {"arxiv_id": f"1.{i}", "title": f"M{i}", "year": 2024} for i in (1,2,3,4)
    ]))
    (run / "06_expansion" / "known_concepts_snapshot.json").write_text('{"known_concepts": []}')
    # fam_a chapter fails verification; m1/m2 pass.
    (run / "14_chapters" / "families" / "fam_a.md").write_text(
        '---\nchapter_id: fam_a\nstatus: excluded_unsupported_claims\nstatus_reason: "x"\n---\n# A\n')
    (run / "14_chapters" / "families" / "fam_b.md").write_text(
        '---\nchapter_id: fam_b\nstatus: passed\n---\n# B\n')
    for mid in ("m1", "m2", "m3", "m4"):
        (run / "14_chapters" / "methods" / f"{mid}.md").write_text(
            f'---\nchapter_id: {mid}\nstatus: passed\n---\n# {mid}\n')

    rb.generate_book_artifacts(run)
    summary = (run / "16_book" / "SUMMARY.md").read_text()
    # fam_a wrapper is NOT linked, but m1 and m2 ARE reachable flat.
    assert "Family A" not in summary or "../14_chapters/families/fam_a.md" not in summary
    assert "../14_chapters/methods/m1.md" in summary
    assert "../14_chapters/methods/m2.md" in summary
    # fam_b wrapper still appears.
    assert "../14_chapters/families/fam_b.md" in summary


def test_excluded_book_section_omitted_from_summary(tmp_path):
    """If a book chapter (e.g. core_concepts) fails verification, it is omitted
    from SUMMARY.md's '## Book' list."""
    from swarn_research_mcp import research_book as rb
    run = tmp_path / "run"
    for sub in ("12_taxonomy", "07_scoring", "16_book",
                "14_chapters/families", "14_chapters/methods", "14_chapters/book",
                "06_expansion", "02_paper_pool"):
        (run / sub).mkdir(parents=True, exist_ok=True)
    outline = {
        "topic": "t",
        "book_sections": [{"id": k, "title": k} for k in
            ["preface", "motivating_intro", "core_concepts", "goals", "method_taxonomy",
             "shared_examples", "evaluation_outlook", "appendices"]],
        "parts": [{"id": "p1", "title": "P1", "family_ids": ["fam_a"]},
                  {"id": "p2", "title": "P2", "family_ids": ["fam_b"]}],
        "families": [
            {"id": "fam_a", "title": "A", "method_ids": ["m1", "m2"]},
            {"id": "fam_b", "title": "B", "method_ids": ["m3", "m4"]},
        ],
        "methods": [{"id": f"m{i}", "title": f"M{i}", "arxiv_id": f"1.{i}",
                     "family_id": fam} for i, fam in [(1,"fam_a"),(2,"fam_a"),(3,"fam_b"),(4,"fam_b")]],
    }
    (run / "12_taxonomy" / "outline.json").write_text(json.dumps(outline))
    (run / "07_scoring" / "promoted_papers.json").write_text(json.dumps(
        {"promoted_papers": [{"arxiv_id": f"1.{i}", "title": f"M{i}", "year": 2024} for i in (1,2,3,4)]}))
    (run / "02_paper_pool" / "paper_pool.json").write_text(json.dumps([
        {"arxiv_id": f"1.{i}", "title": f"M{i}", "year": 2024} for i in (1,2,3,4)
    ]))
    (run / "06_expansion" / "known_concepts_snapshot.json").write_text('{"known_concepts": []}')
    # core_concepts.md (file 02_core_concepts.md) carries chapter_id from front matter.
    (run / "14_chapters" / "book" / "02_core_concepts.md").write_text(
        '---\nchapter_id: core_concepts\nstatus: excluded_unsupported_claims\nstatus_reason: "x"\n---\n# CC\n')
    # All other book sections passed.
    for fname, cid in [("00_preface.md", "preface"), ("01_motivating_intro.md", "motivating_intro"),
                       ("03_goals.md", "goals"), ("04_method_taxonomy.md", "method_taxonomy"),
                       ("05_shared_examples.md", "shared_examples"),
                       ("98_evaluation_outlook.md", "evaluation_outlook")]:
        (run / "14_chapters" / "book" / fname).write_text(
            f'---\nchapter_id: {cid}\nstatus: passed\n---\n# {cid}\n')
    for fid in ("fam_a", "fam_b"):
        (run / "14_chapters" / "families" / f"{fid}.md").write_text(
            f'---\nchapter_id: {fid}\nstatus: passed\n---\n# {fid}\n')
    for mid in ("m1", "m2", "m3", "m4"):
        (run / "14_chapters" / "methods" / f"{mid}.md").write_text(
            f'---\nchapter_id: {mid}\nstatus: passed\n---\n# {mid}\n')

    rb.generate_book_artifacts(run)
    summary = (run / "16_book" / "SUMMARY.md").read_text()
    # core_concepts is NOT linked from the Book list.
    assert "02_core_concepts.md" not in summary
    # NEEDS_REVIEW.md lists it.
    needs = (run / "16_book" / "NEEDS_REVIEW.md").read_text()
    assert "core_concepts" in needs


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


def test_missing_citation_metadata_goes_to_needs_review(tmp_path):
    """Missing citation metadata should not block a readable book."""
    from swarn_research_mcp import research_book as rb
    run = tmp_path / "run"
    for sub in ("12_taxonomy", "07_scoring", "16_book", "14_chapters/book"):
        (run / sub).mkdir(parents=True, exist_ok=True)
    outline = {
        "topic": "t",
        "book_sections": [{"id": k, "title": k} for k in
            ["preface", "motivating_intro", "core_concepts", "goals", "method_taxonomy",
             "shared_examples", "evaluation_outlook", "appendices"]],
        "parts": [{"id": "p1", "title": "P1", "family_ids": ["fam_a"]},
                  {"id": "p2", "title": "P2", "family_ids": ["fam_b"]}],
        "families": [
            {"id": "fam_a", "title": "A", "method_ids": ["m1", "m2"]},
            {"id": "fam_b", "title": "B", "method_ids": ["m3", "m4"]},
        ],
        "methods": [{"id": f"m{i}", "title": f"M{i}", "arxiv_id": f"1.{i}",
                     "family_id": fam} for i, fam in [(1,"fam_a"),(2,"fam_a"),(3,"fam_b"),(4,"fam_b")]],
    }
    (run / "12_taxonomy" / "outline.json").write_text(json.dumps(outline))
    (run / "07_scoring" / "promoted_papers.json").write_text(json.dumps(
        {"promoted_papers": [{"arxiv_id": "1.1"}]}))

    rb.generate_book_artifacts(run)

    refs = (run / "14_chapters" / "book" / "appendices" / "references.md").read_text()
    assert "[arxiv:1.1] <citation metadata missing>" in refs
    needs = (run / "16_book" / "NEEDS_REVIEW.md").read_text()
    assert "citation/1.1" in needs
    assert "missing_citation_metadata" in needs
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_research_book_verification_quarantine.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `collect_excluded` and `write_needs_review`**

In `swarn_research_mcp/research_book.py`, add (note: NO `VerificationGateError` — quarantine never raises):

```python
def collect_excluded(run_dir: Path | str) -> list[dict[str, str]]:
    """Walk 14_chapters/ and return every chapter with front-matter status starting 'excluded_'.

    The returned `id` comes from the front-matter `chapter_id` field (NOT the file stem).
    Book chapter files are named `00_preface.md` etc., but `chapter_id: preface` is the
    key used in `outline.book_sections` and `BOOK_FILE_BY_ID`.
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
            chapter_id = ""
            status = ""
            reason = ""
            for line in front.splitlines():
                line = line.strip()
                if line.startswith("chapter_id:"):
                    chapter_id = line.split(":", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("status:"):
                    status = line.split(":", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("status_reason:"):
                    reason = line.split(":", 1)[1].strip().strip('"').strip("'")
            if status.startswith("excluded_"):
                offenders.append({
                    "type": sub,
                    "id": chapter_id or path.stem,  # fall back to stem if front matter lacks chapter_id
                    "status": status,
                    "reason": reason,
                })
    return offenders


def write_needs_review(run_dir: Path | str, offenders: list[dict[str, str]]) -> None:
    """Emit 16_book/NEEDS_REVIEW.md listing quarantined chapters and citation issues."""
    out = Path(run_dir) / "16_book" / "NEEDS_REVIEW.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Needs Review", "",
             "These chapters or citations need review. Excluded chapters are NOT linked from SUMMARY.md.",
             "Excluded chapters remain on disk under `14_chapters/` and can be re-attempted with",
             "`phase=write fix_excluded=true`.",
             "Missing citation metadata is surfaced here while the book still renders.",
             "", "## Items", ""]
    if not offenders:
        lines.append("_(none — every chapter and citation passed)_")
    for o in offenders:
        lines.append(f"- **{o['type']}/{o['id']}** — `{o['status']}` ({o['reason']})")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
```

- [ ] **Step 4: Update `_build_summary`, `_build_sidebar`, `_build_method_taxonomy` to skip excluded methods/families**

Modify each builder's signature to accept an optional `excluded: set[str]` parameter and skip any family/method whose id is in that set:

```python
def _build_summary(outline: dict[str, Any], excluded: set[str] | None = None,
                    excluded_book_ids: set[str] | None = None) -> str:
    excluded = excluded or set()
    excluded_book_ids = excluded_book_ids or set()
    methods = _method_by_id(outline)
    family_by_id = {f["id"]: f for f in outline.get("families", [])}
    lines = ["# Summary", "", "## Book", ""]
    for section in outline.get("book_sections", []):
        section_id = section["id"]
        if section_id in excluded_book_ids:
            continue
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
            family = family_by_id.get(fid)
            if not family:
                continue
            family_excluded = fid in excluded
            passed_methods = [
                mid for mid in (family.get("method_ids") or []) if mid not in excluded
            ]
            if family.get("is_group") or family_excluded:
                # No family wrapper rendered. Methods listed flat under the part.
                for mid in passed_methods:
                    method = methods.get(mid)
                    if method:
                        lines.append(f"- [{method['title']}](../14_chapters/methods/{mid}.md)")
            else:
                if not passed_methods:
                    # Family passed but every method was excluded; render the family link only.
                    lines.append(f"- [{family['title']}](../14_chapters/families/{fid}.md)")
                else:
                    lines.append(f"- [{family['title']}](../14_chapters/families/{fid}.md)")
                    for mid in passed_methods:
                        method = methods.get(mid)
                        if method:
                            lines.append(f"  - [{method['title']}](../14_chapters/methods/{mid}.md)")
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
    excluded_family_method_ids = {o["id"] for o in offenders if o["type"] in ("families", "methods")}
    excluded_book_ids = {o["id"] for o in offenders if o["type"] == "book"}

    taxonomy_path = run_path / "14_chapters" / "book" / BOOK_FILE_BY_ID["method_taxonomy"]
    _write_markdown_preserving_front_matter(
        taxonomy_path, _build_method_taxonomy(outline, excluded_family_method_ids)
    )
    citation_issues = _build_appendices_dir(run_path, outline)
    all_needs_review = offenders + citation_issues
    write_needs_review(run_path, all_needs_review)

    (run_path / "16_book").mkdir(parents=True, exist_ok=True)
    (run_path / "16_book" / "SUMMARY.md").write_text(
        _build_summary(outline, excluded_family_method_ids, excluded_book_ids) + "\n",
        encoding="utf-8",
    )
    _write_json(run_path / "16_book" / "sidebar.json",
                _build_sidebar(outline, excluded_family_method_ids, excluded_book_ids))
    return {
        "families": len(outline.get("families", [])),
        "methods": len(outline.get("methods", [])),
        "quarantined": len(offenders),
        "needs_review": len(all_needs_review),
    }
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_research_book_verification_quarantine.py -v`
Expected: PASS (8 tests).

- [ ] **Step 7: Sanity-sweep stale references**

Run `grep -rn "verification_gate\|VerificationGateError" tests/`. Expected: zero hits — the quarantine model removed both names. Delete any survivors.

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
At stage 18, `generate_book_artifacts` ALWAYS produces `SUMMARY.md`, `sidebar.json`, `04_method_taxonomy.md`, and `appendices/` (assuming Stage 12.5 normalized the outline). Chapters whose front-matter `status` starts with `excluded_` are **quarantined** — they remain on disk under `14_chapters/` but are NOT linked from main navigation. Missing citation metadata is written as a `citation/<arxiv_id>` item while `references.md` keeps an unresolved marker. The list of quarantined chapters and citation issues is written to `16_book/NEEDS_REVIEW.md`, which always exists (even if empty).
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

Expected: surfaces `missing_parts`, `wrong_chapter_headings` (multiple), and the existing run's status flags. If the audited run still contains raw singleton families, `generate_book_artifacts` should raise via `assert_no_singletons`; `validate_research_book_run` itself does not emit a `singleton_family` issue. (We are NOT migrating the existing run.)

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
- Quarantine model verified end-to-end in Task 5.1 (excluded chapter remains on disk; SUMMARY does not link to it; NEEDS_REVIEW.md lists excluded chapters and missing citation metadata)
