from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_ROOT = REPO_ROOT / "research_runs"
AUTO_RESEARCH_BULK_SEARCH_CONFIG = REPO_ROOT / "swarn_research_mcp" / "bulk_search_config.json"
ARXIV2MD_MARKDOWN_URL = "https://arxiv2md.org/api/markdown"
STAGE_8_MARKDOWN_FETCH_TIMEOUT_SECONDS = 45
DEFAULT_SHARD_TIMEOUT_SECONDS = 3 * 3600
BOOTSTRAP_TIMEOUT_SECONDS = 6 * 3600
DEFAULT_SDK_NOTIFICATION_TIMEOUT_SECONDS = 15 * 60
DEFAULT_STAGE_SDK_NOTIFICATION_TIMEOUT_SECONDS = {
    "11": 5 * 60,
    "19": 5 * 60,
}
DEFAULT_EXECUTOR = "sdk-cli-fallback"
DEFAULT_MAX_EFFECTIVE_WORKERS = 20
DEFAULT_STAGE_MAX_EFFECTIVE_WORKERS = {
    "2": 20,
    "3": 20,
    "6": 10,
    "8": 20,
    "9": 20,
    "10": 20,
    "11": 20,
    "13": 20,
    "14": 20,
    "15": 20,
    "16": 20,
    "17": 20,
    "18": 20,
    "19": 12,
}
DEFAULT_STAGE_6_CODEX_RELEVANCE_SESSION_LIMIT = 1
MIN_BOOTSTRAP_PAPER_POOL = 40
STAGE_1_MAX_NORMAL_QUERIES = 5
STAGE_1_MAX_SURVEY_QUERIES = 3
STAGE_1_MIN_ASPECTS = 4
STAGE_1_MAX_ASPECTS = 5
DIRECT_SHARD_RULES = [
    "Execute directly in this codex exec session.",
    "Do not spawn subagents, do not run nested codex commands, and do not wait for other agents.",
    "Do not run scripts/run_auto_research.py, python scripts/run_auto_research.py, or python -m scripts.run_auto_research.",
    "Do not import or call bootstrap_new_run.",
    "Do not import or call sdk.codex.",
    "Do not ask for human input.",
]

PRIMARY_ARTIFACTS = {
    "0": ("run_config.json",),
    "1": (
        "00_input/search_plan.json",
        "01_seed_pool/seed_pool_raw.json",
        "02_paper_pool/paper_pool.json",
        "02_paper_pool/paper_pool.csv",
        "02_paper_pool/candidate_pool_report.json",
    ),
    "3": ("05_weak_graph/weak_global_graph.json",),
    "4": ("06_expansion/known_concepts_snapshot.json",),
    "5": (
        "06_expansion/gap_candidates_digest.json",
        "06_expansion/extracted_concepts.json",
        "06_expansion/knowledge_gap_report.json",
        "06_expansion/expansion_need_queue.json",
        "06_expansion/stage5_metadata.json",
    ),
    "6": ("06_expansion/expansion_round_01.json",),
    "7": (
        "07_scoring/paper_scores.csv",
        "07_scoring/promotion_candidates.csv",
        "07_scoring/promoted_papers.json",
    ),
    "11": ("11_verified_graph/global_graph.json", "11_verified_graph/graph_report.md"),
    "12": ("12_taxonomy/outline.json",),
    "15": ("15_verification/verification_summary.csv",),
    "16": ("16_book/chapters_manifest.json",),
    "17": ("17_learning_suggestions/knowledge_to_add.md",),
    "18": (
        "16_book/SUMMARY.md",
        "16_book/sidebar.json",
        "14_chapters/book/appendices/references.md",
    ),
    "19": ("19_handbook/.validated/build-ok.json",),
}

NON_BLOCKING_FORM_ISSUE_CHECKS = {
    "method_word_count_high",
    "family_word_count_high",
}

METHOD_PACK_SECTION_TITLES = [
    "Summary",
    "Motivation",
    "Intuition",
    "Theory",
    "Algorithm",
    "Example",
    "Interpretation",
    "Strengths",
    "Limitations",
    "Software",
    "Related Methods",
]
METHOD_PACK_REQUIRED_SOURCE_SECTIONS = {"theory", "algorithm", "example", "limitations"}

STAGE_5_SCHEMA_VERSION = "stage5_digest_classifier_v1"
