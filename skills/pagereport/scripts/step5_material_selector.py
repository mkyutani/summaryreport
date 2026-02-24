#!/usr/bin/env python3
"""Step 5: score PDF links and select materials for summarization."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import unquote, urlparse

from fetch_with_retry import FetchError, fetch_url

OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("PAGEREPORT_STEP5_MODEL", "gpt-5-mini")

BASE_SCORES = {
    "executive_summary": 5,
    "material": 4,
    "agenda": 3,
    "minutes": 3,
    "reference": 2,
    "personal_material": 2,
    "participants": 1,
    "seating": 1,
    "disclosure_method": 1,
    "other": 2,
}

EXCLUDE_CATEGORIES = {"participants", "seating", "disclosure_method"}
SUMMARY_HINTS = [
    "概要",
    "要約",
    "サマリー",
    "エグゼクティブサマリー",
    "executive summary",
]
FULL_HINTS = [
    "本文",
    "本編",
    "報告書",
    "とりまとめ",
    "取りまとめ",
    "詳細",
]


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def _parse_links_json(path: Path) -> list[dict[str, str]]:
    raw = _read_text(path)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []

    out: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        url = _normalize_text(str(item.get("url") or ""))
        if not url:
            continue
        text = _normalize_text(str(item.get("text") or ""))
        filename = _normalize_text(str(item.get("filename") or ""))
        category = _normalize_text(str(item.get("estimated_category") or "other")) or "other"
        if not filename:
            filename = Path(unquote(urlparse(url).path)).name
        out.append({
            "text": text,
            "url": url,
            "filename": filename,
            "estimated_category": category,
        })
    return out


def _classify_document(title: str, filename: str) -> str:
    t = _normalize_text(title)
    tl = t.lower()
    fl = filename.lower()

    if any(kw in t for kw in ["議事次第", "次第"]):
        return "agenda"
    if any(kw in t for kw in ["議事録", "議事要旨", "会議録", "議事概要"]):
        return "minutes"
    if any(kw in t for kw in ["委員名簿", "出席者名簿"]):
        return "participants"
    if any(kw in t for kw in ["座席表", "座席配置"]):
        return "seating"
    if any(kw in t for kw in ["公開方法", "傍聴"]):
        return "disclosure_method"
    if any(kw in t for kw in ["とりまとめ", "取りまとめ", "概要", "Executive Summary", "エグゼクティブサマリー"]):
        return "executive_summary"
    if "参考資料" in t or "参考" in t or "sankou" in fl:
        return "reference"
    if (
        re.match(r"^資料\s*[：:]", t)
        or "説明資料" in t
        or "事務局資料" in t
        or re.search(r"[^\s]+(?:省|府|庁)説明資料", t)
    ):
        return "material"
    if re.match(r"^資料\s*\d+", t) or re.match(r"^資料\d+", t):
        return "material"
    if "gijiroku" in fl or "gijiyoshi" in fl or "minutes" in fl:
        return "minutes"
    return "other"


def _llm_classify_document(title: str, filename: str, url: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "category": {
                "type": "string",
                "enum": list(BASE_SCORES.keys()),
            }
        },
        "required": ["category"],
    }
    body = {
        "model": OPENAI_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Classify Japanese government PDF links. "
                    "Use title/filename/url only. "
                    "If title indicates substantive material like '資料', "
                    "'説明資料', '事務局資料', or '○○省/府/庁説明資料', prefer 'material'. "
                    "But if title clearly says '参考資料', classify as 'reference'."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"title": title, "filename": filename, "url": url},
                    ensure_ascii=False,
                ),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "step5_category", "schema": schema, "strict": True},
        },
    }
    req = request.Request(
        f"{OPENAI_API_BASE}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM request failed: {exc.code} {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"LLM request failed: {exc}") from exc
    data = json.loads(raw.decode("utf-8", errors="replace"))
    parsed = json.loads(data["choices"][0]["message"]["content"])
    return str(parsed.get("category", "other"))


def _parse_links_txt(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in _read_text(path).splitlines():
        raw = line.strip()
        if not raw:
            continue
        text = ""
        url = raw
        if "\t" in raw:
            text, url = raw.split("\t", 1)
            text = _normalize_text(text)
            url = _normalize_text(url)
        if not url:
            continue
        filename = Path(unquote(urlparse(url).path)).name
        category = _classify_document(text, filename)
        rows.append({
            "text": text,
            "url": url,
            "filename": filename,
            "estimated_category": category,
        })
    return rows


def _dedupe_by_url(items: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for it in items:
        url = it.get("url", "")
        if not url:
            continue
        if url not in merged:
            merged[url] = dict(it)
            continue
        if not merged[url].get("text") and it.get("text"):
            merged[url]["text"] = it["text"]
        if merged[url].get("estimated_category") in {"", "other"} and it.get("estimated_category"):
            merged[url]["estimated_category"] = it["estimated_category"]
    return list(merged.values())


def _filename_bonus(filename: str) -> int:
    patterns = [
        r"shiryou[01]\.",
        r"shiryou[01]-\d+\.",
        r"honpen\.",
        r"gaiyou\.",
        r"torimatome\.",
    ]
    fl = filename.lower()
    for pat in patterns:
        if re.search(pat, fl):
            return 1
    return 0


def _material_id_from_text(text: str, filename: str) -> str:
    t = _normalize_text(text)
    m = re.search(r"資料\s*(\d+(?:-\d+)?)", t)
    if m:
        return f"資料{m.group(1)}"
    fl = filename.lower()
    m = re.search(r"(?:shiryou|material)[_-]?(\d+(?:[-_]\d+)?)", fl)
    if m:
        return f"資料{m.group(1).replace('_', '-') }"
    return ""


def _build_minutes_mentions(minutes_text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for m in re.finditer(r"資料\s*(\d+(?:-\d+)?)", minutes_text):
        key = f"資料{m.group(1)}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _minutes_mention_bonus(material_id: str, mentions: dict[str, int]) -> int:
    if not material_id:
        return 0
    c = mentions.get(material_id, 0)
    if c >= 5:
        return 2
    if c >= 2:
        return 1
    return 0


def _category_penalty(category: str, has_executive_summary: bool) -> int:
    if category in EXCLUDE_CATEGORIES:
        return -10
    if category == "reference" and has_executive_summary:
        return -1
    if category == "personal_material" and has_executive_summary:
        return -2
    return 0


def _apply_adjustment_rules(scored: list[dict[str, Any]]) -> None:
    has_substantial = any(
        x["document_category"] in {"executive_summary", "material"} and x["priority_score"] >= 4
        for x in scored
    )
    has_normal_materials = any(x["document_category"] in {"executive_summary", "material"} for x in scored)
    has_official = has_normal_materials

    for x in scored:
        if x["document_category"] == "agenda" and has_substantial and x["priority_score"] >= 5:
            x["priority_score"] = 4
            x["adjustments"].append("agenda_cap_to_4")

        if x["document_category"] == "reference" and has_normal_materials and x["priority_score"] > 4:
            x["priority_score"] = 4
            x["adjustments"].append("reference_cap_to_4")

        if x["document_category"] == "personal_material":
            if has_official:
                capped = min(x["priority_score"], 2)
                if capped != x["priority_score"]:
                    x["adjustments"].append("personal_cap_with_official")
                x["priority_score"] = capped
            else:
                boosted = max(x["priority_score"], 3)
                if boosted != x["priority_score"]:
                    x["adjustments"].append("personal_raise_without_official")
                x["priority_score"] = boosted

        if x["priority_score"] < 1:
            x["priority_score"] = 1


def _safe_filename_part(text: str) -> str:
    def _truncate_utf8_bytes(v: str, max_bytes: int) -> str:
        b = v.encode("utf-8")
        if len(b) <= max_bytes:
            return v
        cut = b[:max_bytes]
        while cut:
            try:
                return cut.decode("utf-8")
            except UnicodeDecodeError:
                cut = cut[:-1]
        return ""

    s = _normalize_text(text)
    s = s.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    s = re.sub(r"[\x00-\x1f\x7f]", "", s)
    s = re.sub(r"[\\/:*?\"<>|]", "_", s)
    s = s.replace(" ", "_")
    s = re.sub(r"_+", "_", s)
    s = s.strip("._ ")
    if not s:
        s = "pdf"
    # Keep filename safely short by UTF-8 byte length to avoid OS/path limits.
    # (Japanese chars are multibyte, so char-count based truncation is insufficient.)
    s = _truncate_utf8_bytes(s, 120).rstrip("._ ")
    if not s:
        s = "pdf"
    return s


def _download_selected_pdfs(run_dir: Path, selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for i, item in enumerate(selected, start=1):
        url = item.get("url", "")
        original_filename = item.get("filename", "") or Path(unquote(urlparse(url).path)).name or "source.pdf"
        title_part = _safe_filename_part(item.get("text", "")) or "pdf"
        ext = Path(original_filename).suffix or ".pdf"
        save_name = f"step5-selected-{i:02d}-{title_part}{ext}"
        save_path = run_dir / save_name

        row = {
            "index": i,
            "url": url,
            "original_filename": original_filename,
            "saved_path": str(save_path),
            "downloaded": False,
        }

        try:
            fetched = fetch_url(url)
            body = fetched.body
            if not body.startswith(b"%PDF-"):
                ctype = fetched.content_type or ""
                if "pdf" not in ctype:
                    raise FetchError(f"selected file is not PDF: url={url}, content_type={ctype!r}")
            save_path.write_bytes(body)
            row["downloaded"] = True
            row["size_bytes"] = len(body)
            row["content_type"] = fetched.content_type
            row["used_browser_headers"] = fetched.used_browser_headers
        except Exception as exc:  # keep pipeline running and record failure
            row["error"] = str(exc)

        results.append(row)
    return results


def _is_summary_text(text: str) -> bool:
    t = _normalize_text(text).lower()
    return any(h.lower() in t for h in SUMMARY_HINTS)


def _is_full_text(text: str) -> bool:
    t = _normalize_text(text).lower()
    return any(h.lower() in t for h in FULL_HINTS)


def _topic_key(text: str) -> str:
    t = _normalize_text(text)
    # remove leading "資料X" etc.
    t = re.sub(r"^資料\s*\d+(?:-\d+)?\s*", "", t)
    # remove parenthesized suffixes like (PDF形式:xxKB)
    t = re.sub(r"[（(][^）)]*pdf[^）)]*[）)]", "", t, flags=re.IGNORECASE)
    t = re.sub(r"[（(][^）)]*[）)]", "", t)
    # remove summary/full hint words to compare base topic
    for h in SUMMARY_HINTS + FULL_HINTS:
        t = re.sub(re.escape(h), "", t, flags=re.IGNORECASE)
    # Normalize common Japanese connective endings.
    t = re.sub(r"の$", "", t)
    t = re.sub(r"について$", "", t)
    t = re.sub(r"に関する$", "", t)
    t = re.sub(r"に係る$", "", t)
    t = re.sub(r"[・／/,:：\-ー_　\s]+", "", t)
    return t


def _build_deferred_decisions(scored_sorted: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], set[str]]:
    summary_candidates = []
    full_candidates = []
    for item in scored_sorted:
        text = item.get("text", "")
        if _is_summary_text(text):
            summary_candidates.append(item)
        else:
            full_candidates.append(item)

    deferred: list[dict[str, Any]] = []
    forced_urls: set[str] = set()
    used_full_urls: set[str] = set()
    gid = 1

    for s in summary_candidates:
        sk = _topic_key(s.get("text", ""))
        if not sk:
            continue
        best_full = None
        best_score = -1
        for f in full_candidates:
            fu = f.get("url", "")
            if fu in used_full_urls:
                continue
            fk = _topic_key(f.get("text", ""))
            if not fk or fk != sk:
                continue
            # Prefer explicit "full" hints, then higher score.
            bonus = 100 if _is_full_text(f.get("text", "")) else 0
            sc = bonus + int(f.get("priority_score", 0))
            if sc > best_score:
                best_full = f
                best_score = sc
        if not best_full:
            continue

        su = s.get("url", "")
        fu = best_full.get("url", "")
        if not su or not fu:
            continue

        group_id = f"deferred-{gid:02d}"
        gid += 1
        used_full_urls.add(fu)
        forced_urls.add(su)
        forced_urls.add(fu)
        deferred.append(
            {
                "group_id": group_id,
                "status": "pending",
                "rule": "prefer_full_if_pages_le_20_else_summary",
                "summary_candidate": {
                    "url": su,
                    "text": s.get("text", ""),
                    "priority_score": s.get("priority_score", 0),
                },
                "full_candidate": {
                    "url": fu,
                    "text": best_full.get("text", ""),
                    "priority_score": best_full.get("priority_score", 0),
                },
            }
        )

    return deferred, forced_urls


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 5 material selector")
    parser.add_argument("--run-id", required=True, help="Run identifier")
    parser.add_argument("--tmp-root", default="tmp/runs", help="Root directory for per-run artifacts")
    parser.add_argument("--pdf-links-file", default="", help="pdf-links.txt path")
    parser.add_argument("--pdf-links-json-file", default="", help="pdf-links.json path")
    parser.add_argument("--minutes-file", default="", help="minutes.md path")
    parser.add_argument("--output-file", default="", help="step5-material-selection.json path")
    args = parser.parse_args()

    out_dir = Path(args.tmp_root) / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    links_txt_path = Path(args.pdf_links_file) if args.pdf_links_file else out_dir / "pdf-links.txt"
    links_json_path = Path(args.pdf_links_json_file) if args.pdf_links_json_file else out_dir / "pdf-links.json"
    minutes_path = Path(args.minutes_file) if args.minutes_file else out_dir / "minutes.md"
    out_path = Path(args.output_file) if args.output_file else out_dir / "step5-material-selection.json"

    items = _parse_links_json(links_json_path)
    source = "pdf-links.json"
    if not items:
        items = _parse_links_txt(links_txt_path)
        source = "pdf-links.txt"

    items = _dedupe_by_url(items)
    minutes_text = _read_text(minutes_path)
    mentions = _build_minutes_mentions(minutes_text)

    has_exec_summary = any((x.get("estimated_category") or "") == "executive_summary" for x in items)

    use_llm = os.getenv("PAGEREPORT_STEP5_LLM_CLASSIFY", "1") != "0"
    llm_errors: list[str] = []
    scored: list[dict[str, Any]] = []
    for it in items:
        estimated = (it.get("estimated_category") or "").strip()
        if estimated and estimated != "other":
            category = estimated
        else:
            category = _classify_document(it.get("text", ""), it.get("filename", ""))
        if use_llm and category == "other":
            try:
                llm_cat = _llm_classify_document(it.get("text", ""), it.get("filename", ""), it.get("url", ""))
                if llm_cat in BASE_SCORES:
                    category = llm_cat
            except Exception as exc:
                llm_errors.append(str(exc))
        base = BASE_SCORES.get(category, BASE_SCORES["other"])
        file_bonus = _filename_bonus(it.get("filename", ""))
        material_id = _material_id_from_text(it.get("text", ""), it.get("filename", ""))
        mention_bonus = _minutes_mention_bonus(material_id, mentions)
        penalty = _category_penalty(category, has_exec_summary)
        score = base + file_bonus + mention_bonus + penalty

        scored.append(
            {
                "text": it.get("text", ""),
                "url": it.get("url", ""),
                "filename": it.get("filename", ""),
                "document_category": category,
                "material_id": material_id,
                "score_components": {
                    "base": base,
                    "filename_bonus": file_bonus,
                    "minutes_mention_bonus": mention_bonus,
                    "category_penalty": penalty,
                },
                "priority_score": max(1, score),
                "adjustments": [],
            }
        )

    _apply_adjustment_rules(scored)

    sorted_scored = sorted(
        scored,
        key=lambda x: (x["priority_score"], x["document_category"], x["filename"]),
        reverse=True,
    )

    deferred_decisions, forced_urls = _build_deferred_decisions(sorted_scored)

    selected = [x for x in sorted_scored if x["priority_score"] >= 4]
    for x in sorted_scored:
        if x.get("url") in forced_urls and x not in selected:
            selected.append(x)

    # Keep traditional cap for score-based picks; deferred pairs can exceed cap.
    score_selected = [x for x in selected if x.get("url") not in forced_urls]
    forced_selected = [x for x in selected if x.get("url") in forced_urls]
    score_selected = sorted(
        score_selected,
        key=lambda x: (x["priority_score"], x["document_category"], x["filename"]),
        reverse=True,
    )
    if len(score_selected) > 5:
        score_selected = score_selected[:5]
    selected = forced_selected + score_selected
    # Deduplicate while preserving order.
    seen_urls: set[str] = set()
    dedup_selected: list[dict[str, Any]] = []
    for x in selected:
        u = x.get("url", "")
        if not u or u in seen_urls:
            continue
        seen_urls.add(u)
        dedup_selected.append(x)
    selected = dedup_selected

    group_by_url: dict[str, tuple[str, str]] = {}
    for g in deferred_decisions:
        gid = g["group_id"]
        su = g["summary_candidate"]["url"]
        fu = g["full_candidate"]["url"]
        group_by_url[su] = (gid, "summary")
        group_by_url[fu] = (gid, "full")
    for x in selected:
        u = x.get("url", "")
        if u in group_by_url:
            gid, role = group_by_url[u]
            x["decision_pending"] = True
            x["decision_group_id"] = gid
            x["decision_role"] = role
        else:
            x["decision_pending"] = False
    downloads = _download_selected_pdfs(out_dir, selected)

    payload = {
        "run_id": args.run_id,
        "inputs": {
            "source": source,
            "pdf_links_file": str(links_txt_path),
            "pdf_links_json_file": str(links_json_path),
            "minutes_file": str(minutes_path),
            "pdf_count": len(items),
            "minutes_mentions_count": sum(mentions.values()),
        },
        "all_pdfs": sorted_scored,
        "selection_rule": "score>=4 with cap 5 for score-based picks; deferred summary/full pairs are force-included",
        "selected_pdfs": selected,
        "deferred_decisions": deferred_decisions,
        "downloaded_files": downloads,
        "llm_classification": {"enabled": use_llm, "errors": llm_errors},
    }

    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
