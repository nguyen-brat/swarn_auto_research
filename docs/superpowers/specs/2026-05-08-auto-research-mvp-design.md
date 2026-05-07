# Auto Research System — MVP Design

**Date:** 2026-05-08
**Topic for first run:** visual instruction tuning for multimodal LLMs
**Source plan:** the long plan pasted in the brainstorming session (stages 0–15, 13 agents, 8 skills, 19 scripts)
**Scope of this spec:** MVP only — the plan's "MVP" section, executed Codex-native (no new Python pipeline scripts).

---

## 1. Goal

Ship a working end-to-end run that:

1. Loads a shared knowledge base from `.agents/knowledge_base.md`.
2. Collects 50 seed papers via existing MCP.
3. Extracts weak evidence (with `reader_needed_concepts`) for each paper.
4. Builds a weak knowledge graph.
5. Detects knowledge gaps against the shared KB.
6. Expands the paper pool **only** for top-5 unknown important concepts (≤3 papers per gap).
7. Promotes the top 10 papers, fetches their full Markdown, builds PageIndex.
8. Writes one chapter pack and one chapter.
9. Verifies the chapter against sources and gap-coverage rules.

Out of scope for MVP: multi-chapter handbook compile, verified-graph stage, taxonomy stage, automatic KB updates.

---

## 2. Architecture

Codex-native pipeline driven by one orchestrator skill that walks stages in order. Each stage delegates to a narrow subagent. Subagents call the existing MCP tools and write JSON/CSV artifacts to `research_runs/{slug}-{ts}/`. No new Python scripts.

```
┌──────────────────────────────────────────────────────────────┐
│   .agents/skills/auto-research-orchestrator/SKILL.md         │
│   (main pipeline, called by user via /start-research)        │
└──────────────────────────────────────────────────────────────┘
                          │ stage by stage
        ┌─────────────────┼──────────────────────────┐
        ▼                 ▼                          ▼
┌──────────────┐  ┌────────────────────┐  ┌────────────────────┐
│ MCP server   │  │ subagent (.codex/  │  │ deterministic file │
│ swarn_       │  │ agents/*.toml)     │  │ IO (orchestrator   │
│ research_mcp │  │ loads matching     │  │ writes JSON/CSV    │
│              │  │ SKILL.md           │  │ directly)          │
└──────────────┘  └────────────────────┘  └────────────────────┘
```

**Key principle preserved from the plan:** expansion fires *only* on knowledge gaps, never on raw citation count.

---

## 3. File layout

### Existing (do not modify)
```
swarn_research_mcp/    # MCP tools, already provides paper search + markdown
sdk/codex.py           # Codex SDK wrapper (not used by MVP)
AGENTS.md, CLAUDE.md   # behavioral guidelines (project rules)
Book_style.md          # writing style for chapters
```

### New
```
.agents/
├── knowledge_base.md                          # seeded KB (was empty)
└── skills/
    ├── auto-research-orchestrator/SKILL.md    # main pipeline
    ├── knowledge-base-reading/SKILL.md
    ├── weak-evidence-extraction/SKILL.md
    ├── weak-graph-extraction/SKILL.md
    ├── knowledge-gap-detection/SKILL.md
    ├── paper-pool-expansion/SKILL.md
    ├── pageindex-building/SKILL.md
    ├── chapter-writing/SKILL.md
    └── verification/SKILL.md

.codex/
├── config.toml                                # MCP registration + agent limits
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
```

### Generated per run
```
research_runs/visual-instruction-tuning-{ts}/
├── run_config.json
├── run_log.csv
├── topic.md
├── 00_input/
├── 01_seed_pool/
├── 02_paper_pool/
├── 03_overviews/
├── 04_weak_evidence/
├── 05_weak_graph/
├── 06_expansion/
├── 07_scoring/
├── 08_full_markdown/
├── 09_pageindex/
├── 13_chapter_packs/
├── 14_chapters/
├── 15_verification/
└── 17_learning_suggestions/
```
Skipped for MVP: `10_verified_evidence`, `11_verified_graph`, `12_taxonomy`, `16_book`.

---

## 4. Agents (9, narrower than plan's 13)

