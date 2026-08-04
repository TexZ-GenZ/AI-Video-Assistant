"""SQS pipeline helpers.

Three queues in a chain:  jobs → transcribe → summarize
  - ingestion publishes to QUEUE_JOBS (message: {job_id, source, language})
  - transcription consumes QUEUE_JOBS... (see worker wiring) and publishes
    {job_id} to QUEUE_TRANSCRIBE, etc.

Each queue has a DLQ (name + "-dlq") configured with maxReceiveCount=3:
messages that fail 3 times land in the DLQ instead of looping forever.
"""

from __future__ import annotations

import json
import os

import boto3

QUEUE_JOBS = os.getenv("JOBS_QUEUE", "videosense-jobs")
QUEUE_TRANSCRIBE = os.getenv("TRANSCRIBE_QUEUE", "videosense-transcribe")
QUEUE_SUMMARIZE = os.getenv("SUMMARIZE_QUEUE", "videosense-summarize")
DLQ_SUFFIX = "-dlq"

ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL") or None
REGION = os.getenv("AWS_REGION", "us-east-1")

_url_cache: dict[str, str] = {}


def _client():
    return boto3.client("sqs", endpoint_url=ENDPOINT_URL, region_name=REGION)


def queue_url(queue_name: str) -> str:
    if queue_name not in _url_cache:
        _url_cache[queue_name] = _client().get_queue_url(QueueName=queue_name)["QueueUrl"]
    return _url_cache[queue_name]


def ensure_queues() -> None:
    """Create the three queues + DLQs with redrive policy (idempotent).

    Used by localstack/dev; production queues are provisioned by the
    infra scripts instead.
    """
    client = _client()
    for name in (QUEUE_JOBS, QUEUE_TRANSCRIBE, QUEUE_SUMMARIZE):
        dlq = f"{name}{DLQ_SUFFIX}"
        client.create_queue(QueueName=dlq)
        dlq_arn = client.get_queue_attributes(
            QueueUrl=queue_url(dlq), AttributeNames=["QueueArn"]
        )["Attributes"]["QueueArn"]
        client.create_queue(
            QueueName=name,
            Attributes={
                "RedrivePolicy": json.dumps(
                    {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": 3}
                )
            },
        )


def publish(queue_name: str, message: dict) -> None:
    """Send a job message to a queue."""
    _client().send_message(
        QueueUrl=queue_url(queue_name),
        MessageBody=json.dumps(message),
    )


def receive(queue_name: str, wait: int = 20, visibility: int = 600) -> list[dict]:
    """Long-poll for messages.

    Returns [{"receipt_handle": str, "body": dict}, ...].
    Workers must ack() after successful processing; unacked messages become
    visible again after `visibility` seconds and eventually redrive to DLQ.
    """
    resp = _client().receive_message(
        QueueUrl=queue_url(queue_name),
        MaxNumberOfMessages=10,
        WaitTimeSeconds=wait,
        VisibilityTimeout=visibility,
    )
    return [
        {"receipt_handle": m["ReceiptHandle"], "body": json.loads(m["Body"])}
        for m in resp.get("Messages", [])
    ]


def ack(receipt_handle: str, queue_name: str) -> None:
    """Delete a processed message from its queue."""
    _client().delete_message(
        QueueUrl=queue_url(queue_name),
        ReceiptHandle=receipt_handle,
    )
