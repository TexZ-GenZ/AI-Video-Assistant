// API client for the AI Video Assistant backend (FastAPI).
//
// All calls go to BASE_URL. Set VITE_API_URL to override the default.
// Use the Vite dev proxy in dev mode — no CORS issues.

export const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type Language = "english" | "hindi";

export type JobStatus = "processing" | "done" | "error";

export interface ProcessResponse {
  job_id: string;
  status: JobStatus;
}

export interface StatusResponse {
  job_id: string;
  status: JobStatus;
  progress?: string;
  error?: string;
}

export interface Results {
  title: string;
  summary: string;
  actionables: string;
  questions: string;
  information: string;
}

export interface AskResponse {
  answer: string;
}

export interface JobSummary {
  job_id: string;
  title: string | null;
  status: JobStatus;
  created_at: string;
}

export interface JobsResponse {
  jobs: JobSummary[];
}

export interface ProcessRequest {
  source: string;
  language: Language;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData
        ? {} // let the browser set Content-Type with boundary for multipart
        : { "Content-Type": "application/json" }),
      ...(init?.headers || {}),
    },
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body || res.statusText}`);
  }

  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/** Upload a video/audio file. Returns a file_id to pass as `source` to processVideo. */
export async function uploadFile(file: File): Promise<{ file_id: string }> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch("/api/upload", { method: "POST", body: form });
}

/** Kick off the full pipeline. `source` is a YouTube URL or a file_id from uploadFile. */
export function processVideo(req: ProcessRequest): Promise<ProcessResponse> {
  return apiFetch("/api/process", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

/** Poll for job progress. Call every 3 s while status === "processing". */
export function getStatus(job_id: string): Promise<StatusResponse> {
  return apiFetch(`/api/process/${job_id}/status`);
}

/** Get structured results for a completed job. */
export function getResults(job_id: string): Promise<Results> {
  return apiFetch(`/api/process/${job_id}/results`);
}

/** Ask a question grounded in the video transcript. */
export function askQuestion(
  job_id: string,
  question: string,
): Promise<AskResponse> {
  return apiFetch(`/api/process/${job_id}/ask`, {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

/** List all jobs for the history sidebar. */
export function listJobs(): Promise<JobsResponse> {
  return apiFetch("/api/jobs");
}

/** Delete a job permanently. */
export function deleteJob(job_id: string): Promise<{ ok: boolean }> {
  return apiFetch(`/api/jobs/${job_id}`, { method: "DELETE" });
}
