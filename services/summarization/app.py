"""
Summarization service — results, chat (RAG), and history endpoints.

Exposes:
  GET  /api/process/{job_id}/status   — poll progress
  GET  /api/process/{job_id}/results  — structured analysis results
  POST /api/process/{job_id}/ask      — chat with the video (RAG)
  GET  /api/jobs                      — history sidebar
  DELETE /api/jobs/{job_id}           — remove a job and all its data
  GET  /health

Run with:  uvicorn services.summarization.app:app --reload
"""

from __future__ import annotations

from urllib.parse import urlparse
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from shared import s3
from shared.config import cors_origins
from shared.dynamo import get_job, get_transcript, list_jobs, delete_job
from shared.models import (
    StatusResponse,
    Results,
    AskRequest,
    AskResponse,
    JobSummary,
    JobsResponse,
)
from services.summarization.worker import (
    get_rag_chain,
    drop_rag_chain,
    register_rag_chain,
    build_job_rag,
    drop_job_collection,
)
from services.summarization.rag import ask_question

app = FastAPI(title="VideoSense Summarization API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)


def _source_label(source: str) -> str:
    """Human-readable label for the history sidebar."""
    if source.startswith("http://") or source.startswith("https://"):
        parsed = urlparse(source)
        path = parsed.path.strip("/")
        if path:
            tail = path.split("/")[-1]
            return tail[:40] if tail else parsed.netloc
        return parsed.netloc
    # file_id — look up the original filename in the S3 staging area
    keys = s3.list_keys(f"uploads/{source}")
    if keys:
        return Path(sorted(keys)[0]).name[:40]
    return source[:40]


@app.get("/health")
def health():
    return {"status": "ok"}


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
    rag_chain = get_rag_chain(job_id)

    if rag_chain is None:
        # Cold pod (or restart) — rebuild the chain from the stored transcript
        job = get_job(job_id)
        if job and job["status"] == "done":
            transcript = get_transcript(job_id)
            if transcript:
                rag_chain = build_job_rag(transcript, job_id)
                register_rag_chain(job_id, rag_chain)
            else:
                raise HTTPException(
                    410,
                    "RAG index expired. Please re-process the video.",
                )
        else:
            raise HTTPException(404, "Job not found or still processing")

    answer = ask_question(rag_chain, req.question)
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
    """Remove a job and ALL its data: RAG chain, Chroma collection, S3
    objects (chunks + transcript + staged upload), and the DynamoDB row."""
    job = get_job(job_id)

    drop_rag_chain(job_id)
    drop_job_collection(job_id)

    # S3: job artifacts + the staged upload if the source was a file_id
    s3.delete_prefix(s3.job_prefix(job_id))
    if job and job.get("source"):
        source = job["source"]
        if not (
            source.startswith("http://") or source.startswith("https://")
        ) and "/" not in source and "\\" not in source:
            s3.delete_prefix(f"uploads/{source}")

    if not delete_job(job_id):
        raise HTTPException(404, "Job not found")
    return {"ok": True}
