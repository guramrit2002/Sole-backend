"""
Layer 2 — Scrapling (smart CSS selectors via Adaptor)

Uses curl-cffi with a randomised profile for the HTTP fetch (same stealth as
Layer 1 but a different browser fingerprint), then hands the HTML to
Scrapling's Adaptor for intelligent CSS/XPath selection.

Scrapling's Adaptor is aware of the DOM tree structure, so its selectors
work even when site class-names change — it finds elements by position and
context, not just exact class strings.
"""

from __future__ import annotations

import logging
import random
import re
from typing import Optional
from urllib.parse import urlparse

from curl_cffi import requests as cfreq

from .parser import ProductData, _PRICE_RE, _SYM

logger = logging.getLogger(__name__)

# Use a different profile than Layer 1's default chrome120
_PROFILES = ["safari17_0", "edge101", "firefox121", "chrome110"]

_PRICE_SELECTORS = [
    "[itemprop='price']",
    "[data-price]",
    "[class*='price']",
    "[class*='Price']",
    "[class*='amount']",
]

_NAME_SELECTORS = [
    "h1[itemprop='name']",
    "[data-testid*='title']",
    "[data-testid*='name']",
    "h1",
]

_IMAGE_SELECTORS = [
    "img[itemprop='image']",
    "img[class*='product']",
    "img[class*='hero']",
    "img[id*='product']",
]


def _headers(url: str) -> dict:
    netloc = urlparse(url)
    return {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": f"{netloc.scheme}://{netloc.netloc}/",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
    }


def _fetch(url: str) -> Optional[str]:
    profile = random.choice(_PROFILES)
    logger.info("[L2] fetching with curl-cffi profile=%s", profile)
    try:
        resp = cfreq.get(
            url,
            impersonate=profile,
            headers=_headers(url),
            timeout=20,
            allow_redirects=True,
        )
        if resp.status_code in {403, 429, 503}:
            logger.warning("[L2] blocked status=%d", resp.status_code)
            return None
        return resp.text
    except Exception as exc:
        logger.warning("[L2] fetch error: %s", exc)
        return None


def _css_text(page, *selectors) -> Optional[str]:
    for sel in selectors:
        el = page.css_first(sel)
        if el:
            val = (
                el.attrib.get("content")
                or el.attrib.get("data-price")
                or el.text
                or ""
            ).strip()
            if val:
                return val
    return None


def _extract_price(page) -> tuple[Optional[str], Optional[str]]:
    for sel in _PRICE_SELECTORS:
        el = page.css_first(sel)
        if not el:
            continue
        text = (
            el.attrib.get("data-price")
            or el.attrib.get("content")
            or el.text
            or ""
        )
        m = _PRICE_RE.search(text)
        if m:
            amount = m.group("amount").replace(",", "")
            sym = m.group("sym") or ""
            code = m.group("code") or _SYM.get(sym)
            return amount, (code.upper() if code else None)
    return None, None


def _extract_image(page) -> Optional[str]:
    og = page.css_first("meta[property='og:image']")
    if og:
        return og.attrib.get("content")
    for sel in _IMAGE_SELECTORS:
        el = page.css_first(sel)
        if el:
            src = (
                el.attrib.get("src")
                or el.attrib.get("data-src")
                or el.attrib.get("data-lazy-src")
            )
            if src and src.startswith("http"):
                return src
    return None


def _extract_name(page) -> Optional[str]:
    og = page.css_first("meta[property='og:title']")
    if og:
        val = og.attrib.get("content", "").strip()
        if val:
            return val
    return _css_text(page, *_NAME_SELECTORS)


def scrape(url: str) -> Optional[ProductData]:
    """
    Fetch with curl-cffi (alternate profile), parse with Scrapling Adaptor.
    Returns ProductData or None on failure.
    """
    try:
        from scrapling import Adaptor
    except ImportError:
        logger.error("[L2] scrapling not installed")
        return None

    html = _fetch(url)
    if not html or len(html.strip()) < 500:
        return None

    page = Adaptor(html, url=url)

    name = _extract_name(page)
    price, currency = _extract_price(page)
    image = _extract_image(page)

    data = ProductData(
        name=name,
        price=price,
        currency=currency,
        image=image,
        source_layer="scrapling",
    )

    if data.filled() > 0:
        logger.info("[L2] scrapling success — filled=%d/3", data.filled())
        return data

    logger.warning("[L2] scrapling returned no usable fields")
    return None
