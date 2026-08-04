"""DynamoDB job store — replaces db.py (SQLite).

Same function signatures as the old SQLite store so callers swap imports
without other changes.

Local development:
  - unit tests: moto (emulated in-process)
  - docker-compose: localstack (set DYNAMO_ENDPOINT_URL)
  - prod: real DynamoDB (no endpoint override)
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

TABLE_NAME = os.getenv("JOBS_TABLE", "videosense-jobs")
ENDPOINT_URL = os.getenv("DYNAMO_ENDPOINT_URL") or None
REGION = os.getenv("AWS_REGION", "us-east-1")

# All known attributes (SQLite parity: rows always expose every column)
_ATTRS = [
    "job_id", "source", "language", "status", "progress", "error",
    "title", "summary", "actionables", "questions", "information",
    "transcript", "created_at", "updated_at",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resource():
    return boto3.resource("dynamodb", endpoint_url=ENDPOINT_URL, region_name=REGION)


def init_db() -> None:
    """Create the jobs table if it doesn't exist. Call once at startup."""
    try:
        client = boto3.client("dynamodb", endpoint_url=ENDPOINT_URL, region_name=REGION)
    except NoCredentialsError:
        raise RuntimeError(
            "AWS credentials not found. Run `aws configure`, or set "
            "DYNAMO_ENDPOINT_URL to localstack/moto for emulated DynamoDB."
        ) from None

    if TABLE_NAME in client.list_tables()["TableNames"]:
        return

    client.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "job_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    client.get_waiter("table_exists").wait(TableName=TABLE_NAME)


# ── write helpers ──────────────────────────────────────────────────────────


def create_job(job_id: str, source: str, language: str) -> None:
    now = _now()
    _resource().Table(TABLE_NAME).put_item(
        Item={
            "job_id": job_id,
            "source": source,
            "language": language,
            "status": "processing",
            "created_at": now,
            "updated_at": now,
        }
    )


def update_progress(job_id: str, progress: str) -> None:
    _resource().Table(TABLE_NAME).update_item(
        Key={"job_id": job_id},
        UpdateExpression="SET #p = :p, updated_at = :now",
        ExpressionAttributeNames={"#p": "progress"},
        ExpressionAttributeValues={":p": progress, ":now": _now()},
    )


def set_done(
    job_id: str,
    title: str,
    summary: str,
    actionables: str,
    questions: str,
    information: str,
    transcript: str = "",
) -> None:
    now = _now()
    _resource().Table(TABLE_NAME).update_item(
        Key={"job_id": job_id},
        UpdateExpression=(
            "SET #s = :s, title = :title, summary = :summary, "
            "actionables = :actionables, questions = :questions, "
            "information = :information, transcript = :transcript, "
            "updated_at = :now "
            "REMOVE progress, #e"
        ),
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={
            ":s": "done",
            ":title": title,
            ":summary": summary,
            ":actionables": actionables,
            ":questions": questions,
            ":information": information,
            ":transcript": transcript,
            ":now": now,
        },
    )


def set_error(job_id: str, error: str) -> None:
    _resource().Table(TABLE_NAME).update_item(
        Key={"job_id": job_id},
        UpdateExpression="SET #s = :s, #e = :e, updated_at = :now REMOVE progress",
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={":s": "error", ":e": error, ":now": _now()},
    )


# ── read helpers ───────────────────────────────────────────────────────────


def get_job(job_id: str) -> dict | None:
    resp = _resource().Table(TABLE_NAME).get_item(Key={"job_id": job_id})
    item = resp.get("Item")
    if item is None:
        return None
    return {attr: item.get(attr) for attr in _ATTRS}


def list_jobs() -> list[dict]:
    rows = _resource().Table(TABLE_NAME).scan().get("Items", [])
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return [
        {
            "job_id": r["job_id"],
            "title": r.get("title"),
            "source": r.get("source"),
            "status": r.get("status", "processing"),
            "created_at": r.get("created_at", ""),
        }
        for r in rows
    ]


def get_transcript(job_id: str) -> str | None:
    resp = _resource().Table(TABLE_NAME).get_item(Key={"job_id": job_id})
    item = resp.get("Item")
    return item.get("transcript") if item else None


def delete_job(job_id: str) -> bool:
    """Delete a job and return True if it existed."""
    try:
        _resource().Table(TABLE_NAME).delete_item(
            Key={"job_id": job_id},
            ConditionExpression="attribute_exists(job_id)",
        )
        return True
    except ClientError:
        return False
