# Auto-Research Web Handbook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Stage 19 to the auto-research pipeline that turns each run's markdown chapters into a deployable Astro Starlight web handbook with multi-agent TLDR/diagram/glossary augmentation and a book-chapter web rewrite.

**Architecture:** A new `handbook_builder/` Python module orchestrates six sub-stages (scaffold → glossary → diagrams → method augmentation → book rewrite → assemble+build). It runs as Stage 19 of `run_auto_research.py` and as a standalone `scripts/build_handbook.py`. Six new Codex agent skills supply web-writing/web-design capabilities; the existing sharded SDK dispatch infrastructure provides parallelism, retry, and verification.

**Tech Stack:** Python 3.12, Astro Starlight 0.x, Tokyo Night theme, Mermaid diagrams, pnpm, Codex app-server SDK (existing), pytest.

**Source spec:** `docs/superpowers/specs/2026-05-15-auto-research-web-handbook-design.md`

**Milestones (each independently shippable):**

- **M0** — Scaffold-only Starlight site that renders existing markdown unchanged.
- **M1** — Glossary + diagrams (tooltips and inline Mermaid).
- **M2** — Per-method TLDR/key-idea/when-to-use augmentation, gated by verifier-web.
- **M3** — Book-chapter web rewrite (7 chapters), gated by verifier-web.
- **M4** — Umbrella site + GitHub Pages deployment workflow.

---

## File Structure (all milestones)

**New module `handbook_builder/`:**

```
handbook_builder/
├── __init__.py
├── pipeline.py        # stage_19 entry: orchestrates sub-stages
├── dispatch.py        # thin adapter over scripts/run_auto_research.py:run_shards
├── scaffold.py        # invokes web-design-curator; writes astro.config.mjs, package.json, theme.css; copies static components
├── augment.py         # splices TLDR/KeyIdea/WhenToUse/Diagram MDX into method pages
├── linker.py          # rewrites sidebar.json into Starlight sidebar; rewrites internal markdown links
├── glossary.py        # invokes glossary-builder; emits public/glossary.json
├── diagrams.py        # invokes diagram-author per family/method; validates .mmd parse
├── book_rewrite.py    # invokes web-book-rewriter for the 7 book chapters
├── verify.py          # verifier-web adapter (top-level passed flag)
├── build.py           # runs `pnpm install && pnpm build` in 19_handbook/
├── cache.py           # source-hash idempotency manifest
└── templates/
    └── components/
        ├── Tldr.astro
        ├── KeyIdea.astro
        ├── Diagram.astro
        └── Term.astro
```

**New scripts:**
- `scripts/build_handbook.py` — standalone driver that calls `handbook_builder.pipeline.build()`.

**Modified files:**
- `scripts/run_auto_research.py` — register Stage 19 handler, add to PRIMARY_ARTIFACTS.

**New agent skills (each `.agents/skills/<name>/SKILL.md` + `.codex/agents/<name>.toml`):**
- `web-design-curator`
- `web-tldr-writer`
- `web-book-rewriter`
- `diagram-author`
- `glossary-builder`
- `verification-web`

**New tests:**
- `tests/test_handbook_scaffold.py`
- `tests/test_handbook_glossary.py`
- `tests/test_handbook_diagram.py`
- `tests/test_handbook_tldr.py`
- `tests/test_handbook_book_rewriter.py`
- `tests/test_handbook_verifier_web.py`
- `tests/test_handbook_augment.py`
- `tests/test_handbook_linker.py`
- `tests/test_handbook_cache.py`
- `tests/test_handbook_pipeline.py`
- `tests/test_handbook_umbrella.py`
- `tests/fixtures/handbook_mini_run/` (3 methods + 1 family + 1 book chapter)

**Repo-level additions:**
- `handbook/` — umbrella Starlight project (M4).
- `.github/workflows/deploy-handbook.yml` (M4).

---

# Milestone M0 — Scaffold-only Starlight Site

**Goal:** A deployable Starlight site at `research_runs/<run>/19_handbook/dist/` that renders every existing chapter unchanged, with working sidebar, search, dark Tokyo Night theme. No agent augmentation yet.

## Task M0.1: Add the `web-design-curator` SKILL and TOML

**Files:**
- Create: `.agents/skills/web-design-curator/SKILL.md`
- Create: `.codex/agents/web_design_curator.toml`

- [ ] **Step 1: Write the failing test**

Create `tests/test_handbook_scaffold.py`:

```python
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_web_design_curator_skill_exists():
    skill = REPO_ROOT / ".agents/skills/web-design-curator/SKILL.md"
    assert skill.exists(), "SKILL.md missing"
    text = skill.read_text()
    assert "Tokyo Night" in text
    assert "starlight(" in text
    assert "expressiveCode" in text
    assert "Return JSON" in text or "Return strict JSON" in text


def test_web_design_curator_toml_exists():
    toml = REPO_ROOT / ".codex/agents/web_design_curator.toml"
    assert toml.exists()
    text = toml.read_text()
    assert 'name = "web_design_curator"' in text
    assert "web-design-curator/SKILL.md" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_scaffold.py -v`
Expected: FAIL — both files missing.

- [ ] **Step 3: Write the SKILL.md**

Create `.agents/skills/web-design-curator/SKILL.md`:

```markdown
---
name: web-design-curator
description: Generate the one-time Astro Starlight scaffold for a research run's handbook (astro.config.mjs, theme CSS, package.json, sidebar, home MDX). Tokyo Night theme.
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
  "astro_config": "<full astro.config.mjs content as a string>",
  "theme_css": "<full custom.css content as a string>",
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
  "home_page_mdx": "<full content of src/content/docs/index.mdx>"
}
```

## Hard Rules
- `astro_config` MUST call `starlight({...})` with `expressiveCode` enabled.
- `astro_config` MUST set `customCss: ['./src/styles/custom.css']`.
- `astro_config` MUST set `defaultLocale: 'en'` and `output: 'static'`.
- `sidebar_items` MUST cover every entry in `chapter_manifest` exactly once.
- `theme_css` MUST override Starlight `--sl-color-*` variables for a Tokyo Night palette (dark bg `#1a1b26`, fg `#c0caf5`, accent `#7aa2f7`).
- Pin exact versions in `package_json`; never use `^` or `~`.
- Return JSON only, inside a single fenced ```json block. No prose before or after.
```

- [ ] **Step 4: Write the TOML**

Create `.codex/agents/web_design_curator.toml`:

```toml
name = "web_design_curator"
description = "Generate the one-time Astro Starlight scaffold for a research run's handbook."
model = "gpt-5.4"
model_reasoning_effort = "medium"

developer_instructions = """
Follow .agents/skills/web-design-curator/SKILL.md.

Inputs: run_id, topic, chapter_manifest, parts.

ALL FILE PATHS ARE RELATIVE TO research_runs/{run_id}/.

Write the scaffold JSON to research_runs/{run_id}/19_handbook/.scaffold/curator_output.json.

Return the standard short success string.
"""
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_scaffold.py -v`
Expected: PASS for both tests.

- [ ] **Step 6: Commit**

```bash
git add .agents/skills/web-design-curator .codex/agents/web_design_curator.toml tests/test_handbook_scaffold.py
git commit -m "feat: add web-design-curator skill and agent toml"
```

---

## Task M0.2: Static Astro components

**Files:**
- Create: `handbook_builder/templates/components/Tldr.astro`
- Create: `handbook_builder/templates/components/KeyIdea.astro`
- Create: `handbook_builder/templates/components/Diagram.astro`
- Create: `handbook_builder/templates/components/Term.astro`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_handbook_scaffold.py`:

```python
def test_static_components_exist():
    base = REPO_ROOT / "handbook_builder/templates/components"
    for name in ("Tldr.astro", "KeyIdea.astro", "Diagram.astro", "Term.astro"):
        path = base / name
        assert path.exists(), f"{name} missing"
        text = path.read_text()
        assert "<style>" in text or "scoped" in text or "<slot" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_scaffold.py::test_static_components_exist -v`
Expected: FAIL.

- [ ] **Step 3: Write `Tldr.astro`**

```astro
---
// TLDR callout — green left border, used at top of method pages.
---
<aside class="tldr">
  <span class="tldr-label">TLDR</span>
  <span class="tldr-body"><slot /></span>
</aside>

<style>
  .tldr {
    display: block;
    border-left: 3px solid #4ade80;
    background: rgba(74, 222, 128, 0.08);
    padding: 0.75rem 1rem;
    margin: 1rem 0;
    border-radius: 0 6px 6px 0;
  }
  .tldr-label {
    display: inline-block;
    color: #4ade80;
    font-weight: 700;
    font-size: 0.75rem;
    letter-spacing: 0.05em;
    margin-right: 0.5rem;
  }
</style>
```

- [ ] **Step 4: Write `KeyIdea.astro`**

```astro
---
// Key-idea callout — blue accent.
---
<aside class="key-idea">
  <span class="ki-label">Key Idea</span>
  <span class="ki-body"><slot /></span>
</aside>

<style>
  .key-idea {
    display: block;
    border-left: 3px solid #7aa2f7;
    background: rgba(122, 162, 247, 0.08);
    padding: 0.75rem 1rem;
    margin: 1rem 0;
    border-radius: 0 6px 6px 0;
  }
  .ki-label {
    color: #7aa2f7;
    font-weight: 700;
    font-size: 0.75rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    margin-right: 0.5rem;
  }
</style>
```

- [ ] **Step 5: Write `Diagram.astro`**

```astro
---
import fs from 'node:fs';
import path from 'node:path';

interface Props { src: string }
const { src } = Astro.props as Props;
const resolved = path.resolve(path.dirname(Astro.url.pathname), src);
let mermaidSource = '';
try {
  mermaidSource = fs.readFileSync(resolved, 'utf-8');
} catch {
  mermaidSource = `graph TD; missing["diagram not found: ${src}"]`;
}
---
<figure class="diagram">
  <pre class="mermaid">{mermaidSource}</pre>
</figure>

<script type="module">
  import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
  mermaid.initialize({ startOnLoad: true, theme: 'dark' });
</script>

<style>
  .diagram {
    margin: 1.5rem 0;
    padding: 1rem;
    background: rgba(255,255,255,0.02);
    border-radius: 6px;
  }
</style>
```

- [ ] **Step 6: Write `Term.astro`**

```astro
---
interface Props { name: string }
const { name } = Astro.props as Props;
---
<span class="term" data-term={name} tabindex="0"><slot /></span>

<script>
  // Tooltips bound at page load by reading /glossary.json.
  document.addEventListener('DOMContentLoaded', async () => {
    const res = await fetch('/glossary.json');
    if (!res.ok) return;
    const entries = await res.json();
    const byTerm = new Map(entries.filter(e => !e.kb_known).map(e => [e.term, e.definition]));
    document.querySelectorAll('.term').forEach(el => {
      const name = el.getAttribute('data-term');
      const def = name ? byTerm.get(name) : null;
      if (def) {
        el.setAttribute('title', def);
      } else {
        el.classList.add('term-plain');
      }
    });
  });
</script>

<style>
  .term {
    border-bottom: 1px dotted #7aa2f7;
    cursor: help;
  }
  .term-plain {
    border-bottom: none;
    cursor: text;
  }
</style>
```

- [ ] **Step 7: Run tests**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_scaffold.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add handbook_builder/templates/components tests/test_handbook_scaffold.py
git commit -m "feat: add static Astro components for handbook (Tldr/KeyIdea/Diagram/Term)"
```

---

## Task M0.3: `handbook_builder.scaffold` module

**Files:**
- Create: `handbook_builder/__init__.py`
- Create: `handbook_builder/scaffold.py`
- Test: `tests/test_handbook_scaffold.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_handbook_scaffold.py`:

