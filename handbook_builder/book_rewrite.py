"""Book-chapter web rewrite sub-stage."""
from __future__ import annotations

import re
from pathlib import Path

from scripts.auto_research_runner.prompts import _generic_agent_prompt
from scripts.auto_research_runner.shared_types import ShardSpec


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
