from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_web_design_curator_skill_exists():
    skill = REPO_ROOT / ".agents/skills/web-design-curator/SKILL.md"
    assert skill.exists(), "SKILL.md missing"
    text = skill.read_text()
    assert "research handbook" in text
    assert "starlight(" in text
    assert "expressiveCode" in text
    assert "Return JSON" in text or "Return strict JSON" in text


def test_web_design_curator_toml_exists():
    toml = REPO_ROOT / ".codex/agents/web_design_curator.toml"
    assert toml.exists()
    text = toml.read_text()
    assert 'name = "web_design_curator"' in text
    assert "web-design-curator/SKILL.md" in text


def test_static_components_exist():
    base = REPO_ROOT / "handbook_builder/templates/components"
    for name in ("Tldr.astro", "KeyIdea.astro", "Diagram.astro", "Term.astro"):
        path = base / name
        assert path.exists(), f"{name} missing"
        text = path.read_text()
        assert "<style>" in text or "scoped" in text or "<slot" in text


import json
import shutil
import tempfile


def test_apply_scaffold_writes_files(tmp_path):
    from handbook_builder.scaffold import apply_scaffold

    run_dir = tmp_path / "run"
    (run_dir / "19_handbook" / ".scaffold").mkdir(parents=True)
    payload = {
        "astro_config": "// intentionally ignored\nexport default {};\n",
        "theme_css": "/* intentionally ignored */",
        "package_json": {
            "name": "handbook-test",
            "type": "module",
            "version": "0.0.1",
            "scripts": {"build": "astro build"},
            "dependencies": {"astro": "5.4.0"},
        },
        "sidebar_items": [{"label": "Book", "items": []}],
        "home_page_mdx": "---\ntitle: Home\n---\n# Home\n",
    }
    (run_dir / "19_handbook" / ".scaffold" / "curator_output.json").write_text(json.dumps(payload))
    (run_dir / "run_config.json").write_text(json.dumps({"topic": "Handbook Topic"}))
    book = run_dir / "16_book"
    book.mkdir()
    (book / "sidebar.json").write_text(json.dumps({"items": []}))
    (book / "chapters_manifest.json").write_text(json.dumps([
        {"type": "book", "id": "preface"},
        {"type": "families", "id": "generation"},
        {"type": "methods", "id": "maskgct"},
    ]))

    apply_scaffold(run_dir)

    base = run_dir / "19_handbook"
    assert "remarkMath" in (base / "astro.config.mjs").read_text()
    assert "radial-gradient" not in (base / "src/styles/custom.css").read_text()
    package = json.loads((base / "package.json").read_text())
    assert package["name"] == "handbook-run"
    assert "remark-math" in package["dependencies"]
    css = (base / "src/styles/custom.css").read_text()
    assert "--sl-content-width: min(72rem, calc(100vw - 24rem));" in css
    assert "min-width: 14rem;" in css
    assert "word-break: normal;" in css
    home = (base / "src/content/docs/index.mdx").read_text()
    assert home.startswith("---")
    assert "head: []" in home
    assert 'title: "Research Handbook: Handbook Topic"' in home
    assert "1 method pages" in home
    assert "1 research families" in home
    assert "docsSchema" in (base / "src/content.config.ts").read_text()
    assert (base / "src/components/Tldr.astro").exists()
    assert (base / "src/components/Diagram.astro").exists()
    sidebar = json.loads((base / ".scaffold/sidebar.json").read_text())
    assert sidebar[0]["label"] == "Book"


def test_professional_site_title_cleans_raw_user_topic():
    from handbook_builder.scaffold import professional_site_title

    assert professional_site_title(
        "AI-agent system in coding that can accelerate my working process",
        run_id="ai-agent-system-in-coding-that-can-accelerate-my-working-process-20260515-152516",
    ) == "Research Handbook: AI Coding Agents for Accelerated Workflows"
    assert professional_site_title("", run_id="real-time-speech-to-speech-language-models") == (
        "Research Handbook: Real Time Speech to Speech Language Models"
    )