```python
import json
import shutil
import tempfile


def test_apply_scaffold_writes_files(tmp_path):
    from handbook_builder.scaffold import apply_scaffold

    run_dir = tmp_path / "run"
    (run_dir / "19_handbook" / ".scaffold").mkdir(parents=True)
    payload = {
        "astro_config": "// astro config\nexport default {};\n",
        "theme_css": "/* tokyo */",
        "package_json": {
            "name": "handbook-test",
            "type": "module",
            "version": "0.0.1",
            "scripts": {"build": "astro build"},
            "dependencies": {"astro": "5.4.0"},
        },
        "sidebar_items": [{"label": "Book", "items": []}],
        "home_page_mdx": "---\ntitle: Home\n---\n# Home\n",
    }
    (run_dir / "19_handbook" / ".scaffold" / "curator_output.json").write_text(json.dumps(payload))

    apply_scaffold(run_dir)

    base = run_dir / "19_handbook"
    assert (base / "astro.config.mjs").read_text().startswith("// astro config")
    assert (base / "src/styles/custom.css").read_text() == "/* tokyo */"
    assert json.loads((base / "package.json").read_text())["name"] == "handbook-test"
    assert (base / "src/content/docs/index.mdx").read_text().startswith("---")
    assert (base / "src/components/Tldr.astro").exists()
    assert (base / "src/components/Diagram.astro").exists()
    sidebar = json.loads((base / ".scaffold/sidebar.json").read_text())
    assert sidebar[0]["label"] == "Book"
```

- [ ] **Step 2: Run test**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_scaffold.py::test_apply_scaffold_writes_files -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Create `handbook_builder/__init__.py`**

```python
"""Handbook builder: turns research run markdown into an Astro Starlight site."""
__all__ = ["scaffold", "pipeline"]
```

- [ ] **Step 4: Create `handbook_builder/scaffold.py`**

```python
"""Apply the curator's scaffold JSON to a run's 19_handbook/ directory."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = REPO_ROOT / "handbook_builder/templates"


def apply_scaffold(run_dir: Path) -> None:
    """Read curator_output.json and write the scaffold files."""
    handbook_dir = run_dir / "19_handbook"
    payload_path = handbook_dir / ".scaffold" / "curator_output.json"
    payload = json.loads(payload_path.read_text())

    _write_text(handbook_dir / "astro.config.mjs", payload["astro_config"])
    _write_text(handbook_dir / "src/styles/custom.css", payload["theme_css"])
    _write_text(
        handbook_dir / "package.json",
        json.dumps(payload["package_json"], indent=2) + "\n",
    )
    _write_text(handbook_dir / "src/content/docs/index.mdx", payload["home_page_mdx"])
    _write_text(
        handbook_dir / ".scaffold/sidebar.json",
        json.dumps(payload["sidebar_items"], indent=2),
    )

    components_dst = handbook_dir / "src/components"
    components_dst.mkdir(parents=True, exist_ok=True)
    for component in (TEMPLATES_DIR / "components").iterdir():
        shutil.copy2(component, components_dst / component.name)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
```

- [ ] **Step 5: Run test**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_scaffold.py::test_apply_scaffold_writes_files -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add handbook_builder/__init__.py handbook_builder/scaffold.py tests/test_handbook_scaffold.py
git commit -m "feat: handbook_builder.scaffold applies curator JSON to run dir"
```

---

## Task M0.4: `handbook_builder.linker` — sidebar + content copy

**Files:**
- Create: `handbook_builder/linker.py`
- Test: `tests/test_handbook_linker.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_handbook_linker.py`:

```python
import json
from pathlib import Path


def test_copy_chapters_into_docs(tmp_path):
    from handbook_builder.linker import copy_chapters_into_docs

    run_dir = tmp_path / "run"
    chapters = run_dir / "14_chapters"
    (chapters / "methods").mkdir(parents=True)
    (chapters / "families").mkdir()
    (chapters / "book").mkdir()
    (chapters / "methods/maskgct.md").write_text("# MaskGCT\n\nBody.\n")
    (chapters / "families/codec-tts.md").write_text("# Codec TTS Family\n")
    (chapters / "book/00_preface.md").write_text("# Preface\n")

    docs = run_dir / "19_handbook/src/content/docs"
    copy_chapters_into_docs(run_dir, docs)

    assert (docs / "methods/maskgct.mdx").exists()
    assert (docs / "families/codec-tts.mdx").exists()
    assert (docs / "book/00_preface.mdx").exists()
    assert "# MaskGCT" in (docs / "methods/maskgct.mdx").read_text()


def test_build_starlight_sidebar(tmp_path):
    from handbook_builder.linker import build_starlight_sidebar

    sidebar_json = {
        "items": [
            {"title": "Book", "children": [{"title": "Preface", "path": "14_chapters/book/00_preface.md"}]},
            {"title": "Generation", "children": [{"title": "MaskGCT (vq-...)", "path": "14_chapters/methods/maskgct.md"}]},
        ]
    }
    result = build_starlight_sidebar(sidebar_json)
    assert result == [
        {"label": "Book", "items": [{"label": "Preface", "slug": "book/00_preface"}]},
        {"label": "Generation", "items": [{"label": "MaskGCT (vq-...)", "slug": "methods/maskgct"}]},
    ]
```

- [ ] **Step 2: Run test**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_linker.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `handbook_builder/linker.py`**

```python
"""Copy chapter markdown into Starlight content docs and translate sidebar."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def copy_chapters_into_docs(run_dir: Path, docs_dir: Path) -> None:
    """Copy 14_chapters/{book,families,methods}/*.md to docs_dir as .mdx."""
    src_root = run_dir / "14_chapters"
    for kind in ("book", "families", "methods"):
        src_kind = src_root / kind
        if not src_kind.exists():
            continue
        dst_kind = docs_dir / kind
        dst_kind.mkdir(parents=True, exist_ok=True)
        for md in src_kind.rglob("*.md"):
            rel = md.relative_to(src_kind)
            dst = dst_kind / rel.with_suffix(".mdx")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(md, dst)


def build_starlight_sidebar(sidebar_json: dict[str, Any]) -> list[dict[str, Any]]:
    """Translate 16_book/sidebar.json into Starlight sidebar config."""
    result: list[dict[str, Any]] = []
    for group in sidebar_json.get("items", []):
        items: list[dict[str, str]] = []
        for child in group.get("children", []):
            slug = _path_to_slug(child["path"])
            items.append({"label": child["title"], "slug": slug})
        result.append({"label": group["title"], "items": items})
    return result


def _path_to_slug(path: str) -> str:
    """`14_chapters/methods/maskgct.md` → `methods/maskgct`."""
    parts = path.split("/")
    if parts and parts[0].startswith("14_chapters"):
        parts = parts[1:]
    last = parts[-1]
    if last.endswith(".md"):
        parts[-1] = last[:-3]
    elif last.endswith(".mdx"):
        parts[-1] = last[:-4]
    return "/".join(parts)
```

- [ ] **Step 4: Run test**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_linker.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add handbook_builder/linker.py tests/test_handbook_linker.py
git commit -m "feat: handbook_builder.linker copies chapters and translates sidebar"
```

---

## Task M0.5: `handbook_builder.dispatch` — adapter over run_shards

**Files:**
- Create: `handbook_builder/dispatch.py`
- Test: `tests/test_handbook_pipeline.py` (initial — dispatch piece only)

- [ ] **Step 1: Write the failing test**

Create `tests/test_handbook_pipeline.py`:

```python
from pathlib import Path


def test_build_curator_spec_uses_run_id_and_payload(tmp_path):
    from handbook_builder.dispatch import build_curator_spec

    run_dir = tmp_path / "run-abc"
    run_dir.mkdir()
    manifest = [{"type": "methods", "id": "maskgct", "title": "MaskGCT", "path": "methods/maskgct"}]
    parts = [{"title": "Generation", "methods": ["maskgct"]}]

    spec = build_curator_spec(run_dir, topic="Real-time S2S", manifest=manifest, parts=parts)

    assert spec.stage == "19"
    assert spec.shard_id.startswith("scaffold")
    assert spec.agent == "web_design_curator"
    assert "run_id=run-abc" in spec.prompt
    assert "Real-time S2S" in spec.prompt
    assert spec.expected_outputs == ["19_handbook/.scaffold/curator_output.json"]
```

- [ ] **Step 2: Run test**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_pipeline.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `handbook_builder/dispatch.py`**

```python
"""Adapter around scripts/run_auto_research.py.run_shards for Stage 19."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Reuse types from the existing runner.
from scripts.run_auto_research import (  # type: ignore
    ShardSpec,
    _generic_agent_prompt,
    run_shards,
)


def build_curator_spec(
    run_dir: Path,
    *,
    topic: str,
    manifest: list[dict[str, Any]],
    parts: list[dict[str, Any]],
) -> ShardSpec:
    payload = {"topic": topic, "chapter_manifest": manifest, "parts": parts}
    return ShardSpec(
        stage="19",
        shard_id="scaffold-001",
        agent="web_design_curator",
        model="gpt-5.4",
        prompt=_generic_agent_prompt(
            ".codex/agents/web_design_curator.toml",
            run_dir.name,
            "19",
            "scaffold-001",
            payload,
        ),
        expected_outputs=["19_handbook/.scaffold/curator_output.json"],
    )


def run_handbook_shards(
    run_dir: Path,
    specs: list[ShardSpec],
    *,
    max_workers: int = 1,
    executor: str = "sdk",
) -> None:
    if not specs:
        return
    run_shards(run_dir, specs, max_workers=max_workers, executor=executor)
```

- [ ] **Step 4: Run test**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_pipeline.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add handbook_builder/dispatch.py tests/test_handbook_pipeline.py
git commit -m "feat: handbook_builder.dispatch adapts run_shards for stage 19"
```

---

## Task M0.6: `handbook_builder.pipeline` — orchestrate M0 (scaffold-only)

**Files:**
- Create: `handbook_builder/pipeline.py`
- Test: `tests/test_handbook_pipeline.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_handbook_pipeline.py`:

```python
import json
import shutil
from unittest.mock import patch


def _make_minimal_run(tmp_path: Path) -> Path:
    """Create a minimal run dir with required inputs for M0 pipeline."""
    run_dir = tmp_path / "run-mini"
    chapters = run_dir / "14_chapters"
    (chapters / "methods").mkdir(parents=True)
    (chapters / "book").mkdir()
    (chapters / "methods/maskgct.md").write_text("# MaskGCT\n")
    (chapters / "book/00_preface.md").write_text("# Preface\n")
    book = run_dir / "16_book"
    book.mkdir()
    (book / "sidebar.json").write_text(json.dumps({"items": [
        {"title": "Book", "children": [{"title": "Preface", "path": "14_chapters/book/00_preface.md"}]},
        {"title": "Generation", "children": [{"title": "MaskGCT", "path": "14_chapters/methods/maskgct.md"}]},
    ]}))
    (book / "chapters_manifest.json").write_text(json.dumps([
        {"type": "book", "id": "preface", "title": "Preface", "path": "book/00_preface"},
        {"type": "methods", "id": "maskgct", "title": "MaskGCT", "path": "methods/maskgct"},
    ]))
    config = run_dir / "run_config.json"
    config.write_text(json.dumps({"run_id": "run-mini", "topic": "Test Topic"}))
    return run_dir


def test_run_scaffold_only_pipeline(tmp_path):
    from handbook_builder import pipeline

    run_dir = _make_minimal_run(tmp_path)

    def fake_run_shards(run_dir, specs, **kwargs):
        scaffold_dir = run_dir / "19_handbook" / ".scaffold"
        scaffold_dir.mkdir(parents=True, exist_ok=True)
        (scaffold_dir / "curator_output.json").write_text(json.dumps({
            "astro_config": "export default {};",
            "theme_css": "/* tokyo */",
            "package_json": {"name": "h", "type": "module", "version": "0.0.1",
                              "scripts": {"build": "astro build"},
                              "dependencies": {"astro": "5.4.0"}},
            "sidebar_items": [{"label": "Book", "items": []}],
            "home_page_mdx": "---\ntitle: Home\n---\n",
        }))

    with patch("handbook_builder.dispatch.run_shards", side_effect=fake_run_shards):
        pipeline.build(run_dir, milestone="M0", run_pnpm_build=False)

    base = run_dir / "19_handbook"
    assert (base / "astro.config.mjs").exists()
    assert (base / "src/content/docs/methods/maskgct.mdx").exists()
    assert (base / "src/content/docs/book/00_preface.mdx").exists()
    assert (base / "src/components/Tldr.astro").exists()
