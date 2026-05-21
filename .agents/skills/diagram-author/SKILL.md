---
name: diagram-author
description: Generate one Mermaid (.mmd) diagram per family chapter and per method chapter-pack. Family diagrams are member trees; method diagrams are architecture sketches.
---

# Diagram Author

## Inputs (from payload)
- `run_id`
- `target_type` — one of `family`, `method`
- `target_id` — id of the family or method
- `source_path` — relative path to the source JSON (taxonomy for family, chapter_pack for method)

## Output
Write a single Mermaid source file:
- family → `19_handbook/src/assets/diagrams/families/<target_id>.mmd`
- method → `19_handbook/src/assets/diagrams/methods/<target_id>.mmd`

## Diagram Conventions
- Family diagram: `graph TD;` with one node per member method. Edges connect to a root `family[<family_title>]` node. Optionally cluster shared mechanisms.
- Method diagram: `graph LR;` block diagram of the architecture: input → tokenizer/encoder → core model → decoder → output. Use components named in the pack only.

## Hard Rules
- Every node label must appear as a name/title in the input JSON. Never invent component names.
- File must parse as valid Mermaid (test with `mmdc --dry-run`).
- Keep the diagram under 25 nodes — collapse repeated structures.
- Return the standard short success string.
