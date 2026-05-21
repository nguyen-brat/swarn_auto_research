import json
import shutil
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_build_curator_spec_uses_run_id_and_payload(tmp_path):
    from handbook_builder.dispatch import build_curator_spec

    run_dir = tmp_path / "run-abc"
    run_dir.mkdir()
    manifest = [{"type": "methods", "id": "maskgct", "title": "MaskGCT", "path": "methods/maskgct"}]
    parts = [{"title": "Generation", "methods": ["maskgct"]}]

    spec = build_curator_spec(run_dir, topic="Real-time S2S", manifest=manifest, parts=parts)

    assert spec.stage == "19"
    assert spec.shard_id.startswith("scaffold")
    assert spec.agent == "web_design_curator"
    assert "run_id=run-abc" in spec.prompt
    assert "Real-time S2S" in spec.prompt
    assert spec.expected_outputs == ["19_handbook/.scaffold/curator_output.json"]


def _make_minimal_run(tmp_path: Path) -> Path:
    """Create a minimal run dir with required inputs for M0 pipeline."""
    run_dir = tmp_path / "run-mini"
    chapters = run_dir / "14_chapters"
    (chapters / "methods").mkdir(parents=True)
    (chapters / "book").mkdir()
    (chapters / "methods/maskgct.md").write_text("# MaskGCT\n")
    (chapters / "book/00_preface.md").write_text("# Preface\n")
    book = run_dir / "16_book"
    book.mkdir()
    (book / "sidebar.json").write_text(json.dumps({"items": [
        {"title": "Book", "children": [{"title": "Preface", "path": "14_chapters/book/00_preface.md"}]},
        {"title": "Generation", "children": [{"title": "MaskGCT", "path": "14_chapters/methods/maskgct.md"}]},
    ]}))
    (book / "chapters_manifest.json").write_text(json.dumps([
        {"type": "book", "id": "preface", "title": "Preface", "path": "book/00_preface"},
        {"type": "methods", "id": "maskgct", "title": "MaskGCT", "path": "methods/maskgct"},
    ]))
    config = run_dir / "run_config.json"
    config.write_text(json.dumps({"run_id": "run-mini", "topic": "Test Topic"}))
    return run_dir


def test_run_scaffold_only_pipeline(tmp_path):
    from handbook_builder import pipeline

    run_dir = _make_minimal_run(tmp_path)

    def fake_run_shards(run_dir, specs, **kwargs):
        scaffold_dir = run_dir / "19_handbook" / ".scaffold"
        scaffold_dir.mkdir(parents=True, exist_ok=True)
        (scaffold_dir / "curator_output.json").write_text(json.dumps({
            "astro_config": "export default {};",
            "theme_css": "/* tokyo */",
            "package_json": {"name": "h", "type": "module", "version": "0.0.1",
                              "scripts": {"build": "astro build"},
                              "dependencies": {"astro": "5.4.0"}},
            "sidebar_items": [{"label": "Book", "items": []}],
            "home_page_mdx": "---\ntitle: Home\n---\n",
        }))

    with patch("handbook_builder.dispatch.run_shards", side_effect=fake_run_shards):
        pipeline.build(run_dir, milestone="M0", run_pnpm_build=False)

    base = run_dir / "19_handbook"
    assert (base / "astro.config.mjs").exists()
    assert (base / "src/content/docs/methods/maskgct.md").exists()
    assert (base / "src/content/docs/book/00_preface.md").exists()
    assert (base / "src/components/Tldr.astro").exists()


def test_pipeline_uses_topic_file_when_run_config_missing(tmp_path):
    from handbook_builder import pipeline

    run_dir = _make_minimal_run(tmp_path)
    (run_dir / "run_config.json").unlink()
    (run_dir / "00_input").mkdir()
    (run_dir / "00_input/topic.md").write_text("Legacy Topic\n")

    captured_prompts: list[str] = []

    def fake_run_shards(run_dir, specs, **kwargs):
        captured_prompts.append(specs[0].prompt)
        scaffold_dir = run_dir / "19_handbook" / ".scaffold"
        scaffold_dir.mkdir(parents=True, exist_ok=True)
        (scaffold_dir / "curator_output.json").write_text(json.dumps({
            "astro_config": "export default {};",
            "theme_css": "",
            "package_json": {"name": "h", "type": "module", "version": "0.0.1",
                              "scripts": {"build": "astro build"},
                              "dependencies": {"astro": "5.4.0"}},
            "sidebar_items": [{"label": "Book", "items": []}],
            "home_page_mdx": "---\ntitle: Home\n---\n",
        }))

    with patch("handbook_builder.dispatch.run_shards", side_effect=fake_run_shards):
        pipeline.build(run_dir, milestone="M0", run_pnpm_build=False)

    assert "Legacy Topic" in captured_prompts[0]
    assert (run_dir / "19_handbook" / "astro.config.mjs").exists()


