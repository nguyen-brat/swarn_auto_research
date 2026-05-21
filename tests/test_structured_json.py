from __future__ import annotations

import json

import pytest

from scripts.auto_research_runner.structured_json import loads_structured_json


def test_loads_structured_json_extracts_markdown_fenced_json():
    assert loads_structured_json('```json\n{"claims": []}\n```') == {"claims": []}


def test_loads_structured_json_repairs_invalid_latex_escapes():
    parsed = loads_structured_json(
        '{"latex": "\\\\theta \\\\left(x\\\\right) \\! \\mathcal{L}"}'
    )

    assert parsed["latex"] == "\\theta \\left(x\\right) \\! \\mathcal{L}"


def test_loads_structured_json_rejects_unclosed_objects():
    with pytest.raises(json.JSONDecodeError):
        loads_structured_json('{"claims": [{"source_node_id": "s.01"}]')
