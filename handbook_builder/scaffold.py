"""Apply the curator's scaffold JSON to a run's 19_handbook/ directory."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from handbook_builder.frontmatter import ensure_head_default
from handbook_builder import linker, site_templates
from handbook_builder.deploy import PublishConfig, resolve_publish_config
from handbook_builder.run_metadata import load_run_topic

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = REPO_ROOT / "handbook_builder/templates"
CONTENT_CONFIG = """import { defineCollection } from 'astro:content';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

export const collections = {
  docs: defineCollection({ loader: docsLoader(), schema: docsSchema() }),
};
"""


def apply_scaffold(run_dir: Path, *, publish_config: PublishConfig | None = None) -> None:
    """Read curator_output.json and write the scaffold files."""
    publish_config = publish_config or resolve_publish_config()
    handbook_dir = run_dir / "19_handbook"
    payload_path = handbook_dir / ".scaffold" / "curator_output.json"
    payload = json.loads(payload_path.read_text())
    manifest = _manifest_items(run_dir)
    sidebar_src = _sidebar_source(run_dir)
    sidebar_items = linker.build_starlight_sidebar(sidebar_src)
    topic = load_run_topic(run_dir)
    site_title = professional_site_title(topic, run_id=run_dir.name)
    site_url = publish_config.site_url
    base_path = publish_config.base_path

    _write_text(
        handbook_dir / "astro.config.mjs",
        site_templates.astro_config(
            title=site_title,
            sidebar_items=sidebar_items,
            site_url=site_url,
            base_path=base_path,
        ),
    )
    _write_text(handbook_dir / "src/styles/custom.css", site_templates.custom_css())
    _write_text(
        handbook_dir / "package.json",
        json.dumps(site_templates.package_json(run_dir.name), indent=2) + "\n",
    )
    _write_text(
        handbook_dir / "src/content/docs/index.mdx",
        ensure_head_default(
            site_templates.home_page(
                title=site_title,
                run_id=run_dir.name,
                book_count=sum(1 for item in manifest if _chapter_type(item) == "book"),
                family_count=sum(1 for item in manifest if _chapter_type(item) == "families"),
                method_count=sum(1 for item in manifest if _chapter_type(item) == "methods"),
                base_path=base_path,
            )
        ),
    )
    _write_text(
        handbook_dir / ".scaffold/sidebar.json",
        json.dumps(payload["sidebar_items"], indent=2),
    )
    _write_text(handbook_dir / "src/content.config.ts", CONTENT_CONFIG)
    _write_text(handbook_dir / "public/.nojekyll", "")

    components_dst = handbook_dir / "src/components"
    components_dst.mkdir(parents=True, exist_ok=True)
    for component in (TEMPLATES_DIR / "components").iterdir():
        shutil.copy2(component, components_dst / component.name)


def professional_site_title(topic: str, *, run_id: str) -> str:
    """Create a stable public title without exposing raw prompt phrasing."""
    source = topic.strip() or run_id
    source = re.sub(r"[-_]+", " ", source)
    source = re.sub(r"\b20\d{6}(?: \d{6})?\b", " ", source)
    source = re.sub(r"\b(?:i want to|please|for me|my)\b", " ", source, flags=re.IGNORECASE)
    source = re.sub(r"\bthat can\b", " ", source, flags=re.IGNORECASE)
    source = re.sub(r"\bworking process(?:es)?\b", "workflow", source, flags=re.IGNORECASE)
    source = re.sub(r"\bAI agent systems? in coding\b", "AI coding agents", source, flags=re.IGNORECASE)
    source = re.sub(r"\baccelerate\s+workflow\b", "accelerated workflows", source, flags=re.IGNORECASE)
    source = re.sub(
        r"\b(AI coding agents)\s+accelerated workflows\b",
        r"\1 for accelerated workflows",
        source,
        flags=re.IGNORECASE,
    )
    source = re.sub(r"\s+", " ", source).strip(" -_:")
    title = _professional_title_case(source or run_id)
    return f"Research Handbook: {title}"


def _professional_title_case(text: str) -> str:
    acronyms = {
        "ai": "AI",
        "api": "API",
        "apis": "APIs",
        "asr": "ASR",
        "llm": "LLM",
        "llms": "LLMs",
        "nlp": "NLP",
        "tts": "TTS",
    }
    small_words = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "via", "with"}
    words = []
    raw_words = text.split()
    for index, word in enumerate(raw_words):
        pieces = word.split("-")
        cased_pieces = []
        for piece in pieces:
            key = piece.casefold()
            if key in acronyms:
                cased_pieces.append(acronyms[key])
            elif index > 0 and key in small_words:
                cased_pieces.append(key)
            else:
                cased_pieces.append(piece[:1].upper() + piece[1:].lower())
        words.append("-".join(cased_pieces))
    return " ".join(words)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _normalize_astro_config(config: str) -> str:
    """Starlight provides the MDX integration; a separate mdx() entry can break ordering."""
    lines = []
    for line in config.splitlines():
        stripped = line.strip()
        if stripped == "import mdx from '@astrojs/mdx';":
            continue
        if stripped in {"mdx(),", "mdx()"}:
            continue
        lines.append(line)
    normalized = "\n".join(lines)
    normalized = re.sub(r"(?<=\[)\s*mdx\(\),\s*", "", normalized)
    normalized = re.sub(r",\s*mdx\(\)(?=\s*\])", "", normalized)
    if "head:" not in normalized:
        normalized = re.sub(r"(starlight\(\{\s*)", r"\1\n      head: [],\n", normalized, count=1)
    return normalized.rstrip() + "\n"


def _manifest_items(run_dir: Path) -> list[dict]:
    path = run_dir / "16_book" / "chapters_manifest.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        chapters = data.get("chapters")
        if isinstance(chapters, list):
            return chapters
    return []


def _chapter_type(item: dict) -> str | None:
    value = item.get("chapter_type") or item.get("type")
    if value in {"family", "families"}:
        return "families"
    if value in {"method", "methods"}:
        return "methods"
    return value


def _sidebar_source(run_dir: Path) -> dict:
    path = run_dir / "16_book" / "sidebar.json"
    if not path.exists():
        return {"items": []}
    data = json.loads(path.read_text())
    return data if isinstance(data, dict) else {"items": []}
