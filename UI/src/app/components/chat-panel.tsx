import { useEffect, useRef, useState } from "react";
import { ArrowUp, MessageSquareText, Sparkles } from "lucide-react";
import { Button } from "./ui/button";
import { renderMarkdown } from "./results-section";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  error?: boolean;
}

interface ChatPanelProps {
  messages: ChatMessage[];
  awaiting: boolean;
  onSend: (question: string) => void;
}

const PROMPTS = [
  "Summarize the main takeaway",
  "What are the key decisions?",
  "What action items were mentioned?",
];

export function ChatPanel({ messages, awaiting, onSend }: ChatPanelProps) {
  const [value, setValue] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, awaiting]);

  const send = (text?: string) => {
    const q = (text ?? value).trim();
    if (!q || awaiting) return;
    onSend(q);
    setValue("");
  };

  return (
    <div className="flex flex-col gap-4 rounded-2xl border border-border bg-card p-5">
      <div className="flex items-center gap-2.5">
        <span className="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <MessageSquareText className="size-4" />
        </span>
        <h3 className="font-display text-lg text-foreground">
          Chat with this video
        </h3>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        className="flex max-h-[26rem] min-h-[8rem] flex-col gap-4 overflow-y-auto"
      >
        {messages.length === 0 && !awaiting && (
          <div className="flex flex-col items-start gap-3 py-2">
            <p className="text-sm text-muted-foreground">
              Answers are grounded in the transcript. Try asking:
            </p>
            <div className="flex flex-wrap gap-2">
              {PROMPTS.map((p) => (
                <button
                  key={p}
                  onClick={() => send(p)}
                  className="rounded-full border border-border bg-background/60 px-3 py-1.5 text-sm text-foreground/80 transition-colors hover:border-primary/30 hover:text-foreground"
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) =>
          m.role === "user" ? (
            <div key={m.id} className="flex justify-end">
              <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-sm leading-relaxed text-primary-foreground">
                {m.content}
              </div>
            </div>
          ) : (
            <div key={m.id} className="flex gap-3">
              <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
                <Sparkles className="size-3.5" />
              </span>
              {m.error ? (
                <div className="text-[0.95rem] leading-relaxed text-destructive">
                  {m.content}
                </div>
              ) : (
                <div
                  className="prose-sm text-[0.95rem] leading-relaxed text-foreground/90 [&_p]:my-1 [&_strong]:font-semibold [&_h3]:text-base [&_h3]:font-semibold [&_h3]:mt-3"
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(m.content) }}
                />
              )}
            </div>
          ),
        )}

        {awaiting && (
          <div className="flex gap-3">
            <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <Sparkles className="size-3.5" />
            </span>
            <div className="flex items-center gap-1.5 py-1.5">
              <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.3s]" />
              <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.15s]" />
              <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground" />
            </div>
          </div>
        )}
      </div>

      {/* Composer */}
      <div className="flex items-center gap-2 rounded-full border border-border bg-background/70 py-1.5 pl-4 pr-1.5 transition-colors focus-within:border-primary/40">
        <input
          placeholder="Ask a follow-up…"
          value={value}
          disabled={awaiting}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground/70 disabled:opacity-60"
        />
        <Button
          onClick={() => send()}
          disabled={awaiting || value.trim().length === 0}
          size="icon"
          className="size-8 shrink-0 rounded-full transition-transform active:scale-95"
        >
          <ArrowUp className="size-4" />
        </Button>
      </div>
    </div>
  );
}
