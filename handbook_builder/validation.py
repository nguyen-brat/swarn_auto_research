"""Validation gates for generated handbook sites."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from handbook_builder.deploy import PublishConfig, href, resolve_publish_config
from handbook_builder.markdown_sanitize import has_bad_math_delimiters, has_duplicate_body_h1


def clear_validation_state(run_dir: Path) -> None:
    for path in (
        build_ok_path(run_dir),
        publish_ready_path(run_dir),
        run_dir / "19_handbook" / "BUILD_ERROR.txt",
    ):
        if path.exists():
            path.unlink()


def build_ok_path(run_dir: Path) -> Path:
    return run_dir / "19_handbook" / ".validated" / "build-ok.json"


def publish_ready_path(run_dir: Path) -> Path:
    return run_dir / "19_handbook" / ".validated" / "publish-ready.json"


def mark_build_ok(run_dir: Path, *, smoke_pages: list[str]) -> None:
    path = build_ok_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"status": "ok", "smoke_pages": smoke_pages}, indent=2) + "\n")


def validate_source_site(run_dir: Path, *, publish_config: PublishConfig | None = None) -> None:
    publish_config = publish_config or resolve_publish_config()
    handbook = run_dir / "19_handbook"
    required = [
        handbook / "astro.config.mjs",
        handbook / "package.json",
        handbook / "src/content.config.ts",
        handbook / "src/content/docs/index.mdx",
        handbook / "src/content/docs/methods/index.md",
        handbook / "src/content/docs/families/index.md",
    ]
    for path in required:
        if not path.exists():
            raise RuntimeError(f"Stage 19 missing required file: {path.relative_to(run_dir)}")

    package = json.loads((handbook / "package.json").read_text())
    deps = package.get("dependencies") or {}
    for dep in ("remark-math", "rehype-katex", "katex"):
        if dep not in deps:
            raise RuntimeError(f"Stage 19 package.json missing dependency: {dep}")

    for page in (handbook / "src/content/docs").rglob("*.*"):
        if page.suffix not in {".md", ".mdx"}:
            continue
        text = page.read_text()
        if not _frontmatter_has(text, "title"):
            raise RuntimeError(f"Stage 19 page missing title frontmatter: {page.relative_to(run_dir)}")
        if not _frontmatter_has(text, "head"):
            raise RuntimeError(f"Stage 19 page missing head frontmatter: {page.relative_to(run_dir)}")
        if has_bad_math_delimiters(text):
            raise RuntimeError(f"Stage 19 page has bad math delimiters: {page.relative_to(run_dir)}")
        if has_duplicate_body_h1(text):
            raise RuntimeError(f"Stage 19 page has duplicate body H1: {page.relative_to(run_dir)}")

    _validate_method_links(run_dir, publish_config=publish_config)


def validate_built_site(run_dir: Path, *, publish_config: PublishConfig | None = None) -> None:
    publish_config = publish_config or resolve_publish_config()
    dist = run_dir / "19_handbook" / "dist"
    if not dist.exists():
        raise RuntimeError("Stage 19 build did not produce dist/")
    smoke = _smoke_pages(run_dir)
    missing = [page for page in smoke if not (dist / page).exists()]
    if missing:
        raise RuntimeError(f"Stage 19 build missing smoke pages: {missing}")
    katex_errors = [
        page.relative_to(run_dir)
        for page in dist.rglob("*.html")
        if "katex-error" in page.read_text(errors="ignore")
    ]
    if katex_errors:
        raise RuntimeError(f"Stage 19 build has KaTeX render errors: {katex_errors[:10]}")
    unsupported_macros = [
        page.relative_to(run_dir)
        for page in dist.rglob("*.html")
        if _has_katex_unsupported_macro_marker(page.read_text(errors="ignore"))
    ]
    if unsupported_macros:
        raise RuntimeError(f"Stage 19 build has KaTeX unsupported macro markers: {unsupported_macros[:10]}")
    _validate_publish_readiness(run_dir, publish_config=publish_config)
    mark_build_ok(run_dir, smoke_pages=smoke)


def _frontmatter_has(text: str, key: str) -> bool:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    for line in lines[1:]:
        if line.strip() == "---":
            return False
        if line.strip().startswith(f"{key}:"):
            return True
    return False


def _has_katex_unsupported_macro_marker(markup: str) -> bool:
    return 'mathcolor="#cc0000"' in markup or "color:#cc0000" in markup


def _validate_method_links(run_dir: Path, *, publish_config: PublishConfig) -> None:
    docs = run_dir / "19_handbook" / "src/content/docs"
    methods_index = docs / "methods" / "index.md"
    index_text = methods_index.read_text()
    methods = _method_slugs(run_dir)
    base_path = publish_config.base_path
    missing_pages = []
    missing_links = []
    for slug in methods:
        if not (docs / f"{slug}.md").exists() and not (docs / f"{slug}.mdx").exists():
            missing_pages.append(slug)
        if f'href="{href(slug + "/", base_path=base_path)}"' not in index_text:
            missing_links.append(slug)
    if missing_pages:
        raise RuntimeError(f"Stage 19 missing method pages: {missing_pages[:10]}")
    if missing_links:
        raise RuntimeError(f"Stage 19 methods index missing links: {missing_links[:10]}")


def _validate_publish_readiness(run_dir: Path, *, publish_config: PublishConfig) -> None:
    path = publish_ready_path(run_dir)
    if not publish_config.enabled and not publish_config.base_path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"status": "local", "base_path": ""}, indent=2) + "\n")
        return

    dist = run_dir / "19_handbook" / "dist"
    if not (dist / ".nojekyll").exists():
        raise RuntimeError("Stage 19 publish-ready build missing dist/.nojekyll")

    index = dist / "index.html"
    index_text = index.read_text(errors="ignore")
    base_path = publish_config.base_path
    if base_path:
        if 'href="/_astro/' in index_text or 'src="/_astro/' in index_text:
            raise RuntimeError("Stage 19 publish-ready build has root _astro asset references")
        if f'{base_path}/_astro/' not in index_text and f'href="{base_path}/' not in index_text:
            raise RuntimeError(f"Stage 19 publish-ready build missing base path references: {base_path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "status": "ready",
                "site_url": publish_config.site_url,
                "base_path": base_path,
                "source_path": str(publish_config.source_path) if publish_config.source_path else None,
            },
            indent=2,
        )
        + "\n"
    )


def _method_slugs(run_dir: Path) -> list[str]:
    outline_path = run_dir / "12_taxonomy" / "outline.json"
    if outline_path.exists():
        data = json.loads(outline_path.read_text())
        methods = data.get("methods") if isinstance(data, dict) else None
        if isinstance(methods, list) and methods:
            return sorted(f"methods/{item['id']}" for item in methods if item.get("id"))
    methods_dir = run_dir / "14_chapters" / "methods"
    if not methods_dir.exists():
        return []
    return sorted(f"methods/{path.stem}" for path in methods_dir.glob("*.md"))


def _smoke_pages(run_dir: Path) -> list[str]:
    pages = ["index.html", "methods/index.html", "families/index.html"]
    methods = _method_slugs(run_dir)
    if methods:
        pages.append(f"{methods[0]}/index.html")
    family = _first_existing_slug(run_dir / "19_handbook/src/content/docs/families")
    if family:
        pages.append(f"families/{family}/index.html")
    appendix = run_dir / "19_handbook/src/content/docs/book/appendices"
    if appendix.exists():
        first = _first_existing_slug(appendix)
        if first:
            pages.append(f"book/appendices/{first}/index.html")
    return pages


def _first_existing_slug(path: Path) -> str | None:
    for suffix in ("*.md", "*.mdx"):
        for item in sorted(path.glob(suffix)):
            if item.name == "index.md" or item.name == "index.mdx":
                continue
            return item.stem
    return None
