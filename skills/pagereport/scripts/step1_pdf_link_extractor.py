#!/usr/bin/env python3
"""Step 1 substep: extract PDF links and convert to absolute URLs."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List
from urllib.parse import unquote, urljoin, urlparse
from uuid import uuid4

from bs4 import BeautifulSoup

CATEGORY_RULES = [
    ("agenda", ["議事次第", "次第", "agenda"]),
    ("minutes", ["議事録", "議事要旨", "minutes"]),
    ("material", ["資料", "material"]),
    ("reference", ["参考資料", "参考", "reference"]),
    ("participants", ["委員名簿", "出席者名簿", "participants"]),
]


def make_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid4().hex[:6]
    return f"{ts}_{suffix}"


def _is_pdf_link(absolute_url: str) -> bool:
    parsed = urlparse(absolute_url)
    path = parsed.path.lower()
    if path.endswith(".pdf"):
        return True
    return ".pdf" in path


def _filename_from_url(absolute_url: str) -> str:
    path_name = Path(unquote(urlparse(absolute_url).path)).name
    if path_name.lower().endswith(".pdf"):
        return path_name
    match = re.search(r"([^/?#]+\.pdf)", absolute_url, re.IGNORECASE)
    if match:
        return match.group(1)
    return "unknown.pdf"


def _estimate_category(text: str, filename: str, url: str) -> str:
    target = " ".join([text, filename, url]).lower()
    for category, keywords in CATEGORY_RULES:
        for keyword in keywords:
            if keyword.lower() in target:
                return category
    return "other"


def extract_pdf_links(base_url: str, html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    links: List[Dict[str, str]] = []
    seen_urls = set()

    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href", "")).strip()
        if not href:
            continue

        absolute_url = urljoin(base_url, href)
        if not _is_pdf_link(absolute_url):
            continue
        if absolute_url in seen_urls:
            continue
        seen_urls.add(absolute_url)

        text = anchor.get_text(" ", strip=True)
        filename = _filename_from_url(absolute_url)
        category = _estimate_category(text, filename, absolute_url)

        links.append(
            {
                "text": text,
                "url": absolute_url,
                "filename": filename,
                "estimated_category": category,
            }
        )

    return links


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 1 PDF link extractor")
    parser.add_argument("--base-url", required=True, help="Base URL for absolute URL conversion")
    parser.add_argument("--html-file", required=True, help="Input HTML file path")
    parser.add_argument("--tmp-root", default="tmp/runs", help="Root directory for per-run artifacts")
    parser.add_argument("--run-id", default="", help="Optional run identifier")
    args = parser.parse_args()

    html_path = Path(args.html_file)
    if not html_path.exists():
        raise SystemExit(f"Input HTML file not found: {html_path}")

    run_id = args.run_id.strip() or make_run_id()
    out_dir = Path(args.tmp_root) / run_id / "step1" / "pdf-links"
    out_dir.mkdir(parents=True, exist_ok=True)

    html = html_path.read_text(encoding="utf-8", errors="replace")
    links = extract_pdf_links(args.base_url, html)

    links_path = out_dir / "pdf-links.json"
    metadata_path = out_dir / "pdf-links-metadata.json"

    links_path.write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8")

    metadata = {
        "run_id": run_id,
        "base_url": args.base_url,
        "input_html_path": str(html_path),
        "pdf_link_count": len(links),
        "pdf_links_path": str(links_path),
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    print(str(links_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
