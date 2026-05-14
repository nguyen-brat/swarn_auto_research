---
name: weak-graph-extraction
description: Per-paper graph fragments from weak evidence; orchestrator merges into the global graph.
---

# Weak Graph Extraction

## Inputs
- `arxiv_ids` (sharded slice; unsharded fallback: every `04_weak_evidence/*.json`)
- `04_weak_evidence/{arxiv_id}.json` per id

## Outputs
- `05_weak_graph/fragments/{arxiv_id}.json` (written by shards)
- `05_weak_graph/weak_global_graph.json` (orchestrator merge — shards never write it)

## Node types
Paper, Problem, Concept, Method, MethodFamily, Dataset, Benchmark, Metric, Claim, Result, Limitation, Application, OpenProblem, Codebase.

## Edge types
INTRODUCES, USES, USES_DATASET, EVALUATES_ON, MEASURES_WITH, COMPARES_TO, IMPROVES_OVER, HAS_RESULT, HAS_LIMITATION, SOLVES, EXTENDS, MENTIONS, RELATED_TO, BELONGS_TO, CITES, CONTRADICTS.

## Rules
- Every edge `confidence: "weak"`.
- Node ID = normalized name (lowercase, no punctuation). Paper nodes use arXiv ID.
- Never invent edges absent from the evidence card.
- Conflicts: keep both edges (verifier resolves later).

## Schema
```json
{
  "nodes": [{"id": "clip-vision-encoder", "type": "Method", "display": "CLIP vision encoder"}],
  "edges": [{"src": "2304.08485", "dst": "clip-vision-encoder", "type": "USES", "confidence": "weak"}]
}
```

## Success
- Every edge endpoint is in nodes. JSON valid. No confidence outside {weak, inferred}.
