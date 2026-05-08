from __future__ import annotations

import datetime
import re


MAX_PAPER_AGE_YEARS = 6

def _arxiv_year_from_id(arxiv_id: str) -> int | None:
    arxiv_id = arxiv_id.strip()

    # Remove version suffix, e.g. 2405.12345v2 -> 2405.12345
    if "v" in arxiv_id:
        arxiv_id = arxiv_id.split("v")[0]

    # New format: YYMM.NNNNN
    if "." in arxiv_id and len(arxiv_id.split(".")[0]) == 4:
        yy = int(arxiv_id[:2])
        # arXiv new IDs started in 2007, so YY normally means 20YY
        return 2000 + yy

    return None

def _normalize_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for term in terms:
        value = term.strip().lower()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _compile_term(term: str) -> re.Pattern[str]:
    escaped = re.escape(term).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(_compile_term(term).search(text) for term in terms)


def _is_recent_enough(paper_id: str) -> bool:
    paper_year = _arxiv_year_from_id(paper_id)
    if paper_year is None:
        return True
    current_year = datetime.datetime.now().year
    return current_year - paper_year <= MAX_PAPER_AGE_YEARS


def filter_papers(
    papers: dict[str, str],
    keywords: list[str],
    negative_keywords: list[str] | None = None,
) -> dict[str, str]:
    keep_terms = _normalize_terms(keywords)
    drop_terms = _normalize_terms(negative_keywords or [])
    kept: dict[str, str] = {}

    for paper_id, abstract in papers.items():
        if not _is_recent_enough(paper_id):
            continue
        text = abstract.lower()
        if drop_terms and _contains_any(text, drop_terms):
            continue
        if keep_terms and not _contains_any(text, keep_terms):
            continue
        kept[paper_id] = abstract

    return kept


def select_papers(
    papers: dict[str, str],
    keywords: list[str],
    negative_keywords: list[str] | None = None,
) -> dict[str, object]:
    kept = filter_papers(papers, keywords, negative_keywords)

    return {
        "keywords": _normalize_terms(keywords),
        "negative_keywords": _normalize_terms(negative_keywords or []),
        "total_input": len(papers),
        "total_kept": len(kept),
        "papers": kept,
    }


def key_words_select(papers: dict[str, str], pos_key_words: list[str]) -> list[str]:
    return list(filter_papers(papers, pos_key_words).keys())
