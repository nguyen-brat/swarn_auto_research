import json


def _write_site(run_dir):
    handbook = run_dir / "19_handbook"
    docs = handbook / "src/content/docs"
    (docs / "methods").mkdir(parents=True)
    (docs / "families").mkdir()
    (docs / "methods/index.md").write_text(
        "---\ntitle: Methods\nhead: []\n---\n<a href=\"/methods/maskgct/\">Open Method</a>\n"
    )
    (docs / "methods/maskgct.md").write_text("---\ntitle: MaskGCT\nhead: []\n---\n## Summary\n")
    (docs / "families/index.md").write_text("---\ntitle: Families\nhead: []\n---\n")
    (docs / "families/codec.md").write_text("---\ntitle: Codec\nhead: []\n---\n## Summary\n")
    (docs / "index.mdx").write_text("---\ntitle: Home\nhead: []\n---\n")
    (handbook / "astro.config.mjs").write_text("export default {};")
    (handbook / "src").mkdir(exist_ok=True)
    (handbook / "src/content.config.ts").write_text("export const collections = {};")
    (handbook / "package.json").write_text(json.dumps({
        "dependencies": {"remark-math": "6.0.0", "rehype-katex": "7.0.1", "katex": "0.16.11"}
    }))
    (run_dir / "12_taxonomy").mkdir()
    (run_dir / "12_taxonomy/outline.json").write_text(json.dumps({
        "methods": [{"id": "maskgct"}]
    }))


def test_validate_source_site_checks_method_links(tmp_path):
    from handbook_builder.validation import validate_source_site

    run_dir = tmp_path / "run"
    _write_site(run_dir)

    validate_source_site(run_dir)


def test_validate_source_site_accepts_project_base_method_links(tmp_path, monkeypatch):
    from handbook_builder.validation import validate_source_site

    run_dir = tmp_path / "run"
    _write_site(run_dir)
    monkeypatch.delenv("HANDBOOK_PUBLISH_ENABLED", raising=False)
    monkeypatch.setenv("HANDBOOK_BASE_PATH", "/automous_agent_research")
    (run_dir / "19_handbook/src/content/docs/methods/index.md").write_text(
        "---\ntitle: Methods\nhead: []\n---\n"
        '<a href="/automous_agent_research/methods/maskgct/">Open Method</a>\n'
    )

    validate_source_site(run_dir)


def test_validate_source_site_rejects_missing_method_link(tmp_path):
    from handbook_builder.validation import validate_source_site

    run_dir = tmp_path / "run"
    _write_site(run_dir)
    (run_dir / "19_handbook/src/content/docs/methods/index.md").write_text(
        "---\ntitle: Methods\nhead: []\n---\n"
    )

    try:
        validate_source_site(run_dir)
    except RuntimeError as error:
        assert "methods index missing links" in str(error)
    else:
        raise AssertionError("expected missing method link failure")


def test_validate_built_site_writes_build_ok_marker(tmp_path):
    from handbook_builder.validation import build_ok_path, validate_built_site

    run_dir = tmp_path / "run"
    _write_site(run_dir)
    dist = run_dir / "19_handbook/dist"
    for page in (
        "index.html",
        "methods/index.html",
        "families/index.html",
        "methods/maskgct/index.html",
        "families/codec/index.html",
    ):
        path = dist / page
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<html></html>")

    validate_built_site(run_dir)

    assert build_ok_path(run_dir).exists()


def test_validate_source_site_rejects_bad_math_delimiters(tmp_path):
    from handbook_builder.validation import validate_source_site

    run_dir = tmp_path / "run"
    _write_site(run_dir)
    (run_dir / "19_handbook/src/content/docs/methods/maskgct.md").write_text(
        "---\ntitle: MaskGCT\nhead: []\n---\n$$ $x+1$ $$\n"
    )

    try:
        validate_source_site(run_dir)
    except RuntimeError as error:
        assert "bad math delimiters" in str(error)
    else:
        raise AssertionError("expected bad math delimiter failure")


def test_validate_source_site_rejects_raw_latex_delimiters(tmp_path):
    from handbook_builder.validation import validate_source_site

    run_dir = tmp_path / "run"
    _write_site(run_dir)
    (run_dir / "19_handbook/src/content/docs/methods/maskgct.md").write_text(
        "---\ntitle: MaskGCT\nhead: []\n---\nUse \\(x\\) and \\[y\\].\n"
    )

    try:
        validate_source_site(run_dir)
    except RuntimeError as error:
        assert "bad math delimiters" in str(error)
    else:
        raise AssertionError("expected raw LaTeX delimiter failure")


