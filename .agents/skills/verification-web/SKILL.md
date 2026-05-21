---
name: verification-web
description: Gate web augmentations (TLDR/callouts/book-rewrites) against the original chapter. Reject any new claim, name, or metric not present in the original.
---

# Verification (Web)

## Inputs (from payload)
- `run_id`
- `original_path` — relative path to the source markdown chapter
- `candidate_path` — relative path to the candidate JSON (TLDR) or MDX (book rewrite)
- `kind` — `tldr` or `book_rewrite`

## Output
Write `19_handbook/.augment/<kind>/<id>.verification.json`:

```json
{
  "passed": true,
  "claims": [
    {"text": "...", "status": "supported"},
    {"text": "...", "status": "partially_supported"}
  ],
  "rejection_reason": null
}
```

Or on failure:

```json
{"passed": false, "claims": [...], "rejection_reason": "Introduces method 'NaturalSpeech 2' absent from source."}
```

## Rules
- Extract every factual claim from the candidate (method names, metrics, architectural choices, comparisons).
- For each claim: status is `supported` (verbatim or paraphrase in original or pack), `partially_supported` (close paraphrase), `unsupported` (not in source), or `overstated` (stronger than source).
- `passed: true` ONLY if every claim is `supported`. `partially_supported`, `unsupported`, `overstated` → `passed: false`.
- For `kind=tldr`, also enforce: every method/dataset/metric name MUST appear in the source markdown OR the chapter pack.
- `rejection_reason` MUST cite the first offending claim's text.
- Return only the standard short success string.