| Agent | Purpose | Reads | Writes | MCP tools |
|---|---|---|---|---|
| `knowledge_base_reader` | Parse shared KB | `.agents/knowledge_base.md` | `06_expansion/known_concepts_snapshot.json` | none |
| `weak_evidence_extractor` | Cheap first-pass per paper (also handles enrichment) | `02_paper_pool/paper_pool.json`, alphaXiv overview, S2 metadata | `03_overviews/`, `04_weak_evidence/{id}.json` | `bulk_normal_start_search` outputs already cached; alphaXiv/S2 calls via service helpers exposed through MCP if needed (see §9) |
| `weak_graph_extractor` | Build weak graph | `04_weak_evidence/*.json` | `05_weak_graph/fragments/`, `weak_global_graph.json` | none |
| `knowledge_gap_detector` | Compare needed vs known | `known_concepts_snapshot.json`, `04_weak_evidence/*`, `weak_global_graph.json` | `06_expansion/knowledge_gap_report.json`, `expansion_need_queue.json` | none |
| `paper_expander` | Search for gap-filling papers | `expansion_need_queue.json`, `paper_pool.json` | `06_expansion/expansion_round_01.json`, `accepted_candidates.csv`, `rejected_candidates.csv`; updates `paper_pool.json` | `bulk_normal_start_search` |
| `paper_ranker` | Score and promote | weak evidence, weak graph, paper pool, gap report | `07_scoring/paper_scores.csv`, `promoted_papers.json` | none |
| `paper_indexer` | PageIndex from full md | `08_full_markdown/{id}.md` | `09_pageindex/trees/{id}.tree.json`, `09_pageindex/nodes/{id}.nodes.json` | none |
| `chapter_writer` | Write one chapter (also covers verified-evidence reading inline) | promoted papers, pageindex, chapter pack, KB | `13_chapter_packs/chapter_01_pack.json`, `14_chapters/chapter_01.md` | `get_paper_section`, `get_paper_markdown` |
| `verifier` | Check claims + gap coverage | chapter, chapter pack, pageindex | `15_verification/chapter_01_verification.json`, `verification_summary.csv` | `get_paper_section` |

Each `.toml` ~20 lines: name, description, model, allowed MCP tools, system prompt that says "follow the rules in `.agents/skills/<matching-skill>/SKILL.md`".

**Dropped from MVP** (folded elsewhere or deferred):
- `paper_enricher` → folded into `weak_evidence_extractor`
- `verified_evidence_extractor`, `verified_graph_extractor` → MVP writes only one chapter; verification reads source nodes directly through `chapter_writer` + `verifier`
- `outline_planner`, `chapter_pack_builder` → orchestrator inlines for the single chapter
- `run_orchestrator` → replaced by orchestrator *skill*

---

## 5. Skills

Nine `SKILL.md` files. Content mirrors the plan's "Recommended skills" section, lightly tightened. Each skill states **goal, inputs, outputs, rules**, and is referenced by the matching agent's system prompt. The orchestrator skill additionally lists the stage order, budgets, and stop conditions.

---

## 6. Knowledge base seed

`.agents/knowledge_base.md` is currently empty. For the first run on multimodal-LLM topic, seed with ~25 bullets across categories:

```markdown
# User Knowledge Base

## Core LLM Concepts
- Large Language Model
- Transformer
- Self-attention
- Multi-head attention
- Token / tokenizer
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

User can edit before first run. The KB is read-only during the run; concepts the system *would* like added land in `17_learning_suggestions/knowledge_to_add.md`.

---

## 7. MVP budgets

```
max_seed_papers:                50
max_expansion_gaps:              5
max_papers_per_gap:              3
max_expansion_rounds:            1
max_promoted_papers:            10
chapters_written:                1
min_gap_importance:              0.70
min_confusion_risk:              medium
```

Recorded in `run_config.json` so the orchestrator skill can enforce them.

---

## 8. Pipeline flow (MVP)

The orchestrator skill executes stages in order. Each stage has a single success check; failure logs to `run_log.csv` and stops the run.

```
0.  create run folder + run_config.json + topic.md
1.  bulk_normal_start_search → seed_pool_raw.json → paper_pool.json/csv
2.  weak_evidence_extractor over all papers (uses cached abstracts/overviews
    from MCP search; fetch alphaXiv overview only if missing)
