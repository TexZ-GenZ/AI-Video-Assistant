"""
Temporary in-process orchestrator (pre-SQS).

Runs the full pipeline by calling across the three service packages and
drives the SQLite job store. Exists only so the CLI, tests, and the two API
services keep working while the SQS wiring lands (steps 5-7 of the
deployment plan); it is deleted once workers consume queues.
"""

from __future__ import annotations

import re
import traceback
from urllib.parse import urlparse
from pathlib import Path

from db import (
    create_job,
    update_progress,
    set_done,
    set_error,
)

from services.ingestion.worker import process_input
from services.transcription.worker import transcribe_all
from services.summarization.worker import (
    run_analysis,
    build_job_rag,
    register_rag_chain,
    clean_title,
)


# ── Source helpers ─────────────────────────────────────────────────────────

UPLOAD_DIR = Path("downloads/uploads")

def resolve_source(source: str) -> str:
    """If source looks like a file_id (no scheme, no path separators), resolve
    it to the uploaded file path. Otherwise return as-is (YouTube URL or local
    path)."""
    if source.startswith("http://") or source.startswith("https://"):
        return source
    if "/" in source or "\\" in source:
        return source
    # Treat as file_id — look up in uploads dir
    candidates = list(UPLOAD_DIR.glob(f"{source}.*"))
    if candidates:
        return str(candidates[0])
    # Maybe it's a direct filename in downloads/
    direct = Path("downloads") / source
    if direct.exists():
        return str(direct)
    # Give up — let process_input decide
    return source


def source_label(source: str) -> str:
    """Derive a human-readable label from the source for the history sidebar."""
    if source.startswith("http://") or source.startswith("https://"):
        parsed = urlparse(source)
        path = parsed.path.strip("/")
        if path:
            tail = path.split("/")[-1]
            return tail[:40] if tail else parsed.netloc
        return parsed.netloc
    if "/" in source or "\\" in source:
        return Path(source).name[:40]
    # file_id — look up original filename
    candidates = list(UPLOAD_DIR.glob(f"{source}.*"))
    if candidates:
        return candidates[0].name[:40]
    return source[:40]


# ── Pipeline ───────────────────────────────────────────────────────────────

def run_pipeline(source: str, language: str = "english") -> dict:
    """Full pipeline (CLI/test path). Returns results + in-memory rag_chain."""
    print("Running AI video assistant ...")

    chunks = process_input(source)
    backend = "whisper" if language != "hindi" else "sarvam"
    transcript = transcribe_all(chunks, backend=backend)

    analysis = run_analysis(transcript)
    rag_chain = build_job_rag(transcript)

    return {**analysis, "rag_chain": rag_chain}


def _run_job(job_id: str, source: str, language: str) -> None:
    """Background task: run the full pipeline and store results (server path)."""
    try:
        resolved = resolve_source(source)

        update_progress(job_id, "Downloading audio...")
        chunks = process_input(resolved)

        backend = "whisper" if language != "hindi" else "sarvam"
        update_progress(job_id, f"Transcribing ({backend})...")
        transcript = transcribe_all(chunks, backend=backend)

        update_progress(job_id, "Analyzing transcript...")
        analysis = run_analysis(transcript)

        update_progress(job_id, "Building search index...")
        rag_chain = build_job_rag(transcript)
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
