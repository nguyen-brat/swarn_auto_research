# Auto Research MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Codex-native auto-research pipeline that produces one verified handbook chapter from a topic, expanding the paper pool only for important unknown concepts.

**Architecture:** One orchestrator skill in `.agents/skills/auto-research-orchestrator/SKILL.md` walks the MVP stages 0→13 in order. Each stage delegates to a narrow Codex subagent declared in `.codex/agents/*.toml` whose system prompt loads a matching `SKILL.md`. Subagents call the existing MCP tools plus two new ones (`get_alphaxiv_overview`, `get_paper_metadata`) and write JSON/CSV artifacts under `research_runs/{slug}-{ts}/`. No new Python pipeline scripts.

**Tech Stack:** Python 3.13, FastMCP (`mcp>=1.0`), Codex CLI agents (TOML), JSON/CSV, existing services in `swarn_research_mcp/services/`.

**Spec:** `docs/superpowers/specs/2026-05-08-auto-research-mvp-design.md`

---

## File Structure

### New files (created by this plan)

```
.agents/
├── knowledge_base.md                            # seeded KB (was empty file)
└── skills/
    ├── auto-research-orchestrator/SKILL.md      # main pipeline
    ├── knowledge-base-reading/SKILL.md
    ├── weak-evidence-extraction/SKILL.md
    ├── weak-graph-extraction/SKILL.md
    ├── knowledge-gap-detection/SKILL.md
    ├── paper-pool-expansion/SKILL.md
    ├── pageindex-building/SKILL.md
    ├── chapter-writing/SKILL.md
    └── verification/SKILL.md

.codex/
├── config.toml                                  # MCP registration + agent limits
└── agents/
    ├── knowledge_base_reader.toml
    ├── weak_evidence_extractor.toml
    ├── weak_graph_extractor.toml
    ├── knowledge_gap_detector.toml
    ├── paper_expander.toml
    ├── paper_ranker.toml
    ├── paper_indexer.toml
    ├── chapter_writer.toml
    └── verifier.toml

tests/
└── test_server.py                               # MODIFIED — add MCP tool tests
```

### Modified files

- `swarn_research_mcp/server.py` — register 2 new MCP tools.
- `swarn_research_mcp/tools/paper_search.py` — add 2 thin async wrappers (`get_alphaxiv_overview`, `get_paper_metadata`) that call existing service helpers.

### Generated per run (not in repo)

```
research_runs/{topic_slug}-{YYYYMMDD-HHMMSS}/  # ignored via .gitignore
```

---

## Task 1: Bootstrap directories and seed knowledge base

**Files:**
- Create dir: `.agents/skills/`
- Create dir: `.codex/agents/`
- Modify: `.agents/knowledge_base.md` (currently empty)
- Modify: `.gitignore` (add `research_runs/*/`)

- [ ] **Step 1: Create skill and agent directories**

```bash
mkdir -p .agents/skills/auto-research-orchestrator
mkdir -p .agents/skills/knowledge-base-reading
mkdir -p .agents/skills/weak-evidence-extraction
mkdir -p .agents/skills/weak-graph-extraction
mkdir -p .agents/skills/knowledge-gap-detection
mkdir -p .agents/skills/paper-pool-expansion
mkdir -p .agents/skills/pageindex-building
mkdir -p .agents/skills/chapter-writing
mkdir -p .agents/skills/verification
mkdir -p .codex/agents
```

- [ ] **Step 2: Seed `.agents/knowledge_base.md`**

Write this exact content to `.agents/knowledge_base.md`:

```markdown
# User Knowledge Base

Concepts the user already knows. The auto-research system reads this
file to decide which concepts need explanation. Edit by hand; the
research run never modifies it.

## Core LLM Concepts
- Large Language Model
- Transformer
- Self-attention
- Multi-head attention
- Token
- Tokenizer
- Context window
- Embeddings
- Positional encoding

## Training & Fine-tuning
- Pretraining
- Supervised fine-tuning
- Instruction tuning
- LoRA
- RLHF

## Vision Basics
- Convolutional neural network
- ResNet
- Image classification
- Image embeddings

## Retrieval & Generation
- Retrieval-augmented generation
- Vector database
- Cosine similarity

## Evaluation Basics
- Accuracy
- F1 score
- BLEU
- Perplexity
```

- [ ] **Step 3: Update `.gitignore` to skip generated run folders**

Append to `.gitignore`:

```
research_runs/*/
!research_runs/.gitkeep
```

- [ ] **Step 4: Add `research_runs/.gitkeep`**

```bash
touch research_runs/.gitkeep
```

- [ ] **Step 5: Commit**

```bash
git add .agents .codex .gitignore research_runs/.gitkeep
git commit -m "scaffold: dirs for codex agents/skills and seed knowledge base"
```

---

## Task 2: Add `get_alphaxiv_overview` MCP tool (TDD)

**Files:**
- Modify: `swarn_research_mcp/tools/paper_search.py`
- Modify: `swarn_research_mcp/server.py:30-57` (extend `MCP_TOOL_SPECS`)
- Test: `tests/test_server.py`

The existing service `swarn_research_mcp/services/alphaxiv.py:23` already exposes `get_alphaxiv_overview_markdown(arxiv_id) -> str`. We only need a tool wrapper that returns a structured dict (so MCP clients see arxiv_id alongside markdown).

- [ ] **Step 1: Read the current `tests/test_server.py` to confirm existing test style**

```bash
sed -n '1,40p' tests/test_server.py
```

- [ ] **Step 2: Write the failing test**

Append this to `tests/test_server.py`:

```python
def test_alphaxiv_overview_tool_registered():
    from swarn_research_mcp.server import MCP_TOOL_SPECS
    names = [spec.function.__name__ for spec in MCP_TOOL_SPECS]
    assert "get_alphaxiv_overview" in names


def test_alphaxiv_overview_returns_arxiv_id_and_markdown(monkeypatch):
    import asyncio
    from swarn_research_mcp.tools import paper_search

    async def fake_overview(arxiv_id: str) -> str:
        assert arxiv_id == "2304.08485"
        return "# LLaVA overview\n\nVisual instruction tuning."

    monkeypatch.setattr(
        paper_search,
        "get_alphaxiv_overview_markdown",
        fake_overview,
    )

    result = asyncio.run(paper_search.get_alphaxiv_overview("2304.08485"))
    assert result == {
        "arxiv_id": "2304.08485",
        "markdown": "# LLaVA overview\n\nVisual instruction tuning.",
    }
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_server.py::test_alphaxiv_overview_tool_registered tests/test_server.py::test_alphaxiv_overview_returns_arxiv_id_and_markdown -v`
Expected: FAIL — `AttributeError: module 'swarn_research_mcp.tools.paper_search' has no attribute 'get_alphaxiv_overview'`.

- [ ] **Step 4: Implement the wrapper in `swarn_research_mcp/tools/paper_search.py`**

