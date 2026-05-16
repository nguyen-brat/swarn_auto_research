from __future__ import annotations

import re
from typing import Any

_PUNCT_TRAIL = re.compile(r"[.,;:!?]+$")
_WS = re.compile(r"\s+")


def normalize(s: str) -> str:
    out = s.strip().lower().replace("-", " ")
    out = _WS.sub(" ", out)
    out = _PUNCT_TRAIL.sub("", out)
    return out


def is_known(concept: str, kb: dict[str, Any]) -> bool:
    needle = normalize(concept)
    aliases = kb.get("aliases", {}) or {}
    for key, variants in aliases.items():
        if normalize(key) == needle:
            return True
        for v in variants or []:
            if normalize(v) == needle:
                return True
    return False
