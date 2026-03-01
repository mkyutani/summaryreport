#!/usr/bin/env python3
"""Step 1 for HTML: fetch page and extract PDF links."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import List
from urllib.parse import unquote, urljoin, urlparse
from uuid import uuid4

from docling_client import DEFAULT_DOCLING_ENDPOINT, DoclingError, convert_url_to_markdown
from fetch_with_retry import FetchError, fetch_url


def is_go_jp_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and (host == "go.jp" or host.endswith(".go.jp"))


def _extract_charset_from_content_type(content_type: str) -> str:
    ct = (content_type or "").lower()
    if "charset=" not in ct:
        return ""
    charset = ct.split("charset=", 1)[1].split(";", 1)[0].strip().strip('"').strip("'")
    return charset


def _extract_declared_charset(raw: bytes) -> str:
    # Read only head-ish bytes to avoid expensive decode.
    head = raw[:8192]
    for enc in ("ascii", "latin-1"):
        try:
            text = head.decode(enc, errors="ignore")
            break
        except Exception:
            continue
    else:
        text = ""

    # XML declaration first.
    m = re.search(r"<\?xml[^>]*encoding=['\"]\s*([A-Za-z0-9_\-]+)\s*['\"]", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # <meta charset="...">
    m = re.search(r"<meta[^>]+charset=['\"]?\s*([A-Za-z0-9_\-]+)\s*['\"]?", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # <meta http-equiv="Content-Type" content="text/html; charset=...">
    m = re.search(
        r"<meta[^>]+http-equiv=['\"]content-type['\"][^>]+content=['\"][^'\"]*charset=\s*([A-Za-z0-9_\-]+)",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    return ""


def _canonical_codec_name(name: str) -> str:
    n = (name or "").strip().lower().replace("_", "-")
    mapping = {
        "shift-jis": "cp932",
        "shift_jis": "cp932",
        "sjis": "cp932",
        "ms932": "cp932",
        "x-sjis": "cp932",
        "windows-31j": "cp932",
    }
    return mapping.get(n, n)


def decode_html(raw: bytes, content_type: str) -> tuple[str, str]:
    candidates: list[str] = []

    header_charset = _extract_charset_from_content_type(content_type)
    declared_charset = _extract_declared_charset(raw)
    if header_charset:
        candidates.append(_canonical_codec_name(header_charset))
    if declared_charset:
        candidates.append(_canonical_codec_name(declared_charset))

    # Common fallbacks for JP government pages.
    candidates.extend(["utf-8", "cp932", "shift_jis", "euc_jp", "iso2022_jp"])

    seen = set()
    ordered: list[str] = []
    for c in candidates:
        if not c or c in seen:
            continue
        seen.add(c)
        ordered.append(c)

    for codec in ordered:
        try:
            return raw.decode(codec), codec
        except (LookupError, UnicodeDecodeError):
            continue

    # Last resort.
    try:
        return raw.decode("utf-8", errors="replace"), "utf-8(replace)"
    except Exception:
        return raw.decode(errors="replace"), "unknown(replace)"


class PdfLinkExtractor(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: List[dict[str, str]] = []
        self._current_pdf_href = ""
        self._current_text_parts: List[str] = []

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
        self._current_pdf_href = absolute
        self._current_text_parts = []

    def handle_data(self, data: str) -> None:
        if not self._current_pdf_href:
            return
        txt = _normalize_inline_text(data)
        if txt:
            self._current_text_parts.append(txt)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a":
            return
        if not self._current_pdf_href:
            return
        text = _normalize_inline_text(" ".join(self._current_text_parts))
        self.links.append({"url": self._current_pdf_href, "text": text})
        self._current_pdf_href = ""
        self._current_text_parts = []


def dedupe_keep_order(values: List[dict[str, str]]) -> List[dict[str, str]]:
    seen = set()
    result: List[dict[str, str]] = []
    for value in values:
        url = value.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(value)
    return result


def clean_markdown(md_text: str) -> str:
    """Drop common navigation/breadcrumb/footer noise from markdown."""
    drop_line_patterns = [
        r"^\s*ホーム\s*$",
        r"^\s*トップページ\s*$",
        r"^\s*サイトマップ\s*$",
        r"^\s*お問い合わせ\s*$",
        r"^\s*English\s*$",
        r"^\s*本文へ\s*$",
        r"^\s*パンくず\s*$",
        r"^\s*copyright\b",
    ]
    compiled = [re.compile(pat, re.IGNORECASE) for pat in drop_line_patterns]
    drop_hint_words = [
        "breadcrumb",
        "パンくず",
        "global navi",
        "global navigation",
        "フッター",
        "サイト内検索",
    ]

    lines = md_text.splitlines()
    cleaned: List[str] = []
    for line in lines:
        raw = line.strip()
        if not raw:
            cleaned.append("")
            continue
        lowered = raw.lower()
        if any(p.match(raw) for p in compiled):
            continue
        if any(word in lowered for word in [w.lower() for w in drop_hint_words]):
            continue
        cleaned.append(line)

    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text + ("\n" if text else "")


def extract_html_titles(html_text: str) -> dict[str, str]:
    title = ""
    og_title = ""

    m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    if m:
        title = _normalize_inline_text(m.group(1))

    m = re.search(
        r"""<meta[^>]+(?:property|name)\s*=\s*["']og:title["'][^>]+content\s*=\s*["'](.*?)["'][^>]*>""",
        html_text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        og_title = _normalize_inline_text(m.group(1))

    return {
        "title": title,
        "og_title": og_title,
    }


def _normalize_inline_text(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", "", text)
    cleaned = cleaned.replace("\n", " ").replace("\r", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def render_source_md(cleaned_md: str, titles: dict[str, str]) -> str:
    lines = ["---"]
    lines.append(f'source_title: "{titles.get("title", "").replace("\"", "\\\"")}"')
    lines.append(f'source_og_title: "{titles.get("og_title", "").replace("\"", "\\\"")}"')
    lines.append("---")
    lines.append("")
    lines.append(cleaned_md.rstrip())
    lines.append("")
    return "\n".join(lines)


def render_pdf_links(entries: List[dict[str, str]]) -> str:
    lines: List[str] = []
    for e in entries:
        url = (e.get("url") or "").strip()
        text = _normalize_inline_text(e.get("text", ""))
        if not url:
            continue
        if text:
            safe_text = text.replace("\t", " ")
            lines.append(f"{safe_text}\t{url}")
        else:
            lines.append(url)
    return "\n".join(lines) + ("\n" if lines else "")


def classify_document_category(title: str, filename: str) -> str:
    title_norm = _normalize_inline_text(title)
    title_lower = title_norm.lower()
    filename_lower = filename.lower()

    if any(kw in title_norm for kw in ["議事次第", "次第"]):
        return "agenda"
    if any(kw in title_norm for kw in ["議事録", "議事要旨", "会議録", "議事概要"]):
        return "minutes"
    if any(kw in title_norm for kw in ["委員名簿", "出席者名簿"]):
        return "participants"
    if any(kw in title_norm for kw in ["座席表", "座席配置"]):
        return "seating"
    if any(kw in title_norm for kw in ["公開方法", "傍聴"]):
        return "disclosure_method"
    if any(
        kw in title_norm
        for kw in ["とりまとめ", "取りまとめ", "概要", "Executive Summary", "エグゼクティブサマリー"]
    ):
        return "executive_summary"
    if "参考資料" in title_norm or "参考" in title_norm or "sankou" in filename_lower:
        return "reference"
    if (
        re.match(r"^資料\s*\d+", title_norm)
        or re.match(r"^資料\d+", title_norm)
        or re.match(r"^資料\s*[:：]", title_norm)
        or "説明資料" in title_norm
        or "事務局資料" in title_norm
        or re.search(r"[^\s]+(?:省|府|庁)説明資料", title_norm)
    ):
        return "material"
    if "gijiroku" in filename_lower or "gijiyoshi" in filename_lower or "minutes" in filename_lower:
        return "minutes"
    return "other"


def build_pdf_link_records(entries: List[dict[str, str]]) -> List[dict[str, str]]:
    records: List[dict[str, str]] = []
    for e in entries:
        url = (e.get("url") or "").strip()
        if not url:
            continue
        text = _normalize_inline_text(e.get("text", ""))
        path_name = Path(unquote(urlparse(url).path)).name
        category = classify_document_category(text, path_name)
        records.append(
            {
                "text": text,
                "url": url,
                "filename": path_name,
                "estimated_category": category,
            }
        )
    return records


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

    html_text, detected_encoding = decode_html(result.body, result.content_type)
    extractor = PdfLinkExtractor(result.final_url)
    extractor.feed(html_text)
    pdf_links = dedupe_keep_order(extractor.links)

    run_id = args.run_id.strip() or make_run_id()
    out_dir = Path(args.tmp_root) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    html_path = out_dir / "source.html"
    links_path = out_dir / "pdf-links.txt"
    links_json_path = out_dir / "pdf-links.json"
    metadata_path = out_dir / "metadata.json"
    source_md_path = out_dir / "source.md"
    docling_raw_path = out_dir / "docling-response.json"

    html_path.write_text(html_text, encoding="utf-8")
    pdf_link_records = build_pdf_link_records(pdf_links)
    links_path.write_text(render_pdf_links(pdf_links), encoding="utf-8")
    links_json_path.write_text(json.dumps(pdf_link_records, ensure_ascii=False, indent=2), encoding="utf-8")

    metadata = {
        "run_id": run_id,
        "tmp_root": str(Path(args.tmp_root)),
        "input_url": args.url,
        "final_url": result.final_url,
        "status_code": result.status_code,
        "content_type": result.content_type,
        "detected_encoding": detected_encoding,
        "used_browser_headers": result.used_browser_headers,
        "pdf_link_count": len(pdf_links),
        "source_html_path": str(html_path),
        "pdf_links_path": str(links_path),
        "pdf_links_json_path": str(links_json_path),
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
        cleaned_md = clean_markdown(docling_result["markdown"])
        titles = extract_html_titles(html_text)
        source_md_path.write_text(render_source_md(cleaned_md, titles), encoding="utf-8")
        docling_raw_path.write_text(
            json.dumps(docling_result["raw_response"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        metadata["docling"]["succeeded"] = True
        metadata["docling"]["source_md_path"] = str(source_md_path)
        metadata["docling"]["response_path"] = str(docling_raw_path)
        metadata["source_titles"] = titles
    except DoclingError as exc:
        metadata["docling"]["error"] = str(exc)
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit(f"Docling conversion failed: {exc}")

    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    print(str(metadata_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