Add this near the other tool functions (search the file for existing `get_paper_markdown` to find the right location). Add the import at top of file if not present.

```python
from swarn_research_mcp.services.alphaxiv import (
    get_alphaxiv_overview_markdown,
)


async def get_alphaxiv_overview(arxiv_id: str) -> dict[str, str]:
    """Fetch the alphaXiv overview Markdown for an arXiv paper.

    Returns a dict with arxiv_id and markdown so MCP clients can
    persist both fields without re-deriving them.
    """
    markdown = await get_alphaxiv_overview_markdown(arxiv_id)
    return {"arxiv_id": arxiv_id, "markdown": markdown}
```

- [ ] **Step 5: Register the tool in `swarn_research_mcp/server.py`**

In `server.py`, extend the imports at line 13:

```python
from swarn_research_mcp.tools.paper_search import (
    bulk_normal_start_search,
    get_alphaxiv_overview,
    get_paper_markdown,
    get_paper_section,
)
```

Append a new `MCPToolSpec` to the `MCP_TOOL_SPECS` tuple at line 30. Insert before the closing `)`:

```python
    MCPToolSpec(
        function=get_alphaxiv_overview,
        description=(
            "Fetch the alphaXiv overview Markdown for an arXiv paper by arXiv ID. "
            "Returns a dict with arxiv_id and markdown. Use during cheap enrichment "
            "before fetching the full paper."
        ),
    ),
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_server.py::test_alphaxiv_overview_tool_registered tests/test_server.py::test_alphaxiv_overview_returns_arxiv_id_and_markdown -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add swarn_research_mcp/tools/paper_search.py swarn_research_mcp/server.py tests/test_server.py
git commit -m "feat(mcp): add get_alphaxiv_overview tool"
```

---

## Task 3: Add `get_paper_metadata` MCP tool (TDD)

**Files:**
- Modify: `swarn_research_mcp/tools/paper_search.py`
- Modify: `swarn_research_mcp/server.py`
- Test: `tests/test_server.py`

The existing `swarn_research_mcp/services/semantic_scholar.py` exposes `paper_batch([arxiv_id])` which calls `POST /paper/batch`. We wrap it for a single paper and return a flat metadata dict.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_server.py`:

```python
def test_paper_metadata_tool_registered():
    from swarn_research_mcp.server import MCP_TOOL_SPECS
    names = [spec.function.__name__ for spec in MCP_TOOL_SPECS]
    assert "get_paper_metadata" in names


def test_paper_metadata_returns_flat_dict(monkeypatch):
    import asyncio
    from swarn_research_mcp.tools import paper_search

    async def fake_paper_batch(paper_ids):
        assert paper_ids == ["2304.08485"]
        return [{
            "arxiv_id": "2304.08485",
            "scholar_semantic_id": "abc123",
            "abstract": "We present LLaVA...",
            "citations": ["2103.00020"],
            "citationCount": 1234,
            "references": [],
            "referenceCount": 0,
        }]

    monkeypatch.setattr(paper_search, "paper_batch", fake_paper_batch)

    result = asyncio.run(paper_search.get_paper_metadata("2304.08485"))
    assert result["arxiv_id"] == "2304.08485"
    assert result["scholar_semantic_id"] == "abc123"
    assert result["citationCount"] == 1234
    assert result["abstract"].startswith("We present")


def test_paper_metadata_returns_empty_when_not_found(monkeypatch):
    import asyncio
    from swarn_research_mcp.tools import paper_search

    async def fake_paper_batch(paper_ids):
        return []

    monkeypatch.setattr(paper_search, "paper_batch", fake_paper_batch)

    result = asyncio.run(paper_search.get_paper_metadata("9999.99999"))
    assert result == {"arxiv_id": "9999.99999", "found": False}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_server.py::test_paper_metadata_tool_registered tests/test_server.py::test_paper_metadata_returns_flat_dict tests/test_server.py::test_paper_metadata_returns_empty_when_not_found -v`
Expected: FAIL — `AttributeError: ... no attribute 'get_paper_metadata'`.

- [ ] **Step 3: Implement the wrapper in `swarn_research_mcp/tools/paper_search.py`**

Add the import at the top of the file if not present:

```python
from swarn_research_mcp.services.semantic_scholar import paper_batch
```

Add the function near `get_alphaxiv_overview`:

```python
async def get_paper_metadata(arxiv_id: str) -> dict:
    """Fetch Semantic Scholar metadata for one arXiv paper.

    Returns a flat dict with abstract, citation/reference counts, and
    linked arxiv IDs. Returns {"arxiv_id": ..., "found": False} when
    Semantic Scholar has no record for the ID.
    """
    rows = await paper_batch([arxiv_id])
    if not rows:
        return {"arxiv_id": arxiv_id, "found": False}
    row = rows[0]
    row.setdefault("arxiv_id", arxiv_id)
    return row
```

- [ ] **Step 4: Register the tool in `swarn_research_mcp/server.py`**

Extend the imports:

```python
from swarn_research_mcp.tools.paper_search import (
    bulk_normal_start_search,
    get_alphaxiv_overview,
    get_paper_markdown,
    get_paper_metadata,
    get_paper_section,
)
```

Append to `MCP_TOOL_SPECS` (after the alphaXiv entry):

```python
    MCPToolSpec(
        function=get_paper_metadata,
        description=(
            "Fetch Semantic Scholar metadata for one arXiv paper by arXiv ID. "
            "Returns abstract, citationCount, referenceCount, and arxiv IDs of "
            "direct citations and references. Returns {arxiv_id, found: false} "
            "when the paper is not in Semantic Scholar."
        ),
    ),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_server.py -v -k "metadata or alphaxiv"`
Expected: all metadata + alphaxiv tests pass.

- [ ] **Step 6: Commit**

```bash
git add swarn_research_mcp/tools/paper_search.py swarn_research_mcp/server.py tests/test_server.py
git commit -m "feat(mcp): add get_paper_metadata tool"
```

---

## Task 4: Write `.codex/config.toml`

**Files:**
- Create: `.codex/config.toml`

This config registers the local MCP server and sets agent limits the orchestrator skill relies on.

- [ ] **Step 1: Create `.codex/config.toml`**

```toml
# Codex project config for swarn_auto_research
# Loaded automatically when running `codex` from this repo root.

[mcp_servers.swarn-auto-research]
command = "uv"
args = ["run", "swarn-auto-research-mcp"]

