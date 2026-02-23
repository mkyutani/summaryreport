#!/usr/bin/env python3
"""Step 6-8 integrated pipeline: process each PDF through Step6->7->8 in one worker."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import step6_document_pipeline as s6
import step7_conversion_pipeline as s7
import step8_material_summarizer as s8


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _load_step5(run_dir: Path, step5_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    raw = _read_text(step5_path)
    if not raw:
        raise SystemExit(f"step5 file not found or empty: {step5_path}")
    try:
        step5 = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid step5 json: {exc}") from exc

    selected = step5.get("selected_pdfs", []) or []
    downloads = step5.get("downloaded_files", []) or []
    deferred = step5.get("deferred_decisions", []) or []
    if not isinstance(selected, list) or not isinstance(downloads, list) or not isinstance(deferred, list):
        raise SystemExit("invalid step5 json: selected_pdfs/downloaded_files/deferred_decisions must be lists")
    return selected, downloads, deferred


def _build_analyze_targets(selected: list[dict[str, Any]], downloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    url_to_download = {d.get("url", ""): d for d in downloads if d.get("url")}
    analyze_targets: list[dict[str, Any]] = []
    for s in selected:
        u = s.get("url", "")
        merged = dict(s)
        if u in url_to_download:
            merged.update(url_to_download[u])
        analyze_targets.append(merged)
    return analyze_targets


def _resolve_deferred_and_selection(
    run_dir: Path,
    analyze_targets: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    deferred: list[dict[str, Any]],
) -> tuple[dict[str, int | None], list[dict[str, Any]], list[dict[str, Any]]]:
    page_count_by_url: dict[str, int | None] = {}
    for idx, item in enumerate(analyze_targets, start=1):
        u = item.get("url", "")
        if not u:
            continue
        page_count_by_url[u] = s6._page_count_from_item(run_dir, item, idx)

    analysis_for_deferred = {u: {"page_count": p} for u, p in page_count_by_url.items()}
    resolved = s6._resolve_deferred(deferred, analysis_for_deferred)
    final_selected = s6._build_final_selection(selected, resolved)
    return page_count_by_url, resolved, final_selected


def _build_final_targets(final_selected: list[dict[str, Any]], downloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    url_to_download = {d.get("url", ""): d for d in downloads if d.get("url")}
    final_targets: list[dict[str, Any]] = []
    for s in final_selected:
        u = s.get("url", "")
        merged = dict(s)
        if u in url_to_download:
            merged.update(url_to_download[u])
        final_targets.append(merged)
    return final_targets


def _process_one(run_dir: Path, item: dict[str, Any], idx: int) -> dict[str, Any]:
    analysis = s6._analyze_one_pdf(run_dir, item, idx)

    conv_item = dict(item)
    conv_item["document_type"] = analysis.get("document_type", "mixed")
    conv_item["saved_path"] = analysis.get("saved_path", conv_item.get("saved_path", ""))
    converted = s7._convert_one(run_dir, conv_item, idx)

    summary = s8._summarize_one(converted)
    return {"analysis": analysis, "converted": converted, "summary": summary}


def main() -> int:
    parser = argparse.ArgumentParser(description="Integrated Step6-8 pipeline")
    parser.add_argument("--run-id", required=True, help="Run identifier")
    parser.add_argument("--tmp-root", default="tmp/runs", help="Root directory for per-run artifacts")
    parser.add_argument(
        "--step5-file",
        default="",
        help="Step5 result path (default: tmp/runs/<run_id>/step5-material-selection.json)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Parallel workers per PDF (each worker runs Step6->7->8 sequentially)",
    )
    args = parser.parse_args()

    run_dir = Path(args.tmp_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    step5_path = Path(args.step5_file) if args.step5_file else run_dir / "step5-material-selection.json"

    selected, downloads, deferred = _load_step5(run_dir, step5_path)
    analyze_targets = _build_analyze_targets(selected, downloads)
    page_counts, resolved, final_selected = _resolve_deferred_and_selection(
        run_dir, analyze_targets, selected, deferred
    )
    final_targets = _build_final_targets(final_selected, downloads)

    workers = max(1, min(args.max_workers, max(1, len(final_targets))))
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_process_one, run_dir, t, i) for i, t in enumerate(final_targets, start=1)]
        for fut in as_completed(futures):
            rows.append(fut.result())
    rows_sorted = sorted(rows, key=lambda x: x["converted"].get("index", 0))

    analyses = [r["analysis"] for r in rows_sorted]
    converted = [r["converted"] for r in rows_sorted]
    summaries = [r["summary"] for r in rows_sorted]

    step6_payload = {
        "run_id": args.run_id,
        "inputs": {"step5_file": str(step5_path), "max_workers": workers, "mode": "integrated_per_pdf"},
        "deferred_resolution_page_counts": page_counts,
        "per_pdf_analysis": analyses,
        "resolved_deferred_decisions": resolved,
        "final_selected_pdfs": final_selected,
    }
    step7_payload = {
        "run_id": args.run_id,
        "inputs": {"step6_file": str(run_dir / "step6-document-pipeline.json"), "max_workers": workers, "mode": "integrated_per_pdf"},
        "converted_documents": converted,
    }
    step8_payload = {
        "run_id": args.run_id,
        "inputs": {
            "step7_file": str(run_dir / "step7-conversion.json"),
            "max_workers": workers,
            "model": s8.OPENAI_MODEL,
            "mode": "integrated_per_pdf",
        },
        "per_document": sorted(summaries, key=lambda x: x.get("title", "")),
    }

    step6_path = run_dir / "step6-document-pipeline.json"
    step7_path = run_dir / "step7-conversion.json"
    step8_path = run_dir / "step8-material-summaries.json"
    step6_path.write_text(json.dumps(step6_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    step7_path.write_text(json.dumps(step7_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    step8_path.write_text(json.dumps(step8_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    out = {
        "run_id": args.run_id,
        "outputs": {
            "step6": str(step6_path),
            "step7": str(step7_path),
            "step8": str(step8_path),
        },
        "processed_count": len(rows_sorted),
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

