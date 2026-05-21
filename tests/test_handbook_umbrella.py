import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_umbrella_scaffold_exists():
    base = REPO_ROOT / "handbook"
    assert (base / "astro.config.mjs").exists()
    pkg = json.loads((base / "package.json").read_text())
    assert pkg["name"] == "swarn-handbook-umbrella"
    assert (base / "src/content/docs/index.mdx").exists()
    assert (base / "src/styles/custom.css").exists()


def test_regen_umbrella_index_writes_pages(tmp_path):
    import importlib.util

    repo_clone = tmp_path / "repo"
    (repo_clone / "research_runs/run-1").mkdir(parents=True)
    (repo_clone / "research_runs/run-1/run_config.json").write_text(json.dumps({
        "run_id": "run-1", "topic": "Speech LMs", "created_at": "2026-05-13"
    }))
    (repo_clone / "research_runs/run-1/19_handbook/dist").mkdir(parents=True)
    (repo_clone / "research_runs/run-2/run_config.json").parent.mkdir(parents=True)
    (repo_clone / "research_runs/run-2/run_config.json").write_text(json.dumps({
        "run_id": "run-2", "topic": "Long Context", "created_at": "2026-05-09"
    }))
    (repo_clone / "handbook/src/content/docs/runs").mkdir(parents=True)

    spec = importlib.util.spec_from_file_location(
        "regen_um", REPO_ROOT / "scripts/regen_umbrella_index.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    mod.regenerate(repo_clone)

    runs_dir = repo_clone / "handbook/src/content/docs/runs"
    assert (runs_dir / "run-1.mdx").exists()
    assert (runs_dir / "run-2.mdx").exists()
    body = (runs_dir / "run-1.mdx").read_text()
    assert "Speech LMs" in body
    assert "Build status: built" in body or "✓ built" in body
    body2 = (runs_dir / "run-2.mdx").read_text()
    assert "Build status: pending" in body2 or "pending" in body2