# Per-agent limits used by the auto-research-orchestrator skill.
# These mirror the MVP budgets in run_config.json.
[agents.limits]
max_seed_papers = 50
max_expansion_gaps = 5
max_papers_per_gap = 3
max_expansion_rounds = 1
max_promoted_papers = 10
min_gap_importance = 0.70
min_confusion_risk = "medium"
```

- [ ] **Step 2: Commit**

```bash
git add .codex/config.toml
git commit -m "config: register MCP server and MVP budgets in .codex/config.toml"
```

---

## Task 5: Write `knowledge-base-reading` skill and `knowledge_base_reader` agent

**Files:**
- Create: `.agents/skills/knowledge-base-reading/SKILL.md`
- Create: `.codex/agents/knowledge_base_reader.toml`

- [ ] **Step 1: Write `.agents/skills/knowledge-base-reading/SKILL.md`**

```markdown
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
```

- [ ] **Step 2: Write `.codex/agents/knowledge_base_reader.toml`**

```toml
name = "knowledge_base_reader"
description = "Parse the shared knowledge base into known_concepts_snapshot.json."
model = "gpt-5.4"
allowed_mcp_tools = []

system_prompt = """
You are knowledge_base_reader. Follow the rules in
.agents/skills/knowledge-base-reading/SKILL.md exactly.

Inputs you receive from the orchestrator:
- run_id (the research run folder name)
- knowledge_base_path (default: .agents/knowledge_base.md)

You must:
1. Read the knowledge base file.
2. Build the JSON snapshot per the skill schema.
3. Write it to research_runs/{run_id}/06_expansion/known_concepts_snapshot.json.
4. Return a one-line status: 'ok: N concepts, M categories'.

Do not modify the knowledge base file. Do not perform web searches.
"""
```

- [ ] **Step 3: Commit**

```bash
git add .agents/skills/knowledge-base-reading .codex/agents/knowledge_base_reader.toml
git commit -m "skill+agent: knowledge_base_reader"
```

---

## Task 6: Write `weak-evidence-extraction` skill and `weak_evidence_extractor` agent

**Files:**
- Create: `.agents/skills/weak-evidence-extraction/SKILL.md`
- Create: `.codex/agents/weak_evidence_extractor.toml`

- [ ] **Step 1: Write `.agents/skills/weak-evidence-extraction/SKILL.md`**

```markdown
---
name: weak-evidence-extraction
description: Cheap first-pass extraction of paper structure from abstract, alphaXiv overview, and Semantic Scholar metadata.
---

# Weak Evidence Extraction

## Goal
Produce one weak-evidence card per paper without reading full Markdown.

## Inputs
- `02_paper_pool/paper_pool.json` (arxiv_id → abstract)
- alphaXiv overview Markdown (via MCP `get_alphaxiv_overview`)
- Semantic Scholar metadata (via MCP `get_paper_metadata`)

## Outputs
- `03_overviews/alphaxiv_overviews/{arxiv_id}.json` — raw overview
- `03_overviews/semantic_scholar/{arxiv_id}.json` — raw metadata
- `04_weak_evidence/{arxiv_id}.json` — extracted card

## Rules
- Call MCP tools at most once per paper. If a call fails, log and continue with what is available.
- Mark `trust_level` as `OVERVIEW_DERIVED` when overview was used, `REPORT_DERIVED` when only metadata + abstract were available.
- The `reader_needed_concepts` field is the most important. List concepts a reader must understand to follow the paper. Aim for 5–15 concepts.
- Do not invent claims. If a field is unknown, use an empty list.
- Output valid JSON.

## Output schema (per paper)
```json
{
  "arxiv_id": "2304.08485",
  "title": "",
  "year": 0,
  "trust_level": "OVERVIEW_DERIVED",
  "paper_type": "method | benchmark | dataset | survey | application | theory | unknown",
  "topic_tags": [],
  "problem": [],
  "solution": [],
  "methods": [],
  "datasets": [],
  "benchmarks": [],
  "metrics": [],
  "baselines": [],
  "results": [],
  "limitations": [],
  "mentioned_entities": [],
  "mentioned_papers": [],
  "reader_needed_concepts": [],
  "book_usage": {
    "possible_chapters": [],
    "role": "core | support | benchmark | dataset | background | limitation | exclude",
    "importance_score_1_to_5": 0
  }
}
```

## Success check
- One file in `04_weak_evidence/` per paper in `paper_pool.json`.
- Every file has non-empty `reader_needed_concepts` (or an explicit empty list with `paper_type: unknown` if extraction completely failed).
```

- [ ] **Step 2: Write `.codex/agents/weak_evidence_extractor.toml`**

```toml
name = "weak_evidence_extractor"
description = "Cheap first-pass extraction of paper structure with reader_needed_concepts."
model = "gpt-5.4"
allowed_mcp_tools = ["get_alphaxiv_overview", "get_paper_metadata"]

system_prompt = """
You are weak_evidence_extractor. Follow
.agents/skills/weak-evidence-extraction/SKILL.md exactly.

Inputs from orchestrator:
- run_id
- arxiv_ids: list of paper IDs to process

For each arxiv_id:
1. Fetch alphaXiv overview via get_alphaxiv_overview(arxiv_id). On failure, log and continue.
2. Fetch metadata via get_paper_metadata(arxiv_id). On failure, log and continue.
3. Save raw responses under 03_overviews/.
4. Build the weak-evidence card per the skill schema and save to 04_weak_evidence/{arxiv_id}.json.

Do NOT use get_paper_markdown — that is reserved for promoted papers only.
Do NOT make claims that are not supported by the abstract/overview/metadata.
Return a one-line status: 'ok: N processed, M failed'.
"""
```

- [ ] **Step 3: Commit**

```bash
git add .agents/skills/weak-evidence-extraction .codex/agents/weak_evidence_extractor.toml
git commit -m "skill+agent: weak_evidence_extractor"
```

---

## Task 7: Write `weak-graph-extraction` skill and `weak_graph_extractor` agent

**Files:**
- Create: `.agents/skills/weak-graph-extraction/SKILL.md`
- Create: `.codex/agents/weak_graph_extractor.toml`

- [ ] **Step 1: Write `.agents/skills/weak-graph-extraction/SKILL.md`**

```markdown
---
name: weak-graph-extraction
description: Build weak knowledge-graph fragments from weak evidence cards.
---

# Weak Graph Extraction

## Goal
Turn weak-evidence cards into a graph fragment per paper plus a merged global graph.

## Inputs
- `04_weak_evidence/*.json`

## Outputs
- `05_weak_graph/fragments/{arxiv_id}.json`
- `05_weak_graph/weak_global_graph.json`

## Node types
Paper, Problem, Concept, Method, MethodFamily, Dataset, Benchmark, Metric, Claim, Result, Limitation, Application, OpenProblem, Codebase.

## Edge types
INTRODUCES, USES, USES_DATASET, EVALUATES_ON, MEASURES_WITH, COMPARES_TO, IMPROVES_OVER, HAS_RESULT, HAS_LIMITATION, SOLVES, EXTENDS, MENTIONS, RELATED_TO, BELONGS_TO, CITES, CONTRADICTS.

