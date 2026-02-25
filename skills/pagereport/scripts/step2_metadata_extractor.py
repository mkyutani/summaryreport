#!/usr/bin/env python3
"""Step 2: extract metadata from source.md using an LLM."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Optional
from urllib import error, request
from urllib.parse import urlparse

OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("PAGEREPORT_STEP2_MODEL", "gpt-5-mini")


def _read_text(path: Optional[str]) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def _strip_frontmatter(md_text: str) -> str:
    lines = md_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return md_text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1 :]).lstrip("\n")
    return md_text


def _extract_heading_texts(md_text: str) -> list[str]:
    body = _strip_frontmatter(md_text)
    headings: list[str] = []
    for line in body.splitlines():
        m = re.match(r"^(#{1,3})\s+(.+?)\s*$", line.strip())
        if m:
            headings.append(m.group(2).strip())
    return headings


def _first_non_empty_line(text: str) -> str:
    for line in text.splitlines():
        s = _normalize(line)
        if s:
            return s
    return ""


def _heading_based_page_type(md_text: str) -> Optional[str]:
    headings = _extract_heading_texts(md_text)
    if not headings:
        return None

    meeting_patterns = [
        re.compile(r"第\s*\d+\s*回"),
        re.compile(r"議事録"),
        re.compile(r"議事要旨"),
        re.compile(r"議事概要"),
        re.compile(r"出席者"),
        re.compile(r"委員名簿"),
    ]
    report_patterns = [
        re.compile(r"予算"),
        re.compile(r"概算要求"),
        re.compile(r"基本方針"),
        re.compile(r"とりまとめ"),
        re.compile(r"取りまとめ"),
        re.compile(r"答申"),
    ]

    has_meeting = False
    has_report = False
    for h in headings:
        if any(p.search(h) for p in meeting_patterns):
            has_meeting = True
        if any(p.search(h) for p in report_patterns):
            has_report = True

    if has_meeting and not has_report:
        return "MEETING"
    if has_report and not has_meeting:
        return "REPORT"
    return None


def _normalize(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _safe_title_part(text: str) -> str:
    cleaned = _normalize(text)
    cleaned = re.sub(r"[\\/:*?\"<>|]", "_", cleaned)
    cleaned = re.sub(r"\s+", "", cleaned)
    return cleaned.strip("._")


def _build_report_title(
    meeting_name: Optional[str],
    date_yyyymmdd: Optional[str],
    url: str,
    source_meta: dict[str, str],
) -> str:
    # Naming policy: <title_or_page>_<yyyymmdd>
    # Do not append round_text to avoid duplication.
    title_or_page = _normalize(meeting_name or "")
    if not title_or_page:
        title_or_page = _normalize(source_meta.get("source_og_title", ""))
    if not title_or_page:
        title_or_page = _normalize(source_meta.get("source_title", ""))
    if not title_or_page:
        host = urlparse(url).hostname or "report"
        title_or_page = host.replace(".", "-")

    title_part = _safe_title_part(title_or_page)
    if date_yyyymmdd:
        return f"{title_part}_{date_yyyymmdd}"
    return title_part


def _to_yyyymmdd(date_text: Optional[str]) -> Optional[str]:
    if not date_text:
        return None
    s = _normalize(str(date_text))

    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", s)
    if m:
        return f"{int(m.group(1)):04d}{int(m.group(2)):02d}{int(m.group(3)):02d}"

    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m:
        return s

    m = re.match(r"^令和\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日$", s)
    if m:
        y = 2018 + int(m.group(1))
        return f"{y:04d}{int(m.group(2)):02d}{int(m.group(3)):02d}"

    m = re.match(r"^平成\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日$", s)
    if m:
        y = 1988 + int(m.group(1))
        return f"{y:04d}{int(m.group(2)):02d}{int(m.group(3)):02d}"

    m = re.match(r"^(\d{4})\s*年\s*(\d+)\s*月\s*(\d+)\s*日$", s)
    if m:
        return f"{int(m.group(1)):04d}{int(m.group(2)):02d}{int(m.group(3)):02d}"

    return None


def _extract_date_candidates(md_text: str) -> list[str]:
    candidates: list[str] = []
    seen = set()

    patterns = [
        re.compile(r"令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日"),
        re.compile(r"平成\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日"),
        re.compile(r"\d{4}\s*年\s*\d+\s*月\s*\d+\s*日"),
        re.compile(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"),
    ]
    for pat in patterns:
        for m in pat.finditer(md_text):
            ymd = _to_yyyymmdd(m.group(0))
            if ymd and ymd not in seen:
                seen.add(ymd)
                candidates.append(ymd)
    return candidates


def _resolve_date_yyyymmdd(llm_date: Optional[str], md_text: str) -> tuple[Optional[str], str]:
    llm_ymd = _to_yyyymmdd(llm_date)
    candidates = _extract_date_candidates(md_text)

    if llm_ymd and llm_ymd in candidates:
        return llm_ymd, "llm+validated"
    if llm_ymd and not candidates:
        return llm_ymd, "llm(no_candidates)"
    if candidates:
        return candidates[0], "rule_fallback:first_date_in_source_md"
    return llm_ymd, "llm(unvalidated)"


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "page_type": {
                "type": "string",
                "enum": ["MEETING", "REPORT", "UNKNOWN"],
            },
            "meeting_name": {
                "type": ["string", "null"],
            },
            "date_iso": {
                "type": ["string", "null"],
                "description": "Date when available. Prefer page-subject date.",
            },
            "round_number": {
                "type": ["integer", "null"],
            },
            "round_text": {
                "type": ["string", "null"],
            },
            "reasoning_brief": {
                "type": "string",
            },
        },
        "required": [
            "page_type",
            "meeting_name",
            "date_iso",
            "round_number",
            "round_text",
            "reasoning_brief",
        ],
    }


def _call_llm(
    md_text: str,
    url: str,
    pdf_count: int,
    source_meta: dict[str, str],
    mode: str,
    first_page_text: str,
) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    first_h1 = ""
    for line in md_text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            first_h1 = s[2:].strip()
            break

    system_prompt = (
        "You are a precise metadata extractor for Japanese government pages and documents. "
        "Extract only what is supported by the provided content. "
        "Follow these strict rules in priority order:\\n"
        "1) For HTML mode, meeting_name: use first level-1 markdown heading ('# ...') as primary source. "
        "Only return null when no reliable candidate exists.\\n"
        "2) For PDF mode, meeting_name: prioritize first_page_text (page 1 text) over filename/URL. "
        "Use formal document/report name appearing on page 1. Do not use filename-derived guesses.\\n"
        "3) date_iso: choose the date representing the page/document subject itself, not historical reference lists.\\n"
        "4) round_number/round_text: extract only when clearly tied to the page/document subject. "
        "Ignore unrelated counters unless clearly the subject.\\n"
        "5) If uncertain, use null."
    )

    user_payload = {
        "mode": mode,
        "url": url,
        "pdf_count": pdf_count,
        "first_h1": first_h1,
        "first_page_text": first_page_text[:6000],
        "source_meta": source_meta,
        "source_markdown": md_text,
    }

    body = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "pagereport_step2_metadata",
                "schema": _schema(),
                "strict": True,
            },
        },
    }

    req = request.Request(
        f"{OPENAI_API_BASE}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM request failed: {exc.code} {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"LLM request failed: {exc}") from exc

    data = json.loads(raw.decode("utf-8", errors="replace"))
    content = data["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 2 metadata extractor (LLM)")
    parser.add_argument("--run-id", required=True, help="Run identifier")
    parser.add_argument("--url", required=True, help="Source URL")
    parser.add_argument("--mode", choices=["html", "pdf"], default="html")
    parser.add_argument("--tmp-root", default="tmp/runs", help="Root directory for per-run artifacts")
    parser.add_argument("--md-file", default="", help="source.md path")
    parser.add_argument("--pdf-links-file", default="", help="pdf-links.txt path")
    parser.add_argument("--first-page-file", default="", help="first-page.txt path (PDF mode)")
    args = parser.parse_args()

    out_dir = Path(args.tmp_root) / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "step2-metadata.json"

    md_path = args.md_file or str(out_dir / "source.md")
    pdf_links_path = args.pdf_links_file or str(out_dir / "pdf-links.txt")
    first_page_path = args.first_page_file or str(out_dir / "first-page.txt")

    source_md = _read_text(md_path)
    first_page_text = _read_text(first_page_path)
    if args.mode == "pdf" and not source_md and first_page_text:
        source_md = f"# PDF Source\n\n{first_page_text}\n"
    if not source_md:
        raise SystemExit(f"source markdown not found or empty: {md_path}")

    pdf_links_text = _read_text(pdf_links_path)
    pdf_count = len([ln for ln in pdf_links_text.splitlines() if _normalize(ln)])

    source_meta: dict[str, str] = {}
    lines = source_md.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            line = lines[i].strip()
            if line == "---":
                break
            if ":" in line:
                k, v = line.split(":", 1)
                source_meta[k.strip()] = v.strip().strip('"').strip("'")

    llm_data = _call_llm(source_md, args.url, pdf_count, source_meta, args.mode, first_page_text)
    heading_page_type = _heading_based_page_type(source_md)
    final_page_type = heading_page_type or llm_data.get("page_type", "UNKNOWN")
    if args.mode == "pdf" and final_page_type == "UNKNOWN":
        final_page_type = "REPORT"

    meeting_name = llm_data.get("meeting_name")
    if args.mode == "pdf" and (not meeting_name):
        meeting_name = _first_non_empty_line(first_page_text) or None
    date_yyyymmdd, date_source = _resolve_date_yyyymmdd(llm_data.get("date_iso"), source_md)
    round_number = llm_data.get("round_number")
    round_text = llm_data.get("round_text")

    report_title = _build_report_title(meeting_name, date_yyyymmdd, args.url, source_meta)

    payload = {
        "run_id": args.run_id,
        "mode": args.mode,
        "url": args.url,
        "page_type": final_page_type,
        "meeting_name": {
            "value": meeting_name,
            "extraction_source": "llm",
        },
        "date": {
            "value": date_yyyymmdd,
            "extraction_source": date_source,
        },
        "round": {
            "value": str(round_number) if round_number is not None else None,
            "extraction_source": "llm",
            "round_number": round_number,
            "round_text": round_text,
        },
        "reasoning_brief": llm_data.get("reasoning_brief", ""),
        "report_title": report_title,
        "output_report_path": f"output/{report_title}_report.md",
        "inputs": {
            "md_file": md_path,
            "pdf_links_file": pdf_links_path,
            "first_page_file": first_page_path,
            "pdf_count": pdf_count,
            "source_meta": source_meta,
            "model": OPENAI_MODEL,
            "heading_page_type": heading_page_type,
            "llm_page_type": llm_data.get("page_type", "UNKNOWN"),
        },
    }

    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
