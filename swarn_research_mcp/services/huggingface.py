import asyncio
import os
import re

from dotenv import load_dotenv
from .utils import http_get, run_blocking


load_dotenv()

HF_PAPERS_SEARCH_URL = "https://huggingface.co/api/papers/search"
HF_DAILY_PAPERS_URL = "https://huggingface.co/api/daily_papers"
HF_TOKEN = os.getenv("HF_TOKEN", "")


def _huggingface_auth_headers():
    if not HF_TOKEN:
        raise ValueError("HF_TOKEN is not set")
    return {"Authorization": f"Bearer {HF_TOKEN}"}


def _paper_summaries_from_huggingface_items(items):
    paper_summaries = {}

    for item in items:
        paper = item.get("paper", {})
        paper_id = paper.get("id")
        summary = paper.get("summary") or item.get("summary")

        if paper_id and summary:
            paper_summaries[paper_id] = summary

    return paper_summaries


def _normalize_month_filter(month: str, year: str | int | None = None) -> str:
    month = str(month).strip()
    match = re.fullmatch(r"(\d{4})-(\d{1,2})", month)
    if match:
        year = match.group(1)
        month = match.group(2)
    elif year is None:
        raise ValueError("year is required when month is not in 'YYYY-MM' format")

    if month.startswith("0") and len(month) > 1:
        month = month.lstrip("0")
    if not month.isdigit() or not 1 <= int(month) <= 12:
        raise ValueError("month must be a string from '1' to '12' or 'YYYY-MM'")

    year = str(year).strip()
    if not re.fullmatch(r"\d{4}", year):
        raise ValueError("year must be a 4 digit string or integer")
    return f"{year}-{int(month):02d}"


def _search_huggingface_papers_sync(query: str, limit: int = 120) -> dict:
    params = {
        "q": query,
        "limit": limit,
    }
    result = http_get(HF_PAPERS_SEARCH_URL, params=params, headers=_huggingface_auth_headers())
    sorted_result = sorted(
        result,
        key=lambda item: item.get("paper", {}).get("upvotes", item.get("upvotes", 0)),
        reverse=True,
    )
    return _paper_summaries_from_huggingface_items(sorted_result)


async def search_huggingface_papers(query: str, limit: int = 120) -> dict:
    return await run_blocking(_search_huggingface_papers_sync, query, limit)


def _collect_huggingface_trending_papers_sync(
    month: str,
    year: str | int | None = None,
    limit: int = 50,
    page: int = 0,
) -> dict:
    params = {
        "p": page,
        "limit": limit,
        "month": _normalize_month_filter(month, year),
        "sort": "publishedAt",
    }
    result = http_get(
        HF_DAILY_PAPERS_URL,
        params=params,
        headers=_huggingface_auth_headers(),
    )
    return _paper_summaries_from_huggingface_items(result)


async def collect_huggingface_trending_papers(
    month: str,
    year: str | int | None = None,
    limit: int = 50,
    page: int = 0,
) -> dict:
    return await run_blocking(_collect_huggingface_trending_papers_sync, month, year, limit, page)


if __name__ == "__main__":
    # result = asyncio.run(search_huggingface_papers("recent advantage LLM architecture design", limit=2))
    result = asyncio.run(collect_huggingface_trending_papers(month="2025-06", limit=5))
    print(result)
