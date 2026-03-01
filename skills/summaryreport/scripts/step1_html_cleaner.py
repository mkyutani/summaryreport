#!/usr/bin/env python3
"""Step 1 substep: clean HTML while preserving core structure."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple
from uuid import uuid4

from bs4 import BeautifulSoup

DROP_TAGS = {
    "header",
    "footer",
    "nav",
    "aside",
    "script",
    "style",
    "noscript",
    "iframe",
    "form",
    "button",
    "svg",
}

DROP_HINTS = [
    "header",
    "footer",
    "breadcrumb",
    "pankuzu",
    "crumb",
    "sidebar",
    "sidemenu",
    "navi",
    "globalnav",
    "ad",
    "ads",
    "banner",
    "related",
    "sns",
    "share",
    "search",
]


def make_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid4().hex[:6]
    return f"{ts}_{suffix}"


def _has_drop_hint(tag) -> bool:
    attrs = []
    if tag.get("id"):
        attrs.append(str(tag.get("id")))
    if tag.get("class"):
        attrs.extend(str(x) for x in tag.get("class"))
    if tag.get("role"):
        attrs.append(str(tag.get("role")))

    text = " ".join(attrs).lower()
    return any(hint in text for hint in DROP_HINTS)


def clean_html(html: str) -> Tuple[str, List[str]]:
    soup = BeautifulSoup(html, "html.parser")
    removed: List[str] = []

    for tag_name in DROP_TAGS:
        for tag in soup.find_all(tag_name):
            removed.append(tag_name)
            tag.decompose()

    for tag in soup.find_all(True):
        if _has_drop_hint(tag):
            removed.append(f"{tag.name}[hint]")
            tag.decompose()

    # Preserve heading/list/table structures but remove empty wrappers.
    block_names = {"div", "section", "article", "main"}
    for tag in soup.find_all(block_names):
        if tag.find(["h1", "h2", "h3", "p", "ul", "ol", "table", "a"]):
            continue
        if not tag.get_text(strip=True):
            removed.append(f"{tag.name}[empty]")
            tag.decompose()

    return str(soup), removed


def extract_text_outline(cleaned_html: str) -> str:
    soup = BeautifulSoup(cleaned_html, "html.parser")
    lines: List[str] = []

    for node in soup.find_all(["h1", "h2", "h3", "li", "p"]):
        text = node.get_text(" ", strip=True)
        if not text:
            continue
        if node.name == "h1":
            lines.append(f"# {text}")
        elif node.name == "h2":
            lines.append(f"## {text}")
        elif node.name == "h3":
            lines.append(f"### {text}")
        elif node.name == "li":
            lines.append(f"- {text}")
        else:
            lines.append(text)

    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 1 HTML cleaner")
    parser.add_argument("--html-file", required=True, help="Input HTML file path")
    parser.add_argument("--tmp-root", default="tmp/runs", help="Root directory for per-run artifacts")
    parser.add_argument("--run-id", default="", help="Optional run identifier")
    args = parser.parse_args()

    html_path = Path(args.html_file)
    if not html_path.exists():
        raise SystemExit(f"Input HTML file not found: {html_path}")

    run_id = args.run_id.strip() or make_run_id()
    out_dir = Path(args.tmp_root) / run_id / "step1" / "clean"
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_html = html_path.read_text(encoding="utf-8", errors="replace")
    cleaned_html, removed = clean_html(raw_html)
    outline_text = extract_text_outline(cleaned_html)

    cleaned_path = out_dir / "cleaned.html"
    outline_path = out_dir / "cleaned-outline.md"
    metadata_path = out_dir / "cleaned-metadata.json"

    cleaned_path.write_text(cleaned_html, encoding="utf-8")
    outline_path.write_text(outline_text, encoding="utf-8")

    metadata = {
        "run_id": run_id,
        "input_html_path": str(html_path),
        "cleaned_html_path": str(cleaned_path),
        "outline_path": str(outline_path),
        "removed_element_count": len(removed),
        "removed_element_samples": removed[:50],
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    print(str(metadata_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
