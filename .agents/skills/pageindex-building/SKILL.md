---
name: pageindex-building
description: Section tree + node map from full paper Markdown so downstream agents find sections by stable ID.
---

# PageIndex Building

## Inputs
- `arxiv_ids` (sharded slice of promoted papers)
- `08_full_markdown/{arxiv_id}.md`

## Outputs
- `09_pageindex/trees/{arxiv_id}.tree.json` (nested)
- `09_pageindex/nodes/{arxiv_id}.nodes.json` (flat, keyed by ID)

## Rules
- Parse `#` … headings.
- Stable ID: `s` + zero-padded path indices (`s.01.03.02`).
- Each node: `id`, `title`, `level`, `start_line`, `end_line` (1-based), `parent_id`, `summary` (≤240 chars; mechanical first non-heading sentence — do not interpret).
- Tree root's `children` array contains top-level sections; leaves have `children: []`.

## tree.json schema
```json
{
  "arxiv_id": "2304.08485",
  "root": {"id": "s.00", "title": "(root)", "children": [
    {"id": "s.01", "title": "Introduction", "level": 1,
     "start_line": 5, "end_line": 84,
     "summary": "We introduce LLaVA...", "children": []}
  ]}
}
```

## Success
- Both files exist per paper. IDs unique. Every leaf has `start_line ≤ end_line`.