```

- [ ] **Step 2: Run test**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_pipeline.py::test_run_scaffold_only_pipeline -v`
Expected: FAIL.

- [ ] **Step 3: Implement `handbook_builder/pipeline.py`**

```python
"""Orchestrate Stage 19 sub-stages."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from handbook_builder import dispatch, linker, scaffold

Milestone = Literal["M0", "M1", "M2", "M3", "M4"]


def build(
    run_dir: Path,
    *,
    milestone: Milestone = "M0",
    max_workers: int = 12,
    executor: str = "sdk",
    run_pnpm_build: bool = True,
) -> None:
    """Run Stage 19 up to the given milestone."""
    config = json.loads((run_dir / "run_config.json").read_text())
    topic = config.get("topic", "")
    manifest = json.loads((run_dir / "16_book" / "chapters_manifest.json").read_text())
    sidebar_src = json.loads((run_dir / "16_book" / "sidebar.json").read_text())
    parts = _parts_from_sidebar(sidebar_src)

    # 19.0 scaffold
    spec = dispatch.build_curator_spec(run_dir, topic=topic, manifest=manifest, parts=parts)
    dispatch.run_handbook_shards(run_dir, [spec], max_workers=1, executor=executor)
    scaffold.apply_scaffold(run_dir)

    # 19.5 (partial) — copy markdown into docs
    docs_dir = run_dir / "19_handbook/src/content/docs"
    linker.copy_chapters_into_docs(run_dir, docs_dir)

    # Later milestones (M1+) add sub-stages here.
    if milestone != "M0":
        raise NotImplementedError(f"milestone {milestone} not yet implemented")

    if run_pnpm_build:
        from handbook_builder import build as build_step
        build_step.run_pnpm_build(run_dir)


def _parts_from_sidebar(sidebar: dict) -> list[dict]:
    parts: list[dict] = []
    for group in sidebar.get("items", []):
        if group.get("title") == "Book":
            continue
        method_ids = [
            _slug_id(child["path"]) for child in group.get("children", [])
        ]
        parts.append({"title": group["title"], "methods": method_ids})
    return parts


def _slug_id(path: str) -> str:
    return path.rsplit("/", 1)[-1].removesuffix(".md")
```

- [ ] **Step 4: Run test**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_pipeline.py::test_run_scaffold_only_pipeline -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add handbook_builder/pipeline.py tests/test_handbook_pipeline.py
git commit -m "feat: handbook_builder.pipeline orchestrates scaffold-only M0"
```

---

## Task M0.7: `handbook_builder.build` — pnpm wrapper

**Files:**
- Create: `handbook_builder/build.py`
- Test: `tests/test_handbook_pipeline.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_handbook_pipeline.py`:

```python
def test_run_pnpm_build_invokes_subprocess(tmp_path):
    from handbook_builder import build

    run_dir = tmp_path / "run-x"
    (run_dir / "19_handbook").mkdir(parents=True)

    calls: list[list[str]] = []

    def fake_run(cmd, cwd, check, capture_output, text):
        calls.append(cmd)
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()

    with patch("handbook_builder.build.subprocess.run", side_effect=fake_run):
        build.run_pnpm_build(run_dir)

    assert calls == [["pnpm", "install", "--frozen-lockfile=false"], ["pnpm", "build"]]
```

- [ ] **Step 2: Run test**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_pipeline.py::test_run_pnpm_build_invokes_subprocess -v`
Expected: FAIL.

- [ ] **Step 3: Implement `handbook_builder/build.py`**

```python
"""Invoke pnpm install + build inside a run's 19_handbook directory."""
from __future__ import annotations

import subprocess
from pathlib import Path


def run_pnpm_build(run_dir: Path) -> None:
    cwd = run_dir / "19_handbook"
    for cmd in (["pnpm", "install", "--frozen-lockfile=false"], ["pnpm", "build"]):
        result = subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"pnpm command failed: {' '.join(cmd)}\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
```

- [ ] **Step 4: Run test**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_pipeline.py::test_run_pnpm_build_invokes_subprocess -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add handbook_builder/build.py tests/test_handbook_pipeline.py
git commit -m "feat: handbook_builder.build wraps pnpm install + build"
```

---

## Task M0.8: Register Stage 19 in `run_auto_research.py`

**Files:**
- Modify: `scripts/run_auto_research.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_handbook_pipeline.py`:

```python
def test_stage_19_registered_in_runner():
    text = (REPO_ROOT / "scripts/run_auto_research.py").read_text()
    assert "def run_stage_19" in text
    assert '("19", run_stage_19)' in text
    assert '"19":' in text  # PRIMARY_ARTIFACTS key
```

(Add `REPO_ROOT = Path(__file__).resolve().parents[1]` to the test file imports if not present.)

- [ ] **Step 2: Run test**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_pipeline.py::test_stage_19_registered_in_runner -v`
Expected: FAIL.

- [ ] **Step 3: Add `run_stage_19` to `scripts/run_auto_research.py`**

Insert after `run_stage_18` (around line 1152):

```python
def run_stage_19(
    run_dir: Path,
    *,
    max_workers: int = 12,
    executor: str = DEFAULT_EXECUTOR,
) -> None:
    """Stage 19: build the web handbook (Astro Starlight site)."""
    from handbook_builder import pipeline  # local import to avoid cycle

    milestone = os.environ.get("HANDBOOK_MILESTONE", "M0")
    pipeline.build(
        run_dir,
        milestone=milestone,  # type: ignore[arg-type]
        max_workers=max_workers,
        executor=executor,
        run_pnpm_build=os.environ.get("HANDBOOK_SKIP_PNPM") != "1",
    )
    if not primary_artifact_exists(run_dir, "19"):
        raise RuntimeError("Stage 19 did not produce handbook artifacts")
```

Add `import os` near top if not already.

In `PRIMARY_ARTIFACTS` (around line 35), add:

```python
    "19": ("19_handbook/astro.config.mjs", "19_handbook/package.json"),
```

In `write_handlers` (around line 3104), append:

```python
        ("19", run_stage_19),
```

- [ ] **Step 4: Run test**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_pipeline.py::test_stage_19_registered_in_runner -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_auto_research.py tests/test_handbook_pipeline.py
git commit -m "feat: register Stage 19 handbook build in run_auto_research.py"
```

---

## Task M0.9: Standalone `scripts/build_handbook.py`

**Files:**
- Create: `scripts/build_handbook.py`
- Test: `tests/test_handbook_pipeline.py` (extend)

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_build_handbook_script_exists_and_imports():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "build_handbook_script", REPO_ROOT / "scripts/build_handbook.py"
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    assert hasattr(mod, "main")
```

- [ ] **Step 2: Run test**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_pipeline.py::test_build_handbook_script_exists_and_imports -v`
Expected: FAIL.

- [ ] **Step 3: Create `scripts/build_handbook.py`**

```python
#!/usr/bin/env python3
"""Standalone driver: rebuild the web handbook for one research run."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from handbook_builder import pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--milestone", default="M0", choices=["M0", "M1", "M2", "M3", "M4"])
    parser.add_argument("--max-workers", type=int, default=12)
    parser.add_argument("--executor", default="sdk")
    parser.add_argument("--skip-pnpm", action="store_true")
    args = parser.parse_args(argv)

    run_dir = args.run_dir.resolve()
    if not run_dir.exists():
        print(f"run dir not found: {run_dir}", file=sys.stderr)
        return 2

    pipeline.build(
        run_dir,
        milestone=args.milestone,
        max_workers=args.max_workers,
        executor=args.executor,
        run_pnpm_build=not args.skip_pnpm,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_pipeline.py::test_build_handbook_script_exists_and_imports -v`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `env PYTHONPATH=. uv run pytest tests/ -x --tb=short`
Expected: all 251 prior tests + new ones PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/build_handbook.py tests/test_handbook_pipeline.py
git commit -m "feat: add scripts/build_handbook.py standalone driver"
```

---

## Task M0.10: End-to-end M0 smoke run

**Files:** (manual run only, no code changes)

- [ ] **Step 1: Pick a real run**

```bash
ls research_runs/
# Use: real-time-speech-to-speech-language-models-for-voice-assistants-20260513-235624
```

- [ ] **Step 2: Build with milestone M0, skipping pnpm**

```bash
env PYTHONPATH=. uv run python scripts/build_handbook.py \
  research_runs/real-time-speech-to-speech-language-models-for-voice-assistants-20260513-235624 \
  --milestone M0 --skip-pnpm
```

Expected: `19_handbook/astro.config.mjs`, `package.json`, `src/content/docs/{book,families,methods}/*.mdx`, `src/components/{Tldr,KeyIdea,Diagram,Term}.astro` all present.

- [ ] **Step 3: Run pnpm build manually (requires pnpm installed)**

```bash
cd research_runs/<run>/19_handbook
pnpm install
pnpm build
```

Expected: `dist/index.html` exists, sidebar covers every chapter.

- [ ] **Step 4: Preview locally**

```bash
pnpm preview
# Open http://localhost:4321
```

Verify: dark Tokyo Night palette, every chapter renders, search works.

- [ ] **Step 5: Tag the milestone**

```bash
git tag handbook-m0
```

**M0 ship gate:** site builds and renders all chapters unchanged. Stop here for review before M1.

---

# Milestone M1 — Glossary + Diagrams

**Goal:** Hover-tooltips on technical terms (`<Term>` component) backed by an agent-built `glossary.json`; inline Mermaid diagrams on family and method pages.

## Task M1.1: `glossary-builder` skill + TOML

**Files:**
- Create: `.agents/skills/glossary-builder/SKILL.md`
- Create: `.codex/agents/glossary_builder.toml`
- Test: `tests/test_handbook_glossary.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_handbook_glossary.py`:

```python
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_glossary_skill_exists():
    skill = REPO_ROOT / ".agents/skills/glossary-builder/SKILL.md"
    assert skill.exists()
    text = skill.read_text()
    assert "knowledge_base.md" in text
    assert "kb_known" in text
    assert "appears_in" in text
    assert "definition" in text


def test_glossary_toml_exists():
    toml = REPO_ROOT / ".codex/agents/glossary_builder.toml"
    assert toml.exists()
    assert 'name = "glossary_builder"' in toml.read_text()
```

- [ ] **Step 2: Run test**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_glossary.py -v`
Expected: FAIL.

- [ ] **Step 3: Write SKILL.md**

Create `.agents/skills/glossary-builder/SKILL.md`:

```markdown
---
name: glossary-builder
description: Build the handbook's glossary.json from method packs and knowledge_base.md. Terms known to the reader are flagged kb_known=true and skipped at tooltip render time.
---

# Glossary Builder

## Inputs (from payload)
- `run_id`
- `pack_dir` — relative path `13_chapter_packs/methods/`
- `kb_path` — relative path `.agents/knowledge_base.md`

## Process
1. Read every `13_chapter_packs/methods/*.json` and extract technical terms from the pack `definitions`, `key_terms`, and section captions.
2. Read `.agents/knowledge_base.md`. Any term whose surface form (case-insensitive) appears in `knowledge_base.md` → `kb_known: true`.
3. For each term, produce a definition no longer than 280 chars, drawn ONLY from the pack. Never invent definitions.
4. Aggregate `appears_in` from every pack the term shows up in.

## Output
Write `19_handbook/public/glossary.json`:

```json
[
  {"term": "RVQ", "definition": "Residual Vector Quantization...", "appears_in": ["maskgct", "vall-e-2"], "kb_known": false},
  {"term": "Transformer", "definition": "...", "appears_in": [...], "kb_known": true}
]
```

## Hard Rules
- Every term and definition MUST be traceable to a pack. No invention.
- `kb_known: true` entries MUST still be emitted (downstream uses them for diagnostics).
- Sort entries alphabetically by `term`.
- Return only the standard short success string.
```

- [ ] **Step 4: Write TOML**

Create `.codex/agents/glossary_builder.toml`:

```toml
name = "glossary_builder"
description = "Build glossary.json for the web handbook from chapter packs."
model = "gpt-5.4"
model_reasoning_effort = "medium"

developer_instructions = """
Follow .agents/skills/glossary-builder/SKILL.md.

