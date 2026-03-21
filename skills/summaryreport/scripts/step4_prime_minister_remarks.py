#!/usr/bin/env python3
"""Extract prime minister remarks from source.md and prepare Step8-like input."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _strip_frontmatter(md: str) -> str:
    if not md.startswith("---"):
        return md
    parts = md.split("\n---", 1)
    if len(parts) != 2:
        return md
    return parts[1].lstrip("\n")


def _clean_body(md: str) -> str:
    body = _strip_frontmatter(md)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    body = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", body)
    body = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", body)
    lines: list[str] = []
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        if s in {"facebookシェアする", "LINEで送る", "ツイート", "前へ", "次へ", "別ウィンドウで開く"}:
            continue
        if re.search(r"総理の一日一覧ページに戻る|ページのトップへ戻る|ご意見・ご要望|プライバシーポリシー", s):
            continue
        lines.append(s)
    return "\n".join(lines).strip()


def _extract_speaker(text: str) -> str:
    for pattern in [
        r"([一-龥ぁ-んァ-ンA-Za-z]+)内閣総理大臣(?:は|が|として|として、|に対し|に)",
        r"([一-龥ぁ-んァ-ンA-Za-z]+)総理(?:は|が|として|として、|に対し|に)",
    ]:
        m = re.search(pattern, text)
        if m:
            return m.group(1)
    return "総理"


def _extract_context(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    contexts: list[str] = []
    for line in lines:
        if "総理は、本日の議論を踏まえ" in line:
            break
        if re.search(r"総理大臣官邸で.+開催しました", line):
            contexts.append(line)
        elif re.search(r"会議では、.+議論が行われました", line):
            contexts.append(line)
        elif line.startswith("# "):
            contexts.append(line.removeprefix("# ").strip())
    return contexts[:3]


def _normalize_whitespace(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_quoted_remarks(text: str) -> str:
    trigger_patterns = [
        r"総理は、本日の議論を踏まえ、次のように述べました。",
        r"総理は、次のように述べました。",
        r"内閣総理大臣は、次のように述べました。",
    ]
    start_index = -1
    for pattern in trigger_patterns:
        m = re.search(pattern, text)
        if m:
            start_index = m.end()
            break
    scoped = text[start_index:] if start_index >= 0 else text

    quote_start = scoped.find("「")
    if quote_start >= 0:
        scoped = scoped[quote_start + 1 :]
        quote_end = scoped.find("」")
        if quote_end >= 0:
            return _normalize_whitespace(scoped[:quote_end])

    lines = [line.strip() for line in scoped.splitlines() if line.strip()]
    collected: list[str] = []
    for line in lines:
        if line.startswith("## ") and collected:
            break
        if "関連リンク" in line and collected:
            break
        if "一覧ページに戻る" in line:
            break
        collected.append(line)
    return _normalize_whitespace(" ".join(collected))


def _build_key_points(remarks_text: str) -> list[str]:
    if not remarks_text:
        return []
    pieces = re.split(r"。", remarks_text)
    points: list[str] = []
    for piece in pieces:
        s = _normalize_whitespace(piece)
        if not s:
            continue
        points.append(s + "。")
        if len(points) >= 8:
            break
    return points


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract prime minister remarks from HTML-derived markdown")
    parser.add_argument("--run-id", required=True, help="Run identifier")
    parser.add_argument("--tmp-root", default="tmp/runs", help="Root directory for per-run artifacts")
    parser.add_argument("--source-md-file", default="", help="source.md path override")
    args = parser.parse_args()

    run_dir = Path(args.tmp_root) / args.run_id
    source_md_path = Path(args.source_md_file) if args.source_md_file else run_dir / "source.md"
    source_md = _read_text(source_md_path)
    if not source_md:
        raise SystemExit(f"source markdown not found or empty: {source_md_path}")

    cleaned = _clean_body(source_md)
    remarks_text = _extract_quoted_remarks(cleaned)
    if not remarks_text:
        raise SystemExit("prime minister remarks not found in source markdown")

    speaker = _extract_speaker(cleaned)
    contexts = _extract_context(cleaned)
    key_points = _build_key_points(remarks_text)

    remarks_payload: dict[str, Any] = {
        "run_id": args.run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "focus_mode": "prime_minister_remarks",
        "source_md_path": str(source_md_path),
        "speaker": speaker,
        "context_lines": contexts,
        "remarks_text": remarks_text,
        "key_points": key_points,
    }
    (run_dir / "prime-minister-remarks.json").write_text(
        json.dumps(remarks_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    body_digest = {
        "run_id": args.run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_md_path": str(source_md_path),
        "source_type": "prime_minister_remarks",
        "digest_ja": remarks_text,
        "key_points": key_points,
        "raw_body_text": remarks_text,
        "focus_mode": "prime_minister_remarks",
    }
    (run_dir / "body-digest.json").write_text(json.dumps(body_digest, ensure_ascii=False, indent=2), encoding="utf-8")

    step8_payload = {
        "run_id": args.run_id,
        "inputs": {"mode": "prime_minister_remarks"},
        "per_document": [
            {
                "title": f"{speaker}総理発言",
                "document_type": "prime_minister_remarks",
                "summary": remarks_text,
                "key_points": key_points,
                "empty_content": False,
                "url": "",
            }
        ],
    }
    (run_dir / "step8-material-summaries.json").write_text(
        json.dumps(step8_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (run_dir / "prime-minister-remarks-pdf-links.json").write_text("[]\n", encoding="utf-8")
    print(str(run_dir / "prime-minister-remarks.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