## Rules
- Use weak evidence only. Mark every edge with `confidence: "weak"`.
- A node ID is the normalized concept name (lowercase, no punctuation). Paper nodes use the arXiv ID.
- Merge fragments into the global graph by deduping nodes via normalized ID and unioning edges.
- When two fragments contradict, keep both edges (the verifier handles conflicts later).
- Do not invent edges that are not directly stated in the evidence card.

## Output schema
```json
{
  "nodes": [
    {"id": "clip-vision-encoder", "type": "Method", "display": "CLIP vision encoder"}
  ],
  "edges": [
    {"src": "2304.08485", "dst": "clip-vision-encoder", "type": "USES", "confidence": "weak"}
  ]
}
```

## Success check
- Every edge endpoint exists in the node set.
- `weak_global_graph.json` is valid JSON.
- No edge has `confidence` other than `weak` or `inferred`.
```

- [ ] **Step 2: Write `.codex/agents/weak_graph_extractor.toml`**

```toml
name = "weak_graph_extractor"
description = "Build weak graph fragments and a merged weak global graph."
model = "gpt-5.4"
allowed_mcp_tools = []

system_prompt = """
You are weak_graph_extractor. Follow
.agents/skills/weak-graph-extraction/SKILL.md exactly.

Inputs from orchestrator:
- run_id

Steps:
1. Read all 04_weak_evidence/*.json under research_runs/{run_id}/.
2. For each card, build a fragment and write 05_weak_graph/fragments/{arxiv_id}.json.
3. Merge into 05_weak_graph/weak_global_graph.json (dedupe nodes by id, union edges).

Use weak evidence only. Mark every edge confidence as 'weak'.
Return a one-line status: 'ok: N fragments, K nodes, E edges in global'.
"""
```

- [ ] **Step 3: Commit**

```bash
git add .agents/skills/weak-graph-extraction .codex/agents/weak_graph_extractor.toml
git commit -m "skill+agent: weak_graph_extractor"
```

---

## Task 8: Write `knowledge-gap-detection` skill and `knowledge_gap_detector` agent

**Files:**
- Create: `.agents/skills/knowledge-gap-detection/SKILL.md`
- Create: `.codex/agents/knowledge_gap_detector.toml`

- [ ] **Step 1: Write `.agents/skills/knowledge-gap-detection/SKILL.md`**

```markdown
---
name: knowledge-gap-detection
description: Compare paper-required concepts against the user's known concepts and emit a knowledge_gap_report.
---

# Knowledge Gap Detection

## Goal
Decide which unknown concepts are important enough to drive paper-pool expansion.

## Inputs
- `06_expansion/known_concepts_snapshot.json`
- `04_weak_evidence/*.json`
- `05_weak_graph/weak_global_graph.json`

## Outputs
- `06_expansion/extracted_concepts.json`
- `06_expansion/knowledge_gap_report.json`
- `06_expansion/expansion_need_queue.json`

## Rules
- Concept matching uses the normalized form. Use the `aliases` map in `known_concepts_snapshot.json`.
- For every concept extracted from `reader_needed_concepts` and graph nodes, classify as one of:
  - `known` — matches a known concept or alias.
  - `unknown_minor` — unknown but only mentioned in passing, dataset/benchmark name with no central role, or trivially explainable in one sentence.
  - `knowledge_gap` — unknown AND important AND its absence would confuse the reader.
- Compute `importance` per concept based on:
  - appears in core paper (importance_score_1_to_5 ≥ 4)
  - appears in title/abstract/solution/result/methods
  - mentioned by ≥ 2 papers
  - is a method/dataset/benchmark/baseline used by a core paper
  - bridges multiple graph communities
- Hard cap: pick the top 5 knowledge gaps for the expansion queue regardless of how many qualify (MVP budget).
- Every queue item must include search queries and `max_papers_to_add` (default 3).

## Output schema for `expansion_need_queue.json`
```json
{
  "items": [
    {
      "gap_id": "gap_clip_vision_encoder",
      "concept": "CLIP vision encoder",
      "priority": 0.91,
      "needed_for_papers": ["2304.08485"],
      "needed_for_chapters": ["Large Multimodal Model Architecture"],
      "search_queries": [
        "CLIP vision encoder arxiv",
        "Contrastive Language Image Pretraining CLIP paper"
      ],
      "target_paper_types": ["foundational method", "survey/background"],
      "max_papers_to_add": 3
    }
  ]
}
```

## Success check
- `knowledge_gap_report.json` has three buckets: `known`, `unknown_minor`, `knowledge_gaps`.
- `expansion_need_queue.json.items` length ≤ 5.
- Every queue item has `search_queries` (≥ 2) and `max_papers_to_add` ≤ 3.
```

- [ ] **Step 2: Write `.codex/agents/knowledge_gap_detector.toml`**

```toml
name = "knowledge_gap_detector"
description = "Detect important unknown concepts that warrant paper-pool expansion."
model = "gpt-5.4"
allowed_mcp_tools = []

system_prompt = """
You are knowledge_gap_detector. Follow
.agents/skills/knowledge-gap-detection/SKILL.md exactly.

Inputs from orchestrator:
- run_id

Read known_concepts_snapshot.json, all weak evidence cards, and the weak
global graph. Classify every concept. Output extracted_concepts.json,
knowledge_gap_report.json, and expansion_need_queue.json under
research_runs/{run_id}/06_expansion/.

MVP cap: at most 5 items in expansion_need_queue.json.items.
Every gap in the queue must have priority >= 0.70.

Return a one-line status: 'ok: K known, U minor, G gaps, Q queued'.
"""
```

- [ ] **Step 3: Commit**

```bash
git add .agents/skills/knowledge-gap-detection .codex/agents/knowledge_gap_detector.toml
git commit -m "skill+agent: knowledge_gap_detector"
```

---

## Task 9: Write `paper-pool-expansion` skill and `paper_expander` agent

**Files:**
- Create: `.agents/skills/paper-pool-expansion/SKILL.md`
- Create: `.codex/agents/paper_expander.toml`

- [ ] **Step 1: Write `.agents/skills/paper-pool-expansion/SKILL.md`**

```markdown
---
name: paper-pool-expansion
description: Expand the paper pool only to cover important unknown concepts.
---

# Paper Pool Expansion

## Goal
For each item in the expansion queue, find a small number of foundational papers that explain the unknown concept, and add only the accepted ones to the pool.

## Inputs
- `06_expansion/expansion_need_queue.json`
- `02_paper_pool/paper_pool.json` (to dedupe)

## Outputs
- `06_expansion/expansion_round_01.json` — full search log for the round
- `06_expansion/accepted_candidates.csv`
- `06_expansion/rejected_candidates.csv`
- updated `02_paper_pool/paper_pool.json` and `02_paper_pool/paper_pool.csv`

