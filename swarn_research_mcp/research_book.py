from __future__ import annotations

import argparse
import copy as _copy
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
    "appendices": "appendices",
}

NOISY_TITLE_PATTERNS = re.compile(
    r"([.!?])|(\d+(?:\.\d+)?\s*(?:x|%|k|m|b)\b)|"
    r"\b(reports?|reported|achieves?|outperforms?|reaches?|improves?|"
    r"speedup|acceleration|trained with|uses? \d+|"
    r"on \d+|with \d+)\b",
    re.IGNORECASE,
)

SECTION_HEADING_METHOD_ID_PATTERNS = re.compile(
    r"(^\d)|problem-formulation|prefilling-stage|observation-window|^pre-filling$",
    re.IGNORECASE,
)

METHOD_REQUIRED_SOURCE_SECTIONS = {"theory", "algorithm", "example", "limitations"}
FAMILY_REQUIRED_HEADINGS = [
    "## Summary",
    "## Motivation",
    "## Core Idea",
    "## Common Pipeline",
    "## Main Variants",
    "## Representative Methods",
    "## Strengths",
    "## Limitations",
    "## When to Use",
    "## Related Families",
]
METHOD_REQUIRED_HEADINGS = [
    "## Summary",
    "## Motivation",
    "## Intuition",
    "## Theory",
    "## Algorithm",
    "## Worked Example",
    "## Interpretation",
    "## Strengths",
    "## Limitations",
    "## Practical Guidance",
    "## Related Methods",
]
METHOD_MIN_WORDS = 1500
FAMILY_MIN_WORDS = 1000
STANDALONE_GROUP_ID = "standalone"
STANDALONE_PART_ID = "standalone_methods"
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


def _method_display_title(method: dict[str, Any], method_id: str) -> str:
    title = str(method.get("title") or method_id)
    readable_id = method_id.replace("-", " ")
    normalized_title = title.lower()
    has_method_id = re.search(rf"(?<!\w){re.escape(method_id.lower())}(?!\w)", normalized_title)
    readable_pattern = r"\s+".join(re.escape(part) for part in readable_id.lower().split())
    has_readable_id = re.search(
        rf"(?<!\w){readable_pattern}(?!\w)",
        normalized_title,
    )
    if has_method_id or has_readable_id:
        return title
    return f"{title} ({method_id})"


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


def _diff_headings(text: str, required: list[str]) -> dict[str, Any]:
    """Return missing/extra/order diagnostics. Allows trailing ## References."""
    headings = [line.strip() for line in text.splitlines() if line.strip().startswith("## ")]
    if headings and headings[-1] == "## References":
        headings = headings[:-1]
    required_set = set(required)
    observed_set = set(headings)
    missing = [heading for heading in required if heading not in observed_set]
    extra = [heading for heading in headings if heading not in required_set]
    observed_required = [heading for heading in headings if heading in required_set]
    expected_observed_order = [heading for heading in required if heading in set(observed_required)]
    out_of_order = observed_required != expected_observed_order
    return {"missing": missing, "extra": extra, "out_of_order": out_of_order}


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


