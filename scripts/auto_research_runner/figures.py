from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import quote, urlparse

import requests


METHOD_IMAGE_KEYWORDS = {
    "architecture",
    "framework",
    "workflow",
    "pipeline",
    "algorithm",
    "method",
    "model",
    "system",
    "overview",
    "training",
    "inference",
    "procedure",
}
PLOT_ONLY_KEYWORDS = {"accuracy", "curve", "curves", "benchmark", "metric", "score", "results"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
DOWNLOAD_TIMEOUT = (3.0, 10.0)


def _safe_arxiv_component(arxiv_id: str) -> str:
    return quote(str(arxiv_id), safe="").replace("%", "pct")


def _image_ext_from_url(url: str, content_type: str = "") -> str | None:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return ".jpg" if suffix == ".jpeg" else suffix
    content_type = content_type.split(";", 1)[0].strip().lower()
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/gif": ".gif",
        "image/svg+xml": ".svg",
        "image/webp": ".webp",
    }
    return mapping.get(content_type)


def _is_allowed_image_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.netloc:
        return False
    suffix = Path(parsed.path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return True
    host = parsed.netloc.lower()
    return host.endswith("arxiv.org") or host.endswith("ar5iv.labs.arxiv.org")


def _score_caption(caption: str, *, index: int) -> int:
    text = caption.lower()
    tokens = set(re.findall(r"[a-z0-9]+", text))
    score = sum(4 for keyword in METHOD_IMAGE_KEYWORDS if keyword in tokens)
    if re.search(r"\bfigure\s+(1|2)\b", text):
        score += 5
    if "overview" in text or "overall" in text:
        score += 3
    if score == 0 and tokens & PLOT_ONLY_KEYWORDS:
        score -= 5
    if tokens & PLOT_ONLY_KEYWORDS and not (tokens & METHOD_IMAGE_KEYWORDS):
        score -= 2
    score -= min(index, 10)
    return score


def _clean_caption(caption: str) -> str:
    caption = re.sub(r"\s+", " ", caption).strip()
    caption = caption.replace("[", "(").replace("]", ")")
    return caption[:500]


def parse_figure_candidates(
    markdown: str,
    *,
    arxiv_id: str,
    markdown_relpath: str,
) -> list[dict]:
    lines = markdown.splitlines()
    candidates: list[dict] = []
    seen_urls: set[str] = set()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        markdown_match = re.search(r"!\[([^\]]*)\]\((https?://[^)]+)\)", stripped)
        if markdown_match:
            caption = markdown_match.group(1).strip() or "Paper figure"
            url = markdown_match.group(2).strip()
            if _is_allowed_image_url(url) and url not in seen_urls:
                seen_urls.add(url)
                candidates.append(
                    {
                        "arxiv_id": arxiv_id,
                        "caption": _clean_caption(caption),
                        "source_url": url,
                        "score": _score_caption(caption, index=len(candidates)),
                        "evidence_refs": [f"{markdown_relpath}:{idx + 1}"],
                    }
                )
            continue

        if not stripped.lower().startswith("figure:"):
            continue
        caption = _clean_caption(stripped.removeprefix("Figure:").strip())
        for lookahead in range(idx + 1, min(idx + 6, len(lines))):
            ref_line = lines[lookahead].strip()
            match = re.search(r"Refer to caption:\s*(https?://\S+)", ref_line)
            if not match:
                continue
            url = match.group(1).rstrip(").,;")
            if _is_allowed_image_url(url) and url not in seen_urls:
                seen_urls.add(url)
                candidates.append(
                    {
                        "arxiv_id": arxiv_id,
                        "caption": caption or "Paper figure",
                        "source_url": url,
                        "score": _score_caption(caption, index=len(candidates)),
                        "evidence_refs": [f"{markdown_relpath}:{idx + 1}"],
                    }
                )
            break
    return sorted(candidates, key=lambda item: item["score"], reverse=True)


def _download_candidate(run_dir: Path, candidate: dict) -> dict | None:
    url = candidate["source_url"]
    try:
        response = requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT)
        response.raise_for_status()
    except Exception:
        return None
    content_length = response.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_IMAGE_BYTES:
                return None
        except ValueError:
            return None
    content_type = response.headers.get("content-type", "")
    ext = _image_ext_from_url(url, content_type)
    if ext is None:
        return None
    data = bytearray()
    for chunk in response.iter_content(chunk_size=8192):
        if not chunk:
            continue
        data.extend(chunk)
        if len(data) > MAX_IMAGE_BYTES:
            return None
    if not data:
        return None
    digest = hashlib.sha256(data).hexdigest()[:16]
    arxiv_component = _safe_arxiv_component(candidate["arxiv_id"])
    cache_path = Path("13_chapter_packs") / "assets" / "paper_figures" / arxiv_component / f"{digest}{ext}"
    output_path = run_dir / cache_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not output_path.exists():
        output_path.write_bytes(bytes(data))
    public_path = Path("paper_figures") / arxiv_component / f"{digest}{ext}"
    caption = candidate["caption"]
    markdown_image = f"![{caption}](/{public_path.as_posix()})"
    return {
        "arxiv_id": candidate["arxiv_id"],
        "caption": caption,
        "source_url": url,
        "cache_path": cache_path.as_posix(),
        "public_path": public_path.as_posix(),
        "markdown_image": markdown_image,
        "score": candidate["score"],
        "evidence_refs": candidate["evidence_refs"],
    }


def select_visual_assets_for_arxiv_ids(
    run_dir: Path,
    arxiv_ids: list[str],
    *,
    limit: int = 1,
) -> list[dict]:
    candidates: list[dict] = []
    for arxiv_id in arxiv_ids:
        markdown_path = run_dir / "08_full_markdown" / f"{arxiv_id}.md"
        if not markdown_path.exists():
            continue
        candidates.extend(
            parse_figure_candidates(
                markdown_path.read_text(encoding="utf-8", errors="ignore"),
                arxiv_id=arxiv_id,
                markdown_relpath=f"08_full_markdown/{arxiv_id}.md",
            )
        )
    assets: list[dict] = []
    for candidate in sorted(candidates, key=lambda item: item["score"], reverse=True):
        asset = _download_candidate(run_dir, candidate)
        if asset is None:
            continue
        assets.append(asset)
        if len(assets) >= limit:
            break
    return assets
