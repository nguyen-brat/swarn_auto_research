"""Copy chapter markdown into Starlight content docs and translate sidebar."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from handbook_builder.frontmatter import ensure_head_default
from handbook_builder import site_templates
from handbook_builder.deploy import href, resolve_publish_config
from scripts.auto_research_runner.paper_roles import is_context_only_paper, is_placeholder_method_id


def copy_chapters_into_docs(
    run_dir: Path,
    docs_dir: Path,
    *,
    output_extension: str = ".md",
    base_path: str = "",
    require_sidebar: bool = False,
) -> None:
    """Copy 14_chapters/{book,families,methods}/*.md to docs_dir."""
    if output_extension not in {".md", ".mdx"}:
        raise ValueError("output_extension must be .md or .mdx")

    src_root = run_dir / "14_chapters"
    sidebar_path = run_dir / "16_book" / "sidebar.json"
    if require_sidebar and not sidebar_path.exists():
        raise RuntimeError("Stage 19 requires 16_book/sidebar.json before copying handbook docs")
    sidebar_json = json.loads(sidebar_path.read_text()) if sidebar_path.exists() else None
    if require_sidebar and sidebar_json is not None:
        _assert_sidebar_publishable(run_dir, sidebar_json)
    reachable = _reachable_chapter_paths(sidebar_json) if sidebar_json is not None else None
    for kind in ("book", "families", "methods"):
        src_kind = src_root / kind
        if not src_kind.exists():
            continue
        dst_kind = docs_dir / kind
        dst_kind.mkdir(parents=True, exist_ok=True)
        for stale in list(dst_kind.rglob("*.md")) + list(dst_kind.rglob("*.mdx")):
            stale.unlink()
        for md in src_kind.rglob("*.md"):
            rel_to_run = md.relative_to(run_dir).as_posix()
            if reachable is not None and rel_to_run not in reachable:
                continue
            rel = md.relative_to(src_kind)
            dst = dst_kind / rel.with_suffix(output_extension)
            dst.parent.mkdir(parents=True, exist_ok=True)
            text = _rewrite_paper_figure_urls(md.read_text(), base_path)
            dst.write_text(ensure_head_default(text, fallback_title=md.stem.replace("-", " ").title()))


def _normalized_base_path(base_path: str) -> str:
    stripped = str(base_path or "").strip()
    if not stripped or stripped == "/":
        return ""
    return "/" + stripped.strip("/")


def _rewrite_paper_figure_urls(text: str, base_path: str) -> str:
    prefix = _normalized_base_path(base_path)
    if not prefix:
        return text
    return re.sub(r"\]\(/paper_figures/", f"]({prefix}/paper_figures/", text)


def copy_paper_figures(run_dir: Path, handbook_dir: Path) -> None:
    src = run_dir / "13_chapter_packs" / "assets" / "paper_figures"
    dst = handbook_dir / "public" / "paper_figures"
    if dst.exists():
        shutil.rmtree(dst)
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)


def build_starlight_sidebar(sidebar_json: dict[str, Any]) -> list[dict[str, Any]]:
    """Translate 16_book/sidebar.json into a compact Starlight sidebar config."""
    result: list[dict[str, Any]] = []
    result.append(
        {
            "label": "Handbook",
            "items": [
                {"label": "Home", "link": "/"},
                {"label": "Methods", "slug": "methods"},
                {"label": "Families", "slug": "families"},
            ],
        }
    )
    for group in sidebar_json.get("items", []):
        if group.get("title") != "Book":
            continue
        result.append(
            {"label": group["title"], "items": [_sidebar_item(c, include_methods=False) for c in group.get("children", [])]}
        )
    family_items = []
    for family in _families_from_sidebar(sidebar_json):
        family_items.append(_family_sidebar_item(family))
    if family_items:
        result.append({"label": "Families", "items": family_items})
    return result


def _family_sidebar_item(family: dict[str, Any]) -> dict[str, Any]:
    if not family["methods"]:
        return {"label": family["title"], "slug": _path_to_slug(family["path"])}
    return {
        "label": family["title"],
        "collapsed": True,
        "items": [
            {"label": "Overview", "slug": _path_to_slug(family["path"])},
            *[
                {"label": method["title"], "slug": method["slug"]}
                for method in family["methods"]
            ],
        ],
    }


def write_index_pages(run_dir: Path, docs_dir: Path, *, base_path: str | None = None) -> None:
    """Write method/family index pages and add method links to family pages."""
    manifest = _manifest_items(run_dir)
    sidebar = json.loads((run_dir / "16_book" / "sidebar.json").read_text())
    families = _families_from_sidebar(sidebar)
    methods = _method_items(run_dir, manifest, families)
    if base_path is None:
        base_path = resolve_publish_config().base_path

    _write_methods_index(docs_dir, methods, base_path=base_path)
    _write_families_index(docs_dir, families, base_path=base_path)
    _enhance_family_pages(docs_dir, families, base_path=base_path)


def _sidebar_item(item: dict[str, Any], *, include_methods: bool = True) -> dict[str, Any]:
    translated: dict[str, Any] = {"label": item["title"]}
    if item.get("path"):
        translated["slug"] = _path_to_slug(item["path"])
    children = item.get("children") or []
    if children:
        child_items = [
            _sidebar_item(child, include_methods=include_methods)
            for child in children
            if include_methods or not _is_method_path(child.get("path"))
        ]
        if child_items:
            translated["items"] = child_items
    return translated


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


def _is_method_path(path: str | None) -> bool:
    return bool(path and "/methods/" in path)


def _reachable_chapter_paths(sidebar_json: dict[str, Any]) -> set[str]:
    paths: set[str] = set()

    def walk(item: dict[str, Any]) -> None:
        path = item.get("path")
        if isinstance(path, str) and path.startswith("14_chapters/"):
            paths.add(path)
        for child in item.get("children") or []:
            if isinstance(child, dict):
                walk(child)

    for item in sidebar_json.get("items", []) or []:
        if isinstance(item, dict):
            walk(item)
    return paths


def _assert_sidebar_publishable(run_dir: Path, sidebar_json: dict[str, Any]) -> None:
    blockers: list[str] = []
    for relpath in _reachable_chapter_paths(sidebar_json):
        if "/methods/" not in relpath:
            continue
        method_id = Path(relpath).stem
        if is_placeholder_method_id(method_id):
            blockers.append(method_id)
            continue
        arxiv_id = _frontmatter_value(run_dir / relpath, "arxiv_id")
        if arxiv_id and is_context_only_paper(run_dir, arxiv_id):
            blockers.append(method_id)
    if blockers:
        raise RuntimeError(
            "Stage 19 cannot publish placeholder or context-only method page(s): "
            f"{blockers[:10]}. Rerun from Stage 13 after Stage 12 normalization."
        )


def _frontmatter_value(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return ""


def _families_from_sidebar(sidebar_json: dict[str, Any]) -> list[dict[str, Any]]:
    families: list[dict[str, Any]] = []
    for group in sidebar_json.get("items", []):
        if group.get("title") == "Book":
            continue
        for child in group.get("children", []):
            path = child.get("path") or ""
            if "/families/" not in path:
                continue
            methods = [
                {
                    "title": grandchild.get("title") or grandchild.get("path", "").rsplit("/", 1)[-1],
                    "path": grandchild.get("path", ""),
                    "slug": _path_to_slug(grandchild.get("path", "")),
                }
                for grandchild in child.get("children", [])
                if _is_method_path(grandchild.get("path"))
            ]
            families.append(
                {
                    "title": child.get("title") or path.rsplit("/", 1)[-1],
                    "path": path,
                    "slug": _path_to_slug(path),
                    "part": group.get("title", ""),
                    "methods": methods,
                }
            )
    return families


def _manifest_items(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "16_book" / "chapters_manifest.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("chapters"), list):
        return data["chapters"]
    return []


def _method_items(
    run_dir: Path,
    manifest: list[dict[str, Any]],
    families: list[dict[str, Any]],
) -> list[dict[str, str]]:
    by_slug: dict[str, dict[str, str]] = {}
    has_sidebar = (run_dir / "16_book" / "sidebar.json").exists()
    for family in families:
        for method in family["methods"]:
            by_slug[method["slug"]] = {
                "title": method["title"],
                "slug": method["slug"],
                "family": family["title"],
                "family_slug": family["slug"],
            }
    if has_sidebar:
        sidebar = json.loads((run_dir / "16_book" / "sidebar.json").read_text())
        for method in _method_entries_from_sidebar(sidebar):
            by_slug.setdefault(
                method["slug"],
                {
                    "title": method["title"],
                    "slug": method["slug"],
                    "family": "Unassigned",
                    "family_slug": "",
                },
            )
        return sorted(by_slug.values(), key=lambda item: (item["family"], item["title"]))
    for item in manifest:
        if _chapter_type(item) != "methods":
            continue
        item_path = item.get("path") or item.get("file")
        slug = _path_to_slug(item_path) if item_path else f"methods/{item.get('id') or item.get('chapter_id') or ''}"
        by_slug.setdefault(
            slug,
            {
                "title": item.get("title") or item.get("id") or item.get("chapter_id") or slug.rsplit("/", 1)[-1],
                "slug": slug,
                "family": "Unassigned",
                "family_slug": "",
            },
        )
    methods_dir = run_dir / "14_chapters" / "methods"
    if methods_dir.exists():
        for path in methods_dir.glob("*.md"):
            slug = f"methods/{path.stem}"
            by_slug.setdefault(
                slug,
                {
                    "title": _title_from_markdown(path) or path.stem.replace("-", " ").title(),
                    "slug": slug,
                    "family": "Unassigned",
                    "family_slug": "",
                },
            )
    return sorted(by_slug.values(), key=lambda item: (item["family"], item["title"]))


def _method_entries_from_sidebar(sidebar_json: dict[str, Any]) -> list[dict[str, str]]:
    methods: list[dict[str, str]] = []

    def walk(item: dict[str, Any]) -> None:
        path = item.get("path")
        if _is_method_path(path):
            methods.append(
                {
                    "title": item.get("title") or Path(str(path)).stem,
                    "slug": _path_to_slug(str(path)),
                }
            )
        for child in item.get("children") or []:
            if isinstance(child, dict):
                walk(child)

    for item in sidebar_json.get("items", []) or []:
        if isinstance(item, dict):
            walk(item)
    return methods


def _title_from_markdown(path: Path) -> str | None:
    for line in path.read_text().splitlines()[:20]:
        if line.startswith("title:"):
            return line.split(":", 1)[1].strip().strip('"')
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _chapter_type(item: dict[str, Any]) -> str | None:
    value = item.get("chapter_type") or item.get("type")
    if value in {"family", "families"}:
        return "families"
    if value in {"method", "methods"}:
        return "methods"
    return value


def _write_methods_index(docs_dir: Path, methods: list[dict[str, str]], *, base_path: str = "") -> None:
    lines = [
        "---",
        "title: Methods",
        "description: Complete method directory for this research handbook.",
        "head: []",
        "---",
        "",
        "# Methods",
        "",
        "Every method page is listed here exactly once. Use the family links to narrow the space before opening a method.",
        "",
        '<div class="method-grid">',
    ]
    for method in methods:
        family_link = (
            f'<a href="{href(method["family_slug"] + "/", base_path=base_path)}">{method["family"]}</a>'
            if method["family_slug"]
            else method["family"]
        )
        lines.extend(
            [
                '<div class="method-card">',
                f'<strong><a href="{href(method["slug"] + "/", base_path=base_path)}">{method["title"]}</a></strong>',
                f'<span>Family: {family_link}</span><br/>',
                f'<a href="{href(method["slug"] + "/", base_path=base_path)}">Open Method</a>',
                "</div>",
            ]
        )
    lines.extend(["</div>", ""])
    (docs_dir / "methods").mkdir(parents=True, exist_ok=True)
    (docs_dir / "methods" / "index.md").write_text("\n".join(lines))


def _write_families_index(docs_dir: Path, families: list[dict[str, Any]], *, base_path: str = "") -> None:
    lines = [
        "---",
        "title: Families",
        "description: Research family index for this handbook.",
        "head: []",
        "---",
        "",
        "# Families",
        "",
        '<div class="family-grid">',
    ]
    for family in families:
        lines.extend(
            [
                '<div class="family-card">',
                f'<strong><a href="{href(family["slug"] + "/", base_path=base_path)}">{family["title"]}</a></strong>',
                f'<span>{len(family["methods"])} methods</span><br/>',
                f'<a href="{href(family["slug"] + "/", base_path=base_path)}">Open Family</a>',
                "</div>",
            ]
        )
    lines.extend(["</div>", ""])
    (docs_dir / "families").mkdir(parents=True, exist_ok=True)
    (docs_dir / "families" / "index.md").write_text("\n".join(lines))


def _enhance_family_pages(docs_dir: Path, families: list[dict[str, Any]], *, base_path: str = "") -> None:
    for family in families:
        path = docs_dir / f"{family['slug']}.md"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"---\ntitle: {json.dumps(family['title'])}\nhead: []\n---\n# {family['title']}\n"
            )
        body = path.read_text()
        if "## Methods in this family" in body:
            continue
        block = ["", "## Methods in this family", "", '<div class="method-grid">']
        for method in family["methods"]:
            block.extend(
                [
                    '<div class="method-card">',
                    f'<strong><a href="{href(method["slug"] + "/", base_path=base_path)}">{method["title"]}</a></strong>',
                    f'<a href="{href(method["slug"] + "/", base_path=base_path)}">Open Method</a>',
                    "</div>",
                ]
            )
        block.extend(["</div>", ""])
        path.write_text(_insert_after_first_heading(body, "\n".join(block)))


def _insert_after_first_heading(markdown: str, block: str) -> str:
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("# "):
            lines.insert(index + 1, block)
            return "\n".join(lines) + ("\n" if markdown.endswith("\n") else "")
    return markdown + "\n" + block + "\n"
