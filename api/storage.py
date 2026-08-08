"""Cloudflare R2 storage for the generated report PDFs.

R2 is S3-compatible, so this is just boto3 pointed at the R2 endpoint.
Objects are laid out as ``packs/<snapshot_date>/<pack_id>/<filename>`` and
handed to the browser as short-lived presigned URLs, so the bucket itself
stays private.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

import boto3
from botocore.config import Config

from api.settings import DOWNLOAD_URL_TTL_SECONDS

_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".png": "image/png",
    ".csv": "text/csv",
}


def _client():
    """Create a boto3 S3 client configured for Cloudflare R2."""
    account_id = os.environ["R2_ACCOUNT_ID"]
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def _bucket() -> str:
    return os.getenv("R2_BUCKET_NAME", "stock-reports")


def upload_pack_file(snapshot_date: str, pack_id: str, file_path: Path) -> str:
    """Upload one report file and return its R2 object key."""
    key = f"packs/{snapshot_date}/{pack_id}/{file_path.name}"
    content_type = _CONTENT_TYPES.get(file_path.suffix.lower(), "application/octet-stream")

    _client().upload_file(
        str(file_path),
        _bucket(),
        key,
        ExtraArgs={"ContentType": content_type},
    )
    return key


def get_download_url(key: str, filename: str | None = None) -> str:
    """Presigned GET URL for an R2 object.

    ``filename`` sets a Content-Disposition so the browser saves the file
    under a friendly name rather than the full object key.
    """
    params: Dict[str, str] = {"Bucket": _bucket(), "Key": key}
    if filename:
        params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'

    return _client().generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=DOWNLOAD_URL_TTL_SECONDS,
    )
