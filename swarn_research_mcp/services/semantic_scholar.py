"""
================================================
  Semantic Scholar API service helpers
================================================

APIs used:
  1. Academic Graph API  -> https://api.semanticscholar.org/graph/v1
  2. Recommendations API -> https://api.semanticscholar.org/recommendations/v1

Auth: Public endpoints work without a key (shared rate-limit).
      Add your key via the "x-api-key" header for dedicated 1 RPS.
"""

import asyncio
import datetime
import json
import math
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock
from time import sleep

from dotenv import load_dotenv

from . import persistent_cache
from .utils import http_get, http_post, run_blocking, safe_get

load_dotenv()
# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GRAPH_BASE = "https://api.semanticscholar.org/graph/v1"
RECOMM_BASE = "https://api.semanticscholar.org/recommendations/v1"


def _parse_semantic_scholar_api_keys():
    keys: list[str] = []

    def add_key(value):
        text = str(value).strip().strip('"').strip("'")
        if text and text not in keys:
            keys.append(text)

    raw_keys = os.getenv("S2_KEYS", "")
    if raw_keys.strip().startswith("["):
        try:
            parsed = json.loads(raw_keys)
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, list):
            for item in parsed:
                add_key(item)
    else:
        for item in re.split(r"[\n,]", raw_keys):
            add_key(item)

    add_key(os.getenv("S2_KEY", ""))
    return keys


SEMANTIC_SCHOLAR_API_KEYS = _parse_semantic_scholar_api_keys()
_SEMANTIC_SCHOLAR_API_KEY_INDEX = 0
SEMANTIC_SCHOLAR_API_KEY_LOCK = Lock()
HEADERS = (
    {"x-api-key": SEMANTIC_SCHOLAR_API_KEYS[_SEMANTIC_SCHOLAR_API_KEY_INDEX]}
    if SEMANTIC_SCHOLAR_API_KEYS
    else {}
)
PAPER_WITH_LINKED_FIELDS = (
    "paperId,title,year,externalIds,abstract,citationCount,referenceCount,"
    "citations.paperId,citations.title,citations.year,citations.abstract,citations.externalIds,"
    "citations.citationCount,citations.referenceCount,"
    "references.paperId,references.title,references.year,references.externalIds"
)
PAPER_SEARCH_FIELDS = "paperId,title,year,externalIds,abstract,citationCount,referenceCount"
PAPER_ABSTRACT_FIELDS = "paperId,externalIds,abstract"
RECOMMENDATION_FIELDS = "paperId,title,year,externalIds,abstract,citationCount,referenceCount"
SEMANTIC_SCHOLAR_BATCH_LIMIT = 500
SEMANTIC_SCHOLAR_LINKED_BATCH_LIMIT = int(os.getenv("S2_LINKED_BATCH_LIMIT", SEMANTIC_SCHOLAR_BATCH_LIMIT))
SEMANTIC_SCHOLAR_TIMEOUT = 300
SEMANTIC_SCHOLAR_REQUEST_DELAY_SECONDS = 1
SEMANTIC_SCHOLAR_RATE_LIMIT_RETRIES = 5
SEMANTIC_SCHOLAR_RATE_LIMIT_BACKOFF_SECONDS = float(
    os.getenv("S2_RATE_LIMIT_BACKOFF_SECONDS", "30")
)
SEMANTIC_SCHOLAR_PAPER_ID_PATTERN = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
ARXIV_ID_PATTERN = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$", re.IGNORECASE)


def _parse_memory_cache_capacity(value, default=256):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


class _BoundedPaperDetailCache:
    def __init__(self, capacity):
        self._groups = OrderedDict()
        self._alias_to_group = {}
        self.capacity = capacity

    @property
    def capacity(self):
        return self._capacity

    @capacity.setter
    def capacity(self, value):
        self._capacity = _parse_memory_cache_capacity(value)
        self._trim()

    def get(self, key):
        group_key = self._alias_to_group.get(key)
        if group_key is None:
            return None
        group = self._groups.pop(group_key)
        self._groups[group_key] = group
        return group["paper"]

    def __setitem__(self, key, value):
        self.set_many([key], value)

    def set_many(self, keys, paper):
        if self.capacity <= 0:
            return
        aliases = list(dict.fromkeys(key for key in keys if key))
        if not aliases:
            return
        group_key = (
            str(paper.get("paperId") or aliases[0])
            if isinstance(paper, dict)
            else aliases[0]
        )
        existing_group_keys = {
            self._alias_to_group[alias]
            for alias in aliases
            if alias in self._alias_to_group
        }
        existing_group_keys.add(group_key)
        for existing_group_key in existing_group_keys:
            self._remove_group(existing_group_key)
        self._groups[group_key] = {"paper": paper, "aliases": aliases}
        for alias in aliases:
            self._alias_to_group[alias] = group_key
        self._trim()

    def clear(self):
        self._groups.clear()
        self._alias_to_group.clear()

    def __len__(self):
        return len(self._groups)

    def _remove_group(self, group_key):
        group = self._groups.pop(group_key, None)
        if group is None:
            return
        for alias in group["aliases"]:
            self._alias_to_group.pop(alias, None)

    def _trim(self):
        while len(self._groups) > self.capacity:
            group_key, group = self._groups.popitem(last=False)
            for alias in group["aliases"]:
                self._alias_to_group.pop(alias, None)


PAPER_DETAIL_CACHE = _BoundedPaperDetailCache(
    os.environ.get("SWARN_S2_MEMORY_CACHE_MAX", "256")
)
PAPER_DETAIL_CACHE_LOCK = Lock()
PAPER_DETAIL_FETCH_LOCK = Lock()
SEMANTIC_SCHOLAR_REQUEST_LOCK = Lock()


@dataclass
class SemanticScholarCitationPaper:
    arxiv_id: str | None
    scholar_semantic_id: str | None
    title: str | None
    year: int | None
    abstract: str | None = None
    citations: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    citationCount: int = 0
    referenceCount: int = 0
    citation_details: list["SemanticScholarCitationPaper"] = field(default_factory=list)

    def to_dict(self):
        return {
            "arxiv_id": self.arxiv_id,
            "scholar_semantic_id": self.scholar_semantic_id,
            "title": self.title,
            "year": self.year,
            "abstract": self.abstract,
            "citations": self.citations,
            "references": self.references,
            "citationCount": self.citationCount,
            "referenceCount": self.referenceCount,
            "citation_details": [
                citation.to_dict()
                for citation in self.citation_details
            ],
        }


