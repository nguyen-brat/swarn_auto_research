---
name: chapter-manifest
description: Inject front matter + References block into each chapter file. Emit a manifest listing all three tiers. No merged handbook.
---

# Chapter Manifest

## Inputs
- `chapter_targets` — typed IDs (`book:{id}` / `family:{id}` / `method:{id}`)
- `12_taxonomy/outline.json`
- `14_chapters/{book|families|methods}/...` (edited in place)
- `15_verification/{book|families|methods}/{id}_verification.json`
- `02_paper_pool/paper_pool.json` (title + year resolution)
- `13_chapter_packs/...` (pack metadata)
- `00_input/topic.md`

## Outputs
- `14_chapters/.../{file}.md` — edited in place: front matter + References.
- `16_book/chapters_manifest_shard_{shard_id}.json` — shard-local list.
- `16_book/chapters_manifest.json` — orchestrator merge.

## Front matter (prepend if absent, replace if present)
Common fields:
```yaml
---
chapter_id: nsa
chapter_type: method   # or 'family' or 'book'
title: ""
slug: ""
topic: ""              # from 00_input/topic.md
status: passed         # passed | excluded_unsupported_claims | excluded_gaps_missing | excluded_form_issues
status_reason: ""
word_count: 0
verified_claims: 0
form_issues: []
---
```

Type-specific extras:
- **method**: `arxiv_id`, `family_id`, `family_title`, `knowledge_gaps_covered`, `known_concepts_assumed`, `neighbor_method_ids`, `equations_rendered`, `pseudocode_blocks`.
- **family**: `family_id`, `method_ids`, `neighbor_family_ids`, `knowledge_gaps_to_explain`.
- **book**: `section_id`.

`status` rule: `passed` only if `claims_unsupported == 0 AND gaps_missing == 0 AND form_issue_count == 0`, the verifier JSON is present, and the verifier summary contains an actual word count from the chapter file. If multiple failure reasons apply, pick first true in this order: unsupported_claims, gaps_missing, form_issues. Missing or unreadable verification is `excluded_form_issues` with `status_reason: verification_missing`.

Do not override verifier failures or synthesize a pass from manifest metadata. For method chapters, below 1500 words is `excluded_form_issues`; for family chapters, below 1000 words is `excluded_form_issues`.

`slug` = title lowercased, non-alphanumeric → `-`, collapse repeats, strip ends.

## References block (append if absent, replace if present)
Last `##` section. Build by scanning chapter body for `[arxiv:ID, ...]`, dedupe by ID, resolve title+year from `paper_pool.json`. Sort by first-citation order. Format:
```markdown
## References

- [arxiv:2502.11089] Native Sparse Attention (2025)
```
Missing title/year → `<title unknown>` / `<year unknown>` — never invent.

## Hard rules
- `book:appendices` is NOT a manifest target. The appendices directory is generated deterministically (`appendices/`) and contains reference files without chapter front matter or verification status. Skip any `book:appendices` target passed to this stage and log `skipped: appendices is directory`.

## Mechanical-edit rule
ONLY the front-matter block at the top and References block at the bottom may change. Body content (paragraphs, tables, equations, pseudocode) stays byte-for-byte.

## Manifest schema
```json
{
  "run_id": "", "topic": "", "generated_at": "",
  "chapters": [
    {"chapter_id": "preface", "chapter_type": "book",
     "section_id": "preface", "file": "14_chapters/book/00_preface.md",
     "status": "passed", "status_reason": "", "word_count": 600},
    {"chapter_id": "sliding_window_attention", "chapter_type": "family",
     "title": "", "file": "14_chapters/families/.../md",
     "method_ids": [], "status": "", "word_count": 0},
    {"chapter_id": "nsa", "chapter_type": "method",
     "title": "", "arxiv_id": "", "family_id": "",
     "file": "14_chapters/methods/nsa.md",
     "status": "", "word_count": 0,
     "equations_rendered": 0, "pseudocode_blocks": 0}
  ]
}
```

Manifest order: book sections (canonical filename order) → families (outline order) → methods (grouped by family in outline order).

## Success
- Every chapter file starts with valid YAML front matter and ends with a `## References` block (may be empty).
- `chapter_type` matches directory.
- `chapters_manifest.json` lists every on-disk chapter in canonical order.
- No `handbook.md` / `index.md` / `references.md` produced.
