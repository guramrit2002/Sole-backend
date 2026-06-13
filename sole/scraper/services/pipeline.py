"""
Scraping pipeline — orchestrates Layer 1 → 2 → 3.

Rules:
- A layer's result is accepted if it has at least 2 of 3 fields (name/price/image).
- A complete result (all 3) short-circuits immediately.
- Each successive layer is only attempted if the previous one failed or was incomplete.
- The best partial result is returned if no layer achieves completeness.
"""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlparse

from . import layer1, layer2, layer3
from .parser import ProductData
from utils.s3 import S3Client, S3Error, S3Utility


def _merge(base: ProductData, new: ProductData) -> ProductData:
    """Fill None fields in base from new; keep base values where already set."""
    return ProductData(
        name=base.name or new.name,
        price=base.price or new.price,
        currency=base.currency or new.currency,
        image=base.image or new.image,
        source_layer=new.source_layer if new.filled() >= base.filled() else base.source_layer,
    )

logger = logging.getLogger(__name__)

# Only stop early if we have ALL three fields. Otherwise always escalate
# through all layers so JS-rendered prices (e.g. VegNonVeg) are captured.
_ACCEPTANCE_THRESHOLD = 3   # must be complete to short-circuit


def _domain(url: str) -> str:
    return urlparse(url).netloc.replace("www.", "")


def run(url: str) -> Optional[ProductData]:
    """
    Run layers in order, return the best result found.

    Layer 1  curl-cffi  — fast, TLS fingerprint impersonation
    Layer 2  Scrapling  — stealth headers + smart CSS selectors
    Layer 3  Playwright — full browser render (JS SPAs)
    """
    best: Optional[ProductData] = None
    source = _domain(url)

    for layer_name, layer_fn in [
        ("curl-cffi", layer1.scrape),
        ("scrapling", layer2.scrape),
        ("playwright", layer3.scrape),
    ]:
        logger.info("trying %s for %s", layer_name, source)

        try:
            result = layer_fn(url)
        except Exception as exc:
            logger.error("[%s] unhandled error: %s", layer_name, exc)
            result = None

        if result is None:
            logger.info("[%s] returned nothing — escalating", layer_name)
            continue

        # Merge into best: pick non-None fields from result over best
        if best is None:
            best = result
        else:
            best = _merge(best, result)

        if result.is_complete():
            logger.info("[%s] complete result — done", layer_name)
            return result

        logger.info("[%s] got %d/3 fields — escalating to next layer", layer_name, result.filled())

    if best:
        logger.warning("no layer achieved full extraction — returning best partial (%d/3)", best.filled())

    return best


# ── Image upload ──────────────────────────────────────────────────────────────

_s3 = S3Client()
_s3_utility = S3Utility(_s3)


def store_image(image_url: str, expires_in: int = 3600) -> str:
    """
    Fetch an image URL, upload the content to S3, and return a permanent
    public S3 URL.

    The S3 key is derived from a SHA-256 of the image URL, so calling this
    function twice with the same URL hits S3 once — the second call skips the
    fetch and upload and returns the same public S3 URL.

    Args:
        image_url:  Public URL of the image to fetch and store.
        expires_in: Seconds the presigned URL should remain valid (default 1 h).

    Returns:
        Public HTTPS URL for the stored image.

    Raises:
        ValueError:    If image_url is empty.
        urllib.error.URLError: If the image cannot be fetched.
        S3Error:       If the upload or presigned URL generation fails.
    """
    if not image_url:
        raise ValueError("image_url must not be empty")

    return _s3_utility.store_image_from_url(
        image_url,
        expires_in=expires_in,
        presigned=False,
    )


def _fetch_image(image_url: str) -> tuple[bytes, str]:
    """
    GET the image URL and return (body_bytes, content_type).

    Sends a browser-like Accept header so CDNs serve the right format.
    Falls back to 'application/octet-stream' if the server omits Content-Type.
    """
    return S3Utility.fetch_image(image_url)


def _ext_from_url(image_url: str) -> str:
    """
    Derive a file extension from the URL path.
    Returns 'jpg' as a safe fallback when the path has no recognisable extension.
    """
    return S3Utility.extension_from_url(image_url)
