import json
from pathlib import Path


def test_splice_tldr_into_method_mdx(tmp_path):
    from handbook_builder.augment import splice_tldr

    mdx = tmp_path / "maskgct.mdx"
    mdx.write_text("# MaskGCT\n\nOriginal prose.\n")
    payload = {
        "tldr": "Non-AR masked codec transformer for zero-shot TTS.",
        "key_idea": "Predict masked codec tokens in parallel.",
        "when_to_use": ["zero-shot cloning", "≤10 unmasking steps"],
        "tags": ["TTS", "Non-AR"],
    }

    splice_tldr(mdx, payload, diagram_rel=None)
    body = mdx.read_text()

    assert body.startswith("---\n")  # frontmatter inserted
    assert "head: []" in body
    assert "tags:" in body
    assert "<Tldr>" in body
    assert "Non-AR masked codec transformer" in body
    assert "<KeyIdea>" in body
    assert ":::tip[When to use this]" in body
    assert "Original prose." in body
    assert body.count("# MaskGCT") == 1  # original H1 retained


def test_splice_tldr_with_diagram(tmp_path):
    from handbook_builder.augment import splice_tldr

    mdx = tmp_path / "maskgct.mdx"
    mdx.write_text("# MaskGCT\n\nProse.\n")
    splice_tldr(mdx, {
        "tldr": "T.", "key_idea": "K.", "when_to_use": ["one"], "tags": []
    }, diagram_rel="../../assets/diagrams/methods/maskgct.mmd")

    body = mdx.read_text()
    assert '<Diagram src="../../assets/diagrams/methods/maskgct.mmd" />' in body


def test_splice_tldr_strips_old_frontmatter_and_preserves_math(tmp_path):
    from handbook_builder.augment import splice_tldr

    mdx = tmp_path / "act.mdx"
    mdx.write_text(
        "---\ntitle: Old\nstatus: passed\n---\n"
        "# ACT\n\n"
        "$$ t=\\frac{\\bar{x}-\\mu_0}{s/\\sqrt{n}} $$\n"
        "```python\nreturn x\n```\n"
    )

    splice_tldr(mdx, {
        "tldr": "T.", "key_idea": "K.", "when_to_use": ["one"], "tags": []
    })

    body = mdx.read_text()
    assert body.count("---") == 2
    assert "head: []" in body
    assert "\\frac{\\bar{x}-\\mu_0}" in body
    assert "```python" in body


def test_splice_tldr_preserves_frontmatter_title_without_body_h1(tmp_path):
    from handbook_builder.augment import splice_tldr

    mdx = tmp_path / "gcc.mdx"
    mdx.write_text("---\ntitle: \"Git Context Controller\"\nhead: []\n---\n\n## Summary\nBody.\n")

    splice_tldr(mdx, {
        "tldr": "T.", "key_idea": "K.", "when_to_use": ["one"], "tags": []
    })

    body = mdx.read_text()
    assert 'title: "Git Context Controller"' in body
    assert 'title: "Untitled"' not in body
