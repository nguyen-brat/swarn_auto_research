# Auto Research Shard 01: Taxonomy Parts and Singleton Normalization

> **For agentic workers:** Implement this shard only. Do not load or execute the full reviewed source plan unless a referenced section is missing from this shard. Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` for execution.

**Source Material:** `docs/superpowers/plans/2026-05-10-codex-book-style-alignment.md` is the reviewed source plan. This shard copies the relevant task text and adds execution boundaries.

**Goal:** Add parts validation, deterministic Stage 12.5 singleton normalization, standalone group behavior, and taxonomy skill contracts.

**Prerequisites:** Shard 00 completed and committed. Citation lookup tests pass.

**Exit Criteria:** `pytest tests/test_research_book_parts.py -v`, `pytest tests/test_research_book_singleton_merge.py -v`, and `pytest tests/test_research_book_is_group.py -v` pass.

## Global Invariants

These apply to every shard. Do not weaken them while implementing a later shard.

- Stage 12.5 normalizes `12_taxonomy/outline.json` before Stage 13 builds chapter packs.
- Stage 18 calls `assert_no_singletons(outline)` and refuses raw singleton families.
- `standalone` is the only allowed singleton group; do not create `other_*` catch-all families.
- `standalone` / `is_group` families have no family chapter file and render methods flat under `standalone_methods`.
- `BOOK_FILE_BY_ID["appendices"] == "appendices"`; appendices is a directory, not `99_appendices.md`.
- Missing citation metadata must not block a readable book. It writes an unresolved marker in `references.md` and a `citation/<arxiv_id>` item in `NEEDS_REVIEW.md`.
- Excluded chapters are quarantined: they remain on disk, are omitted from main navigation, and are listed in `16_book/NEEDS_REVIEW.md`.
- Every shard must keep tests focused and run the shard's targeted tests before committing.

---

## Task 1.3: Add `parts` validator

**Files:**
- Test: `tests/test_research_book_parts.py` (create)
- Modify: `swarn_research_mcp/research_book.py` (extend `validate_research_book_run`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_research_book_parts.py
from __future__ import annotations
import json
from swarn_research_mcp.research_book import validate_research_book_run


def _set_outline(run_dir, outline):
    (run_dir / "12_taxonomy" / "outline.json").write_text(json.dumps(outline))


def _add_parts(outline, parts):
    outline["parts"] = parts
    return outline


def test_missing_parts_field_is_error(voice_lm_minimal):
    # voice_lm_minimal outline has no parts field
    issues = validate_research_book_run(voice_lm_minimal)
    assert any(i["code"] == "missing_parts" for i in issues)


def test_parts_count_too_low(voice_lm_minimal):
    outline = json.loads((voice_lm_minimal / "12_taxonomy" / "outline.json").read_text())
    _set_outline(voice_lm_minimal, _add_parts(outline, [
        {"id": "p1", "title": "P1", "family_ids": ["fam_codec", "fam_flow"]},
    ]))
    issues = validate_research_book_run(voice_lm_minimal)
    assert any(i["code"] == "parts_count_out_of_range" for i in issues)


def test_family_in_two_parts(voice_lm_minimal):
    outline = json.loads((voice_lm_minimal / "12_taxonomy" / "outline.json").read_text())
    _set_outline(voice_lm_minimal, _add_parts(outline, [
        {"id": "p1", "title": "P1", "family_ids": ["fam_codec", "fam_flow"]},
        {"id": "p2", "title": "P2", "family_ids": ["fam_flow"]},
    ]))
    issues = validate_research_book_run(voice_lm_minimal)
    assert any(i["code"] == "family_in_multiple_parts" and "fam_flow" in i["detail"] for i in issues)


def test_family_unassigned_to_part(voice_lm_minimal):
    outline = json.loads((voice_lm_minimal / "12_taxonomy" / "outline.json").read_text())
    # Add a 3rd dummy family so the second part can hold something and we test only the "unassigned" path.
    outline["families"].append({"id": "fam_dummy", "title": "Dummy", "method_ids": ["m_dummy_a", "m_dummy_b"]})
    outline["methods"].extend([
        {"id": "m_dummy_a", "title": "DA", "arxiv_id": "0001.0001", "family_id": "fam_dummy"},
        {"id": "m_dummy_b", "title": "DB", "arxiv_id": "0001.0002", "family_id": "fam_dummy"},
    ])
    _set_outline(voice_lm_minimal, _add_parts(outline, [
        {"id": "p1", "title": "P1", "family_ids": ["fam_codec"]},
        {"id": "p2", "title": "P2", "family_ids": ["fam_dummy"]},
    ]))
    issues = validate_research_book_run(voice_lm_minimal)
    assert any(i["code"] == "family_unassigned_to_part" and "fam_flow" in i["detail"] for i in issues)


def test_empty_part_is_error(voice_lm_minimal):
    outline = json.loads((voice_lm_minimal / "12_taxonomy" / "outline.json").read_text())
    _set_outline(voice_lm_minimal, _add_parts(outline, [
        {"id": "p1", "title": "P1", "family_ids": ["fam_codec", "fam_flow"]},
        {"id": "p2", "title": "P2", "family_ids": []},
    ]))
    issues = validate_research_book_run(voice_lm_minimal)
    assert any(i["code"] == "empty_part" and "p2" in i["detail"] for i in issues)


def test_valid_parts(voice_lm_minimal):
    outline = json.loads((voice_lm_minimal / "12_taxonomy" / "outline.json").read_text())
    _set_outline(voice_lm_minimal, _add_parts(outline, [
        {"id": "p1", "title": "P1", "family_ids": ["fam_codec"]},
        {"id": "p2", "title": "P2", "family_ids": ["fam_flow"]},
    ]))
    issues = validate_research_book_run(voice_lm_minimal)
    parts_codes = {"missing_parts", "parts_count_out_of_range",
                   "family_in_multiple_parts", "family_unassigned_to_part", "empty_part"}
    assert not any(i["code"] in parts_codes for i in issues)
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_research_book_parts.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `_validate_parts`**

In `swarn_research_mcp/research_book.py`, add above `_validate_parts` / `validate_research_book_run` (around line 175):

```python
STANDALONE_GROUP_ID = "standalone"
STANDALONE_PART_ID = "standalone_methods"