@dataclass
class SemanticScholarPaper:
    arxiv_id: str | None
    scholar_semantic_id: str | None
    abstract: str | None
    year: int | None = None
    citations: list[str] = field(default_factory=list)
    citation_details: list[SemanticScholarCitationPaper] = field(default_factory=list)
    citationCount: int = 0
    references: list[str] = field(default_factory=list)
    referenceCount: int = 0

    def to_dict(self):
        return {
            "arxiv_id": self.arxiv_id,
            "scholar_semantic_id": self.scholar_semantic_id,
            "abstract": self.abstract,
            "citations": self.citations,
            "citation_details": [
                citation.to_dict()
                for citation in self.citation_details
            ],
            "citationCount": self.citationCount,
            "references": self.references,
            "referenceCount": self.referenceCount,
        }

def paper_impact_score(
    citations_count: int,
    public_year: int,
) -> float:
    """
    Impact score designed for paper retrieval.

    It rewards:
    - high total citations
    - high citations per year
    - recent publication year
    """
    oldest_paper_age = 6
    current_year = datetime.datetime.now().year

    if citations_count < 0:
        raise ValueError("citations_count must be >= 0")

    if public_year > current_year:
        raise ValueError("public_year cannot be in the future")

    if oldest_paper_age <= 0:
        raise ValueError("oldest_paper_age must be > 0")

    paper_age = max(1, current_year - public_year + 1)

    total_citation_score = math.log1p(citations_count) / math.log1p(10_000)
    total_citation_score = min(total_citation_score, 1.0)

    citations_per_year = citations_count / paper_age
    velocity_score = math.log1p(citations_per_year) / math.log1p(1_000)
    velocity_score = min(velocity_score, 1.0)

    recency_score = 1 - ((paper_age - 1) / oldest_paper_age)
    recency_score = max(0.0, min(recency_score, 1.0))

    score = (
        0.40 * total_citation_score
        + 0.35 * velocity_score
        + 0.25 * recency_score
    )

    return round(score, 6)


def _extract_arxiv_id(paper):
    return safe_get(paper, "externalIds.Arxiv")


def _paper_cache_keys_from_id(paper_id):
    if not paper_id:
        return []
    paper_id = str(paper_id)
    keys = [paper_id]
    arxiv_id = _normalize_arxiv_external_id(paper_id)
    if arxiv_id and arxiv_id not in keys:
        keys.append(arxiv_id)
    return keys


def _paper_cache_keys_from_paper(paper):
    keys = _paper_cache_keys_from_id(paper.get("paperId"))
    arxiv_id = _extract_arxiv_id(paper)
    if arxiv_id:
        formatted_arxiv_id = f"ArXiv:{arxiv_id}"
        keys.extend([arxiv_id, formatted_arxiv_id])
    return list(dict.fromkeys(keys))


def _get_cached_paper_detail(paper_id):
    keys = _paper_cache_keys_from_id(paper_id)
    with PAPER_DETAIL_CACHE_LOCK:
        for key in keys:
            paper = PAPER_DETAIL_CACHE.get(key)
            if paper:
                return paper
    # Fall back to persistent disk cache.
    paper = persistent_cache.get(keys)
    if paper:
        # Promote to in-memory cache so subsequent hits skip the file read.
        with PAPER_DETAIL_CACHE_LOCK:
            PAPER_DETAIL_CACHE.set_many(_paper_cache_keys_from_paper(paper), paper)
        return paper
    return None


def _cache_paper_detail(paper):
    if not paper:
        return
    keys = _paper_cache_keys_from_paper(paper)
    with PAPER_DETAIL_CACHE_LOCK:
        PAPER_DETAIL_CACHE.set_many(keys, paper)
    # Persist to disk cache (batched flush, atomic write).
    persistent_cache.put(keys, paper)


def _normalize_exclude_paper_ids(exclude_paper_ids):
    return {
        str(paper_id)
        for paper_id in (exclude_paper_ids or set())
        if paper_id
    }


def _paper_is_excluded(paper, exclude_paper_ids):
    if not exclude_paper_ids:
        return False
    return (
        paper.get("paperId") in exclude_paper_ids
        or _extract_arxiv_id(paper) in exclude_paper_ids
    )


def _node_is_excluded(node, exclude_paper_ids):
    if not exclude_paper_ids:
        return False
    return (
        node.scholar_semantic_id in exclude_paper_ids
        or node.arxiv_id in exclude_paper_ids
    )


def _filter_linked_papers(papers, exclude_paper_ids):
    return [
        paper
        for paper in (papers or [])
        if not _paper_is_excluded(paper, exclude_paper_ids)
    ]


def _paper_to_summary(paper):
    return SemanticScholarCitationPaper(
        arxiv_id=_extract_arxiv_id(paper),
        scholar_semantic_id=paper.get("paperId"),
        title=paper.get("title"),
        year=paper.get("year"),
        abstract=paper.get("abstract"),
        citationCount=paper.get("citationCount", 0) or 0,
        referenceCount=paper.get("referenceCount", 0) or 0,
    )


def _arxiv_ids_from_linked_papers(papers):
    papers = papers or []
    return [
        linked_paper.get("externalIds", {}).get("ArXiv")
        for linked_paper in papers
        if safe_get(linked_paper, "externalIds.Arxiv")
    ]


def _paper_to_detail_node(
    paper,
    citation_limit_per_level=100,
    min_citation_count=0,
    exclude_paper_ids=None,
):
    citations = _filter_linked_papers(paper.get("citations", []), exclude_paper_ids)
    references = _filter_linked_papers(paper.get("references", []), exclude_paper_ids)
    node = _paper_to_summary(paper)
    node.abstract = paper.get("abstract")
    node.citations = _arxiv_ids_from_linked_papers(citations)
    node.references = _arxiv_ids_from_linked_papers(references)
    node.citation_details = _citation_nodes_from_paper(
        {"citations": citations},
        limit=citation_limit_per_level,
        min_citation_count=min_citation_count,
        exclude_paper_ids=exclude_paper_ids,
    )
    return node


def _paper_ids_from_nodes(nodes):
    return [
        node.scholar_semantic_id
        for node in nodes
        if node.scholar_semantic_id
    ]


