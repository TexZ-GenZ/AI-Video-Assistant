"""Pydantic models shared across services.

Must match the TypeScript interfaces in UI/src/app/lib/videoApi.ts.
"""

from pydantic import BaseModel


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
