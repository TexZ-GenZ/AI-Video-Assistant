"""Summarization worker: LLM analysis passes + RAG chain assembly.

Consumes the summarize queue:  {job_id, language}
  1. read the transcript from S3
  2. run the LLM passes (title, summary, action items, key info, questions)
  3. index the transcript into a PER-JOB Chroma collection and keep the
     chain in the in-memory registry
  4. persist results + transcript to DynamoDB

Owns the in-memory RAG chain registry (chains are keyed by job_id; Chroma +
LCEL chains aren't pickleable, so each pod holds its own copy and the ask
endpoint rebuilds on cold pods).

Run as a standalone process:  python -m services.summarization.worker
"""

from __future__ import annotations

import re
import threading
import traceback

from shared import queue, s3
from shared.dynamo import update_progress, set_done, set_error
from services.summarization.summarize import summarize, generate_title
from services.summarization.extractor import (
    extract_action_items,
    extract_key_information,
    extract_questions,
)
from services.summarization.rag import (
    build_rag_chain,
    collection_name_for,
    delete_collection,
)

# ── RAG chain registry ─────────────────────────────────────────────────────
# Chroma + LCEL chains aren't pickleable, so chains live in-process per pod.
# On a cold pod the ask endpoint rebuilds from the stored transcript.

_rag_chains: dict[str, object] = {}
_rag_lock = threading.Lock()


def register_rag_chain(job_id: str, chain: object) -> None:
    with _rag_lock:
        _rag_chains[job_id] = chain


def get_rag_chain(job_id: str) -> object | None:
    with _rag_lock:
        return _rag_chains.get(job_id)


def drop_rag_chain(job_id: str) -> None:
    with _rag_lock:
        _rag_chains.pop(job_id, None)


# ── Title cleaning ─────────────────────────────────────────────────────────

def clean_title(raw: str) -> str:
    """Strip markdown formatting and quotes the LLM sometimes wraps titles in."""
    cleaned = re.sub(r"\*\*|__", "", raw)          # remove **bold** / __bold__
    cleaned = re.sub(r"^[\"'«‹„]+", "", cleaned)   # leading quotes
    cleaned = re.sub(r"[\"'»›‟]+$", "", cleaned)   # trailing quotes
    cleaned = re.sub(r"^#+\s*", "", cleaned)        # markdown headings
    return cleaned.strip()


# ── Analysis ───────────────────────────────────────────────────────────────

def run_analysis(transcript: str) -> dict:
    """Run the four LLM passes and return the structured results dict."""
    raw_title = generate_title(transcript)
    title = clean_title(raw_title)

    summary = summarize(transcript)
    actionables = extract_action_items(transcript)
    information = extract_key_information(transcript)
    questions = extract_questions(transcript)

    return {
        "title": title,
        "summary": summary,
        "actionables": actionables,
        "questions": questions,
        "information": information,
    }


def build_job_rag(transcript: str, job_id: str):
    """Build the RAG chain for a job's transcript (per-job Chroma collection)."""
    return build_rag_chain(transcript, collection_name=collection_name_for(job_id))


def drop_job_collection(job_id: str) -> None:
    """Delete a job's Chroma collection (called when the job is deleted)."""
    delete_collection(collection_name_for(job_id))


# ── job processing ─────────────────────────────────────────────────────────

def process_job_message(msg: dict) -> None:
    """Process one summarize-queue message end to end (never raises)."""
    job_id = msg["job_id"]

    try:
        update_progress(job_id, "Reading transcript...")
        transcript = s3.download_text(s3.transcript_key(job_id))
        if not transcript.strip():
            raise RuntimeError("transcript is empty")

        update_progress(job_id, "Analyzing transcript...")
        analysis = run_analysis(transcript)

        update_progress(job_id, "Building search index...")
        rag_chain = build_job_rag(transcript, job_id)
        register_rag_chain(job_id, rag_chain)

        set_done(
            job_id,
            analysis["title"],
            analysis["summary"],
            analysis["actionables"],
            analysis["questions"],
            analysis["information"],
            transcript,
        )

    except Exception as exc:
        set_error(job_id, str(exc))
        traceback.print_exc()


def run_worker(poll_seconds: int = 20, visibility: int = 600) -> None:
    """Long-poll the summarize queue forever."""
    print(f"Summarization worker polling {queue.QUEUE_SUMMARIZE} ...")
    while True:
        try:
            messages = queue.receive(
                queue.QUEUE_SUMMARIZE, wait=poll_seconds, visibility=visibility
            )
        except Exception:
            traceback.print_exc()
            continue

        for msg in messages:
            try:
                process_job_message(msg["body"])
            finally:
                # Always ack: business errors are recorded on the job. If the
                # process crashes mid-message, no ack → redrive → DLQ.
                try:
                    queue.ack(msg["receipt_handle"], queue.QUEUE_SUMMARIZE)
                except Exception:
                    traceback.print_exc()


if __name__ == "__main__":
    run_worker()