def test_run_pnpm_build_invokes_subprocess(tmp_path):
    from handbook_builder import build

    run_dir = tmp_path / "run-x"
    (run_dir / "19_handbook").mkdir(parents=True)

    calls: list[list[str]] = []

    def fake_run(cmd, cwd, check, capture_output, text):
        calls.append(cmd)
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()

    with patch("handbook_builder.build.shutil.which", return_value="/usr/bin/pnpm"), \
         patch("handbook_builder.build.subprocess.run", side_effect=fake_run), \
         patch("handbook_builder.build.validate_built_site", lambda run_dir, **kwargs: None):
        build.run_pnpm_build(run_dir)

    assert calls == [["pnpm", "install", "--frozen-lockfile=false"], ["pnpm", "build"]]


def test_run_build_falls_back_to_npm_when_pnpm_missing(tmp_path):
    from handbook_builder import build

    run_dir = tmp_path / "run-x"
    (run_dir / "19_handbook").mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_run(cmd, cwd, check, capture_output, text):
        calls.append(cmd)
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()

    with patch("handbook_builder.build.shutil.which", return_value=None), \
         patch("handbook_builder.build.subprocess.run", side_effect=fake_run), \
         patch("handbook_builder.build.validate_built_site", lambda run_dir, **kwargs: None):
        build.run_pnpm_build(run_dir)

    assert calls == [["npm", "install"], ["npm", "run", "build"]]


def test_pipeline_m1_runs_glossary_and_diagrams(tmp_path):
    from handbook_builder import pipeline

    run_dir = _make_minimal_run(tmp_path)
    # M1 needs taxonomy + a pack
    (run_dir / "12_taxonomy").mkdir(exist_ok=True)
    (run_dir / "12_taxonomy/outline.json").write_text(json.dumps({
        "families": [], "methods": [{"id": "maskgct"}], "book_sections": []
    }))
    (run_dir / "13_chapter_packs/methods").mkdir(parents=True)
    (run_dir / "13_chapter_packs/methods/maskgct.json").write_text("{}")

    seen_shard_ids: list[str] = []

    def fake_run_shards(run_dir, specs, **kwargs):
        for s in specs:
            seen_shard_ids.append(s.shard_id)
            if s.shard_id == "scaffold-001":
                p = run_dir / "19_handbook/.scaffold/curator_output.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({
                    "astro_config": "", "theme_css": "", "package_json": {
                        "name": "h", "type": "module", "version": "0.0.1",
                        "scripts": {"build": "astro build"},
                        "dependencies": {"astro": "5.4.0"}
                    },
                    "sidebar_items": [], "home_page_mdx": "",
                }))
            elif s.shard_id == "glossary-001":
                p = run_dir / "19_handbook/public/glossary.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps([
                    {"term": "RVQ", "definition": "Residual VQ.", "appears_in": ["maskgct"], "kb_known": False}
                ]))
            elif s.shard_id.startswith("diagram-"):
                target = s.shard_id.replace("diagram-method-", "").replace("diagram-family-", "")
                plural = "methods" if "method" in s.shard_id else "families"
                p = run_dir / f"19_handbook/src/assets/diagrams/{plural}/{target}.mmd"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("graph LR; A --> B")

    with patch("handbook_builder.dispatch.run_shards", side_effect=fake_run_shards):
        pipeline.build(run_dir, milestone="M1", run_pnpm_build=False)

    assert "scaffold-001" in seen_shard_ids
    assert "glossary-001" in seen_shard_ids
    assert any(s.startswith("diagram-method-") for s in seen_shard_ids)
    assert (run_dir / "19_handbook/public/glossary.json").exists()
    assert (run_dir / "19_handbook/src/assets/diagrams/methods/maskgct.mmd").exists()


def test_stage_19_registered_in_runner():
    config = (REPO_ROOT / "scripts/auto_research_runner/config.py").read_text()
    stages = (REPO_ROOT / "scripts/auto_research_runner/stages.py").read_text()
    cli = (REPO_ROOT / "scripts/auto_research_runner/cli.py").read_text()
    shim = (REPO_ROOT / "scripts/run_auto_research.py").read_text()

    assert '"19":' in config
    assert '"19": 12' in config
    assert "def run_stage_19" in stages
    assert '("19", run_stage_19)' in cli
    assert "run_stage_19" in shim


def test_handbook_builder_does_not_import_old_runner():
    matches = []
    for path in (REPO_ROOT / "handbook_builder").glob("*.py"):
        if "scripts.run_auto_research" in path.read_text():
            matches.append(path.name)
    assert matches == []


def test_parts_from_sidebar_handles_nested_family_children():
    from handbook_builder.pipeline import _parts_from_sidebar

    sidebar = {
        "items": [
            {
                "title": "Book",
                "children": [{"title": "Preface", "path": "14_chapters/book/00_preface.md"}],
            },
            {
                "title": "Repair Agents",
                "children": [
                    {
                        "title": "APR family",
                        "path": "14_chapters/families/apr.md",
                        "children": [
                            {"title": "RepairAgent", "path": "14_chapters/methods/repairagent.md"},
                            {"title": "SelfHeal", "path": "14_chapters/methods/selfheal.md"},
                        ],
                    }
                ],
            },
        ]
    }

    assert _parts_from_sidebar(sidebar) == [
        {"title": "Repair Agents", "methods": ["repairagent", "selfheal"]}
    ]


