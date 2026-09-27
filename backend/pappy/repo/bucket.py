"""S3 bucket access for generated documents (design-doc.md §2.2, §7.3).

Provides two transports, selected by environment variables — mirroring the
pattern used by `pappy.mailer` (SES vs log):

- **S3** (deployed / moto in tests): `PAPPY_DOCUMENTS_BUCKET_NAME` is set;
  objects are stored and pre-signed URLs generated via boto3.
- **Local file system** (local dev without S3): when the bucket name is
  unset, documents are written under `PAPPY_DOCUMENTS_DIR` (default
  `./documents`). This keeps `docker compose up` useful without provisioning
  an S3 bucket, but the files are private to whichever filesystem the API
  runs on, so `pappy.services.document_service` serves them back over the
  authenticated `GET /documents/{id}/content` endpoint.

Bucket configuration:
- `PAPPY_DOCUMENTS_BUCKET_NAME` — S3 bucket (deployed / tests)
- `PAPPY_DOCUMENTS_DIR` — local directory fallback (dev)
- `PAPPY_S3_ENDPOINT_URL` — for DynamoDB Local / LocalStack / moto
- `PAPPY_API_BASE_URL` — host-visible base URL of this API, so the local
  transport can hand the SPA a download URL the browser can open
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
            path = self.local_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return sha

    def local_path(self, key: str) -> Path:
        """Filesystem location of `key` under the local transport's root.

        The key is server-generated and stored on the Document record, never
        supplied by a client, but it is still resolved *within* the root: a
        stray `..` segment must not be able to address anything outside
        `PAPPY_DOCUMENTS_DIR` (§7.3).
        """
        root = self._local_dir
        path = (root / key).resolve()
        if path != root and root not in path.parents:
            raise ValueError(f"Document key escapes {root}: {key!r}")
        return path

    def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Return a time-limited download URL for the object.

        S3 mode returns a pre-signed HTTPS URL — the deployed path, where the
        browser talks to S3 directly and never touches the API (§7.3).

        Local mode returns a `file://` URL, which is only meaningful inside the
        process's own filesystem. Under `docker compose` that is the API
        container's `/tmp/pappy-documents`, which the host browser cannot read,
        so `document_service` points local clients at the authenticated
        `GET /documents/{id}/content` endpoint instead of calling this.
        """
        if self.is_s3:
            url: str = self._s3_client().generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket_name, "Key": key},
                ExpiresIn=expires_in,
            )
            return url
        return self.local_path(key).as_uri()


def get_bucket() -> Bucket:
    """Create a bucket bound to the current environment configuration."""
    return Bucket()
