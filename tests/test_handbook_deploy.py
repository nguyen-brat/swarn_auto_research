import json


def test_resolve_publish_config_reads_enabled_file(tmp_path, monkeypatch):
    from handbook_builder.deploy import resolve_publish_config

    config_path = tmp_path / "publish.json"
    config_path.write_text(json.dumps({
        "enabled": True,
        "site_url": "https://example.github.io/",
        "base_path": "project-site",
    }))
    monkeypatch.setenv("HANDBOOK_PUBLISH_CONFIG", str(config_path))
    monkeypatch.delenv("HANDBOOK_PUBLISH_ENABLED", raising=False)
    monkeypatch.delenv("HANDBOOK_SITE_URL", raising=False)
    monkeypatch.delenv("HANDBOOK_BASE_PATH", raising=False)

    config = resolve_publish_config()

    assert config.enabled is True
    assert config.site_url == "https://example.github.io"
    assert config.base_path == "/project-site"
    assert config.source_path == config_path


def test_resolve_publish_config_disable_env_restores_local_root(tmp_path, monkeypatch):
    from handbook_builder.deploy import resolve_publish_config

    config_path = tmp_path / "publish.json"
    config_path.write_text(json.dumps({
        "enabled": True,
        "site_url": "https://example.github.io",
        "base_path": "/project-site",
    }))
    monkeypatch.setenv("HANDBOOK_PUBLISH_CONFIG", str(config_path))
    monkeypatch.setenv("HANDBOOK_PUBLISH_ENABLED", "0")
    monkeypatch.setenv("HANDBOOK_SITE_URL", "https://override.github.io")
    monkeypatch.setenv("HANDBOOK_BASE_PATH", "/override")

    config = resolve_publish_config()

    assert config.enabled is False
    assert config.site_url == ""
    assert config.base_path == ""


def test_resolve_publish_config_env_overrides_file(tmp_path, monkeypatch):
    from handbook_builder.deploy import resolve_publish_config

    config_path = tmp_path / "publish.json"
    config_path.write_text(json.dumps({
        "enabled": True,
        "site_url": "https://file.github.io",
        "base_path": "/file-base",
    }))
    monkeypatch.setenv("HANDBOOK_PUBLISH_CONFIG", str(config_path))
    monkeypatch.delenv("HANDBOOK_PUBLISH_ENABLED", raising=False)
    monkeypatch.setenv("HANDBOOK_SITE_URL", "https://env.github.io/")
    monkeypatch.setenv("HANDBOOK_BASE_PATH", "env-base")

    config = resolve_publish_config()

    assert config.enabled is True
    assert config.site_url == "https://env.github.io"
    assert config.base_path == "/env-base"
