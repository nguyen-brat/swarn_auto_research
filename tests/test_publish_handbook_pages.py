import subprocess
import sys


def _write_dist(run_dir, *, with_nojekyll=True, base_path="/project-site"):
    dist = run_dir / "19_handbook/dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text(
        f'<html><link rel="stylesheet" href="{base_path}/_astro/main.css"></html>'
    )
    if with_nojekyll:
        (dist / ".nojekyll").write_text("")
    return dist


def test_publish_handbook_pages_dry_run_checks_dist(tmp_path):
    run_dir = tmp_path / "run"
    _write_dist(run_dir, with_nojekyll=True)
    repo_dir = tmp_path / "pages"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True, text=True)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/publish_handbook_pages.py",
            "--run-dir",
            str(run_dir),
            "--dest",
            str(repo_dir),
            "--base-path",
            "/project-site",
            "--dry-run",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "dry run" in result.stdout.lower()


def test_publish_handbook_pages_rejects_missing_nojekyll(tmp_path):
    run_dir = tmp_path / "run"
    _write_dist(run_dir, with_nojekyll=False)
    repo_dir = tmp_path / "pages"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True, text=True)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/publish_handbook_pages.py",
            "--run-dir",
            str(run_dir),
            "--dest",
            str(repo_dir),
            "--base-path",
            "/project-site",
            "--dry-run",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert ".nojekyll" in result.stderr
