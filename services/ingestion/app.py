"""
Ingestion service — accepts sources (file upload / YouTube URL) and kicks
off jobs via the SQS pipeline.

Exposes:
  POST /api/upload   — multipart file upload → streamed to S3, returns { file_id }
  POST /api/process  — create DynamoDB job + publish to jobs queue, returns { job_id, status }
  GET  /health

Run with:  uvicorn services.ingestion.app:app --reload
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from shared import s3
from shared.dynamo import create_job, init_db
from shared.models import ProcessRequest, ProcessResponse, UploadResponse
from shared.queue import QUEUE_JOBS, publish


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="VideoSense Ingestion API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production (CORS_ORIGINS env)
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


# ── Upload ─────────────────────────────────────────────────────────────────

@app.post("/api/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    """Accept a video/audio file, stream it to S3, return a file_id.

    The upload lands in the staging area (uploads/{file_id}{ext}); the
    ingestion worker picks it up when a job references the file_id.
    """
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    max_bytes = int(os.getenv("MAX_UPLOAD_MB", "500")) * 1024 * 1024

    f = file.file
    if f is None:
        raise HTTPException(400, "Empty upload")

    f.seek(0, os.SEEK_END)
    size = f.tell()
    f.seek(0)
    if size > max_bytes:
        raise HTTPException(
            413,
            f"File too large (max {max_bytes // (1024 * 1024)} MB)",
        )

    file_id = uuid.uuid4().hex
    ext = (Path(file.filename).suffix or ".mp4").lower()[:12]
    key = f"uploads/{file_id}{ext}"

    s3.upload_fileobj(key, f, content_type=file.content_type)

    return UploadResponse(file_id=file_id)


# ── Process ────────────────────────────────────────────────────────────────

@app.post("/api/process", response_model=ProcessResponse)
def process_video(req: ProcessRequest):
    """Create the job and hand it to the ingestion worker via SQS."""
    job_id = uuid.uuid4().hex
    create_job(job_id, req.source, req.language)

    publish(QUEUE_JOBS, {"job_id": job_id, "source": req.source, "language": req.language})

    return ProcessResponse(job_id=job_id, status="processing")
