#!/usr/bin/env python
"""
Apply CORS rules to the S3 bucket so browsers can load images directly.

Run from the sole project root (where manage.py lives):

    python scripts/configure_s3_cors.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sole.settings")

import django
django.setup()

from utils.s3 import S3Client, S3Error
from django.conf import settings

ALLOWED_ORIGINS = [
    "*",
]

PUBLIC_IMAGE_PREFIX = f"{settings.AWS_S3_KEY_PREFIX}/images".strip("/")

def main() -> None:
    s3 = S3Client()
    print(f"Applying CORS to bucket: {s3._bucket}")
    print(f"Allowed origins: {ALLOWED_ORIGINS}")
    try:
        s3.set_cors(ALLOWED_ORIGINS)
        print("CORS configured successfully.")
    except S3Error as e:
        print(f"CORS failed: {e}")
        sys.exit(1)

    print(f"\nApplying public-read bucket policy for prefix: {PUBLIC_IMAGE_PREFIX}")
    try:
        s3.set_public_read_policy(PUBLIC_IMAGE_PREFIX)
        print("Bucket policy configured successfully.")
    except S3Error as e:
        print(f"Bucket policy failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
