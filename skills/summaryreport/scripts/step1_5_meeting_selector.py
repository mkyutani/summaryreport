#!/usr/bin/env python3
"""Step 1.5: select target meeting scope using LLM (HTML multi-meeting pages)."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import urljoin

OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("SUMMARYREPORT_STEP1_5_MODEL", "gpt-5-mini")


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    raw = _read_text(path)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for x in data:
        if isinstance(x, dict):
            out.append(x)
    return out


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _extract_frontmatter(md_text: str) -> tuple[str, str]:
    lines = md_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "", md_text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            front = "\n".join(lines[: i + 1]).strip() + "\n\n"
            body = "\n".join(lines[i + 1 :]).lstrip("\n")
            return front, body
    return "", md_text


def _parse_pdf_links_fallback_txt(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ln in _read_text(path).splitlines():
        raw = ln.strip()
        if not raw:
            continue
        text = ""
        url = raw
        if "\t" in raw:
            text, url = raw.split("\t", 1)
        out.append({"text": _normalize(text), "url": _normalize(url), "filename": Path(url).name})
    return out


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "selected_markdown": {"type": "string"},
            "selected_pdf_urls": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"},
            "reason": {"type": "string"},
        },
        "required": ["selected_markdown", "selected_pdf_urls", "confidence", "reason"],
    }


def _call_llm(source_md: str, links: list[dict[str, Any]], target: dict[str, str]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    system_prompt = (
        "You are selecting one target meeting scope from a Japanese government HTML-derived markdown page. "
        "Return only the requested meeting scope. "
        "Do NOT summarize or paraphrase; keep original text snippets from source markdown. "
        "Exclude other rounds/meetings. "
        "If uncertain, lower confidence."
    )
    user_payload = {
        "target": target,
        "source_markdown": source_md,
        "pdf_links": [
            {
                "text": _normalize(str(x.get("text", ""))),
                "url": _normalize(str(x.get("url", ""))),
                "filename": _normalize(str(x.get("filename", ""))),
            }
            for x in links
        ],
        "output_requirements": {
            "selected_markdown": "Target scope only. Include target heading and directly related lines/links.",
            "selected_pdf_urls": "PDF URLs related to selected_markdown only.",
        },
    }

    body = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "step1_5_scope", "schema": _schema(), "strict": True},
        },
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
    return json.loads(data["choices"][0]["message"]["content"])


def _extract_md_links(md_text: str, base_url: str) -> list[str]:
    out: list[str] = []
    for m in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", md_text):
        href = _normalize(m.group(1))
        if not href:
            continue
        u = urljoin(base_url, href)
        if ".pdf" in u.lower():
            out.append(u)
    seen = set()
    uniq: list[str] = []
    for u in out:
        if u in seen:
            continue
        seen.add(u)
        uniq.append(u)
    return uniq


def _render_links_txt(rows: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for r in rows:
        text = _normalize(str(r.get("text", "")))
        url = _normalize(str(r.get("url", "")))
        if not url:
            continue
        lines.append(f"{text}\t{url}" if text else url)
    return "\n".join(lines) + ("\n" if lines else "")


def main() -> int:
    parser = argparse.ArgumentParser(description="Step1.5 meeting selector")
    parser.add_argument("--run-id", required=True, help="Run identifier")
    parser.add_argument("--tmp-root", default="tmp/runs", help="Root directory for per-run artifacts")
    parser.add_argument("--md-file", default="", help="source.md path")
    parser.add_argument("--pdf-links-json-file", default="", help="pdf-links.json path")
    parser.add_argument("--pdf-links-file", default="", help="pdf-links.txt path")
    parser.add_argument("--metadata-file", default="", help="metadata.json path")
    parser.add_argument("--target-meeting-name", default="", help="Target meeting/report name")
    parser.add_argument("--target-round", default="", help="Target round number/text")
    parser.add_argument("--target-date", default="", help="Target date (yyyymmdd preferred)")
    parser.add_argument("--target-text", default="", help="Free-form target scope")
    parser.add_argument("--min-confidence", type=float, default=0.35, help="Minimum confidence threshold")
    args = parser.parse_args()

    run_dir = Path(args.tmp_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    md_path = Path(args.md_file) if args.md_file else run_dir / "source.md"
    links_json_path = Path(args.pdf_links_json_file) if args.pdf_links_json_file else run_dir / "pdf-links.json"
    links_txt_path = Path(args.pdf_links_file) if args.pdf_links_file else run_dir / "pdf-links.txt"
    meta_path = Path(args.metadata_file) if args.metadata_file else run_dir / "metadata.json"

    out_md_path = run_dir / "selected-source.md"
    out_links_json_path = run_dir / "selected-pdf-links.json"
    out_links_txt_path = run_dir / "selected-pdf-links.txt"
    out_meta_path = run_dir / "selection-metadata.json"

    source_md = _read_text(md_path)
    if not source_md:
        raise SystemExit(f"source md not found or empty: {md_path}")

    target = {
        "meeting_name": _normalize(args.target_meeting_name),
        "round": _normalize(args.target_round),
        "date": _normalize(args.target_date),
        "text": _normalize(args.target_text),
    }

    all_links = _read_json_list(links_json_path)
    if not all_links:
        all_links = _parse_pdf_links_fallback_txt(links_txt_path)

    meta_raw = _read_text(meta_path)
    base_url = ""
    if meta_raw:
        try:
            obj = json.loads(meta_raw)
            if isinstance(obj, dict):
                base_url = str(obj.get("final_url", "") or obj.get("input_url", ""))
        except json.JSONDecodeError:
            pass

    if not any(target.values()):
        _write_text(out_md_path, source_md)
        _write_text(out_links_json_path, json.dumps(all_links, ensure_ascii=False, indent=2) + "\n")
        _write_text(out_links_txt_path, _render_links_txt(all_links))
        out_meta_path.write_text(
            json.dumps(
                {
                    "run_id": args.run_id,
                    "applied": False,
                    "reason": "no target specified",
                    "selected_md_file": str(out_md_path),
                    "selected_pdf_links_json_file": str(out_links_json_path),
                    "selected_pdf_links_file": str(out_links_txt_path),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(str(out_meta_path))
        return 0

    frontmatter, body = _extract_frontmatter(source_md)
    llm = _call_llm(body, all_links, target)

    confidence = float(llm.get("confidence", 0.0))
    selected_body = str(llm.get("selected_markdown", "")).strip()
    if not selected_body:
        raise SystemExit("step1.5 failed: selected_markdown is empty")
    if confidence < args.min_confidence:
        raise SystemExit(
            f"step1.5 low confidence: {confidence:.3f} < {args.min_confidence:.3f}; reason={llm.get('reason','')}"
        )

    if target["meeting_name"] and not re.search(r"^#\s+.+$", selected_body, flags=re.MULTILINE):
        selected_body = f"# {target['meeting_name']}\n\n{selected_body}"

    selected_md = (frontmatter + selected_body + "\n").strip() + "\n"
    _write_text(out_md_path, selected_md)

    selected_urls = [urljoin(base_url, _normalize(u)) for u in llm.get("selected_pdf_urls", []) if _normalize(u)]
    selected_urls = [u for u in selected_urls if ".pdf" in u.lower()]
    if not selected_urls:
        selected_urls = _extract_md_links(selected_body, base_url)

    urlset = set(selected_urls)
    selected_links = [x for x in all_links if _normalize(str(x.get("url", ""))) in urlset]
    if not selected_links:
        raise SystemExit("step1.5 failed: no scoped pdf links selected")

    _write_text(out_links_json_path, json.dumps(selected_links, ensure_ascii=False, indent=2) + "\n")
    _write_text(out_links_txt_path, _render_links_txt(selected_links))

    result = {
        "run_id": args.run_id,
        "applied": True,
        "target": target,
        "section_selection": {
            "confidence": confidence,
            "llm_reason": str(llm.get("reason", "")),
            "min_confidence": args.min_confidence,
        },
        "link_selection": {
            "selected_count": len(selected_links),
            "total_count": len(all_links),
            "method": "llm",
        },
        "selected_md_file": str(out_md_path),
        "selected_pdf_links_json_file": str(out_links_json_path),
        "selected_pdf_links_file": str(out_links_txt_path),
    }
    out_meta_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_meta_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
