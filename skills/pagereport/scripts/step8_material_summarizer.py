#!/usr/bin/env python3
"""Step 8: LLM-based per-document summarization for Step9 input."""

from __future__ import annotations

import argparse
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional
from urllib import error, request

OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("PAGEREPORT_STEP8_MODEL", "gpt-5-mini")

HIGH_PRIORITY_KWS = ["概要", "要旨", "サマリー", "エグゼクティブ", "まとめ", "結論", "今後の方針", "重点", "ポイント"]
MEDIUM_PRIORITY_KWS = ["背景", "目的", "経緯", "課題", "現状"]
LOW_PRIORITY_KWS = ["参考", "補足", "附属", "詳細データ", "免責", "注記"]


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _count_lines(text: str) -> int:
    if not text:
        return 0
    return len(text.splitlines())


def _trim_chars(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-max_chars // 2 :]
    return f"{head}\n\n[...TRUNCATED...]\n\n{tail}"


def _keyword_hit(line: str, keywords: list[str]) -> bool:
    return any(k in line for k in keywords)


def _collect_windows(lines: list[str], hit_indices: list[int], before: int, after: int) -> list[tuple[int, int]]:
    if not hit_indices:
        return []
    intervals: list[tuple[int, int]] = []
    for idx in hit_indices:
        start = max(0, idx - before)
        end = min(len(lines), idx + after + 1)
        intervals.append((start, end))
    intervals.sort()
    merged: list[tuple[int, int]] = []
    cur_s, cur_e = intervals[0]
    for s, e in intervals[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            merged.append((cur_s, cur_e))
            cur_s, cur_e = s, e
    merged.append((cur_s, cur_e))
    return merged


def _extract_text_by_strategy(doc_type: str, output_format: str, text: str) -> tuple[str, str, list[dict[str, Any]]]:
    lines = text.splitlines()
    line_count = len(lines)
    used_sections: list[dict[str, Any]] = []

    if output_format == "markdown" and doc_type == "powerpoint_like":
        strategy = "ppt_selected_pages_md"
        prepared = _trim_chars(text, 18000)
        used_sections.append({"type": "all_selected_pages_markdown", "line_from": 1, "line_to": line_count})
        return strategy, prepared, used_sections

    # text-based strategy
    if line_count <= 1500:
        strategy = "word_small"
        prepared = text
        used_sections.append({"type": "full_text", "line_from": 1, "line_to": line_count})
        return strategy, _trim_chars(prepared, 22000), used_sections

    # common parts
    first_n = 200 if line_count <= 6000 else 150
    last_n = 120
    head = lines[:first_n]
    tail = lines[-last_n:] if line_count > last_n else []
    used_sections.append({"type": "head", "line_from": 1, "line_to": len(head)})
    if tail:
        used_sections.append({"type": "tail", "line_from": line_count - len(tail) + 1, "line_to": line_count})

    high_hits = [i for i, ln in enumerate(lines) if _keyword_hit(ln, HIGH_PRIORITY_KWS)]
    med_hits = [i for i, ln in enumerate(lines) if _keyword_hit(ln, MEDIUM_PRIORITY_KWS)]
    low_hits = [i for i, ln in enumerate(lines) if _keyword_hit(ln, LOW_PRIORITY_KWS)]

    if line_count <= 6000:
        strategy = "word_medium"
        windows = _collect_windows(lines, high_hits + med_hits, before=8, after=20)
        chunk_lines: list[str] = []
        chunk_lines.extend(head)
        for s, e in windows:
            block = lines[s:e]
            if block:
                used_sections.append({"type": "keyword_window", "line_from": s + 1, "line_to": e})
                chunk_lines.append("")
                chunk_lines.extend(block)
        if tail:
            chunk_lines.append("")
            chunk_lines.extend(tail)
        prepared = "\n".join(chunk_lines)
        return strategy, _trim_chars(prepared, 24000), used_sections

    # very large
    strategy = "word_large" if line_count <= 12000 else "word_xlarge"
    windows = _collect_windows(lines, high_hits, before=6, after=14)
    chunk_lines = []
    chunk_lines.extend(head)
    for s, e in windows:
        block = lines[s:e]
        if block:
            used_sections.append({"type": "high_priority_window", "line_from": s + 1, "line_to": e})
            chunk_lines.append("")
            chunk_lines.extend(block)
    if tail:
        chunk_lines.append("")
        chunk_lines.extend(tail)

    # if low-priority hits are dominant and no high hits, keep only head+tail.
    if not high_hits and len(low_hits) > len(med_hits):
        chunk_lines = head + [""] + tail
        used_sections.append({"type": "low_priority_dominant", "line_from": 1, "line_to": line_count})

    prepared = "\n".join(chunk_lines)
    max_chars = 20000 if strategy == "word_large" else 14000
    return strategy, _trim_chars(prepared, max_chars), used_sections


def _response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "key_points": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 8,
            },
            "empty_content": {"type": "boolean"},
            "empty_reason": {"type": ["string", "null"]},
        },
        "required": ["summary", "key_points", "empty_content", "empty_reason"],
    }


def _normalize_summary_opening(text: str) -> str:
    if not text:
        return text
    normalized = text.strip()
    normalized = re.sub(r"^(本資料|この資料|本書|本報告書|本文書)は[、,\s]*", "", normalized)
    return normalized


