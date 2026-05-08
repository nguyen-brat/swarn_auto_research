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


def _resolve_alphaxiv_paper_version_id(arxiv_id: str) -> str:
    url = f"{ALPHAXIV_BASE_URL}/papers/v3/legacy/{arxiv_id}"
    data = http_get(url)
    return data["paper"]["paper_version"]["id"]


def _get_alphaxiv_overview_markdown_sync(arxiv_id: str, language: str = "en") -> str:
    paper_version_id = _resolve_alphaxiv_paper_version_id(arxiv_id)
    url = f"{ALPHAXIV_BASE_URL}/papers/v3/{paper_version_id}/overview/{language}"
    data = http_get(url)
    return data.get("overview", "")


async def get_alphaxiv_overview_markdown(arxiv_id: str, language: str = "en") -> str:
    return await run_blocking(_get_alphaxiv_overview_markdown_sync, arxiv_id, language)


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