## Rules
- Run exactly ONE expansion round in MVP.
- For each queue item, run `bulk_normal_start_search` with the item's `search_queries`.
- Accept a candidate only if ALL hold:
  - directly explains the unknown concept (foundational paper, survey, or canonical reference)
  - has an arXiv ID
  - is not already in the pool
  - is needed to understand a key paper in the run
- Reject if loosely related, application-specific, duplicate, or low relevance.
- Cap: at most `max_papers_to_add` papers per gap (default 3). Stop early when reached.
- Total cap across the round: ≤ 15 new papers (5 gaps × 3 papers).
- Every accepted paper record must include `added_for_gap` and `why_needed`.

## Accepted CSV columns
```
arxiv_id,gap_id,unknown_concept,title,candidate_role,score,why_needed
```

## Pool record extension for expansion papers
```json
{
  "arxiv_id": "2103.00020",
  "status": "DISCOVERED",
  "source": "knowledge_gap_expansion",
  "added_for_gap": "CLIP vision encoder",
  "needed_by_papers": ["2304.08485"],
  "candidate_role": "foundational",
  "abstract": "...",
  "expansion_round": 1
}
```

## Success check
- `accepted_candidates.csv` and `rejected_candidates.csv` exist.
- Updated `paper_pool.json` has no duplicate arxiv_ids.
- Every new paper has `added_for_gap` and `why_needed`.
- Total new papers ≤ 15.
```

- [ ] **Step 2: Write `.codex/agents/paper_expander.toml`**

```toml
name = "paper_expander"
description = "Search for foundational papers per knowledge gap and update the paper pool."
model = "gpt-5.4"
allowed_mcp_tools = ["bulk_normal_start_search", "get_paper_metadata"]

system_prompt = """
You are paper_expander. Follow
.agents/skills/paper-pool-expansion/SKILL.md exactly.

Inputs from orchestrator:
- run_id

Steps:
1. Load expansion_need_queue.json and existing paper_pool.json.
2. For each queue item, call bulk_normal_start_search with the search_queries
   (positive_keywords from the concept terms, negative_keywords empty).
   Use a small per-query limit so total work stays bounded.
3. For each result, decide accept/reject per skill rules.
4. Write expansion_round_01.json with full audit trail.
5. Write accepted_candidates.csv and rejected_candidates.csv.
6. Update paper_pool.json/csv with accepted papers (status=DISCOVERED,
   source=knowledge_gap_expansion, plus added_for_gap and why_needed).

Hard caps:
- ≤ 5 gaps processed
- ≤ 3 accepted papers per gap
- ≤ 15 new papers total in this round
- exactly 1 round

Return a one-line status: 'ok: A accepted, R rejected, P pool size after'.
"""
```

- [ ] **Step 3: Commit**

```bash
git add .agents/skills/paper-pool-expansion .codex/agents/paper_expander.toml
git commit -m "skill+agent: paper_expander"
```

---

## Task 10: Write `paper_ranker` agent (no separate skill)

**Files:**
- Create: `.codex/agents/paper_ranker.toml`

Ranking is purely arithmetic over fields the other agents already produced; we put the formula directly in the agent prompt instead of creating a one-off skill.

- [ ] **Step 1: Write `.codex/agents/paper_ranker.toml`**

```toml
name = "paper_ranker"
description = "Score every paper, apply the knowledge-gap boost, and promote the top N."
model = "gpt-5.4"
allowed_mcp_tools = []

system_prompt = """
You are paper_ranker. Compute a score per paper and pick the top 10
papers to promote (MVP cap).

Inputs from orchestrator:
- run_id

Read:
- 02_paper_pool/paper_pool.json
- 04_weak_evidence/*.json
- 05_weak_graph/weak_global_graph.json
- 06_expansion/knowledge_gap_report.json

Score formula (clamp each component to [0,1]):
  final_score =
      0.35 * topic_relevance
    + 0.20 * graph_centrality
    + 0.15 * citation_or_influence
    + 0.10 * recency
    + 0.10 * implementation_impact
    + 0.10 * chapter_need

Then add a knowledge_gap_boost of up to +0.20 if ALL hold:
  - paper.source == 'knowledge_gap_expansion'
  - the gap it covers has priority >= 0.70
  - paper.candidate_role in {'foundational', 'survey'}

Definitions:
  - topic_relevance: how directly the paper addresses the run topic. Use weak evidence importance_score_1_to_5 / 5.
  - graph_centrality: degree of the paper node in weak_global_graph divided by max degree.
  - citation_or_influence: log1p(citationCount) / log1p(10000), default 0 if unknown.
  - recency: clamp((year - 2018) / 8, 0, 1), default 0.5 if unknown.
  - implementation_impact: 1 if paper introduces a method/codebase used by another paper in the pool, else 0.
  - chapter_need: 1 if the paper is a core/support entry for the dominant graph community, else 0.5 if support, else 0.

Outputs to research_runs/{run_id}/07_scoring/:
- paper_scores.csv with columns:
    arxiv_id,topic_relevance,graph_centrality,citation_or_influence,recency,implementation_impact,chapter_need,knowledge_gap_boost,final_score
- promotion_candidates.csv: top 20 sorted by final_score
- promoted_papers.json: top 10 with this schema:
    {"arxiv_id": "", "final_score": 0.0, "reason": "<one sentence>", "is_gap_paper": bool}

Return a one-line status: 'ok: P scored, 10 promoted'.
"""
```

- [ ] **Step 2: Commit**

```bash
git add .codex/agents/paper_ranker.toml
git commit -m "agent: paper_ranker"
```

---

## Task 11: Write `pageindex-building` skill and `paper_indexer` agent

**Files:**
- Create: `.agents/skills/pageindex-building/SKILL.md`
- Create: `.codex/agents/paper_indexer.toml`

- [ ] **Step 1: Write `.agents/skills/pageindex-building/SKILL.md`**

```markdown
---
name: pageindex-building
description: Build a section tree and node map from a full paper Markdown.
---

# PageIndex Building

## Goal
Let downstream agents find sections by ID without scanning the whole paper.

## Inputs
- `08_full_markdown/{arxiv_id}.md`

## Outputs
- `09_pageindex/trees/{arxiv_id}.tree.json` — nested section tree
- `09_pageindex/nodes/{arxiv_id}.nodes.json` — flat node map keyed by stable ID

## Rules
- Parse Markdown headings (`#`, `##`, `###`, ...).
- Stable node ID format: `s` + zero-padded path indices (e.g. `s.01.03.02`).
- Each node records: `id`, `title`, `level`, `start_line`, `end_line`, `parent_id`, `summary` (≤ 240 chars).
- `start_line` / `end_line` are 1-based line numbers in the source Markdown.
- The tree is the root container with a `children` array; leaves have `children: []`.
- Summaries are mechanical: use the first non-heading sentence under that section. Do not interpret beyond that.

