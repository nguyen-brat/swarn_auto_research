import asyncio

from .utils import http_get, run_blocking
ALPHAXIV_BASE_URL = "https://api.alphaxiv.org"

def _search_alphaxiv_papers_sync(query: str) -> dict:
    url = "https://api.alphaxiv.org/v1/search/paper"
    params = {
        "q": query
    }
    return http_get(url, params=params)


async def search_alphaxiv_papers(query: str) -> dict:
    return await run_blocking(_search_alphaxiv_papers_sync, query)


def _get_alphaxiv_overview_markdown_sync(arxiv_id: str) -> str:
    url = f"{ALPHAXIV_BASE_URL}/overview/{arxiv_id}.md"
    return http_get(url, return_json=False)


async def get_alphaxiv_overview_markdown(arxiv_id: str) -> str:
    return await run_blocking(_get_alphaxiv_overview_markdown_sync, arxiv_id)


def _get_alphaxiv_similar_papers_sync(arxiv_id: str) -> dict:
    url = f"{ALPHAXIV_BASE_URL}/papers/v3/{arxiv_id}/similar-papers"
    return http_get(url)


async def get_alphaxiv_similar_papers(arxiv_id: str) -> dict:
    return await run_blocking(_get_alphaxiv_similar_papers_sync, arxiv_id)


def _get_alphaxiv_preview_sync(arxiv_id: str) -> dict:
    url = f"{ALPHAXIV_BASE_URL}/papers/v3/{arxiv_id}/preview"
    return http_get(url)


async def get_alphaxiv_preview(arxiv_id: str) -> dict:
    return await run_blocking(_get_alphaxiv_preview_sync, arxiv_id)


if __name__ == "__main__":
    result = asyncio.run(get_alphaxiv_similar_papers("2504.04264"))
    print(result)
