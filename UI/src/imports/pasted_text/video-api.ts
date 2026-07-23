Frontend (UI/)
Rewritten: 
src/app/lib/videoApi.ts
The entire file was replaced — stripped ~180 lines of mocks, real fetch only, added uploadFile + deleteJob. Here's the final state:

ts

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
Modified: 
src/app/components/input-section.tsx
9 edits across the file. Here's the diff-style summary — apply each pair:

1. Import line — change:

tsx

import type { Language } from "../lib/videoApi";
→

tsx

import { uploadFile, type Language } from "../lib/videoApi";
2. Suggestions array — add one entry:

tsx

const SUGGESTIONS = [
  "https://youtube.com/watch?v=dQw4w9WgXcQ",
  "Summarize a lecture",
  "Extract action items from a meeting",
  "Find key decisions in a talk",   // ← add this
];
3. State declarations — replace fileSource with fileId + uploading + uploadError:

tsx

// OLD:
  const [fileName, setFileName] = useState("");
  const [fileSource, setFileSource] = useState("");
  const [language, setLanguage] = useState<Language>("english");

// NEW:
  const [fileName, setFileName] = useState("");
  const [fileId, setFileId] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [language, setLanguage] = useState<Language>("english");
4. The busy variable — change from:

tsx

  const busy = state === "processing" || state === "uploading";
→

tsx

  const busy = state === "processing" || uploading;
5. handleFile function — replace entirely:

tsx

// OLD:
  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    setUrl("");
    const reader = new FileReader();
    reader.onload = () => setFileSource(String(reader.result));
    reader.readAsDataURL(file);
  };

// NEW:
  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    setUrl("");
    setUploadError("");
    setFileId("");
    try {
      setUploading(true);
      const { file_id } = await uploadFile(file);
      setFileId(file_id);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
      setFileName("");
    } finally {
      setUploading(false);
    }
  };
6. clearFile function — replace:

tsx

