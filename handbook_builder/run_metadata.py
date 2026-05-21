"""Run metadata helpers for handbook generation."""
from __future__ import annotations

import json
from pathlib import Path


def load_run_topic(run_dir: Path) -> str:
    config_path = run_dir / "run_config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text())
        topic = config.get("topic", "")
        if isinstance(topic, str) and topic.strip():
            return topic.strip()
    topic_path = run_dir / "00_input" / "topic.md"
    if topic_path.exists():
        topic = topic_path.read_text().strip()
        if topic:
            return topic
    return run_dir.name
