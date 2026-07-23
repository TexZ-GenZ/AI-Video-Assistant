import { Plus, Video, Loader2, Check, TriangleAlert, X } from "lucide-react";
import { Button } from "./ui/button";
import type { JobSummary } from "../lib/videoApi";

interface HistorySidebarProps {
  jobs: JobSummary[];
  activeJobId: string | null;
  onSelect: (jobId: string) => void;
  onDelete: (jobId: string) => void;
  onNew: () => void;
}

function StatusIcon({ status }: { status: JobSummary["status"] }) {
  if (status === "done") return <Check className="size-3.5 text-primary" />;
  if (status === "error")
    return <TriangleAlert className="size-3.5 text-destructive" />;
  return <Loader2 className="size-3.5 animate-spin text-muted-foreground" />;
}

export function HistorySidebar({
  jobs,
  activeJobId,
  onSelect,
  onDelete,
  onNew,
}: HistorySidebarProps) {
  return (
    <div className="flex h-full flex-col gap-4">
      <Button
        onClick={onNew}
        variant="outline"
        className="justify-start gap-2 rounded-full"
      >
        <Plus className="size-4" />
        New analysis
      </Button>

      <div className="px-1">
        <span className="font-mono text-xs uppercase tracking-[0.15em] text-muted-foreground">
          Recent
        </span>
      </div>

      <div className="flex flex-1 flex-col gap-1 overflow-y-auto">
        {jobs.length === 0 && (
          <p className="px-1 py-2 text-sm text-muted-foreground">
            Nothing yet — analyze your first video.
          </p>
        )}
        {jobs.map((job) => {
          const active = job.job_id === activeJobId;
          return (
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
                  {job.title ? job.title.replace(/\*\*/g, "").replace(/^["']+|["']+$/g, "").trim() || "Untitled" : "Untitled"}
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
          );
        })}
      </div>
    </div>
  );
}
