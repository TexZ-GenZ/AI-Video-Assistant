"""Tests for the summarization service: worker flow, ask cold-rebuild,
delete cleanup, and per-job Chroma collection logic (moto-emulated AWS;
LLM/embedding calls monkeypatched)."""

import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from services.summarization import app as sum_app
from services.summarization import worker
from services.summarization import rag
from shared import dynamo, queue, s3


@pytest.fixture()
def env():
    # the RAG chain registry is module-global — clear it so tests are isolated
    worker._rag_chains.clear()
    with mock_aws():
        dynamo.init_db()
        s3.ensure_bucket()
        queue.ensure_queues()
        yield
    worker._rag_chains.clear()


def client():
    return TestClient(sum_app.app)


def seed_transcript(job_id: str, text: str = "some transcript words") -> None:
    s3.upload_text(s3.transcript_key(job_id), text)


def seed_done_job(job_id: str, transcript: str = "some transcript words") -> None:
    dynamo.create_job(job_id, f"https://youtu.be/{job_id}", "english")
    dynamo.set_done(
        job_id, "T", "S", "A", "Q", "I", transcript=transcript,
    )


FAKE_ANALYSIS = {
    "title": "Fake Title",
    "summary": "Fake summary",
    "actionables": "1. do thing",
    "questions": "1. why?",
    "information": "1. facts",
}


# ── Chroma collection helpers ──────────────────────────────────────────────

def test_collection_name_per_job(env, monkeypatch, tmp_path):
    monkeypatch.setattr(rag, "CHROMA_DIR", str(tmp_path))
    assert rag.collection_name_for("abc") == "job_abc"
    assert rag.collection_name_for("def") != rag.collection_name_for("abc")


def test_reset_and_delete_collection(env, monkeypatch, tmp_path):
    monkeypatch.setattr(rag, "CHROMA_DIR", str(tmp_path))
    name = rag.collection_name_for("job1")

    # creating with embedding_function=None avoids any model download
    client = rag._client()
    client.create_collection(name=name, embedding_function=None)
    assert name in [c.name for c in client.list_collections()]

    rag.delete_collection(name)
    assert name not in [c.name for c in client.list_collections()]

    # deleting a missing collection is a no-op (idempotent)
    rag.delete_collection(name)


# ── worker ─────────────────────────────────────────────────────────────────

def test_process_job_message_runs_analysis_and_persists(env, monkeypatch):
    seed_transcript("job1")
    queue.publish(queue.QUEUE_SUMMARIZE, {"job_id": "job1", "language": "english"})

    monkeypatch.setattr(worker, "run_analysis", lambda t: dict(FAKE_ANALYSIS))
    monkeypatch.setattr(worker, "build_job_rag", lambda t, j: "fake-chain")
    captured = {}
    orig_register = worker.register_rag_chain
    monkeypatch.setattr(worker, "register_rag_chain",
                        lambda j, c: (captured.update(chain=c), orig_register(j, c)))

    worker.process_job_message({"job_id": "job1", "language": "english"})

    job = dynamo.get_job("job1")
    assert job["status"] == "done"
    assert job["title"] == "Fake Title"
    assert job["summary"] == "Fake summary"
    assert job["actionables"] == "1. do thing"
    assert job["questions"] == "1. why?"
    assert job["information"] == "1. facts"
    assert job["transcript"] == "some transcript words"
    assert captured["chain"] == "fake-chain"
    assert worker.get_rag_chain("job1") == "fake-chain"


def test_process_job_message_missing_transcript_marks_error(env, monkeypatch):
    monkeypatch.setattr(worker, "run_analysis", lambda t: dict(FAKE_ANALYSIS))
    worker.process_job_message({"job_id": "ghost", "language": "english"})

    job = dynamo.get_job("ghost")
    assert job["status"] == "error"
    assert job["error"]


def test_process_job_message_llm_failure_marks_error(env, monkeypatch):
    seed_transcript("job2")

    def boom(t):
        raise RuntimeError("mistral down")

    monkeypatch.setattr(worker, "run_analysis", boom)
    worker.process_job_message({"job_id": "job2", "language": "english"})

    job = dynamo.get_job("job2")
    assert job["status"] == "error"
    assert "mistral down" in job["error"]


# ── API ────────────────────────────────────────────────────────────────────

