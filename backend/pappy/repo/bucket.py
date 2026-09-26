"""S3 bucket access for generated documents (design-doc.md §2.2, §7.3).

Provides two transports, selected by environment variables — mirroring the
pattern used by `pappy.mailer` (SES vs log):

- **S3** (deployed / moto in tests): `PAPPY_DOCUMENTS_BUCKET_NAME` is set;
  objects are stored and pre-signed URLs generated via boto3.
- **Local file system** (local dev without S3): when the bucket name is
  unset, documents are written under `PAPPY_DOCUMENTS_DIR` (default
  `./documents`). Pre-signed URLs are replaced by plain local file paths.
  This keeps `docker compose up` useful without provisioning an S3 bucket.

Bucket configuration:
- `PAPPY_DOCUMENTS_BUCKET_NAME` — S3 bucket (deployed / tests)
- `PAPPY_DOCUMENTS_DIR` — local directory fallback (dev)
- `PAPPY_S3_ENDPOINT_URL` — for DynamoDB Local / LocalStack / moto
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import boto3


class Bucket:
    """Thin abstraction over S3 (deployed / tests) or the local file system
    (dev fallback).

    Every method is stateless — no cached clients, so tests using moto's
    `mock_aws` context get a fresh client bound to the mock backend each
    time.
    """

    def __init__(self) -> None:
        self._bucket_name = os.environ.get("PAPPY_DOCUMENTS_BUCKET_NAME", "")
        self._local_dir = Path(
            os.environ.get("PAPPY_DOCUMENTS_DIR", "./documents")
        ).resolve()
        self._endpoint_url = os.environ.get("PAPPY_S3_ENDPOINT_URL")
        self._region = (
            os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or "us-west-2"
        )

    @property
    def is_s3(self) -> bool:
        return bool(self._bucket_name)

    def _s3_client(self) -> Any:
        return boto3.client(
            "s3",
            region_name=self._region,
            endpoint_url=self._endpoint_url,
        )

    def put(self, key: str, data: bytes, content_type: str = "application/pdf") -> str:
        """Store an object and return its SHA-256 hex digest."""
        sha = hashlib.sha256(data).hexdigest()
        if self.is_s3:
            self._s3_client().put_object(
                Bucket=self._bucket_name,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        else:
            path = self._local_dir / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return sha

    def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Return a time-limited download URL for the object.

        Under the local file-system fallback this returns a ``file://``
        URL (only useful for local testing / debugging; the SPA won't
        fetch it, but it exercises the code path).
        """
        if self.is_s3:
            url: str = self._s3_client().generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket_name, "Key": key},
                ExpiresIn=expires_in,
            )
            return url
        path = self._local_dir / key
        return path.as_uri()


def get_bucket() -> Bucket:
    """Create a bucket bound to the current environment configuration."""
    return Bucket()
