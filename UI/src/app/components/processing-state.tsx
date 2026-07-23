import { motion } from "motion/react";
import { Check, Download, FileAudio, Sparkles, Database } from "lucide-react";
import type { LucideIcon } from "lucide-react";

interface ProcessingStateProps {
  progress: string;
}

const STEPS: { key: string; label: string; icon: LucideIcon; match: RegExp }[] =
  [
    { key: "download", label: "Download", icon: Download, match: /download|fetch/i },
    {
      key: "transcribe",
      label: "Transcribe",
      icon: FileAudio,
      match: /transcrib|audio|chunk/i,
    },
    {
      key: "analyze",
      label: "Analyze",
      icon: Sparkles,
      match: /analy|llm|summar|extract/i,
    },
    { key: "index", label: "Index", icon: Database, match: /index|embed|rag|vector/i },
  ];

function currentStep(progress: string): number {
  const idx = STEPS.findIndex((s) => s.match.test(progress));
  return idx === -1 ? 0 : idx;
}

export function ProcessingState({ progress }: ProcessingStateProps) {
  const active = currentStep(progress);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col gap-6"
    >
      {/* Step indicator */}
      <div className="rounded-2xl border border-border bg-card/70 p-5">
        <div className="flex items-center justify-between gap-2">
          {STEPS.map((step, i) => {
            const Icon = step.icon;
            const done = i < active;
            const isCurrent = i === active;
            return (
              <div key={step.key} className="flex flex-1 items-center gap-2">
                <div className="flex flex-col items-center gap-2">
                  <motion.span
                    animate={
                      isCurrent
                        ? { scale: [1, 1.12, 1], opacity: [0.7, 1, 0.7] }
                        : { scale: 1, opacity: 1 }
                    }
                    transition={
                      isCurrent
                        ? { duration: 1.6, repeat: Infinity, ease: "easeInOut" }
                        : { duration: 0.3 }
                    }
                    className={
                      "flex size-10 items-center justify-center rounded-xl border transition-colors " +
                      (done
                        ? "border-primary/40 bg-primary text-primary-foreground"
                        : isCurrent
                          ? "border-primary/50 bg-primary/10 text-primary shadow-[0_0_24px_-6px_var(--primary)]"
                          : "border-border bg-muted/50 text-muted-foreground")
                    }
                  >
                    {done ? (
                      <Check className="size-5" />
                    ) : (
                      <Icon className="size-5" />
                    )}
                  </motion.span>
                  <span
                    className={
                      "text-xs " +
                      (i <= active
                        ? "text-foreground"
                        : "text-muted-foreground")
                    }
                  >
                    {step.label}
                  </span>
                </div>
                {i < STEPS.length - 1 && (
                  <div className="relative -mt-6 h-0.5 flex-1 overflow-hidden rounded-full bg-border">
                    <motion.div
                      className="absolute inset-y-0 left-0 bg-primary"
                      initial={{ width: "0%" }}
                      animate={{ width: i < active ? "100%" : "0%" }}
                      transition={{ duration: 0.5 }}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Animated gradient progress bar */}
        <div className="relative mt-5 h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <motion.div
            className="absolute inset-y-0 w-1/2 rounded-full"
            style={{
              background:
                "linear-gradient(90deg, transparent, var(--primary), transparent)",
            }}
            animate={{ x: ["-50%", "200%"] }}
            transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
          />
        </div>

        <p className="mt-3 text-center font-mono text-sm text-muted-foreground">
          {progress || "Starting…"}
        </p>
      </div>

      {/* Shimmer skeleton preview of the results layout */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className={
              "overflow-hidden rounded-2xl border border-border bg-card p-5 " +
              (i === 0 ? "md:col-span-2" : "")
            }
          >
            <div className="mb-4 flex items-center gap-2.5">
              <Shimmer className="size-8 rounded-lg" />
              <Shimmer className="h-4 w-32 rounded" />
            </div>
            <div className="flex flex-col gap-2.5">
              {Array.from({ length: i === 0 ? 4 : 3 }).map((_, j) => (
                <Shimmer
                  key={j}
                  className="h-3.5 rounded"
                  style={{ width: `${88 - j * 12}%` }}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </motion.div>
  );
}

function Shimmer({
  className = "",
  style,
}: {
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div
      className={"relative overflow-hidden bg-muted " + className}
      style={style}
    >
      <motion.div
        className="absolute inset-0"
        style={{
          background:
            "linear-gradient(90deg, transparent, var(--accent), transparent)",
        }}
        animate={{ x: ["-100%", "100%"] }}
        transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
      />
    </div>
  );
}
