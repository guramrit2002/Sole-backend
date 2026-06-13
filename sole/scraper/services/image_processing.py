"""
Background removal for scraped product images.

Uses rembg (ONNX U2Net model) to cut the product out of its source photo
and return a transparent PNG, so shoes render cleanly on Sole's own
backgrounds (story cards, collection grids, etc).
"""

from __future__ import annotations

import io
import logging

from rembg import remove

logger = logging.getLogger(__name__)


def remove_background(image_bytes: bytes) -> bytes:
    """
    Strip the background from a product image.

    Args:
        image_bytes: Raw bytes of the source image (jpg/png/webp/...).

    Returns:
        PNG bytes with the background removed (alpha transparency).
        Returns the original bytes unchanged if background removal fails.
    """
    try:
        return remove(image_bytes)
    except Exception as exc:
        logger.warning("background removal failed, using original image: %s", exc)
        return image_bytes
