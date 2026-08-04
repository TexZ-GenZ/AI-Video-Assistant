"""Tests for the ingestion service: upload API, process API, and the worker
pipeline (moto-emulated AWS; a real 1s wav exercises ffmpeg locally)."""

import io
import os

import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from pydub import AudioSegment

from services.ingestion import app as ingestion_app
from services.ingestion import worker
from shared import dynamo, queue, s3


@pytest.fixture()
def env():
    with mock_aws():
        dynamo.init_db()
        s3.ensure_bucket()
        queue.ensure_queues()
        yield


def client():
    return TestClient(ingestion_app.app)


def make_wav_bytes(seconds: int = 1) -> bytes:
    buf = io.BytesIO()
    AudioSegment.silent(duration=seconds * 1000, frame_rate=16000) \
        .set_channels(1).set_frame_rate(16000) \
        .export(buf, format="wav")
    return buf.getvalue()


# ── API ────────────────────────────────────────────────────────────────────

def test_health(env):
    assert client().get("/health").json() == {"status": "ok"}


def test_upload_streams_to_s3_staging(env):
    resp = client().post(
        "/api/upload",
        files={"file": ("clip.mp4", b"hello-world", "video/mp4")},
    )
    assert resp.status_code == 200
    file_id = resp.json()["file_id"]

    keys = s3.list_keys(f"uploads/{file_id}")
    assert len(keys) == 1
    assert s3.download_bytes(keys[0]) == b"hello-world"


def test_upload_rejects_too_large(env, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    resp = client().post(
        "/api/upload",
        files={"file": ("big.mp4", b"x" * (2 * 1024 * 1024), "video/mp4")},
    )
    assert resp.status_code == 413


def test_upload_requires_filename(env):
    # empty filename is rejected at the multipart parser (422)
    resp = client().post("/api/upload", files={"file": ("", b"x", "video/mp4")})
    assert resp.status_code == 422


def test_process_creates_job_and_publishes(env):
    resp = client().post(
        "/api/process",
        json={"source": "https://youtu.be/abc", "language": "english"},
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    job = dynamo.get_job(job_id)
    assert job["status"] == "processing"
    assert job["source"] == "https://youtu.be/abc"

    msgs = queue.receive(queue.QUEUE_JOBS, wait=0)
    assert len(msgs) == 1
    assert msgs[0]["body"] == {
        "job_id": job_id,
        "source": "https://youtu.be/abc",
        "language": "english",
    }


# ── worker ─────────────────────────────────────────────────────────────────

def test_worker_processes_staged_upload(env):
    """Full worker path with a staged upload: chunk → S3 → transcribe queue."""
    s3.upload_bytes(f"uploads/abcd1234.wav", make_wav_bytes(), "audio/wav")
    queue.publish(queue.QUEUE_JOBS, {
        "job_id": "job1", "source": "abcd1234", "language": "english",
    })

    worker.process_job_message({"job_id": "job1", "source": "abcd1234", "language": "english"})

    # chunks landed in S3 under the job prefix
    chunk_keys = s3.list_keys("jobs/job1/chunks/")
    assert len(chunk_keys) == 1
    assert chunk_keys[0].endswith("chunk_0.wav")

    # handoff published to the transcribe queue
    msgs = queue.receive(queue.QUEUE_TRANSCRIBE, wait=0)
    assert len(msgs) == 1
    assert msgs[0]["body"] == {"job_id": "job1", "language": "english"}

    # progress advanced
    assert dynamo.get_job("job1")["progress"] == "Queued for transcription"


def test_worker_marks_job_error_on_bad_source(env):
    worker.process_job_message({
        "job_id": "job2", "source": "not-a-real-file-id", "language": "english",
    })
    job = dynamo.get_job("job2")
    assert job["status"] == "error"
    assert "not found" in job["error"]