def _is_semantic_scholar_paper_id(paper_id):
    return bool(paper_id and SEMANTIC_SCHOLAR_PAPER_ID_PATTERN.match(str(paper_id)))


def _normalize_arxiv_external_id(paper_id):
    if not paper_id:
        return None
    normalized_id = str(paper_id).strip()
    normalized_id = normalized_id.removeprefix("arXiv:")
    normalized_id = normalized_id.removeprefix("ArXiv:")
    normalized_id = normalized_id.removeprefix("ARXIV:")
    normalized_id = normalized_id.removeprefix("https://arxiv.org/abs/")
    normalized_id = normalized_id.removeprefix("http://arxiv.org/abs/")
    normalized_id = normalized_id.removeprefix("https://arxiv.org/pdf/")
    normalized_id = normalized_id.removeprefix("http://arxiv.org/pdf/")
    normalized_id = normalized_id.removesuffix(".pdf")
    if not ARXIV_ID_PATTERN.match(normalized_id):
        return None
    return f"ArXiv:{normalized_id}"


def _recommendation_seed_id(paper_id):
    if not paper_id:
        return None
    paper_id = str(paper_id).strip()
    if _is_semantic_scholar_paper_id(paper_id):
        return paper_id
    return _normalize_arxiv_external_id(paper_id) or paper_id


def _is_rate_limit_error(exc):
    return getattr(getattr(exc, "response", None), "status_code", None) == 429


def _is_bad_request_error(exc):
    return getattr(getattr(exc, "response", None), "status_code", None) == 400


def _rate_limit_backoff_seconds(exc):
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    retry_after = headers.get("Retry-After") if hasattr(headers, "get") else None
    try:
        return max(0.0, float(retry_after))
    except (TypeError, ValueError):
        return SEMANTIC_SCHOLAR_RATE_LIMIT_BACKOFF_SECONDS


def _rotate_semantic_scholar_api_key():
    global _SEMANTIC_SCHOLAR_API_KEY_INDEX
    if len(SEMANTIC_SCHOLAR_API_KEYS) < 2:
        return False
    with SEMANTIC_SCHOLAR_API_KEY_LOCK:
        _SEMANTIC_SCHOLAR_API_KEY_INDEX = (
            _SEMANTIC_SCHOLAR_API_KEY_INDEX + 1
        ) % len(SEMANTIC_SCHOLAR_API_KEYS)
        HEADERS["x-api-key"] = SEMANTIC_SCHOLAR_API_KEYS[
            _SEMANTIC_SCHOLAR_API_KEY_INDEX
        ]
    print("  S2 rate limit: rotated to next API key")
    return True


def _run_semantic_scholar_request(request_func):
    """Serialize Semantic Scholar requests to respect the public 1 RPS limit."""
    with SEMANTIC_SCHOLAR_REQUEST_LOCK:
        sleep(SEMANTIC_SCHOLAR_REQUEST_DELAY_SECONDS)
        try:
            return request_func()
        except Exception as exc:
            if _is_rate_limit_error(exc):
                if not _rotate_semantic_scholar_api_key():
                    sleep(_rate_limit_backoff_seconds(exc))
            raise


def _semantic_scholar_post(
    url,
    payload,
    params=None,
    headers=None,
    direct_retries=None,
    proxy_retries=None,
):
    request_options = {}
    if direct_retries is not None:
        request_options["direct_retries"] = direct_retries
    if proxy_retries is not None:
        request_options["proxy_retries"] = proxy_retries

    last_error = None
    for _attempt in range(SEMANTIC_SCHOLAR_RATE_LIMIT_RETRIES):
        try:
            return _run_semantic_scholar_request(
                lambda: http_post(
                    url,
                    payload,
                    params=params,
                    headers=headers,
                    timeout=SEMANTIC_SCHOLAR_TIMEOUT,
                    **request_options,
                )
            )
        except Exception as exc:
            if not _is_rate_limit_error(exc):
                raise
            last_error = exc
    raise last_error


def _semantic_scholar_get(
    url,
    params=None,
    headers=None,
):
    last_error = None
    for _attempt in range(SEMANTIC_SCHOLAR_RATE_LIMIT_RETRIES):
        try:
            return _run_semantic_scholar_request(
                lambda: http_get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=SEMANTIC_SCHOLAR_TIMEOUT,
                )
            )
        except Exception as exc:
            if not _is_rate_limit_error(exc):
                raise
            last_error = exc
    raise last_error


def _normalize_batch_response(data):
    if isinstance(data, dict):
        return data.get("data", [])
    return data or []


def _paper_to_result_dict(paper, use_api_counts=False):
    arxiv_id = safe_get(paper, "externalIds.Arxiv")
    references = _arxiv_ids_from_linked_papers(paper.get("references", []))
    citations = _arxiv_ids_from_linked_papers(paper.get("citations", []))
    if use_api_counts:
        citation_count = paper.get("citationCount", 0) or 0
        reference_count = paper.get("referenceCount", 0) or 0
    else:
        citation_count = len(citations)
        reference_count = len(references)
    return {
        "arxiv_id": arxiv_id,
        "scholar_semantic_id": paper.get("paperId"),
        "abstract": paper.get("abstract"),
        "citations": citations,
        "citationCount": citation_count,
        "references": references,
        "referenceCount": reference_count,
    }


def _paper_to_recommendation_result_dict(paper):
    result = _paper_to_result_dict(paper, use_api_counts=True)
    result["citations"] = []
    result["references"] = []
    return result


def _fetch_papers_batch_chunk_by_ids(paper_ids):
    if not paper_ids:
        return []

    print(f"  S2 batch detail fetch: {len(paper_ids)} paper ids")
    try:
        data = _semantic_scholar_post(
            f"{GRAPH_BASE}/paper/batch",
            {"ids": paper_ids},
            params={"fields": PAPER_WITH_LINKED_FIELDS},
            headers=HEADERS,
            direct_retries=1,
            proxy_retries=0,
        )
        return [
            paper
            for paper in _normalize_batch_response(data)
            if paper
        ]
    except Exception as exc:
        if not _is_bad_request_error(exc):
            raise
        if len(paper_ids) == 1:
            print("  S2 linked detail rejected for 1 paper; retrying with simple fields")
            data = _semantic_scholar_post(
                f"{GRAPH_BASE}/paper/batch",
                {"ids": paper_ids},
                params={"fields": PAPER_SEARCH_FIELDS},
                headers=HEADERS,
                direct_retries=1,
                proxy_retries=0,
            )
            return [
                paper
                for paper in _normalize_batch_response(data)
                if paper
            ]

        mid = len(paper_ids) // 2
        print(
            f"  S2 batch detail rejected; splitting {len(paper_ids)} ids "
            f"into {mid} and {len(paper_ids) - mid}"
        )
        return (
            _fetch_papers_batch_chunk_by_ids(paper_ids[:mid])
            + _fetch_papers_batch_chunk_by_ids(paper_ids[mid:])
        )


