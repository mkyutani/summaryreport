#!/usr/bin/env python3
"""Step 1 for HTML: fetch page and extract PDF links."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import List
from urllib.parse import urljoin, urlparse
from uuid import uuid4

from docling_client import DEFAULT_DOCLING_ENDPOINT, DoclingError, convert_url_to_markdown
from fetch_with_retry import FetchError, fetch_url


def is_go_jp_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and (host == "go.jp" or host.endswith(".go.jp"))


def decode_html(raw: bytes, content_type: str) -> str:
    charset = "utf-8"
    if "charset=" in content_type:
        charset = content_type.split("charset=", 1)[1].split(";", 1)[0].strip()
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


class PdfLinkExtractor(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "a":
            return
        href = ""
        for key, value in attrs:
            if key.lower() == "href" and value:
                href = value.strip()
                break
        if not href:
            return

        absolute = urljoin(self.base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            return
        lowered = absolute.lower()
        if ".pdf" not in lowered:
            return
        self.links.append(absolute)


def dedupe_keep_order(values: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def make_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid4().hex[:6]
    return f"{ts}_{suffix}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 1 HTML content acquirer")
    parser.add_argument("--url", required=True, help="Target HTML URL (*.go.jp)")
    parser.add_argument(
        "--tmp-root",
        default="tmp/runs",
        help="Root directory for per-run artifacts",
    )
    parser.add_argument(
        "--run-id",
        default="",
        help="Optional run identifier. If omitted, generate time-based run_id.",
    )
    parser.add_argument(
        "--docling-endpoint",
        default=DEFAULT_DOCLING_ENDPOINT,
        help="Docling server endpoint (v1/convert/source). Step 0 must ensure server is running.",
    )
    parser.add_argument(
        "--docling-timeout",
        type=int,
        default=120,
        help="Timeout seconds for Docling request.",
    )
    args = parser.parse_args()

    if not is_go_jp_url(args.url):
        raise SystemExit("URL must be http(s) and in *.go.jp domain")

    try:
        result = fetch_url(args.url)
    except FetchError as exc:
        raise SystemExit(str(exc))

    html_text = decode_html(result.body, result.content_type)
    extractor = PdfLinkExtractor(result.final_url)
    extractor.feed(html_text)
    pdf_links = dedupe_keep_order(extractor.links)

    run_id = args.run_id.strip() or make_run_id()
    out_dir = Path(args.tmp_root) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    html_path = out_dir / "step1-html.html"
    links_path = out_dir / "step1-pdf-links.txt"
    metadata_path = out_dir / "step1-html-metadata.json"
    docling_md_path = out_dir / "step1-docling.md"
    docling_raw_path = out_dir / "step1-docling-response.json"

    html_path.write_text(html_text, encoding="utf-8")
    links_path.write_text("\n".join(pdf_links) + ("\n" if pdf_links else ""), encoding="utf-8")

    metadata = {
        "run_id": run_id,
        "tmp_root": str(Path(args.tmp_root)),
        "input_url": args.url,
        "final_url": result.final_url,
        "status_code": result.status_code,
        "content_type": result.content_type,
        "used_browser_headers": result.used_browser_headers,
        "pdf_link_count": len(pdf_links),
        "html_path": str(html_path),
        "pdf_links_path": str(links_path),
        "docling": {
            "enabled": True,
            "endpoint": args.docling_endpoint,
            "succeeded": False,
        },
    }

    try:
        docling_result = convert_url_to_markdown(
            source_url=result.final_url,
            endpoint=args.docling_endpoint,
            timeout_seconds=args.docling_timeout,
        )
        docling_md_path.write_text(docling_result["markdown"], encoding="utf-8")
        docling_raw_path.write_text(
            json.dumps(docling_result["raw_response"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        metadata["docling"]["succeeded"] = True
        metadata["docling"]["markdown_path"] = str(docling_md_path)
        metadata["docling"]["response_path"] = str(docling_raw_path)
    except DoclingError as exc:
        metadata["docling"]["error"] = str(exc)
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit(f"Docling conversion failed: {exc}")

    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    print(str(metadata_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
