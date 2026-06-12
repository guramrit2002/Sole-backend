"""
Compatibility wrapper for the backend S3 utilities.

The Django project imports `utils.s3` from `Sole-backend/sole/utils/s3.py`
when commands run from the manage.py directory. This root module re-exports
the same classes for code that imports from the backend repository root.
"""

from sole.utils.s3 import S3Client, S3Error, S3Utility

__all__ = ['S3Client', 'S3Error', 'S3Utility']
