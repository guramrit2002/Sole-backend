"""
Layer 3 — Playwright (full browser rendering)

Last resort. Launches headless Chromium, fully renders the page including
JavaScript, waits for network idle, then extracts from the live DOM.

Covers JS-heavy SPAs (StockX, GOAT, Nike) where the product data is only
present after React/Vue hydration.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .parser import ProductData, parse

logger = logging.getLogger(__name__)

_TIMEOUT_MS = 30_000
_WAIT_AFTER_LOAD_MS = 2_500


async def _render_and_extract(url: str) -> Optional[ProductData]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("[L3] playwright not installed — run: pip install playwright && playwright install chromium")
        return None

    logger.info("[L3] launching Chromium for %s", url)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

        # Mask the webdriver flag that anti-bot systems check
        await ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined })"
        )

        page = await ctx.new_page()
        html = ""

        try:
            await page.goto(url, wait_until="networkidle", timeout=_TIMEOUT_MS)
            # Extra wait for SPA hydration / lazy-loaded price widgets
            await page.wait_for_timeout(_WAIT_AFTER_LOAD_MS)
            html = await page.content()
            logger.info("[L3] page rendered — html_len=%d", len(html))
        except Exception as exc:
            logger.warning("[L3] navigation error: %s — attempting partial extract", exc)
            try:
                html = await page.content()
            except Exception:
                pass
        finally:
            await browser.close()

    if not html or len(html.strip()) < 200:
        logger.warning("[L3] no usable HTML from browser")
        return None

    data = parse(html, source_layer="playwright")
    if data.filled() > 0:
        logger.info("[L3] playwright success — filled=%d/3", data.filled())
        return data

    logger.warning("[L3] playwright rendered page but extracted nothing")
    return None


def scrape(url: str) -> Optional[ProductData]:
    """Synchronous entry point — runs the async renderer safely."""
    try:
        # If we're already inside a running event loop (FastAPI, Jupyter etc.)
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _render_and_extract(url))
            return future.result()

    return asyncio.run(_render_and_extract(url))
