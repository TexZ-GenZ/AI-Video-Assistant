"""
FastAPI server for the AI Video Assistant.

Exposes 6 endpoints that wrap the existing pipeline (utils/audio_processor,
core/transcriber, core/summarize, core/extractor, core/rag_engine) behind a
REST API with background processing and SQLite persistence.

Start with:  uvicorn server:app --reload
"""

from __future__ import annotations

import os
import re
import uuid
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from db import (
    init_db,
    create_job,
    update_progress,
    set_done,
    set_error,
    get_job,
    get_transcript,
    list_jobs,
    delete_job,
)

# ── Import existing pipeline modules (unchanged) ───────────────────────────
from utils.audio_processor import process_input
from core.transcriber import transcribe_all
from core.summarize import summarize, generate_title
from core.extractor import (
    extract_action_items,
    extract_key_information,
    extract_questions,
)
from core.rag_engine import build_rag_chain, ask_question as rag_ask

# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

UPLOAD_DIR = Path("downloads/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_WORKERS = 4

# ═══════════════════════════════════════════════════════════════════════════
# App
# ═══════════════════════════════════════════════════════════════════════════

app = FastAPI(title="VideoSense API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# Thread pool for background pipeline execution
_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

# In-memory RAG chains keyed by job_id (Chroma + LCEL chains aren't pickleable)
_rag_chains: dict[str, object] = {}
_rag_lock = threading.Lock()

# ═══════════════════════════════════════════════════════════════════════════
# Pydantic models (must match the TypeScript interfaces in videoApi.ts)
# ═══════════════════════════════════════════════════════════════════════════

class ProcessRequest(BaseModel):
    source: str       # YouTube URL or file_id from /api/upload
    language: str = "english"  # "english" | "hindi"


class ProcessResponse(BaseModel):
    job_id: str
    status: str  # "processing"


class StatusResponse(BaseModel):
    job_id: str
    status: str          # "processing" | "done" | "error"
    progress: str | None = None
    error: str | None = None


class Results(BaseModel):
    title: str
    summary: str
    actionables: str
    questions: str
    information: str


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str


class UploadResponse(BaseModel):
    file_id: str


class JobSummary(BaseModel):
    job_id: str
    title: str | None = None
    status: str
    created_at: str


class JobsResponse(BaseModel):
    jobs: list[JobSummary]

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _source_label(source: str) -> str:
    """Derive a human-readable label from the source for the history sidebar."""
    if source.startswith("http://") or source.startswith("https://"):
        from urllib.parse import urlparse
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


def _clean_title(raw: str) -> str:
    """Strip markdown formatting and quotes the LLM sometimes wraps titles in."""
    cleaned = re.sub(r"\*\*|__", "", raw)          # remove **bold** / __bold__
    cleaned = re.sub(r"^[\"'«‹„]+", "", cleaned)   # leading quotes
    cleaned = re.sub(r"[\"'»›‟]+$", "", cleaned)   # trailing quotes
    cleaned = re.sub(r"^#+\s*", "", cleaned)        # markdown headings
    return cleaned.strip()


def _resolve_source(source: str) -> str:
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


def _run_pipeline(job_id: str, source: str, language: str) -> None:
    """Background task: run the full pipeline and store results."""
    try:
        # Resolve source
        resolved = _resolve_source(source)

        # ── Step 1: Acquire audio ──
        update_progress(job_id, "Downloading audio...")
        chunks = process_input(resolved)

        # ── Step 2: Transcribe ──
        backend = "whisper" if language != "hindi" else "sarvam"
        update_progress(job_id, f"Transcribing ({backend})...")
        transcript = transcribe_all(chunks, backend=backend)

        # ── Step 3: LLM analysis ──
        update_progress(job_id, "Analyzing transcript...")
        raw_title = generate_title(transcript)
        title = _clean_title(raw_title)

        update_progress(job_id, "Summarizing transcript...")
        summary = summarize(transcript)

        update_progress(job_id, "Extracting action items...")
        actionables = extract_action_items(transcript)

        update_progress(job_id, "Extracting key information...")
        information = extract_key_information(transcript)

        update_progress(job_id, "Extracting questions...")
        questions = extract_questions(transcript)

        # ── Step 4: Build RAG ──
        update_progress(job_id, "Building search index...")
        rag_chain = build_rag_chain(transcript)
        with _rag_lock:
            _rag_chains[job_id] = rag_chain

        # ── Persist results (include transcript for RAG rebuild on restart) ──
        set_done(job_id, title, summary, actionables, questions, information, transcript)

    except Exception as exc:
        set_error(job_id, str(exc))
        traceback.print_exc()

# ═══════════════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════════════

# ── Upload ─────────────────────────────────────────────────────────────────

@app.post("/api/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    """Accept a video/audio file, save it, return a file_id for /api/process."""
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    ext = Path(file.filename).suffix or ".mp4"
    file_id = uuid.uuid4().hex
    save_path = UPLOAD_DIR / f"{file_id}{ext}"

    content = await file.read()
    save_path.write_bytes(content)

    return UploadResponse(file_id=file_id)


# ── Process ────────────────────────────────────────────────────────────────

@app.post("/api/process", response_model=ProcessResponse)
def process_video(req: ProcessRequest):
    """Kick off the full pipeline in a background thread."""
    job_id = uuid.uuid4().hex
    create_job(job_id, req.source, req.language)

    _executor.submit(_run_pipeline, job_id, req.source, req.language)

    return ProcessResponse(job_id=job_id, status="processing")


# ── Status ─────────────────────────────────────────────────────────────────

@app.get("/api/process/{job_id}/status", response_model=StatusResponse)
def job_status(job_id: str):
    """Poll for job progress."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    return StatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        progress=job.get("progress"),
        error=job.get("error"),
    )


# ── Results ────────────────────────────────────────────────────────────────

@app.get("/api/process/{job_id}/results", response_model=Results)
def job_results(job_id: str):
    """Get structured analysis results for a completed job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] == "processing":
        raise HTTPException(409, "Job is still processing")
    if job["status"] == "error":
        raise HTTPException(500, job.get("error", "Job failed"))

    return Results(
        title=job["title"] or "",
        summary=job["summary"] or "",
        actionables=job["actionables"] or "",
        questions=job["questions"] or "",
        information=job["information"] or "",
    )


# ── Ask / Chat ─────────────────────────────────────────────────────────────

@app.post("/api/process/{job_id}/ask", response_model=AskResponse)
def ask(job_id: str, req: AskRequest):
    """Ask a question against the video's RAG index."""
    with _rag_lock:
        rag_chain = _rag_chains.get(job_id)

    if rag_chain is None:
        # RAG chain wasn't kept (e.g. server restart) — rebuild from stored transcript
        job = get_job(job_id)
        if job and job["status"] == "done":
            transcript = get_transcript(job_id)
            if transcript:
                rag_chain = build_rag_chain(transcript)
                with _rag_lock:
                    _rag_chains[job_id] = rag_chain
            else:
                raise HTTPException(
                    410,
                    "RAG index expired. Please re-process the video.",
                )
        else:
            raise HTTPException(404, "Job not found or still processing")

    answer = rag_ask(rag_chain, req.question)
    return AskResponse(answer=answer)


# ── Jobs list ──────────────────────────────────────────────────────────────

@app.get("/api/jobs", response_model=JobsResponse)
def jobs_list():
    """Return all jobs for the history sidebar."""
    jobs = list_jobs()
    return JobsResponse(
        jobs=[
            JobSummary(
                job_id=j["job_id"],
                title=j.get("title") or _source_label(j.get("source", "")),
                status=j["status"],
                created_at=j["created_at"],
            )
            for j in jobs
        ]
    )


# ── Delete job ─────────────────────────────────────────────────────────────

@app.delete("/api/jobs/{job_id}")
def delete_job_endpoint(job_id: str):
    """Remove a job and its RAG chain from memory."""
    with _rag_lock:
        _rag_chains.pop(job_id, None)
    if not delete_job(job_id):
        raise HTTPException(404, "Job not found")
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════
# Startup
# ═══════════════════════════════════════════════════════════════════════════

@app.on_event("startup")
def _startup():
    init_db()
