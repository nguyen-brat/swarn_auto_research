from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from scripts.auto_research_runner.config import NON_BLOCKING_FORM_ISSUE_CHECKS
from scripts.auto_research_runner.io_utils import _safe_component, chunked
from scripts.auto_research_runner.prompts import _generic_agent_prompt, _typed_target_ref
from scripts.auto_research_runner.shared_types import ShardSpec
from scripts.auto_research_runner.state import now_iso
from swarn_research_mcp.research_book import BOOK_FILE_BY_ID


def load_outline(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "12_taxonomy" / "outline.json").read_text())


def _validate_chapter_target(target: dict[str, str]) -> None:
    target_type = target["type"]
    if target_type not in {"book", "families", "methods"}:
        raise ValueError(f"unsafe target type: {target_type}")
    _safe_component(target["id"], field="target id")


def build_chapter_targets(run_dir: Path) -> list[dict[str, str]]:
    outline = load_outline(run_dir)
    targets: list[dict[str, str]] = []
    for section in outline.get("book_sections", []):
        if section["id"] == "appendices":
            continue
        target = {"type": "book", "id": section["id"]}
        _validate_chapter_target(target)
        targets.append(target)
    for family in outline.get("families", []):
        if family.get("is_group") or family["id"] == "standalone":
            continue
        target = {"type": "families", "id": family["id"]}
        _validate_chapter_target(target)
        targets.append(target)
    for method in outline.get("methods", []):
        target = {"type": "methods", "id": method["id"]}
        _validate_chapter_target(target)
        targets.append(target)
    return targets


def _expected_chapter_pack(target: dict[str, str]) -> str:
    _validate_chapter_target(target)
    return f"13_chapter_packs/{target['type']}/{target['id']}_pack.json"


def _expected_chapter_file(target: dict[str, str]) -> str:
    _validate_chapter_target(target)
    if target["type"] == "book":
        filename = BOOK_FILE_BY_ID.get(target["id"], f"{target['id']}.md")
        return f"14_chapters/book/{filename}"
    return f"14_chapters/{target['type']}/{target['id']}.md"


def _expected_verification_file(target: dict[str, str]) -> str:
    _validate_chapter_target(target)
    return f"15_verification/{target['type']}/{target['id']}_verification.json"


def _chapter_writer_specs(
    run_dir: Path,
    targets: list[dict[str, str]],
    *,
    form_issues_by_id: dict[str, list[dict[str, Any]]] | None = None,
    shard_prefix: str = "write",
) -> list[ShardSpec]:
    specs = []
    agent_by_type = {
        "book": "book_section_writer",
        "families": "family_chapter_writer",
        "methods": "method_chapter_writer",
    }
    id_key_by_type = {
        "book": "section_ids",
        "families": "family_ids",
        "methods": "method_ids",
    }
    for target_type in ("book", "families", "methods"):
        typed_targets = [t for t in targets if t["type"] == target_type]
        shard_size = 1 if target_type == "methods" else 2
        for idx, chunk in enumerate(chunked(typed_targets, shard_size), start=1):
            if not form_issues_by_id and all(
                (run_dir / _expected_chapter_file(t)).exists() for t in chunk
            ):
                continue
            agent = agent_by_type[target_type]
            shard_id = f"{shard_prefix}-{target_type}-{idx:03d}"
            payload: dict[str, Any] = {
                id_key_by_type[target_type]: [target["id"] for target in chunk]
            }
            if form_issues_by_id:
                payload["form_issues"] = {
                    target["id"]: form_issues_by_id.get(target["id"], [])
                    for target in chunk
                }
            specs.append(
                ShardSpec(
                    stage="14",
                    shard_id=shard_id,
                    agent=agent,
                    model="gpt-5.4",
                    prompt=_generic_agent_prompt(
                        f".codex/agents/{agent}.toml",
                        run_dir.name,
                        "14",
                        shard_id,
                        payload,
                    ),
                    expected_outputs=[_expected_chapter_file(t) for t in chunk],
                )
            )
    return specs


def _verification_specs(
    run_dir: Path,
    targets: list[dict[str, str]],
    *,
    shard_prefix: str = "verify",
) -> list[ShardSpec]:
    return [
        ShardSpec(
            stage="15",
            shard_id=f"{shard_prefix}-{idx:03d}",
            agent="verifier",
            model="gpt-5.4",
            prompt=_generic_agent_prompt(
                ".codex/agents/verifier.toml",
                run_dir.name,
                "15",
                f"{shard_prefix}-{idx:03d}",
                {"chapter_targets": [_typed_target_ref(target) for target in chunk]},
            ),
            expected_outputs=[_expected_verification_file(t) for t in chunk],
        )
        for idx, chunk in enumerate(chunked(targets, 2), start=1)
        if any(not (run_dir / _expected_verification_file(t)).exists() for t in chunk)
    ]


