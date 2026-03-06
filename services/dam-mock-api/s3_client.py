"""
DAM Mock API — S3 Client
Same async wrapper pattern as PLM/PIM (run_in_executor to prevent event-loop blocking).

Security (OWASP A03 / path traversal): all S3 keys are sanitized via
_safe_key() before use — directory components are stripped.

Required environment variables (no fallback — fail fast per ADR-016):
  S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY
"""

import asyncio
import os
from functools import partial

import boto3
from botocore.exceptions import ClientError


def _get_s3_client():
    """Create a boto3 S3 client from environment variables (no hardcoded fallbacks)."""
    return boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT"],
        aws_access_key_id=os.environ["S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"],
        region_name=os.getenv("S3_REGION", "us-east-1"),
    )


def _safe_key(key: str) -> str:
    """Strip directory components to prevent S3 path traversal."""
    return os.path.basename(key).lstrip("/") or "unnamed"


async def upload_asset(
    bucket: str,
    key: str,
    file_data: bytes,
    content_type: str = "application/octet-stream",
) -> dict:
    """Upload a file to S3 (non-blocking)."""
    safe = _safe_key(key)
    loop = asyncio.get_event_loop()
    client = _get_s3_client()
    await loop.run_in_executor(
        None,
        partial(
            client.put_object,
            Bucket=bucket,
            Key=safe,
            Body=file_data,
            ContentType=content_type,
        ),
    )
    return {"bucket": bucket, "key": safe, "size": len(file_data)}


async def get_presigned_url(bucket: str, key: str, expires_in: int = 900) -> str:
    """Generate a presigned download URL (non-blocking, default 15 min expiry)."""
    safe = _safe_key(key)
    loop = asyncio.get_event_loop()
    client = _get_s3_client()
    return await loop.run_in_executor(
        None,
        partial(
            client.generate_presigned_url,
            "get_object",
            Params={"Bucket": bucket, "Key": safe},
            ExpiresIn=expires_in,
        ),
    )


async def list_assets(bucket: str, prefix: str = "") -> list[dict]:
    """List objects in a bucket with optional prefix filter (non-blocking)."""
    loop = asyncio.get_event_loop()
    client = _get_s3_client()
    try:
        response = await loop.run_in_executor(
            None,
            partial(client.list_objects_v2, Bucket=bucket, Prefix=prefix),
        )
        return [
            {
                "key": obj["Key"],
                "size": obj["Size"],
                "last_modified": obj["LastModified"].isoformat(),
            }
            for obj in response.get("Contents", [])
        ]
    except ClientError:
        return []


async def delete_asset(bucket: str, key: str) -> bool:
    """Delete an object from S3 (non-blocking)."""
    safe = _safe_key(key)
    loop = asyncio.get_event_loop()
    client = _get_s3_client()
    try:
        await loop.run_in_executor(
            None,
            partial(client.delete_object, Bucket=bucket, Key=safe),
        )
        return True
    except ClientError:
        return False