def _citation_nodes_from_paper(
    paper,
    limit=100,
    min_citation_count=0,
    exclude_paper_ids=None,
):
    nodes = []
    citations = sorted(
        [
            citation
            for citation in paper.get("citations", []) or []
            if (citation.get("citationCount", 0) or 0) >= min_citation_count
            and not _paper_is_excluded(citation, exclude_paper_ids)
        ],
        key=lambda citation: citation.get("citationCount", 0) or 0,
        reverse=True,
    )
    for citation in citations[:limit]:
        node = _paper_to_summary(citation)
        nodes.append(node)
    return nodes


def _fetch_papers_batch_by_ids(paper_ids):
    if not paper_ids:
        return []

    with PAPER_DETAIL_FETCH_LOCK:
        return _fetch_uncached_papers_batch_by_ids(paper_ids)


def _fetch_uncached_papers_batch_by_ids(paper_ids):
    if not paper_ids:
        return []

    unique_ids = list(dict.fromkeys(paper_ids))
    papers_by_requested_id = {}
    missing_ids = []

    for paper_id in unique_ids:
        cached_paper = _get_cached_paper_detail(paper_id)
        if cached_paper:
            papers_by_requested_id[paper_id] = cached_paper
        else:
            missing_ids.append(paper_id)

    cache_hits = len(unique_ids) - len(missing_ids)
    print(
        f"  S2 detail cache: {cache_hits} hit, {len(missing_ids)} miss "
        f"from {len(unique_ids)} requested ids"
    )
    for start in range(0, len(missing_ids), SEMANTIC_SCHOLAR_LINKED_BATCH_LIMIT):
        chunk = missing_ids[start:start + SEMANTIC_SCHOLAR_LINKED_BATCH_LIMIT]
        print(
            f"  S2 detail chunk {start // SEMANTIC_SCHOLAR_LINKED_BATCH_LIMIT + 1}: "
            f"{len(chunk)} ids"
        )
        fetched_papers = _fetch_papers_batch_chunk_by_ids(chunk)
        for paper in fetched_papers:
            _cache_paper_detail(paper)
        fetched_by_id = {
            key: paper
            for paper in fetched_papers
            for key in _paper_cache_keys_from_paper(paper)
        }
        for paper_id in chunk:
            paper = fetched_by_id.get(paper_id)
            if paper:
                papers_by_requested_id[paper_id] = paper

    return [
        papers_by_requested_id[paper_id]
        for paper_id in unique_ids
        if paper_id in papers_by_requested_id
    ]


def _fetch_paper_abstracts_batch_by_arxiv_ids(arxiv_ids):
    if not arxiv_ids:
        return []

    ids = [
        paper_id if str(paper_id).startswith(("ArXiv:", "arXiv:", "ARXIV:")) else f"ArXiv:{paper_id}"
        for paper_id in arxiv_ids
    ]
    unique_ids = list(dict.fromkeys(ids))
    return _fetch_paper_abstracts_batch_chunk(unique_ids)


def _fetch_paper_abstracts_batch_chunk(arxiv_ids):
    if not arxiv_ids:
        return []
    if len(arxiv_ids) > SEMANTIC_SCHOLAR_BATCH_LIMIT:
        result = []
        for start in range(0, len(arxiv_ids), SEMANTIC_SCHOLAR_BATCH_LIMIT):
            chunk = arxiv_ids[start:start + SEMANTIC_SCHOLAR_BATCH_LIMIT]
            result.extend(_fetch_paper_abstracts_batch_chunk(chunk))
        return result

    try:
        data = _semantic_scholar_post(
            f"{GRAPH_BASE}/paper/batch",
            {"ids": arxiv_ids},
            params={"fields": PAPER_ABSTRACT_FIELDS},
            headers=HEADERS,
        )
    except Exception as exc:
        if not _is_rate_limit_error(exc):
            raise
        if len(arxiv_ids) == 1:
            return []
        mid = len(arxiv_ids) // 2
        left = _fetch_paper_abstracts_batch_chunk(arxiv_ids[:mid])
        right = _fetch_paper_abstracts_batch_chunk(arxiv_ids[mid:])
        return left + right
    return [paper for paper in _normalize_batch_response(data) if paper]


def _format_recommendation_seed_ids(paper_ids):
    if not paper_ids:
        return []
    return [
        seed_id
        for seed_id in (
            _recommendation_seed_id(paper_id)
            for paper_id in paper_ids
        )
        if seed_id
    ]


def _enrich_citation_nodes_with_batch(
    nodes,
    depth,
    limit=100,
    min_citation_depth=0,
    exclude_paper_ids=None,
):
    if depth <= 1 or not nodes:
        if nodes:
            print(f"  S2 citation expansion stop: depth={depth}, nodes={len(nodes)}")
        return

    expandable_nodes = [
        node
        for node in nodes
        if node.citationCount >= min_citation_depth
        and not _node_is_excluded(node, exclude_paper_ids)
    ]
    print(
        f"  S2 citation expansion: depth={depth}, nodes={len(nodes)}, "
        f"expandable={len(expandable_nodes)}, min_citation_depth={min_citation_depth}"
    )
    if not expandable_nodes:
        return

    papers = [
        paper
        for paper in _fetch_papers_batch_by_ids(_paper_ids_from_nodes(expandable_nodes))
        if not _paper_is_excluded(paper, exclude_paper_ids)
    ]
    papers_by_id = {paper.get("paperId"): paper for paper in papers}
    next_level_nodes = []

    for node in expandable_nodes:
        paper = papers_by_id.get(node.scholar_semantic_id)
        if not paper:
            continue
        detailed_node = _paper_to_detail_node(
            paper,
            citation_limit_per_level=limit,
            min_citation_count=min_citation_depth,
            exclude_paper_ids=exclude_paper_ids,
        )
        node.arxiv_id = detailed_node.arxiv_id
        node.scholar_semantic_id = detailed_node.scholar_semantic_id
        node.title = detailed_node.title
        node.year = detailed_node.year
        node.abstract = detailed_node.abstract
        node.citations = detailed_node.citations
        node.references = detailed_node.references
        node.citationCount = detailed_node.citationCount
        node.referenceCount = detailed_node.referenceCount
        node.citation_details = detailed_node.citation_details
        child_nodes = node.citation_details
        next_level_nodes.extend(child_nodes)

    print(
        f"  S2 citation expansion complete: depth={depth}, "
        f"next_level_nodes={len(next_level_nodes)}"
    )
    _enrich_citation_nodes_with_batch(
        next_level_nodes,
        depth - 1,
        limit=limit,
        min_citation_depth=min_citation_depth,
        exclude_paper_ids=exclude_paper_ids,
    )