def collect_excluded(run_dir: Path | str) -> list[dict[str, str]]:
    """Return chapters whose front-matter status starts with excluded_."""
    run_path = Path(run_dir)
    offenders: list[dict[str, str]] = []
    for sub in ("families", "methods", "book"):
        directory = run_path / "14_chapters" / sub
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.md")):
            front, _ = _split_front_matter(path.read_text(encoding="utf-8"))
            if not front:
                continue
            chapter_id = ""
            status = ""
            reason = ""
            for line in front.splitlines():
                line = line.strip()
                if line.startswith("chapter_id:"):
                    chapter_id = line.split(":", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("status:"):
                    status = line.split(":", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("status_reason:"):
                    reason = line.split(":", 1)[1].strip().strip('"').strip("'")
            if status.startswith("excluded_"):
                offenders.append(
                    {
                        "type": sub,
                        "id": chapter_id or path.stem,
                        "status": status,
                        "reason": reason,
                    }
                )
    return offenders


def write_needs_review(run_dir: Path | str, offenders: list[dict[str, str]]) -> None:
    """Emit a review file for quarantined chapters and citation issues."""
    out = Path(run_dir) / "16_book" / "NEEDS_REVIEW.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Needs Review",
        "",
        "These chapters or citations need review. Excluded chapters are NOT linked from SUMMARY.md.",
        "Excluded chapters remain on disk under `14_chapters/` and can be re-attempted with",
        "`phase=write fix_excluded=true`.",
        "Missing citation metadata is surfaced here while the book still renders.",
        "",
        "## Items",
        "",
    ]
    if not offenders:
        lines.append("_(none - every chapter and citation passed)_")
    for offender in offenders:
        lines.append(
            f"- **{offender['type']}/{offender['id']}** - "
            f"`{offender['status']}` ({offender['reason']})"
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _validate_parts(outline: dict[str, Any], families: list[dict[str, Any]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    parts = outline.get("parts")
    if parts is None:
        issues.append(
            {
                "severity": "error",
                "code": "missing_parts",
                "detail": "outline.json must define a 'parts' array (2..5 entries)",
            }
        )
        return issues
    # 2..5 normal parts, plus an optional standalone_methods part on top.
    normal_parts = (
        [p for p in parts if isinstance(p, dict) and p.get("id") != STANDALONE_PART_ID]
        if isinstance(parts, list)
        else []
    )
    if not isinstance(parts, list) or not (2 <= len(normal_parts) <= 5):
        n = len(normal_parts) if isinstance(parts, list) else "non-list"
        issues.append(
            {
                "severity": "error",
                "code": "parts_count_out_of_range",
                "detail": f"parts must have 2..5 entries (excluding {STANDALONE_PART_ID}), got {n}",
            }
        )
        return issues
    family_ids = {f.get("id") for f in families if f.get("id")}
    seen_in: dict[str, str] = {}
    for part in parts:
        pid = part.get("id", "")
        fids = part.get("family_ids", []) or []
        if not fids:
            issues.append({"severity": "error", "code": "empty_part", "detail": f"part {pid} has no families"})
        for fid in fids:
            if fid in seen_in:
                issues.append(
                    {
                        "severity": "error",
                        "code": "family_in_multiple_parts",
                        "detail": f"family {fid} appears in parts {seen_in[fid]} and {pid}",
                    }
                )
            else:
                seen_in[fid] = pid
    for fid in family_ids:
        if fid not in seen_in:
            issues.append(
                {
                    "severity": "error",
                    "code": "family_unassigned_to_part",
                    "detail": f"family {fid} is not in any part",
                }
            )
    return issues


def validate_research_book_run(run_dir: Path | str) -> list[dict[str, str]]:
    run_path = Path(run_dir)
    issues: list[dict[str, str]] = []
    outline = _outline(run_path)
    manifest = _manifest(run_path)
    promoted = _promoted_entries(run_path)
    offenders = collect_excluded(run_path)
    excluded_family_method_ids = {
        offender["id"]
        for offender in offenders
        if offender.get("type") in ("families", "methods") and offender.get("id")
    }

    methods = outline.get("methods", [])
    families = outline.get("families", [])
    issues.extend(_validate_parts(outline, families))
    chapters_dir = run_path / "14_chapters"
    for family in families:
        family_id = family.get("id")
        if family.get("is_group") or not family_id:
            continue
        family_path = chapters_dir / "families" / f"{family_id}.md"
        if not family_path.exists():
            continue
        diff = _diff_headings(family_path.read_text(encoding="utf-8"), FAMILY_REQUIRED_HEADINGS)
        if diff["missing"] or diff["extra"] or diff["out_of_order"]:
            issues.append(
                {
                    "severity": "error",
                    "code": "wrong_chapter_headings",
                    "detail": (
                        f"family/{family_id}: missing={diff['missing']} "
                        f"extra={diff['extra']} out_of_order={diff['out_of_order']}"
                    ),
                }
            )
    for method in methods:
        method_id = method.get("id")
        if not method_id:
            continue
        method_path = chapters_dir / "methods" / f"{method_id}.md"
        if not method_path.exists():
            continue
        diff = _diff_headings(method_path.read_text(encoding="utf-8"), METHOD_REQUIRED_HEADINGS)
        if diff["missing"] or diff["extra"] or diff["out_of_order"]:
            issues.append(
                {
                    "severity": "error",
                    "code": "wrong_chapter_headings",
                    "detail": (
                        f"method/{method_id}: missing={diff['missing']} "
                        f"extra={diff['extra']} out_of_order={diff['out_of_order']}"
                    ),
                }
            )
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
        if family.get("is_group"):
            continue
        family_id = family.get("id")
        if family_id in excluded_family_method_ids:
            continue
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
        if method_id in excluded_family_method_ids:
            continue
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
        target = run_path / "14_chapters" / "book" / filename
        if section_id == "appendices":
            ok = target.is_dir() and all(
                (target / sub).exists()
                for sub in ("glossary.md", "notation.md", "datasets.md", "software.md", "references.md")
            )
        else:
            ok = target.exists()
        if not ok:
            issues.append(
                {
                    "severity": "error",
                    "code": "missing_book_chapter",
                    "detail": f"14_chapters/book/{filename} is missing for {section_id}",
                }
            )
    for family in families:
        if family.get("is_group"):
            continue
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

    for family in families:
        if family.get("is_group"):
            continue
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


def _graph_evidence_score(singleton: dict, candidate: dict, method_by_id: dict) -> int:
    s_method = method_by_id[singleton["method_ids"][0]]
    s_neighbor_methods = set(s_method.get("neighbor_method_ids", []) or [])
    s_neighbor_families = set(singleton.get("neighbor_family_ids", []) or [])
    cand_methods = set(candidate.get("method_ids", []) or [])
    shared = len(s_neighbor_methods & cand_methods)
    if shared >= 2:
        return shared
    if candidate["id"] in s_neighbor_families and shared >= 1:
        return shared
    return 0


def _has_strong_graph_evidence(singleton: dict, candidate: dict, method_by_id: dict) -> bool:
    return _graph_evidence_score(singleton, candidate, method_by_id) > 0


def _prune_invalid_outline_links(outline: dict[str, Any]) -> dict[str, Any]:
    families = outline.get("families", []) or []
    methods = outline.get("methods", []) or []
    family_ids = {family["id"] for family in families}
    method_ids = {method["id"] for method in methods}

    for family in families:
        neighbors = family.get("neighbor_family_ids")
        if neighbors is not None:
            family["neighbor_family_ids"] = [fid for fid in neighbors if fid in family_ids and fid != family["id"]]

    for method in methods:
        neighbors = method.get("neighbor_method_ids")
        if neighbors is not None:
            method["neighbor_method_ids"] = [mid for mid in neighbors if mid in method_ids and mid != method["id"]]

    return outline


def merge_singletons(outline: dict[str, Any]) -> dict[str, Any]:
    """Stage 12.5 post-processor for singleton families."""
    out = _copy.deepcopy(outline)
    families: list[dict[str, Any]] = out["families"]
    methods: list[dict[str, Any]] = out["methods"]
    method_by_id = {m["id"]: m for m in methods}
    parts = out.get("parts") or []

    original_singletons = sorted(
        (
            f
            for f in families
            if len(f.get("method_ids", [])) == 1 and f["id"] != STANDALONE_GROUP_ID
        ),
        key=lambda f: f["id"],
    )
    if not original_singletons:
        return _prune_invalid_outline_links(out)

    original_singleton_method_ids = {f["id"]: f["method_ids"][0] for f in original_singletons}
    multi_method_families = [
        f
        for f in families
        if f["id"] != STANDALONE_GROUP_ID and len(f.get("method_ids", [])) >= 2
    ]
    reserved_singleton_ids: set[str] = set()
    reserved_family_id: str | None = None
    if len(multi_method_families) == 1 and len(original_singletons) >= 2:
        reserved = original_singletons[-2:]
        reserved_singleton_ids = {f["id"] for f in reserved}
        reserved_family_id = reserved[0]["id"]
        reserved[0]["title"] = "Complementary Methods"
        reserved[0]["method_ids"] = []
        reserved[0]["neighbor_family_ids"] = []

    for singleton in original_singletons:
        sid = singleton["id"]
        if not any(f["id"] == sid for f in families):
            continue
        s_method_id = original_singleton_method_ids[sid]

        if sid in reserved_singleton_ids and reserved_family_id is not None:
            reserve_family = next(f for f in families if f["id"] == reserved_family_id)
            reserve_family["method_ids"] = list(reserve_family.get("method_ids", [])) + [s_method_id]
            method_by_id[s_method_id]["family_id"] = reserved_family_id
            if sid != reserved_family_id:
                families = [f for f in families if f["id"] != sid]
                for part in parts:
                    fids = part.get("family_ids", []) or []
                    part["family_ids"] = [fid for fid in fids if fid != sid]
            continue

        candidates = [
            f
            for f in families
            if f["id"] != sid and f["id"] != STANDALONE_GROUP_ID and len(f.get("method_ids", [])) >= 2
        ]

        scored_candidates = []
        for cand in candidates:
            score = _graph_evidence_score(singleton, cand, method_by_id)
            if score > 0:
                scored_candidates.append((score, cand["id"], cand))
        winner = None
        if scored_candidates:
            winner = sorted(scored_candidates, key=lambda item: (-item[0], item[1]))[0][2]

        if winner is not None:
            winner["method_ids"] = list(winner["method_ids"]) + [s_method_id]
            method_by_id[s_method_id]["family_id"] = winner["id"]
        else:
            standalone = next((f for f in families if f["id"] == STANDALONE_GROUP_ID), None)
            if standalone is None:
                standalone = {
                    "id": STANDALONE_GROUP_ID,
                    "title": "Standalone / Emerging Methods",
                    "method_ids": [],
                    "neighbor_family_ids": [],
                    "is_group": True,
                }
                families.append(standalone)
                if not any(p["id"] == STANDALONE_PART_ID for p in parts):
                    parts.append(
                        {
                            "id": STANDALONE_PART_ID,
                            "title": "Standalone / Emerging Methods",
                            "family_ids": [STANDALONE_GROUP_ID],
                        }
                    )
                else:
                    sp = next(p for p in parts if p["id"] == STANDALONE_PART_ID)
                    if STANDALONE_GROUP_ID not in (sp.get("family_ids") or []):
                        sp.setdefault("family_ids", []).append(STANDALONE_GROUP_ID)
            standalone["method_ids"] = list(standalone["method_ids"]) + [s_method_id]
            method_by_id[s_method_id]["family_id"] = STANDALONE_GROUP_ID

        families = [f for f in families if f["id"] != sid]
        for part in parts:
            fids = part.get("family_ids", []) or []
            part["family_ids"] = [fid for fid in fids if fid != sid]

    parts = [p for p in parts if (p.get("family_ids") or []) or p.get("id") == STANDALONE_PART_ID]
    out["families"] = families
    out["parts"] = parts
    return _prune_invalid_outline_links(out)


def assert_no_singletons(outline: dict[str, Any]) -> None:
    """Stage 18 precondition: single-method families must be the standalone group."""
    bad = [
        f["id"]
        for f in outline.get("families", [])
        if len(f.get("method_ids", [])) == 1 and f["id"] != STANDALONE_GROUP_ID
    ]
    if bad:
        raise RuntimeError(
            f"outline.json has singleton families {bad}; run --normalize-outline "
            "(stage 12.5) before generate_book_artifacts."
        )


def _book_chapter_path(section_id: str) -> str:
    return f"14_chapters/book/{BOOK_FILE_BY_ID.get(section_id, section_id + '.md')}"


def _build_method_taxonomy(outline: dict[str, Any], excluded: set[str] | None = None) -> str:
    excluded = excluded or set()
    methods = _method_by_id(outline)
    family_by_id = {family["id"]: family for family in outline.get("families", [])}
    lines = [
        "# Method Taxonomy",
        "",
        "This taxonomy is generated from `12_taxonomy/outline.json` so it stays complete and navigable.",
        "",
    ]
    for idx, part in enumerate(outline.get("parts", []) or [], start=1):
        lines.extend(["", f"## Part {idx}: {part['title']}", ""])
        for family_id in part.get("family_ids", []) or []:
            family = family_by_id.get(family_id)
            if not family:
                continue
            family_excluded = family_id in excluded
            passed_methods = [method_id for method_id in (family.get("method_ids") or []) if method_id not in excluded]
            if family.get("is_group") or family_excluded:
                for method_id in passed_methods:
                    method = methods.get(method_id)
                    if method:
                        lines.append(
                            f"- [{method['title']}](../methods/{method_id}.md) "
                            f"[arxiv:{method.get('arxiv_id', '')}]"
                        )
            else:
                lines.append(f"- [{family['title']}](../families/{family_id}.md)")
                for method_id in passed_methods:
                    method = methods.get(method_id)
                    if method:
                        lines.append(
                            f"  - [{method['title']}](../methods/{method_id}.md) "
                            f"[arxiv:{method.get('arxiv_id', '')}]"
                        )
    return "\n".join(lines)


def _build_appendices_dir(run_dir: Path, outline: dict[str, Any]) -> list[dict[str, str]]:
    out_dir = run_dir / "14_chapters" / "book" / "appendices"
    out_dir.mkdir(parents=True, exist_ok=True)

    snap = run_dir / "06_expansion" / "known_concepts_snapshot.json"
    glossary = ["# Glossary", ""]
    if snap.exists():
        for entry in (_load_json(snap).get("known_concepts") or []):
            name = entry.get("name") or entry.get("id") or ""
            definition = entry.get("definition") or entry.get("summary") or ""
            if name:
                glossary.append(f"- **{name}** - {definition}")
    (out_dir / "glossary.md").write_text("\n".join(glossary) + "\n", encoding="utf-8")

    packs_dir = run_dir / "13_chapter_packs" / "methods"

    def _harvest(field: str, header: str) -> list[str]:
        seen: set[str] = set()
        lines = [f"# {header}", ""]
        if packs_dir.exists():
            for pack_path in sorted(packs_dir.glob("*_pack.json")):
                pack = _load_json(pack_path)
                for entry in (pack.get("structured", {}).get(field) or []):
                    name = entry.get("name") or ""
                    if name and name not in seen:
                        seen.add(name)
                        if field == "equations":
                            for symbol in entry.get("symbols", []) or []:
                                symbol_name = symbol.get("name") or ""
                                symbol_desc = symbol.get("description") or ""
                                if symbol_name and symbol_name not in seen:
                                    seen.add(symbol_name)
                                    lines.append(f"- `{symbol_name}` - {symbol_desc}")
                        else:
                            lines.append(f"- {name}")
        return lines

    notation = ["# Notation", ""]
    seen_notation: set[str] = set()
    if packs_dir.exists():
        for pack_path in sorted(packs_dir.glob("*_pack.json")):
            pack = _load_json(pack_path)
            for equation in (pack.get("structured", {}).get("equations") or []):
                for symbol in equation.get("symbols", []) or []:
                    symbol_name = symbol.get("name") or ""
                    symbol_desc = symbol.get("description") or ""
                    if symbol_name and symbol_name not in seen_notation:
                        seen_notation.add(symbol_name)
                        notation.append(f"- `{symbol_name}` - {symbol_desc}")
    (out_dir / "notation.md").write_text("\n".join(notation) + "\n", encoding="utf-8")
    (out_dir / "datasets.md").write_text("\n".join(_harvest("datasets", "Datasets")) + "\n", encoding="utf-8")
    (out_dir / "software.md").write_text(
        "\n".join(_harvest("artifacts", "Software and Artifacts")) + "\n", encoding="utf-8"
    )

    refs = ["# References", ""]
    citation_issues: list[dict[str, str]] = []
    for entry in sorted(_promoted_entries(run_dir), key=lambda item: item.get("arxiv_id", "")):
        arxiv_id = entry.get("arxiv_id", "")
        if not arxiv_id:
            continue
        try:
            cite = resolve_paper_citation(run_dir, arxiv_id)
            refs.append(f"- [arxiv:{cite['arxiv_id']}] {cite['title']} ({cite['year']})")
        except MissingCitationError as exc:
            refs.append(f"- [arxiv:{arxiv_id}] <citation metadata missing> (see NEEDS_REVIEW.md)")
            citation_issues.append(
                {
                    "type": "citation",
                    "id": arxiv_id,
                    "status": "missing_citation_metadata",
                    "reason": str(exc),
                }
            )
    (out_dir / "references.md").write_text("\n".join(refs) + "\n", encoding="utf-8")
    return citation_issues


def _build_summary(
    outline: dict[str, Any],
    excluded: set[str] | None = None,
    excluded_book_ids: set[str] | None = None,
) -> str:
    excluded = excluded or set()
    excluded_book_ids = excluded_book_ids or set()
    methods = _method_by_id(outline)
    family_by_id = {family["id"]: family for family in outline.get("families", [])}
    lines = ["# Summary", "", "## Book", ""]
    for section in outline.get("book_sections", []):
        section_id = section["id"]
        if section_id in excluded_book_ids:
            continue
        filename = BOOK_FILE_BY_ID.get(section_id)
        if not filename:
            continue
        if section_id == "appendices":
            href = f"../14_chapters/book/{filename}/glossary.md"
        else:
            href = f"../14_chapters/book/{filename}"
        lines.append(f"- [{section['title']}]({href})")

    for idx, part in enumerate(outline.get("parts", []) or [], start=1):
        lines.extend(["", f"## Part {idx}: {part['title']}", ""])
        for family_id in part.get("family_ids", []) or []:
            family = family_by_id.get(family_id)
            if not family:
                continue
            family_excluded = family_id in excluded
            passed_methods = [method_id for method_id in (family.get("method_ids") or []) if method_id not in excluded]
            if family.get("is_group") or family_excluded:
                for method_id in passed_methods:
                    method = methods.get(method_id)
                    if method:
                        title = _method_display_title(method, method_id)
                        lines.append(f"- [{title}](../14_chapters/methods/{method_id}.md)")
            else:
                lines.append(f"- [{family['title']}](../14_chapters/families/{family_id}.md)")
                for method_id in passed_methods:
                    method = methods.get(method_id)
                    if method:
                        title = _method_display_title(method, method_id)
                        lines.append(f"  - [{title}](../14_chapters/methods/{method_id}.md)")
    return "\n".join(lines)


def _build_sidebar(
    outline: dict[str, Any],
    excluded: set[str] | None = None,
    excluded_book_ids: set[str] | None = None,
) -> dict[str, Any]:
    excluded = excluded or set()
    excluded_book_ids = excluded_book_ids or set()
    methods = _method_by_id(outline)
    family_by_id = {family["id"]: family for family in outline.get("families", [])}
    book_items = []
    for section in outline.get("book_sections", []):
        if section["id"] in excluded_book_ids:
            continue
        filename = BOOK_FILE_BY_ID.get(section["id"])
        if not filename:
            continue
        path = (
            f"14_chapters/book/{filename}/glossary.md"
            if section["id"] == "appendices"
            else f"14_chapters/book/{filename}"
        )
        book_items.append({"title": section["title"], "path": path})

    part_items = []
    for part in outline.get("parts", []) or []:
        children = []
        for family_id in part.get("family_ids", []) or []:
            family = family_by_id.get(family_id)
            if not family:
                continue
            family_excluded = family_id in excluded
            passed_methods = [method_id for method_id in (family.get("method_ids") or []) if method_id not in excluded]
            if family.get("is_group") or family_excluded:
                for method_id in passed_methods:
                    method = methods.get(method_id)
                    if method:
                        children.append(
                            {
                                "title": _method_display_title(method, method_id),
                                "path": f"14_chapters/methods/{method_id}.md",
                            }
                        )
            else:
                method_kids = []
                for method_id in passed_methods:
                    method = methods.get(method_id)
                    if method:
                        method_kids.append(
                            {
                                "title": _method_display_title(method, method_id),
                                "path": f"14_chapters/methods/{method_id}.md",
                            }
                        )
                children.append(
                    {
                        "title": family["title"],
                        "path": f"14_chapters/families/{family_id}.md",
                        "children": method_kids,
                    }
                )
        part_items.append({"title": part["title"], "children": children})
    return {"items": [{"title": "Book", "children": book_items}] + part_items}


def generate_book_artifacts(run_dir: Path | str) -> dict[str, int]:
    run_path = Path(run_dir)
    outline = _outline(run_path)
    assert_no_singletons(outline)
    offenders = collect_excluded(run_path)
    excluded_family_method_ids = {o["id"] for o in offenders if o["type"] in ("families", "methods")}
    excluded_book_ids = {o["id"] for o in offenders if o["type"] == "book"}

    taxonomy_path = run_path / "14_chapters" / "book" / BOOK_FILE_BY_ID["method_taxonomy"]
    _write_markdown_preserving_front_matter(
        taxonomy_path, _build_method_taxonomy(outline, excluded_family_method_ids)
    )
    citation_issues = _build_appendices_dir(run_path, outline)
    all_needs_review = offenders + citation_issues
    write_needs_review(run_path, all_needs_review)

    (run_path / "16_book").mkdir(parents=True, exist_ok=True)
    (run_path / "16_book" / "SUMMARY.md").write_text(
        _build_summary(outline, excluded_family_method_ids, excluded_book_ids) + "\n",
        encoding="utf-8",
    )
    _write_json(
        run_path / "16_book" / "sidebar.json",
        _build_sidebar(outline, excluded_family_method_ids, excluded_book_ids),
    )
    return {
        "families": len(outline.get("families", [])),
        "methods": len(outline.get("methods", [])),
        "quarantined": len(offenders),
        "needs_review": len(all_needs_review),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and generate deterministic research-book artifacts.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument(
        "--normalize-outline",
        action="store_true",
        help="Stage 12.5: read 12_taxonomy/outline.json, run merge_singletons, write back if changed.",
    )
    args = parser.parse_args()

    if args.normalize_outline:
        run_path = Path(args.run_dir)
        outline = _outline(run_path)
        normalized = merge_singletons(outline)
        if normalized != outline:
            _write_json(run_path / "12_taxonomy" / "outline.json", normalized)
            print(f"normalized: families {len(outline['families'])} -> {len(normalized['families'])}")
        else:
            print("normalized: no singletons to merge")
        return

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