// OLD:
  const clearFile = () => {
    setFileName("");
    setFileSource("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

// NEW:
  const clearFile = () => {
    setFileName("");
    setFileId("");
    setUploadError("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  };
7. handleSubmit — change fileSource || fileName to fileId:

tsx

// OLD:
    const source = url.trim() || fileSource || fileName;

// NEW:
    const source = url.trim() || fileId;
8. canSubmit — change fileSource to fileId:

tsx

// OLD:
  const canSubmit = (url.trim().length > 0 || fileSource.length > 0) && !busy;

// NEW:
  const canSubmit = (url.trim().length > 0 || fileId.length > 0) && !busy;
9. JSX — add upload error display right before {state === "idle" && (:

tsx

      {uploadError && (
        <div className="flex items-center gap-2 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-2">
          <span className="text-sm text-destructive">{uploadError}</span>
        </div>
      )}
10. JSX — processing indicator text — change from:

tsx

            {progress || "Starting…"}
→

tsx

            {uploading ? "Uploading…" : progress || "Starting…"}
Modified: 
src/app/components/history-sidebar.tsx
1. Import — add X:

tsx

// OLD:
import { Plus, Video, Loader2, Check, TriangleAlert } from "lucide-react";

// NEW:
import { Plus, Video, Loader2, Check, TriangleAlert, X } from "lucide-react";
2. Props interface — add onDelete:

tsx

interface HistorySidebarProps {
  jobs: JobSummary[];
  activeJobId: string | null;
  onSelect: (jobId: string) => void;
  onDelete: (jobId: string) => void;   // ← add
  onNew: () => void;
}
3. Destructure — add onDelete:

tsx

export function HistorySidebar({
  jobs,
  activeJobId,
  onSelect,
  onDelete,   // ← add
  onNew,
}: HistorySidebarProps) {
4. Job item template — replace the single <button> with a <div> wrapper containing a select button + delete button:

tsx

// OLD:
            <button
              key={job.job_id}
              onClick={() => onSelect(job.job_id)}
              className={
                "group flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left transition-colors " +
                (active
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "hover:bg-sidebar-accent/60")
              }
            >
              <Video
                className={
                  "size-4 shrink-0 " +
                  (active ? "text-primary" : "text-muted-foreground")
                }
              />
              <span className="flex-1 truncate text-sm">{job.title}</span>
              <StatusIcon status={job.status} />
            </button>

// NEW:
            <div
              key={job.job_id}
              className={
                "group flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left transition-colors " +
                (active
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "hover:bg-sidebar-accent/60")
              }
            >
              <button
                onClick={() => onSelect(job.job_id)}
                className="flex min-w-0 flex-1 items-center gap-2.5"
              >
                <Video
                  className={
                    "size-4 shrink-0 " +
                    (active ? "text-primary" : "text-muted-foreground")
                  }
                />
                <span className="flex-1 truncate text-sm">
                  {job.title || "Untitled"}
                </span>
                <StatusIcon status={job.status} />
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(job.job_id);
                }}
                className="shrink-0 rounded-full p-0.5 text-muted-foreground opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
                title="Remove from history"
              >
                <X className="size-3.5" />
              </button>
            </div>
Modified: 
src/app/App.tsx
1. Import — add deleteJob:

tsx

import {
  askQuestion,
  deleteJob,        // ← add
  getResults,
  getStatus,
  listJobs,
  processVideo,
  type JobSummary,
  type Language,
  type Results,
} from "./lib/videoApi";
2. Add handleDelete right before handleSelectJob:

tsx

  const handleDelete = async (id: string) => {
    try {
      await deleteJob(id);
      if (id === jobId) {
        handleNew();
      }
      refreshJobs();
    } catch {
      toast.error("Failed to delete job");
    }
  };
3. Both HistorySidebar instances — add onDelete={handleDelete}:

tsx

    <HistorySidebar
      jobs={jobs}
      activeJobId={jobId}
      onSelect={handleSelectJob}
      onDelete={handleDelete}     // ← add
      onNew={handleNew}
    />
(There are two instances — one in the sidebar variable used in both the desktop <aside> and mobile <Sheet>. The variable is defined once, so one change covers both.)

4. After <ResultsSection> — add jump-to-chat link:

tsx

              {state === "done" && results && (
                <>
                  <ResultsSection results={results} />
                  <div className="flex justify-center">                          {/* ← add */}
                    <a                                                                 {/* ← add */}
                      href="#chat"                                                     {/* ← add */}
                      className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-4 py-2 text-sm text-muted-foreground transition-colors hover:border-primary/30 hover:text-foreground"  {/* ← add */}
                    >                                                                    {/* ← add */}
                      ↓ Jump to chat                                                   {/* ← add */}
                    </a>                                                                {/* ← add */}
                  </div>                                                               {/* ← add */}
                  <ChatPanel
Modified: 
src/app/components/chat-panel.tsx
1. Suggestion chips — replace:

tsx

// OLD:
const PROMPTS = [
  "What chunk size did they recommend?",
  "How does MMR work?",
  "Summarize the main takeaway",
];

// NEW:
const PROMPTS = [
  "Summarize the main takeaway",
  "What are the key decisions?",
  "What action items were mentioned?",
];
2. Root div — add id="chat":

tsx

// OLD:
    <div className="flex flex-col gap-4 rounded-2xl border border-border bg-card p-5">

// NEW:
    <div id="chat" className="flex flex-col gap-4 rounded-2xl border border-border bg-card p-5">
Modified: 
index.html
html

<!-- OLD -->
<title>Review design changes</title>
<meta name="description" content="Effortlessly track and manage tasks with this intuitive web app designed for individuals and teams, enhancing productivity and collaboration." />

<!-- NEW -->
<title>ReelSense — AI Video Assistant</title>
<meta name="description" content="Understand any video in seconds — get summaries, action items, key facts, and chat with the transcript." />
Modified: 
package.json
json

// OLD:
"name": "@figma/my-make-file",

// NEW:
"name": "reelsense-ui",
That's every change. Apply these to your UI repo and the two codebases will be in sync.