ALL FILE PATHS ARE RELATIVE TO research_runs/{run_id}/.

Write the output to research_runs/{run_id}/19_handbook/public/glossary.json.

Return the standard short success string.
"""
```

- [ ] **Step 5: Run tests**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_glossary.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add .agents/skills/glossary-builder .codex/agents/glossary_builder.toml tests/test_handbook_glossary.py
git commit -m "feat: add glossary-builder skill and agent toml"
```

---

## Task M1.2: `handbook_builder.glossary` module

**Files:**
- Create: `handbook_builder/glossary.py`
- Test: `tests/test_handbook_glossary.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_handbook_glossary.py`:

```python
def test_validate_glossary_schema(tmp_path):
    from handbook_builder.glossary import validate_glossary

    good = [
        {"term": "RVQ", "definition": "Residual VQ.", "appears_in": ["maskgct"], "kb_known": False},
        {"term": "Z", "definition": "Z.", "appears_in": [], "kb_known": True},
    ]
    validate_glossary(good)  # should not raise

    bad = [{"term": "X"}]
    import pytest
    with pytest.raises(ValueError):
        validate_glossary(bad)


def test_build_glossary_spec(tmp_path):
    from handbook_builder.glossary import build_glossary_spec

    run_dir = tmp_path / "run-y"
    run_dir.mkdir()
    spec = build_glossary_spec(run_dir)
    assert spec.stage == "19"
    assert spec.shard_id == "glossary-001"
    assert spec.agent == "glossary_builder"
    assert spec.expected_outputs == ["19_handbook/public/glossary.json"]
```

- [ ] **Step 2: Run test**

Expected: FAIL — module missing.

- [ ] **Step 3: Implement `handbook_builder/glossary.py`**

```python
"""Glossary sub-stage: invoke glossary-builder and validate output."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.run_auto_research import ShardSpec, _generic_agent_prompt  # type: ignore


REQUIRED_FIELDS = {"term", "definition", "appears_in", "kb_known"}


def build_glossary_spec(run_dir: Path) -> ShardSpec:
    payload = {
        "pack_dir": "13_chapter_packs/methods",
        "kb_path": ".agents/knowledge_base.md",
    }
    return ShardSpec(
        stage="19",
        shard_id="glossary-001",
        agent="glossary_builder",
        model="gpt-5.4",
        prompt=_generic_agent_prompt(
            ".codex/agents/glossary_builder.toml",
            run_dir.name,
            "19",
            "glossary-001",
            payload,
        ),
        expected_outputs=["19_handbook/public/glossary.json"],
    )


def validate_glossary(entries: list[dict[str, Any]]) -> None:
    for i, entry in enumerate(entries):
        missing = REQUIRED_FIELDS - set(entry.keys())
        if missing:
            raise ValueError(f"glossary entry {i} missing fields: {sorted(missing)}")
        if not isinstance(entry["appears_in"], list):
            raise ValueError(f"glossary entry {i} 'appears_in' must be a list")
        if not isinstance(entry["kb_known"], bool):
            raise ValueError(f"glossary entry {i} 'kb_known' must be bool")
        if len(entry["definition"]) > 280:
            raise ValueError(f"glossary entry {i} definition exceeds 280 chars")
```

- [ ] **Step 4: Run test**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_glossary.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add handbook_builder/glossary.py tests/test_handbook_glossary.py
git commit -m "feat: handbook_builder.glossary spec + schema validation"
```

---

## Task M1.3: `diagram-author` skill + TOML

**Files:**
- Create: `.agents/skills/diagram-author/SKILL.md`
- Create: `.codex/agents/diagram_author.toml`
- Test: `tests/test_handbook_diagram.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_handbook_diagram.py`:

```python
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_diagram_skill_exists():
    skill = REPO_ROOT / ".agents/skills/diagram-author/SKILL.md"
    assert skill.exists()
    text = skill.read_text()
    assert "Mermaid" in text or "mermaid" in text
    assert "every node label" in text.lower() or "node labels" in text.lower()
    assert ".mmd" in text


def test_diagram_toml_exists():
    toml = REPO_ROOT / ".codex/agents/diagram_author.toml"
    assert toml.exists()
    assert 'name = "diagram_author"' in toml.read_text()
```

- [ ] **Step 2: Run test**

Expected: FAIL.

- [ ] **Step 3: Write SKILL.md**

Create `.agents/skills/diagram-author/SKILL.md`:

```markdown
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
- Every node LABEL must appear as a name/title in the input JSON. Never invent component names.
- File must parse as valid Mermaid (test with `mmdc --dry-run`).
- Keep the diagram under 25 nodes — collapse repeated structures.
- Return the standard short success string.
```

- [ ] **Step 4: Write TOML**

```toml
name = "diagram_author"
description = "Generate one Mermaid diagram per family chapter and per method chapter-pack."
model = "gpt-5.4"
model_reasoning_effort = "medium"

developer_instructions = """
Follow .agents/skills/diagram-author/SKILL.md.

Inputs: run_id, target_type, target_id, source_path.

ALL FILE PATHS ARE RELATIVE TO research_runs/{run_id}/.

Read the source JSON, emit a single .mmd file at the path specified by the skill.

Return the standard short success string.
"""
```

- [ ] **Step 5: Run tests**

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add .agents/skills/diagram-author .codex/agents/diagram_author.toml tests/test_handbook_diagram.py
git commit -m "feat: add diagram-author skill and agent toml"
```

---

## Task M1.4: `handbook_builder.diagrams` module

**Files:**
- Create: `handbook_builder/diagrams.py`
- Test: `tests/test_handbook_diagram.py` (extend)

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_validate_mermaid_node_provenance():
    from handbook_builder.diagrams import validate_node_provenance

    allowed = {"MaskGCT", "Tokenizer", "Decoder"}
    good = "graph LR; Tokenizer --> MaskGCT --> Decoder"
    validate_node_provenance(good, allowed)

    bad = "graph LR; Tokenizer --> WaveNet --> Decoder"
    import pytest
    with pytest.raises(ValueError) as ex:
        validate_node_provenance(bad, allowed)
    assert "WaveNet" in str(ex.value)


def test_build_diagram_specs(tmp_path):
    from handbook_builder.diagrams import build_diagram_specs

    run_dir = tmp_path / "run-z"
    (run_dir / "12_taxonomy").mkdir(parents=True)
    (run_dir / "13_chapter_packs/methods").mkdir(parents=True)
    (run_dir / "12_taxonomy/outline.json").write_text('{"families":[{"id":"codec-tts"},{"id":"non-ar-tts"}],"methods":[{"id":"maskgct"}]}')
    (run_dir / "13_chapter_packs/methods/maskgct.json").write_text("{}")

    specs = build_diagram_specs(run_dir)
    ids = {s.shard_id for s in specs}
    assert "diagram-family-codec-tts" in ids
    assert "diagram-method-maskgct" in ids
    assert all(s.stage == "19" for s in specs)
```

- [ ] **Step 2: Run test**

Expected: FAIL.

- [ ] **Step 3: Implement `handbook_builder/diagrams.py`**

```python
"""Diagram sub-stage: spec builder + post-hoc validation."""
from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.run_auto_research import ShardSpec, _generic_agent_prompt  # type: ignore


NODE_TOKEN_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_\- ]*)\b")


def build_diagram_specs(run_dir: Path) -> list[ShardSpec]:
    outline = json.loads((run_dir / "12_taxonomy/outline.json").read_text())
    specs: list[ShardSpec] = []

    for family in outline.get("families", []):
        fid = family["id"]
        if fid == "standalone" or family.get("is_group"):
            continue
        specs.append(_make_spec(run_dir, "family", fid, "12_taxonomy/outline.json"))

    for method in outline.get("methods", []):
        mid = method["id"]
        specs.append(
            _make_spec(run_dir, "method", mid, f"13_chapter_packs/methods/{mid}.json")
        )

    return specs


def _make_spec(run_dir: Path, target_type: str, target_id: str, source_path: str) -> ShardSpec:
    payload = {
        "target_type": target_type,
        "target_id": target_id,
        "source_path": source_path,
    }
    plural = "families" if target_type == "family" else "methods"
    return ShardSpec(
        stage="19",
        shard_id=f"diagram-{target_type}-{target_id}",
        agent="diagram_author",
        model="gpt-5.4",
        prompt=_generic_agent_prompt(
            ".codex/agents/diagram_author.toml",
            run_dir.name,
            "19",
            f"diagram-{target_type}-{target_id}",
            payload,
        ),
        expected_outputs=[
            f"19_handbook/src/assets/diagrams/{plural}/{target_id}.mmd"
        ],
    )


def validate_node_provenance(mermaid_source: str, allowed_names: set[str]) -> None:
    """Reject diagrams whose node labels are absent from the source JSON."""
    body = re.sub(r"^\s*graph\s+\w+;?", "", mermaid_source, count=1).strip()
    tokens = set()
    for line in body.splitlines():
        line = line.split("%%")[0]  # strip mermaid comments
        for match in re.findall(r"([A-Z][A-Za-z0-9_\-]*)\b", line):
            tokens.add(match)
    skipped = {"TD", "LR", "TB", "BT", "RL"}
    unknown = (tokens - allowed_names) - skipped
    if unknown:
        raise ValueError(f"diagram references unknown nodes: {sorted(unknown)}")
```

- [ ] **Step 4: Run test**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add handbook_builder/diagrams.py tests/test_handbook_diagram.py
git commit -m "feat: handbook_builder.diagrams spec builder + node provenance check"
```

---

## Task M1.5: Extend pipeline to run M1 sub-stages

**Files:**
- Modify: `handbook_builder/pipeline.py`
- Test: `tests/test_handbook_pipeline.py` (extend)

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_pipeline_m1_runs_glossary_and_diagrams(tmp_path):
    from handbook_builder import pipeline

    run_dir = _make_minimal_run(tmp_path)
    # M1 needs taxonomy + a pack
    (run_dir / "12_taxonomy").mkdir(exist_ok=True)
    (run_dir / "12_taxonomy/outline.json").write_text(json.dumps({
        "families": [], "methods": [{"id": "maskgct"}], "book_sections": []
    }))
    (run_dir / "13_chapter_packs/methods").mkdir(parents=True)
    (run_dir / "13_chapter_packs/methods/maskgct.json").write_text("{}")

    seen_shard_ids: list[str] = []

    def fake_run_shards(run_dir, specs, **kwargs):
        for s in specs:
            seen_shard_ids.append(s.shard_id)
            if s.shard_id == "scaffold-001":
                p = run_dir / "19_handbook/.scaffold/curator_output.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({
                    "astro_config": "", "theme_css": "", "package_json": {
                        "name": "h", "type": "module", "version": "0.0.1",
                        "scripts": {"build": "astro build"},
                        "dependencies": {"astro": "5.4.0"}
                    },
                    "sidebar_items": [], "home_page_mdx": "",
                }))
            elif s.shard_id == "glossary-001":
                p = run_dir / "19_handbook/public/glossary.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps([
                    {"term": "RVQ", "definition": "Residual VQ.", "appears_in": ["maskgct"], "kb_known": False}
                ]))
            elif s.shard_id.startswith("diagram-"):
                target = s.shard_id.replace("diagram-method-", "").replace("diagram-family-", "")
                plural = "methods" if "method" in s.shard_id else "families"
                p = run_dir / f"19_handbook/src/assets/diagrams/{plural}/{target}.mmd"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("graph LR; A --> B")

    with patch("handbook_builder.dispatch.run_shards", side_effect=fake_run_shards):
        pipeline.build(run_dir, milestone="M1", run_pnpm_build=False)

    assert "scaffold-001" in seen_shard_ids
    assert "glossary-001" in seen_shard_ids
    assert any(s.startswith("diagram-method-") for s in seen_shard_ids)
    assert (run_dir / "19_handbook/public/glossary.json").exists()
    assert (run_dir / "19_handbook/src/assets/diagrams/methods/maskgct.mmd").exists()
```

- [ ] **Step 2: Run test**

