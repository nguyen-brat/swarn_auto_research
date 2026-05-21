from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_book_rewriter_skill_exists():
    skill = REPO_ROOT / ".agents/skills/web-book-rewriter/SKILL.md"
    assert skill.exists()
    text = skill.read_text()
    assert "≤ 4 sentences" in text or "<= 4 sentences" in text or "four sentences" in text
    assert "h3" in text
    assert ":::tip" in text or ":::note" in text
    assert "<details>" in text
    assert "no new factual claims" in text.lower() or "no new claims" in text.lower()


def test_book_rewriter_toml_exists():
    toml = REPO_ROOT / ".codex/agents/web_book_rewriter.toml"
    assert toml.exists()
    assert 'name = "web_book_rewriter"' in toml.read_text()


def test_build_book_rewrite_specs(tmp_path):
    from handbook_builder.book_rewrite import build_book_rewrite_specs

    run_dir = tmp_path / "run-b"
    (run_dir / "14_chapters/book").mkdir(parents=True)
    (run_dir / "14_chapters/book/00_preface.md").write_text("# Preface")
    (run_dir / "14_chapters/book/04_method_taxonomy.md").write_text("# Taxonomy")

    specs = build_book_rewrite_specs(run_dir, topic="Speech LMs")
    ids = sorted(s.shard_id for s in specs)
    assert ids == ["bookrewrite-00_preface", "bookrewrite-04_method_taxonomy"]
    assert all(s.agent == "web_book_rewriter" for s in specs)


def test_citation_count_matches():
    from handbook_builder.book_rewrite import count_citations

    original = "See [VALL-E 2](methods/vall-e-2.md) and [arxiv:2503.01234]."
    candidate = "Refer to [VALL-E 2](methods/vall-e-2.md) and [arxiv:2503.01234]."
    assert count_citations(original) == count_citations(candidate)
