"""Deployment helpers for generated handbook sites."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PUBLISH_CONFIG = REPO_ROOT / "swarn_research_mcp/config/handbook_publish_config.json"


@dataclass(frozen=True)
class PublishConfig:
    enabled: bool
    site_url: str
    base_path: str
    source_path: Path | None = None


def resolve_publish_config(config_path: Path | str | None = None) -> PublishConfig:
    """Resolve handbook publish settings from env first, then config file."""
    explicit_enabled = _env_bool(os.environ.get("HANDBOOK_PUBLISH_ENABLED"))
    if explicit_enabled is False:
        return PublishConfig(enabled=False, site_url="", base_path="", source_path=None)

    path = _config_path(config_path)
    file_config = _load_config(path)
    file_enabled = bool(file_config.get("enabled")) if file_config else False
    has_env_target = bool(
        os.environ.get("HANDBOOK_SITE_URL", "").strip()
        or os.environ.get("HANDBOOK_BASE_PATH", "").strip()
    )
    enabled = explicit_enabled is True or has_env_target or file_enabled
    if not enabled:
        return PublishConfig(enabled=False, site_url="", base_path="", source_path=path if path.exists() else None)

    site_url = str(file_config.get("site_url", "")).strip().rstrip("/")
    base_path = normalize_base_path(str(file_config.get("base_path", "")))
    if os.environ.get("HANDBOOK_SITE_URL", "").strip():
        site_url = os.environ["HANDBOOK_SITE_URL"].strip().rstrip("/")
    if os.environ.get("HANDBOOK_BASE_PATH", "").strip():
        base_path = normalize_base_path(os.environ["HANDBOOK_BASE_PATH"])

    return PublishConfig(
        enabled=True,
        site_url=site_url,
        base_path=base_path,
        source_path=path if path.exists() else None,
    )


def site_url_from_env() -> str:
    return resolve_publish_config().site_url


def base_path_from_env() -> str:
    return resolve_publish_config().base_path


def normalize_base_path(value: str) -> str:
    value = value.strip()
    if not value or value == "/":
        return ""
    return "/" + value.strip("/")


def href(path: str, *, base_path: str = "") -> str:
    normalized_base = normalize_base_path(base_path)
    normalized_path = "/" + path.strip("/")
    if path.endswith("/"):
        normalized_path += "/"
    return f"{normalized_base}{normalized_path}"


def _config_path(config_path: Path | str | None) -> Path:
    if config_path is not None:
        return Path(config_path)
    override = os.environ.get("HANDBOOK_PUBLISH_CONFIG", "").strip()
    if override:
        return Path(override)
    return DEFAULT_PUBLISH_CONFIG


def _load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise RuntimeError(f"handbook publish config must be a JSON object: {path}")
    return data


def _env_bool(value: str | None) -> bool | None:
    if value is None or value.strip() == "":
        return None
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"invalid HANDBOOK_PUBLISH_ENABLED value: {value!r}")
