import { useRef, useState } from "react";
import {
  Loader2,
  Paperclip,
  ArrowUp,
  RotateCcw,
  X,
  Youtube,
  ChevronDown,
} from "lucide-react";
import { Button } from "./ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import { uploadFile, type Language } from "../lib/videoApi";

const ACCEPTED = ".mp4,.mkv,.webm,.mp3,.wav,.m4a";

export type AppState =
  | "idle"
  | "uploading"
  | "processing"
  | "done"
  | "error";

const SUGGESTIONS = [
  "https://youtube.com/watch?v=dQw4w9WgXcQ",
  "Summarize a lecture",
  "Extract action items from a meeting",
  "Find key decisions in a talk",
];

interface InputSectionProps {
  state: AppState;
  /** Reserved for callers; the full processing state is rendered by App. */
  progress?: string;
  error: string;
  onProcess: (source: string, language: Language) => void;
  onRetry: () => void;
}

const LANG_LABEL: Record<Language, string> = {
  english: "English",
  hindi: "हिन्दी Hindi",
};

export function InputSection({
  state,
  error,
  onProcess,
  onRetry,
}: InputSectionProps) {
  const [url, setUrl] = useState("");
  const [fileName, setFileName] = useState("");
  const [fileId, setFileId] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [language, setLanguage] = useState<Language>("english");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const busy = state === "processing" || uploading;

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

  const clearFile = () => {
    setFileName("");
    setFileId("");
    setUploadError("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleSubmit = () => {
    const source = url.trim() || fileId;
    if (!source || busy) return;
    onProcess(source, language);
  };

  const canSubmit = (url.trim().length > 0 || fileId.length > 0) && !busy;

  return (
    <div className="flex flex-col gap-4">
      {/* Composer */}
      <div className="group relative rounded-[1.75rem] border border-border bg-card p-2 shadow-[0_1px_0_rgba(0,0,0,0.02),0_12px_40px_-12px_rgba(80,40,20,0.15)] transition-shadow focus-within:border-primary/40 focus-within:shadow-[0_1px_0_rgba(0,0,0,0.02),0_16px_50px_-12px_rgba(180,90,50,0.28)]">
        <div className="flex items-start gap-3 px-4 pt-3">
          <Youtube className="mt-0.5 size-5 shrink-0 text-primary/70" />
          <input
            type="text"
            placeholder="Paste a YouTube link, or attach a video to analyze…"
            value={url}
            disabled={busy}
            className="flex-1 resize-none bg-transparent text-[1.05rem] leading-relaxed outline-none placeholder:text-muted-foreground/70 disabled:opacity-60"
            onChange={(e) => {
              setUrl(e.target.value);
              if (e.target.value) clearFile();
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                handleSubmit();
              }
            }}
          />
        </div>

        {fileName && (
          <div className="mx-4 mt-3 flex w-fit items-center gap-2 rounded-full bg-secondary py-1.5 pl-3 pr-1.5 text-sm text-secondary-foreground">
            <Paperclip className="size-3.5" />
            <span className="max-w-52 truncate">{fileName}</span>
            <button
              onClick={clearFile}
              className="rounded-full p-0.5 hover:bg-background/60"
            >
              <X className="size-3.5" />
            </button>
          </div>
        )}

        <div className="mt-2 flex items-center justify-between gap-2 px-2 pb-1">
          <div className="flex items-center gap-1">
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPTED}
              className="hidden"
              onChange={handleFile}
            />
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => fileInputRef.current?.click()}
              className="gap-1.5 rounded-full text-muted-foreground hover:text-foreground"
            >
              <Paperclip className="size-4" />
              Attach
            </Button>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  className="gap-1 rounded-full text-muted-foreground hover:text-foreground"
                >
                  {LANG_LABEL[language]}
                  <ChevronDown className="size-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                <DropdownMenuItem onClick={() => setLanguage("english")}>
                  English
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setLanguage("hindi")}>
                  हिन्दी Hindi
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          <Button
            size="icon"
            disabled={!canSubmit}
            onClick={handleSubmit}
            className="size-9 rounded-full transition-transform active:scale-95"
          >
            {busy ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <ArrowUp className="size-4" />
            )}
          </Button>
        </div>
      </div>

      {uploadError && (
        <div className="flex items-center gap-2 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-2">
          <span className="text-sm text-destructive">{uploadError}</span>
        </div>
      )}

      {/* Suggestions (only when idle) */}
      {state === "idle" && (
        <div className="flex flex-wrap justify-center gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => {
                if (s.startsWith("http")) setUrl(s);
              }}
              className="rounded-full border border-border bg-card/60 px-3.5 py-1.5 text-sm text-muted-foreground transition-colors hover:border-primary/30 hover:text-foreground"
            >
              {s.startsWith("http") ? "Try an example link" : s}
            </button>
          ))}
        </div>
      )}

      {/* Upload indicator (full processing state is rendered by App) */}
      {uploading && (
        <div className="flex items-center justify-center gap-3 rounded-2xl border border-border bg-card/70 px-5 py-4">
          <Loader2 className="size-4 animate-spin text-primary" />
          <span className="font-mono text-sm text-muted-foreground">
            Uploading…
          </span>
        </div>
      )}

      {/* Error */}
      {state === "error" && (
        <div className="flex items-center justify-between gap-3 rounded-2xl border border-destructive/30 bg-destructive/10 px-5 py-4">
          <span className="text-sm text-destructive">
            {error || "Something went wrong."}
          </span>
          <Button size="sm" variant="outline" onClick={onRetry} className="gap-2">
            <RotateCcw className="size-3.5" />
            Retry
          </Button>
        </div>
      )}
    </div>
  );
}
