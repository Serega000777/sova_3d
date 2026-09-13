"""S3-compatible object storage adapter (T-011).

The API process never streams model binaries itself: clients upload and
download through short-lived presigned URLs. Keys are content-addressed
under a workspace prefix so cross-workspace access is impossible by
construction and identical uploads dedupe within the privacy boundary.
"""

import hashlib
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from app.config import Settings

DEFAULT_PRESIGN_TTL_SECONDS = 15 * 60
DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ObjectInfo:
    key: str
    byte_size: int
    content_type: str | None
    etag: str


class StorageError(Exception):
    pass


class ObjectNotFoundError(StorageError):
    pass


class ObjectStorage(Protocol):
    def object_key(self, workspace_id: uuid.UUID, sha256: str, extension: str) -> str: ...
    def upload_key(self, workspace_id: uuid.UUID, upload_id: uuid.UUID) -> str: ...
    def put(self, key: str, data: bytes, content_type: str) -> ObjectInfo: ...
    def get(self, key: str) -> bytes: ...
    def iter_chunks(self, key: str, chunk_size: int = ...) -> Iterator[bytes]: ...
    def head(self, key: str) -> ObjectInfo: ...
    def delete(self, key: str) -> None: ...
    def copy(self, source_key: str, dest_key: str) -> ObjectInfo: ...
    def presign_put(
        self, key: str, content_type: str, byte_size: int, ttl_seconds: int = ...
    ) -> str: ...
    def presign_get(self, key: str, ttl_seconds: int = ...) -> str: ...


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class S3Storage:
    """boto3-backed implementation; works against MinIO locally and AWS/compatible in prod."""

    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.s3_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            # path-style keeps MinIO and bucket names with dots working.
            config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    # --- key layout ------------------------------------------------------------------------

    @staticmethod
    def object_key(workspace_id: uuid.UUID, sha256: str, extension: str) -> str:
        ext = extension.lstrip(".").lower()
        return f"ws/{workspace_id}/assets/{sha256[:2]}/{sha256}.{ext}"

    @staticmethod
    def upload_key(workspace_id: uuid.UUID, upload_id: uuid.UUID) -> str:
        # Staging area for presigned uploads until the hash is verified (T-013).
        return f"ws/{workspace_id}/uploads/{upload_id}"

    # --- operations ------------------------------------------------------------------------

    def put(self, key: str, data: bytes, content_type: str) -> ObjectInfo:
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        return self.head(key)

    def get(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            raise self._translate(exc, key) from exc
        body: bytes = response["Body"].read()
        return body

    def iter_chunks(self, key: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Iterator[bytes]:
        """Stream an object without holding it in memory (hashing multi-hundred-MB uploads)."""
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            raise self._translate(exc, key) from exc
        yield from response["Body"].iter_chunks(chunk_size)

    def head(self, key: str) -> ObjectInfo:
        try:
            response = self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            raise self._translate(exc, key) from exc
        return ObjectInfo(
            key=key,
            byte_size=int(response["ContentLength"]),
            content_type=response.get("ContentType"),
            etag=response["ETag"].strip('"'),
        )

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)

    def copy(self, source_key: str, dest_key: str) -> ObjectInfo:
        try:
            self._client.copy_object(
                Bucket=self.bucket,
                Key=dest_key,
                CopySource={"Bucket": self.bucket, "Key": source_key},
            )
        except ClientError as exc:
            raise self._translate(exc, source_key) from exc
        return self.head(dest_key)

    def presign_put(
        self,
        key: str,
        content_type: str,
        byte_size: int,
        ttl_seconds: int = DEFAULT_PRESIGN_TTL_SECONDS,
    ) -> str:
        # Signing ContentType/ContentLength binds the URL to the declared upload,
        # so a client cannot reuse it for a different payload shape.
        url: str = self._client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ContentType": content_type,
                "ContentLength": byte_size,
            },
            ExpiresIn=ttl_seconds,
            HttpMethod="PUT",
        )
        return url

    def presign_get(self, key: str, ttl_seconds: int = DEFAULT_PRESIGN_TTL_SECONDS) -> str:
        url: str = self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=ttl_seconds,
        )
        return url

    @staticmethod
    def _translate(exc: ClientError, key: str) -> StorageError:
        error = exc.response.get("Error", {})
        code = error.get("Code")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return ObjectNotFoundError(key)
        return StorageError(f"{code}: {error.get('Message')}")