def _build_paper_result(
    paper,
    depth=1,
    citation_limit_per_level=100,
    min_citation_depth=0,
    exclude_paper_ids=None,
):
    direct_citations = _filter_linked_papers(paper.get("citations", []), exclude_paper_ids)
    reference_papers = _filter_linked_papers(paper.get("references", []), exclude_paper_ids)
    references = [
        r.get("externalIds", {}).get("ArXiv")
        for r in reference_papers
        if safe_get(r, "externalIds.ArXiv")
    ]
    citation_details = _citation_nodes_from_paper(
        {"citations": direct_citations},
        limit=citation_limit_per_level,
        min_citation_count=min_citation_depth,
        exclude_paper_ids=exclude_paper_ids,
    )
    _enrich_citation_nodes_with_batch(
        citation_details,
        depth,
        limit=citation_limit_per_level,
        min_citation_depth=min_citation_depth,
        exclude_paper_ids=exclude_paper_ids,
    )

    citations = [
        citation.get("externalIds", {}).get("ArXiv")
        for citation in direct_citations
        if safe_get(citation, "externalIds.Arxiv")
    ]
    return SemanticScholarPaper(
        arxiv_id=_extract_arxiv_id(paper),
        scholar_semantic_id=paper.get("paperId"),
        abstract=paper.get("abstract"),
        year=paper.get("year"),
        citations=citations,
        citation_details=citation_details,
        citationCount=paper.get("citationCount", len(citations)),
        references=references,
        referenceCount=paper.get("referenceCount", len(references)),
    )


def _nested_citation_threshold(min_citation_count=None, min_citation_depth=None):
    if min_citation_depth is None and min_citation_count is not None:
        return min_citation_count
    return min_citation_depth or 0


def _paper_search_params(query, limit, start_year=None, end_year=None, min_citation_count=None):
    if not end_year:
        end_year = time.strftime("%Y")
    return {
        "query": query,
        "fields": PAPER_SEARCH_FIELDS,
        "year": f"{start_year}-{end_year}" if start_year else None,
        "limit": limit,
        "minCitationCount": min_citation_count,
    }


def _root_papers_need_detail(search_results):
    return any(
        "citations" not in paper or "references" not in paper
        for paper in search_results
    )


def _fetch_root_paper_details(search_results):
    paper_ids = [
        paper.get("paperId")
        for paper in search_results
        if paper.get("paperId")
    ]
    print(f"  S2 root detail enrichment: fetching {len(paper_ids)} root papers")
    detailed_papers = _fetch_papers_batch_by_ids(paper_ids)
    print(f"  S2 root detail enrichment: received {len(detailed_papers)} papers")
    return {
        paper.get("paperId"): paper
        for paper in detailed_papers
        if paper and paper.get("paperId")
    }


# 1-A  Paper Relevance Search  (keyword search, ranked by relevance)
# ---------------------------------------------------------------------------
def _paper_relevance_search_models_sync(
    query,
    limit=100,
    start_year=None,
    end_year=None,
    min_citation_count=None,
    depth=1,
    citation_limit_per_level=100,
    min_citation_depth=None,
    exclude_paper_ids=None,
):
    """
    Use case: Find the most relevant papers for a keyword query.
    Endpoint: GET /paper/search
    Best for: Small result sets where ranking quality matters most.
    """
    exclude_paper_ids = _normalize_exclude_paper_ids(exclude_paper_ids)
    nested_min_citation_count = _nested_citation_threshold(
        min_citation_count=min_citation_count,
        min_citation_depth=min_citation_depth,
    )
    params = _paper_search_params(
        query=query,
        limit=limit,
        start_year=start_year,
        end_year=end_year,
        min_citation_count=min_citation_count,
    )
    print(
        f"  S2 relevance search start: query={query!r}, limit={limit}, "
        f"year={params['year']}, minCitationCount={min_citation_count}, depth={depth}"
    )
    # Search-result cache lookup. Key combines the parameters that
    # determine S2's ranked output. Citation traversal still happens
    # downstream (and goes through the paper-detail cache); we only
    # short-circuit the /paper/search call itself here.
    search_cache_key = "|".join([
        str(query),
        str(params.get("year") or ""),
        str(params.get("minCitationCount") or ""),
        str(params.get("limit") or ""),
    ])
    data = persistent_cache.get_search(search_cache_key)
    if data is not None:
        print(f"  S2 relevance search cache HIT: query={query!r}")
    else:
        data = _semantic_scholar_get(
            f"{GRAPH_BASE}/paper/search",
            params=params,
            headers=HEADERS,
        )
        if data:
            persistent_cache.put_search(search_cache_key, data)
    result = []
    if data:
        raw_count = len(data.get("data", []))
        search_results = [
            paper
            for paper in data.get("data", [])
            if not _paper_is_excluded(paper, exclude_paper_ids)
        ]
        print(
            f"  S2 relevance search results: raw={raw_count}, "
            f"after_exclude={len(search_results)}, excluded_ids={len(exclude_paper_ids)}"
        )
        detailed_papers_by_id = (
            _fetch_root_paper_details(search_results)
            if _root_papers_need_detail(search_results)
            else {}
        )

        for p in search_results:
            paper = detailed_papers_by_id.get(p.get("paperId"), p)
            if _paper_is_excluded(paper, exclude_paper_ids):
                continue
            result.append(
                _build_paper_result(
                    paper,
                    depth=depth,
                    citation_limit_per_level=citation_limit_per_level,
                    min_citation_depth=nested_min_citation_count,
                    exclude_paper_ids=exclude_paper_ids,
                )
            )
    print(f"  S2 relevance search done: query={query!r}, model_count={len(result)}")
    return result