def _enforce_summary_max_chars(text: str, max_chars: int = 2000) -> str:
    if not text:
        return text
    t = text.strip()
    if len(t) <= max_chars:
        return t
    # Prefer sentence boundary truncation.
    clipped = t[:max_chars]
    last_period = max(clipped.rfind("。"), clipped.rfind("."), clipped.rfind("．"))
    if last_period >= max_chars // 2:
        return clipped[: last_period + 1]
    return clipped


def _call_llm(doc: dict[str, Any], prepared_text: str) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    system_prompt = (
        "You summarize Japanese policy documents precisely. "
        "Use only provided text, do not infer unstated facts. "
        "If content is effectively empty (cover-only etc.), return empty_content=true. "
        "Write summary in plain Japanese with concrete subject from content. "
        "Do not start summary with generic lead-ins like '本資料は' or 'この資料は'. "
        "At this stage, do not over-compress: keep most major points that appear in key_points. "
        "Target roughly 800-1600 Japanese characters when material is substantial, "
        "and keep summary within 2000 characters."
    )
    user_payload = {
        "document_title": doc.get("title", ""),
        "document_type": doc.get("document_type", ""),
        "read_strategy": doc.get("read_strategy", ""),
        "summary_length_guidance": "2000文字以内。内容が十分ある場合は800-1600文字目安。主要論点はkey_pointsと整合してなるべく含める。",
        "text": prepared_text,
    }
    body = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "step8_material_summary", "schema": _response_schema(), "strict": True},
        },
        "temperature": 0,
    }

    req = request.Request(
        f"{OPENAI_API_BASE}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=180) as resp:
            raw = resp.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM request failed: {exc.code} {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"LLM request failed: {exc}") from exc

    data = json.loads(raw.decode("utf-8", errors="replace"))
    content = data["choices"][0]["message"]["content"]
    return json.loads(content)


def _summarize_one(doc: dict[str, Any]) -> dict[str, Any]:
    output_path = Path(str(doc.get("output_path", "")))
    raw_text = _read_text(output_path)
    if not raw_text:
        return {
            "url": doc.get("url", ""),
            "title": doc.get("title", ""),
            "document_type": doc.get("document_type", ""),
            "read_strategy": "unreadable",
            "used_sections": [],
            "summary": "",
            "key_points": [],
            "empty_content": True,
            "empty_reason": "output file missing or empty",
            "error": "input text missing",
        }

    strategy, prepared, used_sections = _extract_text_by_strategy(
        str(doc.get("document_type", "")),
        str(doc.get("output_format", "")),
        raw_text,
    )

    payload = {
        "url": doc.get("url", ""),
        "title": doc.get("title", ""),
        "document_type": doc.get("document_type", ""),
        "read_strategy": strategy,
        "input_path": str(output_path),
        "input_chars": len(raw_text),
        "prepared_chars": len(prepared),
        "used_sections": used_sections,
        "llm_model": OPENAI_MODEL,
    }

    try:
        llm = _call_llm({**doc, "read_strategy": strategy}, prepared)
        llm["summary"] = _normalize_summary_opening(str(llm.get("summary", "")))
        llm["summary"] = _enforce_summary_max_chars(str(llm.get("summary", "")), max_chars=2000)
        payload.update(llm)
    except Exception as exc:
        payload.update(
            {
                "summary": "",
                "key_points": [],
                "empty_content": True,
                "empty_reason": "llm_error",
                "error": str(exc),
            }
        )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 8 material summarizer")
    parser.add_argument("--run-id", required=True, help="Run identifier")
    parser.add_argument("--tmp-root", default="tmp/runs", help="Root directory for per-run artifacts")
    parser.add_argument(
        "--step7-file",
        default="",
        help="Step7 result path (default: tmp/runs/<run_id>/step7-conversion.json)",
    )
    parser.add_argument(
        "--output-file",
        default="",
        help="Step8 result path (default: tmp/runs/<run_id>/step8-material-summaries.json)",
    )
    parser.add_argument("--max-workers", type=int, default=2, help="Parallel workers for per-doc LLM summaries")
    args = parser.parse_args()

    run_dir = Path(args.tmp_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    step7_path = Path(args.step7_file) if args.step7_file else run_dir / "step7-conversion.json"
    out_path = Path(args.output_file) if args.output_file else run_dir / "step8-material-summaries.json"

    raw = _read_text(step7_path)
    if not raw:
        raise SystemExit(f"step7 file not found or empty: {step7_path}")
    try:
        step7 = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid step7 json: {exc}") from exc

    docs = step7.get("converted_documents", []) or []
    if not isinstance(docs, list):
        raise SystemExit("invalid step7 json: converted_documents must be a list")

    workers = max(1, min(args.max_workers, max(1, len(docs))))
    summarized: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_summarize_one, d) for d in docs]
        for fut in as_completed(futures):
            summarized.append(fut.result())
    summarized_sorted = sorted(summarized, key=lambda x: x.get("title", ""))

    payload = {
        "run_id": args.run_id,
        "inputs": {
            "step7_file": str(step7_path),
            "max_workers": workers,
            "model": OPENAI_MODEL,
        },
        "per_document": summarized_sorted,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
