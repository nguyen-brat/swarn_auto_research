from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


BOOK_FILE_BY_ID = {
    "preface": "00_preface.md",
    "motivating_intro": "01_motivating_intro.md",
    "core_concepts": "02_core_concepts.md",
    "goals": "03_goals.md",
    "method_taxonomy": "04_method_taxonomy.md",
    "shared_examples": "05_shared_examples.md",
    "evaluation_outlook": "98_evaluation_outlook.md",
    "appendices": "99_appendices.md",
}

NOISY_TITLE_PATTERNS = re.compile(
    r"([.!?])|(\d+(?:\.\d+)?\s*(?:x|%|k|m|b)\b)|"
    r"\b(reports?|reported|achieves?|outperforms?|reaches?|improves?|"
    r"evaluation|benchmark|speedup|acceleration|trained with|uses? \d+|"
    r"on \d+|with \d+)\b",
    re.IGNORECASE,
)

SECTION_HEADING_METHOD_ID_PATTERNS = re.compile(
    r"(^\d)|problem-formulation|prefilling-stage|observation-window|^pre-filling$",
    re.IGNORECASE,
)

METHOD_REQUIRED_SOURCE_SECTIONS = {"theory", "algorithm", "example", "limitations"}
METHOD_MIN_WORDS = 1500
FAMILY_MIN_WORDS = 1000
COPIED_SOURCE_OUTLINE_PATTERN = re.compile(
    r"^\s*[-*]\s+(?:\d+(?:\.\d+)*\s+[A-Z]|[A-Z]\.\d+\s+)|^\s*[-*]\s+Baselines\.?\s*$",
    re.IGNORECASE,
)
PLACEHOLDER_PATTERNS = re.compile(
    r"\b(serves as a navigation layer|variations on the same engineering pressure|"
    r"this file is regenerated deterministically|too thin|^none\.$)\b",
    re.IGNORECASE,
)


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _promoted_entries(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "07_scoring" / "promoted_papers.json"
    data = _load_json(path)
    raw = data.get("promoted_papers", data) if isinstance(data, dict) else data
    if isinstance(raw, dict):
        entries = []
        for arxiv_id, record in raw.items():
            if isinstance(record, dict):
                entries.append({"arxiv_id": arxiv_id, **record})
            else:
                entries.append({"arxiv_id": arxiv_id})
        return entries
    entries = []
    for record in raw:
        if isinstance(record, dict):
            arxiv_id = record.get("arxiv_id") or record.get("id")
            if arxiv_id:
                entries.append({"arxiv_id": arxiv_id, **record})
    return entries


def _paper_lookup(run_dir: Path) -> dict[str, dict[str, Any]]:
    path = run_dir / "02_paper_pool" / "paper_pool.json"
    lookup: dict[str, dict[str, Any]] = {}
    if path.exists():
        data = _load_json(path)
        records: list[dict[str, Any]] = []
        if isinstance(data, dict):
            if isinstance(data.get("papers"), list):
                records = [record for record in data["papers"] if isinstance(record, dict)]
            else:
                for arxiv_id, record in data.items():
                    if isinstance(record, dict):
                        merged = dict(record)
                        merged.setdefault("arxiv_id", arxiv_id)
                        records.append(merged)
        elif isinstance(data, list):
            records = [record for record in data if isinstance(record, dict)]
        for record in records:
            arxiv_id = record.get("arxiv_id")
            if not arxiv_id:
                continue
            lookup[arxiv_id] = dict(record)
    for directory in (run_dir / "03_overviews" / "semantic_scholar", run_dir / "04_weak_evidence"):
        if not directory.exists():
            continue
        for metadata_path in directory.glob("*.json"):
            record = _load_json(metadata_path)
            if not isinstance(record, dict):
                continue
            arxiv_id = record.get("arxiv_id") or metadata_path.stem
            merged = dict(lookup.get(arxiv_id, {}))
            for key in ("title", "year"):
                if record.get(key) and not merged.get(key):
                    merged[key] = record[key]
            lookup[arxiv_id] = merged
    return lookup


class MissingCitationError(LookupError):
    """Raised when a cited arxiv_id cannot be resolved to title+year."""


def resolve_paper_citation(run_dir: Path | str, arxiv_id: str) -> dict[str, Any]:
    """Resolve {arxiv_id, title, year} from paper_pool, semantic_scholar, or weak_evidence."""
    pool = _paper_lookup(Path(run_dir))
    record = pool.get(arxiv_id)
    if record is None:
        raise MissingCitationError(f"arxiv_id {arxiv_id} not found in paper_pool / overviews / weak_evidence")
    title = record.get("title") or ""
    year = record.get("year")
    if not title or year in (None, "", 0):
        raise MissingCitationError(
            f"arxiv_id {arxiv_id} missing title or year (title={title!r}, year={year!r})"
        )
    return {"arxiv_id": arxiv_id, "title": title, "year": year}


def _paper_label(arxiv_id: str, promoted: dict[str, dict[str, Any]], pool: dict[str, dict[str, Any]]) -> str:
    promoted_record = promoted.get(arxiv_id) or {}
    pool_record = pool.get(arxiv_id) or {}
    title = promoted_record.get("title") or pool_record.get("title")
    year = promoted_record.get("year") or pool_record.get("year")
    if not title or year in (None, "", 0):
        raise MissingCitationError(
            f"_paper_label cannot render {arxiv_id}: title={title!r}, year={year!r}. "
            "Add title/year to paper_pool, semantic_scholar overviews, or weak_evidence."
        )
    return f"[arxiv:{arxiv_id}] {title} ({year})"


def _outline(run_dir: Path) -> dict[str, Any]:
    return _load_json(run_dir / "12_taxonomy" / "outline.json")


def _manifest(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "16_book" / "chapters_manifest.json"
    return _load_json(path) if path.exists() else {"chapters": []}


def _normalize_title(title: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", title.strip().lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _word_count(text: str) -> int:
    _, body = _split_front_matter(text)
    return len(re.findall(r"\b\w+\b", body))


def _section_has_source_text(section: dict[str, Any]) -> bool:
    for source in section.get("source_nodes", []):
        if isinstance(source, dict) and source.get("section_text", "").strip():
            return True
    return False


def _body_without_citations(text: str) -> str:
    return re.sub(r"\[arxiv:[^\]]+\]", "", text)


def _markdown_sections(text: str) -> dict[str, str]:
    _, body = _split_front_matter(text)
    sections: dict[str, list[str]] = {}
    current = ""
    for line in body.splitlines():
        if line.startswith("## "):
            current = _normalize_title(line[3:])
            sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(line)
    return {title: "\n".join(lines).strip() for title, lines in sections.items()}


def _copied_source_outline_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if COPIED_SOURCE_OUTLINE_PATTERN.search(line))


def _split_front_matter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---\n", 4)
    if end == -1:
        return "", text
    return text[: end + len("\n---\n")], text[end + len("\n---\n") :]


def _write_markdown_preserving_front_matter(path: Path, body: str) -> None:
    front_matter = ""
    if path.exists():
        front_matter, _ = _split_front_matter(path.read_text(encoding="utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = front_matter + "\n" if front_matter else ""
    path.write_text(prefix + body.rstrip() + "\n", encoding="utf-8")


def validate_research_book_run(run_dir: Path | str) -> list[dict[str, str]]:
    run_path = Path(run_dir)
    issues: list[dict[str, str]] = []
    outline = _outline(run_path)
    manifest = _manifest(run_path)
    promoted = _promoted_entries(run_path)

    methods = outline.get("methods", [])
    families = outline.get("families", [])
    method_by_id = _method_by_id(outline)
    family_by_id = {family.get("id"): family for family in families if family.get("id")}

    book_section_ids = [section.get("id") for section in outline.get("book_sections", [])]
    expected_book_section_ids = list(BOOK_FILE_BY_ID)
    if book_section_ids != expected_book_section_ids:
        issues.append(
            {
                "severity": "error",
                "code": "invalid_book_sections",
                "detail": "book_sections must be the fixed 8-element Book_style order",
            }
        )

    method_ids: dict[str, int] = defaultdict(int)
    method_arxiv_counts: dict[str, int] = defaultdict(int)
    for method in methods:
        method_id = method.get("id", "")
        if method_id:
            method_ids[method_id] += 1
        arxiv_id = method.get("arxiv_id")
        if arxiv_id:
            method_arxiv_counts[arxiv_id] += 1

    for method_id, count in method_ids.items():
        if count > 1:
            issues.append(
                {
                    "severity": "error",
                    "code": "duplicate_method_id",
                    "detail": f"{method_id} appears {count} times in outline.json",
                }
            )

    for entry in promoted:
        arxiv_id = entry["arxiv_id"]
        count = method_arxiv_counts.get(arxiv_id, 0)
        if count == 0:
            issues.append(
                {
                    "severity": "error",
                    "code": "promoted_paper_without_method",
                    "detail": f"{arxiv_id} is promoted but has no method in outline.json",
                }
            )
        elif count > 1:
            issues.append(
                {
                    "severity": "error",
                    "code": "promoted_paper_with_multiple_methods",
                    "detail": f"{arxiv_id} is promoted but maps to {count} methods in outline.json",
                }
            )

    family_titles: dict[str, list[str]] = defaultdict(list)
    family_method_memberships: dict[str, list[str]] = defaultdict(list)
    for family in families:
        title = family.get("title", "")
        family_id = family.get("id", "")
        family_titles[_normalize_title(title)].append(family_id)
        if len(title) > 70 or NOISY_TITLE_PATTERNS.search(title):
            issues.append(
                {
                    "severity": "error",
                    "code": "noisy_family_title",
                    "detail": f"{family_id} has noisy title: {title}",
                }
            )
        if not family.get("method_ids"):
            issues.append(
                {
                    "severity": "error",
                    "code": "family_without_methods",
                    "detail": f"{family_id} has no method_ids",
                }
            )
        for method_id in family.get("method_ids", []):
            family_method_memberships[method_id].append(family_id)
            if method_id not in method_by_id:
                issues.append(
                    {
                        "severity": "error",
                        "code": "family_references_missing_method",
                        "detail": f"{family_id} references missing method {method_id}",
                    }
                )
    for title, ids in family_titles.items():
        if title and len(ids) > 1:
            issues.append(
                {
                    "severity": "error",
                    "code": "duplicate_family_title",
                    "detail": f"{title} appears in families: {', '.join(ids)}",
                }
            )

    for method in methods:
        method_id = method.get("id", "")
        family_id = method.get("family_id", "")
        if family_id not in family_by_id:
            issues.append(
                {
                    "severity": "error",
                    "code": "method_family_id_missing",
                    "detail": f"{method_id} has unresolved family_id {family_id}",
                }
            )
        memberships = family_method_memberships.get(method_id, [])
        if len(memberships) == 0:
            issues.append(
                {
                    "severity": "error",
                    "code": "method_not_listed_in_family",
                    "detail": f"{method_id} is not listed in any family method_ids",
                }
            )
        elif len(memberships) > 1:
            issues.append(
                {
                    "severity": "error",
                    "code": "method_listed_in_multiple_families",
                    "detail": f"{method_id} is listed in families: {', '.join(memberships)}",
                }
            )
        elif memberships[0] != family_id:
            issues.append(
                {
                    "severity": "error",
                    "code": "method_family_id_mismatch",
                    "detail": f"{method_id} declares {family_id} but is listed under {memberships[0]}",
                }
            )
        if SECTION_HEADING_METHOD_ID_PATTERNS.search(method_id):
            issues.append(
                {
                    "severity": "error",
                    "code": "section_heading_method_id",
                    "detail": f"{method_id} looks like a paper section heading, not a method slug",
                }
            )

    taxonomy_path = run_path / "14_chapters" / "book" / BOOK_FILE_BY_ID["method_taxonomy"]
    taxonomy_text = taxonomy_path.read_text(encoding="utf-8") if taxonomy_path.exists() else ""
    for family in families:
        family_id = family.get("id")
        expected_link = f"../families/{family_id}.md"
        if family_id and expected_link not in taxonomy_text:
            issues.append(
                {
                    "severity": "error",
                    "code": "method_taxonomy_missing_family_link",
                    "detail": f"{expected_link} is absent from 04_method_taxonomy.md",
                }
            )
    for method in methods:
        method_id = method.get("id")
        expected_link = f"../methods/{method_id}.md"
        if method_id and expected_link not in taxonomy_text:
            issues.append(
                {
                    "severity": "error",
                    "code": "method_taxonomy_missing_method_link",
                    "detail": f"{expected_link} is absent from 04_method_taxonomy.md",
                }
            )

    for section_id, filename in BOOK_FILE_BY_ID.items():
        if not (run_path / "14_chapters" / "book" / filename).exists():
            issues.append(
                {
                    "severity": "error",
                    "code": "missing_book_chapter",
                    "detail": f"14_chapters/book/{filename} is missing for {section_id}",
                }
            )
    for family in families:
        family_id = family.get("id")
        if family_id and not (run_path / "14_chapters" / "families" / f"{family_id}.md").exists():
            issues.append(
                {
                    "severity": "error",
                    "code": "missing_family_chapter",
                    "detail": f"14_chapters/families/{family_id}.md is missing",
                }
            )
    for method in methods:
        method_id = method.get("id")
        if method_id and not (run_path / "14_chapters" / "methods" / f"{method_id}.md").exists():
            issues.append(
                {
                    "severity": "error",
                    "code": "missing_method_chapter",
                    "detail": f"14_chapters/methods/{method_id}.md is missing",
                }
            )

    appendices_path = run_path / "14_chapters" / "book" / BOOK_FILE_BY_ID["appendices"]
    appendices_text = appendices_path.read_text(encoding="utf-8") if appendices_path.exists() else ""
    for entry in promoted:
        arxiv_id = entry["arxiv_id"]
        if f"[arxiv:{arxiv_id}]" not in appendices_text:
            issues.append(
                {
                    "severity": "error",
                    "code": "appendices_missing_promoted_reference",
                    "detail": f"{arxiv_id} is absent from 99_appendices.md",
                }
            )

    for family in families:
        family_id = family.get("id")
        if not family_id:
            continue
        family_path = run_path / "14_chapters" / "families" / f"{family_id}.md"
        if family_path.exists():
            family_text = family_path.read_text(encoding="utf-8")
            words = _word_count(family_text)
            if words < FAMILY_MIN_WORDS:
                issues.append(
                    {
                        "severity": "error",
                        "code": "family_chapter_word_count_low",
                        "detail": f"{family_id} has {words} words; expected at least {FAMILY_MIN_WORDS}",
                    }
                )
            if PLACEHOLDER_PATTERNS.search(family_text):
                issues.append(
                    {
                        "severity": "error",
                        "code": "family_placeholder_prose",
                        "detail": f"{family_id} contains generic placeholder prose",
                    }
                )
            if "## Core design pattern" not in family_text:
                issues.append(
                    {
                        "severity": "error",
                        "code": "family_core_design_pattern_missing",
                        "detail": f"{family_id} is missing ## Core design pattern",
                    }
                )

    for method in methods:
        method_id = method.get("id")
        if not method_id:
            continue
        pack_path = run_path / "13_chapter_packs" / "methods" / f"{method_id}_pack.json"
        if not pack_path.exists():
            issues.append(
                {
                    "severity": "error",
                    "code": "missing_method_pack",
                    "detail": f"13_chapter_packs/methods/{method_id}_pack.json is missing",
                }
            )
        else:
            pack = _load_json(pack_path)
            sections_with_text = {
                _normalize_title(section.get("section_title", "")).replace(" ", "_")
                for section in pack.get("section_plan", [])
                if isinstance(section, dict) and _section_has_source_text(section)
            }
            missing_sections = sorted(METHOD_REQUIRED_SOURCE_SECTIONS - sections_with_text)
            if missing_sections:
                issues.append(
                    {
                        "severity": "error",
                        "code": "method_pack_missing_required_section_text",
                        "detail": f"{method_id} lacks section_text for: {', '.join(missing_sections)}",
                    }
                )

        method_path = run_path / "14_chapters" / "methods" / f"{method_id}.md"
        if method_path.exists():
            method_text = method_path.read_text(encoding="utf-8")
            words = _word_count(method_text)
            if words < METHOD_MIN_WORDS:
                issues.append(
                    {
                        "severity": "error",
                        "code": "method_chapter_word_count_low",
                        "detail": f"{method_id} has {words} words; expected at least {METHOD_MIN_WORDS}",
                    }
                )
            outline_count = _copied_source_outline_count(method_text)
            if outline_count >= 8:
                issues.append(
                    {
                        "severity": "error",
                        "code": "method_chapter_copied_source_outline",
                        "detail": f"{method_id} contains {outline_count} copied source-outline lines",
                    }
                )
            for section_title, section_body in _markdown_sections(method_text).items():
                if section_title in {"software", "related methods", "references"}:
                    continue
                non_citation_words = len(re.findall(r"\b\w+\b", _body_without_citations(section_body)))
                if non_citation_words < 20:
                    issues.append(
                        {
                            "severity": "error",
                            "code": "method_chapter_citation_only_section",
                            "detail": f"{method_id}:{section_title} has fewer than 20 non-citation words",
                        }
                    )
                    break

    for chapter in manifest.get("chapters", []):
        chapter_type = chapter.get("chapter_type")
        chapter_id = chapter.get("chapter_id")
        if chapter.get("status") == "passed":
            if chapter_type == "method" and int(chapter.get("word_count") or 0) < METHOD_MIN_WORDS:
                issues.append(
                    {
                        "severity": "error",
                        "code": "passed_method_chapter_word_count_low",
                        "detail": f"{chapter_id} is marked passed with {chapter.get('word_count')} words",
                    }
                )
            if chapter_type == "family" and int(chapter.get("word_count") or 0) < FAMILY_MIN_WORDS:
                issues.append(
                    {
                        "severity": "error",
                        "code": "passed_family_chapter_word_count_low",
                        "detail": f"{chapter_id} is marked passed with {chapter.get('word_count')} words",
                    }
                )
        if chapter.get("status") != "passed":
            issues.append(
                {
                    "severity": "warning",
                    "code": "chapter_not_passed",
                    "detail": f"{chapter.get('chapter_type')}:{chapter.get('chapter_id')} is {chapter.get('status')}",
                }
            )
    return issues


def _method_by_id(outline: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {method["id"]: method for method in outline.get("methods", [])}


def _book_chapter_path(section_id: str) -> str:
    return f"14_chapters/book/{BOOK_FILE_BY_ID.get(section_id, section_id + '.md')}"


def _build_method_taxonomy(outline: dict[str, Any]) -> str:
    methods = _method_by_id(outline)
    lines = [
        "# Method Taxonomy",
        "",
        "This section is generated from `12_taxonomy/outline.json` so it stays complete and navigable.",
        "",
        "## Family Map",
        "",
    ]
    for family in outline.get("families", []):
        family_id = family["id"]
        lines.append(f"- [{family['title']}](../families/{family_id}.md)")
        for method_id in family.get("method_ids", []):
            method = methods.get(method_id)
            if not method:
                continue
            arxiv_id = method.get("arxiv_id", "")
            lines.append(f"  - [{method['title']}](../methods/{method_id}.md) [arxiv:{arxiv_id}]")
    lines.extend(["", "## Boundary Notes", ""])
    for family in outline.get("families", []):
        neighbors = family.get("neighbor_family_ids") or []
        neighbor_text = ", ".join(f"`{neighbor}`" for neighbor in neighbors) or "no explicit neighboring families"
        lines.append(
            f"- **[{family['title']}](../families/{family['id']}.md)** contains "
            f"{len(family.get('method_ids', []))} method(s); neighboring families: {neighbor_text}."
        )
    return "\n".join(lines)


def _build_appendices(run_dir: Path, outline: dict[str, Any]) -> str:
    promoted_entries = _promoted_entries(run_dir)
    promoted_by_id = {entry["arxiv_id"]: entry for entry in promoted_entries}
    pool = _paper_lookup(run_dir)
    gap_terms = sorted(
        {
            term
            for family in outline.get("families", [])
            for term in family.get("knowledge_gaps_to_explain", [])
        }
        | {
            term
            for method in outline.get("methods", [])
            for term in method.get("knowledge_gaps_to_explain", [])
        }
    )
    lines = [
        "# Appendices",
        "",
        "## References",
        "",
    ]
    for arxiv_id in sorted(promoted_by_id):
        lines.append(f"- {_paper_label(arxiv_id, promoted_by_id, pool)}")
    lines.extend(["", "## Glossary", ""])
    if gap_terms:
        for term in gap_terms:
            lines.append(f"- **{term}**: concept marked for explanation by the taxonomy.")
    else:
        lines.append("- No taxonomy-level knowledge gaps were recorded.")
    return "\n".join(lines)


def _build_summary(outline: dict[str, Any]) -> str:
    methods = _method_by_id(outline)
    lines = ["# Summary", "", "## Book", ""]
    for section in outline.get("book_sections", []):
        section_id = section["id"]
        filename = BOOK_FILE_BY_ID.get(section_id)
        if filename:
            lines.append(f"- [{section['title']}](../14_chapters/book/{filename})")
    lines.extend(["", "## Families and Methods", ""])
    for family in outline.get("families", []):
        family_id = family["id"]
        lines.append(f"- [{family['title']}](../14_chapters/families/{family_id}.md)")
        for method_id in family.get("method_ids", []):
            method = methods.get(method_id)
            if method:
                lines.append(f"  - [{method['title']}](../14_chapters/methods/{method_id}.md)")
    return "\n".join(lines)


def _build_sidebar(outline: dict[str, Any]) -> dict[str, Any]:
    methods = _method_by_id(outline)
    book_items = []
    for section in outline.get("book_sections", []):
        filename = BOOK_FILE_BY_ID.get(section["id"])
        if filename:
            book_items.append({"title": section["title"], "path": f"14_chapters/book/{filename}"})
    family_items = []
    for family in outline.get("families", []):
        children = []
        for method_id in family.get("method_ids", []):
            method = methods.get(method_id)
            if method:
                children.append({"title": method["title"], "path": f"14_chapters/methods/{method_id}.md"})
        family_items.append(
            {
                "title": family["title"],
                "path": f"14_chapters/families/{family['id']}.md",
                "children": children,
            }
        )
    return {"items": [{"title": "Book", "children": book_items}, {"title": "Families", "children": family_items}]}


def generate_book_artifacts(run_dir: Path | str) -> dict[str, int]:
    run_path = Path(run_dir)
    outline = _outline(run_path)
    taxonomy_path = run_path / "14_chapters" / "book" / BOOK_FILE_BY_ID["method_taxonomy"]
    appendices_path = run_path / "14_chapters" / "book" / BOOK_FILE_BY_ID["appendices"]
    _write_markdown_preserving_front_matter(taxonomy_path, _build_method_taxonomy(outline))
    _write_markdown_preserving_front_matter(appendices_path, _build_appendices(run_path, outline))
    (run_path / "16_book").mkdir(parents=True, exist_ok=True)
    (run_path / "16_book" / "SUMMARY.md").write_text(_build_summary(outline) + "\n", encoding="utf-8")
    _write_json(run_path / "16_book" / "sidebar.json", _build_sidebar(outline))
    return {"families": len(outline.get("families", [])), "methods": len(outline.get("methods", []))}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and generate deterministic research-book artifacts.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()

    if args.generate:
        result = generate_book_artifacts(args.run_dir)
        print(f"generated: {result['families']} families, {result['methods']} methods")
    if args.validate or not args.generate:
        issues = validate_research_book_run(args.run_dir)
        for issue in issues:
            prefix = issue.get("severity", "error")
            print(f"{prefix}: {issue['code']}: {issue['detail']}")
        if any(issue.get("severity", "error") == "error" for issue in issues):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
