"""Tests for SQS pipeline helpers (moto-emulated)."""

import pytest
from moto import mock_aws

from shared import queue


@pytest.fixture()
def q():
    with mock_aws():
        queue.ensure_queues()
        yield queue


def test_publish_receive_roundtrip(q):
    msg = {"job_id": "j1", "source": "https://youtu.be/abc", "language": "english"}
    q.publish(queue.QUEUE_JOBS, msg)
    msgs = q.receive(queue.QUEUE_JOBS, wait=0)
    assert len(msgs) == 1
    assert msgs[0]["body"] == msg


def test_receive_empty(q):
    assert q.receive(queue.QUEUE_JOBS, wait=0) == []


def test_ack_removes_message(q):
    q.publish(queue.QUEUE_TRANSCRIBE, {"job_id": "j1"})
    msgs = q.receive(queue.QUEUE_TRANSCRIBE, wait=0)
    assert len(msgs) == 1
    q.ack(msgs[0]["receipt_handle"], queue.QUEUE_TRANSCRIBE)
    assert q.receive(queue.QUEUE_TRANSCRIBE, wait=0) == []


def test_unacked_message_becomes_visible_again(q):
    """No ack → message reappears after visibility timeout (worker retry)."""
    q.publish(queue.QUEUE_SUMMARIZE, {"job_id": "j1"})
    msgs = q.receive(queue.QUEUE_SUMMARIZE, wait=0, visibility=0)
    assert len(msgs) == 1

    again = q.receive(queue.QUEUE_SUMMARIZE, wait=0, visibility=0)
    assert [m["body"]["job_id"] for m in again] == ["j1"]


def test_queues_are_distinct(q):
    q.publish(queue.QUEUE_JOBS, {"job_id": "j1"})
    # messages published to one queue do not leak into the next
    assert q.receive(queue.QUEUE_TRANSCRIBE, wait=0) == []
    assert q.receive(queue.QUEUE_SUMMARIZE, wait=0) == []
    assert len(q.receive(queue.QUEUE_JOBS, wait=0)) == 1