async def paper_relevance_search_models(
    query,
    limit=100,
    start_year=None,
    end_year=None,
    min_citation_count=None,
    depth=1,
    citation_limit_per_level=100,
    min_citation_depth=None,
    exclude_paper_ids=None,
):
    return await run_blocking(
        _paper_relevance_search_models_sync,
        query,
        limit,
        start_year,
        end_year,
        min_citation_count,
        depth,
        citation_limit_per_level,
        min_citation_depth,
        exclude_paper_ids,
    )


def _add_paper_abstract(abstracts_by_arxiv_id, arxiv_id, abstract):
    if not arxiv_id:
        return
    if arxiv_id not in abstracts_by_arxiv_id or not abstracts_by_arxiv_id[arxiv_id]:
        abstracts_by_arxiv_id[arxiv_id] = abstract


def _safe_paper_impact_score(citation_count, year):
    if year is None:
        return 0
    try:
        return paper_impact_score(citation_count or 0, int(year))
    except (TypeError, ValueError):
        return 0


def _add_paper_impact_score(impact_scores_by_arxiv_id, arxiv_id, citation_count, year):
    if not arxiv_id:
        return
    score = _safe_paper_impact_score(citation_count, year)
    impact_scores_by_arxiv_id[arxiv_id] = max(
        score,
        impact_scores_by_arxiv_id.get(arxiv_id, 0),
    )


def _add_citation_abstracts(abstracts_by_arxiv_id, impact_scores_by_arxiv_id, citation_details):
    for citation in citation_details:
        _add_paper_abstract(
            abstracts_by_arxiv_id,
            citation.arxiv_id,
            citation.abstract,
        )
        _add_paper_impact_score(
            impact_scores_by_arxiv_id,
            citation.arxiv_id,
            citation.citationCount,
            citation.year,
        )
        _add_citation_abstracts(
            abstracts_by_arxiv_id,
            impact_scores_by_arxiv_id,
            citation.citation_details,
        )


def _fill_missing_abstracts_with_batch(abstracts_by_arxiv_id):
    missing_arxiv_ids = [
        arxiv_id
        for arxiv_id, abstract in abstracts_by_arxiv_id.items()
        if abstract is None
    ]
    if not missing_arxiv_ids:
        print("  S2 abstract fill: no missing abstracts")
        return

    print(f"  S2 abstract fill: fetching {len(missing_arxiv_ids)} missing abstracts")
    filled_count = 0
    for paper in _fetch_paper_abstracts_batch_by_arxiv_ids(missing_arxiv_ids):
        arxiv_id = _extract_arxiv_id(paper)
        abstract = paper.get("abstract")
        if arxiv_id in abstracts_by_arxiv_id and abstract:
            abstracts_by_arxiv_id[arxiv_id] = abstract
            filled_count += 1
    print(f"  S2 abstract fill: filled {filled_count}/{len(missing_arxiv_ids)}")


def _sort_and_limit_papers_by_impact_score(abstracts_by_arxiv_id, impact_scores_by_arxiv_id, max_papers):
    try:
        max_papers = None if max_papers is None else int(max_papers)
    except (TypeError, ValueError):
        raise ValueError("max_papers must be an integer or None")
    if max_papers is not None and max_papers <= 0:
        return {}

    sorted_items = sorted(
        abstracts_by_arxiv_id.items(),
        # Higher paper_impact_score means more impact, so sort descending.
        key=lambda item: impact_scores_by_arxiv_id.get(item[0], 0),
        reverse=True,
    )
    return dict(sorted_items[:max_papers] if max_papers is not None else sorted_items)


def _paper_relevance_search_sync(
    query,
    limit=100,
    start_year=None,
    end_year=None,
    min_citation_count=None,
    depth=1,
    citation_limit_per_level=100,
    min_citation_depth=None,
    exclude_paper_ids=None,
    max_papers=None,
):
    """
    JSON-compatible wrapper for MCP output.
    Returns {arxiv_id: abstract} for search papers, nested citation papers,
    and references from the original search papers only.
    Use paper_relevance_search_models() when you want class instances.
    """
    papers = _paper_relevance_search_models_sync(
        query=query,
        limit=limit,
        start_year=start_year,
        end_year=end_year,
        min_citation_count=min_citation_count,
        depth=depth,
        citation_limit_per_level=citation_limit_per_level,
        min_citation_depth=min_citation_depth,
        exclude_paper_ids=exclude_paper_ids
    )
    print(f"  S2 relevance mapping: converting {len(papers)} root models to arxiv abstract map")

    abstracts_by_arxiv_id = {}
    impact_scores_by_arxiv_id = {}
    for paper in papers:
        _add_paper_abstract(abstracts_by_arxiv_id, paper.arxiv_id, paper.abstract)
        _add_paper_impact_score(
            impact_scores_by_arxiv_id,
            paper.arxiv_id,
            paper.citationCount,
            paper.year,
        )
        _add_citation_abstracts(
            abstracts_by_arxiv_id,
            impact_scores_by_arxiv_id,
            paper.citation_details,
        )
        for reference_arxiv_id in paper.references:
            _add_paper_abstract(abstracts_by_arxiv_id, reference_arxiv_id, None)
            impact_scores_by_arxiv_id.setdefault(reference_arxiv_id, 0)

    _fill_missing_abstracts_with_batch(abstracts_by_arxiv_id)
    abstracts_by_arxiv_id = _sort_and_limit_papers_by_impact_score(
        abstracts_by_arxiv_id,
        impact_scores_by_arxiv_id,
        max_papers,
    )

    print(f"  S2 relevance mapping done: total_arxiv_abstracts={len(abstracts_by_arxiv_id)}")
    return abstracts_by_arxiv_id


async def paper_relevance_search(
    query,
    limit=100,
    start_year=None,
    end_year=None,
    min_citation_count=None,
    depth=1,
    citation_limit_per_level=100,
    min_citation_depth=None,
    exclude_paper_ids=None,
    max_papers=None
):
    return await run_blocking(
        _paper_relevance_search_sync,
        query,
        limit,
        start_year,
        end_year,
        min_citation_count,
        depth,
        citation_limit_per_level,
        min_citation_depth,
        exclude_paper_ids,
        max_papers,
    )


