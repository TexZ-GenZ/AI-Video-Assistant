import { motion } from "motion/react";
import { Download, FileText, CheckSquare, HelpCircle, Sparkles } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Button } from "./ui/button";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "./ui/accordion";
import type { Results } from "../lib/videoApi";

// "full" = all 4 cards + title + export (legacy)
// "summary" = title + export + summary card only
// "details" = action-items, questions, key-info cards only (no title)
export type ResultsMode = "full" | "summary" | "details";

interface ResultsSectionProps {
  results: Results;
  mode?: ResultsMode;
}

const SECTIONS: {
  key: keyof Results;
  label: string;
  icon: LucideIcon;
}[] = [
  { key: "summary", label: "Summary", icon: FileText },
  { key: "actionables", label: "Action Items", icon: CheckSquare },
  { key: "questions", label: "Questions Raised", icon: HelpCircle },
  { key: "information", label: "Key Information", icon: Sparkles },
];

/** Convert basic markdown (**bold**, ### headings) to HTML. */
export function renderMarkdown(text: string): string {
  return text
    .split("\n")
    .map((line) => {
      const isHeading = /^#{1,3}\s/.test(line);
      let html = line
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/^###\s+(.+)/, "<h3 class='text-base font-semibold text-foreground mt-3 mb-1'>$1</h3>")
        .replace(/^##\s+(.+)/, "<h3 class='text-lg font-semibold text-foreground mt-4 mb-2'>$1</h3>")
        .replace(/^#\s+(.+)/, "<h2 class='text-xl font-bold text-foreground mt-4 mb-2'>$1</h2>");
      // Wrap non-heading, non-empty lines in <p>
      if (!isHeading && line.trim()) {
        html = `<p class="text-[0.95rem] leading-relaxed text-foreground/85">${html}</p>`;
      }
      if (!line.trim()) {
        html = "<div class='h-2'></div>";
      }
      return html;
    })
    .join("\n");
}

export function Lines({ text }: { text: string }) {
  const lines = text.split("\n").filter((l) => l.trim().length > 0);
  return (
    <ul className="flex flex-col gap-2.5">
      {lines.map((line, i) => (
        <li
          key={i}
          className="flex gap-2.5 text-[0.95rem] leading-relaxed text-foreground/85"
        >
          <span className="mt-2 size-1.5 shrink-0 rounded-full bg-primary/50" />
          <span>{line.replace(/^[•\d.\-)\s]+/, "")}</span>
        </li>
      ))}
    </ul>
  );
}

export function ResultsSection({ results, mode = "full" }: ResultsSectionProps) {
  const handleExport = () => {
    const content = [
      results.title,
      "",
      ...SECTIONS.map((s) => `## ${s.label}\n${results[s.key]}\n`),
    ].join("\n");
    const blob = new Blob([content], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${results.title.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}.txt`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const showTitle = mode === "full" || mode === "summary";
  const cards =
    mode === "details"
      ? SECTIONS.filter((s) => s.key !== "summary")
      : mode === "summary"
        ? SECTIONS.filter((s) => s.key === "summary")
        : SECTIONS;

  return (
    <div className="flex flex-col gap-6">
      {/* Title row */}
      {showTitle && (
        <div className="flex items-start justify-between gap-4 border-b border-border pb-5">
          <div className="flex flex-col gap-2">
            <span className="font-mono text-xs uppercase tracking-[0.18em] text-primary">
              Analysis complete
            </span>
            <h2 className="font-display text-[2rem] leading-[1.15] tracking-tight text-foreground">
              {results.title.replace(/\*\*/g, "").replace(/^["']+|["']+$/g, "").trim()}
            </h2>
          </div>
          {mode === "full" && (
            <Button
              variant="outline"
              size="sm"
              className="shrink-0 gap-2 rounded-full"
              onClick={handleExport}
            >
              <Download className="size-4" />
              Export
            </Button>
          )}
        </div>
      )}

      {/* Section cards */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {cards.map((s, i) => {
          const Icon = s.icon;
          const isSummary = s.key === "summary";
          const wide = isSummary && mode !== "details" ? "md:col-span-2" : "";
          return (
            <motion.section
              key={s.key}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.35, delay: i * 0.06, ease: "easeOut" }}
              className={`rounded-2xl border border-border bg-card p-5 transition-colors hover:border-primary/25 ${wide}`}
            >
              {isSummary ? (
                <Accordion
                  type="single"
                  collapsible
                  defaultValue={mode === "full" ? "summary" : undefined}
                >
                  <AccordionItem value="summary" className="border-none">
                    <AccordionTrigger className="py-0 hover:no-underline">
                      <div className="flex items-center gap-2.5">
                        <span className="flex size-8 items-center justify-center rounded-lg bg-accent text-accent-foreground">
                          <Icon className="size-4" />
                        </span>
                        <h3 className="font-display text-lg text-foreground">
                          {s.label}
                        </h3>
                      </div>
                    </AccordionTrigger>
                    <AccordionContent>
                      <div
                        className="pt-4 text-foreground/85"
                        dangerouslySetInnerHTML={{ __html: renderMarkdown(results.summary) }}
                      />
                    </AccordionContent>
                  </AccordionItem>
                </Accordion>
              ) : (
                <>
                  <div className="mb-4 flex items-center gap-2.5">
                    <span className="flex size-8 items-center justify-center rounded-lg bg-accent text-accent-foreground">
                      <Icon className="size-4" />
                    </span>
                    <h3 className="font-display text-lg text-foreground">
                      {s.label}
                    </h3>
                  </div>
                  <Lines text={results[s.key]} />
                </>
              )}
            </motion.section>
          );
        })}
      </div>
    </div>
  );
}
