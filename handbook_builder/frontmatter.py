"""Small helpers for generated Starlight frontmatter."""
from __future__ import annotations

import json


def ensure_head_default(markdown: str, *, fallback_title: str = "Untitled") -> str:
    """Ensure Starlight pages have minimal frontmatter and explicit head config."""
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        title = _first_heading(lines) or fallback_title
        trailing_newline = "\n" if markdown.endswith("\n") else ""
        return f"---\ntitle: {json.dumps(title)}\nhead: []\n---\n{markdown}" + trailing_newline

    end = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = idx
            break
    if end is None:
        return markdown

    frontmatter = lines[1:end]
    has_title = any(line.strip().startswith("title:") for line in frontmatter)
    if any(line.strip().startswith("head:") for line in frontmatter):
        if has_title:
            return markdown
        updated = [*lines[:end], f"title: {json.dumps(fallback_title)}", *lines[end:]]
        trailing_newline = "\n" if markdown.endswith("\n") else ""
        return "\n".join(updated) + trailing_newline

    additions = []
    if not has_title:
        additions.append(f"title: {json.dumps(fallback_title)}")
    additions.append("head: []")
    updated = [*lines[:end], *additions, *lines[end:]]
    trailing_newline = "\n" if markdown.endswith("\n") else ""
    return "\n".join(updated) + trailing_newline


def _first_heading(lines: list[str]) -> str | None:
    for line in lines:
        if line.startswith("# "):
            return line[2:].strip()
    return None
