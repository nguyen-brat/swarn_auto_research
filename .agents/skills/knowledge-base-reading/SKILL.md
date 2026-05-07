---
name: knowledge-base-reading
description: Parse the shared user knowledge base into a normalized JSON snapshot.
---

# Knowledge Base Reading

## Goal
Parse `.agents/knowledge_base.md` into `06_expansion/known_concepts_snapshot.json`.

## Inputs
- `.agents/knowledge_base.md`

## Outputs
- `research_runs/{run_id}/06_expansion/known_concepts_snapshot.json`

## Rules
- Treat each Markdown `##` heading as a category.
- Treat each bullet item under a category as one known concept.
- Normalize each concept: lowercase, strip punctuation, collapse whitespace.
- For each concept, also infer obvious aliases: common abbreviations (LLM ↔ Large Language Model), plural ↔ singular, dash variants. Do not invent non-obvious aliases.
- Preserve the original casing in a `display` field.
- Do not modify `.agents/knowledge_base.md`.

## Output schema
```json
{
  "source_path": ".agents/knowledge_base.md",
  "known_concepts": [
    {
      "display": "Large Language Model",
      "normalized": "large language model",
      "category": "Core LLM Concepts"
    }
  ],
  "aliases": {
    "large language model": ["llm", "large language models"]
  }
}
```

## Success check
- File exists at the expected path.
- `known_concepts` length > 0.
- Every concept has `display`, `normalized`, `category`.
