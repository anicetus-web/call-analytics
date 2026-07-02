"""
Yandex Cloud Object Storage (S3-compatible) operations.

All paths stored in DB are S3 object keys only (no bucket, no URL).
Full URL assembly: settings.S3_ENDPOINT + "/" + settings.S3_BUCKET + "/" + key

Key format: {S3_KEY_PREFIX}/{call_id}/{filename}
Example:    calls/42/audio.wav
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aioboto3
from botocore.exceptions import ClientError

from config import settings

logger = logging.getLogger(__name__)

_session = aioboto3.Session(
    aws_access_key_id=settings.S3_ACCESS_KEY,
    aws_secret_access_key=settings.S3_SECRET_KEY,
    region_name=settings.S3_REGION,
)


@asynccontextmanager
async def _client() -> AsyncIterator:
    async with _session.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT,
    ) as client:
        yield client


class StorageError(Exception):
    """Raised when an S3 operation fails."""


def build_key(call_id: int, filename: str) -> str:
    """
    Build an S3 object key for a call file.
    Example: build_key(42, "audio.wav") → "calls/42/audio.wav"
    """
    return f"{settings.S3_KEY_PREFIX}/{call_id}/{filename}"


def build_url(key: str) -> str:
    """Build the full public URL for an S3 key."""
    return f"{settings.S3_ENDPOINT.rstrip('/')}/{settings.S3_BUCKET}/{key}"


async def upload_file(local_path: str, key: str) -> None:
    """
    Upload a local file to S3 at the given key.
    Raises StorageError on failure.
    """
    try:
        async with _client() as client:
            await client.upload_file(
                Filename=local_path,
                Bucket=settings.S3_BUCKET,
                Key=key,
            )
        logger.info("Uploaded %s → s3://%s/%s", local_path, settings.S3_BUCKET, key)
    except ClientError as exc:
        raise StorageError(f"S3 upload failed for key '{key}': {exc}") from exc


async def download_file(key: str, local_path: str) -> None:
    """
    Download an S3 object to a local path.
    Raises StorageError if the key does not exist or download fails.
    """
    try:
        async with _client() as client:
            await client.download_file(
                Bucket=settings.S3_BUCKET,
                Key=key,
                Filename=local_path,
            )
        logger.info("Downloaded s3://%s/%s → %s", settings.S3_BUCKET, key, local_path)
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        if error_code == "404":
            raise StorageError(f"S3 key not found: '{key}'") from exc
        raise StorageError(f"S3 download failed for key '{key}': {exc}") from exc


async def generate_presigned_url(key: str, expires_in: int = 3600) -> str:
    """
    Generate a pre-signed URL to allow temporary access to a private S3 object.
    Used by the web UI to let admins listen to call recordings.
    expires_in: seconds until the URL expires (default 1 hour).
    """
    try:
        async with _client() as client:
            url: str = await client.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.S3_BUCKET, "Key": key},
                ExpiresIn=expires_in,
            )
        return url
    except ClientError as exc:
        raise StorageError(
            f"Failed to generate presigned URL for key '{key}': {exc}"
        ) from exc


async def delete_file(key: str) -> None:
    """
    Delete an S3 object. Silently succeeds if the key does not exist
    (S3 delete is idempotent).
    """
    try:
        async with _client() as client:
            await client.delete_object(Bucket=settings.S3_BUCKET, Key=key)
        logger.info("Deleted s3://%s/%s", settings.S3_BUCKET, key)
    except ClientError as exc:
        raise StorageError(f"S3 delete failed for key '{key}': {exc}") from exc
