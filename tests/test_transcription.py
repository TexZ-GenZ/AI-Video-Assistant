"""Tests for the transcription worker (moto-emulated AWS).

The real whisper/Sarvam calls are monkeypatched — this suite verifies the
AWS wiring (chunk download order, transcript upload, queue handoff, error
handling). The real model runs in the compose integration test (step 9).
"""

import os
import tempfile

import pytest
from moto import mock_aws

from services.transcription import worker
from shared import dynamo, queue, s3


@pytest.fixture()
def env():
    with mock_aws():
        dynamo.init_db()
        s3.ensure_bucket()
        queue.ensure_queues()
        yield


def seed_chunks(job_id: str, n: int = 2) -> None:
    for i in range(n):
        s3.upload_bytes(s3.chunk_key(job_id, f"chunk_{i}.wav"), b"fake-wav", "audio/wav")


# ── chunk ordering / download ──────────────────────────────────────────────

def test_chunk_sort_key_natural_order(env):
    keys = [
        "jobs/j/chunks/chunk_10.wav",
        "jobs/j/chunks/chunk_2.wav",
        "jobs/j/chunks/chunk_1.wav",
    ]
    ordered = sorted(keys, key=worker._chunk_sort_key)
    assert ordered == [
        "jobs/j/chunks/chunk_1.wav",
        "jobs/j/chunks/chunk_2.wav",
        "jobs/j/chunks/chunk_10.wav",
    ]


def test_download_chunks_in_order(env):
    seed_chunks("job1", n=3)
    with tempfile.TemporaryDirectory() as td:
        paths = worker._download_chunks("job1", td)
        assert [os.path.basename(p) for p in paths] == [
            "chunk_0.wav", "chunk_1.wav", "chunk_2.wav",
        ]


def test_download_chunks_missing_raises(env):
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(FileNotFoundError, match="no audio chunks"):
            worker._download_chunks("ghost", td)


# ── backend dispatch ───────────────────────────────────────────────────────

def test_transcribe_chunk_dispatches_whisper(env, monkeypatch):
    monkeypatch.setattr(worker, "transcribe_chunk_whisper", lambda p, **kw: "whisper text")
    assert worker.transcribe_chunk("x.wav", backend="whisper") == "whisper text"


def test_transcribe_chunk_dispatches_sarvam(env, monkeypatch):
    monkeypatch.setattr(worker, "transcribe_chunk_sarvam", lambda p, **kw: "hindi text")
    assert worker.transcribe_chunk("x.wav", backend="sarvam") == "hindi text"


def test_transcribe_chunk_rejects_unknown_backend(env):
    with pytest.raises(ValueError, match="Unsupported backend"):
        worker.transcribe_chunk("x.wav", backend="bogus")


# ── job processing ─────────────────────────────────────────────────────────

def test_process_job_message_english(env, monkeypatch):
    seed_chunks("job1", n=2)
    queue.publish(queue.QUEUE_TRANSCRIBE, {"job_id": "job1", "language": "english"})

    captured = {}

    def fake_transcribe_all(chunks, backend="whisper", **kwargs):
        captured["backend"] = backend
        captured["n_chunks"] = len(chunks)
        return "hello world transcript"

    monkeypatch.setattr(worker, "transcribe_all", fake_transcribe_all)

    worker.process_job_message({"job_id": "job1", "language": "english"})

    # whisper backend used, both chunks transcribed in order
    assert captured == {"backend": "whisper", "n_chunks": 2}
    # transcript persisted to S3
    assert s3.download_text(s3.transcript_key("job1")) == "hello world transcript"
    # handoff published to the summarize queue
    msgs = queue.receive(queue.QUEUE_SUMMARIZE, wait=0)
    assert len(msgs) == 1
    assert msgs[0]["body"] == {"job_id": "job1", "language": "english"}
    # progress advanced
    assert dynamo.get_job("job1")["progress"] == "Queued for analysis"


def test_process_job_message_hindi_uses_sarvam(env, monkeypatch):
    seed_chunks("job2", n=1)

    captured = {}

    def fake_transcribe_all(chunks, backend="whisper", **kwargs):
        captured["backend"] = backend
        return "translated hindi text"

    monkeypatch.setattr(worker, "transcribe_all", fake_transcribe_all)

    worker.process_job_message({"job_id": "job2", "language": "hindi"})

    assert captured["backend"] == "sarvam"
    assert s3.download_text(s3.transcript_key("job2")) == "translated hindi text"


def test_process_job_message_empty_transcript_is_error(env, monkeypatch):
    seed_chunks("job3", n=1)
    monkeypatch.setattr(worker, "transcribe_all", lambda chunks, **kw: "   ")

    worker.process_job_message({"job_id": "job3", "language": "english"})

    job = dynamo.get_job("job3")
    assert job["status"] == "error"
    assert "no text" in job["error"]
    # nothing published downstream, no transcript stored
    assert queue.receive(queue.QUEUE_SUMMARIZE, wait=0) == []
    assert s3.list_keys("jobs/job3/transcript.txt") == []


def test_process_job_message_missing_chunks_marks_error(env):
    worker.process_job_message({"job_id": "ghost", "language": "english"})

    job = dynamo.get_job("ghost")
    assert job["status"] == "error"
    assert "no audio chunks" in job["error"]
    assert queue.receive(queue.QUEUE_SUMMARIZE, wait=0) == []
