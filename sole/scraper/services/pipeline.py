"""
Scraping pipeline — orchestrates Layer 1 → 2 → 3.

Rules:
- A layer's result is accepted if it has at least 2 of 3 fields (name/price/image).
- A complete result (all 3) short-circuits immediately.
- Each successive layer is only attempted if the previous one failed or was incomplete.
- The best partial result is returned if no layer achieves completeness.
"""

from __future__ import annotations

import hashlib
import logging
import urllib.request
from typing import Optional
from urllib.parse import urlparse

from . import layer1, layer2, layer3
from .parser import ProductData
from utils.s3 import S3Client, S3Error


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

_CONTENT_TYPE_TO_EXT = {
    "image/jpeg":  "jpg",
    "image/jpg":   "jpg",
    "image/png":   "png",
    "image/webp":  "webp",
    "image/gif":   "gif",
    "image/avif":  "avif",
    "image/svg+xml": "svg",
}

_s3 = S3Client()


def store_image(image_url: str, expires_in: int = 3600) -> str:
    """
    Fetch an image URL, upload the content to S3, and return a presigned
    GET URL valid for `expires_in` seconds.

    The S3 key is derived from a SHA-256 of the image URL, so calling this
    function twice with the same URL hits S3 once — the second call skips the
    fetch and upload and goes straight to generating a fresh presigned URL.

    Args:
        image_url:  Public URL of the image to fetch and store.
        expires_in: Seconds the presigned URL should remain valid (default 1 h).

    Returns:
        Presigned HTTPS URL for the stored image.

    Raises:
        ValueError:    If image_url is empty.
        urllib.error.URLError: If the image cannot be fetched.
        S3Error:       If the upload or presigned URL generation fails.
    """
    if not image_url:
        raise ValueError("image_url must not be empty")

    url_hash = hashlib.sha256(image_url.encode()).hexdigest()
    ext      = _ext_from_url(image_url)       # fallback before fetch
    s3_key   = f"images/{url_hash[:2]}/{url_hash}.{ext}"

    if _s3.exists(s3_key):
        logger.debug("image already in S3, skipping upload: %s", s3_key)
        return _s3.presigned_get_url(s3_key, expires_in=expires_in)

    image_bytes, content_type = _fetch_image(image_url)

    # Refine extension now that we have the real content-type
    resolved_ext = _CONTENT_TYPE_TO_EXT.get(content_type.split(";")[0].strip().lower())
    if resolved_ext and resolved_ext != ext:
        s3_key = f"images/{url_hash[:2]}/{url_hash}.{resolved_ext}"

    _s3.upload_bytes(image_bytes, s3_key, content_type=content_type)
    logger.info("stored image %s -> s3://%s", image_url, s3_key)

    return _s3.presigned_get_url(s3_key, expires_in=expires_in)


def _fetch_image(image_url: str) -> tuple[bytes, str]:
    """
    GET the image URL and return (body_bytes, content_type).

    Sends a browser-like Accept header so CDNs serve the right format.
    Falls back to 'application/octet-stream' if the server omits Content-Type.
    """
    req = urllib.request.Request(
        image_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        content_type = resp.headers.get_content_type() or "application/octet-stream"
        return resp.read(), content_type


def _ext_from_url(image_url: str) -> str:
    """
    Derive a file extension from the URL path.
    Returns 'jpg' as a safe fallback when the path has no recognisable extension.
    """
    path = urlparse(image_url).path.lower()
    for ext in ("jpg", "jpeg", "png", "webp", "gif", "avif", "svg"):
        if path.endswith(f".{ext}"):
            return "jpg" if ext == "jpeg" else ext
    return "jpg"