def _is_non_blocking_form_issue(issue: dict[str, Any]) -> bool:
    check = str(issue.get("check") or "")
    return check in NON_BLOCKING_FORM_ISSUE_CHECKS or check.endswith("_word_count_high")


def _blocking_form_issues(
    verification: dict[str, Any],
    form_issue_count: int,
) -> list[dict[str, Any]]:
    issues = verification.get("form_issues")
    if isinstance(issues, list):
        return [
            issue
            for issue in issues
            if isinstance(issue, dict) and not _is_non_blocking_form_issue(issue)
        ]
    if form_issue_count:
        return [{"check": "unknown_form_issue"}] * form_issue_count
    return []


def _has_only_non_blocking_form_issues(
    verification: dict[str, Any],
    form_issue_count: int,
) -> bool:
    issues = verification.get("form_issues")
    return (
        form_issue_count > 0
        and isinstance(issues, list)
        and any(isinstance(issue, dict) for issue in issues)
        and not _blocking_form_issues(verification, form_issue_count)
    )


def _load_verification_or_none(run_dir: Path, target: dict[str, str]) -> dict[str, Any] | None:
    path = run_dir / _expected_verification_file(target)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _targets_with_blocking_form_issues(
    run_dir: Path, targets: list[dict[str, str]]
) -> tuple[list[dict[str, str]], dict[str, list[dict[str, Any]]]]:
    repair_targets: list[dict[str, str]] = []
    form_issues_by_id: dict[str, list[dict[str, Any]]] = {}
    for target in targets:
        verification = _load_verification_or_none(run_dir, target)
        if verification is None:
            continue
        summary = verification.get("summary", {})
        form_issue_count = int(summary.get("form_issue_count") or 0)
        blocking_issues = _blocking_form_issues(verification, form_issue_count)
        if blocking_issues:
            repair_targets.append(target)
            form_issues_by_id[target["id"]] = blocking_issues
    return repair_targets, form_issues_by_id


def _verification_passed(verification: dict[str, Any]) -> bool:
    if "passed" in verification:
        return verification.get("passed") is True
    summary = verification.get("summary")
    return isinstance(summary, dict) and summary.get("passed") is True


def _verification_status(
    target: dict[str, str],
    verification: dict[str, Any] | None,
    chapter_word_count: int,
) -> tuple[str, str]:
    if verification is None:
        return "excluded_missing_verification", "verification file is missing or unreadable"
    summary = verification.get("summary", {})
    form_issues = int(summary.get("form_issue_count") or 0)
    blocking_form_issues = _blocking_form_issues(verification, form_issues)
    if blocking_form_issues:
        return "excluded_form_issues", f"{len(blocking_form_issues)} form issue(s)"

    word_count = int(summary.get("word_count") or chapter_word_count or 0)
    if target["type"] == "methods" and word_count < 1500:
        return "excluded_too_short", f"method chapter has {word_count} words"
    if target["type"] == "families" and word_count < 1000:
        return "excluded_too_short", f"family chapter has {word_count} words"

    if _verification_passed(verification):
        return "passed", ""
    claims_unsupported = int(summary.get("claims_unsupported") or 0)
    claims_overstated = int(summary.get("claims_overstated") or 0)
    gaps_missing = int(summary.get("gaps_missing") or 0)
    if claims_unsupported or claims_overstated:
        return "excluded_unsupported_claims", "unsupported or overstated claims"
    if gaps_missing:
        return "excluded_missing_evidence", "required evidence gaps missing"
    if _has_only_non_blocking_form_issues(verification, form_issues):
        return "passed", ""
    return "excluded_verification_failed", "verification did not pass"


