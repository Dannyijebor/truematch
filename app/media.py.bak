"""Presigned R2 uploads — bypasses Vercel's 4.5 MB body limit."""
import os
import uuid
from datetime import datetime, timezone
import boto3
from botocore.config import Config


ALLOWED_IMAGE = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_VIDEO = {"video/mp4", "video/webm", "video/quicktime"}

MAX_IMAGE_BYTES = 15 * 1024 * 1024        # 15 MB
MAX_VIDEO_BYTES = 70 * 1024 * 1024        # 70 MB


def _client():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("R2_ENDPOINT"),
        aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        region_name="auto",
    )


def _public_url(key: str) -> str:
    base = (os.getenv("R2_PUBLIC_URL") or "").rstrip("/")
    return f"{base}/{key}"


def _ext_from_mime(mime: str) -> str:
    return {
        "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif",
        "video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov",
    }.get(mime, "bin")


def presign_upload(user_id, filename: str, content_type: str, size: int, kind: str) -> dict:
    """Returns {upload_url, public_url, key} or raises ValueError."""
    if kind == "image":
        if content_type not in ALLOWED_IMAGE:
            raise ValueError("unsupported image type")
        if size > MAX_IMAGE_BYTES:
            raise ValueError(f"image too large (max {MAX_IMAGE_BYTES // 1024 // 1024} MB)")
    elif kind == "video":
        if content_type not in ALLOWED_VIDEO:
            raise ValueError("unsupported video type")
        if size > MAX_VIDEO_BYTES:
            raise ValueError(f"video too large (max {MAX_VIDEO_BYTES // 1024 // 1024} MB)")
    else:
        raise ValueError("kind must be image or video")

    ext = _ext_from_mime(content_type)
    year_month = datetime.now(timezone.utc).strftime("%Y/%m")
    key = f"u/{user_id}/{kind}/{year_month}/{uuid.uuid4().hex}.{ext}"

    client = _client()
    bucket = os.getenv("R2_BUCKET")

    upload_url = client.generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket": bucket,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=600,  # 10 minutes
    )

    return {
        "upload_url": upload_url,
        "public_url": _public_url(key),
        "key": key,
        "expires_in": 600,
    }


def delete_object(public_url: str):
    """Best-effort delete of an object given its public URL."""
    base = (os.getenv("R2_PUBLIC_URL") or "").rstrip("/")
    if not base or not public_url or not public_url.startswith(base + "/"):
        return
    key = public_url[len(base) + 1:]
    try:
        _client().delete_object(Bucket=os.getenv("R2_BUCKET"), Key=key)
    except Exception:
        pass
