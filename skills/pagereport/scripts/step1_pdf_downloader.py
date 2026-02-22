#!/usr/bin/env python3
"""Step 1 for PDF: download and persist source PDF."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import uuid4

from fetch_with_retry import FetchError, fetch_url


def is_go_jp_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and (host == "go.jp" or host.endswith(".go.jp"))


def is_pdf_content(content_type: str, body: bytes) -> bool:
    if "application/pdf" in content_type:
        return True
    return body.startswith(b"%PDF-")


def make_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid4().hex[:6]
    return f"{ts}_{suffix}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 1 PDF downloader")
    parser.add_argument("--url", required=True, help="Target PDF URL (*.go.jp)")
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
    args = parser.parse_args()

    if not is_go_jp_url(args.url):
        raise SystemExit("URL must be http(s) and in *.go.jp domain")

    try:
        result = fetch_url(args.url)
    except FetchError as exc:
        raise SystemExit(str(exc))

    if not is_pdf_content(result.content_type, result.body):
        raise SystemExit(
            "Fetched content is not PDF. "
            f"content_type={result.content_type!r}, first_bytes={result.body[:8]!r}"
        )

    run_id = args.run_id.strip() or make_run_id()
    out_dir = Path(args.tmp_root) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    source = result.final_url or args.url
    original_filename = Path(unquote(urlparse(source).path)).name or "source.pdf"
    pdf_path = out_dir / "source.pdf"
    metadata_path = out_dir / "metadata.json"

    pdf_path.write_bytes(result.body)

    metadata = {
        "run_id": run_id,
        "tmp_root": str(Path(args.tmp_root)),
        "input_url": args.url,
        "final_url": result.final_url,
        "status_code": result.status_code,
        "content_type": result.content_type,
        "used_browser_headers": result.used_browser_headers,
        "original_filename": original_filename,
        "pdf_path": str(pdf_path),
        "size_bytes": len(result.body),
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    print(str(metadata_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
