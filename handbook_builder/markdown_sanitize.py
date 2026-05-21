"""Render-safety normalization for generated handbook markdown."""
from __future__ import annotations

from collections.abc import Callable
import json
import re
from pathlib import Path


DOC_SUFFIXES = {".md", ".mdx"}


def sanitize_docs_tree(docs_dir: Path) -> None:
    """Normalize every generated markdown page before validation/build."""
    for path in sorted(docs_dir.rglob("*")):
        if path.suffix not in DOC_SUFFIXES:
            continue
        original = path.read_text()
        sanitized = remove_duplicate_body_h1(normalize_math_delimiters(original))
        if sanitized != original:
            path.write_text(sanitized)


def normalize_math_delimiters(markdown: str) -> str:
    """Fix known nested inline-in-display delimiter mistakes without broad LaTeX repair."""
    markdown = _normalize_latex_bracket_delimiters_outside_code(markdown)
    markdown = re.sub(
        r"(?m)^([ \t]*)\$\$[ \t]+([^$]*?)\$(.*?)\$([^$]*?)\$\$[ \t]*$",
        lambda match: f"{match.group(1)}$$\n{(match.group(2) + match.group(3) + match.group(4)).strip()}\n{match.group(1)}$$",
        markdown,
    )
    markdown = re.sub(
        r"(?m)^([ \t]*)\$\$[ \t]+([^$]*?)\$(.*?)\$([^$]*?)\$[ \t]*$",
        lambda match: f"{match.group(1)}$$\n{(match.group(2) + match.group(3) + match.group(4)).strip()}\n{match.group(1)}$$",
        markdown,
    )
    markdown = _normalize_multiline_display_blocks(markdown)
    return _sanitize_common_katex_fragments(markdown)


def remove_duplicate_body_h1(markdown: str) -> str:
    """Remove the first body H1 when it duplicates frontmatter title exactly."""
    frontmatter = _split_frontmatter(markdown)
    if frontmatter is None:
        return markdown
    before, body, trailing_newline = frontmatter
    title = _frontmatter_title(before)
    if not title:
        return markdown

    body_lines = body.splitlines()
    for index, line in enumerate(body_lines):
        if not line.strip():
            continue
        if not line.startswith("# "):
            return markdown
        if _normalize_title(line[2:]) != _normalize_title(title):
            return markdown
        del body_lines[index]
        new_body = "\n".join(body_lines)
        return before + new_body + ("\n" if trailing_newline else "")
    return markdown


def has_bad_math_delimiters(markdown: str) -> bool:
    searchable = _markdown_without_code(markdown)
    return bool(
        re.search(r"(?m)^\s*\$\$\s+\$", searchable)
        or re.search(r"\$\s+\$\$\s*$", searchable, re.M)
        or re.search(r"(?<!\\)\\[()[\]]", searchable)
        or r"\textsc{" in searchable
    )


def has_duplicate_body_h1(markdown: str) -> bool:
    frontmatter = _split_frontmatter(markdown)
    if frontmatter is None:
        return False
    before, body, _ = frontmatter
    title = _frontmatter_title(before)
    if not title:
        return False
    for line in body.splitlines():
        if not line.strip():
            continue
        return line.startswith("# ") and _normalize_title(line[2:]) == _normalize_title(title)
    return False


def _normalize_multiline_display_blocks(markdown: str) -> str:
    lines = markdown.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip() != "$$":
            output.append(line)
            index += 1
            continue

        end = index + 1
        while end < len(lines) and lines[end].strip() != "$$":
            end += 1
        if end >= len(lines):
            output.extend(lines[index:])
            break

        content = "\n".join(lines[index + 1 : end]).strip()
        if content.startswith("$") and "$" in content[1:]:
            last_dollar = content.rfind("$")
            content = (content[1:last_dollar] + content[last_dollar + 1 :]).strip()
        if "$" in content:
            content = content.replace("$", "").strip()
        output.append(line)
        output.extend(content.splitlines())
        output.append(lines[end])
        index = end + 1

    return "\n".join(output) + ("\n" if markdown.endswith("\n") else "")