Expected: FAIL.

- [ ] **Step 3: Modify `handbook_builder/pipeline.py`**

Replace the body after `linker.copy_chapters_into_docs(run_dir, docs_dir)` with:

```python
    if milestone == "M0":
        if run_pnpm_build:
            from handbook_builder import build as build_step
            build_step.run_pnpm_build(run_dir)
        return

    # 19.1 glossary
    from handbook_builder import diagrams as diagrams_mod
    from handbook_builder import glossary as glossary_mod

    gloss_spec = glossary_mod.build_glossary_spec(run_dir)
    dispatch.run_handbook_shards(run_dir, [gloss_spec], max_workers=1, executor=executor)
    gloss_path = run_dir / "19_handbook/public/glossary.json"
    glossary_mod.validate_glossary(json.loads(gloss_path.read_text()))

    # 19.2 diagrams
    diagram_specs = diagrams_mod.build_diagram_specs(run_dir)
    dispatch.run_handbook_shards(
        run_dir, diagram_specs, max_workers=min(max_workers, 8), executor=executor
    )

    if milestone == "M1":
        if run_pnpm_build:
            from handbook_builder import build as build_step
            build_step.run_pnpm_build(run_dir)
        return

    raise NotImplementedError(f"milestone {milestone} not yet implemented")
```

- [ ] **Step 4: Run test**

Run: `env PYTHONPATH=. uv run pytest tests/test_handbook_pipeline.py::test_pipeline_m1_runs_glossary_and_diagrams -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add handbook_builder/pipeline.py tests/test_handbook_pipeline.py
git commit -m "feat: pipeline.build runs glossary + diagrams for M1"
```

---

## Task M1.6: M1 end-to-end smoke run

**Files:** none.

- [ ] **Step 1: Build M1 against a real run**

```bash
env PYTHONPATH=. uv run python scripts/build_handbook.py \
  research_runs/<run>/ --milestone M1 --skip-pnpm
```

Expected: `19_handbook/public/glossary.json` valid; `src/assets/diagrams/{families,methods}/*.mmd` present.

- [ ] **Step 2: Validate Mermaid parses (requires `@mermaid-js/mermaid-cli`)**

```bash
cd research_runs/<run>/19_handbook
for f in src/assets/diagrams/**/*.mmd; do
  npx -y @mermaid-js/mermaid-cli mmdc -i "$f" -o /tmp/test.svg || echo "FAIL: $f"
done
```

Expected: no FAILs.

- [ ] **Step 3: pnpm build and preview**

```bash
pnpm install && pnpm build && pnpm preview
```

Verify tooltips appear on hover, diagrams render.

- [ ] **Step 4: Tag**

```bash
git tag handbook-m1
```

**M1 ship gate:** glossary tooltips and Mermaid diagrams render on a real run.

---

# Milestone M2 — Method-Page TLDR Augmentation

**Goal:** Each of the ~150 method pages gets an agent-written TLDR + Key Idea + When-to-use callouts, gated by `verification-web`.

## Task M2.1: `web-tldr-writer` skill + TOML + tags vocab

**Files:**
- Create: `.agents/skills/web-tldr-writer/SKILL.md`
- Create: `.codex/agents/web_tldr_writer.toml`
- Create: `handbook_builder/tags_vocab.json`
- Test: `tests/test_handbook_tldr.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_handbook_tldr.py`:

```python
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_tldr_skill_exists():
    skill = REPO_ROOT / ".agents/skills/web-tldr-writer/SKILL.md"
    assert skill.exists()
    text = skill.read_text()
    assert "MUST be grounded" in text or "must appear in" in text.lower()
    assert "tldr" in text
    assert "key_idea" in text
    assert "when_to_use" in text
    assert "tags" in text
    assert "tags_vocab.json" in text
    assert "280" in text
    assert "140" in text


def test_tldr_toml_exists():
    toml = REPO_ROOT / ".codex/agents/web_tldr_writer.toml"
    assert toml.exists()
    assert 'name = "web_tldr_writer"' in toml.read_text()


def test_tags_vocab_present():
    vocab = REPO_ROOT / "handbook_builder/tags_vocab.json"
    assert vocab.exists()
    data = json.loads(vocab.read_text())
    assert isinstance(data, list)
    assert len(data) >= 10
    for tag in data:
        assert isinstance(tag, str)
```

- [ ] **Step 2: Run test**

Expected: FAIL.

- [ ] **Step 3: Write SKILL.md**

```markdown
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
- **Grounding.** Every claim in `tldr`, `key_idea`, `when_to_use` MUST appear in the source markdown OR the chapter pack. No new method names. No new metrics. No fabricated comparisons.
- **Lengths.** `tldr` ≤ 280 chars. `key_idea` ≤ 140 chars. 2–3 bullets in `when_to_use`, each ≤ 120 chars.
- **Tags.** Drawn ONLY from `handbook_builder/tags_vocab.json`. 1–4 tags. Reject and emit `tags: []` if no tag from the vocab is supported by the source.
- **Pack-only naming.** No mention of methods/datasets/metrics not present in the pack.
- Return the standard short success string.
```

- [ ] **Step 4: Write TOML**

```toml
name = "web_tldr_writer"
description = "Per-method-page TLDR / key idea / when-to-use JSON, grounded in the pack."
model = "gpt-5.4"
model_reasoning_effort = "medium"

developer_instructions = """
Follow .agents/skills/web-tldr-writer/SKILL.md.

Inputs: run_id, method_id, chapter_path, pack_path, tags_vocab_path.

ALL FILE PATHS ARE RELATIVE TO research_runs/{run_id}/ EXCEPT tags_vocab_path which is repo-root-relative.

Write the JSON to research_runs/{run_id}/19_handbook/.augment/methods/{method_id}.json.

Return the standard short success string.
"""
```

- [ ] **Step 5: Write `handbook_builder/tags_vocab.json`**

```json
[
  "TTS", "ASR", "S2ST", "S2T", "Streaming", "Full-Duplex",
  "Non-AR", "Autoregressive", "Diffusion", "Masked-Generative",
  "Codec", "Continuous", "Discrete-Token",
  "Zero-Shot", "Few-Shot", "Multilingual",
  "Speaker-Cloning", "Editing",
  "Tokenizer", "Encoder-Decoder", "Decoder-Only",
  "Low-Latency", "High-Quality",
  "Interaction", "Generation"
]
```

- [ ] **Step 6: Run tests**

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add .agents/skills/web-tldr-writer .codex/agents/web_tldr_writer.toml handbook_builder/tags_vocab.json tests/test_handbook_tldr.py
git commit -m "feat: add web-tldr-writer skill, agent toml, and tags vocab"
```

---

## Task M2.2: `verification-web` skill + TOML

**Files:**
- Create: `.agents/skills/verification-web/SKILL.md`
- Create: `.codex/agents/verifier_web.toml`
- Test: `tests/test_handbook_verifier_web.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_handbook_verifier_web.py`:

```python
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_verifier_web_skill_exists():
    skill = REPO_ROOT / ".agents/skills/verification-web/SKILL.md"
    assert skill.exists()
    text = skill.read_text()
    assert '"passed"' in text  # top-level passed flag contract
    assert "claims" in text
    assert "rejection_reason" in text
    assert "MUST appear" in text or "must appear" in text


def test_verifier_web_toml_exists():
    toml = REPO_ROOT / ".codex/agents/verifier_web.toml"
    assert toml.exists()
    assert 'name = "verifier_web"' in toml.read_text()
```

- [ ] **Step 2: Run test**

Expected: FAIL.

- [ ] **Step 3: Write SKILL.md**

```markdown
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
```

- [ ] **Step 4: Write TOML**

```toml
name = "verifier_web"
description = "Gate handbook web augmentations against the original chapter."
model = "gpt-5.4"
model_reasoning_effort = "high"

developer_instructions = """
Follow .agents/skills/verification-web/SKILL.md.

ALL FILE PATHS ARE RELATIVE TO research_runs/{run_id}/.

Write the verification JSON to the path specified by the skill.

Return the standard short success string.
"""
```

- [ ] **Step 5: Run tests**

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add .agents/skills/verification-web .codex/agents/verifier_web.toml tests/test_handbook_verifier_web.py
git commit -m "feat: add verification-web skill and agent toml"
```

---

## Task M2.3: `handbook_builder.verify` adapter

**Files:**
- Create: `handbook_builder/verify.py`
- Test: `tests/test_handbook_verifier_web.py` (extend)

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_load_verification_result_uses_top_level_passed(tmp_path):
    import json
    from handbook_builder.verify import load_verification_result

    path = tmp_path / "v.json"
    path.write_text(json.dumps({"passed": True, "claims": [], "rejection_reason": None}))
    result = load_verification_result(path)
    assert result.passed is True
    assert result.rejection_reason is None

    path.write_text(json.dumps({
        "passed": False, "claims": [{"text": "x", "status": "unsupported"}],
        "rejection_reason": "x not in source"
    }))
    result = load_verification_result(path)
    assert result.passed is False
    assert "x not in source" in result.rejection_reason


def test_build_verifier_spec():
    from handbook_builder.verify import build_verifier_spec
    from pathlib import Path

    spec = build_verifier_spec(
        Path("/tmp/run-1"),
        kind="tldr",
        target_id="maskgct",
        original_path="14_chapters/methods/maskgct.md",
        candidate_path="19_handbook/.augment/methods/maskgct.json",
    )
    assert spec.shard_id == "verify-tldr-maskgct"
    assert spec.agent == "verifier_web"
