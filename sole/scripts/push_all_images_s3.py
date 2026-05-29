#!/usr/bin/env python
"""
Push every ScrapedProduct image URL to S3 and write the permanent S3 URL
back to ScrapedProduct.image_s3.

Run from the sole project root (where manage.py lives):

    python scripts/push_all_images_s3.py

Flags:
    --dry-run     Print what would be uploaded without touching S3 or the DB.
    --limit N     Process at most N products (useful for testing).
    --expires N   Presigned URL lifetime in seconds used for the terminal
                  output only (default 3600). The value stored in image_s3
                  is always the permanent public S3 URL.
"""

import argparse
import hashlib
import os
import sys
import time

# Bootstrap Django before importing any app code.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sole.settings")

import django
django.setup()

from scraper.models import ScrapedProduct
from scraper.services.pipeline import _ext_from_url, _fetch_image
from utils.s3 import S3Client, S3Error


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run",  action="store_true",
                   help="Print what would be processed; do not upload or update DB.")
    p.add_argument("--limit",    type=int, default=None, metavar="N",
                   help="Stop after N products.")
    p.add_argument("--expires",  type=int, default=3600, metavar="SECONDS",
                   help="Presigned URL lifetime for terminal output (default 3600).")
    return p.parse_args()


# ── Formatting helpers ────────────────────────────────────────────────────────

def _trunc(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 1] + "…"

def _col(text: str, width: int) -> str:
    return _trunc(str(text), width).ljust(width)

HEADER  = f"{'ID':>5}  {'Name':<35}  {'Status':<10}  S3 URL"
DIVIDER = "-" * 120

_CONTENT_TYPE_TO_EXT = {
    "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png",
    "image/webp": "webp", "image/gif": "gif", "image/avif": "avif",
    "image/svg+xml": "svg",
}


# ── Core upload logic ─────────────────────────────────────────────────────────

def _upload_and_save(product: ScrapedProduct, s3: S3Client, expires_in: int) -> tuple[str, str]:
    """
    Upload product.image to S3, save public URL to product.image_s3, and
    return (status, display_url) where status is 'uploaded' or 'cached'.

    Raises S3Error or urllib.error.URLError on failure.
    """
    url_hash = hashlib.sha256(product.image.encode()).hexdigest()
    ext      = _ext_from_url(product.image)
    s3_key   = f"images/{url_hash[:2]}/{url_hash}.{ext}"

    image_bytes, content_type = _fetch_image(product.image)

    resolved_ext = _CONTENT_TYPE_TO_EXT.get(content_type.split(";")[0].strip().lower())
    if resolved_ext and resolved_ext != ext:
        s3_key = f"images/{url_hash[:2]}/{url_hash}.{resolved_ext}"

    s3.upload_bytes(image_bytes, s3_key, content_type=content_type)

    public_url = s3.public_url(s3_key)
    ScrapedProduct.objects.filter(pk=product.pk).update(image_s3=public_url)
    return "uploaded", public_url


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    s3   = S3Client()

    qs = (
        ScrapedProduct.objects
        .exclude(image__isnull=True)
        .exclude(image="")
        .order_by("id")
    )
    if args.limit:
        qs = qs[: args.limit]

    total = qs.count()
    if total == 0:
        print("No products with an image URL found — nothing to do.")
        return

    print(f"\nPushing {total} image(s) to S3"
          + (" [DRY RUN — no uploads, no DB writes]" if args.dry_run else "") + "\n")
    print(HEADER)
    print(DIVIDER)

    uploaded = 0
    cached   = 0
    failed   = 0
    t_start  = time.monotonic()

    for product in qs:
        pid  = product.id
        name = product.name or "—"

        if args.dry_run:
            already = "has s3" if product.image_s3 else "no s3 yet"
            print(f"{pid:>5}  {_col(name, 35)}  {'DRY-RUN':<10}  [{already}]  {_trunc(product.image, 70)}")
            continue

        try:
            status, display_url = _upload_and_save(product, s3, args.expires)
            if status == "uploaded":
                uploaded += 1
            else:
                cached += 1
            print(f"{pid:>5}  {_col(name, 35)}  {status:<10}  {display_url}")

        except Exception as exc:
            failed += 1
            print(f"{pid:>5}  {_col(name, 35)}  {'FAILED':<10}  {exc}")

    elapsed = time.monotonic() - t_start
    print(DIVIDER)

    if args.dry_run:
        already_done = sum(1 for p in qs if p.image_s3)
        print(f"\nDry run complete — {already_done}/{total} already have image_s3 set.")
    else:
        print(
            f"\nDone in {elapsed:.1f}s — "
            f"{uploaded} uploaded, {cached} cached, {failed} failed."
        )

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
