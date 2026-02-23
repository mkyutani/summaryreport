#!/usr/bin/env python3
"""Step 4: choose minutes source from source.md and/or PDF links."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse

from docling_client import DEFAULT_DOCLING_ENDPOINT, DoclingError, convert_url_to_markdown

MINUTES_HEADING_PATTERNS = [
    re.compile(r"議事録"),
    re.compile(r"議事要旨"),
    re.compile(r"議事概要"),
    re.compile(r"会議概要"),
]

MINUTES_PDF_KEYWORDS = [
    "gijiroku",
    "gijiyoshi",
    "minutes",
    "議事録",
    "議事要旨",
    "議事概要",
]


def _normalize_digits(text: str) -> str:
    return text.translate(str.maketrans("０１２３４５６７８９", "0123456789"))


def _extract_round_numbers(text: str) -> list[int]:
    s = _normalize_digits(text or "")
    values: list[int] = []
    seen = set()
    patterns = [
        re.compile(r"第\s*([0-9]+)\s*回"),
        re.compile(r"dai[_-]?([0-9]+)", re.IGNORECASE),
    ]
    for pat in patterns:
        for m in pat.finditer(s):
            try:
                n = int(m.group(1))
            except (TypeError, ValueError):
                continue
            if n not in seen:
                seen.add(n)
                values.append(n)
    return values


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _normalize_line(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def _strip_markdown_noise(s: str) -> str:
    # Remove links and comments for rough text-length estimation.
    s = re.sub(r"\[[^\]]*\]\([^)]*\)", "", s)
    s = re.sub(r"<!--.*?-->", "", s)
    return s


def _extract_frontmatter_and_body(md: str) -> tuple[dict[str, str], str]:
    lines = md.splitlines()
    meta: dict[str, str] = {}
    if not lines or lines[0].strip() != "---":
        return meta, md

    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
        if ":" in lines[i]:
            k, v = lines[i].split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")

    if end == -1:
        return meta, md
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return meta, body


def _heading_level_and_title(line: str) -> tuple[int, str] | None:
    m = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
    if not m:
        return None
    return len(m.group(1)), m.group(2).strip()


def _is_minutes_heading(title: str) -> bool:
    t = _normalize_line(title)
    return any(p.search(t) for p in MINUTES_HEADING_PATTERNS)


def _extract_section(lines: list[str], start_idx: int, start_level: int) -> str:
    buf: list[str] = []
    for i in range(start_idx + 1, len(lines)):
        h = _heading_level_and_title(lines[i])
        if h is not None and h[0] <= start_level:
            break
        buf.append(lines[i])
    return "\n".join(buf).strip()


def _find_minutes_in_markdown(md_text: str) -> dict:
    _, body = _extract_frontmatter_and_body(md_text)
    lines = body.splitlines()

    candidates: list[dict] = []
    for idx, line in enumerate(lines):
        parsed = _heading_level_and_title(line)
        if parsed is None:
            continue
        level, title = parsed
        if not _is_minutes_heading(title):
            continue
        section = _extract_section(lines, idx, level)
        section_for_count = _strip_markdown_noise(section)
        text_len = len(re.sub(r"\s+", "", section_for_count))
        candidates.append(
            {
                "start_index": idx,
                "anchor": title,
                "heading_level": level,
                "section_text_length": text_len,
                "section_preview": _normalize_line(section_for_count)[:160],
                "section_body": section,
            }
        )

    if not candidates:
        return {
            "found": False,
            "reason": "no minutes-like heading found in source.md",
            "candidates": [],
        }

    best = sorted(
        candidates,
        key=lambda c: (c["section_text_length"], -c["heading_level"]),
        reverse=True,
    )[0]

    # Treat as usable when section has enough substance.
    if best["section_text_length"] < 80:
        return {
            "found": False,
            "reason": "minutes-like heading exists but section content is too short",
            "candidates": candidates,
        }

    return {
        "found": True,
        "reason": "minutes section found in markdown body",
        "selected": best,
        "candidates": candidates,
    }


def _score_minutes_pdf_url(url: str) -> int:
    parsed = urlparse(url)
    target = f"{parsed.path} {parsed.query}"
    target = unquote(target)
    lowered = target.lower()
    score = 0
    for kw in MINUTES_PDF_KEYWORDS:
        kw_l = kw.lower()
        if kw_l in lowered:
            score += 3
    basename = Path(parsed.path).name.lower()
    if basename.endswith(".pdf"):
        score += 1
    return score


def _parse_pdf_link_line(line: str) -> dict[str, str] | None:
    raw = line.strip()
    if not raw:
        return None
    if "\t" in raw:
        text, url = raw.split("\t", 1)
        return {"text": _normalize_line(text), "url": _normalize_line(url)}
    return {"text": "", "url": raw}


def _parse_pdf_links_from_source_md(md_text: str, base_url: str) -> list[dict[str, str]]:
    _, body = _extract_frontmatter_and_body(md_text)
    results: list[dict[str, str]] = []
    # Markdown link pattern: [text](url)
    for m in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", body):
        text = _normalize_line(m.group(1))
        href = _normalize_line(m.group(2))
        if ".pdf" not in href.lower():
            continue
        abs_url = urljoin(base_url, href)
        if urlparse(abs_url).scheme not in {"http", "https"}:
            continue
        results.append({"text": text, "url": abs_url})
    return results


def _score_minutes_pdf_entry(entry: dict[str, str]) -> int:
    score = _score_minutes_pdf_url(entry.get("url", ""))
    text = (entry.get("text") or "").lower()
    for kw in MINUTES_PDF_KEYWORDS:
        if kw.lower() in text:
            score += 5
    return score


def _has_minutes_signal(entry: dict[str, str]) -> bool:
    text = (entry.get("text") or "").lower()
    url = (entry.get("url") or "").lower()
    return any(kw.lower() in text or kw.lower() in url for kw in MINUTES_PDF_KEYWORDS)


def _contains_minutes_keyword(text: str) -> bool:
    t = (text or "").lower()
    return any(kw.lower() in t for kw in MINUTES_PDF_KEYWORDS)


def _prefer_new_text(old_text: str, new_text: str) -> bool:
    old_t = old_text or ""
    new_t = new_text or ""
    if not new_t:
        return False
    if not old_t:
        return True
    # Prefer non-mojibake text.
    if "�" in old_t and "�" not in new_t:
        return True
    # Prefer text with minutes-like keywords.
    if _contains_minutes_keyword(new_t) and not _contains_minutes_keyword(old_t):
        return True
    return False


def _find_minutes_pdf(
    pdf_links_text: str,
    md_text: str,
    base_url: str,
    expected_round: Optional[int] = None,
) -> dict:
    entries = []
    for ln in pdf_links_text.splitlines():
        parsed = _parse_pdf_link_line(ln)
        if parsed and parsed.get("url"):
            entries.append(parsed)
    # Enrich with source.md markdown links (text is often cleaner than raw HTML parse).
    entries.extend(_parse_pdf_links_from_source_md(md_text, base_url))

    if not entries:
        return {
            "found": False,
            "reason": "no pdf links found in pdf-links.txt and source.md",
            "candidates": [],
        }

    dedup: dict[str, dict[str, str]] = {}
    for e in entries:
        u = e.get("url", "")
        if not u:
            continue
        if u not in dedup:
            dedup[u] = {"url": u, "text": e.get("text", "")}
        else:
            if _prefer_new_text(dedup[u].get("text", ""), e.get("text", "")):
                dedup[u]["text"] = e.get("text", "")

    scored = []
    for e in dedup.values():
        text = e.get("text", "")
        url = e.get("url", "")
        url_basename = Path(urlparse(url).path).name
        rounds_in_entry = _extract_round_numbers(f"{text} {url_basename}")
        round_mismatch = bool(
            expected_round is not None
            and rounds_in_entry
            and expected_round not in rounds_in_entry
        )
        score = _score_minutes_pdf_entry(e)
        if round_mismatch:
            score -= 100
        scored.append(
            {
                "text": text,
                "url": url,
                "score": score,
                "has_minutes_signal": _has_minutes_signal(e),
                "rounds_in_entry": rounds_in_entry,
                "round_mismatch": round_mismatch,
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    eligible = [c for c in scored if c.get("has_minutes_signal", False) and not c.get("round_mismatch", False)]
    if not eligible:
        return {
            "found": False,
            "reason": "no minutes-like PDF matched the page round",
            "expected_round": expected_round,
            "candidates": scored,
        }
    best = eligible[0]
    if not best.get("has_minutes_signal", False):
        return {
            "found": False,
            "reason": "no minutes-like keyword in PDF link text/URLs",
            "expected_round": expected_round,
            "candidates": scored,
        }

    return {
        "found": True,
        "reason": "minutes-like keyword matched in PDF URL",
        "expected_round": expected_round,
        "selected": best,
        "candidates": scored,
    }


def _extract_expected_round(md_text: str, metadata_text: str, base_url: str) -> Optional[int]:
    frontmatter, _ = _extract_frontmatter_and_body(md_text)
    probes: list[str] = [
        frontmatter.get("source_title", ""),
        frontmatter.get("source_og_title", ""),
        base_url,
    ]
    if metadata_text:
        try:
            meta = json.loads(metadata_text)
            if isinstance(meta, dict):
                probes.extend(
                    [
                        str(meta.get("title", "")),
                        str(meta.get("final_url", "")),
                        str(meta.get("input_url", "")),
                    ]
                )
        except json.JSONDecodeError:
            pass

    for p in probes:
        rounds = _extract_round_numbers(p)
        if rounds:
            return rounds[0]
    return None


def _build_output(
    run_id: str,
    md_path: Path,
    pdf_links_path: Path,
    html_result: dict,
    pdf_result: dict,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()

    if html_result.get("found"):
        sel = html_result.get("selected", {})
        minutes_source = {
            "type": "html",
            "path": str(md_path),
            "anchor": sel.get("anchor"),
            "reason": html_result.get("reason"),
            "section_text_length": sel.get("section_text_length"),
        }
    elif pdf_result.get("found"):
        sel = pdf_result.get("selected", {})
        minutes_source = {
            "type": "pdf",
            "url": sel.get("url"),
            "reason": pdf_result.get("reason"),
            "score": sel.get("score"),
        }
    else:
        minutes_source = {
            "type": "none",
            "reason": "no minutes content in html and no minutes-like pdf link",
        }

    return {
        "run_id": run_id,
        "generated_at": now,
        "inputs": {
            "md_file": str(md_path),
            "pdf_links_file": str(pdf_links_path),
        },
        "minutes_source": minutes_source,
        "checks": {
            "html": html_result,
            "pdf": pdf_result,
        },
    }


def _extract_minutes_to_markdown(
    payload: dict,
    out_dir: Path,
    docling_endpoint: str,
    docling_timeout: int,
) -> dict:
    source = payload.get("minutes_source", {})
    source_type = source.get("type")
    out_md_path = out_dir / "minutes.md"
    out_meta_path = out_dir / "minutes-extraction.json"
    out_docling_raw_path = out_dir / "minutes-docling-response.json"

    result = {
        "succeeded": False,
        "source_type": source_type,
        "minutes_md_path": str(out_md_path),
    }

    if source_type == "html":
        checks = payload.get("checks", {})
        html_sel = (checks.get("html", {}) or {}).get("selected", {}) or {}
        anchor = html_sel.get("anchor") or "議事録"
        section = (html_sel.get("section_body") or "").strip()
        if not section:
            result["error"] = "selected html minutes section was empty"
        else:
            text = f"# {anchor}\n\n{section.strip()}\n"
            out_md_path.write_text(text, encoding="utf-8")
            result["succeeded"] = True
            result["line_count"] = len(text.splitlines())

    elif source_type == "pdf":
        url = source.get("url", "")
        if not url:
            result["error"] = "selected pdf url is empty"
        else:
            try:
                doc = convert_url_to_markdown(
                    source_url=url,
                    endpoint=docling_endpoint,
                    timeout_seconds=docling_timeout,
                )
                md = (doc.get("markdown") or "").strip()
                if not md:
                    result["error"] = "docling returned empty markdown for minutes pdf"
                else:
                    out_md_path.write_text(md + "\n", encoding="utf-8")
                    out_docling_raw_path.write_text(
                        json.dumps(doc.get("raw_response"), ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    result["succeeded"] = True
                    result["line_count"] = len(md.splitlines())
                    result["docling_response_path"] = str(out_docling_raw_path)
            except DoclingError as exc:
                result["error"] = f"docling conversion failed: {exc}"

    else:
        result["error"] = "minutes source type is none; nothing to extract"

    out_meta_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["metadata_path"] = str(out_meta_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 4 minutes referencer")
    parser.add_argument("--run-id", required=True, help="Run identifier")
    parser.add_argument("--tmp-root", default="tmp/runs", help="Root directory for per-run artifacts")
    parser.add_argument("--md-file", default="", help="source.md path")
    parser.add_argument("--pdf-links-file", default="", help="pdf-links.txt path")
    parser.add_argument("--metadata-file", default="", help="metadata.json path")
    parser.add_argument("--output-file", default="", help="minutes-source.json path")
    parser.add_argument(
        "--docling-endpoint",
        default=DEFAULT_DOCLING_ENDPOINT,
        help="Docling server endpoint (v1/convert/source)",
    )
    parser.add_argument(
        "--docling-timeout",
        type=int,
        default=120,
        help="Timeout seconds for Docling request.",
    )
    args = parser.parse_args()

    out_dir = Path(args.tmp_root) / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    md_path = Path(args.md_file) if args.md_file else out_dir / "source.md"
    pdf_links_path = Path(args.pdf_links_file) if args.pdf_links_file else out_dir / "pdf-links.txt"
    metadata_path = Path(args.metadata_file) if args.metadata_file else out_dir / "metadata.json"
    out_path = Path(args.output_file) if args.output_file else out_dir / "minutes-source.json"

    md_text = _read_text(md_path)
    pdf_links_text = _read_text(pdf_links_path)
    metadata_text = _read_text(metadata_path)

    if not md_text:
        raise SystemExit(f"source markdown not found or empty: {md_path}")
    base_url = ""
    if metadata_text:
        try:
            meta = json.loads(metadata_text)
            base_url = _normalize_line(str(meta.get("final_url") or meta.get("input_url") or ""))
        except json.JSONDecodeError:
            base_url = ""

    expected_round = _extract_expected_round(md_text, metadata_text, base_url)
    html_result = _find_minutes_in_markdown(md_text)
    pdf_result = _find_minutes_pdf(pdf_links_text, md_text, base_url, expected_round=expected_round)
    # Remove heavy inline section body from non-selected candidates before writing.
    for c in html_result.get("candidates", []):
        if "section_body" in c:
            c["section_body"] = c["section_body"][:1000]
    payload = _build_output(args.run_id, md_path, pdf_links_path, html_result, pdf_result)
    extraction = _extract_minutes_to_markdown(
        payload=payload,
        out_dir=out_dir,
        docling_endpoint=args.docling_endpoint,
        docling_timeout=args.docling_timeout,
    )
    payload["minutes_extraction"] = extraction

    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
