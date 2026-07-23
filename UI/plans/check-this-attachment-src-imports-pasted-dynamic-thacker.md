# ReelSense — Backend Sync + UX Polish

## Context

ReelSense (AI Video Assistant) is functional and visually themed, but has two gaps:

1. **Backend drift** — the live `src/app/lib/videoApi.ts` is still the demo *mock* client I first built. The user's real FastAPI repo has moved on (see `src/imports/pasted_text/video-api.ts`): real-fetch only, plus `uploadFile` (multipart → `file_id`) and `deleteJob`. The frontend must be brought in sync so the two codebases match.
2. **Weak UX** — the processing state feels frozen (tiny dot + text), results/chat pop in with no transition, the hero→results layout teleports, and results+chat feel like two bolted-together tools.

User decisions: **apply both the sync edits and the UX polish**, and reorganize results+chat as **Tabs (Analysis | Chat)**.

Stack: React 18, TS, Tailwind v4, shadcn/ui, Lucide, `motion` (v12, already installed → import from `motion/react`). Constraints: keep one page (no routing), keep all existing features (upload, language picker, dark mode, history, export), mobile responsive, TS interfaces unchanged.

## Part A — Backend sync (apply the doc verbatim)

Apply the edits exactly as specified in `src/imports/pasted_text/video-api.ts`:

- **`src/app/lib/videoApi.ts`** — replace with the doc's real-fetch version: `BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000"`, `apiFetch` helper (FormData-aware, throws on `!res.ok`), and functions `uploadFile`, `processVideo`, `getStatus`, `getResults`, `askQuestion`, `listJobs`, `deleteJob`. `JobSummary.title` becomes `string | null`.
- **`src/app/components/input-section.tsx`** — the 10 listed edits: import `uploadFile`; add 4th suggestion; replace `fileSource` state with `fileId`/`uploading`/`uploadError`; `busy = state === "processing" || uploading`; async `handleFile` that uploads and stores `file_id`; updated `clearFile`; `source = url.trim() || fileId`; `canSubmit` uses `fileId`; upload-error block; processing text shows "Uploading…".
- **`src/app/components/history-sidebar.tsx`** — add `X` import, `onDelete` prop, split job row into a select `<button>` + a hover-reveal delete `<button>` (with `title || "Untitled"`).
- **`src/app/App.tsx`** — import `deleteJob`; add `handleDelete` (calls `deleteJob`, `handleNew` if active, `refreshJobs`, toast on failure); pass `onDelete={handleDelete}` to the (single) `sidebar` element.
- **`src/app/components/chat-panel.tsx`** — swap `PROMPTS` to the generic set. (The `id="chat"` / jump-to-chat link in the doc is superseded by the Tabs layout in Part B — skip it.)
- **`index.html`** title/description and **`package.json`** `name` → per doc.

> ⚠️ Preview note: real-fetch removes the mock fallback, so nothing renders in preview unless the FastAPI backend is reachable (via `VITE_API_URL` or a Vite dev proxy). This is expected and was confirmed with the user.

## Part B — UX polish

### B1. Animated processing state (brief #1)
New **`src/app/components/processing-state.tsx`**, rendered while `state === "processing"` (replaces the current inline dot+text in the processing branch):
- **Step indicator** — phases `Download → Transcribe → Analyze → Index`. Derive the active step from the `progress` string (e.g. `/download/i`, `/transcrib/i`, `/analy|llm/i`, `/index/i`); completed steps get a filled check, current step glows/pulses (Motion), future steps muted. Show the raw `progress` text in mono beneath.
- **Animated gradient progress bar** — indeterminate sweeping gradient in `--primary`.
- **Shimmer skeleton cards** — mirror the 4 result sections (full-width Summary + 2×2 grid) with a pulsing shimmer, previewing the arriving layout.

### B2. Smooth hero → results transition (brief #3)
- Keep **one** persistent `InputSection` wrapped in a Motion `layout` container. Instead of swapping between a centered hero block and a top-aligned block, use a single flex column whose `justify-content` animates from `center` (idle/error) to `flex-start` (processing/done). The composer keeps its identity and glides up rather than teleporting.
- Hero copy (headline/subhead/badge) wrapped in `<AnimatePresence>` — fades/collapses out when leaving `idle`.

### B3. Results "arrival" (brief #2)
- Wrap result cards in Motion with a **staggered fade-up** (`initial opacity:0, y:12` → `animate`, ~60ms stagger).
- Fire a subtle success `toast.success("Analysis ready")` on transition into `done` (from `App.tsx`). No confetti/sound — keep it refined.

### B4. Tabs: Analysis | Chat (brief #2/#4)
- New **`src/app/components/analysis-view.tsx`** wrapping the existing `ResultsSection` (keeps the 4-card grid + export button).
- In `App.tsx` `done` branch, use shadcn **`Tabs`** (`src/app/components/ui/tabs.tsx`): `TabsList` with "Analysis" and "Chat" triggers (Chat trigger shows a small dot/badge once messages exist); `TabsContent` renders `AnalysisView` and `ChatPanel` respectively. Persist selected tab in component state (default "Analysis").
- Animate `TabsContent` swap with a light fade via Motion. `ChatPanel` keeps its own scroll + composer; drop the jump-to-chat link entirely.

### Files
- New: `components/processing-state.tsx`, `components/analysis-view.tsx`.
- Modified: `App.tsx` (sync + tabs + transition + success toast), `input-section.tsx` (sync + Motion layout host), `history-sidebar.tsx` (sync), `chat-panel.tsx` (sync prompts), `results-section.tsx` (add stagger animation), `lib/videoApi.ts` (sync), `index.html`, `package.json`.
- Reuse: shadcn `Tabs`, `Skeleton` (`components/ui/skeleton.tsx`) for shimmer, existing `toast` from `sonner`, theme tokens (`--primary`, `--accent`, `--muted`).

## Verification
- Preview loads; idle shows centered hero composer. (Live data requires the FastAPI backend via `VITE_API_URL`/proxy — mock fallback is gone by design.)
- Start a job → composer glides to top, animated step indicator advances through Download→Transcribe→Analyze→Index with a sweeping progress bar and shimmer skeletons.
- On completion → success toast; **Analysis** tab shows result cards fading up in stagger; switching to **Chat** tab reveals the chat panel; asking a question streams the typing indicator and answer.
- History sidebar: hover a job → delete (X) appears; deleting the active job resets to hero.
- File upload: choosing a file shows "Uploading…", then processes via returned `file_id`; upload failure shows the error chip.
- Toggle dark/light and resize to <1000px: hero, tabs, sidebar (Sheet on mobile) all hold.
- Confirm `import.meta.env.VITE_API_URL` override works and `deleteJob`/`uploadFile` hit the correct paths.
