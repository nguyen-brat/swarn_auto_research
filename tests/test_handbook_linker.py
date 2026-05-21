import json
from pathlib import Path


def test_copy_chapters_into_docs(tmp_path):
    from handbook_builder.linker import copy_chapters_into_docs

    run_dir = tmp_path / "run"
    chapters = run_dir / "14_chapters"
    (chapters / "methods").mkdir(parents=True)
    (chapters / "families").mkdir()
    (chapters / "book").mkdir()
    (chapters / "methods/maskgct.md").write_text("---\ntitle: MaskGCT\n---\n# MaskGCT\n\nBody.\n")
    (chapters / "families/codec-tts.md").write_text("# Codec TTS Family\n")
    (chapters / "book/00_preface.md").write_text("# Preface\n")

    docs = run_dir / "19_handbook/src/content/docs"
    copy_chapters_into_docs(run_dir, docs)

    assert (docs / "methods/maskgct.md").exists()
    assert (docs / "families/codec-tts.md").exists()
    assert (docs / "book/00_preface.md").exists()
    method_text = (docs / "methods/maskgct.md").read_text()
    assert "head: []" in method_text
    assert "# MaskGCT" in method_text


def test_copy_chapters_into_docs_can_emit_mdx_for_augmented_milestones(tmp_path):
    from handbook_builder.linker import copy_chapters_into_docs

    run_dir = tmp_path / "run"
    chapters = run_dir / "14_chapters"
    (chapters / "methods").mkdir(parents=True)
    (chapters / "methods/maskgct.md").write_text("# MaskGCT\n")

    docs = run_dir / "19_handbook/src/content/docs"
    copy_chapters_into_docs(run_dir, docs, output_extension=".mdx")

    assert (docs / "methods/maskgct.mdx").exists()


def test_copy_chapters_into_docs_removes_stale_markdown_outputs(tmp_path):
    from handbook_builder.linker import copy_chapters_into_docs

    run_dir = tmp_path / "run"
    chapters = run_dir / "14_chapters"
    (chapters / "methods").mkdir(parents=True)
    (chapters / "methods/maskgct.md").write_text("# MaskGCT\n")
    docs = run_dir / "19_handbook/src/content/docs"
    stale = docs / "methods/maskgct.mdx"
    stale.parent.mkdir(parents=True)
    stale.write_text("# stale\n")

    copy_chapters_into_docs(run_dir, docs)

    assert not stale.exists()
    assert (docs / "methods/maskgct.md").exists()


def test_copy_chapters_into_docs_adds_frontmatter_when_missing(tmp_path):
    from handbook_builder.linker import copy_chapters_into_docs

    run_dir = tmp_path / "run"
    chapters = run_dir / "14_chapters"
    (chapters / "book/appendices").mkdir(parents=True)
    (chapters / "book/appendices/notation.md").write_text("# Notation\n\nBody.\n")

    docs = run_dir / "19_handbook/src/content/docs"
    copy_chapters_into_docs(run_dir, docs)

    text = (docs / "book/appendices/notation.md").read_text()
    assert text.startswith('---\ntitle: "Notation"\nhead: []\n---\n# Notation')


def test_copy_chapters_into_docs_rewrites_public_figure_paths_with_base_path(tmp_path):
    from handbook_builder.linker import copy_chapters_into_docs

    run_dir = tmp_path / "run"
    chapters = run_dir / "14_chapters"
    (chapters / "methods").mkdir(parents=True)
    (chapters / "methods/maskgct.md").write_text(
        "# MaskGCT\n\n![Workflow](/paper_figures/1234/workflow.png)\n"
    )

    docs = run_dir / "19_handbook/src/content/docs"
    copy_chapters_into_docs(run_dir, docs, base_path="/automous_agent_research")

    text = (docs / "methods/maskgct.md").read_text()
    assert "(/automous_agent_research/paper_figures/1234/workflow.png)" in text


def test_copy_chapters_into_docs_prunes_to_sidebar_reachable_pages(tmp_path):
    from handbook_builder.linker import copy_chapters_into_docs

    run_dir = tmp_path / "run"
    chapters = run_dir / "14_chapters"
    (chapters / "methods").mkdir(parents=True)
    (chapters / "families").mkdir()
    (chapters / "book").mkdir()
    (chapters / "methods/keep.md").write_text("# Keep\n")
    (chapters / "methods/orphan.md").write_text("# Orphan\n")
    (chapters / "families/fam.md").write_text("# Family\n")
    (chapters / "book/00_preface.md").write_text("# Preface\n")
    (run_dir / "16_book").mkdir()
    (run_dir / "16_book/sidebar.json").write_text(json.dumps({"items": [
        {"title": "Book", "children": [{"title": "Preface", "path": "14_chapters/book/00_preface.md"}]},
        {
            "title": "Part",
            "children": [
                {
                    "title": "Family",
                    "path": "14_chapters/families/fam.md",
                    "children": [{"title": "Keep", "path": "14_chapters/methods/keep.md"}],
                }
            ],
        },
    ]}))
    docs = run_dir / "19_handbook/src/content/docs"
    stale = docs / "methods/orphan.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("# stale orphan\n")

    copy_chapters_into_docs(run_dir, docs, require_sidebar=True)

    assert (docs / "methods/keep.md").exists()
    assert not (docs / "methods/orphan.md").exists()
    assert (docs / "families/fam.md").exists()
    assert (docs / "book/00_preface.md").exists()


