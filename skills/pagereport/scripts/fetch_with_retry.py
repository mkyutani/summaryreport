#!/usr/bin/env python3
"""Shared HTTP fetch utility with optional browser User-Agent retry."""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from typing import Dict, Optional
from urllib import error, request

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

RETRY_STATUS_CODES = {403, 406, 429}


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    content_type: str
    body: bytes
    used_browser_headers: bool


class FetchError(RuntimeError):
    """Raised when HTTP fetch fails after retries."""


def _build_headers(use_browser_headers: bool) -> Dict[str, str]:
    headers = {
        "Accept": "*/*",
    }
    if use_browser_headers:
        headers.update(
            {
                "User-Agent": BROWSER_USER_AGENT,
                "Accept": "text/html,application/pdf,application/octet-stream,*/*",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            }
        )
    return headers


def _content_type_from_headers(resp: request.addinfourl) -> str:
    return (resp.headers.get("Content-Type") or "").lower()


def fetch_url(url: str, timeout_seconds: int = 30, max_bytes: int = 20 * 1024 * 1024) -> FetchResult:
    """Fetch URL and retry once with browser headers when blocked."""
    ssl_context = ssl.create_default_context()
    last_error: Optional[Exception] = None

    for use_browser_headers in (False, True):
        req = request.Request(url, headers=_build_headers(use_browser_headers))
        try:
            with request.urlopen(req, timeout=timeout_seconds, context=ssl_context) as resp:
                body = resp.read(max_bytes + 1)
                if len(body) > max_bytes:
                    raise FetchError(f"Response too large (>{max_bytes} bytes): {url}")

                return FetchResult(
                    url=url,
                    final_url=resp.geturl(),
                    status_code=getattr(resp, "status", 200),
                    content_type=_content_type_from_headers(resp),
                    body=body,
                    used_browser_headers=use_browser_headers,
                )
        except error.HTTPError as exc:
            last_error = exc
            if use_browser_headers or exc.code not in RETRY_STATUS_CODES:
                break
        except (error.URLError, TimeoutError, ssl.SSLError) as exc:
            last_error = exc
            if use_browser_headers:
                break

    raise FetchError(f"Failed to fetch URL: {url} ({last_error})")
