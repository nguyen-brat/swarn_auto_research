---
name: web-tldr-writer
description: Per method page, produce a strict JSON payload with TLDR / key_idea / when_to_use / tags. Every claim must be grounded in the source markdown or the chapter pack.
---

# Web TLDR Writer

## Inputs (from payload)
- `run_id`
- `method_id` — id of the method chapter
- `chapter_path` — `14_chapters/methods/{method_id}.md`
- `pack_path` — `13_chapter_packs/methods/{method_id}.json`
- `tags_vocab_path` — `handbook_builder/tags_vocab.json`

## Output
Write `19_handbook/.augment/methods/{method_id}.json`:

```json
{
  "tldr": "<2–4 sentences, ≤ 280 chars>",
  "key_idea": "<1 sentence, ≤ 140 chars>",
  "when_to_use": ["<bullet>", "<bullet>", "<bullet>"],
  "tags": ["TTS", "Non-AR"]
}
```

## Hard Rules
- **Grounding.** Every claim in `tldr`, `key_idea`, `when_to_use` MUST be grounded — it MUST appear in the source markdown OR the chapter pack. No new method names. No new metrics. No fabricated comparisons.
- **Lengths.** `tldr` ≤ 280 chars. `key_idea` ≤ 140 chars. 2–3 bullets in `when_to_use`, each ≤ 120 chars.
- **Tags.** Drawn ONLY from `handbook_builder/tags_vocab.json`. 1–4 tags. Reject and emit `tags: []` if no tag from the vocab is supported by the source.
- **Pack-only naming.** No mention of methods/datasets/metrics not present in the pack.
- Return the standard short success string.