def test_copy_chapters_into_docs_requires_sidebar_when_requested(tmp_path):
    from handbook_builder.linker import copy_chapters_into_docs

    run_dir = tmp_path / "run"
    docs = run_dir / "19_handbook/src/content/docs"

    try:
        copy_chapters_into_docs(run_dir, docs, require_sidebar=True)
    except RuntimeError as error:
        assert "sidebar.json" in str(error)
    else:
        raise AssertionError("expected missing sidebar failure")


def test_copy_chapters_into_docs_rejects_placeholder_sidebar_method(tmp_path):
    from handbook_builder.linker import copy_chapters_into_docs

    run_dir = tmp_path / "run"
    chapters = run_dir / "14_chapters"
    (chapters / "methods").mkdir(parents=True)
    (chapters / "methods/method-2509-06216.md").write_text(
        "---\narxiv_id: \"2509.06216\"\n---\n# Placeholder\n"
    )
    (run_dir / "16_book").mkdir()
    (run_dir / "16_book/sidebar.json").write_text(json.dumps({"items": [
        {
            "title": "Part",
            "children": [
                {"title": "2509.06216", "path": "14_chapters/methods/method-2509-06216.md"}
            ],
        }
    ]}))

    try:
        copy_chapters_into_docs(
            run_dir,
            run_dir / "19_handbook/src/content/docs",
            require_sidebar=True,
        )
    except RuntimeError as error:
        assert "cannot publish placeholder" in str(error)
        assert "Rerun from Stage 13" in str(error)
    else:
        raise AssertionError("expected placeholder sidebar failure")


def test_copy_paper_figures_copies_cached_stage13_assets(tmp_path):
    from handbook_builder.linker import copy_paper_figures

    run_dir = tmp_path / "run"
    src = run_dir / "13_chapter_packs/assets/paper_figures/1234/workflow.png"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"image")

    copy_paper_figures(run_dir, run_dir / "19_handbook")

    assert (run_dir / "19_handbook/public/paper_figures/1234/workflow.png").read_bytes() == b"image"


def test_build_starlight_sidebar(tmp_path):
    from handbook_builder.linker import build_starlight_sidebar

    sidebar_json = {
        "items": [
            {"title": "Book", "children": [{"title": "Preface", "path": "14_chapters/book/00_preface.md"}]},
            {
                "title": "Generation",
                "children": [
                    {
                        "title": "Codec TTS",
                        "path": "14_chapters/families/codec-tts.md",
                        "children": [
                            {"title": "MaskGCT (vq-...)", "path": "14_chapters/methods/maskgct.md"}
                        ],
                    }
                ],
            },
        ]
    }
    result = build_starlight_sidebar(sidebar_json)
    assert result == [
        {"label": "Handbook", "items": [
            {"label": "Home", "link": "/"},
            {"label": "Methods", "slug": "methods"},
            {"label": "Families", "slug": "families"},
        ]},
        {"label": "Book", "items": [{"label": "Preface", "slug": "book/00_preface"}]},
        {
            "label": "Families",
            "items": [
                {
                    "label": "Codec TTS",
                    "collapsed": True,
                    "items": [
                        {"label": "Overview", "slug": "families/codec-tts"},
                        {"label": "MaskGCT (vq-...)", "slug": "methods/maskgct"},
                    ],
                }
            ],
        },
    ]


def test_build_starlight_sidebar_preserves_nested_families(tmp_path):
    from handbook_builder.linker import build_starlight_sidebar

    sidebar_json = {
        "items": [
            {
                "title": "Repair",
                "children": [
                    {
                        "title": "APR family",
                        "path": "14_chapters/families/apr.md",
                        "children": [
                            {"title": "RepairAgent", "path": "14_chapters/methods/repairagent.md"},
                        ],
                    }
                ],
            }
        ]
    }

    sidebar = build_starlight_sidebar(sidebar_json)
    assert sidebar[-1] == {
        "label": "Families",
        "items": [
            {
                "label": "APR family",
                "collapsed": True,
                "items": [
                    {"label": "Overview", "slug": "families/apr"},
                    {"label": "RepairAgent", "slug": "methods/repairagent"},
                ],
            }
        ],
    }


def test_build_starlight_sidebar_does_not_mix_slug_and_items():
    from handbook_builder.linker import build_starlight_sidebar

    sidebar_json = {
        "items": [
            {
                "title": "Repair",
                "children": [
                    {
                        "title": "APR",
                        "path": "14_chapters/families/apr.md",
                        "children": [
                            {"title": "RepairAgent", "path": "14_chapters/methods/repairagent.md"},
                        ],
                    }
                ],
            }
        ]
    }

    def assert_valid_starlight_shape(items):
        for item in items:
            assert not ("slug" in item and "items" in item), item
            if "items" in item:
                assert_valid_starlight_shape(item["items"])

    assert_valid_starlight_shape(build_starlight_sidebar(sidebar_json))