```

- [ ] **Step 2: Run test**

Expected: FAIL.

- [ ] **Step 3: Implement `handbook_builder/verify.py`**

```python
"""Adapter for the verification-web agent."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from scripts.run_auto_research import ShardSpec, _generic_agent_prompt  # type: ignore

Kind = Literal["tldr", "book_rewrite"]


@dataclass
class VerificationResult:
    passed: bool
    rejection_reason: str | None
    claims: list[dict[str, Any]]


def build_verifier_spec(
    run_dir: Path,
    *,
    kind: Kind,
    target_id: str,
    original_path: str,
    candidate_path: str,
) -> ShardSpec:
    expected = f"19_handbook/.augment/{kind}/{target_id}.verification.json"
    payload = {
        "kind": kind,
        "original_path": original_path,
        "candidate_path": candidate_path,
    }
    return ShardSpec(
        stage="19",
        shard_id=f"verify-{kind}-{target_id}",
        agent="verifier_web",
        model="gpt-5.4",
        prompt=_generic_agent_prompt(
            ".codex/agents/verifier_web.toml",
            run_dir.name,
            "19",
            f"verify-{kind}-{target_id}",
            payload,
        ),
        expected_outputs=[expected],
    )


def load_verification_result(path: Path) -> VerificationResult:
    data = json.loads(path.read_text())
    return VerificationResult(
        passed=bool(data.get("passed", False)),
        rejection_reason=data.get("rejection_reason"),
        claims=list(data.get("claims", [])),
    )
```

- [ ] **Step 4: Run test**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add handbook_builder/verify.py tests/test_handbook_verifier_web.py
git commit -m "feat: handbook_builder.verify adapts verifier-web for stage 19"
```

---

## Task M2.4: `handbook_builder.augment` — splicing logic

**Files:**
- Create: `handbook_builder/augment.py`
- Test: `tests/test_handbook_augment.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_handbook_augment.py`:

```python
import json
from pathlib import Path


def test_splice_tldr_into_method_mdx(tmp_path):
    from handbook_builder.augment import splice_tldr

    mdx = tmp_path / "maskgct.mdx"
    mdx.write_text("# MaskGCT\n\nOriginal prose.\n")
    payload = {
        "tldr": "Non-AR masked codec transformer for zero-shot TTS.",
        "key_idea": "Predict masked codec tokens in parallel.",
        "when_to_use": ["zero-shot cloning", "≤10 unmasking steps"],
        "tags": ["TTS", "Non-AR"],
    }

    splice_tldr(mdx, payload, diagram_rel=None)
    body = mdx.read_text()

    assert body.startswith("---\n")  # frontmatter inserted
    assert "tags:" in body
    assert "<Tldr>" in body
    assert "Non-AR masked codec transformer" in body
    assert "<KeyIdea>" in body
    assert ":::tip[When to use this]" in body
    assert "Original prose." in body
    assert body.count("# MaskGCT") == 1  # original H1 retained


def test_splice_tldr_with_diagram(tmp_path):
    from handbook_builder.augment import splice_tldr

    mdx = tmp_path / "maskgct.mdx"
    mdx.write_text("# MaskGCT\n\nProse.\n")
    splice_tldr(mdx, {
        "tldr": "T.", "key_idea": "K.", "when_to_use": ["one"], "tags": []
    }, diagram_rel="../../assets/diagrams/methods/maskgct.mmd")

    body = mdx.read_text()
    assert '<Diagram src="../../assets/diagrams/methods/maskgct.mmd" />' in body
```

- [ ] **Step 2: Run test**

Expected: FAIL.

- [ ] **Step 3: Implement `handbook_builder/augment.py`**

```python
"""Splice agent-authored TLDR/KeyIdea/WhenToUse + diagram into a method MDX page."""
from __future__ import annotations

from pathlib import Path
from typing import Any

IMPORTS = """import Tldr from '../../components/Tldr.astro';
import KeyIdea from '../../components/KeyIdea.astro';
import Diagram from '../../components/Diagram.astro';
"""


def splice_tldr(
    mdx_path: Path,
    payload: dict[str, Any],
    *,
    diagram_rel: str | None = None,
) -> None:
    """Rewrite an MDX file in place: frontmatter + imports + augment blocks + original body."""
    body = mdx_path.read_text()
    title = _extract_title(body)
    body_without_h1 = _strip_first_h1(body)

    frontmatter_lines = [
        "---",
        f'title: "{title}"',
    ]
    tags = payload.get("tags") or []
    if tags:
        frontmatter_lines.append(f"tags: {tags}")
    frontmatter_lines.append("---")
    frontmatter = "\n".join(frontmatter_lines)

    when_bullets = "\n".join(f"- {b}" for b in payload["when_to_use"])
    diagram_block = (
        f'\n<Diagram src="{diagram_rel}" />\n' if diagram_rel else ""
    )

    new_body = (
        f"{frontmatter}\n\n"
        f"{IMPORTS}\n"
        f"<Tldr>{payload['tldr']}</Tldr>\n\n"
        f"<KeyIdea>{payload['key_idea']}</KeyIdea>\n\n"
        f":::tip[When to use this]\n{when_bullets}\n:::\n"
        f"{diagram_block}\n"
        f"{body_without_h1}"
    )
    mdx_path.write_text(new_body)


def _extract_title(body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip().replace('"', '\\"')
    return "Untitled"


def _strip_first_h1(body: str) -> str:
    lines = body.splitlines()
    out: list[str] = []
    seen = False
    for line in lines:
        if not seen and line.startswith("# "):
            seen = True
            continue
        out.append(line)
    return "\n".join(out).lstrip("\n")
```

- [ ] **Step 4: Run test**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add handbook_builder/augment.py tests/test_handbook_augment.py
git commit -m "feat: handbook_builder.augment splices TLDR/KeyIdea/WhenToUse/Diagram into MDX"
```

---

## Task M2.5: M2 sub-stage orchestration in pipeline

**Files:**
- Modify: `handbook_builder/pipeline.py`
- Modify: `handbook_builder/augment.py` (add the orchestration)
- Test: `tests/test_handbook_pipeline.py` (extend)

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_pipeline_m2_runs_tldr_writer_and_verifier(tmp_path):
    from handbook_builder import pipeline

    run_dir = _make_minimal_run(tmp_path)
    (run_dir / "12_taxonomy").mkdir(exist_ok=True)
    (run_dir / "12_taxonomy/outline.json").write_text(json.dumps({
        "families": [], "methods": [{"id": "maskgct"}], "book_sections": []
    }))
    (run_dir / "13_chapter_packs/methods").mkdir(parents=True)
    (run_dir / "13_chapter_packs/methods/maskgct.json").write_text("{}")

    def fake_run_shards(run_dir, specs, **kwargs):
        for s in specs:
            if s.shard_id == "scaffold-001":
                p = run_dir / "19_handbook/.scaffold/curator_output.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({
                    "astro_config": "", "theme_css": "",
                    "package_json": {"name": "h", "type": "module", "version": "0.0.1",
                                      "scripts": {"build": "astro build"},
                                      "dependencies": {"astro": "5.4.0"}},
                    "sidebar_items": [], "home_page_mdx": "",
                }))
            elif s.shard_id == "glossary-001":
                p = run_dir / "19_handbook/public/glossary.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("[]")
            elif s.shard_id.startswith("diagram-"):
                target = s.shard_id.split("-", 2)[-1]
                plural = "methods" if "method" in s.shard_id else "families"
                p = run_dir / f"19_handbook/src/assets/diagrams/{plural}/{target}.mmd"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("graph LR; A --> B")
            elif s.shard_id.startswith("tldr-"):
                mid = s.shard_id.removeprefix("tldr-")
                p = run_dir / f"19_handbook/.augment/methods/{mid}.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({
                    "tldr": "T.", "key_idea": "K.",
                    "when_to_use": ["use"], "tags": ["TTS"],
                }))
            elif s.shard_id.startswith("verify-tldr-"):
                mid = s.shard_id.removeprefix("verify-tldr-")
                p = run_dir / f"19_handbook/.augment/tldr/{mid}.verification.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({"passed": True, "claims": [], "rejection_reason": None}))

    with patch("handbook_builder.dispatch.run_shards", side_effect=fake_run_shards):
        pipeline.build(run_dir, milestone="M2", run_pnpm_build=False)

    mdx = run_dir / "19_handbook/src/content/docs/methods/maskgct.mdx"
    assert mdx.exists()
    body = mdx.read_text()
    assert "<Tldr>T.</Tldr>" in body
    assert "<KeyIdea>K.</KeyIdea>" in body
    assert ":::tip[When to use this]" in body
```

- [ ] **Step 2: Run test**

Expected: FAIL.

- [ ] **Step 3: Add `build_tldr_specs` to `handbook_builder/augment.py`**

Append to `handbook_builder/augment.py`:

```python
from scripts.run_auto_research import ShardSpec, _generic_agent_prompt  # type: ignore


def build_tldr_specs(run_dir: Path, method_ids: list[str]) -> list[ShardSpec]:
    specs = []
    for mid in method_ids:
        payload = {
            "method_id": mid,
            "chapter_path": f"14_chapters/methods/{mid}.md",
            "pack_path": f"13_chapter_packs/methods/{mid}.json",
            "tags_vocab_path": "handbook_builder/tags_vocab.json",
        }
        specs.append(ShardSpec(
            stage="19",
            shard_id=f"tldr-{mid}",
            agent="web_tldr_writer",
            model="gpt-5.4",
            prompt=_generic_agent_prompt(
                ".codex/agents/web_tldr_writer.toml",
                run_dir.name, "19", f"tldr-{mid}", payload,
            ),
            expected_outputs=[f"19_handbook/.augment/methods/{mid}.json"],
        ))
    return specs
```

- [ ] **Step 4: Modify `handbook_builder/pipeline.py`**

Replace the `raise NotImplementedError` tail with the M2 block:

```python
    # 19.3 augment methods (TLDR + verifier)
    from handbook_builder import augment as augment_mod
    from handbook_builder import verify as verify_mod

    method_ids = [m["id"] for m in json.loads(
        (run_dir / "12_taxonomy/outline.json").read_text()
    ).get("methods", [])]

    tldr_specs = augment_mod.build_tldr_specs(run_dir, method_ids)
    dispatch.run_handbook_shards(
        run_dir, tldr_specs, max_workers=max_workers, executor=executor
    )

    verify_specs = [
        verify_mod.build_verifier_spec(
            run_dir,
            kind="tldr",
            target_id=mid,
            original_path=f"14_chapters/methods/{mid}.md",
            candidate_path=f"19_handbook/.augment/methods/{mid}.json",
        )
        for mid in method_ids
    ]
    dispatch.run_handbook_shards(
        run_dir, verify_specs, max_workers=max_workers, executor=executor
    )

    docs_dir = run_dir / "19_handbook/src/content/docs"
    needs_review: list[tuple[str, str]] = []
    for mid in method_ids:
        verification = verify_mod.load_verification_result(
            run_dir / f"19_handbook/.augment/tldr/{mid}.verification.json"
        )
        if not verification.passed:
            needs_review.append((mid, verification.rejection_reason or "unknown"))
            continue
        payload = json.loads(
            (run_dir / f"19_handbook/.augment/methods/{mid}.json").read_text()
        )
        mdx_path = docs_dir / "methods" / f"{mid}.mdx"
        diagram_rel = None
        diagram_path = run_dir / f"19_handbook/src/assets/diagrams/methods/{mid}.mmd"
        if diagram_path.exists():
            diagram_rel = f"../../assets/diagrams/methods/{mid}.mmd"
        augment_mod.splice_tldr(mdx_path, payload, diagram_rel=diagram_rel)

    if needs_review:
        review = run_dir / "19_handbook/NEEDS_REVIEW.md"
        review.write_text(
            "# Pages skipped by verifier-web\n\n"
            + "\n".join(f"- `{mid}` — {reason}" for mid, reason in needs_review)
        )

    if milestone == "M2":
        if run_pnpm_build:
            from handbook_builder import build as build_step
            build_step.run_pnpm_build(run_dir)
        return

    raise NotImplementedError(f"milestone {milestone} not yet implemented")
```

- [ ] **Step 5: Run test**

Expected: PASS.

- [ ] **Step 6: Run full test suite**

Run: `env PYTHONPATH=. uv run pytest tests/ -x --tb=short`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add handbook_builder/augment.py handbook_builder/pipeline.py tests/test_handbook_pipeline.py
git commit -m "feat: pipeline runs TLDR augment + verifier for M2; failures land in NEEDS_REVIEW.md"
```

---

## Task M2.6: M2 end-to-end smoke run

**Files:** none.

- [ ] **Step 1: Build M2 against a real run**

```bash
env PYTHONPATH=. uv run python scripts/build_handbook.py \
  research_runs/<run>/ --milestone M2 --max-workers 12
```

Expected: ~150 `.augment/methods/*.json` + ~150 `.augment/tldr/*.verification.json`; method MDX files contain `<Tldr>` blocks; `NEEDS_REVIEW.md` lists any rejected pages.

- [ ] **Step 2: Preview**

```bash
cd research_runs/<run>/19_handbook && pnpm preview
```

Click through five method pages — TLDR + Key Idea + When-to-use should render with the right palette.

- [ ] **Step 3: Tag**

```bash
git tag handbook-m2
```

**M2 ship gate:** ≥ 90% of method pages augmented (others gracefully fall back). Visually confirmed.

---

# Milestone M3 — Book-Chapter Web Rewrite

**Goal:** The 7 book-level chapters (preface, motivating intro, goals, taxonomy, shared examples, eval outlook, glossary) get a full web rewrite gated by `verification-web`.

## Task M3.1: `web-book-rewriter` skill + TOML

**Files:**
- Create: `.agents/skills/web-book-rewriter/SKILL.md`
- Create: `.codex/agents/web_book_rewriter.toml`
- Test: `tests/test_handbook_book_rewriter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_handbook_book_rewriter.py`:

```python
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_book_rewriter_skill_exists():
    skill = REPO_ROOT / ".agents/skills/web-book-rewriter/SKILL.md"
    assert skill.exists()
    text = skill.read_text()
    assert "≤ 4 sentences" in text or "<= 4 sentences" in text or "four sentences" in text
    assert "h3" in text
    assert ":::tip" in text or ":::note" in text
    assert "<details>" in text
    assert "no new factual claims" in text.lower() or "no new claims" in text.lower()


def test_book_rewriter_toml_exists():
    toml = REPO_ROOT / ".codex/agents/web_book_rewriter.toml"
    assert toml.exists()
    assert 'name = "web_book_rewriter"' in toml.read_text()
```

- [ ] **Step 2: Run test**

Expected: FAIL.

- [ ] **Step 3: Write SKILL.md**

```markdown
---
name: web-book-rewriter
description: Rewrite a book-level chapter (preface / intro / goals / taxonomy / shared examples / eval outlook / glossary) into web-scannable MDX. Preserve every citation and link. No new claims.
---

# Web Book Rewriter

## Inputs (from payload)
- `run_id`
- `chapter_id` — id of the book chapter (e.g., `00_preface`, `04_method_taxonomy`)
- `chapter_path` — `14_chapters/book/{chapter_id}.md`
- `topic` — research topic string
- `outline_path` — `12_taxonomy/outline.json`

## Output
Write `19_handbook/.augment/book/{chapter_id}.mdx` — the full MDX content (frontmatter + imports + body).

## Rewrite Rules
- **Paragraphs ≤ 4 sentences.** Split longer paragraphs.
- **Section every ~200 words.** Use h3 (`###`). Use h2 (`##`) only for the top-level structure already present in the original.
- **Callouts.** Wrap "key takeaways" in Starlight `:::tip[Title]` / `:::note[Title]` syntax.
- **Asides.** Wrap tangential content in `<details><summary>...</summary>...</details>`.
- **Diagrams.** Reference an existing diagram with `<Diagram src="../../assets/diagrams/families/<id>.mmd" />` only if the .mmd file already exists.
- **Links and citations.** Every `[text](path)` link and `[arxiv:NNNN]` citation from the original MUST be preserved verbatim.
- **No new claims.** No new method names. No new metrics. No comparisons absent from the original. The verifier will reject.

## Output Frontmatter Template
```mdx
---
title: "<Chapter Title>"
sidebar:
  order: <NN from filename prefix>
---

import Diagram from '../../components/Diagram.astro';
```

## Hard Rules
- Length: rewrite stays within ±25% of original word count.
- Citations preserved 1:1.
- Return the standard short success string.
```

- [ ] **Step 4: Write TOML**

```toml
name = "web_book_rewriter"
description = "Rewrite a book-level chapter into web-scannable MDX preserving all citations."
model = "gpt-5.4"
model_reasoning_effort = "high"

developer_instructions = """
Follow .agents/skills/web-book-rewriter/SKILL.md.