## Output schema (tree.json)
```json
{
  "arxiv_id": "2304.08485",
  "root": {
    "id": "s.00",
    "title": "(root)",
    "children": [
      {
        "id": "s.01",
        "title": "Introduction",
        "level": 1,
        "start_line": 5,
        "end_line": 84,
        "summary": "We introduce LLaVA...",
        "children": []
      }
    ]
  }
}
```

## Success check
- Both files exist for every promoted paper.
- Tree node IDs are unique.
- Every leaf has `start_line <= end_line`.
```

- [ ] **Step 2: Write `.codex/agents/paper_indexer.toml`**

```toml
name = "paper_indexer"
description = "Build PageIndex trees and node maps from full paper Markdown."
model = "gpt-5.4"
allowed_mcp_tools = []

system_prompt = """
You are paper_indexer. Follow
.agents/skills/pageindex-building/SKILL.md exactly.

Inputs from orchestrator:
- run_id
- arxiv_ids: list of promoted papers to index

For each arxiv_id:
1. Read research_runs/{run_id}/08_full_markdown/{arxiv_id}.md.
2. Parse Markdown headings into a tree with stable IDs (s.NN.NN.NN).
3. Record start_line / end_line / summary per node.
4. Write tree to 09_pageindex/trees/{arxiv_id}.tree.json.
5. Write flat node map to 09_pageindex/nodes/{arxiv_id}.nodes.json.

Do not interpret content beyond mechanical first-sentence summaries.
Return a one-line status: 'ok: N papers indexed, X total nodes'.
"""
```

- [ ] **Step 3: Commit**

```bash
git add .agents/skills/pageindex-building .codex/agents/paper_indexer.toml
git commit -m "skill+agent: paper_indexer"
```

---

## Task 12: Write `chapter-writing` skill and `chapter_writer` agent

**Files:**
- Create: `.agents/skills/chapter-writing/SKILL.md`
- Create: `.codex/agents/chapter_writer.toml`

- [ ] **Step 1: Write `.agents/skills/chapter-writing/SKILL.md`**

```markdown
---
name: chapter-writing
description: Write one handbook chapter from a chapter pack, citing arXiv IDs and source nodes.
---

# Chapter Writing

## Goal
Produce one chapter that explains a topic clearly, assuming KB-known concepts and explaining only necessary unknown concepts.

## Inputs
- `13_chapter_packs/chapter_NN_pack.json`
- `09_pageindex/trees/{arxiv_id}.tree.json` and `.nodes.json` for cited papers
- `08_full_markdown/{arxiv_id}.md` (read sections via MCP `get_paper_section` to keep context small)
- `06_expansion/known_concepts_snapshot.json`
- `Book_style.md` (style rules)

## Outputs
- `14_chapters/chapter_NN.md`

## Rules
- Treat KB-known concepts as already understood. Brief mention only; never an explanation.
- Explain unknown but necessary concepts in proportion to their centrality:
  - central → dedicated subsection
  - supporting → short paragraph
  - minor → footnote/glossary or skip
- Every non-trivial claim cites an arXiv ID inline like `[arxiv:2304.08485, s.03.02]`.
- Follow `Book_style.md` chapter pattern: definition → motivation → intuition → formal explanation → worked example → interpretation → strengths → limitations → practical guidance → tools.
- Never invent datasets, metrics, or numerical results.
- Do not over-explain known concepts. The verifier flags this.

## Success check
- `14_chapters/chapter_NN.md` exists.
- Every section maps to at least one source node listed in the chapter pack.
- The chapter includes Strengths and Limitations sections.
```

- [ ] **Step 2: Write `.codex/agents/chapter_writer.toml`**

```toml
name = "chapter_writer"
description = "Write one handbook chapter using the chapter pack and PageIndex sources."
model = "gpt-5.4"
allowed_mcp_tools = ["get_paper_section", "get_paper_markdown"]

system_prompt = """
You are chapter_writer. Follow
.agents/skills/chapter-writing/SKILL.md and Book_style.md exactly.

Inputs from orchestrator:
- run_id
- chapter_id (e.g. 'chapter_01')

Steps:
1. Load research_runs/{run_id}/13_chapter_packs/{chapter_id}_pack.json.
2. For each source listed in the pack, read the relevant PageIndex node
   range in 09_pageindex/. Use get_paper_section to fetch only what you need.
3. Load known_concepts_snapshot.json. Note KB-known concepts; do not
   re-explain them.
4. Write the chapter to 14_chapters/{chapter_id}.md following Book_style.md
   chapter pattern.
5. Cite arXiv IDs inline. Use [arxiv:ID, node_id] format.

Do not invent results. If a needed claim is not supported, omit it.
Return a one-line status: 'ok: chapter_id, sections=N, citations=C'.
"""
```

- [ ] **Step 3: Commit**

```bash
git add .agents/skills/chapter-writing .codex/agents/chapter_writer.toml
git commit -m "skill+agent: chapter_writer"
```

---

## Task 13: Write `verification` skill and `verifier` agent

**Files:**
- Create: `.agents/skills/verification/SKILL.md`
- Create: `.codex/agents/verifier.toml`

- [ ] **Step 1: Write `.agents/skills/verification/SKILL.md`**

```markdown
---
name: verification
description: Verify chapter claims against source nodes and check knowledge-gap coverage.
---

# Verification

## Goal
Catch unsupported claims, overstated results, missing background, and over-explained known concepts.

## Inputs
- `14_chapters/{chapter_id}.md`
- `13_chapter_packs/{chapter_id}_pack.json`
- `09_pageindex/trees/*.tree.json` and `.nodes.json`
- `08_full_markdown/{arxiv_id}.md` (via MCP `get_paper_section`)
- `06_expansion/known_concepts_snapshot.json`
- `06_expansion/knowledge_gap_report.json`

## Outputs
- `15_verification/{chapter_id}_verification.json`
- `15_verification/verification_summary.csv`

## Rules
- For each non-trivial claim with a citation `[arxiv:ID, node_id]`, fetch that section and judge: `supported`, `partially_supported`, `unsupported`, `overstated`.
- For each high-priority knowledge gap from `knowledge_gap_report.json`, judge `covered` / `missing` / `overexplained` based on the chapter text.
- For KB-known concepts that the chapter explains in detail (more than a sentence), flag as `overexplained_background`.
- A claim that invents a dataset, metric, or numerical result is `unsupported`.

## Output schema
```json
{
  "chapter_id": "chapter_01",
  "claims": [
    {"text": "...", "citation": "arxiv:2304.08485, s.03.02", "verdict": "supported", "reason": ""}
  ],
  "knowledge_gap_coverage": [
    {"concept": "CLIP vision encoder", "status": "covered", "reason": ""}
  ],
  "overexplained_known_concepts": [
    {"concept": "Transformer", "reason": "Two paragraphs of explanation; KB lists it as known."}
  ],
  "summary": {
    "claims_total": 0,
    "claims_unsupported": 0,
    "claims_overstated": 0,
    "gaps_covered": 0,
    "gaps_missing": 0,
    "overexplained_count": 0
  }
}
```