def test_status_flow(env):
    c = client()
    c.post("/api/process", json={"source": "https://youtu.be/abc", "language": "english"})
    # (summarization has no /api/process — that's ingestion's; just verify 404)
    assert c.post("/api/process", json={}).status_code == 404


def test_status_and_results(env):
    dynamo.create_job("j1", "https://youtu.be/abc", "english")
    c = client()
    assert c.get("/api/process/j1/status").json()["status"] == "processing"
    assert c.get("/api/process/j1/results").status_code == 409  # still processing

    dynamo.set_done("j1", "My Title", "Sum", "Acts", "Qs", "Info")
    res = c.get("/api/process/j1/results").json()
    assert res == {
        "title": "My Title", "summary": "Sum", "actionables": "Acts",
        "questions": "Qs", "information": "Info",
    }
    assert c.get("/api/process/j1/status").json()["status"] == "done"


def test_status_missing_404(env):
    assert client().get("/api/process/nope/status").status_code == 404


def test_ask_rebuilds_chain_on_cold_pod(env, monkeypatch):
    seed_done_job("j1", transcript="hello transcript")

    builds = []

    def fake_build(transcript, job_id):
        builds.append((transcript, job_id))
        return "rebuilt-chain"

    # the app holds its own references — patch them on the app module
    monkeypatch.setattr(sum_app, "build_job_rag", fake_build)
    monkeypatch.setattr(sum_app, "ask_question", lambda chain, q: f"answer-from-{chain}")

    c = client()
    resp = c.post("/api/process/j1/ask", json={"question": "what is this about?"})
    assert resp.status_code == 200
    assert resp.json() == {"answer": "answer-from-rebuilt-chain"}
    # chain now cached — second ask must not rebuild
    resp2 = c.post("/api/process/j1/ask", json={"question": "again"})
    assert resp2.status_code == 200
    assert len(builds) == 1


def test_ask_on_processing_job_404(env):
    dynamo.create_job("j1", "https://youtu.be/abc", "english")
    resp = client().post("/api/process/j1/ask", json={"question": "hi"})
    assert resp.status_code == 404


def test_jobs_list_with_url_label(env):
    dynamo.create_job("j1", "https://youtu.be/abc123", "english")
    dynamo.create_job("j2", "https://youtu.be/xyz789", "english")
    dynamo.set_done("j1", "Finished Title", "S", "A", "Q", "I")

    jobs = client().get("/api/jobs").json()["jobs"]
    by_id = {j["job_id"]: j for j in jobs}
    assert by_id["j1"]["title"] == "Finished Title"
    assert by_id["j2"]["title"] == "xyz789"  # label derived from URL tail


def test_delete_job_cleans_everything(env, monkeypatch):
    seed_done_job("j1")
    s3.upload_text(s3.transcript_key("j1"), "hello")
    s3.upload_bytes(s3.chunk_key("j1", "chunk_0.wav"), b"x", "audio/wav")
    s3.upload_bytes("uploads/uploadid1.mp4", b"raw", "video/mp4")
    # job whose source is the file_id — its staged upload must be removed too
    dynamo.create_job("j2", "uploadid1", "english")
    s3.upload_text(s3.transcript_key("j2"), "y")

    dropped = []
    # the app holds its own reference — patch it on the app module
    monkeypatch.setattr(sum_app, "drop_job_collection", lambda j: dropped.append(j))

    c = client()
    assert c.delete("/api/jobs/j1").status_code == 200
    assert c.delete("/api/jobs/j2").status_code == 200

    # DDB rows gone
    assert dynamo.get_job("j1") is None
    assert dynamo.get_job("j2") is None
    # S3 artifacts gone (job prefixes + staged upload for file_id source)
    assert s3.list_keys("jobs/j1/") == []
    assert s3.list_keys("jobs/j2/") == []
    assert s3.list_keys("uploads/uploadid1") == []
    # chroma collection dropped for both
    assert sorted(dropped) == ["j1", "j2"]
    # deleting a missing job → 404
    assert c.delete("/api/jobs/j1").status_code == 404


def test_delete_job_does_not_remove_unrelated_uploads(env):
    seed_done_job("j1", transcript="x")
    s3.upload_bytes("uploads/keepme.mp4", b"raw", "video/mp4")
    client().delete("/api/jobs/j1")
    assert s3.list_keys("uploads/keepme") == ["uploads/keepme.mp4"]
