"""Deterministic templates for the generated Starlight handbook."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ASTRO_VERSION = "5.4.0"
STARLIGHT_VERSION = "0.30.5"
MDX_VERSION = "4.0.6"
REMARK_MATH_VERSION = "6.0.0"
REHYPE_KATEX_VERSION = "7.0.1"
KATEX_VERSION = "0.16.11"


def package_json(run_id: str) -> dict[str, Any]:
    return {
        "name": f"handbook-{run_id}",
        "type": "module",
        "version": "0.0.1",
        "scripts": {
            "dev": "astro dev",
            "build": "astro build",
            "preview": "astro preview",
        },
        "dependencies": {
            "astro": ASTRO_VERSION,
            "@astrojs/starlight": STARLIGHT_VERSION,
            "@astrojs/mdx": MDX_VERSION,
            "remark-math": REMARK_MATH_VERSION,
            "rehype-katex": REHYPE_KATEX_VERSION,
            "katex": KATEX_VERSION,
        },
    }


def astro_config(
    *,
    title: str,
    sidebar_items: list[dict[str, Any]],
    site_url: str = "",
    base_path: str = "",
) -> str:
    sidebar = json.dumps(sidebar_items, indent=8)
    deploy_lines = ""
    if site_url:
        deploy_lines += f"  site: {json.dumps(site_url)},\n"
    if base_path:
        deploy_lines += f"  base: {json.dumps(base_path)},\n"
    return f"""import {{ defineConfig }} from 'astro/config';
import starlight from '@astrojs/starlight';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';

export default defineConfig({{
{deploy_lines}  trailingSlash: 'always',
  output: 'static',
  markdown: {{
    remarkPlugins: [remarkMath],
    rehypePlugins: [rehypeKatex],
  }},
  integrations: [
    starlight({{
      head: [],
      title: {json.dumps(title)},
      description: 'Research handbook generated from the completed chapter set for this run.',
      defaultLocale: 'en',
      expressiveCode: {{}},
      customCss: ['./src/styles/custom.css'],
      sidebar: {sidebar},
    }}),
  ],
}});
"""


def custom_css() -> str:
    return """@import 'katex/dist/katex.min.css';

:root {
  --sl-color-accent-low: #d8e7ff;
  --sl-color-accent: #2f6fbd;
  --sl-color-accent-high: #183b73;
  --sl-color-white: #ffffff;
  --sl-color-gray-1: #172033;
  --sl-color-gray-2: #354156;
  --sl-color-gray-3: #617089;
  --sl-color-gray-4: #94a0b3;
  --sl-color-gray-5: #ccd3df;
  --sl-color-gray-6: #edf1f7;
  --sl-color-black: #f8fafc;
  --sl-color-bg: #f8fafc;
  --sl-color-bg-nav: #ffffff;
  --sl-color-bg-sidebar: #f3f6fb;
  --sl-color-bg-inline-code: #e9eef7;
  --sl-content-width: min(72rem, calc(100vw - 24rem));
  --sl-font-system: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --sl-font-system-mono: 'IBM Plex Mono', 'SFMono-Regular', Consolas, monospace;
}

:root[data-theme='dark'] {
  --sl-color-accent-low: #12213d;
  --sl-color-accent: #8ab4ff;
  --sl-color-accent-high: #d6e5ff;
  --sl-color-white: #f6f8fb;
  --sl-color-gray-1: #e6ebf2;
  --sl-color-gray-2: #c4cedb;
  --sl-color-gray-3: #96a4b8;
  --sl-color-gray-4: #66758b;
  --sl-color-gray-5: #334054;
  --sl-color-gray-6: #1d2736;
  --sl-color-black: #101722;
  --sl-color-bg: #101722;
  --sl-color-bg-nav: #121a26;
  --sl-color-bg-sidebar: #0f1722;
  --sl-color-bg-inline-code: #1c2737;
}

body {
  background: var(--sl-color-bg);
}

.site-title {
  letter-spacing: 0;
}

.sl-markdown-content {
  line-height: 1.68;
}

.sl-markdown-content table {
  display: block;
  max-width: 100%;
  overflow-x: auto;
  white-space: normal;
  table-layout: auto;
}

.sl-markdown-content th,
.sl-markdown-content td {
  min-width: 14rem;
  max-width: 32rem;
  overflow-wrap: normal;
  word-break: normal;
  vertical-align: top;
}

.method-grid,
.family-grid,
.quick-links {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
  gap: 0.75rem;
  margin: 1rem 0 1.5rem;
}

.method-card,
.family-card,
.metric-card {
  border: 1px solid var(--sl-color-gray-5);
  border-radius: 8px;
  background: var(--sl-color-bg-nav);
  padding: 0.85rem 1rem;
}

.method-card strong,
.family-card strong {
  display: block;
  margin-bottom: 0.35rem;
}

.method-card a,
.family-card a,
.quick-link {
  font-weight: 650;
  text-decoration-thickness: 1px;
  text-underline-offset: 0.2em;
}

.method-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin: 0.75rem 0 1.25rem;
}

.method-meta span {
  border: 1px solid var(--sl-color-gray-5);
  border-radius: 999px;
  padding: 0.15rem 0.55rem;
  color: var(--sl-color-gray-2);
  font-size: 0.82rem;
}

.katex-display {
  overflow-x: auto;
  overflow-y: hidden;
  padding: 0.35rem 0;
}
"""


def home_page(
    *,
    title: str,
    run_id: str,
    book_count: int,
    family_count: int,
    method_count: int,
    base_path: str = "",
) -> str:
    from handbook_builder.deploy import href

    return f"""---
title: {json.dumps(title)}
description: Research handbook generated from run `{run_id}`.
head: []
---

# {title}

This handbook is a dense reference for the completed research run. Use the method and family indexes for navigation; use the book chapters for the synthesized narrative.

<div class=\"quick-links\">
  <a class=\"metric-card quick-link\" href=\"{href('/methods/', base_path=base_path)}\">All Methods<br/><span>{method_count} method pages</span></a>
  <a class=\"metric-card quick-link\" href=\"{href('/families/', base_path=base_path)}\">Families<br/><span>{family_count} research families</span></a>
  <a class=\"metric-card quick-link\" href=\"{href('/book/04_method_taxonomy/', base_path=base_path)}\">Method Taxonomy<br/><span>Start with the map</span></a>
  <a class=\"metric-card quick-link\" href=\"{href('/book/98_evaluation_outlook/', base_path=base_path)}\">Evaluation<br/><span>Compare evidence and limits</span></a>
</div>

## Start Reading

- [Browse every method]({href('/methods/', base_path=base_path)}) if you want direct access to individual papers and systems.
- [Browse families]({href('/families/', base_path=base_path)}) if you want the conceptual organization first.
- [Read the book preface]({href('/book/00_preface/', base_path=base_path)}) if you want the synthesized narrative from the beginning.

## Coverage

- {book_count} book chapters
- {family_count} family chapters
- {method_count} method chapters
"""


def slug_from_path(path: str) -> str:
    path_obj = Path(path)
    if path_obj.suffix in {".md", ".mdx"}:
        path_obj = path_obj.with_suffix("")
    parts = list(path_obj.parts)
    if parts and parts[0] == "14_chapters":
        parts = parts[1:]
    return "/".join(parts)