ALL FILE PATHS ARE RELATIVE TO research_runs/{run_id}/.

Write the MDX to research_runs/{run_id}/19_handbook/.augment/book/{chapter_id}.mdx.

Return the standard short success string.
"""
```

- [ ] **Step 5: Run tests**

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add .agents/skills/web-book-rewriter .codex/agents/web_book_rewriter.toml tests/test_handbook_book_rewriter.py
git commit -m "feat: add web-book-rewriter skill and agent toml"
```

---

## Task M3.2: `handbook_builder.book_rewrite` module

**Files:**
- Create: `handbook_builder/book_rewrite.py`
- Test: `tests/test_handbook_book_rewriter.py` (extend)

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_build_book_rewrite_specs(tmp_path):
    from handbook_builder.book_rewrite import build_book_rewrite_specs

    run_dir = tmp_path / "run-b"
    (run_dir / "14_chapters/book").mkdir(parents=True)
    (run_dir / "14_chapters/book/00_preface.md").write_text("# Preface")
    (run_dir / "14_chapters/book/04_method_taxonomy.md").write_text("# Taxonomy")

    specs = build_book_rewrite_specs(run_dir, topic="Speech LMs")
    ids = sorted(s.shard_id for s in specs)
    assert ids == ["bookrewrite-00_preface", "bookrewrite-04_method_taxonomy"]
    assert all(s.agent == "web_book_rewriter" for s in specs)


def test_citation_count_matches():
    from handbook_builder.book_rewrite import count_citations

    original = "See [VALL-E 2](methods/vall-e-2.md) and [arxiv:2503.01234]."
    candidate = "Refer to [VALL-E 2](methods/vall-e-2.md) and [arxiv:2503.01234]."
    assert count_citations(original) == count_citations(candidate)
```

- [ ] **Step 2: Run test**

Expected: FAIL.

- [ ] **Step 3: Implement `handbook_builder/book_rewrite.py`**

```python
"""Book-chapter web rewrite sub-stage."""
from __future__ import annotations

import re
from pathlib import Path

from scripts.run_auto_research import ShardSpec, _generic_agent_prompt  # type: ignore


CITATION_RE = re.compile(r"\[arxiv:[^\]]+\]|\[[^\]]+\]\([^)]+\)")


def build_book_rewrite_specs(run_dir: Path, *, topic: str) -> list[ShardSpec]:
    book_dir = run_dir / "14_chapters/book"
    chapter_ids = sorted(
        p.stem for p in book_dir.glob("*.md") if not p.stem.startswith("appendix")
    )
    specs = []
    for cid in chapter_ids:
        payload = {
            "chapter_id": cid,
            "chapter_path": f"14_chapters/book/{cid}.md",
            "topic": topic,
            "outline_path": "12_taxonomy/outline.json",
        }
        specs.append(ShardSpec(
            stage="19",
            shard_id=f"bookrewrite-{cid}",
            agent="web_book_rewriter",
            model="gpt-5.4",
            prompt=_generic_agent_prompt(
                ".codex/agents/web_book_rewriter.toml",
                run_dir.name, "19", f"bookrewrite-{cid}", payload,
            ),
            expected_outputs=[f"19_handbook/.augment/book/{cid}.mdx"],
        ))
    return specs


def count_citations(markdown_or_mdx: str) -> int:
    return len(CITATION_RE.findall(markdown_or_mdx))
```

- [ ] **Step 4: Run test**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add handbook_builder/book_rewrite.py tests/test_handbook_book_rewriter.py
git commit -m "feat: handbook_builder.book_rewrite spec builder + citation counter"
```

---

## Task M3.3: M3 orchestration in pipeline

**Files:**
- Modify: `handbook_builder/pipeline.py`
- Test: `tests/test_handbook_pipeline.py` (extend)

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_pipeline_m3_runs_book_rewrite_and_verifier(tmp_path):
    from handbook_builder import pipeline

    run_dir = _make_minimal_run(tmp_path)
    (run_dir / "12_taxonomy").mkdir(exist_ok=True)
    (run_dir / "12_taxonomy/outline.json").write_text(json.dumps({
        "families": [], "methods": [], "book_sections": [{"id": "preface"}]
    }))

    def fake(run_dir, specs, **kwargs):
        for s in specs:
            if s.shard_id == "scaffold-001":
                p = run_dir / "19_handbook/.scaffold/curator_output.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({
                    "astro_config": "", "theme_css": "",
                    "package_json": {"name": "h", "type": "module", "version": "0.0.1",
                                      "scripts": {"build": "astro build"},
                                      "dependencies": {"astro": "5.4.0"}},
                    "sidebar_items": [], "home_page_mdx": "",
                }))
            elif s.shard_id == "glossary-001":
                p = run_dir / "19_handbook/public/glossary.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("[]")
            elif s.shard_id.startswith("bookrewrite-"):
                cid = s.shard_id.removeprefix("bookrewrite-")
                p = run_dir / f"19_handbook/.augment/book/{cid}.mdx"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("---\ntitle: P\n---\n# Preface\nNew text.\n")
            elif s.shard_id.startswith("verify-book_rewrite-"):
                cid = s.shard_id.removeprefix("verify-book_rewrite-")
                p = run_dir / f"19_handbook/.augment/book_rewrite/{cid}.verification.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({"passed": True, "claims": [], "rejection_reason": None}))

    with patch("handbook_builder.dispatch.run_shards", side_effect=fake):
        pipeline.build(run_dir, milestone="M3", run_pnpm_build=False)

    mdx = run_dir / "19_handbook/src/content/docs/book/00_preface.mdx"
    assert mdx.exists()
    assert "New text." in mdx.read_text()
```

- [ ] **Step 2: Run test**

Expected: FAIL.

- [ ] **Step 3: Modify pipeline — add M3 block**

In `handbook_builder/pipeline.py`, replace the `raise NotImplementedError(f"milestone {milestone}...")` tail with:

```python
    # 19.4 rewrite book chapters
    from handbook_builder import book_rewrite as book_mod

    book_specs = book_mod.build_book_rewrite_specs(run_dir, topic=topic)
    dispatch.run_handbook_shards(
        run_dir, book_specs, max_workers=min(max_workers, 7), executor=executor
    )

    book_verify_specs = [
        verify_mod.build_verifier_spec(
            run_dir,
            kind="book_rewrite",
            target_id=s.shard_id.removeprefix("bookrewrite-"),
            original_path=f"14_chapters/book/{s.shard_id.removeprefix('bookrewrite-')}.md",
            candidate_path=f"19_handbook/.augment/book/{s.shard_id.removeprefix('bookrewrite-')}.mdx",
        )
        for s in book_specs
    ]
    dispatch.run_handbook_shards(
        run_dir, book_verify_specs, max_workers=min(max_workers, 7), executor=executor
    )

    for s in book_specs:
        cid = s.shard_id.removeprefix("bookrewrite-")
        verification = verify_mod.load_verification_result(
            run_dir / f"19_handbook/.augment/book_rewrite/{cid}.verification.json"
        )
        dst = docs_dir / "book" / f"{cid}.mdx"
        if not verification.passed:
            needs_review.append((f"book/{cid}", verification.rejection_reason or "unknown"))
            continue
        candidate = (run_dir / f"19_handbook/.augment/book/{cid}.mdx").read_text()
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(candidate)

    if needs_review:
        review = run_dir / "19_handbook/NEEDS_REVIEW.md"
        review.write_text(
            "# Pages skipped by verifier-web\n\n"
            + "\n".join(f"- `{p}` — {reason}" for p, reason in needs_review)
        )

    if milestone == "M3":
        if run_pnpm_build:
            from handbook_builder import build as build_step
            build_step.run_pnpm_build(run_dir)
        return

    raise NotImplementedError(f"milestone {milestone} not yet implemented")
```

- [ ] **Step 4: Run test**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add handbook_builder/pipeline.py tests/test_handbook_pipeline.py
git commit -m "feat: pipeline runs book-rewrite + verifier for M3"
```

---

## Task M3.4: M3 end-to-end smoke run

- [ ] **Step 1: Build M3 against a real run**

```bash
env PYTHONPATH=. uv run python scripts/build_handbook.py \
  research_runs/<run>/ --milestone M3 --max-workers 7
```

Expected: 7 book-chapter rewrites in `.augment/book/`; 7 verifier outputs; book chapter MDX files updated where passed.

- [ ] **Step 2: Citation parity check**

```bash
for f in research_runs/<run>/14_chapters/book/*.md; do
  cid=$(basename "$f" .md)
  orig=$(grep -oE '\[arxiv:[^]]+\]|\[[^]]+\]\([^)]+\)' "$f" | wc -l)
  new=$(grep -oE '\[arxiv:[^]]+\]|\[[^]]+\]\([^)]+\)' "research_runs/<run>/19_handbook/.augment/book/$cid.mdx" | wc -l)
  echo "$cid: original=$orig rewrite=$new"
done
```

Expected: counts match for every chapter.

- [ ] **Step 3: Preview**

```bash
cd research_runs/<run>/19_handbook && pnpm preview
```

Verify book chapters now have callouts and `<details>` collapsibles.

- [ ] **Step 4: Tag**

```bash
git tag handbook-m3
```

**M3 ship gate:** book chapters rewritten with preserved citations, no verifier rejections.

---

# Milestone M4 — Umbrella Site + Deployment

**Goal:** A repo-root `handbook/` Starlight site that lists every run with a card linking to its deployed site. GitHub Pages workflow.

## Task M4.1: Umbrella `handbook/` scaffold

**Files:**
- Create: `handbook/astro.config.mjs`
- Create: `handbook/package.json`
- Create: `handbook/src/content/docs/index.mdx`
- Create: `handbook/src/content/config.ts`
- Create: `handbook/src/styles/custom.css`
- Test: `tests/test_handbook_umbrella.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_handbook_umbrella.py`:

```python
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_umbrella_scaffold_exists():
    base = REPO_ROOT / "handbook"
    assert (base / "astro.config.mjs").exists()
    pkg = json.loads((base / "package.json").read_text())
    assert pkg["name"] == "swarn-handbook-umbrella"
    assert (base / "src/content/docs/index.mdx").exists()
    assert (base / "src/styles/custom.css").exists()
```

- [ ] **Step 2: Run test**

Expected: FAIL.

- [ ] **Step 3: Create `handbook/astro.config.mjs`**

```javascript
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  output: 'static',
  integrations: [
    starlight({
      title: 'Swarn Research Handbook',
      customCss: ['./src/styles/custom.css'],
      sidebar: [
        { label: 'Home', slug: 'index' },
        { label: 'Runs', autogenerate: { directory: 'runs' } },
      ],
    }),
  ],
});
```

- [ ] **Step 4: Create `handbook/package.json`**

```json
{
  "name": "swarn-handbook-umbrella",
  "type": "module",
  "version": "0.0.1",
  "scripts": {
    "dev": "astro dev",
    "build": "astro build",
    "preview": "astro preview"
  },
  "dependencies": {
    "astro": "5.4.0",
    "@astrojs/starlight": "0.30.5",
    "@astrojs/mdx": "4.0.6"
  }
}
```

- [ ] **Step 5: Create `handbook/src/content/docs/index.mdx`**

```mdx
---
title: Swarn Research Handbook
description: AI research handbooks generated by auto-research runs.
---

Browse the **Runs** section in the sidebar to read each handbook.

Each run is a self-contained, citation-grounded handbook for a single AI research topic, generated from arxiv papers and refined through a multi-agent pipeline.
```

- [ ] **Step 6: Create `handbook/src/content/config.ts`**

```typescript
import { defineCollection } from 'astro:content';
import { docsSchema } from '@astrojs/starlight/schema';

export const collections = {
  docs: defineCollection({ schema: docsSchema() }),
};
```

- [ ] **Step 7: Create `handbook/src/styles/custom.css`**

```css
:root {
  --sl-color-accent: #7aa2f7;
  --sl-color-bg: #1a1b26;
  --sl-color-text: #c0caf5;
}

.run-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 1rem;
  margin: 1.5rem 0;
}
```

- [ ] **Step 8: Run test**

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add handbook tests/test_handbook_umbrella.py
git commit -m "feat: umbrella handbook Astro Starlight scaffold"
```

---

## Task M4.2: Umbrella run-index generator

**Files:**
- Create: `scripts/regen_umbrella_index.py`
- Test: `tests/test_handbook_umbrella.py` (extend)

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_regen_umbrella_index_writes_pages(tmp_path):
    import importlib.util

    repo_clone = tmp_path / "repo"
    (repo_clone / "research_runs/run-1").mkdir(parents=True)
    (repo_clone / "research_runs/run-1/run_config.json").write_text(json.dumps({
        "run_id": "run-1", "topic": "Speech LMs", "created_at": "2026-05-13"
    }))
    (repo_clone / "research_runs/run-1/19_handbook/dist").mkdir(parents=True)
    (repo_clone / "research_runs/run-2/run_config.json").parent.mkdir(parents=True)
    (repo_clone / "research_runs/run-2/run_config.json").write_text(json.dumps({
        "run_id": "run-2", "topic": "Long Context", "created_at": "2026-05-09"
    }))
    (repo_clone / "handbook/src/content/docs/runs").mkdir(parents=True)

    spec = importlib.util.spec_from_file_location(
        "regen_um", REPO_ROOT / "scripts/regen_umbrella_index.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    mod.regenerate(repo_clone)

    runs_dir = repo_clone / "handbook/src/content/docs/runs"
    assert (runs_dir / "run-1.mdx").exists()
    assert (runs_dir / "run-2.mdx").exists()
    body = (runs_dir / "run-1.mdx").read_text()
    assert "Speech LMs" in body
    assert "Build status: built" in body or "✓ built" in body
    body2 = (runs_dir / "run-2.mdx").read_text()
    assert "Build status: pending" in body2 or "pending" in body2
```

- [ ] **Step 2: Run test**

Expected: FAIL.

- [ ] **Step 3: Create `scripts/regen_umbrella_index.py`**

```python
#!/usr/bin/env python3
"""Regenerate handbook/src/content/docs/runs/*.mdx from research_runs/*."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def regenerate(repo_root: Path) -> None:
    runs_root = repo_root / "research_runs"
    dst = repo_root / "handbook/src/content/docs/runs"
    dst.mkdir(parents=True, exist_ok=True)
    for run_dir in sorted(runs_root.iterdir()):
        if not run_dir.is_dir():
            continue
        config_path = run_dir / "run_config.json"
        if not config_path.exists():
            continue
        config = json.loads(config_path.read_text())
        run_id = config.get("run_id", run_dir.name)
        topic = config.get("topic", run_id)
        created_at = config.get("created_at", "")
        built = (run_dir / "19_handbook/dist").exists()
        status = "✓ built" if built else "pending"
        body = (
            f"---\ntitle: \"{topic}\"\ndescription: \"Run {run_id}\"\n---\n\n"
            f"**Run id:** `{run_id}`\n\n"
            f"**Created:** {created_at}\n\n"
            f"Build status: {status}\n\n"
            f"[Open run directory](/research_runs/{run_id}/19_handbook/dist/)\n"
        )
        (dst / f"{run_id}.mdx").write_text(body)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    regenerate(args.repo_root.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/regen_umbrella_index.py tests/test_handbook_umbrella.py
git commit -m "feat: regen_umbrella_index.py generates run cards under handbook/"
```

---

## Task M4.3: GitHub Pages deploy workflow

**Files:**
- Create: `.github/workflows/deploy-handbook.yml`

- [ ] **Step 1: Create the workflow**

```yaml
name: Deploy handbook

on:
  workflow_dispatch:
  push:
    branches: [main]
    paths:
      - 'handbook/**'
      - 'research_runs/**/19_handbook/dist/**'

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - uses: pnpm/action-setup@v3
        with: { version: '9' }
      - name: Regenerate run index
        run: python scripts/regen_umbrella_index.py
      - name: Build umbrella
        working-directory: handbook
        run: pnpm install --no-frozen-lockfile && pnpm build
      - name: Stage per-run dist directories
        run: |
          mkdir -p handbook/dist/runs
          for run_dist in research_runs/*/19_handbook/dist; do
            [ -d "$run_dist" ] || continue
            run_id=$(basename "$(dirname "$(dirname "$run_dist")")")
            cp -r "$run_dist" "handbook/dist/runs/$run_id"
          done
      - uses: actions/upload-pages-artifact@v3
        with: { path: handbook/dist }

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/deploy-pages@v4
        id: deployment
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/deploy-handbook.yml
git commit -m "ci: add GitHub Pages workflow for handbook umbrella + run sites"
```

---

## Task M4.4: Update docs + final smoke

**Files:**
- Modify: `README.md` (add handbook section)

- [ ] **Step 1: Append a "Web handbook" section to README.md**

```markdown
## Web handbook

