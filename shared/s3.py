"""S3 storage helpers — per-job object layout.

Keys:  jobs/{job_id}/raw/<filename>      original upload (or nothing for URLs)
       jobs/{job_id}/chunks/<chunk.wav>  audio chunks
       jobs/{job_id}/transcript.txt      raw transcript
"""

from __future__ import annotations

import os

import boto3
from botocore.exceptions import ClientError

BUCKET = os.getenv("JOBS_BUCKET", "videosense-jobs")
ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL") or None
REGION = os.getenv("AWS_REGION", "us-east-1")


def _client():
    return boto3.client("s3", endpoint_url=ENDPOINT_URL, region_name=REGION)


def ensure_bucket() -> None:
    """Create the bucket if missing (idempotent; used by localstack/dev)."""
    client = _client()
    try:
        client.head_bucket(Bucket=BUCKET)
        return
    except ClientError:
        pass
    kwargs = {}
    if REGION != "us-east-1":
        kwargs["CreateBucketConfiguration"] = {"LocationConstraint": REGION}
    client.create_bucket(Bucket=BUCKET, **kwargs)


# ── key layout ─────────────────────────────────────────────────────────────

def raw_key(job_id: str, filename: str) -> str:
    return f"jobs/{job_id}/raw/{filename}"


def chunk_key(job_id: str, chunk_name: str) -> str:
    return f"jobs/{job_id}/chunks/{chunk_name}"


def transcript_key(job_id: str) -> str:
    return f"jobs/{job_id}/transcript.txt"


def chunk_prefix(job_id: str) -> str:
    return f"jobs/{job_id}/chunks/"


def job_prefix(job_id: str) -> str:
    return f"jobs/{job_id}/"


# ── transfer helpers ────────────────────────────────────────────────────────

def upload_bytes(key: str, data: bytes, content_type: str | None = None) -> None:
    kwargs = {"ContentType": content_type} if content_type else {}
    _client().put_object(Bucket=BUCKET, Key=key, Body=data, **kwargs)


def upload_text(key: str, text: str) -> None:
    upload_bytes(key, text.encode("utf-8"), "text/plain")


def upload_fileobj(key: str, fileobj, content_type: str | None = None) -> None:
    """Stream a file-like object to S3 (multipart under the hood)."""
    extra = {"ContentType": content_type} if content_type else None
    _client().upload_fileobj(fileobj, BUCKET, key, ExtraArgs=extra)


def download_bytes(key: str) -> bytes:
    resp = _client().get_object(Bucket=BUCKET, Key=key)
    return resp["Body"].read()


def download_text(key: str) -> str:
    return download_bytes(key).decode("utf-8")


def delete_prefix(prefix: str) -> None:
    """Delete every object under a prefix (used when a job is deleted)."""
    client = _client()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
        if keys:
            client.delete_objects(Bucket=BUCKET, Delete={"Objects": keys})


def list_keys(prefix: str) -> list[str]:
    """Return all object keys under a prefix."""
    client = _client()
    out: list[str] = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):
        out.extend(obj["Key"] for obj in page.get("Contents", []))
    return out


def download_to_path(key: str, path: str) -> None:
    """Download an object to a local file path."""
    with open(path, "wb") as f:
        _client().download_fileobj(BUCKET, key, f)
