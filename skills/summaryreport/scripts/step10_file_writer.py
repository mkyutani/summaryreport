#!/usr/bin/env python3
"""Step 10: write final markdown report file."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _read_json(path: Path) -> dict[str, Any]:
    raw = _read_text(path)
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(obj, dict):
        return {}
    return obj


def _safe_filename_part(text: str) -> str:
    s = re.sub(r"\s+", "", (text or "").strip())
    s = re.sub(r"[\\/:*?\"<>|]", "_", s)
    s = s.strip("._")
    return s or "report"


def _derive_output_path(step2: dict[str, Any]) -> Path:
    out = str(step2.get("output_report_path", "")).strip()
    if out:
        return Path(out)

    report_title = str(step2.get("report_title", "")).strip()
    if not report_title:
        meeting = str(step2.get("meeting_name", {}).get("value", "")).strip()
        date = str(step2.get("date", {}).get("value", "")).strip()
        base = _safe_filename_part(meeting)
        report_title = f"{base}_{date}" if date else base
    return Path("output") / f"{_safe_filename_part(report_title)}_report.md"


def _build_page_overview(step2: dict[str, Any], step9: dict[str, Any]) -> str:
    page_type = str(step2.get("page_type", "UNKNOWN"))
    meeting_name = str(step2.get("meeting_name", {}).get("value", ""))
    round_text = str(step2.get("round", {}).get("round_text", ""))
    if round_text.lower() in {"none", "null"}:
        round_text = ""
    date_ymd = str(step2.get("date", {}).get("value", ""))
    coverage = str(step9.get("coverage_note", "")).strip()
    url = str(step9.get("source_url", "")).strip() or str(step2.get("url", "")).strip()

    lines: list[str] = []
    if meeting_name:
        title = meeting_name
        if round_text and round_text not in meeting_name:
            title = f"{meeting_name}（{round_text}）"
        lines.append(f"- 対象: {title}")
    if page_type:
        lines.append(f"- 種別: {page_type}")
    if date_ymd:
        lines.append(f"- 日付: {date_ymd}")
    if url:
        lines.append(f"- URL: {url}")
    if coverage:
        lines.append(f"- 概要: {coverage}")
    return "\n".join(lines).strip()


def _build_material_details(step8: dict[str, Any], step2: dict[str, Any]) -> str:
    docs = step8.get("per_document", [])
    if not isinstance(docs, list) or not docs:
        return "（資料サマリーなし）"

    mode = str(step2.get("mode", "")).lower()
    preferred_title = str(step2.get("meeting_name", {}).get("value", "")).strip() or str(
        step2.get("report_title", "")
    ).strip()

    parts: list[str] = []
    for i, d in enumerate(docs, start=1):
        if not isinstance(d, dict):
            continue
        title = str(d.get("title", "")).strip() or f"資料{i}"
        if mode == "pdf" and title.lower() in {"source.pdf", "source"} and preferred_title:
            title = preferred_title
        url = str(d.get("url", "")).strip()
        doc_type = str(d.get("document_type", "")).strip()
        summary = str(d.get("summary", "")).strip()
        points = d.get("key_points", [])
        if not isinstance(points, list):
            points = []

        parts.append(f"### {i}. {title}")
        if url:
            parts.append(f"- URL: {url}")
        if doc_type:
            parts.append(f"- 文書タイプ: {doc_type}")
        if summary:
            parts.append("- 要約:")
            parts.append(summary)
        if points:
            parts.append("- 主要ポイント:")
            for p in points[:8]:
                if not isinstance(p, str) or not p.strip():
                    continue
                parts.append(f"  - {p.strip()}")
        parts.append("")

    return "\n".join(parts).strip()


def _build_report_md(step2: dict[str, Any], step9: dict[str, Any], step8: dict[str, Any]) -> str:
    title = str(step2.get("report_title", "")).strip() or "report"
    abstract = str(step9.get("abstract_ja", "")).strip()
    overall = str(step9.get("overall_summary_ja", "")).strip()
    url = str(step9.get("source_url", "")).strip() or str(step2.get("url", "")).strip()
    page_overview = _build_page_overview(step2, step9)
    details = _build_material_details(step8, step2)

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append("## ページの概要")
    lines.append(page_overview or "（概要情報なし）")
    lines.append("")
    lines.append("## 要約（Abstract）")
    lines.append("```")
    lines.append(abstract)
    if url:
        lines.append(url)
    lines.append("```")
    lines.append("")
    lines.append("## ページの詳細サマリー")
    lines.append(overall or "（詳細サマリーなし）")
    lines.append("")
    lines.append("### 資料別サマリー")
    lines.append(details)
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def _validate_report(md: str, source_url: str) -> dict[str, Any]:
    has_fence = "## 要約（Abstract）" in md and re.search(r"## 要約（Abstract）\n```[\s\S]*?```", md) is not None
    has_url = bool(source_url and source_url in md)
    return {"has_abstract_code_fence": has_fence, "has_source_url_in_report": has_url}


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 10 markdown file writer")
    parser.add_argument("--run-id", required=True, help="Run identifier")
    parser.add_argument("--tmp-root", default="tmp/runs", help="Root directory for per-run artifacts")
    parser.add_argument("--step2-file", default="", help="step2-metadata.json path")
    parser.add_argument("--step8-file", default="", help="step8-material-summaries.json path")
    parser.add_argument("--step9-file", default="", help="step9-summary.json path")
    parser.add_argument("--output-file", default="", help="output report path override")
    args = parser.parse_args()

    run_dir = Path(args.tmp_root) / args.run_id
    step2_path = Path(args.step2_file) if args.step2_file else run_dir / "step2-metadata.json"
    step8_path = Path(args.step8_file) if args.step8_file else run_dir / "step8-material-summaries.json"
    step9_path = Path(args.step9_file) if args.step9_file else run_dir / "step9-summary.json"

    step2 = _read_json(step2_path)
    step8 = _read_json(step8_path)
    step9 = _read_json(step9_path)

    if not step2:
        raise SystemExit(f"step2 file not found or invalid: {step2_path}")
    if not step9:
        raise SystemExit(f"step9 file not found or invalid: {step9_path}")

    out_path = Path(args.output_file) if args.output_file else _derive_output_path(step2)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    md = _build_report_md(step2, step9, step8)
    out_path.write_text(md, encoding="utf-8")

    source_url = str(step9.get("source_url", "")).strip() or str(step2.get("url", "")).strip()
    validation = _validate_report(md, source_url)
    meta = {
        "run_id": args.run_id,
        "output_file": str(out_path),
        "size_bytes": out_path.stat().st_size,
        "validation": validation,
    }
    (run_dir / "step10-output.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
