---
name: verified-evidence-extraction
description: Source-grounded artifacts (claims + verbatim equations + verbatim pseudocode + hyperparameters + complexity + neighbors) for promoted papers — the spine of every method chapter.
---

# Verified Evidence Extraction

## Inputs
- `arxiv_ids` (sharded slice of promoted papers)
- `09_pageindex/trees/{arxiv_id}.tree.json` and `.nodes.json`
- `08_full_markdown/{arxiv_id}.md` (fetched section-by-section via `get_paper_section`)
- `04_weak_evidence/{arxiv_id}.json` (reading roadmap only)

## Output
- `10_verified_evidence/{arxiv_id}.json`

## Section selection
- Always include every leaf node whose path matches:
  `method | algorithm | architecture | implementation | framework | kernel | design | formulation` (case-insensitive).
- Always include: abstract, introduction, experiments/evaluation/results, limitations (or discussion if it carries them), related work.
- Soft cap 20 sections. The always-include list overrides the cap.

## Per-section extraction
- **claims** — sentence-level facts. Each carries `source_node_id` + `source_lines`.
- **equations** — every numbered display equation. **VERBATIM LaTeX**. Each entry has `purpose` (1 phrase) and `symbols` (when stated nearby).
- **algorithms** — when section has a numbered procedure / pseudocode / "Algorithm 1", copy `pseudocode` verbatim. Else build numbered `steps`. Both grounded.
- **hyperparameters** — every named param with assigned value (block size, window, sparsity, lr, training tokens, head count, etc.).
- **complexity** — every big-O / FLOPs / memory statement, with `regime` ∈ {prefill, decoding, training}.
- **neighbors** — every prior method/system/paper compared against. `relation` ∈ {compared_to, predecessor, concurrent, builds_on}.

## Hard rules
- Equations and pseudocode are VERBATIM. No paraphrase. (The verifier accepts a chapter's math iff it appears as a substring of a cited node's text — paraphrasing breaks this.)
- Never invent node_ids, lines, values, equations, or arxiv IDs.
- Drop anything you can't ground in a fetched section. Empty arrays are fine.
- `trust_level` is always `PAPER_VERIFIED`.

## Schema
```json
{
  "arxiv_id": "", "trust_level": "PAPER_VERIFIED",
  "title": "", "year": 0, "abstract_summary": "",
  "claims": [{"text":"", "source_node_id":"", "source_lines":[0,0],
              "claim_type":"method|result|limitation|motivation",
              "confidence":"high|medium"}],
  "methods": [{"name":"", "source_node_id":""}],
  "equations": [{"latex":"", "purpose":"",
                 "symbols":[{"name":"", "meaning":""}],
                 "source_node_id":"", "source_lines":[0,0]}],
  "algorithms": [{"name":"", "pseudocode":"", "steps":[],
                  "source_node_id":"", "source_lines":[0,0]}],
  "hyperparameters": [{"name":"", "value":"", "purpose":"",
                       "source_node_id":""}],
  "complexity": [{"text":"", "regime":"prefill|decoding|training",
                  "source_node_id":""}],
  "neighbors": [{"name":"", "arxiv_id_if_known":"",
                 "relation":"compared_to|predecessor|concurrent|builds_on",
                 "source_node_id":""}],
  "datasets": [{"name":"", "source_node_id":""}],
  "benchmarks": [{"name":"", "source_node_id":""}],
  "metrics": [{"name":"", "source_node_id":""}],
  "baselines": [{"name":"", "source_node_id":""}],
  "results": [{"text":"", "source_node_id":"", "source_lines":[0,0]}],
  "limitations": [{"text":"", "source_node_id":"", "source_lines":[0,0]}]
}
```

## Success
- One file per id. Every artifact has `source_node_id` (+ `source_lines` where applicable).
- `equations` non-empty when method sections contain numbered display equations.
- `algorithms[].pseudocode` non-empty when an Algorithm/pseudocode block exists.
