---
name: chapter-pack-building
description: Self-contained packs for the three chapter tiers. Method packs inline verbatim section text + structured fields so writers need no MCP fetches.
---

# Chapter Pack Building

## Inputs
- `pack_targets` — typed IDs (`book:{id}` / `family:{id}` / `method:{id}`)
- `12_taxonomy/outline.json`
- `11_verified_graph/global_graph.json`
- `10_verified_evidence/{arxiv_id}.json`
- `09_pageindex/trees/...` and `.nodes.json`
- `08_full_markdown/{arxiv_id}.md` (via `get_paper_section` for inlining)
- Cached figures under `13_chapter_packs/assets/paper_figures/` when safe images are selected
- `06_expansion/known_concepts_snapshot.json`, `knowledge_gap_report.json`
- `00_input/topic.md`

## Output paths
- Method:  `13_chapter_packs/methods/{method_id}_pack.json`
- Family:  `13_chapter_packs/families/{family_id}_pack.json`
- Book:    `13_chapter_packs/book/{section_id}_pack.json`

---

## Method pack (load-bearing)

Required Book_style sections in `section_plan` (11):
`summary, motivation, intuition, theory, algorithm, example, interpretation, strengths, limitations, software, related_methods`.

An empty or partial `section_plan` is a build failure. Never write a method pack with zero source nodes or with fewer than these 11 section entries.

Method packs must scope `knowledge_gaps_to_explain` to concepts actually touched by that method's evidence. Prefer `outline.methods[*].knowledge_gaps_to_explain` when present, otherwise intersect `knowledge_gap_report` concepts with the method's evidence claim and structured text. Cap method `knowledge_gaps_to_explain` at 3 concepts. Do not copy the global `knowledge_gap_report` into every method pack.

Per-section `source_node` shape:
```json
{"arxiv_id":"", "node_id":"", "lines":[0,0],
 "claim_type":"method|result|limitation|...",
 "section_title":"",
 "section_text":"<full verbatim markdown of the node>"}
```
**`section_text` is mandatory for theory / algorithm / example / limitations sources.** Empty = build error; retry the fetch then fail. Do not emit a pack that would force the method writer to guess from titles, abstracts, or citation placeholders.

### Method pack schema
```json
{
  "pack_type": "method",
  "method_id": "", "method_title": "", "arxiv_id": "",
  "family_id": "", "family_title": "",
  "known_concepts_assumed": [], "knowledge_gaps_to_explain": [],
  "structured": {
    "equations": [/* verbatim from verified_evidence */],
    "algorithms": [/* verbatim */],
    "hyperparameters": [],
    "complexity": []
  },
  "section_plan": [
    {"section_title": "Theory", "purpose": "",
     "source_nodes": [/* with section_text */],
     "structured_refs": ["equation:0", "equation:1"]}
  ],
  "neighbors": [
    {"method_id": "", "arxiv_id": "", "title": "", "family_id": "",
     "diff_summary": "", "source_node_id": ""}
  ],
  "visual_assets": [
    {"arxiv_id": "", "caption": "", "cache_path": "13_chapter_packs/assets/paper_figures/...",
     "public_path": "paper_figures/...", "markdown_image": "![caption](/paper_figures/...)",
     "score": 0, "evidence_refs": []}
  ]
}
```

---

## Family pack
- Title, `method_ids` (with title + arxiv_id each), `neighbor_family_ids` (with title).
- `comparison_rows`: one row per method with `mechanism`, `when_helps`, `when_hurts`, `arxiv_id`, `source_node_id` — values from each method's verified-evidence summary.
- Family-level `knowledge_gaps_to_explain`, `known_concepts_assumed`.
- Top-level `visual_assets`: either `[]` or one cached method/workflow/algorithm image selected from an in-scope method paper.
- No `section_text` inlining at this tier.

---

## Book-section pack

Per `section_id`:
- `preface` — topic, target audience, prerequisites (from known_concepts_snapshot), scope (from `00_input/topic.md`).
- `motivating_intro` — 1–2 real failure-mode anecdotes from any paper's intro/related-work, with citations.
- `core_concepts` — union of `knowledge_gaps_to_explain` + their definitions from verified-evidence claims; plus the `known_concepts_assumed` list (no re-explanation).
- `goals` — derived from topic + highest-priority gaps.
- `method_taxonomy` — full families×methods with cross-family neighbors.
- `shared_examples` — union of method packs' `example` sources, deduped.
- `evaluation_outlook` — every benchmark/metric/limitation from verified-evidence + open gaps from knowledge_gap_report.
- `appendices` — references list of every promoted paper (title, year, arxiv_id) + glossary stub.

Schema:
```json
{"pack_type": "book", "section_id": "preface", "section_title": "Preface",
 "topic": "...", "data": {/* section-specific */}}
```

---

## Hard rules
- Method packs MUST have non-empty `section_text` on theory/algorithm/example/limitations sources.
- Method pack sources only reference the method's own arxiv_id; family packs reference any of `method_ids`' arxiv_ids; book packs reference any promoted paper.
- Never invent neighbor relations (pull from verified_evidence + verified graph).
- `pack.structured` is a verbatim subset of `verified_evidence` — do not re-derive.
- `visual_assets` must be top-level for method and family packs. Use cached local paths only (`13_chapter_packs/assets/paper_figures/...` and `/paper_figures/...` in `markdown_image`); never use absolute filesystem paths. If no safe image is available, write `visual_assets: []`.

## Success
- One pack per ID, in the correct subdir.
- Method packs: every theory/algorithm/example/limitations source has `section_text`.
- Method packs: `family_id` resolves; family packs: `method_ids` resolve.
- Method and family packs have a top-level `visual_assets` list.
