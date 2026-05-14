---
name: verified-graph-extraction
description: Promote graph edges to verified using source-grounded claims; drop unsupported weak edges.
---

# Verified Graph Extraction

## Inputs
- `arxiv_ids` (sharded slice of promoted papers)
- `10_verified_evidence/{arxiv_id}.json`
- `05_weak_graph/fragments/{arxiv_id}.json` (node-id namespace only — weak edges are NOT auto-promoted)

## Outputs
- Per shard: `11_verified_graph/fragments/{arxiv_id}.json`
- Orchestrator merge: `11_verified_graph/global_graph.json` + `graph_report.md` (counts + dropped weak edges)

## Node + edge types
Same sets as weak graph (Paper, Concept, Method, ...; INTRODUCES, USES, ...).

## Rules
- Node ID: normalized name (lowercase, no punctuation). Papers use arXiv ID. Reuse weak-graph IDs when matching.
- An edge enters the verified graph ONLY if tied to a claim in `verified_evidence`. Attach `source_node_id` + `source_lines`.
- Every verified edge: `confidence: "verified"`.
- Weak edges with no verified support are NOT added. Orchestrator logs drops in `graph_report.md`.
- Contradictions: keep both — verifier resolves later.

## Fragment schema
```json
{
  "arxiv_id": "2304.08485",
  "nodes": [{"id": "clip-vision-encoder", "type": "Method", "display": "CLIP vision encoder"}],
  "edges": [{"src": "2304.08485", "dst": "clip-vision-encoder", "type": "USES",
             "confidence": "verified", "source_node_id": "s.03.01", "source_lines": [120, 138]}]
}
```

## Success
- Every edge: `confidence='verified'` + non-empty `source_node_id`.
- Every edge endpoint exists in the fragment's node set.
