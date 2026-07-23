Build a simple single-page website for an **AI Video Assistant**. The frontend talks to a FastAPI backend (explained below). Use **plain HTML + CSS + vanilla JavaScript** (or React/Vue if you prefer — keep it one page). No build tools required. The page should be clean, modern, and mobile-friendly.

### What the product does

The user provides a YouTube URL or uploads a local audio/video file. The backend downloads it, transcribes it (English via Whisper, Hindi via Sarvam), then uses an LLM to:
- Generate a title
- Write a summary
- Extract action items
- Extract key information (facts, dates, names, decisions)
- Extract questions asked in the video

The user can also **chat with the video** — ask questions and get answers grounded in the transcript via RAG.

---

### Backend API (FastAPI — you're building the frontend for this)

Base URL: configurable (default `http://localhost:8000`)

#### 1. Start Processing
```
POST /api/process
Content-Type: application/json

Request body:
{
  "source": "https://youtube.com/watch?v=..." | "local_file_path",
  "language": "english" | "hindi"
}

Response (200):
{
  "job_id": "uuid-string",
  "status": "processing"
}
```
Processing is async — this returns immediately. Transcription + LLM analysis takes 1–5 minutes.

#### 2. Check Status (poll every 3–5 seconds)
```
GET /api/process/{job_id}/status

Response while processing:
{
  "job_id": "uuid-string",
  "status": "processing",
  "progress": "Transcribing chunk 2/4..."
}

Response when done:
{
  "job_id": "uuid-string",
  "status": "done"
}

Response on error:
{
  "job_id": "uuid-string",
  "status": "error",
  "error": "Something went wrong"
}
```

#### 3. Get Results
```
GET /api/process/{job_id}/results

Response:
{
  "title": "How to Build a RAG Pipeline",
  "summary": "• Covers chunking strategies\n• Explains vector databases\n• ...",
  "actionables": "1. Install ChromaDB\n2. Choose an embedding model\n...",
  "questions": "1. What is the ideal chunk size?\n2. How does MMR work?\n...",
  "information": "1. Chunk sizes of 500-1000 work best\n2. MMR balances relevance and diversity\n..."
}
```

#### 4. Ask a Question (chat with the video)
```
POST /api/process/{job_id}/ask
Content-Type: application/json

Request body:
{
  "question": "What chunk size did they recommend?"
}

Response:
{
  "answer": "They recommended chunk sizes between 500 and 1000 tokens, with 50-100 token overlap."
}
```

#### 5. List All Jobs (optional — for a sidebar/history)
```
GET /api/jobs

Response:
{
  "jobs": [
    { "job_id": "...", "title": "How to Build a RAG Pipeline", "status": "done", "created_at": "..." },
    ...
  ]
}
```

---

### Frontend Requirements

**Page layout: three sections flowing top-to-bottom.**

**Section 1 — Input**
- A text input for YouTube URL
- A file upload button for local audio/video (accept `.mp4`, `.mkv`, `.webm`, `.mp3`, `.wav`, `.m4a`)
- A language dropdown: English / Hindi (default: English)
- A big "Process Video" button
- Show a progress indicator (spinner + status text like "Downloading audio..." / "Transcribing chunk 2/4...") while `status === "processing"`

**Section 2 — Results (shown after processing completes)**
- Title (large, bold)
- Four collapsible/expandable cards or tabs:
  - 📝 Summary
  - ✅ Action Items
  - ❓ Questions
  - 📊 Key Information
- A download/export button (stretch goal — exports results as text/PDF)

**Section 3 — Chat**
- A chat panel: scrollable message history (user questions + assistant answers)
- A text input + send button at the bottom
- Pressing Enter sends; disable while waiting for response
- Assistant responses should be clearly distinguished (different background/bubble)
- If the backend returns an error (e.g. job expired), show a friendly message

**States to handle:**
- **Idle** — empty form, nothing happening
- **Uploading** (if local file) — progress bar for upload
- **Processing** — spinner + polling status, disable the form
- **Done** — show results + enable chat
- **Error** — show error message, allow retry

**UX details:**
- Auto-scroll chat to bottom on new messages
- Disable the "Process Video" button while a job is running
- Show a small "History" sidebar (collapsible on mobile) listing past jobs — clicking one loads its results and reconnects the chat
- The job_id should be stored in `localStorage` so refreshing the page doesn't lose the session
- Polling interval: 3 seconds during processing

---

### Things YOU need to decide (respond with your choices)

1. **CSS framework?** Plain CSS, Tailwind, Bootstrap, or something else?
2. **JS framework?** Vanilla JS, React, Vue, Svelte, etc.?
3. **File upload flow** — should the frontend upload the file directly in the POST body alongside the source, or should there be a separate upload endpoint? (Recommendation: base64-encode and include in the JSON body for files under ~100MB; separate `POST /api/upload` multipart endpoint for larger files.)
4. **Chat history persistence** — should chat messages survive a page refresh? (Recommendation: store in `localStorage` keyed by job_id.)
5. **Styling vibe** — dark mode, light mode, or both? Minimalist or colorful?
6. **Single HTML file** or a proper project with separate CSS/JS files?

Respond with your choices, then build it. Keep it under 500 lines if using vanilla JS, or a clean component structure if using a framework.