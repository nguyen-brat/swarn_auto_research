import asyncio
import ast
import datetime
import json
import os
import re
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


_DEFAULT_BULK_SEARCH_CONFIG = {
    "trending_months": 12,
    "trending_month_limit": 30,
    "influence_windows": [
        {"label": "older", "year_offset_start": -4, "year_offset_end": -2,
         "limit": 10, "min_citation_count": 50, "depth": 1,
         "citation_limit_per_level": 20, "min_citation_depth": 30, "max_papers": 100},
        {"label": "middle", "year_offset_start": -2, "year_offset_end": -1,
         "limit": 10, "min_citation_count": 30, "depth": 2,
         "citation_limit_per_level": 30, "min_citation_depth": 20, "max_papers": 100},
        {"label": "recent", "year_offset_start": -1, "year_offset_end": None,
         "limit": 10, "min_citation_count": 10, "depth": 3,
         "citation_limit_per_level": 20, "min_citation_depth": 10, "max_papers": 100},
    ],
    "huggingface_search_limit": 120,
    "recommendations_seed_cap": 100,
    "recommendations_limit": 100,
    "survey_limit": 5,
    "survey_citation_limit_per_level": 30,
    "survey_max_papers": 100,
}


def _load_bulk_search_config():
    path = os.environ.get(
        "SWARN_BULK_SEARCH_CONFIG",
        str(Path(__file__).resolve().parents[1] / "bulk_search_config.json"),
    )
    cfg = dict(_DEFAULT_BULK_SEARCH_CONFIG)
    p = Path(path)
    if p.is_file():
        overrides = json.loads(p.read_text())
        cfg.update(overrides)
    return cfg

from swarn_research_mcp.services.semantic_scholar import (
    paper_batch,
    paper_metadata_simple,
    paper_metadata_simple_batch,
    paper_relevance_search,
    recommendations_multi,
)
from swarn_research_mcp.tools.select_paper import select_papers
from swarn_research_mcp.services.huggingface import search_huggingface_papers, collect_huggingface_trending_papers
from swarn_research_mcp.services.arxiv import extract_markdown_section, get_arxiv_markdown
from swarn_research_mcp.services.alphaxiv import get_alphaxiv_overview_markdown
from time import time
from sdk.codex import AsyncCodex, build_config


CODEX_RELEVANCE_SESSION_LIMIT = 20


