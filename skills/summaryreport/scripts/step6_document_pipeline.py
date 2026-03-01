#!/usr/bin/env python3
"""Step 6: parallel PDF analysis + deferred decision resolution."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _run_command(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _pdf_page_count(pdf_path: Path) -> Optional[int]:
    code, out, _ = _run_command(["pdfinfo", str(pdf_path)])
    if code != 0:
        return None
    m = re.search(r"^Pages:\s+(\d+)", out, re.MULTILINE)
    if not m:
        return None
    return int(m.group(1))


def _extract_first5_text(pdf_path: Path, out_txt: Path) -> tuple[bool, str]:
    code, _, err = _run_command(["pdftotext", "-f", "1", "-l", "5", str(pdf_path), str(out_txt)])
    if code != 0:
        return False, err.strip()
    return True, ""


def _count_topic_lines(text: str) -> int:
    count = 0
    for line in text.splitlines():
        t = line.strip()
        if not t:
            continue
        if len(t) <= 40 and re.search(r"(議題|資料|方針|概要|案|について|に関して|調査|対策|検討)", t):
            count += 1
    return count


def _extract_features(text: str) -> dict[str, Any]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    joined = "\n".join(lines)

    sentence_like_count = len(re.findall(r"[。．.!！?？]\s*$", "\n".join(lines), re.MULTILINE))
    bullet_count = len(re.findall(r"^\s*[●・○◯■□◆◇▶▷➢①②③④⑤⑥⑦⑧⑨⑩]\s*", text, re.MULTILINE))
    bullet_count += len(re.findall(r"^\s*[\-\*]\s+", text, re.MULTILINE))
    # Some PDFs use garbled/non-standard bullet glyphs (e.g., private-use symbols).
    symbol_bullet_count = len(re.findall(r"^\s*[^\wぁ-んァ-ン一-龥A-Za-z0-9]{1,2}\s+", text, re.MULTILINE))
    bullet_count += symbol_bullet_count
    nominal_ending_count = len(
        re.findall(r"(について|に関して|の推進|の強化|の検討|の概要|の方針|の方向性)\s*$", "\n".join(lines), re.MULTILINE)
    )
    paragraph_count = len([p for p in re.split(r"\n\s*\n", text) if p.strip()])
    particle_count = len(re.findall(r"[はがをにでと]", joined))
    polite_style_count = len(re.findall(r"(です|ます)", joined))
    dearu_style_count = len(re.findall(r"(である|だ。)", joined))
    citation_count = len(re.findall(r"(によれば|によると|として|示す)", joined))
    reference_expr_count = len(re.findall(r"(下図|次の表|以下|上記|図\d|表\d)", joined))
    short_line_count = len([ln for ln in lines if len(ln) <= 24])
    short_line_ratio = (short_line_count / len(lines)) if lines else 0.0
    topic_lines = _count_topic_lines(text)
    page_number_line_count = len(re.findall(r"^\s*\d{1,3}\s*$", text, re.MULTILINE))
    sentence_density = (sentence_like_count / len(lines)) if lines else 0.0

    return {
        "line_count": len(lines),
        "sentence_like_count": sentence_like_count,
        "sentence_density": round(sentence_density, 4),
        "bullet_count": bullet_count,
        "symbol_bullet_count": symbol_bullet_count,
        "nominal_ending_count": nominal_ending_count,
        "topic_line_count": topic_lines,
        "paragraph_count": paragraph_count,
        "particle_count": particle_count,
        "polite_style_count": polite_style_count,
        "dearu_style_count": dearu_style_count,
        "citation_count": citation_count,
        "reference_expr_count": reference_expr_count,
        "page_number_line_count": page_number_line_count,
        "short_line_ratio": round(short_line_ratio, 4),
    }


def _classify_document_type(title: str, first5_text: str, features: dict[str, Any]) -> tuple[str, str]:
    t = (title or "").strip()
    joined = first5_text

    if any(k in t for k in ("委員名簿", "出席者名簿")):
        return "participants_list", "名簿系キーワード"

    if ("議事次第" in t or "次第" in t) and (
        re.search(r"\b\d{1,2}[:：]\d{2}\b", joined) or "配布資料" in joined
    ):
        return "agenda", "議事次第キーワード + 時刻/資料記載"

    if any(k in t for k in ("プレスリリース", "報道発表")):
        return "press_release", "報道系キーワード"

    if any(k in t for k in ("調査結果", "アンケート")):
        return "survey_report", "調査系キーワード"

    word_score = 0
    ppt_score = 0

    word_score += min(features["sentence_like_count"], 8)
    word_score += 2 if features["paragraph_count"] >= 3 else 0
    word_score += 2 if features["particle_count"] >= 20 else 0
    word_score += 1 if (features["polite_style_count"] + features["dearu_style_count"]) >= 3 else 0
    word_score += 1 if features["citation_count"] >= 2 else 0

    ppt_score += min(features["bullet_count"], 8)
    ppt_score += min(features["nominal_ending_count"], 4)
    ppt_score += 2 if features["short_line_ratio"] >= 0.45 else 0
    ppt_score += 2 if features["topic_line_count"] >= 4 else 0
    ppt_score += 1 if features["reference_expr_count"] >= 2 else 0
    ppt_score += 2 if features["page_number_line_count"] >= 2 else 0
    # Slide-like dense layout: many short lines, low sentence density, visible page numbers.
    if (
        features["short_line_ratio"] >= 0.6
        and features["sentence_density"] <= 0.2
        and features["page_number_line_count"] >= 2
    ):
        ppt_score += 4

    if word_score >= ppt_score + 2:
        return "word_like", f"word_score={word_score}, ppt_score={ppt_score}"
    if ppt_score >= word_score + 2:
        return "powerpoint_like", f"ppt_score={ppt_score}, word_score={word_score}"
    return "mixed", f"close_scores word={word_score}, ppt={ppt_score}"


def _analysis_strategy(doc_type: str) -> str:
    if doc_type == "word_like":
        return "longform_summary"
    if doc_type == "powerpoint_like":
        return "slide_bullet_summary"
    if doc_type == "agenda":
        return "agenda_structure_summary"
    if doc_type == "participants_list":
        return "name_list_extract"
    if doc_type == "press_release":
        return "news_style_summary"
    if doc_type == "survey_report":
        return "data_points_summary"
    return "hybrid_summary"


def _analyze_one_pdf(run_dir: Path, item: dict[str, Any], idx: int) -> dict[str, Any]:
    url = item.get("url", "")
    title = item.get("text", "")
    path_str = ""
    downloaded = False
    if isinstance(item.get("downloaded"), bool):
        downloaded = item["downloaded"]
    if item.get("saved_path"):
        path_str = str(item["saved_path"])
    else:
        # Fallback path pattern from step5
        path_str = str(run_dir / f"step5-selected-{idx:02d}-{item.get('text', 'pdf')}.pdf")

    pdf_path = Path(path_str)
    result: dict[str, Any] = {
        "url": url,
        "text": title,
        "saved_path": str(pdf_path),
        "analyzed": False,
    }
    if not downloaded or not pdf_path.exists():
        result["error"] = "pdf file not available for analysis"
        return result

    page_count = _pdf_page_count(pdf_path)
    first5_path = run_dir / f"step6-first5-{idx:02d}.txt"
    ok, err = _extract_first5_text(pdf_path, first5_path)
    if not ok:
        result["error"] = f"pdftotext failed: {err}"
        return result

    text = _read_text(first5_path)
    features = _extract_features(text)
    doc_type, reason = _classify_document_type(title, text, features)
    strategy = _analysis_strategy(doc_type)

    result.update(
        {
            "analyzed": True,
            "page_count": page_count,
            "first5_text_path": str(first5_path),
            "document_type": doc_type,
            "classification_reason": reason,
            "summary_strategy": strategy,
            "features": features,
        }
    )
    return result


def _resolve_pdf_path(run_dir: Path, item: dict[str, Any], idx: int) -> Path:
    if item.get("saved_path"):
        return Path(str(item["saved_path"]))
    return run_dir / f"step5-selected-{idx:02d}-{item.get('text', 'pdf')}.pdf"


def _page_count_from_item(run_dir: Path, item: dict[str, Any], idx: int) -> Optional[int]:
    downloaded = bool(item.get("downloaded"))
    pdf_path = _resolve_pdf_path(run_dir, item, idx)
    if not downloaded or not pdf_path.exists():
        return None
    return _pdf_page_count(pdf_path)


def _resolve_deferred(
    deferred: list[dict[str, Any]],
    analysis_by_url: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for d in deferred:
        gid = d.get("group_id", "")
        summary = d.get("summary_candidate", {}) or {}
        full = d.get("full_candidate", {}) or {}
        su = summary.get("url", "")
        fu = full.get("url", "")
        full_pages = None
        if fu in analysis_by_url:
            full_pages = analysis_by_url[fu].get("page_count")

        chosen_role = "summary"
        reason = "default_to_summary"
        if isinstance(full_pages, int):
            if full_pages <= 20:
                chosen_role = "full"
                reason = f"full_page_count={full_pages} <= 20"
            else:
                chosen_role = "summary"
                reason = f"full_page_count={full_pages} > 20"

        chosen = full if chosen_role == "full" else summary
        other = summary if chosen_role == "full" else full
        resolved.append(
            {
                "group_id": gid,
                "status": "resolved",
                "rule": d.get("rule", "prefer_full_if_pages_le_20_else_summary"),
                "chosen_role": chosen_role,
                "chosen_url": chosen.get("url", ""),
                "chosen_text": chosen.get("text", ""),
                "rejected_url": other.get("url", ""),
                "rejected_text": other.get("text", ""),
                "reason": reason,
            }
        )
    return resolved


def _build_final_selection(
    selected_pdfs: list[dict[str, Any]],
    resolved: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    reject_urls = {r.get("rejected_url", "") for r in resolved if r.get("rejected_url")}
    keep_urls = {r.get("chosen_url", "") for r in resolved if r.get("chosen_url")}

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in selected_pdfs:
        u = item.get("url", "")
        if not u or u in seen:
            continue
        if u in reject_urls:
            continue
        row = dict(item)
        if u in keep_urls:
            row["decision_pending"] = False
            row["decision_resolved"] = True
        out.append(row)
        seen.add(u)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 6 document pipeline")
    parser.add_argument("--run-id", required=True, help="Run identifier")
    parser.add_argument("--tmp-root", default="tmp/runs", help="Root directory for per-run artifacts")
    parser.add_argument(
        "--step5-file",
        default="",
        help="Step5 result path (default: tmp/runs/<run_id>/step5-material-selection.json)",
    )
    parser.add_argument(
        "--output-file",
        default="",
        help="Step6 result path (default: tmp/runs/<run_id>/step6-document-pipeline.json)",
    )
    parser.add_argument("--max-workers", type=int, default=4, help="Parallel workers per PDF")
    args = parser.parse_args()

    run_dir = Path(args.tmp_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    step5_path = Path(args.step5_file) if args.step5_file else run_dir / "step5-material-selection.json"
    out_path = Path(args.output_file) if args.output_file else run_dir / "step6-document-pipeline.json"

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

    url_to_download = {d.get("url", ""): d for d in downloads if d.get("url")}
    analyze_targets: list[dict[str, Any]] = []
    for s in selected:
        url = s.get("url", "")
        merged = dict(s)
        if url in url_to_download:
            merged.update(url_to_download[url])
        analyze_targets.append(merged)

    # Phase A: lightweight pass for deferred resolution (page count only).
    page_count_by_url: dict[str, Optional[int]] = {}
    for idx, item in enumerate(analyze_targets, start=1):
        url = item.get("url", "")
        if not url:
            continue
        page_count_by_url[url] = _page_count_from_item(run_dir, item, idx)

    analysis_for_deferred = {u: {"page_count": p} for u, p in page_count_by_url.items()}
    resolved = _resolve_deferred(deferred, analysis_for_deferred)
    final_selected = _build_final_selection(selected, resolved)

    # Phase B: full analysis only for finally selected PDFs.
    final_targets: list[dict[str, Any]] = []
    for s in final_selected:
        u = s.get("url", "")
        merged = dict(s)
        if u in url_to_download:
            merged.update(url_to_download[u])
        final_targets.append(merged)

    analyses: list[dict[str, Any]] = []
    workers = max(1, min(args.max_workers, max(1, len(final_targets))))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = []
        for idx, item in enumerate(final_targets, start=1):
            futures.append(ex.submit(_analyze_one_pdf, run_dir, item, idx))
        for fut in as_completed(futures):
            analyses.append(fut.result())

    analyses_sorted = sorted(analyses, key=lambda x: x.get("saved_path", ""))

    payload = {
        "run_id": args.run_id,
        "inputs": {
            "step5_file": str(step5_path),
            "max_workers": workers,
        },
        "deferred_resolution_page_counts": page_count_by_url,
        "per_pdf_analysis": analyses_sorted,
        "resolved_deferred_decisions": resolved,
        "final_selected_pdfs": final_selected,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
