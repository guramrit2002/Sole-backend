"""
S3 utility for Sole.

Usage:
    from utils.s3 import S3Client, S3Error

    s3 = S3Client()
    s3.upload_file(open('shoe.jpg', 'rb'), 'shoes/123.jpg', content_type='image/jpeg', public=True)
    url = s3.public_url('shoes/123.jpg')

Settings required in Django settings.py (all read from environment):
    AWS_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY
    AWS_S3_BUCKET_NAME
    AWS_S3_REGION          (default: us-east-1)
    AWS_S3_KEY_PREFIX      (optional, prepended to every key)
    AWS_S3_ENDPOINT_URL    (optional, for MinIO / localstack)
"""

import io
import logging
from typing import IO, Optional

import boto3
import botocore.config
import botocore.exceptions
from django.conf import settings

logger = logging.getLogger(__name__)


class S3Error(Exception):
    """Raised when any S3 operation fails."""


class S3Client:
    """
    Thin wrapper around boto3 S3 that reads credentials from Django settings,
    normalises keys, and converts botocore exceptions into S3Error.

    One instance per process is sufficient; the underlying boto3 client is
    thread-safe for read operations and reused across calls.
    """

    def __init__(self) -> None:
        self._bucket: str = getattr(settings, 'AWS_S3_BUCKET_NAME', '')
        self._region: str = getattr(settings, 'AWS_S3_REGION', 'us-east-1')
        self._prefix: str = getattr(settings, 'AWS_S3_KEY_PREFIX', '').rstrip('/')
        self._endpoint: Optional[str] = getattr(settings, 'AWS_S3_ENDPOINT_URL', None)
        self._boto_client = None  # lazy-initialised

    # ── Private helpers ───────────────────────────────────────────────────────

    @property
    def _client(self):
        """Lazy-create and cache the boto3 S3 client."""
        if self._boto_client is None:
            # Use virtual-hosted-style URLs (bucket.s3.region.amazonaws.com)
            # and SigV4 — required for all non-us-east-1 regions.
            # Only set endpoint_url for custom overrides (MinIO / LocalStack).
            kwargs = dict(
                region_name=self._region,
                aws_access_key_id=getattr(settings, 'AWS_ACCESS_KEY_ID', None),
                aws_secret_access_key=getattr(settings, 'AWS_SECRET_ACCESS_KEY', None),
                config=botocore.config.Config(
                    signature_version='s3v4',
                    s3={'addressing_style': 'virtual'},
                ),
            )
            if self._endpoint:
                kwargs['endpoint_url'] = self._endpoint
            self._boto_client = boto3.client('s3', **kwargs)
        return self._boto_client

    def _build_key(self, key: str) -> str:
        """Prepend the configured key prefix, normalising slashes."""
        key = key.lstrip('/')
        if self._prefix:
            return f'{self._prefix}/{key}'
        return key

    def _resolve_acl(self, public: bool) -> str:
        return 'public-read' if public else 'private'

    def _handle_error(self, exc: Exception, context: str) -> None:
        """Convert a botocore exception into S3Error and re-raise."""
        if isinstance(exc, botocore.exceptions.ClientError):
            code = exc.response['Error']['Code']
            msg  = exc.response['Error']['Message']
            raise S3Error(f'{context}: [{code}] {msg}') from exc
        raise S3Error(f'{context}: {exc}') from exc

    def _put_object(
        self,
        body: bytes,
        key: str,
        content_type: Optional[str],
        public: bool,
    ) -> None:
        """Internal single-path for all uploads."""
        full_key = self._build_key(key)
        extra: dict = {}
        if public:
            extra['ACL'] = self._resolve_acl(public)
        if content_type:
            extra['ContentType'] = content_type
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=full_key,
                Body=body,
                **extra,
            )
            logger.debug('s3 put %s/%s', self._bucket, full_key)
        except Exception as exc:
            self._handle_error(exc, f'upload {full_key}')

    # ── Public API ────────────────────────────────────────────────────────────

    def upload_file(
        self,
        file_obj: IO[bytes],
        key: str,
        *,
        content_type: Optional[str] = None,
        public: bool = False,
    ) -> None:
        """
        Upload a file-like object to S3.

        Args:
            file_obj:     Any readable binary stream (open file, BytesIO, …).
            key:          Destination key relative to the configured prefix.
            content_type: MIME type (e.g. 'image/jpeg'). Detected from the
                          stream is attempted when omitted.
            public:       If True, object is world-readable (public-read ACL).

        Raises:
            S3Error: on any upload failure.
        """
        self._put_object(file_obj.read(), key, content_type, public)

    def upload_bytes(
        self,
        data: bytes,
        key: str,
        *,
        content_type: Optional[str] = None,
        public: bool = False,
    ) -> None:
        """
        Upload raw bytes to S3.

        Args:
            data:         Bytes to upload.
            key:          Destination key relative to the configured prefix.
            content_type: MIME type.
            public:       If True, object is world-readable.

        Raises:
            S3Error: on any upload failure.
        """
        self._put_object(data, key, content_type, public)

    def download_bytes(self, key: str) -> bytes:
        """
        Download an object and return its contents as bytes.

        Args:
            key: Key relative to the configured prefix.

        Returns:
            Raw bytes of the object body.

        Raises:
            S3Error: if the object does not exist or download fails.
        """
        full_key = self._build_key(key)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=full_key)
            return response['Body'].read()
        except Exception as exc:
            self._handle_error(exc, f'download {full_key}')

    def delete(self, key: str) -> None:
        """
        Delete an object from S3. No-ops silently if the key does not exist.

        Args:
            key: Key relative to the configured prefix.

        Raises:
            S3Error: on unexpected errors.
        """
        full_key = self._build_key(key)
        try:
            self._client.delete_object(Bucket=self._bucket, Key=full_key)
            logger.debug('s3 delete %s/%s', self._bucket, full_key)
        except Exception as exc:
            self._handle_error(exc, f'delete {full_key}')

    def exists(self, key: str) -> bool:
        """
        Check whether an object exists in S3.

        Args:
            key: Key relative to the configured prefix.

        Returns:
            True if the object exists, False if it does not.

        Raises:
            S3Error: on unexpected errors (not a 404).
        """
        full_key = self._build_key(key)
        try:
            self._client.head_object(Bucket=self._bucket, Key=full_key)
            return True
        except botocore.exceptions.ClientError as exc:
            if exc.response['Error']['Code'] in ('404', 'NoSuchKey'):
                return False
            self._handle_error(exc, f'exists check {full_key}')
        except Exception as exc:
            self._handle_error(exc, f'exists check {full_key}')

    def list_keys(self, prefix: str = '') -> list[str]:
        """
        List all object keys under a given prefix.

        Args:
            prefix: Sub-prefix to filter on (combined with the configured
                    key prefix). Pass '' to list everything in the bucket prefix.

        Returns:
            List of full keys (including the configured prefix).

        Raises:
            S3Error: on pagination or permission errors.
        """
        search_prefix = self._build_key(prefix) if prefix else (self._prefix or '')
        keys: list[str] = []
        paginator = self._client.get_paginator('list_objects_v2')
        try:
            for page in paginator.paginate(Bucket=self._bucket, Prefix=search_prefix):
                for obj in page.get('Contents', []):
                    keys.append(obj['Key'])
        except Exception as exc:
            self._handle_error(exc, f'list {search_prefix}')
        return keys

    def copy(self, source_key: str, dest_key: str, *, public: bool = False) -> None:
        """
        Copy an object within the same bucket.

        Args:
            source_key: Source key relative to the configured prefix.
            dest_key:   Destination key relative to the configured prefix.
            public:     If True, the copy gets a public-read ACL.

        Raises:
            S3Error: if the source does not exist or the copy fails.
        """
        full_source = self._build_key(source_key)
        full_dest   = self._build_key(dest_key)
        extra: dict = {'ACL': self._resolve_acl(public)}
        try:
            self._client.copy_object(
                Bucket=self._bucket,
                CopySource={'Bucket': self._bucket, 'Key': full_source},
                Key=full_dest,
                **extra,
            )
            logger.debug('s3 copy %s -> %s', full_source, full_dest)
        except Exception as exc:
            self._handle_error(exc, f'copy {full_source} -> {full_dest}')

    def public_url(self, key: str) -> str:
        """
        Return the public HTTPS URL for an object.

        The object must have been uploaded with public=True.

        Args:
            key: Key relative to the configured prefix.

        Returns:
            Public URL string.
        """
        full_key = self._build_key(key)
        if self._endpoint:
            return f'{self._endpoint.rstrip("/")}/{self._bucket}/{full_key}'
        return (
            f'https://{self._bucket}.s3.{self._region}.amazonaws.com/{full_key}'
        )

    def presigned_get_url(self, key: str, expires_in: int = 3600) -> str:
        """
        Generate a presigned GET URL for a private object.

        Args:
            key:        Key relative to the configured prefix.
            expires_in: Seconds until the URL expires (default 1 hour).

        Returns:
            Presigned URL string valid for `expires_in` seconds.

        Raises:
            S3Error: if URL generation fails.
        """
        full_key = self._build_key(key)
        try:
            return self._client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self._bucket, 'Key': full_key},
                ExpiresIn=expires_in,
            )
        except Exception as exc:
            self._handle_error(exc, f'presigned GET {full_key}')

    def presigned_upload_url(
        self,
        key: str,
        *,
        content_type: Optional[str] = None,
        expires_in: int = 3600,
    ) -> dict:
        """
        Generate a presigned POST policy for direct browser-to-S3 uploads.

        The returned dict has 'url' and 'fields' keys that should be forwarded
        to the client and used as a multipart POST form.

        Args:
            key:          Destination key relative to the configured prefix.
            content_type: Restrict the upload to this MIME type when provided.
            expires_in:   Seconds until the policy expires (default 1 hour).

        Returns:
            {'url': str, 'fields': dict}

        Raises:
            S3Error: if policy generation fails.
        """
        full_key = self._build_key(key)
        conditions = []
        if content_type:
            conditions.append(['eq', '$Content-Type', content_type])
        try:
            return self._client.generate_presigned_post(
                Bucket=self._bucket,
                Key=full_key,
                Conditions=conditions or None,
                ExpiresIn=expires_in,
            )
        except Exception as exc:
            self._handle_error(exc, f'presigned POST {full_key}')

    def set_public_read_policy(self, key_prefix: str) -> None:
        """
        Apply a bucket policy that grants anonymous s3:GetObject on all keys
        under key_prefix (e.g. 'Sole/images').

        Safe to call repeatedly — merges with any existing policy statements
        that have the same Sid, then replaces the full policy.

        Args:
            key_prefix: S3 key prefix to make publicly readable (no leading slash).

        Raises:
            S3Error: if the policy cannot be applied.
        """
        import json

        resource = f'arn:aws:s3:::{self._bucket}/{key_prefix.strip("/")}/*'
        sid = 'SolePublicRead'

        try:
            existing_raw = self._client.get_bucket_policy(Bucket=self._bucket)['Policy']
            policy = json.loads(existing_raw)
        except botocore.exceptions.ClientError as exc:
            if exc.response['Error']['Code'] == 'NoSuchBucketPolicy':
                policy = {'Version': '2012-10-17', 'Statement': []}
            else:
                self._handle_error(exc, 'get_bucket_policy')

        policy['Statement'] = [s for s in policy['Statement'] if s.get('Sid') != sid]
        policy['Statement'].append({
            'Sid': sid,
            'Effect': 'Allow',
            'Principal': '*',
            'Action': 's3:GetObject',
            'Resource': resource,
        })

        try:
            self._client.put_bucket_policy(
                Bucket=self._bucket,
                Policy=json.dumps(policy),
            )
            logger.info('Public read policy set for %s/%s', self._bucket, key_prefix)
        except Exception as exc:
            self._handle_error(exc, f'set_public_read_policy on {self._bucket}')

    def set_cors(self, allowed_origins: list[str]) -> None:
        """
        Apply a CORS configuration to the bucket that allows browsers to
        GET/HEAD objects from the given origins.

        Safe to call repeatedly — each call overwrites the existing CORS rules.

        Args:
            allowed_origins: List of allowed origins, e.g.
                             ['http://localhost:5174', 'https://sole.app'].
                             Pass ['*'] to allow any origin.

        Raises:
            S3Error: if the bucket policy cannot be updated.
        """
        cors_config = {
            'CORSRules': [
                {
                    'AllowedOrigins': allowed_origins,
                    'AllowedMethods': ['GET', 'HEAD'],
                    'AllowedHeaders': ['*'],
                    'ExposeHeaders':  ['ETag', 'Content-Type', 'Content-Length'],
                    'MaxAgeSeconds':  86400,
                }
            ]
        }
        try:
            self._client.put_bucket_cors(
                Bucket=self._bucket,
                CORSConfiguration=cors_config,
            )
            logger.info('CORS updated for bucket %s: %s', self._bucket, allowed_origins)
        except Exception as exc:
            self._handle_error(exc, f'set_cors on {self._bucket}')
