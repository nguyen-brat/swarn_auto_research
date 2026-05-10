# Auto Research Shard 03: Appendices Directory and Reader Navigation

> **For agentic workers:** Implement this shard only. Do not load or execute the full reviewed source plan unless a referenced section is missing from this shard. Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` for execution.

**Source Material:** `docs/superpowers/plans/2026-05-10-codex-book-style-alignment.md` is the reviewed source plan. This shard copies the relevant task text and adds execution boundaries.

**Goal:** Switch appendices to a generated directory and make parts visible in SUMMARY, sidebar, and method taxonomy.

**Prerequisites:** Shards 00 through 02 completed and committed. Heading lint and standalone group behavior are available.

**Exit Criteria:** `pytest tests/test_research_book_appendices_dir.py -v`, `pytest tests/test_research_book_artifacts.py -v`, and then `pytest tests/ -v` pass for this shard boundary.

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
    outline = rb.merge_singletons(outline)  # Stage 12.5 precondition for Stage 18.
    op.write_text(json.dumps(outline))
    rb.generate_book_artifacts(voice_lm_minimal)
    assert (voice_lm_minimal / "14_chapters" / "book" / "appendices" / "glossary.md").exists()


def test_build_appendices_dir_records_missing_reference_issue(tmp_path):
    run = tmp_path / "run"
    for sub in ("12_taxonomy", "07_scoring", "14_chapters/book"):
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

    issues = _build_appendices_dir(run, outline)

    refs = (run / "14_chapters" / "book" / "appendices" / "references.md").read_text()
    assert "[arxiv:1.1] <citation metadata missing>" in refs
    assert issues == [{
        "type": "citation",
        "id": "1.1",
        "status": "missing_citation_metadata",
        "reason": "arxiv_id 1.1 not found in paper_pool / overviews / weak_evidence",
    }]


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

- [ ] **Step 5: Remove the old appendices `.md` reference validator**

Find the old block in `validate_research_book_run` that constructs `appendices_path`, calls `appendices_path.read_text(...)`, and emits `appendices_missing_promoted_reference`. Delete that whole block:

```python
    appendices_path = run_path / "14_chapters" / "book" / BOOK_FILE_BY_ID["appendices"]
    appendices_text = appendices_path.read_text(encoding="utf-8") if appendices_path.exists() else ""
    for entry in promoted:
        arxiv_id = entry["arxiv_id"]
        if f"[arxiv:{arxiv_id}]" not in appendices_text:
            issues.append(
                {
                    "severity": "error",
                    "code": "appendices_missing_promoted_reference",
                    "detail": f"{arxiv_id} is absent from 99_appendices.md",
                }
            )
```

`appendices` is now a directory. Keeping this block can make validation call `read_text()` on a directory. `references.md` generation is covered by `_build_appendices_dir`, and missing generated files are covered by the existence check above.

- [ ] **Step 6: Replace `_build_appendices` with `_build_appendices_dir`**

Remove the existing `_build_appendices` function (lines 562–594). Add:

```python
def _build_appendices_dir(run_dir: Path, outline: dict[str, Any]) -> list[dict[str, str]]:
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
    # Use _promoted_entries to handle every promoted_papers.json shape the repo supports.
    refs = ["# References", ""]
    citation_issues: list[dict[str, str]] = []
    for entry in sorted(_promoted_entries(run_dir), key=lambda e: e.get("arxiv_id", "")):
        aid = entry.get("arxiv_id", "")
        if not aid:
            continue
        try:
            cite = resolve_paper_citation(run_dir, aid)
            refs.append(f"- [arxiv:{cite['arxiv_id']}] {cite['title']} ({cite['year']})")
        except MissingCitationError as exc:
            refs.append(f"- [arxiv:{aid}] <citation metadata missing> (see NEEDS_REVIEW.md)")
            citation_issues.append({
                "type": "citation",
                "id": aid,
                "status": "missing_citation_metadata",
                "reason": str(exc),
            })
    (out_dir / "references.md").write_text("\n".join(refs) + "\n", encoding="utf-8")
    return citation_issues
