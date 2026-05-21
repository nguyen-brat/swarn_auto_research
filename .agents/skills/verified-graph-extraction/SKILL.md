---
name: verified-graph-extraction
description: Promote graph edges to verified using source-grounded claims; drop unsupported weak edges.
---

# Verified Graph Extraction

## Inputs
- `arxiv_ids` (sharded slice of promoted papers with non-quarantined verified evidence claims)
- `11_verified_graph/frames/{arxiv_id}.json`
  - `claims`: Stage 10 verified claims with stable `claim_id`, exact `source_node_id`, and exact `source_lines`
  - `allowed_nodes`: node ids you may use
  - `allowed_edge_types`: edge labels you may use
- `05_weak_graph/fragments/{arxiv_id}.json` is only background context; weak edges are NOT auto-promoted.

## Outputs
- Per shard: `11_verified_graph/fragments/{arxiv_id}.json`
- Orchestrator merge: `11_verified_graph/global_graph.json` + `graph_report.md` (counts + dropped weak edges)

## Node + edge types
Same sets as weak graph (Paper, Concept, Method, ...; INTRODUCES, USES, ...).

## Rules
- Node ID: normalized name (lowercase, no punctuation). Papers use arXiv ID. Reuse weak-graph IDs when matching.
- An edge enters the verified graph ONLY if tied to a `claim_id` from the Stage 11 frame.
- In your edge output, include `claim_id`; do not invent or edit `source_node_id` / `source_lines`. The runner copies exact grounding from the selected `claim_id`.
- Every verified edge: `confidence: "verified"`.
- Weak edges with no verified support are NOT added. Orchestrator logs drops in `graph_report.md`.
- Contradictions: keep both — verifier resolves later.

## Fragment schema
```json
{
  "arxiv_id": "2304.08485",
  "nodes": [{"id": "clip-vision-encoder", "type": "Method", "display": "CLIP vision encoder"}],
  "edges": [{"src": "2304.08485", "dst": "clip-vision-encoder", "type": "USES",
             "confidence": "verified", "claim_id": "c004"}]
}
```

## Success
- Every edge you write: `confidence='verified'` + valid `claim_id`.
- Every edge endpoint exists in the fragment's node set.
- Every edge has a valid `claim_id` from the frame. The runner compiles that into exact `source_node_id` + `source_lines`.
- Do not write fragments for papers that remain quarantined after the runner clears stale rows for valid evidence.