After running the research pipeline, build the deployable handbook with:

\`\`\`bash
env PYTHONPATH=. uv run python scripts/build_handbook.py research_runs/<run>/ --milestone M3
\`\`\`

This produces `research_runs/<run>/19_handbook/dist/`, deployable as a static site. The umbrella index at `handbook/` lists every run; rebuild it with:

\`\`\`bash
python scripts/regen_umbrella_index.py
cd handbook && pnpm install && pnpm build
\`\`\`

The CI workflow `.github/workflows/deploy-handbook.yml` deploys everything to GitHub Pages on push to main.
```

- [ ] **Step 2: Run full test suite**

```bash
env PYTHONPATH=. uv run pytest tests/ -x --tb=short
```

Expected: all PASS.

- [ ] **Step 3: Tag**

```bash
git tag handbook-m4
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document web handbook build commands"
```

---

# Cross-cutting Tasks

## Task X.1: Idempotency cache (optional polish, ship with any milestone)

**Files:**
- Create: `handbook_builder/cache.py`
- Test: `tests/test_handbook_cache.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_handbook_cache.py`:

```python
import json
from pathlib import Path


def test_source_hash_manifest_roundtrip(tmp_path):
    from handbook_builder.cache import compute_source_hashes, load_manifest, write_manifest

    chapters = tmp_path / "14_chapters/methods"
    chapters.mkdir(parents=True)
    (chapters / "a.md").write_text("A")
    (chapters / "b.md").write_text("B")

    hashes = compute_source_hashes(tmp_path)
    assert set(hashes.keys()) == {"14_chapters/methods/a.md", "14_chapters/methods/b.md"}
    assert all(len(v) == 64 for v in hashes.values())  # sha256 hex

    manifest_path = tmp_path / "19_handbook/.cache/manifest.json"
    manifest_path.parent.mkdir(parents=True)
    write_manifest(manifest_path, hashes)
    assert load_manifest(manifest_path) == hashes


def test_changed_targets(tmp_path):
    from handbook_builder.cache import changed_targets

    old = {"methods/a.md": "h1", "methods/b.md": "h2"}
    new = {"methods/a.md": "h1", "methods/b.md": "DIFFERENT", "methods/c.md": "h3"}
    assert sorted(changed_targets(old, new)) == ["methods/b.md", "methods/c.md"]
```

- [ ] **Step 2: Run test**

Expected: FAIL.

- [ ] **Step 3: Implement `handbook_builder/cache.py`**

```python
"""Source-hash manifest for Stage 19 idempotency."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def compute_source_hashes(run_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for kind in ("book", "families", "methods"):
        base = run_dir / "14_chapters" / kind
        if not base.exists():
            continue
        for md in base.rglob("*.md"):
            key = str(md.relative_to(run_dir))
            out[key] = hashlib.sha256(md.read_bytes()).hexdigest()
    return out


def load_manifest(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def write_manifest(path: Path, manifest: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True))


def changed_targets(old: dict[str, str], new: dict[str, str]) -> list[str]:
    return [key for key, h in new.items() if old.get(key) != h]
```

- [ ] **Step 4: Run test**

Expected: PASS.

- [ ] **Step 5: Wire into pipeline (optional)**

In `handbook_builder/pipeline.py`, at the end of each milestone block, before pnpm build:

```python
    from handbook_builder import cache as cache_mod
    manifest_path = run_dir / "19_handbook/.cache/manifest.json"
    cache_mod.write_manifest(manifest_path, cache_mod.compute_source_hashes(run_dir))
```

Earlier (before dispatch), read the old manifest and filter `method_ids` / `book_specs` to changed ones unless `--rebuild-all` is passed. Implementation parallel to the manifest pattern in Stage 14.

- [ ] **Step 6: Commit**

```bash
git add handbook_builder/cache.py tests/test_handbook_cache.py
git commit -m "feat: handbook_builder.cache for stage-19 idempotency"
```

---

## Self-Review (run before handoff)

After all tasks are written above, this section captures the review checks the planner ran. **No action needed unless following up on a noted gap.**

**1. Spec coverage:**
- Scaffold (M0.1–M0.10) ✓
- Glossary (M1.1–M1.2) ✓
- Diagrams (M1.3–M1.4) ✓
- Method TLDR augmentation (M2.1, M2.4, M2.5) ✓
- Verifier-web gating (M2.2, M2.3) ✓
- Book chapter rewrite (M3.1–M3.3) ✓
- Umbrella site (M4.1, M4.2) ✓
- Deployment (M4.3) ✓
- Idempotency cache (X.1) ✓
- NEEDS_REVIEW.md fallback (M2.5, M3.3) ✓

**2. Placeholder scan:** Each step contains the actual file content or command, no "TBD" or "implement later". Confirmed.

**3. Type consistency:** `ShardSpec` reused from `scripts.run_auto_research` throughout; `VerificationResult` dataclass defined once in `verify.py`; `Milestone` Literal defined once in `pipeline.py`; component imports (`Tldr`, `KeyIdea`, `Diagram`, `Term`) match between `Tldr.astro` + `splice_tldr` + skill examples.

**4. Ambiguity check:** All file paths absolute or stated relative to `run_dir`. The `outline.json` schema is referenced by multiple tasks — they all access `families[]`, `methods[]`, `book_sections[]` which match the existing pipeline's contract.