```

- [ ] **Step 7: Update `generate_book_artifacts` to call the dir builder**

Find the existing call to `_build_appendices` in `generate_book_artifacts` (around line 645). Replace:
```python
    _write_markdown_preserving_front_matter(appendices_path, _build_appendices(run_path, outline))
```
with:
```python
    # Citation issues are returned here but not surfaced until Task 5.1 adds
    # write_needs_review(). This keeps Task 4.2 scoped to appendices generation.
    _citation_issues = _build_appendices_dir(run_path, outline)
```
Also remove the line that constructs `appendices_path` (it referenced `BOOK_FILE_BY_ID["appendices"]` as a file).

- [ ] **Step 8: Update `_build_summary` and `_build_sidebar` to link the directory index**

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

- [ ] **Step 9: Run tests**

Run: `pytest tests/test_research_book_appendices_dir.py -v`
Expected: PASS (6 tests).

Run: `pytest tests/test_research_book_artifacts.py -v`
Expected: existing tests still pass (any that asserted `appendices.md` should now be updated to assert the directory).

- [ ] **Step 10: Update existing artifact tests if they mention `appendices.md`**

Run: `grep -n "appendices.md" tests/`. For each hit, update to `appendices` (directory) or to a specific sub-file. If the assertion was on the file existing, change to `(... / "appendices" / "glossary.md").exists()`.

Run: `pytest tests/ -v`
Expected: PASS.

- [ ] **Step 11: Update `chapter-manifest` SKILL — exclude `book:appendices`**

In `.agents/skills/chapter-manifest/SKILL.md`, find the section that enumerates `chapter_targets` (`book:{id}` / `family:{id}` / `method:{id}`). Add a hard rule:

```markdown
## Hard rules
- `book:appendices` is NOT a manifest target. The appendices directory is generated deterministically (`appendices/`) and contains reference files without chapter front matter or verification status. Skip any `book:appendices` target passed to this stage and log `skipped: appendices is directory`.
```

- [ ] **Step 12: Update orchestrator SKILL — Stage 16 target list**

In `.agents/skills/auto-research-orchestrator/SKILL.md`, find Stage 16 description. Add:

```markdown
Stage 16 chapter_targets EXCLUDE `book:appendices` — the appendices directory is generated by `_build_appendices_dir` (Stage 18) and has no per-file front matter. Do not dispatch `chapter_manifest_builder` for `book:appendices`.
```

- [ ] **Step 13: Commit**

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
def _build_sidebar(outline: dict[str, Any], excluded: set[str] | None = None,
                   excluded_book_ids: set[str] | None = None) -> dict[str, Any]:
    excluded = excluded or set()
    excluded_book_ids = excluded_book_ids or set()
    methods = _method_by_id(outline)
    family_by_id = {f["id"]: f for f in outline.get("families", [])}
    book_items = []
    for section in outline.get("book_sections", []):
        if section["id"] in excluded_book_ids:
            continue
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
            family_excluded = fid in excluded
            passed_methods = [mid for mid in (family.get("method_ids") or []) if mid not in excluded]
            if family.get("is_group") or family_excluded:
                # No family wrapper. Methods rendered flat under the part.
                for mid in passed_methods:
                    m = methods.get(mid)
                    if m:
                        children.append({"title": m["title"], "path": f"14_chapters/methods/{mid}.md"})
            else:
                method_kids = []
                for mid in passed_methods:
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
def _build_method_taxonomy(outline: dict[str, Any], excluded: set[str] | None = None) -> str:
    excluded = excluded or set()
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
            family_excluded = fid in excluded
            passed_methods = [mid for mid in (family.get("method_ids") or []) if mid not in excluded]
            if family.get("is_group") or family_excluded:
                for mid in passed_methods:
                    m = methods.get(mid)
                    if m:
                        lines.append(f"- [{m['title']}](../methods/{mid}.md) [arxiv:{m.get('arxiv_id', '')}]")
            else:
                lines.append(f"- [{family['title']}](../families/{fid}.md)")
                for mid in passed_methods:
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
