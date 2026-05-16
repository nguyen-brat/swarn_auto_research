from knowledge_gap_aggregator.signals import (
    SLOT_BY_FIELD,
    concepts_in_paper,
    paper_count_per_concept,
    core_paper_count_per_concept,
    in_slots_per_concept,
    is_method_of_core_per_concept,
)


def _p(arxiv_id, *, importance, **fields):
    base = {
        "arxiv_id": arxiv_id,
        "title": fields.pop("title", ""),
        "topic_tags": [],
        "methods": [],
        "datasets": [],
        "benchmarks": [],
        "baselines": [],
        "metrics": [],
        "mentioned_entities": [],
        "reader_needed_concepts": [],
        "book_usage": {"importance_score_1_to_5": importance},
    }
    base.update(fields)
    return base


def test_slot_by_field_table():
    assert SLOT_BY_FIELD["methods"] == "method"
    assert SLOT_BY_FIELD["datasets"] == "method"
    assert SLOT_BY_FIELD["benchmarks"] == "result"
    assert SLOT_BY_FIELD["baselines"] == "result"
    assert SLOT_BY_FIELD["metrics"] == "result"
    assert SLOT_BY_FIELD["topic_tags"] == "abstract"
    assert SLOT_BY_FIELD["reader_needed_concepts"] == "reader_needed"
    assert SLOT_BY_FIELD["mentioned_entities"] == "mention"


def test_concepts_in_paper_yields_normalized_name_and_slot():
    paper = _p("p1", importance=5,
               title="ViT for Vision",
               methods=["ViT", "Transformer"],
               topic_tags=["computer vision"])
    out = concepts_in_paper(paper)
    pairs = sorted((c["normalized"], c["slot"]) for c in out)
    assert ("computer vision", "abstract") in pairs
    assert ("transformer", "method") in pairs
    assert ("vit", "method") in pairs
    assert ("vit", "title") in pairs  # ViT in title -> title slot too


def test_concepts_in_paper_title_match_case_insensitive():
    paper = _p("p1", importance=5, title="A Survey of CLIP",
               methods=["CLIP"])
    out = concepts_in_paper(paper)
    slots = {(c["normalized"], c["slot"]) for c in out}
    assert ("clip", "title") in slots
    assert ("clip", "method") in slots


def test_concepts_in_paper_title_match_is_word_boundary():
    # "vit" must NOT match a title containing "gravity".
    paper = _p("p1", importance=5, title="Gravity and Inertia",
               methods=["ViT"])
    out = concepts_in_paper(paper)
    slots = {(c["normalized"], c["slot"]) for c in out}
    assert ("vit", "method") in slots
    assert ("vit", "title") not in slots


def test_paper_count_per_concept_from_evidence():
    evidence = {
        "p1": _p("p1", importance=5, methods=["ViT", "Transformer"]),
        "p2": _p("p2", importance=4, methods=["ViT"], baselines=["Transformer"]),
        "p3": _p("p3", importance=2, methods=["wav2vec"]),
    }
    counts = paper_count_per_concept(evidence)
    assert counts["vit"] == 2
    assert counts["transformer"] == 2
    assert counts["wav2vec"] == 1


def test_core_paper_count_uses_book_usage_importance():
    evidence = {
        "p1": _p("p1", importance=5, methods=["ViT"]),
        "p2": _p("p2", importance=3, methods=["ViT"]),  # not core
    }
    counts = core_paper_count_per_concept(evidence, threshold=4)
    assert counts["vit"] == 1


def test_in_slots_aggregates_across_papers():
    evidence = {
        "p1": _p("p1", importance=5, title="ViT for Vision",
                 methods=["ViT"], topic_tags=["vision"]),
        "p2": _p("p2", importance=3, baselines=["ViT"]),
    }
    slots = in_slots_per_concept(evidence)
    # ViT appears as method (p1), title (p1), and result via baselines (p2)
    assert sorted(slots["vit"]) == ["method", "result", "title"]
    assert "abstract" in slots["vision"]


def test_is_method_of_core_true_when_methods_of_core_paper():
    evidence = {
        "p1": _p("p1", importance=5, methods=["ViT"]),
        "p2": _p("p2", importance=2, methods=["wav2vec"]),
    }
    out = is_method_of_core_per_concept(evidence, threshold=4)
    assert out.get("vit") is True
    assert out.get("wav2vec") is False  # core threshold not met


def test_is_method_of_core_datasets_also_count():
    evidence = {"p1": _p("p1", importance=5, datasets=["LAION"])}
    out = is_method_of_core_per_concept(evidence, threshold=4)
    assert out.get("laion") is True


def test_is_method_of_core_baselines_do_not_count():
    evidence = {"p1": _p("p1", importance=5, baselines=["GPT-2"])}
    out = is_method_of_core_per_concept(evidence, threshold=4)
    # baselines map to slot "result", not "method of core"
    assert out.get("gpt 2", False) is False


from knowledge_gap_aggregator.signals import (
    graph_concept_ids,
    graph_paper_count_per_concept,
    is_method_of_core_via_graph,
    graph_neighbors_per_concept,
)


def _graph():
    return {
        "nodes": [
            {"id": "p1", "type": "Paper"},
            {"id": "p2", "type": "Paper"},
            {"id": "vit", "type": "Method", "display": "ViT"},
            {"id": "clip vision encoder", "type": "Method", "display": "CLIP vision encoder"},
            {"id": "graph only concept", "type": "Method", "display": "Graph Only Concept"},
        ],
        "edges": [
            {"src": "p1", "dst": "vit", "type": "INTRODUCES"},
            {"src": "p2", "dst": "vit", "type": "USES"},
            {"src": "p2", "dst": "clip vision encoder", "type": "INTRODUCES"},
            {"src": "p2", "dst": "graph only concept", "type": "USES"},
        ],
    }


def test_graph_concept_ids_excludes_papers():
    ids = graph_concept_ids(_graph())
    assert "p1" not in ids and "p2" not in ids
    assert "vit" in ids
    assert "graph only concept" in ids


def test_graph_paper_count_per_concept():
    counts = graph_paper_count_per_concept(_graph())
    assert counts["vit"] == 2
    assert counts["clip vision encoder"] == 1
    assert counts["graph only concept"] == 1


def test_is_method_of_core_via_graph_recognises_method_edge_types():
    graph = _graph()
    evidence = {"p1": _p("p1", importance=5), "p2": _p("p2", importance=2)}
    out = is_method_of_core_via_graph(graph, evidence, threshold=4)
    assert out.get("vit") is True            # INTRODUCES from core p1
    assert out.get("clip vision encoder") is False  # INTRODUCES only from non-core p2


def test_is_method_of_core_via_graph_ignores_non_method_types():
    graph = {
        "nodes": [{"id": "p1", "type": "Paper"}, {"id": "x", "type": "Method"}],
        "edges": [{"src": "p1", "dst": "x", "type": "MENTIONS"}],
    }
    evidence = {"p1": _p("p1", importance=5)}
    out = is_method_of_core_via_graph(graph, evidence, threshold=4)
    assert out.get("x", False) is False


def test_graph_neighbors_via_shared_papers():
    graph = _graph()
    n = graph_neighbors_per_concept(graph, limit=5)
    # vit and clip vision encoder share p2 -> neighbors of each other.
    assert "CLIP vision encoder" in n["vit"]
    assert "ViT" in n["clip vision encoder"]
