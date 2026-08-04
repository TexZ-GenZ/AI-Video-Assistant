"""Tests for the DynamoDB job store, emulated in-process with moto."""

import pytest
from moto import mock_aws

from shared import dynamo


@pytest.fixture()
def store():
    with mock_aws():
        dynamo.init_db()
        yield dynamo


def test_init_db_is_idempotent(store):
    store.init_db()  # second call must not raise


def test_create_job_and_get(store):
    store.create_job("j1", "https://youtu.be/abc", "english")
    job = store.get_job("j1")
    assert job is not None
    assert job["job_id"] == "j1"
    assert job["source"] == "https://youtu.be/abc"
    assert job["language"] == "english"
    assert job["status"] == "processing"
    assert job["created_at"]
    # unset attributes normalize to None (SQLite parity)
    assert job["title"] is None
    assert job["progress"] is None


def test_get_job_missing(store):
    assert store.get_job("nope") is None


def test_update_progress(store):
    store.create_job("j1", "src", "english")
    store.update_progress("j1", "Downloading audio...")
    assert store.get_job("j1")["progress"] == "Downloading audio..."


def test_set_done(store):
    store.create_job("j1", "src", "english")
    store.update_progress("j1", "Building search index...")
    store.set_done("j1", "T", "S", "A", "Q", "I", transcript="full transcript")

    job = store.get_job("j1")
    assert job["status"] == "done"
    assert job["title"] == "T"
    assert job["summary"] == "S"
    assert job["actionables"] == "A"
    assert job["questions"] == "Q"
    assert job["information"] == "I"
    assert job["transcript"] == "full transcript"
    # progress/error cleared on completion
    assert job["progress"] is None
    assert job["error"] is None


def test_set_error(store):
    store.create_job("j1", "src", "english")
    store.set_error("j1", "boom")
    job = store.get_job("j1")
    assert job["status"] == "error"
    assert job["error"] == "boom"
    assert job["progress"] is None


def test_list_jobs_orders_newest_first(store):
    store.create_job("old", "src1", "english")
    store.create_job("new", "src2", "english")
    jobs = store.list_jobs()
    assert [j["job_id"] for j in jobs] == ["new", "old"]
    assert jobs[1]["source"] == "src1"
    assert jobs[0]["status"] == "processing"


def test_list_jobs_shows_title_once_done(store):
    store.create_job("j1", "src", "english")
    store.set_done("j1", "My Title", "S", "A", "Q", "I")
    jobs = store.list_jobs()
    assert jobs[0]["title"] == "My Title"


def test_get_transcript(store):
    store.create_job("j1", "src", "english")
    assert store.get_transcript("j1") is None
    store.set_done("j1", "T", "S", "A", "Q", "I", transcript="hello world")
    assert store.get_transcript("j1") == "hello world"


def test_delete_job(store):
    store.create_job("j1", "src", "english")
    assert store.delete_job("j1") is True
    assert store.get_job("j1") is None
    # deleting a missing job reports False
    assert store.delete_job("j1") is False