def _paper_relevance_search_json_sync(
    query,
    limit=100,
    start_year=None,
    end_year=None,
    min_citation_count=None,
    depth=1,
    citation_limit_per_level=100,
    min_citation_depth=None,
    exclude_paper_ids=None,
):
    """
    JSON-compatible structured output for callers that need the full paper model.
    """
    return [
        paper.to_dict()
        for paper in _paper_relevance_search_models_sync(
            query=query,
            limit=limit,
            start_year=start_year,
            end_year=end_year,
            min_citation_count=min_citation_count,
            depth=depth,
            citation_limit_per_level=citation_limit_per_level,
            min_citation_depth=min_citation_depth,
            exclude_paper_ids=exclude_paper_ids,
        )
    ]


async def paper_relevance_search_json(
    query,
    limit=100,
    start_year=None,
    end_year=None,
    min_citation_count=None,
    depth=1,
    citation_limit_per_level=100,
    min_citation_depth=None,
    exclude_paper_ids=None,
):
    return await run_blocking(
        _paper_relevance_search_json_sync,
        query,
        limit,
        start_year,
        end_year,
        min_citation_count,
        depth,
        citation_limit_per_level,
        min_citation_depth,
        exclude_paper_ids,
    )


async def search_transformer_language_models_2024_2026(
    limit=2,
    depth=1,
    citation_limit_per_level=100,
    min_citation_depth=None,
):
    return await paper_relevance_search(
        query="transformer language models",
        limit=limit,
        start_year=2024,
        end_year=2026,
        depth=depth,
        citation_limit_per_level=citation_limit_per_level,
        min_citation_depth=min_citation_depth,
    )


# ---------------------------------------------------------------------------
# 1-B  Paper Bulk Search  (sorted, paginated, efficient for large crawls)
# ---------------------------------------------------------------------------
def _paper_bulk_search_sync(query, start_year=None, end_year=None, min_citation_count=None):
    """
    Use case: Download large sets of papers matching a query.
    Endpoint: GET /paper/search/bulk
    Supports sorting by publicationDate or citationCount.
    Uses a 'token' for cursor-based pagination.
    """
    print("\n─── 1-B  Paper Bulk Search ───")
    if not end_year:
        end_year = time.strftime("%Y")
    params = {
        "query": query,
        "fields": f"{PAPER_WITH_LINKED_FIELDS}",
        "fieldsOfStudy": "Computer Science",
        "minCitationCount": min_citation_count,
        "sort": "citationCount:desc",
        "year": f"{start_year}-{end_year}" if start_year and end_year else None,
    }
    data = _semantic_scholar_get(f"{GRAPH_BASE}/paper/search/bulk", params=params, headers=HEADERS)
    return [
        _paper_to_result_dict(paper)
        for paper in data.get("data", [])
    ]


async def paper_bulk_search(query, start_year=None, end_year=None, min_citation_count=None):
    return await run_blocking(
        _paper_bulk_search_sync,
        query,
        start_year,
        end_year,
        min_citation_count,
    )


PAPER_METADATA_SIMPLE_FIELDS = (
    "paperId,title,year,externalIds,abstract,citationCount,referenceCount"
)


def _row_to_simple_metadata(paper: dict, fallback_arxiv_id: str) -> dict:
    return {
        "arxiv_id": safe_get(paper, "externalIds.ArXiv") or fallback_arxiv_id,
        "scholar_semantic_id": paper.get("paperId"),
        "title": paper.get("title"),
        "year": paper.get("year"),
        "abstract": paper.get("abstract"),
        "citationCount": paper.get("citationCount") or 0,
        "referenceCount": paper.get("referenceCount") or 0,
    }


def _paper_metadata_simple_post(arxiv_ids: list[str]) -> list:
    """One POST against /paper/batch for the given arxiv_ids slice.

    Caller is responsible for chunking. Lets the underlying 429 raise
    propagate so the batch-with-split helper can react.
    """
    payload = {"ids": [f"ArXiv:{arxiv_id}" for arxiv_id in arxiv_ids]}
    params = {"fields": PAPER_METADATA_SIMPLE_FIELDS}
    data = _semantic_scholar_post(
        f"{GRAPH_BASE}/paper/batch",
        payload,
        params=params,
        headers=HEADERS,
    )
    return _normalize_batch_response(data)


def _paper_metadata_simple_batch_sync(arxiv_ids: list[str]) -> list[dict]:
    """Fetch metadata for many arxiv_ids in one POST, halving on 429.

    Returns a list aligned with the input order. Each entry is either
    the simple-metadata dict or {"arxiv_id": id, "found": False[, "error"]}.

    On HTTP 429, recursively split the batch in half until success or
    until a single-id batch still 429s — at which point the failure is
    recorded per id rather than crashing the whole call.
    """
    if not arxiv_ids:
        return []

    try:
        rows = _paper_metadata_simple_post(arxiv_ids)
    except Exception as exc:
        if not _is_rate_limit_error(exc):
            raise
        if len(arxiv_ids) == 1:
            return [{
                "arxiv_id": arxiv_ids[0],
                "found": False,
                "error": f"{type(exc).__name__}: {exc}",
            }]
        mid = len(arxiv_ids) // 2
        left = _paper_metadata_simple_batch_sync(arxiv_ids[:mid])
        right = _paper_metadata_simple_batch_sync(arxiv_ids[mid:])
        return left + right

    by_arxiv_id: dict[str, dict] = {}
    for paper in rows:
        if not paper:
            continue
        resolved_id = safe_get(paper, "externalIds.ArXiv")
        if resolved_id:
            by_arxiv_id[str(resolved_id)] = paper

    results: list[dict] = []
    for index, arxiv_id in enumerate(arxiv_ids):
        paper = by_arxiv_id.get(arxiv_id)
        if paper is None and index < len(rows):
            paper = rows[index] or None
        if not paper:
            results.append({"arxiv_id": arxiv_id, "found": False})
            continue
        results.append(_row_to_simple_metadata(paper, arxiv_id))
    return results


def _paper_metadata_simple_sync(arxiv_id: str) -> dict:
    """Single-paper helper. Raises on transport/HTTP errors so the
    MCP tool wrapper can format a structured-error response."""
    rows = _paper_metadata_simple_post([arxiv_id])
    if not rows or not rows[0]:
        return {}
    return _row_to_simple_metadata(rows[0], arxiv_id)


