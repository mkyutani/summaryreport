#!/usr/bin/env python3
"""Step 7: convert final selected PDFs based on Step6 document type."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib import error, request


HIGH_PRIORITY_KEYWORDS = [
    "背景",
    "現状",
    "課題",
    "問題",
    "方向性",
    "戦略",
    "ロードマップ",
    "施策",
    "取組",
    "予算",
    "スケジュール",
    "目標",
    "kpi",
    "実績",
    "成果",
]

LOW_PRIORITY_KEYWORDS = [
    "表紙",
    "目次",
    "参考",
    "補足",
    "用語集",
    "組織図",
    "名簿",
    "免責",
    "注記",
]

OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("PAGEREPORT_STEP7_MODEL", "gpt-4.1-mini")

def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _run_command(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _call_llm_for_page_scoring(title: str, page_summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    system_prompt = (
        "You are a slide page scorer for Japanese policy documents. "
        "For each page, infer title, content_type, importance_score(1-5), and reason. "
        "Use the provided rubric strictly. Return JSON only."
    )
    rubric = {
        "content_types": ["agenda", "issues", "conclusion", "overview", "detail", "cover_or_other"],
        "scoring": {
            "5": "agenda/table of contents, key issues, conclusion/bones",
            "4": "overview/policy points, major direction/schedule",
            "3": "background/challenges/analysis",
            "2": "detail/supplement/reference/section divider",
            "1": "cover/admin/other",
        },
    }

    payload = {
        "document_title": title,
        "rubric": rubric,
        "pages": page_summaries,
        "output_schema": {
            "pages": [
                {
                    "page": "int",
                    "slide_title": "string",
                    "content_type": "agenda|issues|conclusion|overview|detail|cover_or_other",
                    "importance_score": "1-5 int",
                    "reason": "string",
                }
            ]
        },
    }

    body = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
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
    rows = parsed.get("pages", [])
    if not isinstance(rows, list):
        raise RuntimeError("LLM response format invalid: pages is not a list")
    return rows


def _safe_filename_part(text: str) -> str:
    s = re.sub(r"\s+", " ", (text or "").strip())
    s = s.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    s = re.sub(r"[\x00-\x1f\x7f]", "", s)
    s = re.sub(r"[\\/:*?\"<>|]", "_", s)
    s = s.replace(" ", "_")
    s = re.sub(r"_+", "_", s)
    s = s.strip("._ ")
    if not s:
        s = "pdf"
    if len(s) > 80:
        s = s[:80].rstrip("._ ")
    return s


def _pdftotext_full(pdf_path: Path, out_txt: Path) -> tuple[bool, str]:
    code, _, err = _run_command(["pdftotext", str(pdf_path), str(out_txt)])
    if code != 0:
        return False, err.strip()
    return True, ""


def _extract_important_pages_from_text(full_text: str) -> list[int]:
    pages = full_text.split("\f")
    important: list[int] = []
    for i, page in enumerate(pages, start=1):
        lines = [ln.strip() for ln in page.splitlines() if ln.strip()]
        if not lines:
            continue
        title = " ".join(lines[:2]).lower()

        if any(k.lower() in title for k in LOW_PRIORITY_KEYWORDS):
            continue

        if any(k.lower() in title for k in HIGH_PRIORITY_KEYWORDS):
            important.append(i)
            continue

        if i <= 5:
            important.append(i)

    if not important:
        important = list(range(1, min(6, len(pages) + 1)))
    return sorted(set(important))


def _page_summaries_for_llm(full_text: str) -> list[dict[str, Any]]:
    pages = full_text.split("\f")
    out: list[dict[str, Any]] = []
    for i, page in enumerate(pages, start=1):
        lines = [ln.strip() for ln in page.splitlines() if ln.strip()]
        title = " ".join(lines[:2]) if lines else f"Page {i}"
        excerpt = "\n".join(lines[:10]) if lines else ""
        out.append({"page": i, "title_hint": title[:200], "excerpt": excerpt[:1200]})
    return out


def _important_pages_llm(title: str, full_text: str) -> tuple[list[int], list[dict[str, Any]]]:
    summaries = _page_summaries_for_llm(full_text)
    scored = _call_llm_for_page_scoring(title, summaries)
    important: list[int] = []
    normalized: list[dict[str, Any]] = []
    for row in scored:
        try:
            p = int(row.get("page"))
            score = int(row.get("importance_score"))
        except Exception:
            continue
        normalized.append(
            {
                "page": p,
                "slide_title": str(row.get("slide_title", "")),
                "content_type": str(row.get("content_type", "")),
                "importance_score": score,
                "reason": str(row.get("reason", "")),
            }
        )
        if score >= 4:
            important.append(p)
    if not important:
        important = _extract_important_pages_from_text(full_text)
    return sorted(set(important)), normalized


def _render_markdown_from_pages(full_text: str, important_pages: list[int]) -> str:
    pages = full_text.split("\f")
    out: list[str] = []
    out.append("# 重要ページ抜粋")
    out.append("")
    out.append(f"- 抽出ページ: {', '.join(str(p) for p in important_pages)}")
    out.append("")

    for p in important_pages:
        if p < 1 or p > len(pages):
            continue
        raw = pages[p - 1]
        lines = [ln.rstrip() for ln in raw.splitlines()]
        non_empty = [ln.strip() for ln in lines if ln.strip()]
        title = non_empty[0] if non_empty else f"Page {p}"
        out.append(f"## Page {p}: {title}")
        out.append("")
        cleaned = "\n".join(lines).strip()
        out.append(cleaned)
        out.append("")

    return "\n".join(out).strip() + "\n"


def _convert_one(run_dir: Path, item: dict[str, Any], idx: int) -> dict[str, Any]:
    url = item.get("url", "")
    title = item.get("text", "")
    doc_type = item.get("document_type", "mixed")
    saved_path = Path(str(item.get("saved_path", "")))

    result: dict[str, Any] = {
        "index": idx,
        "url": url,
        "title": title,
        "document_type": doc_type,
        "converted": False,
    }

    if not saved_path.exists():
        result["error"] = f"input pdf not found: {saved_path}"
        return result

    base = _safe_filename_part(title or saved_path.stem)
    txt_path = run_dir / f"step7-{idx:02d}-{base}.txt"
    ok, err = _pdftotext_full(saved_path, txt_path)
    if not ok:
        result["error"] = f"pdftotext failed: {err}"
        return result

    full_text = _read_text(txt_path)
    if not full_text.strip():
        result["error"] = "pdftotext produced empty text"
        return result

    result["pdftotext_path"] = str(txt_path)
    result["pdftotext_chars"] = len(full_text)

    if doc_type == "powerpoint_like":
        llm_scoring: list[dict[str, Any]] = []
        llm_used = False
        llm_error = ""
        try:
            important_pages, llm_scoring = _important_pages_llm(title, full_text)
            llm_used = True
        except Exception as exc:
            important_pages = _extract_important_pages_from_text(full_text)
            llm_error = str(exc)
        md_path = run_dir / f"step7-{idx:02d}-{base}.md"
        md = _render_markdown_from_pages(full_text, important_pages)
        md_path.write_text(md, encoding="utf-8")
        result.update(
            {
                "converted": True,
                "conversion_strategy": "ppt_important_pages_markdown",
                "output_format": "markdown",
                "output_path": str(md_path),
                "processing_details": {
                    "important_pages": important_pages,
                    "important_page_count": len(important_pages),
                    "full_text_path": str(txt_path),
                    "llm_used": llm_used,
                    "llm_error": llm_error,
                    "llm_page_scoring": llm_scoring,
                },
            }
        )
        return result

    # word_like / mixed / other
    result.update(
        {
            "converted": True,
            "conversion_strategy": "pdftotext_fulltext",
            "output_format": "text",
            "output_path": str(txt_path),
            "processing_details": {
                "full_text_path": str(txt_path),
            },
        }
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 7 conversion pipeline")
    parser.add_argument("--run-id", required=True, help="Run identifier")
    parser.add_argument("--tmp-root", default="tmp/runs", help="Root directory for per-run artifacts")
    parser.add_argument(
        "--step6-file",
        default="",
        help="Step6 result path (default: tmp/runs/<run_id>/step6-document-pipeline.json)",
    )
    parser.add_argument(
        "--output-file",
        default="",
        help="Step7 result path (default: tmp/runs/<run_id>/step7-conversion.json)",
    )
    parser.add_argument("--max-workers", type=int, default=4, help="Parallel workers per PDF")
    args = parser.parse_args()

    run_dir = Path(args.tmp_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    step6_path = Path(args.step6_file) if args.step6_file else run_dir / "step6-document-pipeline.json"
    out_path = Path(args.output_file) if args.output_file else run_dir / "step7-conversion.json"

    raw = _read_text(step6_path)
    if not raw:
        raise SystemExit(f"step6 file not found or empty: {step6_path}")
    try:
        step6 = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid step6 json: {exc}") from exc

    final_selected = step6.get("final_selected_pdfs", []) or []
    per_pdf = step6.get("per_pdf_analysis", []) or []
    type_by_url = {x.get("url", ""): x for x in per_pdf if x.get("url")}

    targets: list[dict[str, Any]] = []
    for item in final_selected:
        u = item.get("url", "")
        merged = dict(item)
        analysis = type_by_url.get(u, {})
        if analysis:
            merged["document_type"] = analysis.get("document_type", merged.get("document_type", "mixed"))
            merged["saved_path"] = analysis.get("saved_path", merged.get("saved_path", ""))
        if "saved_path" not in merged or not merged["saved_path"]:
            # fallback by matching step5 selected files is intentionally omitted;
            # Step6 is expected to populate saved_path in per_pdf_analysis.
            merged["saved_path"] = ""
        targets.append(merged)

    workers = max(1, min(args.max_workers, max(1, len(targets))))
    converted: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = []
        for idx, t in enumerate(targets, start=1):
            futures.append(ex.submit(_convert_one, run_dir, t, idx))
        for fut in as_completed(futures):
            converted.append(fut.result())

    converted_sorted = sorted(converted, key=lambda x: x.get("index", 0))
    payload = {
        "run_id": args.run_id,
        "inputs": {
            "step6_file": str(step6_path),
            "max_workers": workers,
        },
        "converted_documents": converted_sorted,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
