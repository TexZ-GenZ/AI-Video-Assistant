"""
Ingestion service — accepts sources (file upload / YouTube URL) and kicks
off jobs.

Exposes:
  POST /api/upload   — multipart file upload, returns { file_id }
  POST /api/process  — start a job, returns { job_id, status }
  GET  /health

Run with:  uvicorn services.ingestion.app:app --reload
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from shared.models import ProcessRequest, ProcessResponse, UploadResponse
from shared.dynamo import create_job
import shared.pipeline as pipeline

UPLOAD_DIR = Path("downloads/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_WORKERS = 4

app = FastAPI(title="VideoSense Ingestion API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production (CORS_ORIGINS env)
    allow_methods=["*"],
    allow_headers=["*"],
)

# Thread pool for background pipeline execution (interim — replaced by SQS)
_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)


@app.get("/health")
def health():
    return {"status": "ok"}


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
    """Kick off the full pipeline in a background thread (interim)."""
    job_id = uuid.uuid4().hex
    create_job(job_id, req.source, req.language)

    _executor.submit(pipeline._run_job, job_id, req.source, req.language)

    return ProcessResponse(job_id=job_id, status="processing")