def _validate_parts(outline: dict[str, Any], families: list[dict[str, Any]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    parts = outline.get("parts")
    if parts is None:
        issues.append({"severity": "error", "code": "missing_parts",
                       "detail": "outline.json must define a 'parts' array (2..5 entries)"})
        return issues
    # 2..5 normal parts, plus an optional standalone_methods part on top.
    normal_parts = [p for p in parts if isinstance(p, dict) and p.get("id") != STANDALONE_PART_ID] \
        if isinstance(parts, list) else []
    if not isinstance(parts, list) or not (2 <= len(normal_parts) <= 5):
        n = len(normal_parts) if isinstance(parts, list) else "non-list"
        issues.append({"severity": "error", "code": "parts_count_out_of_range",
                       "detail": f"parts must have 2..5 entries (excluding {STANDALONE_PART_ID}), got {n}"})
        return issues
    family_ids = {f.get("id") for f in families if f.get("id")}
    seen_in: dict[str, str] = {}
    for part in parts:
        pid = part.get("id", "")
        fids = part.get("family_ids", []) or []
        if not fids:
            issues.append({"severity": "error", "code": "empty_part",
                           "detail": f"part {pid} has no families"})
        for fid in fids:
            if fid in seen_in:
                issues.append({"severity": "error", "code": "family_in_multiple_parts",
                               "detail": f"family {fid} appears in parts {seen_in[fid]} and {pid}"})
            else:
                seen_in[fid] = pid
    for fid in family_ids:
        if fid not in seen_in:
            issues.append({"severity": "error", "code": "family_unassigned_to_part",
                           "detail": f"family {fid} is not in any part"})
    return issues
```

In `validate_research_book_run`, after `families = outline.get("families", [])` (around line 185), append:
```python
    issues.extend(_validate_parts(outline, families))
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_research_book_parts.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_research_book_parts.py swarn_research_mcp/research_book.py
git commit -m "feat(research-book): validate outline.json parts (2..5, exclusive coverage of families)"
```

---

## Task 1.4: Singleton policy — merge with evidence, otherwise standalone

This is a **named Stage 12.5 contract** running between Stages 12 and 13.

**Policy:**
- A singleton **merges** into its nearest non-singleton family iff there is **strong graph evidence**: at least 2 of the singleton-method's `neighbor_method_ids` live in the candidate family, OR the candidate's id appears in the singleton's `neighbor_family_ids` AND at least 1 method overlap exists.
- Otherwise the singleton is **kept as a standalone method chapter** (no family chapter wrapper). Its family record is replaced with a marker `{"id": "standalone", "title": "Standalone / Emerging Methods", "method_ids": [...], "is_group": true}` — one such record per book, accumulating all weak singletons. The `standalone` group lives in its own part `standalone_methods` (auto-added if any standalone methods exist).
- `assert_no_singletons` (Stage 18) treats the `standalone` group as valid (i.e. allows `len(method_ids) >= 1` for `id == "standalone"`).

**Files:**
- Test: `tests/test_research_book_singleton_merge.py` (create)
- Modify: `swarn_research_mcp/research_book.py` (add `merge_singletons`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_research_book_singleton_merge.py
from __future__ import annotations
import json
from swarn_research_mcp.research_book import merge_singletons


BOOK_SECTIONS = [{"id": k, "title": k} for k in
    ["preface", "motivating_intro", "core_concepts", "goals", "method_taxonomy",
     "shared_examples", "evaluation_outlook", "appendices"]]


def _outline(families, methods, parts=None):
    return {"topic": "t", "book_sections": BOOK_SECTIONS,
            "families": families, "methods": methods,
            "parts": parts or [{"id": "p1", "title": "P1", "family_ids": [f["id"] for f in families]},
                                {"id": "p2", "title": "P2", "family_ids": []}]}


def test_singleton_with_strong_evidence_merges():
    """≥2 shared neighbor methods OR (neighbor_family_id + ≥1 shared method) triggers merge."""
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["m1"], "neighbor_family_ids": ["fam_b"]},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"], "neighbor_family_ids": ["fam_a"]},
    ]
    methods = [
        # m1 has 2 shared neighbors in fam_b → strong evidence → merge.
        {"id": "m1", "arxiv_id": "1.1", "family_id": "fam_a", "neighbor_method_ids": ["m2", "m3"]},
        {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b", "neighbor_method_ids": ["m1", "m3"]},
        {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b", "neighbor_method_ids": ["m2"]},
    ]
    merged = merge_singletons(_outline(families, methods))
    family_by_id = {f["id"]: f for f in merged["families"]}
    assert "fam_a" not in family_by_id
    assert sorted(family_by_id["fam_b"]["method_ids"]) == ["m1", "m2", "m3"]


def test_singleton_with_weak_evidence_goes_to_standalone():
    """1 shared neighbor without neighbor_family link → weak → standalone."""
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["m1"], "neighbor_family_ids": []},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"], "neighbor_family_ids": []},
    ]
    methods = [
        {"id": "m1", "arxiv_id": "1.1", "family_id": "fam_a", "neighbor_method_ids": ["m2"]},
        {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b", "neighbor_method_ids": ["m1", "m3"]},
        {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b", "neighbor_method_ids": ["m2"]},
    ]
    merged = merge_singletons(_outline(families, methods))
    family_by_id = {f["id"]: f for f in merged["families"]}
    assert "fam_a" not in family_by_id
    standalone = family_by_id["standalone"]
    assert standalone["is_group"] is True
    assert standalone["method_ids"] == ["m1"]
    parts_by_id = {p["id"]: p for p in merged["parts"]}
    assert "standalone" in parts_by_id["standalone_methods"]["family_ids"]


def test_singleton_with_no_evidence_goes_to_standalone():
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["m1"], "neighbor_family_ids": []},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"], "neighbor_family_ids": []},
    ]
    methods = [
        {"id": "m1", "arxiv_id": "1.1", "family_id": "fam_a", "neighbor_method_ids": []},
        {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b", "neighbor_method_ids": ["m3"]},
        {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b", "neighbor_method_ids": ["m2"]},
    ]
    merged = merge_singletons(_outline(families, methods))
    standalone = next(f for f in merged["families"] if f["id"] == "standalone")
    assert standalone["method_ids"] == ["m1"]


def test_method_family_id_updated_to_winner():
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["m1"], "neighbor_family_ids": ["fam_b"]},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"], "neighbor_family_ids": ["fam_a"]},
    ]
    methods = [
        {"id": "m1", "arxiv_id": "1.1", "family_id": "fam_a", "neighbor_method_ids": ["m2", "m3"]},
        {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b", "neighbor_method_ids": ["m1"]},
        {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b", "neighbor_method_ids": []},
    ]
    merged = merge_singletons(_outline(families, methods))
    method_by_id = {m["id"]: m for m in merged["methods"]}
    assert method_by_id["m1"]["family_id"] == "fam_b"


def test_singleton_picks_candidate_with_more_shared_neighbors():
    """If multiple candidates pass, choose the strongest graph evidence, not first id."""
    families = [
        {"id": "fam_single", "title": "Single", "method_ids": ["m1"], "neighbor_family_ids": []},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"], "neighbor_family_ids": []},
        {"id": "fam_c", "title": "C", "method_ids": ["m4", "m5", "m6"], "neighbor_family_ids": []},
    ]
    methods = [
        {"id": "m1", "arxiv_id": "1.1", "family_id": "fam_single",
         "neighbor_method_ids": ["m2", "m3", "m4", "m5", "m6"]},
        {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b"},
        {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b"},
        {"id": "m4", "arxiv_id": "1.4", "family_id": "fam_c"},
        {"id": "m5", "arxiv_id": "1.5", "family_id": "fam_c"},
        {"id": "m6", "arxiv_id": "1.6", "family_id": "fam_c"},
    ]
    merged = merge_singletons(_outline(families, methods))
    method_by_id = {m["id"]: m for m in merged["methods"]}
    family_by_id = {f["id"]: f for f in merged["families"]}
    assert method_by_id["m1"]["family_id"] == "fam_c"
    assert "m1" in family_by_id["fam_c"]["method_ids"]
    assert "m1" not in family_by_id["fam_b"]["method_ids"]


def test_no_op_when_all_families_have_two_methods():
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["m1", "m2"]},
        {"id": "fam_b", "title": "B", "method_ids": ["m3", "m4"]},
    ]
    methods = [{"id": f"m{i}", "arxiv_id": f"1.{i}", "family_id": fam} for i, fam in [(1,"fam_a"),(2,"fam_a"),(3,"fam_b"),(4,"fam_b")]]
    before = _outline(families, methods)
    after = merge_singletons(before)
    assert after == before


def test_assert_no_singletons_raises_on_unmerged_outline():
    from swarn_research_mcp.research_book import assert_no_singletons
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["m1"]},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"]},
    ]
    methods = [{"id": "m1", "arxiv_id": "1.1", "family_id": "fam_a"},
               {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b"},
               {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b"}]
    with pytest.raises(RuntimeError, match="singleton"):
        assert_no_singletons(_outline(families, methods))


def test_merge_prunes_empty_parts():
    """If a singleton was the only family in its part, the empty part is pruned."""
    families = [
        {"id": "fam_a", "title": "A", "method_ids": ["m1"], "neighbor_family_ids": ["fam_b"]},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"], "neighbor_family_ids": ["fam_a"]},
    ]
    methods = [
        {"id": "m1", "arxiv_id": "1.1", "family_id": "fam_a", "neighbor_method_ids": ["m2", "m3"]},
        {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b", "neighbor_method_ids": ["m1"]},
        {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b", "neighbor_method_ids": ["m1"]},
    ]
    parts = [{"id": "p_lone", "title": "Lone", "family_ids": ["fam_a"]},
             {"id": "p_main", "title": "Main", "family_ids": ["fam_b"]}]
    merged = merge_singletons(_outline(families, methods, parts))
    part_ids = {p["id"] for p in merged["parts"]}
    assert "p_lone" not in part_ids  # pruned (was empty after merge)
    assert "p_main" in part_ids


def test_standalone_part_does_not_count_against_5_cap():
    """6 total parts is OK iff one of them is standalone_methods."""
    from swarn_research_mcp.research_book import _validate_parts
    families = [{"id": f"fam_{c}", "title": c, "method_ids": [f"m_{c}1", f"m_{c}2"]}
                for c in "abcde"] + [{"id": "standalone", "title": "Standalone",
                                       "method_ids": ["m_solo"], "is_group": True}]
    parts = [{"id": f"p{i}", "title": f"P{i}", "family_ids": [f"fam_{c}"]}
             for i, c in enumerate("abcde", 1)]
    parts.append({"id": "standalone_methods", "title": "Standalone",
                  "family_ids": ["standalone"]})
    outline = {"parts": parts}
    issues = _validate_parts(outline, families)
    assert not any(i["code"] == "parts_count_out_of_range" for i in issues)


def test_assert_no_singletons_allows_standalone_group_with_one_method():
    from swarn_research_mcp.research_book import assert_no_singletons
    families = [
        {"id": "standalone", "title": "Standalone / Emerging Methods", "method_ids": ["m1"], "is_group": True},
        {"id": "fam_b", "title": "B", "method_ids": ["m2", "m3"]},
    ]
    methods = [{"id": "m1", "arxiv_id": "1.1", "family_id": "standalone"},
               {"id": "m2", "arxiv_id": "1.2", "family_id": "fam_b"},
               {"id": "m3", "arxiv_id": "1.3", "family_id": "fam_b"}]
    assert_no_singletons(_outline(families, methods))  # no raise
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_research_book_singleton_merge.py -v`
Expected: FAIL — `merge_singletons` does not exist.

- [ ] **Step 3: Implement `merge_singletons`**

In `swarn_research_mcp/research_book.py`, add (place after `_method_by_id`, around line 528). `STANDALONE_GROUP_ID` and `STANDALONE_PART_ID` were defined in Task 1.3; do not define a second copy here:

```python
import copy as _copy


def _graph_evidence_score(singleton: dict, candidate: dict, method_by_id: dict) -> int:
    s_method = method_by_id[singleton["method_ids"][0]]
    s_neighbor_methods = set(s_method.get("neighbor_method_ids", []) or [])
    s_neighbor_families = set(singleton.get("neighbor_family_ids", []) or [])
    cand_methods = set(candidate.get("method_ids", []) or [])
    shared = len(s_neighbor_methods & cand_methods)
    if shared >= 2:
        return shared
    if candidate["id"] in s_neighbor_families and shared >= 1:
        return shared
    return 0


def _has_strong_graph_evidence(singleton: dict, candidate: dict, method_by_id: dict) -> bool:
    return _graph_evidence_score(singleton, candidate, method_by_id) > 0


def merge_singletons(outline: dict[str, Any]) -> dict[str, Any]:
    """Stage 12.5 post-processor.

    For each original singleton family:
      - If a non-singleton family has STRONG graph evidence (≥2 shared neighbor methods,
        OR neighbor_family + ≥1 shared method): merge into it.
      - Otherwise: drop the singleton family; the method becomes a member of the
        `standalone` group (a family marked `is_group=True`) under a new
        `standalone_methods` part. No family chapter is rendered for the group.

    Catch-all `other_*` families are NEVER created. The standalone group replaces them.
    """
    out = _copy.deepcopy(outline)
    families: list[dict[str, Any]] = out["families"]
    methods: list[dict[str, Any]] = out["methods"]
    method_by_id = {m["id"]: m for m in methods}
    parts = out.get("parts") or []

    original_singletons = sorted(
        (f for f in families
         if len(f.get("method_ids", [])) == 1
         and f["id"] != STANDALONE_GROUP_ID),
        key=lambda f: f["id"],
    )
    if not original_singletons:
        return out

    for singleton in original_singletons:
        sid = singleton["id"]
        if not any(f["id"] == sid for f in families):
            continue
        s_method_id = singleton["method_ids"][0]

        candidates = [
            f for f in families
            if f["id"] != sid
            and f["id"] != STANDALONE_GROUP_ID
            and len(f.get("method_ids", [])) >= 2
        ]

        # Pick the strongest-evidence candidate; on tie, lexicographically smaller id wins.
        scored_candidates = []
        for cand in candidates:
            score = _graph_evidence_score(singleton, cand, method_by_id)
            if score > 0:
                scored_candidates.append((score, cand["id"], cand))
        winner = None
        if scored_candidates:
            winner = sorted(scored_candidates, key=lambda item: (-item[0], item[1]))[0][2]

        if winner is not None:
            winner["method_ids"] = list(winner["method_ids"]) + [s_method_id]
            method_by_id[s_method_id]["family_id"] = winner["id"]
        else:
            standalone = next((f for f in families if f["id"] == STANDALONE_GROUP_ID), None)
            if standalone is None:
                standalone = {
                    "id": STANDALONE_GROUP_ID,
                    "title": "Standalone / Emerging Methods",
                    "method_ids": [],
                    "neighbor_family_ids": [],
                    "is_group": True,
                }
                families.append(standalone)
                if not any(p["id"] == STANDALONE_PART_ID for p in parts):
                    parts.append({
                        "id": STANDALONE_PART_ID,
                        "title": "Standalone / Emerging Methods",
                        "family_ids": [STANDALONE_GROUP_ID],
                    })
                else:
                    sp = next(p for p in parts if p["id"] == STANDALONE_PART_ID)
                    if STANDALONE_GROUP_ID not in (sp.get("family_ids") or []):
                        sp.setdefault("family_ids", []).append(STANDALONE_GROUP_ID)
            standalone["method_ids"] = list(standalone["method_ids"]) + [s_method_id]
            method_by_id[s_method_id]["family_id"] = STANDALONE_GROUP_ID

        families = [f for f in families if f["id"] != sid]
        for part in parts:
            fids = part.get("family_ids", []) or []
            part["family_ids"] = [fid for fid in fids if fid != sid]

    # Prune any part that ended up empty after singleton removal (except keep
    # standalone_methods even if temporarily empty — pre-existing parts should not vanish silently;
    # the validator's empty_part rule will surface the case if it persists).
    parts = [p for p in parts if (p.get("family_ids") or []) or p.get("id") == STANDALONE_PART_ID]
    out["families"] = families
    out["parts"] = parts
    return out


def assert_no_singletons(outline: dict[str, Any]) -> None:
    """Stage 18 precondition: every family with len(method_ids)==1 must be the standalone group."""
    bad = [f["id"] for f in outline.get("families", [])
           if len(f.get("method_ids", [])) == 1 and f["id"] != STANDALONE_GROUP_ID]
    if bad:
        raise RuntimeError(
            f"outline.json has singleton families {bad}; run --normalize-outline "
            "(stage 12.5) before generate_book_artifacts."
        )
```

- [ ] **Step 4: Add `pytest` import to the test file**

At the top of `tests/test_research_book_singleton_merge.py`, ensure `import pytest` is present (added implicitly by the new tests above).

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_research_book_singleton_merge.py -v`
Expected: PASS (10 tests).

- [ ] **Step 6: Commit**

```bash
git add tests/test_research_book_singleton_merge.py swarn_research_mcp/research_book.py
git commit -m "feat(research-book): merge_singletons + assert_no_singletons (Stage 12.5)"
```

---

## Task 1.4b: Skip `is_group` families from existing validators

Existing validator loops in `validate_research_book_run` check every family for a chapter file under `14_chapters/families/{id}.md` and a corresponding link in `04_method_taxonomy.md`. The standalone group (`is_group: true`) has neither — its methods render flat under `Part: Standalone / Emerging Methods`. The validator must skip groups for these checks.

**Files:**
- Test: `tests/test_research_book_is_group.py` (create)
- Modify: `swarn_research_mcp/research_book.py` — find every check that iterates `families` and reads chapter files or family links

- [ ] **Step 1: Inspect existing checks**

Run: `grep -n "families/{.*}.md\|method_taxonomy_missing_family_link\|missing_family_chapter" swarn_research_mcp/research_book.py`

For each hit inside `validate_research_book_run`, the loop body needs `if family.get("is_group"): continue` as the first line.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_research_book_is_group.py
from __future__ import annotations
import json
from pathlib import Path
from swarn_research_mcp.research_book import validate_research_book_run

BOOK_SECTIONS = [{"id": k, "title": k} for k in
    ["preface", "motivating_intro", "core_concepts", "goals", "method_taxonomy",
     "shared_examples", "evaluation_outlook", "appendices"]]


def _scaffold(tmp_path):
    run = tmp_path / "run"
    for sub in ("12_taxonomy", "07_scoring", "16_book",
                "14_chapters/families", "14_chapters/methods", "14_chapters/book"):
        (run / sub).mkdir(parents=True, exist_ok=True)
    outline = {
        "topic": "t",
        "book_sections": BOOK_SECTIONS,
        "parts": [
            {"id": "p1", "title": "P1", "family_ids": ["fam_real"]},
            {"id": "standalone_methods", "title": "Standalone", "family_ids": ["standalone"]},
        ],
        "families": [
            {"id": "fam_real", "title": "Real Fam", "method_ids": ["m1", "m2"]},
            {"id": "standalone", "title": "Standalone / Emerging Methods",
             "method_ids": ["m_solo"], "is_group": True},
        ],
        "methods": [
            {"id": "m1", "title": "M1", "arxiv_id": "1.1", "family_id": "fam_real"},
            {"id": "m2", "title": "M2", "arxiv_id": "1.2", "family_id": "fam_real"},
            {"id": "m_solo", "title": "Solo", "arxiv_id": "1.3", "family_id": "standalone"},
        ],
    }
    (run / "12_taxonomy" / "outline.json").write_text(json.dumps(outline))
    (run / "07_scoring" / "promoted_papers.json").write_text(json.dumps(
        {"promoted_papers": [{"arxiv_id": "1.1"}, {"arxiv_id": "1.2"}, {"arxiv_id": "1.3"}]}))
    (run / "16_book" / "chapters_manifest.json").write_text(json.dumps(
        {"book": [], "families": ["fam_real"], "methods": ["m1", "m2", "m_solo"]}))
    # Real family chapter exists; standalone has NONE.
    (run / "14_chapters" / "families" / "fam_real.md").write_text(
        "---\nstatus: passed\n---\n# Real Fam\n## Summary\nx\n## Motivation\nx\n## Core Idea\nx\n"
        "## Common Pipeline\nx\n## Main Variants\n| a | b | c | d | e |\n|--|--|--|--|--|\n| 1|2|3|4|5|\n"
        "## Representative Methods\nx\n## Strengths\nx\n## Limitations\nx\n## When to Use\nx\n## Related Families\nx\n")
    # method_taxonomy.md: links real family + lists solo method flat (group has no family link).
    (run / "14_chapters" / "book" / "04_method_taxonomy.md").write_text(
        "# Method Taxonomy\n## Part 1: P1\n- [Real Fam](../families/fam_real.md)\n"
        "  - [M1](../methods/m1.md)\n  - [M2](../methods/m2.md)\n"
        "## Part 2: Standalone\n- [Solo](../methods/m_solo.md)\n")
    return run


def test_is_group_does_not_trigger_missing_family_chapter(tmp_path):
    run = _scaffold(tmp_path)
    issues = validate_research_book_run(run)
    assert not any(i["code"] == "missing_family_chapter" and "standalone" in i["detail"] for i in issues)


def test_is_group_does_not_trigger_missing_family_link(tmp_path):
    run = _scaffold(tmp_path)
    issues = validate_research_book_run(run)
    assert not any(
        i["code"] == "method_taxonomy_missing_family_link" and "standalone" in i["detail"]
        for i in issues
    )


def test_is_group_does_not_trigger_wrong_chapter_headings(tmp_path):
    run = _scaffold(tmp_path)
    issues = validate_research_book_run(run)
    assert not any(
        i["code"] == "wrong_chapter_headings" and "standalone" in i["detail"]
        for i in issues
    )
```

- [ ] **Step 3: Run test**

Run: `pytest tests/test_research_book_is_group.py -v`
Expected: FAIL — existing validator does not special-case groups.

- [ ] **Step 4: Patch `validate_research_book_run`**

For every loop in `validate_research_book_run` that iterates `families` AND inspects chapter file paths or method-taxonomy family links, add as the loop body's first line:

```python
        if family.get("is_group"):
            continue
```

This applies to:
- the loop emitting `missing_family_chapter`
- the loop emitting `method_taxonomy_missing_family_link`
- the heading-lint loop added in Task 3.1
- any future loop that assumes a per-family chapter file

For methods inside an `is_group` family, the existing `method_taxonomy_missing_method_link` check still applies (the method DOES need a flat link in `04_method_taxonomy.md`); do not skip method-level checks.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_research_book_is_group.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add tests/test_research_book_is_group.py swarn_research_mcp/research_book.py
git commit -m "feat(research-book): validators skip is_group families for chapter/link/heading checks"
```

---

## Task 1.5: Stage 12.5 CLI entry point + Stage 18 assertion

Stage 12.5 normalizes `outline.json` ONCE, immediately after Stage 12 emits it and BEFORE Stage 13 builds packs. `generate_book_artifacts` (Stage 18) only ASSERTS — no late mutation.

**Files:**
- Modify: `swarn_research_mcp/research_book.py:651` (`main` CLI), `:638` (`generate_book_artifacts`)
- Modify: `.agents/skills/auto-research-orchestrator/SKILL.md` (Stage 12.5 row in stage table)

- [ ] **Step 1: Add `--normalize-outline` flag to the CLI**

In `main` (around line 651), add to the argparse setup:

```python
    parser.add_argument(
        "--normalize-outline",
        action="store_true",
        help="Stage 12.5: read 12_taxonomy/outline.json, run merge_singletons, write back if changed.",
    )
```

In `main`'s body, BEFORE the `--generate` branch:

```python
    if args.normalize_outline:
        run_path = Path(args.run_dir)
        outline = _outline(run_path)
        normalized = merge_singletons(outline)
        if normalized != outline:
            _write_json(run_path / "12_taxonomy" / "outline.json", normalized)
            print(f"normalized: families {len(outline['families'])} -> {len(normalized['families'])}")
        else:
            print("normalized: no singletons to merge")
        return
```

- [ ] **Step 2: Add the assertion inside `generate_book_artifacts`**

In `generate_book_artifacts`, after `outline = _outline(run_path)` (line 640), add:

```python
    assert_no_singletons(outline)
```

NO mutation. Stage 12.5 is responsible for normalizing.

- [ ] **Step 3: Add tests**

Append to `tests/test_research_book_singleton_merge.py`:

```python
def test_cli_normalize_outline(voice_lm_minimal, capsys, monkeypatch):
    """Stage 12.5 CLI: --normalize-outline merges singletons and rewrites outline.json."""
    from swarn_research_mcp import research_book as rb
    op = voice_lm_minimal / "12_taxonomy" / "outline.json"
    monkeypatch.setattr("sys.argv", ["research_book", str(voice_lm_minimal), "--normalize-outline"])
    rb.main()
    after = json.loads(op.read_text())
    fids = {f["id"] for f in after["families"]}
    assert "fam_codec" not in fids  # singleton fam_codec merged into fam_flow


def test_generate_book_artifacts_asserts_unnormalized_outline(voice_lm_minimal, monkeypatch):
    """generate_book_artifacts MUST refuse to render a non-normalized outline."""
    from swarn_research_mcp import research_book as rb
    op = voice_lm_minimal / "12_taxonomy" / "outline.json"
    outline = json.loads(op.read_text())
    outline["parts"] = [
        {"id": "p1", "title": "P1", "family_ids": ["fam_codec"]},
        {"id": "p2", "title": "P2", "family_ids": ["fam_flow"]},
    ]
    op.write_text(json.dumps(outline))
    with pytest.raises(RuntimeError, match="singleton"):
        rb.generate_book_artifacts(voice_lm_minimal)
```

- [ ] **Step 4: Update orchestrator SKILL stage table — add Stage 12.5**

In `.agents/skills/auto-research-orchestrator/SKILL.md`, find the stage/artifact table. Insert AFTER the Stage 12 row:

```markdown
| 12.5 | `12_taxonomy/outline.json` (normalized — `python -m swarn_research_mcp.research_book {run_dir} --normalize-outline`) |
```

In the same file, document Stage 12.5 in the body:

```markdown
## Stage 12.5 — Normalize outline (deterministic)
After Stage 12 writes `outline.json` and BEFORE Stage 13 builds packs, run:

  `python -m swarn_research_mcp.research_book research_runs/{run_id} --normalize-outline`

This calls `merge_singletons`, which deterministically merges every single-method family into its nearest non-singleton family when strong graph evidence exists; otherwise the method is placed under the `standalone` group in the `standalone_methods` part. Stage 13's pack-building reads the normalized outline; Stage 18's `generate_book_artifacts` asserts the outline is normalized and refuses to render otherwise.
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_research_book_singleton_merge.py -v`
Expected: PASS (12 tests).

- [ ] **Step 6: Commit**

```bash
git add tests/test_research_book_singleton_merge.py swarn_research_mcp/research_book.py .agents/skills/auto-research-orchestrator/SKILL.md
git commit -m "feat(stage-12.5): CLI normalizer + Stage 18 assertion (no late outline mutation)"
```

---

## Task 1.6: Update `taxonomy-building` SKILL.md (parts + singleton notes)

**Files:**
- Modify: `.agents/skills/taxonomy-building/SKILL.md`

- [ ] **Step 1: Add parts section**

In `.agents/skills/taxonomy-building/SKILL.md`, find `## Family clustering` and AFTER its bullet list, insert:

```markdown
## Parts (topic-adaptive grouping)
After clustering, assign every family to exactly one part.

Default labels (Book_style.md): `interpretable`, `local`, `global`, `model_specific`, `evaluation_outlook`. You MAY rename, merge, or drop default parts when the topic fits a different shape.

Hard rules (self-validate):
- 2 ≤ len(parts) ≤ 5
- Every family appears in exactly one part
- Every part contains ≥ 1 family

Emit as `parts: [{id, title, family_ids[]}]` in `outline.json`.

## Singleton handling
If clustering produces a singleton family (`len(method_ids) == 1`), prefer to merge it into the nearest non-singleton family only when shared verified-graph edges provide strong evidence. The deterministic Stage 12.5 post-processor `merge_singletons` in `swarn_research_mcp.research_book` will normalize the outline before Stage 13; if no strong merge evidence exists, the method stays as a standalone method chapter under the `standalone` group. Do not create catch-all `other_*` families.
```

- [ ] **Step 2: Update outline.json schema**

Find the `outline.json schema` JSON block and add `parts` after `book_sections`:
```json
  "parts": [{"id": "interpretable", "title": "Interpretable Methods", "family_ids": ["fam_a"]}],
```

- [ ] **Step 3: Update Hard rules**

Add to `## Hard rules`:
```markdown
- `parts` is present with 2..5 entries; every family belongs to exactly one part.
```

- [ ] **Step 4: Commit**

```bash
git add .agents/skills/taxonomy-building/SKILL.md
git commit -m "docs(taxonomy): document parts + singleton merge contract"
```
