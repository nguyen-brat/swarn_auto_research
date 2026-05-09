import re
from .utils import http_get, run_blocking

ARXIV2MD_MARKDOWN_URL = "https://arxiv2md.org/api/markdown"
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def _get_arxiv_markdown_sync(arxiv_id: str, remove_toc: bool = False) -> str:
    params = {
        "url": arxiv_id,
        "remove_toc": str(remove_toc).lower(),
    }
    return http_get(ARXIV2MD_MARKDOWN_URL, params=params, return_json=False)


async def get_arxiv_markdown(arxiv_id: str, remove_toc: bool = False) -> str:
    return await run_blocking(_get_arxiv_markdown_sync, arxiv_id, remove_toc)


_HEADING_NUMERIC_PREFIX = re.compile(r"^\d+(?:\.\d+)*\.?\s+")


def _normalize_heading(title: str) -> str:
    normalized = re.sub(r"\s+", " ", title.strip().lower())
    normalized = _HEADING_NUMERIC_PREFIX.sub("", normalized)
    return normalized.rstrip(":").strip()


def _parse_markdown_headings(markdown: str) -> list[dict]:
    lines = markdown.splitlines()
    headings = []

    for index, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if not match:
            continue
        headings.append(
            {
                "level": len(match.group(1)),
                "title": match.group(2).strip(),
                "start_line": index,
            }
        )

    for index, heading in enumerate(headings):
        end_line = len(lines)
        for next_heading in headings[index + 1:]:
            if next_heading["level"] <= heading["level"]:
                end_line = next_heading["start_line"]
                break
        heading["end_line"] = end_line

    return headings


def extract_markdown_section(markdown: str, section: str) -> str:
    lines = markdown.splitlines()
    headings = _parse_markdown_headings(markdown)
    requested_path = [_normalize_heading(part) for part in section.split("/") if part.strip()]

    if not requested_path:
        raise ValueError("section must not be empty")

    active_path = []
    matched_heading = None

    for heading in headings:
        while active_path and active_path[-1]["level"] >= heading["level"]:
            active_path.pop()
        active_path.append(heading)

        current_path = [_normalize_heading(item["title"]) for item in active_path]
        if current_path[-len(requested_path):] == requested_path:
            matched_heading = heading
            break

    if matched_heading is None:
        raise ValueError(f"section not found: {section}")

    section_lines = lines[matched_heading["start_line"]:matched_heading["end_line"]]
    return "\n".join(section_lines).strip()


if __name__ == "__main__":
    import asyncio
    result = asyncio.run(get_arxiv_markdown("1706.03762", remove_toc=False))
    print(result)