def _recent_month_filters(current_year, current_month, month_count=12):
    months = []
    year = current_year
    month = current_month

    for _ in range(month_count):
        months.append(f"{year}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1

    return list(reversed(months))


def _paper_chunks(papers, chunk_size):
    items = list(papers.items())
    for start in range(0, len(items), chunk_size):
        yield dict(items[start:start + chunk_size])


def _format_codex_relevance_prompt(query_topic, paper_chunk):
    papers_payload = [
        {
            "arxiv_id": arxiv_id,
            "abstract": abstract,
        }
        for arxiv_id, abstract in paper_chunk.items()
    ]
    return (
        "You are filtering research papers for relevance.\n"
        f"User query topic: {query_topic}\n\n"
        "Input papers are JSON objects with arxiv_id and abstract:\n"
        f"{json.dumps(papers_payload, ensure_ascii=False, indent=2)}\n\n"
        "Return only a Python list string of arxiv_id values that are really related "
        "to the user query topic. Do not include explanation, markdown, or extra text. "
        "Example output: ['2401.00001', '2502.12345']"
    )


def _parse_codex_related_ids(response, allowed_ids):
    match = re.search(r"\[[\s\S]*\]", response or "")
    if not match:
        return []

    try:
        parsed = ast.literal_eval(match.group(0))
    except (SyntaxError, ValueError):
        return []

    if not isinstance(parsed, list):
        return []

    related_ids = []
    seen = set()
    for item in parsed:
        arxiv_id = str(item).strip()
        if arxiv_id in allowed_ids and arxiv_id not in seen:
            seen.add(arxiv_id)
            related_ids.append(arxiv_id)
    return related_ids


async def _validate_related_paper_chunk_with_codex(query_topic, paper_chunk, semaphore):
    async with semaphore:
        prompt = _format_codex_relevance_prompt(query_topic, paper_chunk)
        async with AsyncCodex(config=build_config()) as codex:
            thread = await codex.thread_start(model="gpt-5.4-mini")
            result = await thread.run(prompt, effort="low")
        return _parse_codex_related_ids(result.final_response, set(paper_chunk))


async def validate_related_papers_with_codex(
    papers,
    query_topic,
    chunk_size=50,
    max_parallel_sessions=CODEX_RELEVANCE_SESSION_LIMIT,
):
    paper_map = papers.get("papers", papers) if isinstance(papers, dict) else {}
    if not paper_map:
        return []

    semaphore = asyncio.Semaphore(max_parallel_sessions)
    tasks = [
        asyncio.create_task(_validate_related_paper_chunk_with_codex(query_topic, chunk, semaphore))
        for chunk in _paper_chunks(paper_map, chunk_size)
    ]
    chunk_results = await asyncio.gather(*tasks)

    related_ids = []
    seen = set()
    for chunk_result in chunk_results:
        for arxiv_id in chunk_result:
            if arxiv_id not in seen:
                seen.add(arxiv_id)
                related_ids.append(arxiv_id)
    return related_ids


def _coerce_string_list(value, *, field_name: str) -> list[str]:
    """Accept either a list[str] or a single newline/comma-delimited string.

    Agents connecting through MCP often serialize list parameters as one
    string. Split on newlines first; if there is only one resulting item
    AND it contains commas, fall back to comma-splitting. Strip and drop
    empties so we never produce blank queries (which made Hugging Face
    return 400 for q=+).
    """
    if value is None:
        return []
    if isinstance(value, str):
        parts = [line.strip() for line in value.splitlines() if line.strip()]
        if len(parts) <= 1 and "," in value:
            parts = [p.strip() for p in value.split(",") if p.strip()]
        return parts
    if isinstance(value, (list, tuple)):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return cleaned
    raise TypeError(
        f"{field_name} must be a list of strings or a newline/comma "
        f"delimited string, got {type(value).__name__}"
    )


async def bulk_normal_start_search(
    queries: list[str],
    survey_queries: list[str],
    positive_keywords: list[str],
    negative_keywords: list[str],
    output_dir: str | None = None,
):
    queries = _coerce_string_list(queries, field_name="queries")
    survey_queries = _coerce_string_list(survey_queries, field_name="survey_queries")
    positive_keywords = _coerce_string_list(positive_keywords, field_name="positive_keywords")
    negative_keywords = _coerce_string_list(negative_keywords, field_name="negative_keywords")
    if not queries:
        raise ValueError("queries must contain at least one non-empty string")

    cfg = _load_bulk_search_config()
    output_dir = Path(output_dir) if output_dir is not None else None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    current_date = datetime.datetime.now()
    current_year = current_date.year
    start_year = str(current_year - 4)
    trending_months = _recent_month_filters(
        current_year, current_date.month, month_count=cfg["trending_months"]
    )

    def _resolve_year(offset):
        return None if offset is None else str(current_year + offset)

    influence_search_windows = [
        {
            "label": w["label"],
            "start_year": _resolve_year(w["year_offset_start"]),
            "end_year": _resolve_year(w["year_offset_end"]),
            "limit": w["limit"],
            "min_citation_count": w["min_citation_count"],
            "depth": w["depth"],
            "citation_limit_per_level": w["citation_limit_per_level"],
            "min_citation_depth": w["min_citation_depth"],
            "max_papers": w["max_papers"],
        }
        for w in cfg["influence_windows"]
    ]
    bulk_results = {}
    excluded_paper_ids = set()
    print(
        f"Bulk search start: normal_queries={len(queries)}, "
        f"survey_queries={len(survey_queries)}, start_year={start_year}, "
        f"trending_months={trending_months[0]}..{trending_months[-1]}"
    )
    monthly_trending_tasks = [
        asyncio.create_task(collect_huggingface_trending_papers(
            month=month, limit=cfg["trending_month_limit"]
        ))
        for month in trending_months
    ]

    for index, query in enumerate(queries, start=1):
        print(
            f"\nBulk normal query {index}/{len(queries)} start: {query!r}; "
            f"excluded={len(excluded_paper_ids)}, total_results={len(bulk_results)}"
        )
        influence_tasks = [
            asyncio.create_task(paper_relevance_search(
                query=query,
                limit=window["limit"],
                start_year=window["start_year"],
                end_year=window["end_year"],
                min_citation_count=window["min_citation_count"],
                depth=window["depth"],
                citation_limit_per_level=window["citation_limit_per_level"],
                min_citation_depth=window["min_citation_depth"],
                exclude_paper_ids=set(excluded_paper_ids),
                max_papers=window["max_papers"],
            ))
            for window in influence_search_windows
        ]
        trending_task = asyncio.create_task(
            search_huggingface_papers(query=query, limit=cfg["huggingface_search_limit"])
        )

        trending_paper_result = await trending_task
        print(f"Bulk normal query {index}: HuggingFace results={len(trending_paper_result)}")
        recommendations_task = asyncio.create_task(
            recommendations_multi(
                list(trending_paper_result.keys())[:cfg["recommendations_seed_cap"]],
                limit=cfg["recommendations_limit"],
            )
        )
        influence_results = await asyncio.gather(*influence_tasks)
        influence_paper_result = {}
        for window, window_result in zip(influence_search_windows, influence_results):
            print(
                f"Bulk normal query {index}: Semantic Scholar {window['label']} "
                f"window results={len(window_result)}"
            )
            influence_paper_result = influence_paper_result | window_result
        print(f"Bulk normal query {index}: Semantic Scholar pool={len(influence_paper_result)}")
        _, enriched_influence_result = await recommendations_task
        print(f"Bulk normal query {index}: recommendation results={len(enriched_influence_result)}")

        bulk_results = bulk_results | influence_paper_result | trending_paper_result | enriched_influence_result
        excluded_paper_ids = excluded_paper_ids | set(influence_paper_result.keys()) | set(trending_paper_result.keys()) | set(enriched_influence_result.keys())
        print(
            f"Bulk normal query {index}/{len(queries)} done: "
            f"total_results={len(bulk_results)}, excluded={len(excluded_paper_ids)}"
        )
    
    for index, survey_query in enumerate(survey_queries, start=1):
        print(
            f"\nBulk survey query {index}/{len(survey_queries)} start: {survey_query!r}; "
            f"excluded={len(excluded_paper_ids)}, total_results={len(bulk_results)}"
        )
        survey_result_old = asyncio.create_task(paper_relevance_search(
            query=survey_query,
            limit=cfg["survey_limit"],
            start_year=str(datetime.datetime.now().year - 2),
            end_year=str(datetime.datetime.now().year - 1),
            min_citation_count=30,
            depth=1,
            citation_limit_per_level=cfg["survey_citation_limit_per_level"],
            min_citation_depth=30,
            exclude_paper_ids=set(excluded_paper_ids),
            max_papers=cfg["survey_max_papers"],
        ))
        survey_result_new = asyncio.create_task(paper_relevance_search(
            query=survey_query,
            limit=cfg["survey_limit"],
            start_year=str(datetime.datetime.now().year - 1),
            min_citation_count=10,
            depth=1,
            citation_limit_per_level=cfg["survey_citation_limit_per_level"],
            min_citation_depth=10,
            exclude_paper_ids=set(excluded_paper_ids),
            max_papers=cfg["survey_max_papers"],
        ))
        survey_result_new_result = await survey_result_new
        survey_result_old_result = await survey_result_old
        survey_result = survey_result_old_result | survey_result_new_result
        print(f"Bulk survey query {index}: Semantic Scholar pool={len(survey_result)}")
        bulk_results = bulk_results | survey_result
        excluded_paper_ids = excluded_paper_ids | set(survey_result.keys())
        print(
            f"Bulk survey query {index}/{len(survey_queries)} done: "
            f"total_results={len(bulk_results)}, excluded={len(excluded_paper_ids)}"
        )

    monthly_trending_results = await asyncio.gather(*monthly_trending_tasks)
    monthly_trending_pool = {}
    for month, month_result in zip(trending_months, monthly_trending_results):
        print(f"Bulk monthly HuggingFace trending {month}: results={len(month_result)}")
        monthly_trending_pool = monthly_trending_pool | month_result
    bulk_results = bulk_results | monthly_trending_pool
    print(
        f"Bulk monthly HuggingFace trending done: pool={len(monthly_trending_pool)}, "
        f"total_results={len(bulk_results)}"
    )

    selected_results = select_papers(
        papers=bulk_results,
        keywords=positive_keywords,
        negative_keywords=negative_keywords,
    )
    total_input = selected_results.get("total_input", len(bulk_results))
    total_kept = selected_results.get("total_kept", len(selected_results.get("papers", {})))
    print(
        f"Bulk search keyword filter done: input={total_input}, "
        f"kept={total_kept}"
    )

    keyword_filtered_papers = selected_results.get("papers", {})
    
    
    # ############################## dump code to test only
    # with open("data/bulk_search_results_1777799131.json", "r", encoding="utf-8") as f:
    #     keyword_filtered_papers = json.load(f)
    # selected_results = {}
    # selected_results["papers"] = keyword_filtered_papers
    # selected_results["total_kept"] = len(keyword_filtered_papers)
    # #############################
    
    
    query_topic = " & ".join(queries)
    print(
        f"Bulk Codex relevance validation start: "
        f"papers={len(keyword_filtered_papers)}, topic={query_topic!r}"
    )
    related_ids = await validate_related_papers_with_codex(
        papers=keyword_filtered_papers,
        query_topic=query_topic,
    )
    related_id_set = set(related_ids)
    selected_results["papers"] = {
        arxiv_id: abstract
        for arxiv_id, abstract in keyword_filtered_papers.items()
        if arxiv_id in related_id_set
    }
    selected_results["total_kept"] = len(selected_results["papers"])
    print(
        f"Bulk Codex relevance validation done: "
        f"related={selected_results['total_kept']} from {len(keyword_filtered_papers)}"
    )

    if output_dir is not None:
        output_path = output_dir / f"bulk_search_results_{int(time())}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(selected_results["papers"], f, ensure_ascii=False, indent=2)
        selected_results["output_path"] = str(output_path)
    print("Bulk search done")
    return selected_results


def _ensure_output_dir(output_dir):
    if output_dir is None:
        return None
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _section_filename_slug(section: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", section).strip("_").lower()
    return slug or "section"


async def get_paper_markdown(arxiv_id: str, output_dir: str | None = None) -> dict:
    """Return the full Markdown content for an arXiv paper.

    When `output_dir` is None: returns {"arxiv_id", "markdown"}.
    When `output_dir` is provided: writes the markdown to
    `{output_dir}/{arxiv_id}.md` and returns {"arxiv_id", "output_path"}
    instead of the full text.
    On any failure (bad ID, upstream 4xx/5xx, network error) returns
    {"arxiv_id", "markdown": "", "error": "<TypeName: msg>"} and does
    NOT write a file even if output_dir was given.
    """
    try:
        markdown = await get_arxiv_markdown(arxiv_id, remove_toc=False)
    except Exception as exc:
        return {
            "arxiv_id": arxiv_id,
            "markdown": "",
            "error": f"{type(exc).__name__}: {exc}",
        }
    out = _ensure_output_dir(output_dir)
    if out is None:
        return {"arxiv_id": arxiv_id, "markdown": markdown}
    output_path = out / f"{arxiv_id}.md"
    output_path.write_text(markdown, encoding="utf-8")
    return {"arxiv_id": arxiv_id, "output_path": str(output_path)}


async def get_paper_section(
    arxiv_id: str, section: str, output_dir: str | None = None
) -> dict:
    """Return a single Markdown section from an arXiv paper.

    When `output_dir` is None: returns {"arxiv_id", "section_path", "section"}.
    When `output_dir` is provided: writes the section text to
    `{output_dir}/{arxiv_id}__{slug}.md` and returns
    {"arxiv_id", "section_path", "output_path"}.
    On any failure (bad ID, missing heading, upstream error) returns
    {"arxiv_id", "section_path", "section": "", "error": ...} and does
    NOT write a file. Heading lookup is case-insensitive and ignores
    leading numeric prefixes like "1 Introduction".
    """
    try:
        markdown = await get_arxiv_markdown(arxiv_id, remove_toc=False)
        section_text = extract_markdown_section(markdown, section)
    except Exception as exc:
        return {
            "arxiv_id": arxiv_id,
            "section_path": section,
            "section": "",
            "error": f"{type(exc).__name__}: {exc}",
        }
    out = _ensure_output_dir(output_dir)
    if out is None:
        return {
            "arxiv_id": arxiv_id,
            "section_path": section,
            "section": section_text,
        }
    output_path = out / f"{arxiv_id}__{_section_filename_slug(section)}.md"
    output_path.write_text(section_text, encoding="utf-8")
    return {
        "arxiv_id": arxiv_id,
        "section_path": section,
        "output_path": str(output_path),
    }


async def get_paper_metadata(
    arxiv_ids: list[str], output_dir: str | None = None
) -> dict:
    """Fetch Semantic Scholar metadata for one or more arXiv papers.

    Sends the whole id list in a single POST to /paper/batch. On HTTP
    429 the batch is split in half and each half retried, recursively,
    until every sub-batch either succeeds or shrinks to a single id
    that still 429s (in which case that id gets a structured error).

    Accepts either a list of arxiv ids or a single id string for
    convenience.

    When `output_dir` is None: returns {"results": [...]} where each
    entry is the flat metadata dict, {arxiv_id, found: False}, or
    {arxiv_id, found: False, error: ...}. Result order matches input.

    When `output_dir` is provided: writes one file per id to
    `{output_dir}/{arxiv_id}.json` (containing that id's record) and
    returns {"results": [{arxiv_id, output_path}, ...]} for successful
    or not-found rows. Error rows still carry the error in-line and
    are NOT written to disk.
    """
    if isinstance(arxiv_ids, str):
        arxiv_ids = [arxiv_ids]
    arxiv_ids = list(arxiv_ids)
    if not arxiv_ids:
        return {"results": []}

    try:
        rows = await paper_metadata_simple_batch(arxiv_ids)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        return {
            "results": [
                {"arxiv_id": arxiv_id, "found": False, "error": error}
                for arxiv_id in arxiv_ids
            ],
        }

    out = _ensure_output_dir(output_dir)
    results = []
    for arxiv_id, row in zip(arxiv_ids, rows):
        if not row:
            row = {"arxiv_id": arxiv_id, "found": False}
        elif row.get("found") is not False:
            row.setdefault("arxiv_id", arxiv_id)
        if out is None or "error" in row:
            results.append(row)
            continue
        output_path = out / f"{arxiv_id}.json"
        output_path.write_text(
            json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        entry = {"arxiv_id": arxiv_id, "output_path": str(output_path)}
        if row.get("found") is False:
            entry["found"] = False
        results.append(entry)
    return {"results": results}


async def get_alphaxiv_overview(
    arxiv_id: str, output_dir: str | None = None
) -> dict:
    """Fetch the alphaXiv overview Markdown for an arXiv paper.

    When `output_dir` is None: returns {"arxiv_id", "markdown"}.
    When `output_dir` is provided: writes the full result to
    `{output_dir}/{arxiv_id}.json` and returns
    {"arxiv_id", "output_path"} instead of the markdown body.
    On any failure (no alphaXiv overview, network error, upstream API
    change), returns {"arxiv_id", "markdown": "", "error": ...} and
    does NOT write a file.
    """
    try:
        markdown = await get_alphaxiv_overview_markdown(arxiv_id)
    except Exception as exc:
        return {
            "arxiv_id": arxiv_id,
            "markdown": "",
            "error": f"{type(exc).__name__}: {exc}",
        }
    out = _ensure_output_dir(output_dir)
    if out is None:
        return {"arxiv_id": arxiv_id, "markdown": markdown}
    output_path = out / f"{arxiv_id}.json"
    output_path.write_text(
        json.dumps({"arxiv_id": arxiv_id, "markdown": markdown},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"arxiv_id": arxiv_id, "output_path": str(output_path)}

if __name__ == "__main__":
    queries = [
        "transformer language models",
        "large language models",
    ]
    survey_queries = [
        "survey transformer language models",
        "survey large language models",
    ]
    asyncio.run(bulk_normal_start_search(
        queries,
        survey_queries,
        positive_keywords=["transformer", "language model", "llm"],
        negative_keywords=["robotics", "vision"],
        output_dir="./data/bulk_research_result",
    ))
