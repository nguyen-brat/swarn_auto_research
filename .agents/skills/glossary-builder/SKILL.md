---
name: glossary-builder
description: Build the handbook's glossary.json from method packs and knowledge_base.md. Terms known to the reader are flagged kb_known=true and skipped at tooltip render time.
---

# Glossary Builder

## Inputs (from payload)
- `run_id`
- `pack_dir` — relative path `13_chapter_packs/methods/`
- `kb_path` — relative path `.agents/knowledge_base.md`

## Process
1. Read every `13_chapter_packs/methods/*.json` and extract technical terms from the pack `definitions`, `key_terms`, and section captions.
2. Read `.agents/knowledge_base.md`. Any term whose surface form (case-insensitive) appears in `knowledge_base.md` → `kb_known: true`.
3. For each term, produce a definition no longer than 280 chars, drawn ONLY from the pack. Never invent definitions.
4. Aggregate `appears_in` from every pack the term shows up in.

## Output
Write `19_handbook/public/glossary.json`:

```json
[
  {"term": "RVQ", "definition": "Residual Vector Quantization...", "appears_in": ["maskgct", "vall-e-2"], "kb_known": false},
  {"term": "Transformer", "definition": "...", "appears_in": [...], "kb_known": true}
]
```

## Hard Rules
- Every term and definition MUST be traceable to a pack. No invention.
- `kb_known: true` entries MUST still be emitted (downstream uses them for diagnostics).
- Sort entries alphabetically by `term`.
- Return only the standard short success string.