## Success check
- File exists.
- `summary.claims_unsupported == 0` and `summary.gaps_missing == 0` for the run to pass MVP success criteria.
```

- [ ] **Step 2: Write `.codex/agents/verifier.toml`**

```toml
name = "verifier"
description = "Verify chapter claims and check knowledge-gap coverage."
model = "gpt-5.4"
allowed_mcp_tools = ["get_paper_section"]

system_prompt = """
You are verifier. Follow .agents/skills/verification/SKILL.md exactly.

Inputs from orchestrator:
- run_id
- chapter_id

Steps:
1. Read 14_chapters/{chapter_id}.md.
2. Extract every citation [arxiv:ID, node_id] and check it against the
   source via get_paper_section + the PageIndex node line range.
3. Check knowledge gap coverage from knowledge_gap_report.json.
4. Flag any KB-known concept that gets more than a sentence of explanation.
5. Write 15_verification/{chapter_id}_verification.json and append a row
   to verification_summary.csv.

Return a one-line status: 'ok: claims=C unsupported=U gaps=G missing=M'.
"""
```

- [ ] **Step 3: Commit**

```bash
git add .agents/skills/verification .codex/agents/verifier.toml
git commit -m "skill+agent: verifier"
```

---

## Task 14: Write the orchestrator skill

**Files:**
- Create: `.agents/skills/auto-research-orchestrator/SKILL.md`

This is the main entry point. Codex CLI users invoke it (e.g. `/start-research <topic>` or by reading the skill directly).

- [ ] **Step 1: Write `.agents/skills/auto-research-orchestrator/SKILL.md`**

```markdown
---
name: auto-research-orchestrator
description: Run the MVP auto-research pipeline end-to-end for one topic.
---

# Auto Research Orchestrator (MVP)

## Goal
Drive stages 0–13 in order, delegating LLM work to subagents in `.codex/agents/` and writing artifacts under `research_runs/{slug}-{ts}/`.

## Inputs
- `topic` (string, required)
- `knowledge_base_path` (default: `.agents/knowledge_base.md`)
- normal queries, survey queries, positive/negative keywords (optional; derive from topic if missing)

## MVP budgets
```
max_seed_papers       = 50
max_expansion_gaps    = 5
max_papers_per_gap    = 3
max_expansion_rounds  = 1
max_promoted_papers   = 10
chapters_written      = 1
min_gap_importance    = 0.70
min_confusion_risk    = "medium"
```

## Stage order

### Stage 0 — Create run
- Slugify topic. Create `research_runs/{slug}-{YYYYMMDD-HHMMSS}/`.
- Create the per-stage subfolders:
  `00_input 01_seed_pool 02_paper_pool 03_overviews 04_weak_evidence
   05_weak_graph 06_expansion 07_scoring 08_full_markdown 09_pageindex
   13_chapter_packs 14_chapters 15_verification 17_learning_suggestions`
- Write `run_config.json` with the budgets above plus topic and KB path.
- Write `topic.md` with the topic and any user-provided queries/keywords.
- Initialize `run_log.csv` with header `timestamp,stage,status,detail`.

### Stage 1 — Seed pool
- Call MCP `bulk_normal_start_search` with the topic queries and
  `output_dir = research_runs/{run_id}/01_seed_pool/`.
- Save results as `01_seed_pool/seed_pool_raw.json`.
- Write `02_paper_pool/paper_pool.json` (arxiv_id → record) and
  `02_paper_pool/paper_pool.csv`.
- Stop if pool < 10 papers; log and exit (topic too narrow).

### Stage 2 — Weak evidence (cheap)
- Dispatch `weak_evidence_extractor` with `arxiv_ids = paper_pool.keys()`.

### Stage 3 — Weak graph
- Dispatch `weak_graph_extractor`.

### Stage 4 — Read knowledge base
- Dispatch `knowledge_base_reader`.

### Stage 5 — Detect gaps
- Dispatch `knowledge_gap_detector`.
- Stop if `expansion_need_queue.json.items` is empty (skip Stage 6).

### Stage 6 — Expand pool (one round only)
- Dispatch `paper_expander`.
- After acceptance, dispatch `weak_evidence_extractor` AGAIN for the
  newly added arxiv_ids only.

### Stage 7 — Score and promote
- Dispatch `paper_ranker`.

### Stage 8 — Full Markdown
- For each paper in `promoted_papers.json`, call MCP `get_paper_markdown`
  and save to `08_full_markdown/{arxiv_id}.md`.
- Log each fetch in `run_log.csv`.

### Stage 9 — PageIndex
- Dispatch `paper_indexer` with the 10 promoted arxiv_ids.

### Stage 10 — Build one chapter pack (orchestrator-inline)
- Pick the largest graph community in `weak_global_graph.json` whose
  central concept is NOT in the KB (or whose central concept IS in KB
  but bridges a gap). Use it as the chapter title.
- Write `13_chapter_packs/chapter_01_pack.json`:
  ```json
  {
    "chapter_id": "chapter_01",
    "chapter_title": "<central concept>",
    "known_concepts_assumed": [<KB concepts touching this community>],
    "knowledge_gaps_to_explain": [<gap concepts mapped to this community>],
    "core_papers": [<promoted papers in community>],
    "background_papers": [<expansion papers covering the gaps>],
    "supporting_papers": [<other promoted papers cited>],
    "section_plan": [
      {"section_title": "...", "purpose": "...", "source_nodes": [...]}
    ]
  }
  ```

### Stage 11 — Write chapter
- Dispatch `chapter_writer` with `chapter_id = chapter_01`.

### Stage 12 — Verify
- Dispatch `verifier` with `chapter_id = chapter_01`.
- If `summary.claims_unsupported > 0` or `summary.gaps_missing > 0`, log
  but do not auto-rewrite (MVP).

### Stage 13 — Learning suggestions
- Read `knowledge_gap_report.json`. List gaps that recurred across
  multiple papers. Group them under simple category headings.
- Write `17_learning_suggestions/knowledge_to_add.md`:
  ```markdown
  # Suggested Knowledge Base Additions

  Run: {run_id}

  ## <category>
  - <concept> — needed by <N> papers
  ```
- Do NOT modify `.agents/knowledge_base.md`.

## Failure handling
- On any stage failure, append a row to `run_log.csv` and stop the
  pipeline. Do not silently skip.
- Subagent return strings are logged verbatim.

