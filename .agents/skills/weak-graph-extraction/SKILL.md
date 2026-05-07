---
name: weak-graph-extraction
description: Build weak knowledge-graph fragments from weak evidence cards.
---

# Weak Graph Extraction

## Goal
Turn weak-evidence cards into a graph fragment per paper plus a merged global graph.

## Inputs
- `04_weak_evidence/*.json`

## Outputs
- `05_weak_graph/fragments/{arxiv_id}.json`
- `05_weak_graph/weak_global_graph.json`

## Node types
Paper, Problem, Concept, Method, MethodFamily, Dataset, Benchmark, Metric, Claim, Result, Limitation, Application, OpenProblem, Codebase.

## Edge types
INTRODUCES, USES, USES_DATASET, EVALUATES_ON, MEASURES_WITH, COMPARES_TO, IMPROVES_OVER, HAS_RESULT, HAS_LIMITATION, SOLVES, EXTENDS, MENTIONS, RELATED_TO, BELONGS_TO, CITES, CONTRADICTS.

## Rules
- Use weak evidence only. Mark every edge with `confidence: "weak"`.
- A node ID is the normalized concept name (lowercase, no punctuation). Paper nodes use the arXiv ID.
- Merge fragments into the global graph by deduping nodes via normalized ID and unioning edges.
- When two fragments contradict, keep both edges (the verifier handles conflicts later).
- Do not invent edges that are not directly stated in the evidence card.

## Output schema
```json
{
  "nodes": [
    {"id": "clip-vision-encoder", "type": "Method", "display": "CLIP vision encoder"}
  ],
  "edges": [
    {"src": "2304.08485", "dst": "clip-vision-encoder", "type": "USES", "confidence": "weak"}
  ]
}
```

## Success check
- Every edge endpoint exists in the node set.
- `weak_global_graph.json` is valid JSON.
- No edge has `confidence` other than `weak` or `inferred`.