def _write_verification_summary(run_dir: Path, targets: list[dict[str, str]]) -> None:
    summary_dir = run_dir / "15_verification"
    summary_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for target in targets:
        path = run_dir / _expected_verification_file(target)
        if not path.exists():
            raise RuntimeError(f"Stage 15 missing verification file: {path}")
        data = json.loads(path.read_text())
        summary = data.get("summary", {})
        rows.append(
            {
                "target_type": target["type"],
                "target_id": target["id"],
                "passed": _verification_passed(data),
                "claims_total": summary.get("claims_total", 0),
                "claims_unsupported": summary.get("claims_unsupported", 0),
                "claims_overstated": summary.get("claims_overstated", 0),
                "gaps_covered": summary.get("gaps_covered", 0),
                "gaps_missing": summary.get("gaps_missing", 0),
                "word_count": summary.get("word_count", 0),
                "form_issue_count": summary.get("form_issue_count", 0),
                "equations_rendered": summary.get("equations_rendered", 0),
                "pseudocode_blocks": summary.get("pseudocode_blocks", 0),
            }
        )
    summary_path = summary_dir / "verification_summary.csv"
    tmp_path = summary_dir / "verification_summary.csv.tmp"
    with tmp_path.open("w", newline="") as handle:
        fieldnames = [
            "target_type",
            "target_id",
            "passed",
            "claims_total",
            "claims_unsupported",
            "claims_overstated",
            "gaps_covered",
            "gaps_missing",
            "word_count",
            "form_issue_count",
            "equations_rendered",
            "pseudocode_blocks",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.replace(summary_path)


def _manifest_chapter_type(target_type: str) -> str:
    return {"book": "book", "families": "family", "methods": "method"}[target_type]


def _outline_entry_for_target(
    outline: dict[str, Any], target: dict[str, str]
) -> dict[str, Any]:
    if target["type"] == "book":
        entries = outline.get("book_sections", [])
    elif target["type"] == "families":
        entries = outline.get("families", [])
    else:
        entries = outline.get("methods", [])
    for entry in entries:
        if entry.get("id") == target["id"]:
            return entry
    return {"id": target["id"], "title": target["id"]}


def _split_markdown_front_matter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---\n", 4)
    if end == -1:
        return "", text
    return text[: end + len("\n---\n")], text[end + len("\n---\n") :]


def _strip_references_section(body: str) -> str:
    return re.split(r"(?m)^## References\s*$", body, maxsplit=1)[0].rstrip()


def _markdown_word_count(text: str) -> int:
    _, body = _split_markdown_front_matter(text)
    return len(re.findall(r"\b\w+\b", body))


def _yaml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=True)
    return json.dumps(str(value), ensure_ascii=True)


def _write_chapter_front_matter_and_references(
    chapter_path: Path,
    metadata: dict[str, Any],
    references: list[str],
) -> None:
    if not chapter_path.exists():
        return
    _, body = _split_markdown_front_matter(chapter_path.read_text(encoding="utf-8"))
    body = _strip_references_section(body)
    front_matter = "\n".join(
        ["---"]
        + [f"{key}: {_yaml_value(value)}" for key, value in metadata.items()]
        + ["---", ""]
    )
    reference_lines = ["", "## References", ""]
    reference_lines.extend(f"- {reference}" for reference in references)
    chapter_path.write_text(
        front_matter + body.rstrip() + "\n" + "\n".join(reference_lines).rstrip() + "\n",
        encoding="utf-8",
    )


def _references_for_target(
    target: dict[str, str],
    entry: dict[str, Any],
    method_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    arxiv_ids: list[str] = []
    if target["type"] == "methods" and entry.get("arxiv_id"):
        arxiv_ids.append(str(entry["arxiv_id"]))
    elif target["type"] == "families":
        for method_id in entry.get("method_ids", []) or []:
            method = method_by_id.get(method_id) or {}
            if method.get("arxiv_id"):
                arxiv_ids.append(str(method["arxiv_id"]))
    seen = set()
    references = []
    for arxiv_id in arxiv_ids:
        if arxiv_id in seen:
            continue
        seen.add(arxiv_id)
        references.append(f"[arxiv:{arxiv_id}]")
    return references


def _build_deterministic_chapter_manifest(run_dir: Path) -> dict[str, Any]:
    outline = load_outline(run_dir)
    methods = {method["id"]: method for method in outline.get("methods", [])}
    chapters: list[dict[str, Any]] = []
    for target in build_chapter_targets(run_dir):
        entry = _outline_entry_for_target(outline, target)
        chapter_path = run_dir / _expected_chapter_file(target)
        chapter_text = chapter_path.read_text(encoding="utf-8") if chapter_path.exists() else ""
        chapter_word_count = _markdown_word_count(chapter_text)
        verification = _load_verification_or_none(run_dir, target)
        summary = verification.get("summary", {}) if verification else {}
        word_count = int(summary.get("word_count") or chapter_word_count or 0)
        equations_rendered = int(summary.get("equations_rendered") or chapter_text.count("$$") // 2)
        pseudocode_blocks = int(summary.get("pseudocode_blocks") or chapter_text.count("```") // 2)
        status, reason = _verification_status(target, verification, word_count)

        chapter_type = _manifest_chapter_type(target["type"])
        metadata: dict[str, Any] = {
            "chapter_id": target["id"],
            "chapter_type": chapter_type,
            "title": entry.get("title", target["id"]),
            "status": status,
            "word_count": word_count,
            "equations_rendered": equations_rendered,
            "pseudocode_blocks": pseudocode_blocks,
        }
        if reason:
            metadata["status_reason"] = reason
        if target["type"] == "methods":
            metadata["arxiv_id"] = entry.get("arxiv_id", "")
            metadata["family_id"] = entry.get("family_id", "")
        elif target["type"] == "families":
            metadata["method_ids"] = entry.get("method_ids", []) or []

        references = _references_for_target(target, entry, methods)
        _write_chapter_front_matter_and_references(chapter_path, metadata, references)

        manifest_entry = dict(metadata)
        manifest_entry["file"] = _expected_chapter_file(target)
        chapters.append(manifest_entry)

    return {"run_id": run_dir.name, "generated_at": now_iso(), "chapters": chapters}
