---
name: pageindex-building
description: Build a section tree and node map from a full paper Markdown.
---

# PageIndex Building

## Goal
Let downstream agents find sections by ID without scanning the whole paper.

## Inputs
- `08_full_markdown/{arxiv_id}.md`

## Outputs
- `09_pageindex/trees/{arxiv_id}.tree.json` — nested section tree
- `09_pageindex/nodes/{arxiv_id}.nodes.json` — flat node map keyed by stable ID

## Rules
- Parse Markdown headings (`#`, `##`, `###`, ...).
- Stable node ID format: `s` + zero-padded path indices (e.g. `s.01.03.02`).
- Each node records: `id`, `title`, `level`, `start_line`, `end_line`, `parent_id`, `summary` (≤ 240 chars).
- `start_line` / `end_line` are 1-based line numbers in the source Markdown.
- The tree is the root container with a `children` array; leaves have `children: []`.
- Summaries are mechanical: use the first non-heading sentence under that section. Do not interpret beyond that.

## Output schema (tree.json)
```json
{
  "arxiv_id": "2304.08485",
  "root": {
    "id": "s.00",
    "title": "(root)",
    "children": [
      {
        "id": "s.01",
        "title": "Introduction",
        "level": 1,
        "start_line": 5,
        "end_line": 84,
        "summary": "We introduce LLaVA...",
        "children": []
      }
    ]
  }
}
```

## Success check
- Both files exist for every promoted paper.
- Tree node IDs are unique.
- Every leaf has `start_line <= end_line`.
