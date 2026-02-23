#!/usr/bin/env python3
"""Step 9: generate integrated summary from Step2/Step4/Step8 outputs."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib import error, request

OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("PAGEREPORT_STEP9_MODEL", "gpt-5-mini")


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _read_json(path: Path) -> dict[str, Any]:
    raw = _read_text(path)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _read_json_list(path: Path) -> list[Any]:
    raw = _read_text(path)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return parsed


def _trim_chars(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def _step9_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "abstract_ja": {"type": "string"},
            "overall_summary_ja": {"type": "string"},
            "minutes_note": {"type": ["string", "null"]},
            "coverage_note": {"type": "string"},
        },
        "required": ["abstract_ja", "overall_summary_ja", "minutes_note", "coverage_note"],
    }


def _call_llm(system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    body = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "step9_integrated_summary", "schema": _step9_schema(), "strict": True},
        },
    }

    req = request.Request(
        f"{OPENAI_API_BASE}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=240) as resp:
            raw = resp.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM request failed: {exc.code} {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"LLM request failed: {exc}") from exc

    data = json.loads(raw.decode("utf-8", errors="replace"))
    content = data["choices"][0]["message"]["content"]
    return json.loads(content)


def _normalize_summary_opening(text: str) -> str:
    if not text:
        return text
    normalized = text.strip()
    normalized = re.sub(r"^(本資料|この資料|本書|本報告書|本文書)は[、,\s]*", "", normalized)
    return normalized


def _strip_meta_page_leadin(text: str) -> str:
    if not text:
        return text
    t = text.strip()
    patterns = [
        re.compile(r"^.{0,120}を掲載するページ。"),
        re.compile(r"^.{0,120}をまとめたページ。"),
        re.compile(r"^.{0,120}のページ。"),
    ]
    for pat in patterns:
        m = pat.match(t)
        if m:
            rest = t[m.end() :].lstrip()
            if rest:
                return rest
    return t


def _strip_absence_statements(text: str) -> str:
    if not text:
        return text
    t = text
    patterns = [
        r"[^。]*議事録[^。]*(未公開|公開されていない|未取得|確認できない|ない)[^。]*。",
        r"[^。]*資料[^。]*(未取得|不足|存在しない|ない|確認できない)[^。]*。",
        r"[^。]*逐語的詳細[^。]*(確認できない|不明)[^。]*。",
    ]
    for p in patterns:
        t = re.sub(p, "", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t


def _minutes_note_metadata(page_type: str, minutes_available: bool) -> str:
    if page_type != "MEETING":
        return ""
    if minutes_available:
        return "議事録情報を統合済み。"
    return "議事録は未取得。"


def _build_system_prompt(page_type: str, minutes_available: bool, materials_non_empty: int) -> str:
    common = (
        "You generate an integrated Japanese summary from structured inputs. "
        "Use only provided facts; do not infer unstated details. "
        "Keep abstract_ja within 1500 Japanese characters. "
        "abstract_ja must be one prose paragraph (no bullets, no list numbering, no line breaks). "
        "Do not start abstract_ja with generic lead-ins like '本資料は'. "
        "overall_summary_ja may be longer but keep it concise and factual. "
        "Do not include lack-of-data statements such as missing minutes/materials in abstract_ja or overall_summary_ja."
    )
    if page_type == "MEETING" and (not minutes_available) and materials_non_empty == 0:
        return (
            common
            + " This is a MEETING page with no usable minutes and no material summaries. "
            "Describe only what is explicitly present on the page and its linked document titles. "
            "Do not describe discussion details, opinions, or decisions. "
            "Write in meeting style: start with the meeting name/round and agenda, "
            "not with meta page-description phrases like '...を掲載するページ'."
        )
    if page_type == "REPORT":
        return (
            common
            + " This is a REPORT page. Focus on policy/report content and key points from materials. "
            "Do not describe meeting discussions as if spoken proceedings existed."
        )
    if minutes_available:
        return (
            common
            + " This is a MEETING page with minutes available. "
            "Integrate meeting context, materials, and minutes-derived discussion flow."
        )
    return (
        common
        + " This is a MEETING page but minutes are unavailable. "
        "Summarize only available meeting/material content without mentioning missing minutes."
    )


def _build_user_payload(
    step2: dict[str, Any],
    step4_source: dict[str, Any],
    step4_extract: dict[str, Any],
    minutes_md: str,
    step8: dict[str, Any],
    pdf_links: list[Any],
) -> dict[str, Any]:
    page_type = str(step2.get("page_type", "UNKNOWN"))
    meeting_name = str(step2.get("meeting_name", {}).get("value", ""))
    date_value = str(step2.get("date", {}).get("value", ""))
    round_text = str(step2.get("round", {}).get("round_text", ""))
    source_url = str(step2.get("url", ""))

    minutes_source = step4_source.get("minutes_source", {}) if isinstance(step4_source, dict) else {}
    minutes_succeeded = bool(step4_extract.get("succeeded", False))
    minutes_available = bool(minutes_succeeded and minutes_source.get("type") in {"html", "pdf"})

    docs = step8.get("per_document", []) if isinstance(step8, dict) else []
    if not isinstance(docs, list):
        docs = []

    normalized_docs: list[dict[str, Any]] = []
    for d in docs:
        if not isinstance(d, dict):
            continue
        normalized_docs.append(
            {
                "title": d.get("title", ""),
                "document_type": d.get("document_type", ""),
                "summary": _trim_chars(str(d.get("summary", "")), 2500),
                "key_points": d.get("key_points", [])[:8] if isinstance(d.get("key_points"), list) else [],
                "empty_content": bool(d.get("empty_content", False)),
            }
        )

    linked_documents: list[dict[str, str]] = []
    for item in pdf_links:
        if not isinstance(item, dict):
            continue
        linked_documents.append(
            {
                "title": str(item.get("text", "")),
                "url": str(item.get("url", "")),
            }
        )
        if len(linked_documents) >= 20:
            break

    return {
        "page_type": page_type,
        "meeting_name": meeting_name,
        "date_yyyymmdd": date_value,
        "round_text": round_text,
        "source_url": source_url,
        "minutes": {
            "source_type": minutes_source.get("type", "none"),
            "available": minutes_available,
            "summary_excerpt": _trim_chars(minutes_md, 4000),
        },
        "materials": normalized_docs,
        "linked_documents": linked_documents,
    }


def _extract_page_type(step2: dict[str, Any]) -> str:
    t = str(step2.get("page_type", "UNKNOWN")).upper().strip()
    if t in {"MEETING", "REPORT"}:
        return t
    return "UNKNOWN"


def _generate_with_retry(system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
    first = _call_llm(system_prompt, payload)
    abstract = _normalize_summary_opening(str(first.get("abstract_ja", "")).strip())
    if len(abstract) <= 1500:
        first["abstract_ja"] = abstract
        return first

    retry_prompt = (
        system_prompt
        + " Retry mode: shorten abstract_ja to <=1500 chars while preserving key policy points and decisions."
    )
    second = _call_llm(retry_prompt, payload)
    second["abstract_ja"] = _normalize_summary_opening(str(second.get("abstract_ja", "")).strip())
    if len(second["abstract_ja"]) > 1500:
        second["abstract_ja"] = _trim_chars(second["abstract_ja"], 1500)
    return second


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 9 integrated summary generator")
    parser.add_argument("--run-id", required=True, help="Run identifier")
    parser.add_argument("--tmp-root", default="tmp/runs", help="Root directory for per-run artifacts")
    parser.add_argument("--step2-file", default="", help="Step2 json path")
    parser.add_argument("--minutes-source-file", default="", help="minutes-source.json path")
    parser.add_argument("--minutes-extraction-file", default="", help="minutes-extraction.json path")
    parser.add_argument("--minutes-md-file", default="", help="minutes markdown path")
    parser.add_argument("--step8-file", default="", help="step8-material-summaries.json path")
    parser.add_argument("--pdf-links-file", default="", help="pdf-links.json path")
    parser.add_argument("--output-file", default="", help="Step9 output path")
    args = parser.parse_args()

    run_dir = Path(args.tmp_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    step2_path = Path(args.step2_file) if args.step2_file else run_dir / "step2-metadata.json"
    minutes_source_path = Path(args.minutes_source_file) if args.minutes_source_file else run_dir / "minutes-source.json"
    minutes_extract_path = (
        Path(args.minutes_extraction_file) if args.minutes_extraction_file else run_dir / "minutes-extraction.json"
    )
    minutes_md_path = Path(args.minutes_md_file) if args.minutes_md_file else run_dir / "minutes.md"
    step8_path = Path(args.step8_file) if args.step8_file else run_dir / "step8-material-summaries.json"
    pdf_links_path = Path(args.pdf_links_file) if args.pdf_links_file else run_dir / "pdf-links.json"
    out_path = Path(args.output_file) if args.output_file else run_dir / "step9-summary.json"

    step2 = _read_json(step2_path)
    step4_source = _read_json(minutes_source_path)
    step4_extract = _read_json(minutes_extract_path)
    step8 = _read_json(step8_path)
    pdf_links = _read_json_list(pdf_links_path)
    minutes_md = _read_text(minutes_md_path)

    if not step2:
        raise SystemExit(f"step2 file not found or invalid: {step2_path}")
    if not step8:
        raise SystemExit(f"step8 file not found or invalid: {step8_path}")

    page_type = _extract_page_type(step2)
    minutes_source = step4_source.get("minutes_source", {}) if isinstance(step4_source, dict) else {}
    minutes_available = bool(step4_extract.get("succeeded", False) and minutes_source.get("type") in {"html", "pdf"})

    materials = step8.get("per_document", [])
    materials_count = len(materials) if isinstance(materials, list) else 0
    materials_non_empty = 0
    if isinstance(materials, list):
        materials_non_empty = len([d for d in materials if isinstance(d, dict) and not d.get("empty_content", False)])

    system_prompt = _build_system_prompt(page_type, minutes_available, materials_non_empty)
    user_payload = _build_user_payload(step2, step4_source, step4_extract, minutes_md, step8, pdf_links)
    generated = _generate_with_retry(system_prompt, user_payload)

    abstract = _normalize_summary_opening(str(generated.get("abstract_ja", "")).strip())
    abstract = _strip_meta_page_leadin(abstract)
    overall = str(generated.get("overall_summary_ja", "")).strip()
    abstract = _strip_absence_statements(abstract)
    overall = _strip_absence_statements(overall)
    auto_minutes_note = _minutes_note_metadata(page_type, minutes_available)

    payload = {
        "run_id": args.run_id,
        "inputs": {
            "step2_file": str(step2_path),
            "minutes_source_file": str(minutes_source_path),
            "minutes_extraction_file": str(minutes_extract_path),
            "minutes_md_file": str(minutes_md_path),
            "step8_file": str(step8_path),
            "pdf_links_file": str(pdf_links_path),
            "model": OPENAI_MODEL,
        },
        "page_type": page_type,
        "source_url": step2.get("url", ""),
        "minutes_used": minutes_available,
        "minutes_note": generated.get("minutes_note") or auto_minutes_note or None,
        "coverage_note": generated.get("coverage_note", ""),
        "materials_coverage": {
            "total_documents": materials_count,
            "non_empty_documents": materials_non_empty,
        },
        "abstract_ja": _trim_chars(abstract, 1500),
        "overall_summary_ja": overall,
    }

    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