async def paper_metadata_simple(arxiv_id: str) -> dict:
    return await run_blocking(_paper_metadata_simple_sync, arxiv_id)


async def paper_metadata_simple_batch(arxiv_ids: list[str]) -> list[dict]:
    return await run_blocking(_paper_metadata_simple_batch_sync, list(arxiv_ids))


# ---------------------------------------------------------------------------
# 1-D  Paper Batch  (fetch many papers in ONE request)
# ---------------------------------------------------------------------------
def _paper_batch_sync(paper_ids: list[str] = None):
    """
    Use case: Retrieve details for a known list of paper IDs efficiently.
    Endpoint: POST /paper/batch
    Accepts up to 500 IDs per request.
    """
    print("\n─── 1-D  Paper Batch ───")
    ids = [f"ArXiv:{pid}" for pid in paper_ids]
    payload = {"ids": ids}
    params  = {
        "fields": f"{PAPER_WITH_LINKED_FIELDS}",
    }
    data = _semantic_scholar_post(
        f"{GRAPH_BASE}/paper/batch",
        payload,
        params=params,
        headers=HEADERS,
    )
    return [
        _paper_to_result_dict(paper)
        for paper in data.get("data", [])
    ]


async def paper_batch(paper_ids: list[str] = None):
    return await run_blocking(_paper_batch_sync, paper_ids)


# ---------------------------------------------------------------------------
# 3-A  Recommendations from a single paper
# ---------------------------------------------------------------------------
def _recommendations_single_sync(paper_id, limit=100):
    """
    Use case: Discover papers similar to one seed paper.
    Endpoint: GET /recommendations/v1/papers/forpaper/{paper_id}
    """
    print(f"\n─── 3-A  Single-Paper Recommendations ───")
    params = {
        "fields": f"{PAPER_WITH_LINKED_FIELDS}",
        "limit": limit,
    }
    data = _semantic_scholar_get(
        f"{RECOMM_BASE}/papers/forpaper/ARXIV:{paper_id}",
        params=params,
        headers=HEADERS,
    )
    return [
        _paper_to_result_dict(paper)
        for paper in data.get("data", [])
    ]


async def recommendations_single(paper_id, limit=100):
    return await run_blocking(_recommendations_single_sync, paper_id, limit)


# ---------------------------------------------------------------------------
# 3-B  Recommendations from multiple papers (positive + negative examples)
# ---------------------------------------------------------------------------
def _recommendations_multi_sync(postitive_ids: list[str] = None, negative_ids: list[str] = None, limit=100):
    """
    Use case: Steer recommendations using positive examples (like) and
              negative examples (dislike) to fine-tune results.
    Endpoint: POST /recommendations/v1/papers
    """
    if not postitive_ids and not negative_ids:
        raise ValueError("At least one of postitive_ids or negative_ids must be provided")
    positive_paper_ids = _format_recommendation_seed_ids(postitive_ids)
    negative_paper_ids = _format_recommendation_seed_ids(negative_ids)
    if not positive_paper_ids and not negative_paper_ids:
        raise ValueError("No recommendation seed papers could be resolved")

    payload = {}
    if positive_paper_ids:
        payload["positivePaperIds"] = positive_paper_ids
    if negative_paper_ids:
        payload["negativePaperIds"] = negative_paper_ids
    params = {
        "fields": f"{RECOMMENDATION_FIELDS}",
        "limit": limit,
    }
    data = _semantic_scholar_post(
        f"{RECOMM_BASE}/papers",
        payload,
        params=params,
        headers=HEADERS,
    )
    result = []
    abstract_result = {}
    recommendation_papers = data.get("recommendedPapers", data.get("data", []))
    for paper in recommendation_papers:
        arxiv_id = safe_get(paper, "externalIds.Arxiv")
        result.append(_paper_to_recommendation_result_dict(paper))
        if arxiv_id:
            abstract_result[arxiv_id] = paper.get("abstract")
    return result, abstract_result


async def recommendations_multi(postitive_ids: list[str] = None, negative_ids: list[str] = None, limit=100):
    return await run_blocking(_recommendations_multi_sync, postitive_ids, negative_ids, limit)

# ---------------------------------------------------------------------------
# 5-B  Build a citation network (2-hop BFS)
# ---------------------------------------------------------------------------
def _build_citation_network_sync(seed_paper_id, depth=2, max_per_level=3):
    """
    Use case: Build a small citation graph starting from one seed paper.
    Useful for visualising how ideas propagate through literature.
    """
    print(f"\n─── 5-B  Citation Network (depth={depth}) ───")
    visited = set()
    network = {}

    def fetch_citations(pid, current_depth):
        if current_depth == 0 or pid in visited:
            return
        visited.add(pid)
        params = {"fields": "paperId,title,year", "limit": max_per_level}
        data = _semantic_scholar_get(
            f"{GRAPH_BASE}/paper/{pid}/citations",
            params=params,
            headers=HEADERS,
        )
        if not data:
            return
        citing = [e["citingPaper"] for e in data.get("data", []) if e.get("citingPaper")]
        network[pid] = citing
        print(f"  Depth {current_depth} | {pid[:12]}... → {len(citing)} citing papers")
        for p in citing:
            time.sleep(0.5)
            fetch_citations(p["paperId"], current_depth - 1)

    fetch_citations(seed_paper_id, depth)
    return network


async def build_citation_network(seed_paper_id, depth=2, max_per_level=3):
    return await run_blocking(
        _build_citation_network_sync,
        seed_paper_id,
        depth,
        max_per_level,
    )


# ===========================================================================
# MAIN — local smoke test
# ===========================================================================

if __name__ == "__main__":
    print("=" * 65)
    print("  Semantic Scholar API — All Use Cases")
    print("=" * 65)

    result = asyncio.run(paper_relevance_search(
        query="transformer language models",
        limit=10,
        start_year=2025,
        min_citation_count=10,
        depth=3,
        citation_limit_per_level=30,
        min_citation_depth=10,
        max_papers=300,
        exclude_paper_ids={"2604.28181", "2604.28178", "2604.28158", "2604.28125", "2604.28112", "2505.24119"},
    ))
    with open("semantic_scholar_debug.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(result)} papers to semantic_scholar_debug.json")
