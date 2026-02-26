#!/usr/bin/env python3
"""Minimal Docling Serve client for source conversion."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib import error, request


DEFAULT_DOCLING_ENDPOINT = "http://127.0.0.1:5001/v1/convert/source"


class DoclingError(RuntimeError):
    """Raised when Docling conversion fails."""


def _walk_strings(value: Any) -> List[str]:
    found: List[str] = []
    if isinstance(value, str):
        found.append(value)
        return found
    if isinstance(value, dict):
        for item in value.values():
            found.extend(_walk_strings(item))
        return found
    if isinstance(value, list):
        for item in value:
            found.extend(_walk_strings(item))
    return found


def _extract_markdown(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        # Direct key matches first.
        for key in ("markdown", "md", "md_content", "text_content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value

        # Common nested response patterns.
        for key in ("document", "documents", "results", "output"):
            value = payload.get(key)
            result = _extract_markdown(value)
            if result:
                return result

        # Heuristic: first non-empty string containing markdown cues.
        for text in _walk_strings(payload):
            trimmed = text.strip()
            if not trimmed:
                continue
            if "\n#" in trimmed or "\n- " in trimmed or "|" in trimmed:
                return trimmed
        return None

    if isinstance(payload, list):
        for item in payload:
            result = _extract_markdown(item)
            if result:
                return result
    return None


def convert_url_to_markdown(
    source_url: str,
    endpoint: str = DEFAULT_DOCLING_ENDPOINT,
    timeout_seconds: int = 120,
) -> Dict[str, Any]:
    """Convert a URL source with Docling Serve and return markdown + raw response."""
    body = json.dumps(
        {
            "sources": [{"kind": "http", "url": source_url}],
        }
    ).encode("utf-8")

    req = request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read()
    except error.URLError as exc:
        raise DoclingError(f"Docling request failed: {exc}") from exc
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise DoclingError(f"Docling HTTP error: {exc.code} {detail}") from exc

    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise DoclingError("Docling response was not valid JSON") from exc

    markdown = _extract_markdown(payload)
    if not markdown:
        raise DoclingError("Could not extract markdown text from Docling response")

    return {
        "markdown": markdown,
        "raw_response": payload,
    }
