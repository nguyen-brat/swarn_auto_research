"""Orchestrate Stage 19 sub-stages."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from handbook_builder import deploy, dispatch, linker, scaffold
from handbook_builder.frontmatter import ensure_head_default
from handbook_builder.markdown_sanitize import sanitize_docs_tree
from handbook_builder.run_metadata import load_run_topic
from handbook_builder.validation import clear_validation_state, validate_source_site

Milestone = Literal["M0", "M1", "M2", "M3"]
IMPLEMENTED_MILESTONES = frozenset(("M0", "M1", "M2", "M3"))


def build(
    run_dir: Path,
    *,
    milestone: Milestone = "M0",
    max_workers: int = 12,
    executor: str = "sdk",
    run_pnpm_build: bool = True,
) -> None:
    """Run Stage 19 up to the given milestone."""
    if milestone not in IMPLEMENTED_MILESTONES:
        raise ValueError(
            f"unsupported handbook milestone {milestone!r}; "
            f"expected one of {sorted(IMPLEMENTED_MILESTONES)}"
        )
    clear_validation_state(run_dir)
    publish_config = deploy.resolve_publish_config()
    topic = load_run_topic(run_dir)
    manifest = json.loads((run_dir / "16_book" / "chapters_manifest.json").read_text())
    sidebar_src = json.loads((run_dir / "16_book" / "sidebar.json").read_text())
    parts = _parts_from_sidebar(sidebar_src)

    # 19.0 scaffold
    spec = dispatch.build_curator_spec(run_dir, topic=topic, manifest=manifest, parts=parts)
    dispatch.run_handbook_shards(run_dir, [spec], max_workers=1, executor=executor)
    scaffold.apply_scaffold(run_dir, publish_config=publish_config)

    # 19.5 (partial) — copy markdown into docs
    docs_dir = run_dir / "19_handbook/src/content/docs"
    page_extension = ".mdx" if milestone in {"M2", "M3"} else ".md"
    linker.copy_chapters_into_docs(
        run_dir,
        docs_dir,
        output_extension=page_extension,
        base_path=publish_config.base_path,
        require_sidebar=True,
    )
    linker.copy_paper_figures(run_dir, run_dir / "19_handbook")
    linker.write_index_pages(run_dir, docs_dir, base_path=publish_config.base_path)
    _sanitize_and_validate(run_dir, docs_dir, publish_config=publish_config)

    if milestone == "M0":
        _sanitize_and_validate(run_dir, docs_dir, publish_config=publish_config)
        if run_pnpm_build:
            from handbook_builder import build as build_step
            build_step.run_pnpm_build(run_dir, publish_config=publish_config)
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
        _sanitize_and_validate(run_dir, docs_dir, publish_config=publish_config)
        if run_pnpm_build:
            from handbook_builder import build as build_step
            build_step.run_pnpm_build(run_dir, publish_config=publish_config)
        return

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
        _sanitize_and_validate(run_dir, docs_dir, publish_config=publish_config)
        if run_pnpm_build:
            from handbook_builder import build as build_step
            build_step.run_pnpm_build(run_dir, publish_config=publish_config)
        return

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
        dst.write_text(ensure_head_default(candidate, fallback_title=cid.replace("_", " ").title()))

    if needs_review:
        review = run_dir / "19_handbook/NEEDS_REVIEW.md"
        review.write_text(
            "# Pages skipped by verifier-web\n\n"
            + "\n".join(f"- `{p}` — {reason}" for p, reason in needs_review)
        )

    if milestone == "M3":
        _sanitize_and_validate(run_dir, docs_dir, publish_config=publish_config)
        if run_pnpm_build:
            from handbook_builder import build as build_step
            build_step.run_pnpm_build(run_dir, publish_config=publish_config)
        return

    raise AssertionError(f"unhandled handbook milestone {milestone!r}")


def _parts_from_sidebar(sidebar: dict) -> list[dict]:
    parts: list[dict] = []
    for group in sidebar.get("items", []):
        if group.get("title") == "Book":
            continue
        method_ids = _method_ids_from_children(group.get("children", []))
        parts.append({"title": group["title"], "methods": method_ids})
    return parts


def _sanitize_and_validate(run_dir: Path, docs_dir: Path, *, publish_config: deploy.PublishConfig) -> None:
    sanitize_docs_tree(docs_dir)
    validate_source_site(run_dir, publish_config=publish_config)


def _method_ids_from_children(children: list[dict]) -> list[str]:
    method_ids: list[str] = []
    for child in children:
        nested = child.get("children") or []
        if nested:
            method_ids.extend(_method_ids_from_children(nested))
            continue
        path = child.get("path")
        if path:
            method_ids.append(_slug_id(path))
    return method_ids


def _slug_id(path: str) -> str:
    return path.rsplit("/", 1)[-1].removesuffix(".md").removesuffix(".mdx")
