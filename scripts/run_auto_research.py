"""Compatibility shim for the auto-research runner.

The runner now lives under ``scripts.auto_research_runner``; this module
keeps ``python scripts/run_auto_research.py`` working and re-exports the
public names that existing callers (scripts, notebooks, tests) import.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.auto_research_runner.artifacts import (  # noqa: E402
    merge_verified_graph_fragments,
    run_stage_11_merge,
)
from scripts.auto_research_runner.chapters import (  # noqa: E402
    build_chapter_targets,
)
from scripts.auto_research_runner.cli import main  # noqa: E402
from scripts.auto_research_runner.packs import (  # noqa: E402
    build_deterministic_stage_13_packs,
)
from scripts.auto_research_runner.shards import (  # noqa: E402
    expected_outputs_exist,
    run_deterministic_command,
    run_shards,
)
from scripts.auto_research_runner.shared_types import (  # noqa: E402
    ShardAttemptResult,
    ShardSpec,
    Stage8MarkdownUnavailable,
)
from scripts.auto_research_runner.stages import (  # noqa: E402
    bootstrap_new_run,
    run_stage_1,
    run_stage_2,
    run_stage_3,
    run_stage_4,
    run_stage_5,
    run_stage_6,
    run_stage_7,
    run_stage_8,
    run_stage_9,
    run_stage_10,
    run_stage_11,
    run_stage_12,
    run_stage_12_5,
    run_stage_13,
    run_stage_14,
    run_stage_15,
    run_stage_16,
    run_stage_17,
    run_stage_18,
    start_new_run,
)
from scripts.auto_research_runner.state import (  # noqa: E402
    append_run_log,
    ensure_run_control,
    load_run_state,
    save_run_state,
)
from scripts.auto_research_runner.validation import (  # noqa: E402
    primary_artifact_exists,
    validate_bootstrap_stage_0_10_contract,
    validate_stage_1_keep_all_contract,
)


if __name__ == "__main__":
    raise SystemExit(main())
