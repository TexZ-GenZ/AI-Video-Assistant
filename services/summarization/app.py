"""
Summarization service — results, chat (RAG), and history endpoints.

Exposes:
  GET  /api/process/{job_id}/status   — poll progress
  GET  /api/process/{job_id}/results  — structured analysis results
  POST /api/process/{job_id}/ask      — chat with the video (RAG)
  GET  /api/jobs                      — history sidebar
  DELETE /api/jobs/{job_id}           — remove a job
  GET  /health

Run with:  uvicorn services.summarization.app:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from shared.dynamo import get_job, get_transcript, list_jobs, delete_job
from shared.models import (
    StatusResponse,
    Results,
    AskRequest,
    AskResponse,
    JobSummary,
    JobsResponse,
)
from shared.pipeline import source_label
from services.summarization.worker import (
    get_rag_chain,
    drop_rag_chain,
    register_rag_chain,
    build_job_rag,
)
from services.summarization.rag import ask_question

app = FastAPI(title="VideoSense Summarization API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production (CORS_ORIGINS env)
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        # RAG chain wasn't kept (e.g. cold pod) — rebuild from stored transcript
        job = get_job(job_id)
        if job and job["status"] == "done":
            transcript = get_transcript(job_id)
            if transcript:
                rag_chain = build_job_rag(transcript)
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
                title=j.get("title") or source_label(j.get("source", "")),
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
    drop_rag_chain(job_id)
    if not delete_job(job_id):
        raise HTTPException(404, "Job not found")
    return {"ok": True}
