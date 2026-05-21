from __future__ import annotations

import json


def _write_minimal_outline(run_dir):
    (run_dir / "12_taxonomy").mkdir(parents=True, exist_ok=True)
    (run_dir / "12_taxonomy/outline.json").write_text(
        json.dumps(
            {
                "topic": "Fixture topic",
                "book_sections": [{"id": "preface", "title": "Preface"}],
                "families": [{"id": "fam_a", "title": "Family A", "method_ids": ["m1"]}],
                "methods": [{"id": "m1", "title": "M1", "arxiv_id": "1.1", "family_id": "fam_a"}],
            }
        )
    )


def _write_minimal_stage_13_sources(run_dir):
    (run_dir / "00_input").mkdir(parents=True, exist_ok=True)
    (run_dir / "00_input/topic.md").write_text("# Fixture topic\n")
    (run_dir / "06_expansion").mkdir(parents=True, exist_ok=True)
    (run_dir / "06_expansion/known_concepts_snapshot.json").write_text(
        json.dumps({"known_concepts": []})
    )
    (run_dir / "06_expansion/knowledge_gap_report.json").write_text(
        json.dumps({"knowledge_gaps": []})
    )
    (run_dir / "10_verified_evidence").mkdir(parents=True, exist_ok=True)
    (run_dir / "10_verified_evidence/1.1.json").write_text(
        json.dumps(
            {
                "claims": [
                    {"text": "Motivation.", "source_node_id": "s.01", "claim_type": "motivation"},
                    {"text": "Method.", "source_node_id": "s.02", "claim_type": "method"},
                    {"text": "Result.", "source_node_id": "s.03", "claim_type": "result"},
                    {"text": "Limitation.", "source_node_id": "s.04", "claim_type": "limitation"},
                ],
                "equations": [{"latex": "x=y", "source_node_id": "s.02"}],
                "algorithms": [{"pseudocode": "return x", "source_node_id": "s.02"}],
                "hyperparameters": [{"name": "steps", "source_node_id": "s.03"}],
                "limitations": [{"text": "Limitation.", "source_node_id": "s.04"}],
            }
        )
    )
    (run_dir / "09_pageindex/nodes").mkdir(parents=True, exist_ok=True)
    (run_dir / "09_pageindex/nodes/1.1.nodes.json").write_text(
        json.dumps(
            {
                "s.01": {"title": "Intro", "start_line": 1, "end_line": 2},
                "s.02": {"title": "Method", "start_line": 3, "end_line": 4},
                "s.03": {"title": "Example", "start_line": 5, "end_line": 6},
                "s.04": {"title": "Limitations", "start_line": 7, "end_line": 8},
            }
        )
    )
    (run_dir / "08_full_markdown").mkdir(parents=True, exist_ok=True)
    (run_dir / "08_full_markdown/1.1.md").write_text(
        "\n".join(
            [
                "## Intro",
                "Motivation text.",
                "## Method",
                "Method text.",
                "## Example",
                "Example text.",
                "## Limitations",
                "Limitation text.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


class _FakeImageResponse:
    def __init__(self, body: bytes = b"png-bytes", *, content_type: str = "image/png"):
        self.headers = {
            "content-type": content_type,
            "content-length": str(len(body)),
        }
        self._body = body
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int = 8192):
        yield self._body


def test_parse_figure_candidates_prefers_method_workflow_images():
    from scripts.auto_research_runner.figures import parse_figure_candidates

    markdown = """
## Method

Figure: Figure 1: The overall workflow and architecture of the training algorithm.
Refer to caption: https://arxiv.org/html/1234.56789/figures/framework.png

Figure: Figure 2: Accuracy curves on the benchmark.
Refer to caption: https://arxiv.org/html/1234.56789/figures/plot.png
"""

    candidates = parse_figure_candidates(
        markdown,
        arxiv_id="1234.56789",
        markdown_relpath="08_full_markdown/1234.56789.md",
    )

    assert candidates[0]["source_url"].endswith("framework.png")
    assert candidates[0]["score"] > candidates[1]["score"]
    assert candidates[0]["evidence_refs"] == ["08_full_markdown/1234.56789.md:4"]


def test_select_visual_assets_caches_first_live_ranked_image(tmp_path, monkeypatch):
    from scripts.auto_research_runner.figures import select_visual_assets_for_arxiv_ids

    run_dir = tmp_path / "run"
    markdown_dir = run_dir / "08_full_markdown"
    markdown_dir.mkdir(parents=True)
    (markdown_dir / "1234.56789.md").write_text(
        """
Figure: Figure 1: Model architecture and training pipeline.
Refer to caption: https://arxiv.org/html/1234.56789/dead.png

Figure: Figure 2: Algorithm workflow.
Refer to caption: https://arxiv.org/html/1234.56789/live.png
""",
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if url.endswith("dead.png"):
            raise TimeoutError("dead")
        return _FakeImageResponse()

    monkeypatch.setattr("scripts.auto_research_runner.figures.requests.get", fake_get)

    assets = select_visual_assets_for_arxiv_ids(run_dir, ["1234.56789"], limit=1)

    assert calls == [
        "https://arxiv.org/html/1234.56789/dead.png",
        "https://arxiv.org/html/1234.56789/live.png",
    ]
    assert len(assets) == 1
    asset = assets[0]
    assert asset["source_url"].endswith("live.png")
    assert asset["cache_path"].startswith("13_chapter_packs/assets/paper_figures/")
    assert not asset["cache_path"].startswith(str(tmp_path))
    assert asset["public_path"].startswith("paper_figures/")
    assert asset["markdown_image"].startswith("![")
    assert (run_dir / asset["cache_path"]).read_bytes() == b"png-bytes"


def test_deterministic_stage_13_packs_include_visual_assets(tmp_path, monkeypatch):
    from scripts.auto_research_runner.packs import build_deterministic_stage_13_packs

    run_dir = tmp_path / "run"
    _write_minimal_outline(run_dir)
    _write_minimal_stage_13_sources(run_dir)
    markdown_path = run_dir / "08_full_markdown" / "1.1.md"
    markdown_path.write_text(
        markdown_path.read_text()
        + "\nFigure: Figure 1: Method architecture and algorithm workflow.\n"
        + "Refer to caption: https://arxiv.org/html/1.1/framework.png\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "scripts.auto_research_runner.figures.requests.get",
        lambda *args, **kwargs: _FakeImageResponse(),
    )

    build_deterministic_stage_13_packs(run_dir)

    method_pack = json.loads((run_dir / "13_chapter_packs/methods/m1_pack.json").read_text())
    family_pack = json.loads((run_dir / "13_chapter_packs/families/fam_a_pack.json").read_text())
    assert method_pack["visual_assets"][0]["public_path"].startswith("paper_figures/")
    assert family_pack["visual_assets"][0]["public_path"].startswith("paper_figures/")


def test_enrich_stage_13_visual_assets_retries_empty_existing_assets(tmp_path, monkeypatch):
    from scripts.auto_research_runner.packs import enrich_stage_13_visual_assets

    run_dir = tmp_path / "run"
    _write_minimal_stage_13_sources(run_dir)
    markdown_path = run_dir / "08_full_markdown" / "1.1.md"
    markdown_path.write_text(
        markdown_path.read_text()
        + "\nFigure: Figure 1: Method architecture and algorithm workflow.\n"
        + "Refer to caption: https://arxiv.org/html/1.1/framework.png\n",
        encoding="utf-8",
    )
    pack_path = run_dir / "13_chapter_packs" / "methods" / "m1_pack.json"
    pack_path.parent.mkdir(parents=True)
    pack_path.write_text(
        json.dumps(
            {
                "pack_type": "method",
                "method_id": "m1",
                "arxiv_id": "1.1",
                "visual_assets": [],
            }
        )
    )

    monkeypatch.setattr(
        "scripts.auto_research_runner.figures.requests.get",
        lambda *args, **kwargs: _FakeImageResponse(),
    )

    enrich_stage_13_visual_assets(run_dir)

    method_pack = json.loads(pack_path.read_text())
    assert method_pack["visual_assets"][0]["public_path"].startswith("paper_figures/")
