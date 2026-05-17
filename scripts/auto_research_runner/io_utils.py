from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.auto_research_runner.config import REPO_ROOT


def _load_json(path: Path) -> Any:
    if not path.exists():
        try:
            display_path = path.relative_to(REPO_ROOT)
        except ValueError:
            display_path = path
        raise RuntimeError(f"missing required bootstrap artifact: {display_path}")
    return json.loads(path.read_text())


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp_path.replace(path)


def _load_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        try:
            display_path = path.relative_to(REPO_ROOT)
        except ValueError:
            display_path = path
        raise RuntimeError(f"missing required bootstrap artifact: {display_path}")
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise RuntimeError(f"{path.name} must contain at least one row")
    return rows


def _safe_component(value: str, *, field: str) -> str:
    path = Path(value)
    if path.is_absolute() or len(path.parts) != 1 or value in {"", ".", ".."}:
        raise ValueError(f"unsafe {field}: {value}")
    return value


def _safe_relative_path(value: str, *, field: str) -> Path:
    path = Path(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"unsafe {field}: {value}")
    return path


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def chunked(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]
