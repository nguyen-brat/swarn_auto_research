#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


SECTION_ORDER = [
    "Summary",
    "Motivation",
    "Intuition",
    "Theory",
    "Algorithm",
    "Example",
    "Interpretation",
    "Strengths",
    "Limitations",
    "Software",
    "Related Methods",
]

ARTIFACT_PATTERNS = [
    "PyTorch",
    "Transformers",
    "FlashAttention",
    "FlashAttention-2",
    "Flash-Decoding",
    "FlashInfer",
    "Triton",
    "CUDA graphs",
    "CUDA",
    "vLLM",
    "Hugging Face",
    "DeepSpeed-Zero-Inference",
    "StreamingLLM",
]


def load_json(path: Path):
    with path.open() as f:
        return json.load(f)


def cite(arxiv_id: str, node_id: str) -> str:
    return f"[arxiv:{arxiv_id}, {node_id}]"


def normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("Figure:") or line.startswith("Refer to caption:"):
            continue
        if line.startswith("**Table"):
            continue
        if line.startswith("|"):
            continue
        if re.match(r"^#+\s", line):
            continue
        if re.match(r"^[A-Z][A-Za-z0-9 .:/()-]{0,80}$", line) and len(line.split()) <= 10:
            continue
        line = re.sub(r"\(\^\d+\^\d+.*?\)", "", line)
        lines.append(line)
    text = " ".join(lines)
    text = re.sub(r"^\s*Abstract\s+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_sentences(text: str):
    text = normalize_text(text)
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def sentence_text(source_node: dict):
    return split_sentences(source_node.get("section_text", ""))


def section_map(pack: dict):
    return {entry["section_title"]: entry for entry in pack.get("section_plan", [])}


def take_sentences(nodes, target_count, min_len=25):
    picked = []
    seen = set()
    for node in nodes:
        for sentence in sentence_text(node):
            norm = sentence.lower()
            if len(sentence) < min_len or norm in seen:
                continue
            seen.add(norm)
            picked.append((sentence, node))
            if len(picked) >= target_count:
                return picked
    return picked


def paragraph_from_nodes(arxiv_id, nodes, target_count, min_len=25):
    picked = take_sentences(nodes, target_count, min_len=min_len)
    if not picked:
        return ""
    text = " ".join(sentence for sentence, _ in picked)
    cite_ids = []
    for _, node in picked:
        marker = cite(arxiv_id, node["node_id"])
        if marker not in cite_ids:
            cite_ids.append(marker)
    cites = " ".join(cite_ids)
    return f"{text} {cites}".strip()


def intro_from_section(pack: dict, title: str, target_count=4, min_len=25):
    entry = section_map(pack).get(title, {})
    return paragraph_from_nodes(pack["arxiv_id"], entry.get("source_nodes", []), target_count, min_len=min_len)


def select_example_node(pack: dict):
    entry = section_map(pack).get("Example", {})
    nodes = entry.get("source_nodes", [])
    if nodes:
        return nodes[0]
    return None


def build_summary(pack: dict):
    entry = section_map(pack).get("Summary", {})
    nodes = entry.get("source_nodes", [])
    first = paragraph_from_nodes(pack["arxiv_id"], nodes[:1], 5)
    second = paragraph_from_nodes(pack["arxiv_id"], nodes[1:], 3)
    return "\n\n".join([p for p in [first, second] if p])


def build_motivation(pack: dict):
    entry = section_map(pack).get("Motivation", {})
    nodes = entry.get("source_nodes", [])
    first = paragraph_from_nodes(pack["arxiv_id"], nodes[:1], 4)
    second = paragraph_from_nodes(pack["arxiv_id"], nodes[1:], 4)
    return "\n\n".join([p for p in [first, second] if p])


def build_intuition(pack: dict):
    entry = section_map(pack).get("Intuition", {})
    nodes = entry.get("source_nodes", [])
    first = paragraph_from_nodes(pack["arxiv_id"], nodes, 5)
    theory = intro_from_section(pack, "Theory", 2)
    theory = re.sub(r"\[arxiv:[^\]]+\]", "", theory).strip()
    if theory:
        first = f"{first}\n\nRead informally, the design keeps the heavy computation focused on the parts of the sequence or cache that the method treats as most informative, while leaving the rest to cheaper summaries, retrieval, sparsity, or reuse."
    return first.strip()


def build_theory(pack: dict):
    parts = []
    prose = intro_from_section(pack, "Theory", 5)
    if prose:
        parts.append(prose)
    equations = pack.get("structured", {}).get("equations") or []
    for eq in equations:
        parts.append("$$")
        parts.append(eq["latex"])
        parts.append("$$")
        parts.append(
            f"{eq.get('purpose', 'Equation used in the method.')} {cite(pack['arxiv_id'], eq['source_node_id'])}"
        )
    if not equations and not prose:
        parts.append(f"No explicit equations were extracted in the pack; the theory is described operationally in the source sections. {cite(pack['arxiv_id'], section_map(pack)['Summary']['source_nodes'][0]['node_id'])}")
    return "\n\n".join(parts)


def build_algorithm(pack: dict):
    parts = []
    prose = intro_from_section(pack, "Algorithm", 4)
    if prose:
        parts.append(prose)
    algorithms = pack.get("structured", {}).get("algorithms") or []
    for algo in algorithms:
        name = algo.get("name") or "Algorithm"
        parts.append(f"### {name}")
        pseudocode = (algo.get("pseudocode") or "").rstrip()
        if pseudocode:
            parts.append("```text")
            parts.append(pseudocode)
            parts.append("```")
        steps = algo.get("steps") or []
        if steps:
            for idx, step in enumerate(steps, start=1):
                parts.append(f"{idx}. {step}")
        parts.append(cite(pack["arxiv_id"], algo["source_node_id"]))
    if not algorithms:
        entry = section_map(pack).get("Algorithm", {})
        nodes = entry.get("source_nodes", [])
        fallback_steps = take_sentences(nodes, 4, min_len=20)
        if fallback_steps:
            for idx, (sentence, node) in enumerate(fallback_steps[:4], start=1):
                parts.append(f"{idx}. {sentence} {cite(pack['arxiv_id'], node['node_id'])}")
    return "\n\n".join(parts)


def build_example(pack: dict):
    parts = []
    prose = intro_from_section(pack, "Example", 6, min_len=20)
    if prose:
        parts.append(prose)
    hparams = pack.get("structured", {}).get("hyperparameters") or []
    if hparams:
        parts.append("Concrete settings extracted from the pack:")
        for hp in hparams[:10]:
            parts.append(
                f"- `{hp['name']}` = `{hp['value']}`: {hp['purpose']} {cite(pack['arxiv_id'], hp['source_node_id'])}"
            )
    else:
        node = select_example_node(pack)
        if node:
            parts.append(f"The pack does not expose structured hyperparameters beyond the example narrative in this section. {cite(pack['arxiv_id'], node['node_id'])}")
    return "\n\n".join(parts)


def build_interpretation(pack: dict):
    entry = section_map(pack).get("Interpretation", {})
    nodes = entry.get("source_nodes", [])
    first = paragraph_from_nodes(pack["arxiv_id"], nodes, 6, min_len=20)
    if not first:
        complexities = pack.get("structured", {}).get("complexity") or []
        if complexities:
            text = " ".join(item["text"] for item in complexities[:3])
            cites = " ".join(cite(pack["arxiv_id"], item["source_node_id"]) for item in complexities[:3])
            first = f"{text} {cites}"
    return first


def bullets_from_nodes(pack: dict, section_title: str, min_bullets=3, max_bullets=6, keyword_bias=None):
    entry = section_map(pack).get(section_title, {})
    nodes = entry.get("source_nodes", [])
    bullets = []
    seen = set()
    for node in nodes:
        sentences = sentence_text(node)
        for sentence in sentences:
            norm = sentence.lower()
            if len(sentence) < 30 or norm in seen:
                continue
            if sentence.startswith("Table ") or sentence.startswith("Figure "):
                continue
            if keyword_bias and not any(word in norm for word in keyword_bias):
                continue
            seen.add(norm)
            bullets.append(f"- {sentence} {cite(pack['arxiv_id'], node['node_id'])}")
            if len(bullets) >= max_bullets:
                return bullets
    return bullets


def build_strengths(pack: dict):
    bullets = bullets_from_nodes(
        pack,
        "Strengths",
        3,
        6,
        keyword_bias=["improv", "better", "higher", "lower", "speed", "efficient", "robust", "maintain", "outperform"],
    )
    if len(bullets) < 3:
        for hp in (pack.get("structured", {}).get("complexity") or [])[:6]:
            bullets.append(f"- {hp['text']} {cite(pack['arxiv_id'], hp['source_node_id'])}")
            if len(bullets) >= 3:
                break
    return "\n".join(bullets[:6])


def build_limitations(pack: dict):
    bullets = bullets_from_nodes(
        pack,
        "Limitations",
        3,
        6,
        keyword_bias=["limit", "trade", "cost", "depends", "overhead", "fail", "struggle", "heuristic"],
    )
    if len(bullets) < 3:
        fallback_titles = ["Motivation", "Theory", "Interpretation", "Example"]
        for title in fallback_titles:
            entry = section_map(pack).get(title, {})
            for sentence, node in take_sentences(entry.get("source_nodes", []), 8, min_len=30):
                lowered = sentence.lower()
                if any(word in lowered for word in ["struggle", "challenge", "however", "bottleneck", "cost", "latency", "memory", "overhead", "limited", "degrad"]):
                    bullet = f"- {sentence} {cite(pack['arxiv_id'], node['node_id'])}"
                    if bullet not in bullets:
                        bullets.append(bullet)
                if len(bullets) >= 3:
                    break
            if len(bullets) >= 3:
                break
    if len(bullets) < 3:
        for hp in (pack.get("structured", {}).get("complexity") or [])[:6]:
            bullet = f"- {hp['text']} {cite(pack['arxiv_id'], hp['source_node_id'])}"
            if bullet not in bullets:
                bullets.append(bullet)
            if len(bullets) >= 3:
                break
    return "\n".join(bullets[:6])


def extract_artifacts(pack: dict):
    nodes = []
    for title in ["Software", "Summary", "Algorithm", "Example"]:
        nodes.extend(section_map(pack).get(title, {}).get("source_nodes", []))
    artifacts = []
    seen = set()
    for node in nodes:
        text = node.get("section_text", "")
        urls = re.findall(r"https?://[^\s)]+", text)
        for url in urls:
            if url.endswith(".png") or "/x" in url and "arxiv.org/html/" in url:
                continue
            if url not in seen:
                artifacts.append((url, node["node_id"], "Reference implementation or project page"))
                seen.add(url)
        for name in ARTIFACT_PATTERNS:
            if name in text and name not in seen:
                artifacts.append((name, node["node_id"], "Named implementation artifact or runtime"))
                seen.add(name)
    return artifacts


def build_software(pack: dict):
    artifacts = extract_artifacts(pack)
    if not artifacts:
        entry = section_map(pack).get("Software", {})
        node_id = None
        if entry.get("source_nodes"):
            node_id = entry["source_nodes"][0]["node_id"]
        elif section_map(pack).get("Summary", {}).get("source_nodes"):
            node_id = section_map(pack)["Summary"]["source_nodes"][0]["node_id"]
        if node_id:
            return f"no concrete artifacts; use the software section in the pack as the lookup point for implementation notes. {cite(pack['arxiv_id'], node_id)}"
        return "no concrete artifacts"
    lines = []
    for name, node_id, desc in artifacts:
        lines.append(f"- `{name}`: {desc}. {cite(pack['arxiv_id'], node_id)}")
    return "\n".join(lines)


def build_related(pack: dict):
    paragraphs = []
    for neighbor in pack.get("neighbors", []):
        title = neighbor.get("title") or neighbor.get("method_id") or "Related method"
        relation = neighbor.get("diff_summary") or "Listed as a neighboring method in the pack."
        label = title
        if neighbor.get("method_id"):
            label = f"`{neighbor['method_id']}` ({title})"
        paragraphs.append(
            f"{label} is a useful comparison point because {relation} {cite(pack['arxiv_id'], neighbor['source_node_id'])}"
        )
    return "\n\n".join(paragraphs)


def build_method(pack: dict):
    parts = [f"# {pack['method_title']}"]
    builders = {
        "Summary": build_summary,
        "Motivation": build_motivation,
        "Intuition": build_intuition,
        "Theory": build_theory,
        "Algorithm": build_algorithm,
        "Example": build_example,
        "Interpretation": build_interpretation,
        "Strengths": build_strengths,
        "Limitations": build_limitations,
        "Software": build_software,
        "Related Methods": build_related,
    }
    for title in SECTION_ORDER:
        parts.append(f"## {title}")
        body = builders[title](pack).strip()
        parts.append(body if body else "None.")
    chapter = "\n\n".join(parts) + "\n"
    for extra_section in ["Interpretation", "Example", "Motivation"]:
        if len(chapter.split()) >= 1500:
            break
        extra = intro_from_section(pack, extra_section, 8, min_len=20)
        if extra:
            chapter = chapter.rstrip() + "\n\n" + extra + "\n"
    return chapter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("method_ids", nargs="+")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    packs_dir = run_dir / "13_chapter_packs" / "methods"
    out_dir = run_dir / "14_chapters" / "methods"
    out_dir.mkdir(parents=True, exist_ok=True)

    for method_id in args.method_ids:
        pack_path = packs_dir / f"{method_id}_pack.json"
        pack = load_json(pack_path)
        chapter = build_method(pack)
        (out_dir / f"{method_id}.md").write_text(chapter)


if __name__ == "__main__":
    main()
