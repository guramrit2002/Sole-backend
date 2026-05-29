"""
Layer 1 — curl-cffi

Fastest layer. Sends an HTTP request that impersonates a real browser's
TLS fingerprint (JA3/JA4), so it bypasses most TLS-level bot detection.
Falls back through multiple browser profiles on failure.
"""

from __future__ import annotations

import logging
import time
from typing import Optional
from urllib.parse import urlparse

from curl_cffi import requests as cfreq

from .parser import ProductData, parse

logger = logging.getLogger(__name__)

# Rotation order: most common browsers first
_PROFILES = ["chrome120", "chrome110", "safari17_0", "firefox121", "edge101"]

_BLOCKED_CODES = {403, 429, 503}
_BLOCKED_BODY = [
    "access denied", "you have been blocked", "captcha",
    "cloudflare", "ddos-guard", "verifying you are human",
    "are you a robot", "unusual traffic", "please enable javascript",
]


def _is_blocked(status: int, html: str) -> bool:
    if status in _BLOCKED_CODES:
        return True
    lower = html.lower()
    return any(sig in lower for sig in _BLOCKED_BODY)


def _headers(url: str) -> dict:
    origin = "{0.scheme}://{0.netloc}".format(urlparse(url))
    return {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": origin + "/",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }


def _fetch_once(url: str, profile: str) -> tuple[str, int]:
    """Return (html, status_code). Raises on network error."""
    resp = cfreq.get(
        url,
        impersonate=profile,
        headers=_headers(url),
        timeout=20,
        allow_redirects=True,
    )
    return resp.text, resp.status_code


def scrape(url: str) -> Optional[ProductData]:
    """
    Try each browser profile in turn with exponential backoff.
    Returns ProductData on the first clean result, or None if all profiles fail.
    """
    for attempt, profile in enumerate(_PROFILES):
        if attempt > 0:
            wait = 1.5 ** attempt
            logger.info("[L1] retry %d — profile=%s backoff=%.1fs", attempt, profile, wait)
            time.sleep(wait)

        try:
            html, status = _fetch_once(url, profile)
        except Exception as exc:
            logger.warning("[L1] network error profile=%s: %s", profile, exc)
            continue

        if _is_blocked(status, html) or len(html.strip()) < 500:
            logger.warning("[L1] blocked/empty — profile=%s status=%d", profile, status)
            continue

        logger.info("[L1] success — profile=%s status=%d len=%d", profile, status, len(html))
        data = parse(html, source_layer="curl-cffi")
        if data.filled() > 0:
            return data

    logger.error("[L1] all profiles failed for %s", url)
    return None