## MVP success criteria
1. `run_config.json` exists.
2. `paper_pool.json` has ≥ 40 papers.
3. Every paper in `04_weak_evidence/` has non-empty `reader_needed_concepts`.
4. `knowledge_gap_report.json` has all three buckets populated.
5. Every row in `accepted_candidates.csv` has `added_for_gap` and `why_needed`.
6. `promoted_papers.json` has 10 entries each with a reason.
7. `08_full_markdown/` has 10 `.md` files.
8. `09_pageindex/trees/` has 10 valid trees.
9. `13_chapter_packs/chapter_01_pack.json` lists `known_concepts_assumed` AND `knowledge_gaps_to_explain`.
10. `14_chapters/chapter_01.md` exists, cites arXiv IDs.
11. `15_verification/chapter_01_verification.json.summary.claims_unsupported == 0` and `summary.gaps_missing == 0`.
12. `17_learning_suggestions/knowledge_to_add.md` exists.
```

- [ ] **Step 2: Commit**

```bash
git add .agents/skills/auto-research-orchestrator
git commit -m "skill: auto-research-orchestrator main pipeline"
```

---

## Task 15: Add scaffold validation test

**Files:**
- Create: `tests/test_codex_scaffold.py`

A small integration test that confirms the agent and skill files parse and reference each other consistently. This catches typos in TOML keys or missing skill files before a Codex run starts.

- [ ] **Step 1: Write the test**

Create `tests/test_codex_scaffold.py`:

```python
"""Sanity checks for the .codex/agents and .agents/skills scaffold."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = REPO_ROOT / ".codex" / "agents"
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"

EXPECTED_AGENTS = {
    "knowledge_base_reader",
    "weak_evidence_extractor",
    "weak_graph_extractor",
    "knowledge_gap_detector",
    "paper_expander",
    "paper_ranker",
    "paper_indexer",
    "chapter_writer",
    "verifier",
}

EXPECTED_SKILLS = {
    "auto-research-orchestrator",
    "knowledge-base-reading",
    "weak-evidence-extraction",
    "weak-graph-extraction",
    "knowledge-gap-detection",
    "paper-pool-expansion",
    "pageindex-building",
    "chapter-writing",
    "verification",
}


def test_all_agents_present():
    found = {p.stem for p in AGENTS_DIR.glob("*.toml")}
    assert found == EXPECTED_AGENTS


def test_all_skills_present():
    found = {p.name for p in SKILLS_DIR.iterdir() if p.is_dir()}
    assert found == EXPECTED_SKILLS
    for skill_name in EXPECTED_SKILLS:
        assert (SKILLS_DIR / skill_name / "SKILL.md").is_file(), skill_name


def test_agents_parse_and_have_required_keys():
    for toml_path in AGENTS_DIR.glob("*.toml"):
        data = tomllib.loads(toml_path.read_text())
        for key in ("name", "description", "model", "allowed_mcp_tools", "system_prompt"):
            assert key in data, f"{toml_path.name} missing {key}"
        assert data["name"] == toml_path.stem


def test_agent_skill_references_resolve():
    """Every SKILL.md path mentioned in an agent prompt must exist."""
    pattern = re.compile(r"\.agents/skills/([a-z\-]+)/SKILL\.md")
    for toml_path in AGENTS_DIR.glob("*.toml"):
        data = tomllib.loads(toml_path.read_text())
        for skill_name in pattern.findall(data["system_prompt"]):
            assert (SKILLS_DIR / skill_name / "SKILL.md").is_file(), (
                f"{toml_path.name} references missing skill {skill_name}"
            )


def test_orchestrator_skill_references_all_agents():
    skill_md = (SKILLS_DIR / "auto-research-orchestrator" / "SKILL.md").read_text()
    for agent in EXPECTED_AGENTS:
        assert agent in skill_md, f"orchestrator does not mention {agent}"


def test_config_toml_has_mcp_server_block():
    config = tomllib.loads((REPO_ROOT / ".codex" / "config.toml").read_text())
    assert "mcp_servers" in config
    assert "swarn-auto-research" in config["mcp_servers"]
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_codex_scaffold.py -v`
Expected: all 6 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_codex_scaffold.py
git commit -m "test: scaffold validation for .codex/agents and .agents/skills"
```

---

## Task 16: Update README with usage instructions

**Files:**
- Modify: `README.md`

The current README references the scaffold but the skills/agents didn't exist before this plan. Replace the "Research Workflow Scaffold" section to point at the actual files.

- [ ] **Step 1: Read the current README**

```bash
cat README.md
```

- [ ] **Step 2: Replace lines 14–32 of `README.md` with**

```markdown
## Research Workflow Scaffold

The MVP scaffold (see `docs/superpowers/specs/2026-05-08-auto-research-mvp-design.md`) lives entirely in config files:

- `.agents/skills/auto-research-orchestrator/SKILL.md` — the main pipeline.
- `.agents/skills/<name>/SKILL.md` — per-stage skills (knowledge-base-reading, weak-evidence-extraction, weak-graph-extraction, knowledge-gap-detection, paper-pool-expansion, pageindex-building, chapter-writing, verification).
- `.codex/agents/*.toml` — narrow Codex subagents that load the matching skill.
- `.codex/config.toml` — registers the local MCP server and MVP budgets.
- `.agents/knowledge_base.md` — the user's known-concepts list. Edit by hand.

A run produces files only under `research_runs/{topic_slug}-{timestamp}/`. The shared knowledge base is read-only during a run; any concepts that recurred but were not in the KB land in `17_learning_suggestions/knowledge_to_add.md` for the user to review.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: point README at the new scaffold files"
```

---

## Self-review notes (filled in after writing the plan)

**Spec coverage check:**
- §2 Architecture → covered by Tasks 4, 5–13, 14.
- §3 File layout (new files) → every path appears in a task.
- §4 Agents (9) → Tasks 5–13 (one agent each), plus Task 10 for the no-skill `paper_ranker`.
- §5 Skills (9) → Tasks 5–14.
- §6 KB seed → Task 1.
- §7 Budgets → Task 4 (`config.toml`) and Task 14 (orchestrator skill body).
- §8 Pipeline flow → Task 14 stage list.
- §9 MCP tool additions → Tasks 2 and 3.
- §10 Success criteria → Task 14 final section + Task 15 scaffold validation.
- §11 Risks → mitigations live in the agent caps in Tasks 9, 10, and the orchestrator skill.
- §12 Non-goals → no tasks added for `10_verified_evidence`, `11_verified_graph`, `12_taxonomy`, `16_book`. Confirmed.

**Placeholder scan:** none — every code/content step contains the exact bytes to write.

**Type/name consistency:**
- Agent names match between `.codex/agents/*.toml`, the orchestrator skill, and `tests/test_codex_scaffold.py:EXPECTED_AGENTS`.
- Skill folder names match between `.agents/skills/*/SKILL.md`, agent system prompts, and `EXPECTED_SKILLS`.
- MCP tool names (`get_alphaxiv_overview`, `get_paper_metadata`) match between Tasks 2/3, agent `allowed_mcp_tools` entries, and the orchestrator skill body.
- File path scheme `research_runs/{run_id}/NN_xxx/` is used identically across all skills and agents.