def test_validate_source_site_rejects_unsupported_textsc(tmp_path):
    from handbook_builder.validation import validate_source_site

    run_dir = tmp_path / "run"
    _write_site(run_dir)
    (run_dir / "19_handbook/src/content/docs/methods/maskgct.md").write_text(
        "---\ntitle: MaskGCT\nhead: []\n---\n$$\n\\textsc{Pass}(x)\n$$\n"
    )

    try:
        validate_source_site(run_dir)
    except RuntimeError as error:
        assert "bad math delimiters" in str(error)
    else:
        raise AssertionError("expected unsupported textsc failure")


def test_validate_source_site_ignores_raw_latex_in_code(tmp_path):
    from handbook_builder.validation import validate_source_site

    run_dir = tmp_path / "run"
    _write_site(run_dir)
    (run_dir / "19_handbook/src/content/docs/methods/maskgct.md").write_text(
        "---\ntitle: MaskGCT\nhead: []\n---\nUse `\\(x\\)`.\n\n```md\n\\[y\\]\n\\textsc{Pass}\n```\n"
    )

    validate_source_site(run_dir)


def test_validate_source_site_rejects_duplicate_body_h1(tmp_path):
    from handbook_builder.validation import validate_source_site

    run_dir = tmp_path / "run"
    _write_site(run_dir)
    (run_dir / "19_handbook/src/content/docs/methods/maskgct.md").write_text(
        "---\ntitle: MaskGCT\nhead: []\n---\n# MaskGCT\n"
    )

    try:
        validate_source_site(run_dir)
    except RuntimeError as error:
        assert "duplicate body H1" in str(error)
    else:
        raise AssertionError("expected duplicate body H1 failure")


def test_validate_built_site_rejects_katex_error(tmp_path):
    from handbook_builder.validation import validate_built_site

    run_dir = tmp_path / "run"
    _write_site(run_dir)
    dist = run_dir / "19_handbook/dist"
    for page in (
        "index.html",
        "methods/index.html",
        "families/index.html",
        "methods/maskgct/index.html",
        "families/codec/index.html",
    ):
        path = dist / page
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<html></html>")
    (dist / "methods/maskgct/index.html").write_text('<span class="katex-error">bad</span>')

    try:
        validate_built_site(run_dir)
    except RuntimeError as error:
        assert "KaTeX render errors" in str(error)
    else:
        raise AssertionError("expected KaTeX render error failure")


def test_validate_built_site_rejects_katex_unsupported_macro_marker(tmp_path):
    from handbook_builder.validation import validate_built_site

    run_dir = tmp_path / "run"
    _write_site(run_dir)
    dist = run_dir / "19_handbook/dist"
    for page in (
        "index.html",
        "methods/index.html",
        "families/index.html",
        "methods/maskgct/index.html",
        "families/codec/index.html",
    ):
        path = dist / page
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<html></html>")
    (dist / "methods/maskgct/index.html").write_text('<mtext mathcolor="#cc0000">\\textsc</mtext>')

    try:
        validate_built_site(run_dir)
    except RuntimeError as error:
        assert "KaTeX unsupported macro markers" in str(error)
    else:
        raise AssertionError("expected KaTeX unsupported macro marker failure")


def test_validate_built_site_requires_publish_ready_project_base(tmp_path):
    from handbook_builder.deploy import PublishConfig
    from handbook_builder.validation import publish_ready_path, validate_built_site

    run_dir = tmp_path / "run"
    _write_site(run_dir)
    dist = run_dir / "19_handbook/dist"
    for page in (
        "index.html",
        "methods/index.html",
        "families/index.html",
        "methods/maskgct/index.html",
        "families/codec/index.html",
    ):
        path = dist / page
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<html></html>")

    config = PublishConfig(
        enabled=True,
        site_url="https://example.github.io",
        base_path="/project-site",
        source_path=None,
    )

    try:
        validate_built_site(run_dir, publish_config=config)
    except RuntimeError as error:
        assert ".nojekyll" in str(error)
    else:
        raise AssertionError("expected missing .nojekyll failure")

    (dist / ".nojekyll").write_text("")
    (dist / "index.html").write_text(
        '<html><link rel="stylesheet" href="/project-site/_astro/main.css"></html>'
    )

    validate_built_site(run_dir, publish_config=config)

    assert publish_ready_path(run_dir).exists()