def _sanitize_common_katex_fragments(markdown: str) -> str:
    markdown = re.sub(
        r"\\text\{\{\\color\[rgb\]\{[^}]+\}\\definecolor\[named\]\{pgfstrokecolor\}\{rgb\}\{[^}]+\}\s*"
        r"\\pgfsys@color@gray@stroke\{0\}\\pgfsys@color@gray@fill\{0\}([^{}]+)\}\}",
        lambda match: r"\text{" + match.group(1).strip() + "}",
        markdown,
    )
    markdown = re.sub(
        r"\\textsc\{([^{}]+)\}",
        _replace_textsc_macro,
        markdown,
    )
    return re.sub(
        r"\\(texttt|text)\{([^{}]*)\}",
        lambda match: f"\\{match.group(1)}{{{_escape_text_macro_underscores(match.group(2))}}}",
        markdown,
    )


def _replace_textsc_macro(match: re.Match[str]) -> str:
    value = match.group(1).strip()
    if re.search(r"\s", value):
        return r"\text{" + value + "}"
    return r"\mathrm{" + value + "}"


def _escape_text_macro_underscores(value: str) -> str:
    return re.sub(r"(?<!\\)_", r"\\_", value)


def _normalize_latex_bracket_delimiters_outside_code(markdown: str) -> str:
    return _transform_non_code_markdown(markdown, _normalize_latex_bracket_delimiters_in_text)


def _normalize_latex_bracket_delimiters_in_text(text: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(text):
        if text[index] == "`":
            end = _find_inline_code_end(text, index)
            if end is not None:
                output.append(text[index:end])
                index = end
                continue

        if _is_single_backslash_command(text, index, r"\["):
            end = text.find(r"\]", index + 2)
            if end != -1:
                content = text[index + 2 : end].strip()
                output.append("$$\n" + content + "\n$$")
                index = end + 2
                continue

        if _is_single_backslash_command(text, index, r"\("):
            end = text.find(r"\)", index + 2)
            if end != -1:
                content = text[index + 2 : end]
                if "\n" not in content:
                    output.append("$" + content + "$")
                    index = end + 2
                    continue

        output.append(text[index])
        index += 1
    return "".join(output)


def _is_single_backslash_command(text: str, index: int, command: str) -> bool:
    return text.startswith(command, index) and (index == 0 or text[index - 1] != "\\")


def _markdown_without_code(markdown: str) -> str:
    return _transform_non_code_markdown(
        markdown,
        _strip_inline_code,
        code_transform=lambda value: " " * len(value),
    )


def _strip_inline_code(text: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(text):
        if text[index] == "`":
            end = _find_inline_code_end(text, index)
            if end is not None:
                output.append(" " * (end - index))
                index = end
                continue
        output.append(text[index])
        index += 1
    return "".join(output)


def _transform_non_code_markdown(
    markdown: str,
    transform: Callable[[str], str],
    *,
    code_transform: Callable[[str], str] | None = None,
) -> str:
    chunks: list[str] = []
    lines = markdown.splitlines(keepends=True)
    buffer: list[str] = []
    fence_marker: str | None = None
    code_transform = code_transform or (lambda value: value)

    def flush_buffer() -> None:
        if buffer:
            chunks.append(transform("".join(buffer)))
            buffer.clear()

    for line in lines:
        marker = _fence_marker(line)
        if fence_marker is not None:
            chunks.append(code_transform(line))
            if marker == fence_marker:
                fence_marker = None
            continue
        if marker is not None:
            flush_buffer()
            fence_marker = marker
            chunks.append(code_transform(line))
            continue
        buffer.append(line)

    flush_buffer()
    return "".join(chunks)


def _fence_marker(line: str) -> str | None:
    match = re.match(r"^[ \t]*(```+|~~~+)", line)
    if not match:
        return None
    return match.group(1)[0]


def _find_inline_code_end(text: str, start: int) -> int | None:
    tick_count = 0
    while start + tick_count < len(text) and text[start + tick_count] == "`":
        tick_count += 1
    delimiter = "`" * tick_count
    end = text.find(delimiter, start + tick_count)
    if end == -1:
        return None
    return end + tick_count


def _split_frontmatter(markdown: str) -> tuple[str, str, bool] | None:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = index
            break
    if end is None:
        return None
    before = "\n".join(lines[: end + 1]) + "\n"
    body = "\n".join(lines[end + 1 :])
    return before, body, markdown.endswith("\n")


def _frontmatter_title(frontmatter_with_delimiters: str) -> str | None:
    for line in frontmatter_with_delimiters.splitlines()[1:]:
        if line.strip() == "---":
            break
        if line.startswith("title:"):
            raw = line.split(":", 1)[1].strip()
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = raw.strip("'\"")
            return str(parsed)
    return None


def _normalize_title(value: str) -> str:
    return " ".join(value.strip().split())