def test_write_index_pages_adds_method_links(tmp_path):
    from handbook_builder.linker import write_index_pages

    run_dir = tmp_path / "run"
    docs = run_dir / "19_handbook/src/content/docs"
    (docs / "families").mkdir(parents=True)
    (docs / "families/apr.md").write_text("---\ntitle: APR\nhead: []\n---\n# APR\n")
    (docs / "methods").mkdir(parents=True)
    (docs / "methods/repairagent.md").write_text("---\ntitle: RepairAgent\nhead: []\n---\n# RepairAgent\n")
    book = run_dir / "16_book"
    book.mkdir(parents=True)
    (book / "chapters_manifest.json").write_text(json.dumps([
        {"type": "methods", "id": "repairagent", "title": "RepairAgent", "path": "methods/repairagent"},
        {"type": "families", "id": "apr", "title": "APR", "path": "families/apr"},
    ]))
    (book / "sidebar.json").write_text(json.dumps({"items": [
        {
            "title": "Repair",
            "children": [
                {
                    "title": "APR",
                    "path": "14_chapters/families/apr.md",
                    "children": [
                        {"title": "RepairAgent", "path": "14_chapters/methods/repairagent.md"}
                    ],
                }
            ],
        }
    ]}))

    write_index_pages(run_dir, docs)

    methods_index = (docs / "methods/index.md").read_text()
    families_index = (docs / "families/index.md").read_text()
    family_page = (docs / "families/apr.md").read_text()
    assert methods_index.count('href="/methods/repairagent/"') >= 1
    assert "Open Method" in methods_index
    assert 'href="/families/apr/"' in families_index
    assert "Methods in this family" in family_page
    assert 'href="/methods/repairagent/"' in family_page


def test_write_index_pages_prefixes_project_base_links(tmp_path):
    from handbook_builder.linker import write_index_pages

    run_dir = tmp_path / "run"
    docs = run_dir / "19_handbook/src/content/docs"
    (docs / "families").mkdir(parents=True)
    (docs / "families/apr.md").write_text("---\ntitle: APR\nhead: []\n---\n# APR\n")
    (docs / "methods").mkdir(parents=True)
    (docs / "methods/repairagent.md").write_text("---\ntitle: RepairAgent\nhead: []\n---\n# RepairAgent\n")
    book = run_dir / "16_book"
    book.mkdir(parents=True)
    (book / "chapters_manifest.json").write_text(json.dumps([
        {"type": "methods", "id": "repairagent", "title": "RepairAgent", "path": "methods/repairagent"},
        {"type": "families", "id": "apr", "title": "APR", "path": "families/apr"},
    ]))
    (book / "sidebar.json").write_text(json.dumps({"items": [
        {
            "title": "Repair",
            "children": [
                {
                    "title": "APR",
                    "path": "14_chapters/families/apr.md",
                    "children": [
                        {"title": "RepairAgent", "path": "14_chapters/methods/repairagent.md"}
                    ],
                }
            ],
        }
    ]}))

    write_index_pages(run_dir, docs, base_path="/automous_agent_research")

    methods_index = (docs / "methods/index.md").read_text()
    families_index = (docs / "families/index.md").read_text()
    family_page = (docs / "families/apr.md").read_text()
    assert 'href="/automous_agent_research/methods/repairagent/"' in methods_index
    assert 'href="/automous_agent_research/families/apr/"' in families_index
    assert 'href="/automous_agent_research/methods/repairagent/"' in family_page


def test_write_index_pages_ignores_stale_docs_not_in_sidebar(tmp_path):
    from handbook_builder.linker import write_index_pages

    run_dir = tmp_path / "run"
    docs = run_dir / "19_handbook/src/content/docs"
    (docs / "families").mkdir(parents=True)
    (docs / "families/apr.md").write_text("---\ntitle: APR\nhead: []\n---\n# APR\n")
    (docs / "methods").mkdir(parents=True)
    (docs / "methods/repairagent.md").write_text("---\ntitle: RepairAgent\nhead: []\n---\n# RepairAgent\n")
    (docs / "methods/orphan.md").write_text("---\ntitle: Orphan\nhead: []\n---\n# Orphan\n")
    book = run_dir / "16_book"
    book.mkdir(parents=True)
    (book / "chapters_manifest.json").write_text(json.dumps([
        {"type": "methods", "id": "repairagent", "title": "RepairAgent", "path": "methods/repairagent"},
        {"type": "methods", "id": "orphan", "title": "Orphan", "path": "methods/orphan"},
    ]))
    (book / "sidebar.json").write_text(json.dumps({"items": [
        {
            "title": "Repair",
            "children": [
                {
                    "title": "APR",
                    "path": "14_chapters/families/apr.md",
                    "children": [
                        {"title": "RepairAgent", "path": "14_chapters/methods/repairagent.md"}
                    ],
                }
            ],
        }
    ]}))

    write_index_pages(run_dir, docs)

    methods_index = (docs / "methods/index.md").read_text()
    assert "RepairAgent" in methods_index
    assert "Orphan" not in methods_index