def test_build_handbook_script_rejects_unimplemented_m4():
    text = (REPO_ROOT / "scripts/build_handbook.py").read_text()
    assert '"M4"' not in text


def test_legacy_stage_19_monolith_not_present():
    text = (REPO_ROOT / "scripts/run_auto_research.py").read_text()
    assert "def run_stage_19" not in text
    assert '("19", run_stage_19)' not in text


def test_build_handbook_script_exists_and_imports():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "build_handbook_script", REPO_ROOT / "scripts/build_handbook.py"
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    assert hasattr(mod, "main")


def test_pipeline_m2_runs_tldr_writer_and_verifier(tmp_path):
    from handbook_builder import pipeline

    run_dir = _make_minimal_run(tmp_path)
    (run_dir / "12_taxonomy").mkdir(exist_ok=True)
    (run_dir / "12_taxonomy/outline.json").write_text(json.dumps({
        "families": [], "methods": [{"id": "maskgct"}], "book_sections": []
    }))
    (run_dir / "13_chapter_packs/methods").mkdir(parents=True)
    (run_dir / "13_chapter_packs/methods/maskgct.json").write_text("{}")

    def fake_run_shards(run_dir, specs, **kwargs):
        for s in specs:
            if s.shard_id == "scaffold-001":
                p = run_dir / "19_handbook/.scaffold/curator_output.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({
                    "astro_config": "", "theme_css": "",
                    "package_json": {"name": "h", "type": "module", "version": "0.0.1",
                                      "scripts": {"build": "astro build"},
                                      "dependencies": {"astro": "5.4.0"}},
                    "sidebar_items": [], "home_page_mdx": "",
                }))
            elif s.shard_id == "glossary-001":
                p = run_dir / "19_handbook/public/glossary.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("[]")
            elif s.shard_id.startswith("diagram-"):
                target = s.shard_id.split("-", 2)[-1]
                plural = "methods" if "method" in s.shard_id else "families"
                p = run_dir / f"19_handbook/src/assets/diagrams/{plural}/{target}.mmd"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("graph LR; A --> B")
            elif s.shard_id.startswith("tldr-"):
                mid = s.shard_id.removeprefix("tldr-")
                p = run_dir / f"19_handbook/.augment/methods/{mid}.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({
                    "tldr": "T.", "key_idea": "K.",
                    "when_to_use": ["use"], "tags": ["TTS"],
                }))
            elif s.shard_id.startswith("verify-tldr-"):
                mid = s.shard_id.removeprefix("verify-tldr-")
                p = run_dir / f"19_handbook/.augment/tldr/{mid}.verification.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({"passed": True, "claims": [], "rejection_reason": None}))

    with patch("handbook_builder.dispatch.run_shards", side_effect=fake_run_shards):
        pipeline.build(run_dir, milestone="M2", run_pnpm_build=False)

    mdx = run_dir / "19_handbook/src/content/docs/methods/maskgct.mdx"
    assert mdx.exists()
    body = mdx.read_text()
    assert "<Tldr>T.</Tldr>" in body
    assert "<KeyIdea>K.</KeyIdea>" in body
    assert ":::tip[When to use this]" in body


def test_pipeline_m3_runs_book_rewrite_and_verifier(tmp_path):
    from handbook_builder import pipeline

    run_dir = _make_minimal_run(tmp_path)
    (run_dir / "12_taxonomy").mkdir(exist_ok=True)
    (run_dir / "12_taxonomy/outline.json").write_text(json.dumps({
        "families": [], "methods": [], "book_sections": [{"id": "preface"}]
    }))

    def fake(run_dir, specs, **kwargs):
        for s in specs:
            if s.shard_id == "scaffold-001":
                p = run_dir / "19_handbook/.scaffold/curator_output.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({
                    "astro_config": "", "theme_css": "",
                    "package_json": {"name": "h", "type": "module", "version": "0.0.1",
                                      "scripts": {"build": "astro build"},
                                      "dependencies": {"astro": "5.4.0"}},
                    "sidebar_items": [], "home_page_mdx": "",
                }))
            elif s.shard_id == "glossary-001":
                p = run_dir / "19_handbook/public/glossary.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("[]")
            elif s.shard_id.startswith("bookrewrite-"):
                cid = s.shard_id.removeprefix("bookrewrite-")
                p = run_dir / f"19_handbook/.augment/book/{cid}.mdx"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("---\ntitle: P\n---\n# Preface\nNew text.\n")
            elif s.shard_id.startswith("verify-book_rewrite-"):
                cid = s.shard_id.removeprefix("verify-book_rewrite-")
                p = run_dir / f"19_handbook/.augment/book_rewrite/{cid}.verification.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({"passed": True, "claims": [], "rejection_reason": None}))

    with patch("handbook_builder.dispatch.run_shards", side_effect=fake):
        pipeline.build(run_dir, milestone="M3", run_pnpm_build=False)

    mdx = run_dir / "19_handbook/src/content/docs/book/00_preface.mdx"
    assert mdx.exists()
    assert "New text." in mdx.read_text()
