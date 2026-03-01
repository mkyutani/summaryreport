#!/usr/bin/env python3
"""Step 4b: extract body digest from source.md for Step9."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request

OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("SUMMARYREPORT_STEP4_BODY_MODEL", "gpt-5-mini")


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _read_json(path: Path) -> dict[str, Any]:
    raw = _read_text(path)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


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
    noise = [
        r"^\s*ツイート\s*$",
        r"^\s*facebookシェアする\s*$",
        r"^\s*LINEで送る\s*$",
        r"^\s*主な閣議決定・本部決定一覧ページに戻る\s*$",
    ]
    lines: list[str] = []
    stop = False
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        if re.search(r"これまでの\s*主な閣議決定・本部決定", s):
            stop = True
            continue
        if stop:
            continue
        if any(re.search(p, s) for p in noise):
            continue
        lines.append(s)
    cleaned = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", cleaned)


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "digest_ja": {"type": "string"},
            "key_points": {"type": "array", "items": {"type": "string"}},
            "source_type": {"type": "string", "enum": ["report_body", "meeting_body", "none"]},
        },
        "required": ["digest_ja", "key_points", "source_type"],
    }


def _call_llm(page_type: str, cleaned_body: str, title: str, date_yyyymmdd: str) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    system_prompt = (
        "You extract body digest from markdown content. "
        "Use only provided text; do not invent details. "
        "For REPORT pages, preserve numbered structure if present (1., 2., 3. or （1）（2）...). "
        "Return concise digest and key points."
    )
    user_payload = {
        "page_type": page_type,
        "title": title,
        "date_yyyymmdd": date_yyyymmdd,
        "cleaned_body_markdown": cleaned_body[:12000],
    }
    body = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "step4_body_digest", "schema": _schema(), "strict": True},
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


def _fallback_digest(page_type: str, cleaned_body: str) -> dict[str, Any]:
    lines = [ln.strip() for ln in cleaned_body.splitlines() if ln.strip()]
    points: list[str] = []
    for ln in lines:
        if re.match(r"^[0-9０-９]+[\.．]\s*", ln) or re.match(r"^[（(][0-9０-９]+[）)]\s*", ln):
            points.append(ln)
        if len(points) >= 8:
            break
    if not points:
        points = lines[:5]
    digest = " ".join(lines[:20])[:2000]
    return {
        "digest_ja": digest,
        "key_points": points,
        "source_type": "report_body" if page_type == "REPORT" else "meeting_body",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Step4 body digest extractor")
    parser.add_argument("--run-id", required=True, help="Run identifier")
    parser.add_argument("--tmp-root", default="tmp/runs", help="Root directory for per-run artifacts")
    parser.add_argument("--source-md-file", default="", help="source.md path")
    parser.add_argument("--step2-file", default="", help="step2-metadata.json path")
    parser.add_argument("--output-file", default="", help="body-digest.json path")
    args = parser.parse_args()

    run_dir = Path(args.tmp_root) / args.run_id
    source_md_path = Path(args.source_md_file) if args.source_md_file else run_dir / "source.md"
    step2_path = Path(args.step2_file) if args.step2_file else run_dir / "step2-metadata.json"
    out_path = Path(args.output_file) if args.output_file else run_dir / "body-digest.json"

    raw_md = _read_text(source_md_path)
    if not raw_md:
        raise SystemExit(f"source markdown not found or empty: {source_md_path}")
    step2 = _read_json(step2_path)
    page_type = str(step2.get("page_type", "UNKNOWN"))
    title = str(step2.get("meeting_name", {}).get("value", ""))
    date_yyyymmdd = str(step2.get("date", {}).get("value", ""))
    cleaned_body = _clean_body(raw_md)

    llm_error = ""
    try:
        llm = _call_llm(page_type, cleaned_body, title, date_yyyymmdd)
    except Exception as exc:  # pragma: no cover
        llm_error = str(exc)
        llm = _fallback_digest(page_type, cleaned_body)
    payload = {
        "run_id": args.run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_md_path": str(source_md_path),
        "source_type": llm.get("source_type", "none"),
        "digest_ja": str(llm.get("digest_ja", "")),
        "key_points": llm.get("key_points", []) if isinstance(llm.get("key_points"), list) else [],
        "raw_body_text": cleaned_body,
        "llm_error": llm_error or None,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
