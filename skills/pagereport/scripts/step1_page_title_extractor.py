#!/usr/bin/env python3
"""Step 1 substep: extract page title from cleaned or raw HTML."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List
from uuid import uuid4

from bs4 import BeautifulSoup


def make_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid4().hex[:6]
    return f"{ts}_{suffix}"


def _texts(soup: BeautifulSoup, selector: str) -> List[str]:
    values: List[str] = []
    for node in soup.select(selector):
        text = node.get_text(" ", strip=True)
        if text:
            values.append(text)
    return values


def extract_title(html: str) -> Dict[str, object]:
    soup = BeautifulSoup(html, "html.parser")

    h1_list = _texts(soup, "h1")
    h2_list = _texts(soup, "h2")
    title_text = (soup.title.get_text(" ", strip=True) if soup.title else "")

    if h1_list:
        selected = h1_list[0]
        source = "h1"
    elif title_text:
        selected = title_text
        source = "title"
    elif h2_list:
        selected = h2_list[0]
        source = "h2"
    else:
        selected = ""
        source = "none"

    return {
        "page_title": selected,
        "source": source,
        "candidates": {
            "h1": h1_list[:10],
            "title": title_text,
            "h2": h2_list[:10],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 1 page title extractor")
    parser.add_argument("--html-file", required=True, help="Input HTML file path")
    parser.add_argument("--tmp-root", default="tmp/runs", help="Root directory for per-run artifacts")
    parser.add_argument("--run-id", default="", help="Optional run identifier")
    args = parser.parse_args()

    html_path = Path(args.html_file)
    if not html_path.exists():
        raise SystemExit(f"Input HTML file not found: {html_path}")

    run_id = args.run_id.strip() or make_run_id()
    out_dir = Path(args.tmp_root) / run_id / "step1" / "title"
    out_dir.mkdir(parents=True, exist_ok=True)

    html = html_path.read_text(encoding="utf-8", errors="replace")
    result = extract_title(html)
    result["run_id"] = run_id
    result["input_html_path"] = str(html_path)

    out_path = out_dir / "page-title.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