3.  weak_graph_extractor → fragments + weak_global_graph.json
4.  knowledge_base_reader → known_concepts_snapshot.json
5.  knowledge_gap_detector → knowledge_gap_report.json + expansion_need_queue.json
6.  paper_expander (1 round, ≤5 gaps, ≤3 papers each, total ≤15 new)
    → updates paper_pool.json, writes accepted_candidates.csv
    → run weak_evidence_extractor on newly added papers only
7.  paper_ranker → promoted_papers.json (top 10)
8.  get_paper_markdown for each promoted paper → 08_full_markdown/{id}.md
9.  paper_indexer → 09_pageindex/{trees,nodes}/
10. orchestrator inlines outline + chapter_pack_builder for ONE chapter:
    chapter title = the dominant graph community's anchor concept
    → chapter_packs/chapter_01_pack.json
11. chapter_writer (uses Book_style.md style) → 14_chapters/chapter_01.md
12. verifier → 15_verification/chapter_01_verification.json
13. orchestrator writes 17_learning_suggestions/knowledge_to_add.md from
    repeatedly-needed concepts in knowledge_gap_report.json
```

---

## 9. MCP tool additions (decided)

The MCP server registers only three tools today: `bulk_normal_start_search`, `get_paper_markdown`, `get_paper_section`. AlphaXiv overview and Semantic Scholar paper detail exist as service helpers but are not exposed.

**Decision:** add two new MCP tools in `swarn_research_mcp/server.py`:

- `get_alphaxiv_overview(arxiv_id)` → wraps `services/alphaxiv.py` overview helper.
- `get_paper_metadata(arxiv_id)` → wraps `services/semantic_scholar.py` paper-detail helper.

Both inherit the existing retry wrapper. Estimated diff: ~30 lines. This is the only Python change in MVP.

---

## 10. Success criteria (MVP done = all of these pass)

```
✓ research_runs/visual-instruction-tuning-<ts>/run_config.json exists
✓ paper_pool.json has ≥40 papers (50 seeds may dedupe to fewer)
✓ every paper in 04_weak_evidence/ has reader_needed_concepts (non-empty)
✓ knowledge_gap_report.json separates known / unknown_minor / knowledge_gaps
✓ accepted_candidates.csv: every row has added_for_gap and why_needed
✓ promoted_papers.json has 10 entries, each with reason
✓ 08_full_markdown/ has 10 .md files
✓ 09_pageindex/trees/ has 10 valid trees
✓ 13_chapter_packs/chapter_01_pack.json lists known_concepts_assumed
  AND knowledge_gaps_to_explain
✓ 14_chapters/chapter_01.md exists, cites arXiv IDs, doesn't over-explain
  KB-known concepts (verifier check)
✓ 15_verification/chapter_01_verification.json: zero unsupported major
  claims, all high-priority gaps marked covered
✓ 17_learning_suggestions/knowledge_to_add.md exists
```

---

## 11. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Codex agent loops or burns tokens on weak evidence over 50 papers | Strict per-stage budgets in `run_config.json`; orchestrator enforces and stops on overrun |
| MCP `bulk_normal_start_search` returns <50 papers for niche topic | Lower seed budget gracefully; do not loop searches |
| Knowledge gap detector flags too many gaps as "important" | Hard cap of 5 gaps in MVP regardless of importance scores |
| AlphaXiv/S2 endpoints rate-limit or fail | New MCP tools (§9) inherit existing retry wrapper in `server.py` |
| Chapter writer over-explains KB concepts | `verifier` flags `overexplained-background`; surfaced in summary CSV |
| User KB seed (§6) is wrong for chosen topic | KB is read-only and editable; user reviews before run |

---

## 12. Non-goals (explicit)

- No SQLite; JSON/CSV only (per plan).
- No automatic edits to `.agents/knowledge_base.md` (only suggestions).
- No multi-chapter handbook (`16_book/`) compile in MVP.
- No verified-graph stage (`11_verified_graph/`) in MVP.
- No taxonomy stage (`12_taxonomy/`) in MVP.
- No new Python pipeline scripts; the only Python touched is the MCP server (§9 option b).
