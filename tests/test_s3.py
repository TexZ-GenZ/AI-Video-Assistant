"""Tests for S3 storage helpers (moto-emulated)."""

import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from shared import s3


@pytest.fixture()
def store():
    with mock_aws():
        s3.ensure_bucket()
        yield s3


def test_ensure_bucket_idempotent(store):
    store.ensure_bucket()  # second call must not raise


def test_key_layout(store):
    assert s3.raw_key("j", "a.mp4") == "jobs/j/raw/a.mp4"
    assert s3.chunk_key("j", "chunk_0.wav") == "jobs/j/chunks/chunk_0.wav"
    assert s3.transcript_key("j") == "jobs/j/transcript.txt"
    assert s3.job_prefix("j") == "jobs/j/"


def test_bytes_roundtrip(store):
    key = s3.raw_key("job1", "clip.mp4")
    store.upload_bytes(key, b"raw-bytes")
    assert store.download_bytes(key) == b"raw-bytes"


def test_text_roundtrip(store):
    key = s3.transcript_key("job1")
    store.upload_text(key, "hello transcript")
    assert store.download_text(key) == "hello transcript"


def test_delete_prefix_only_removes_that_job(store):
    store.upload_text(s3.transcript_key("job1"), "a")
    store.upload_bytes(s3.chunk_key("job1", "c0.wav"), b"x")
    store.upload_text(s3.transcript_key("job2"), "b")

    store.delete_prefix(s3.job_prefix("job1"))

    # job2 untouched
    assert store.download_text(s3.transcript_key("job2")) == "b"
    # job1 gone
    with pytest.raises(ClientError):
        store.download_text(s3.transcript_key("job1"))
