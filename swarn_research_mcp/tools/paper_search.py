import asyncio
import ast
import datetime
import json
import re
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from swarn_research_mcp.services.semantic_scholar import (
    paper_relevance_search, 
    recommendations_multi
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


async def bulk_normal_start_search(
    queries, 
    survey_queries, 
    positive_keywords,
    negative_keywords,
    output_dir
):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    current_date = datetime.datetime.now()
    current_year = current_date.year
    start_year = str(current_year - 4)
    trending_months = _recent_month_filters(current_year, current_date.month, month_count=12)
    influence_search_windows = [
        {
            "label": "older",
            "start_year": str(current_year - 4),
            "end_year": str(current_year - 2),
            "limit": 10,
            "min_citation_count": 50,
            "depth": 1,
            "citation_limit_per_level": 20,
            "min_citation_depth": 30,
        },
        {
            "label": "middle",
            "start_year": str(current_year - 2),
            "end_year": str(current_year - 1),
            "limit": 10,
            "min_citation_count": 30,
            "depth": 2,
            "citation_limit_per_level": 30,
            "min_citation_depth": 20,
        },
        {
            "label": "recent",
            "start_year": str(current_year - 1),
            "end_year": None,
            "limit": 10,
            "min_citation_count": 10,
            "depth": 3,
            "citation_limit_per_level": 20,
            "min_citation_depth": 10,
        },
    ]
    bulk_results = {}
    excluded_paper_ids = set()
    print(
        f"Bulk search start: normal_queries={len(queries)}, "
        f"survey_queries={len(survey_queries)}, start_year={start_year}, "
        f"trending_months={trending_months[0]}..{trending_months[-1]}"
    )
    monthly_trending_tasks = [
        asyncio.create_task(collect_huggingface_trending_papers(month=month, limit=30))
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
                max_papers=100,
            ))
            for window in influence_search_windows
        ]
        trending_task = asyncio.create_task(search_huggingface_papers(query=query, limit=120))

        trending_paper_result = await trending_task
        print(f"Bulk normal query {index}: HuggingFace results={len(trending_paper_result)}")
        recommendations_task = asyncio.create_task(
            recommendations_multi(list(trending_paper_result.keys())[:100], limit=100)
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
            limit=5,
            start_year=str(datetime.datetime.now().year - 2),
            end_year=str(datetime.datetime.now().year - 1),
            min_citation_count=30,
            depth=1,
            citation_limit_per_level=30,
            min_citation_depth=30,
            exclude_paper_ids=set(excluded_paper_ids),
            max_papers=100,
        ))
        survey_result_new = asyncio.create_task(paper_relevance_search(
            query=survey_query,
            limit=5,
            start_year=str(datetime.datetime.now().year - 1),
            min_citation_count=10,
            depth=1,
            citation_limit_per_level=30,
            min_citation_depth=10,
            exclude_paper_ids=set(excluded_paper_ids),
            max_papers=100,
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

    output_path = output_dir / f"bulk_search_results_{int(time())}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(selected_results["papers"], f, ensure_ascii=False, indent=2)
    print("Bulk search done")
    selected_results["output_path"] = str(output_path)
    return selected_results


async def get_paper_markdown(arxiv_id: str) -> str:
    """Return the full Markdown content for an arXiv paper."""
    return await get_arxiv_markdown(arxiv_id, remove_toc=False)


async def get_paper_section(arxiv_id: str, section: str) -> str:
    """Return a single Markdown section from an arXiv paper."""
    markdown = await get_arxiv_markdown(arxiv_id, remove_toc=False)
    return extract_markdown_section(markdown, section)


async def get_alphaxiv_overview(arxiv_id: str) -> dict[str, str]:
    """Fetch the alphaXiv overview Markdown for an arXiv paper.

    Returns a dict with arxiv_id and markdown so MCP clients can
    persist both fields without re-deriving them.
    """
    markdown = await get_alphaxiv_overview_markdown(arxiv_id)
    return {"arxiv_id": arxiv_id, "markdown": markdown}

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
