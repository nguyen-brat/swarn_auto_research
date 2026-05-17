from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_JSON_MARKDOWN_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_VALID_JSON_ESCAPES = {'"', "\\", "/", "b", "f", "n", "r", "t", "u"}


def _json_candidates(text: str) -> list[str]:
    stripped = text.strip()
    candidates = [stripped]
    match = _JSON_MARKDOWN_RE.search(stripped)
    if match:
        fenced = match.group(1).strip()
        if fenced and fenced != stripped:
            candidates.append(fenced)
    return candidates


def _escape_invalid_json_backslashes(text: str) -> str:
    chars: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        if not in_string:
            chars.append(char)
            if char == '"':
                in_string = True
            continue
        if escaped:
            if char not in _VALID_JSON_ESCAPES:
                chars.append("\\")
            chars.append(char)
            escaped = False
            continue
        if char == "\\":
            chars.append("\\")
            escaped = True
            continue
        chars.append(char)
        if char == '"':
            in_string = False
    if escaped:
        chars.append("\\")
    return "".join(chars)


def loads_structured_json(text: str) -> Any:
    last_error: json.JSONDecodeError | None = None
    for candidate in _json_candidates(text):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as error:
            last_error = error
        repaired = _escape_invalid_json_backslashes(candidate)
        if repaired != candidate:
            try:
                return json.loads(repaired)
            except json.JSONDecodeError as error:
                last_error = error
    if last_error is not None:
        raise last_error
    raise json.JSONDecodeError("empty JSON content", text, 0)


def load_structured_json_file(path: Path, *, canonicalize: bool = False) -> Any:
    raw = path.read_text(encoding="utf-8")
    parsed = loads_structured_json(raw)
    if canonicalize:
        canonical = json.dumps(parsed, indent=2, sort_keys=True) + "\n"
        if raw != canonical:
            path.write_text(canonical, encoding="utf-8")
    return parsed
