def test_sanitize_nested_display_math_single_line():
    from handbook_builder.markdown_sanitize import normalize_math_delimiters

    text = "$$ $\\mathcal{M}_{t}=\\texttt{COMMIT}(\\mathcal{H}_{t})$ $$\n"

    assert normalize_math_delimiters(text) == (
        "$$\n"
        "\\mathcal{M}_{t}=\\texttt{COMMIT}(\\mathcal{H}_{t})\n"
        "$$\n"
    )


def test_sanitize_nested_display_math_multiline():
    from handbook_builder.markdown_sanitize import normalize_math_delimiters

    text = "$$\n$\\mathcal{F}(x)=x+1$\n$$\n"

    assert normalize_math_delimiters(text) == "$$\n\\mathcal{F}(x)=x+1\n$$\n"


def test_sanitize_multiline_display_math_with_trailing_label():
    from handbook_builder.markdown_sanitize import normalize_math_delimiters

    text = "$$\n$r=\\frac{x}{y},$ (1)\n$$\n"

    assert normalize_math_delimiters(text) == "$$\nr=\\frac{x}{y}, (1)\n$$\n"


def test_sanitize_labeled_nested_display_math_single_line():
    from handbook_builder.markdown_sanitize import normalize_math_delimiters

    text = "$$ (1) $\\text{Efficiency@}k:=\\frac{\\text{Play@}k}{AT_{k}}$ $$\n"

    assert normalize_math_delimiters(text) == (
        "$$\n"
        "(1) \\text{Efficiency@}k:=\\frac{\\text{Play@}k}{AT_{k}}\n"
        "$$\n"
    )


def test_sanitize_trailing_labeled_nested_display_math_single_line():
    from handbook_builder.markdown_sanitize import normalize_math_delimiters

    text = "$$ $T_{i}(1|h)=\\sigma(h)$ (1) $$\n"

    assert normalize_math_delimiters(text) == "$$\nT_{i}(1|h)=\\sigma(h) (1)\n$$\n"


def test_sanitize_missing_closing_display_delimiter_with_nested_inline_math():
    from handbook_builder.markdown_sanitize import normalize_math_delimiters

    text = "$$ $\\displaystyle O^{(t)}(q)=\\operatorname{EXECUTE}(C^{(t)}(q)),$ (3) $\n"

    assert normalize_math_delimiters(text) == (
        "$$\n"
        "\\displaystyle O^{(t)}(q)=\\operatorname{EXECUTE}(C^{(t)}(q)), (3)\n"
        "$$\n"
    )


def test_sanitize_preserves_valid_inline_and_display_math():
    from handbook_builder.markdown_sanitize import normalize_math_delimiters

    text = "Inline $x+1$ stays.\n\n$$\ny=x+2\n$$\n"

    assert normalize_math_delimiters(text) == text


def test_sanitize_escapes_underscores_inside_text_macros():
    from handbook_builder.markdown_sanitize import normalize_math_delimiters

    text = "$$\n\\Delta\\texttt{val_bpb}+\\text{FAIL_TO_PASS}\n$$\n"

    assert normalize_math_delimiters(text) == "$$\n\\Delta\\texttt{val\\_bpb}+\\text{FAIL\\_TO\\_PASS}\n$$\n"


def test_sanitize_raw_inline_latex_delimiters():
    from handbook_builder.markdown_sanitize import normalize_math_delimiters

    text = "Use \\(P^{\\prime}\\) and \\((x,y)\\) in prose.\n"

    assert normalize_math_delimiters(text) == "Use $P^{\\prime}$ and $(x,y)$ in prose.\n"


def test_sanitize_raw_latex_delimiters_skips_code():
    from handbook_builder.markdown_sanitize import normalize_math_delimiters

    text = "Use `\\(raw\\)`.\n\n```md\n\\(raw\\)\n\\[x\\]\n```\n"

    assert normalize_math_delimiters(text) == text


def test_sanitize_raw_display_latex_delimiters_multiline():
    from handbook_builder.markdown_sanitize import normalize_math_delimiters

    text = "\\[\na+b\n=c\n\\]\n"

    assert normalize_math_delimiters(text) == "$$\na+b\n=c\n$$\n"


def test_sanitize_keeps_latex_linebreak_spacing_in_display_math():
    from handbook_builder.markdown_sanitize import normalize_math_delimiters

    text = "$$\n\\begin{cases}a,&b\\\\[8.0pt]0,&c\\end{cases}\n$$\n"

    assert normalize_math_delimiters(text) == text


def test_sanitize_textsc_macros_for_katex():
    from handbook_builder.markdown_sanitize import normalize_math_delimiters

    text = "$$\n\\textsc{Pass}(x)+\\textsc{Fail to Pass}(y)\n$$\n"

    assert normalize_math_delimiters(text) == "$$\n\\mathrm{Pass}(x)+\\text{Fail to Pass}(y)\n$$\n"


def test_sanitize_removes_internal_dollar_separators_inside_display_math():
    from handbook_builder.markdown_sanitize import normalize_math_delimiters

    text = "$$\n\\displaystyle S(x)$ $\\displaystyle=\\lambda x$ (1) $\\displaystyle+y\n$$\n"

    assert normalize_math_delimiters(text) == "$$\n\\displaystyle S(x) \\displaystyle=\\lambda x (1) \\displaystyle+y\n$$\n"


def test_sanitize_removes_pgf_color_noise_inside_text_macro():
    from handbook_builder.markdown_sanitize import normalize_math_delimiters

    text = (
        "$$\\text{{\\color[rgb]{0,0,0}\\definecolor[named]{pgfstrokecolor}{rgb}{0,0,0} "
        "\\pgfsys@color@gray@stroke{0}\\pgfsys@color@gray@fill{0}visibility}}=1$$\n"
    )

    assert normalize_math_delimiters(text) == "$$\\text{visibility}=1$$\n"


def test_remove_duplicate_h1_matching_frontmatter_title():
    from handbook_builder.markdown_sanitize import remove_duplicate_body_h1

    text = "---\ntitle: \"GCC\"\nhead: []\n---\n# GCC\n\n## Summary\nBody.\n"

    assert remove_duplicate_body_h1(text) == "---\ntitle: \"GCC\"\nhead: []\n---\n\n## Summary\nBody.\n"


def test_keep_nonmatching_h1():
    from handbook_builder.markdown_sanitize import remove_duplicate_body_h1

    text = "---\ntitle: \"GCC\"\nhead: []\n---\n# Summary\n\nBody.\n"

    assert remove_duplicate_body_h1(text) == text


def test_sanitize_docs_tree_removes_duplicate_h1_after_family_enhancement(tmp_path):
    from handbook_builder.markdown_sanitize import sanitize_docs_tree

    docs = tmp_path / "docs"
    family = docs / "families/apr.md"
    family.parent.mkdir(parents=True)
    family.write_text(
        "---\ntitle: APR\nhead: []\n---\n"
        "# APR\n"
        "\n## Methods in this family\n\n"
        '<div class="method-grid"></div>\n'
        "\n## Summary\nBody.\n"
    )

    sanitize_docs_tree(docs)

    text = family.read_text()
    assert "# APR" not in text
    assert text.index("## Methods in this family") < text.index("## Summary")
