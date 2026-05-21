"""Splice agent-authored TLDR/KeyIdea/WhenToUse + diagram into a method MDX page."""
from __future__ import annotations

import json
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
    original = mdx_path.read_text()
    title = _extract_frontmatter_title(original) or _extract_title(_strip_frontmatter(original))
    body = _strip_frontmatter(original)

    frontmatter_lines = [
        "---",
        f"title: {json.dumps(title)}",
        "head: []",
    ]
    tags = payload.get("tags") or []
    if tags:
        frontmatter_lines.append(f"tags: {json.dumps(tags)}")
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
        f"{body}"
    )
    mdx_path.write_text(new_body)


def _extract_title(body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "Untitled"


def _extract_frontmatter_title(body: str) -> str | None:
    lines = body.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        if line.startswith("title:"):
            raw = line.split(":", 1)[1].strip()
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = raw.strip("'\"")
            return str(parsed)
    return None


def _strip_frontmatter(body: str) -> str:
    lines = body.splitlines()
    if not lines or lines[0].strip() != "---":
        return body
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1:]).lstrip() + ("\n" if body.endswith("\n") else "")
    return body


from scripts.auto_research_runner.prompts import _generic_agent_prompt
from scripts.auto_research_runner.shared_types import ShardSpec


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
