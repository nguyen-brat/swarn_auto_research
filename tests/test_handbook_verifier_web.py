from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_verifier_web_skill_exists():
    skill = REPO_ROOT / ".agents/skills/verification-web/SKILL.md"
    assert skill.exists()
    text = skill.read_text()
    assert '"passed"' in text  # top-level passed flag contract
    assert "claims" in text
    assert "rejection_reason" in text
    assert "MUST appear" in text or "must appear" in text


def test_verifier_web_toml_exists():
    toml = REPO_ROOT / ".codex/agents/verifier_web.toml"
    assert toml.exists()
    assert 'name = "verifier_web"' in toml.read_text()


def test_load_verification_result_uses_top_level_passed(tmp_path):
    import json
    from handbook_builder.verify import load_verification_result

    path = tmp_path / "v.json"
    path.write_text(json.dumps({"passed": True, "claims": [], "rejection_reason": None}))
    result = load_verification_result(path)
    assert result.passed is True
    assert result.rejection_reason is None

    path.write_text(json.dumps({
        "passed": False, "claims": [{"text": "x", "status": "unsupported"}],
        "rejection_reason": "x not in source"
    }))
    result = load_verification_result(path)
    assert result.passed is False
    assert "x not in source" in result.rejection_reason


def test_build_verifier_spec():
    from handbook_builder.verify import build_verifier_spec
    from pathlib import Path

    spec = build_verifier_spec(
        Path("/tmp/run-1"),
        kind="tldr",
        target_id="maskgct",
        original_path="14_chapters/methods/maskgct.md",
        candidate_path="19_handbook/.augment/methods/maskgct.json",
    )
    assert spec.shard_id == "verify-tldr-maskgct"
    assert spec.agent == "verifier_web"
