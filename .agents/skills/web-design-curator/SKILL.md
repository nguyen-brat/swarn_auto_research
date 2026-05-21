---
name: web-design-curator
description: Generate structure hints for a research handbook scaffold. Final Astro config, package metadata, CSS, and render-safety details are deterministic Python templates.
---

# Web Design Curator

## Inputs (from payload)
- `run_id`
- `topic` — research topic string
- `chapter_manifest` — list of `{type, id, title, path}` covering every chapter file under `14_chapters/`
- `parts` — list of `{title, methods: [id...]}` (parts derived from `16_book/sidebar.json`)

## Outputs (strict JSON to stdout in a fenced ```json block)

```json
{
  "astro_config": "<legacy compatibility string; deterministic Python templates write final config>",
  "theme_css": "<legacy compatibility string; deterministic Python templates write final CSS>",
  "package_json": {
    "name": "handbook-<run_id>",
    "type": "module",
    "version": "0.0.1",
    "scripts": {"dev": "astro dev", "build": "astro build", "preview": "astro preview"},
    "dependencies": {
      "astro": "5.4.0",
      "@astrojs/starlight": "0.30.5",
      "@astrojs/mdx": "4.0.6"
    }
  },
  "sidebar_items": [
    {"label": "Book", "items": [{"label": "Preface", "slug": "book/00-preface"}, ...]},
    {"label": "Part 1: Generation", "items": [{"label": "MaskGCT (vq-vae-...)", "slug": "methods/maskgct"}, ...]}
  ],
  "home_page_mdx": "<legacy compatibility string; deterministic Python templates write final home page>"
}
```

## Hard Rules
- Treat the output as structure hints for a dense research handbook, not as final UI code.
- `astro_config` MUST include `starlight({...})` and mention `expressiveCode` for compatibility, but Python templates write the final renderable config.
- `sidebar_items` MUST cover every entry in `chapter_manifest` exactly once.
- Prefer compact navigation: Book, Methods, Families, family pages, and appendices. Do not make a 150-method sidebar tree the primary navigation surface.
- The final site must feel like a research reference: compact, table-forward, readable, and free of decorative hero/gradient/orb styling.
- Treat render safety as part of the design: math must be KaTeX-renderable, page titles must not be duplicated as body H1s, and wide tables must remain readable through horizontal scrolling.
- Pin exact versions in `package_json`; never use `^` or `~`.
- Return JSON only, inside a single fenced ```json block. No prose before or after.