def test_apply_scaffold_counts_real_manifest_schema(tmp_path):
    from handbook_builder.scaffold import apply_scaffold

    run_dir = tmp_path / "run"
    (run_dir / "19_handbook" / ".scaffold").mkdir(parents=True)
    (run_dir / "19_handbook" / ".scaffold" / "curator_output.json").write_text(
        json.dumps(
            {
                "astro_config": "",
                "theme_css": "",
                "package_json": {"dependencies": {}},
                "sidebar_items": [],
                "home_page_mdx": "",
            }
        )
    )
    (run_dir / "run_config.json").write_text(json.dumps({"topic": "Real Schema"}))
    book = run_dir / "16_book"
    book.mkdir()
    (book / "sidebar.json").write_text(json.dumps({"items": []}))
    (book / "chapters_manifest.json").write_text(
        json.dumps(
            [
                {"chapter_type": "book", "chapter_id": "preface"},
                {"chapter_type": "family", "chapter_id": "generation"},
                {"chapter_type": "method", "chapter_id": "maskgct"},
            ]
        )
    )

    apply_scaffold(run_dir)

    home = (run_dir / "19_handbook/src/content/docs/index.mdx").read_text()
    assert "1 book chapters" in home
    assert "1 research families" in home
    assert "1 method pages" in home


def test_apply_scaffold_removes_redundant_mdx_integration(tmp_path):
    from handbook_builder.scaffold import apply_scaffold

    run_dir = tmp_path / "run"
    (run_dir / "19_handbook" / ".scaffold").mkdir(parents=True)
    payload = {
        "astro_config": (
            "import { defineConfig } from 'astro/config';\n"
            "import mdx from '@astrojs/mdx';\n"
            "import starlight from '@astrojs/starlight';\n"
            "export default defineConfig({ integrations: [mdx(), starlight({ title: 'T' })] });\n"
        ),
        "theme_css": "",
        "package_json": {
            "name": "handbook-test",
            "type": "module",
            "version": "0.0.1",
            "scripts": {"build": "astro build"},
            "dependencies": {"astro": "5.4.0"},
        },
        "sidebar_items": [],
        "home_page_mdx": "---\ntitle: Home\n---\n",
    }
    (run_dir / "19_handbook" / ".scaffold" / "curator_output.json").write_text(json.dumps(payload))
    (run_dir / "run_config.json").write_text(json.dumps({"topic": "T"}))
    book = run_dir / "16_book"
    book.mkdir()
    (book / "sidebar.json").write_text(json.dumps({"items": []}))
    (book / "chapters_manifest.json").write_text("[]")

    apply_scaffold(run_dir)

    config = (run_dir / "19_handbook" / "astro.config.mjs").read_text()
    assert "import mdx from '@astrojs/mdx';" not in config
    assert "mdx()" not in config
    assert "head: []" in config
    assert "remarkMath" in config


def test_apply_scaffold_supports_github_pages_project_base(tmp_path, monkeypatch):
    from handbook_builder.scaffold import apply_scaffold

    run_dir = tmp_path / "run"
    (run_dir / "19_handbook" / ".scaffold").mkdir(parents=True)
    (run_dir / "19_handbook" / ".scaffold" / "curator_output.json").write_text(
        json.dumps(
            {
                "astro_config": "",
                "theme_css": "",
                "package_json": {"dependencies": {}},
                "sidebar_items": [],
                "home_page_mdx": "",
            }
        )
    )
    (run_dir / "run_config.json").write_text(json.dumps({"topic": "Agent Research"}))
    book = run_dir / "16_book"
    book.mkdir()
    (book / "sidebar.json").write_text(json.dumps({"items": []}))
    (book / "chapters_manifest.json").write_text("[]")
    monkeypatch.delenv("HANDBOOK_PUBLISH_ENABLED", raising=False)
    monkeypatch.setenv("HANDBOOK_SITE_URL", "https://nguyen-brat.github.io")
    monkeypatch.setenv("HANDBOOK_BASE_PATH", "/automous_agent_research")

    apply_scaffold(run_dir)

    config = (run_dir / "19_handbook/astro.config.mjs").read_text()
    home = (run_dir / "19_handbook/src/content/docs/index.mdx").read_text()
    assert "site: \"https://nguyen-brat.github.io\"" in config
    assert "base: \"/automous_agent_research\"" in config
    assert 'href="/automous_agent_research/methods/"' in home
    assert (run_dir / "19_handbook/public/.nojekyll").exists()
