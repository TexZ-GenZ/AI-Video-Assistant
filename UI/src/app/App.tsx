import { useCallback, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  Menu,
  Moon,
  Sun,
  Clapperboard,
  LayoutList,
  MessagesSquare,
} from "lucide-react";
import { Button } from "./components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "./components/ui/sheet";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "./components/ui/tabs";
import { Toaster } from "./components/ui/sonner";
import { toast } from "sonner";
import { InputSection, type AppState } from "./components/input-section";
import { ProcessingState } from "./components/processing-state";
import { ResultsSection } from "./components/results-section";
import { ChatPanel, type ChatMessage } from "./components/chat-panel";
import { HistorySidebar } from "./components/history-sidebar";
import {
  askQuestion,
  deleteJob,
  getResults,
  getStatus,
  listJobs,
  processVideo,
  type JobSummary,
  type Language,
  type Results,
} from "./lib/videoApi";

const LS_JOB = "ava:current_job";
const LS_CHAT = "ava:chat:";
const LS_THEME = "ava:theme";
const POLL_MS = 3000;

function useTheme() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(LS_THEME);
    const prefers = window.matchMedia?.(
      "(prefers-color-scheme: dark)",
    ).matches;
    setDark(stored ? stored === "dark" : !!prefers);
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem(LS_THEME, dark ? "dark" : "light");
  }, [dark]);

  return { dark, toggle: () => setDark((d) => !d) };
}

export default function App() {
  const { dark, toggle } = useTheme();

  const [state, setState] = useState<AppState>("idle");
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [results, setResults] = useState<Results | null>(null);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [awaiting, setAwaiting] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [activeTab, setActiveTab] = useState("chat");

  const lastRequest = useRef<{ source: string; language: Language } | null>(
    null,
  );
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refreshJobs = useCallback(async () => {
    try {
      const { jobs } = await listJobs();
      setJobs(jobs);
    } catch {
      // Backend unreachable (e.g. in preview without VITE_API_URL) — keep the
      // current list rather than crashing.
    }
  }, []);

  const loadChat = useCallback((id: string) => {
    const raw = localStorage.getItem(LS_CHAT + id);
    setMessages(raw ? (JSON.parse(raw) as ChatMessage[]) : []);
  }, []);

  const poll = useCallback(
    async (id: string) => {
      try {
        const status = await getStatus(id);
        if (status.status === "processing") {
          setProgress(status.progress || "Processing…");
          pollTimer.current = setTimeout(() => poll(id), POLL_MS);
          return;
        }
        if (status.status === "error") {
          setState("error");
          setError(status.error || "Processing failed.");
          return;
        }
        const res = await getResults(id);
        setResults(res);
        setState("done");
        setActiveTab("chat");
        setProgress("");
        toast.success("Analysis ready");
        refreshJobs();
      } catch (e) {
        setState("error");
        setError(e instanceof Error ? e.message : "Failed to fetch status.");
      }
    },
    [refreshJobs],
  );

  useEffect(() => {
    const savedId = localStorage.getItem(LS_JOB);
    refreshJobs();
    if (!savedId) return;
    setJobId(savedId);
    loadChat(savedId);
    (async () => {
      try {
        const status = await getStatus(savedId);
        if (status.status === "done") {
          const res = await getResults(savedId);
          setResults(res);
          setState("done");
        } else if (status.status === "processing") {
          setState("processing");
          poll(savedId);
        }
      } catch {
        /* stale session — ignore */
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(
    () => () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    },
    [],
  );

  const handleProcess = async (source: string, language: Language) => {
    lastRequest.current = { source, language };
    setState("processing");
    setError("");
    setResults(null);
    setMessages([]);
    setProgress("Starting…");
    try {
      const { job_id } = await processVideo({ source, language });
      setJobId(job_id);
      localStorage.setItem(LS_JOB, job_id);
      refreshJobs();
      poll(job_id);
    } catch (e) {
      setState("error");
      setError(e instanceof Error ? e.message : "Failed to start processing.");
    }
  };

  const handleRetry = () => {
    if (lastRequest.current) {
      handleProcess(lastRequest.current.source, lastRequest.current.language);
    } else {
      setState("idle");
      setError("");
    }
  };

  const handleNew = () => {
    if (pollTimer.current) clearTimeout(pollTimer.current);
    setMobileOpen(false);
    setState("idle");
    setResults(null);
    setMessages([]);
    setError("");
    setProgress("");
    setJobId(null);
    localStorage.removeItem(LS_JOB);
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteJob(id);
      if (id === jobId) handleNew();
      refreshJobs();
    } catch {
      toast.error("Failed to delete job");
    }
  };

  const handleSelectJob = async (id: string) => {
    if (pollTimer.current) clearTimeout(pollTimer.current);
    setMobileOpen(false);
    setJobId(id);
    localStorage.setItem(LS_JOB, id);
    loadChat(id);
    setError("");
    try {
      const status = await getStatus(id);
      if (status.status === "done") {
        const res = await getResults(id);
        setResults(res);
        setState("done");
      } else if (status.status === "processing") {
        setState("processing");
        poll(id);
      } else {
        setState("error");
        setError(status.error || "This job is unavailable.");
      }
    } catch (e) {
      setState("error");
      setError(e instanceof Error ? e.message : "Could not load this job.");
    }
  };

  const handleSend = async (question: string) => {
    if (!jobId) return;
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: question,
    };
    const next = [...messages, userMsg];
    setMessages(next);
    setAwaiting(true);
    try {
      const { answer } = await askQuestion(jobId, question);
      const finalMsgs = [
        ...next,
        { id: crypto.randomUUID(), role: "assistant" as const, content: answer },
      ];
      setMessages(finalMsgs);
      localStorage.setItem(LS_CHAT + jobId, JSON.stringify(finalMsgs));
    } catch (e) {
      const msg =
        e instanceof Error ? e.message : "Sorry, I couldn't answer that.";
      setMessages([
        ...next,
        {
          id: crypto.randomUUID(),
          role: "assistant" as const,
          content: msg,
          error: true,
        },
      ]);
      toast.error("Chat request failed");
    } finally {
      setAwaiting(false);
    }
  };

  const sidebar = (
    <HistorySidebar
      jobs={jobs}
      activeJobId={jobId}
      onSelect={handleSelectJob}
      onDelete={handleDelete}
      onNew={handleNew}
    />
  );

  const showHero = state === "idle" || state === "error";

  return (
    <div className="relative flex h-full w-full flex-col overflow-hidden bg-background text-foreground">
      {/* Ambient warm glow */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10"
        style={{
          background:
            "radial-gradient(60rem 40rem at 50% -10%, oklch(0.58 0.14 40 / 0.10), transparent 60%), radial-gradient(50rem 30rem at 100% 0%, oklch(0.6 0.13 320 / 0.06), transparent 55%)",
        }}
      />
      <Toaster />

      {/* Header */}
      <header className="flex items-center gap-3 border-b border-border/70 px-4 py-3 backdrop-blur-sm">
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" className="lg:hidden">
              <Menu className="size-5" />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-72 bg-sidebar p-4">
            <SheetHeader className="sr-only">
              <SheetTitle>History</SheetTitle>
            </SheetHeader>
            {sidebar}
          </SheetContent>
        </Sheet>

        <div className="flex items-center gap-2.5">
          <span className="flex size-8 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <Clapperboard className="size-4" />
          </span>
          <span className="font-display text-lg tracking-tight">
            Video<span className="text-primary">Sense</span>
          </span>
        </div>

        <Button
          variant="ghost"
          size="icon"
          className="ml-auto rounded-full"
          onClick={toggle}
          aria-label="Toggle theme"
        >
          {dark ? <Sun className="size-5" /> : <Moon className="size-5" />}
        </Button>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Desktop sidebar */}
        <aside className="hidden w-72 shrink-0 border-r border-border/70 bg-sidebar/50 p-4 lg:block">
          {sidebar}
        </aside>

        {/* Main */}
        <main className="flex-1 overflow-y-auto">
          <motion.div
            layout
            transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            className={
              "mx-auto flex min-h-full w-full flex-col gap-8 px-5 " +
              (showHero
                ? "max-w-2xl justify-center py-16"
                : "max-w-4xl justify-start py-8")
            }
          >
            <AnimatePresence mode="popLayout">
              {showHero && (
                <motion.div
                  key="hero"
                  layout
                  initial={{ opacity: 0, y: -8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -16, height: 0, marginBottom: -32 }}
                  transition={{ duration: 0.4 }}
                  className="flex flex-col items-center gap-4 text-center"
                >
                  <span className="rounded-full border border-border bg-card/60 px-3 py-1 font-mono text-xs uppercase tracking-[0.15em] text-muted-foreground">
                    AI Video Assistant
                  </span>
                  <h1 className="font-display text-[2.75rem] leading-[1.05] tracking-tight text-foreground sm:text-[3.5rem]">
                    Understand any video
                    <br />
                    <span className="text-primary">in seconds.</span>
                  </h1>
                  <p className="max-w-md text-[1.05rem] leading-relaxed text-muted-foreground">
                    Drop a YouTube link or a file. Get a summary, action items,
                    key facts, and open questions — then chat with the
                    transcript.
                  </p>
                </motion.div>
              )}
            </AnimatePresence>

            {(state === "idle" || state === "error") && (
              <motion.div layout>
                <InputSection
                  state={state}
                  progress={progress}
                  error={error}
                  onProcess={handleProcess}
                  onRetry={handleRetry}
                />
              </motion.div>
            )}

            {state === "processing" && (
              <motion.div layout>
                <ProcessingState progress={progress} />
              </motion.div>
            )}

            {state === "done" && results && (
              <motion.div
                layout
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4 }}
                className="flex flex-col gap-6"
              >
                {/* Title + summary always visible */}
                <ResultsSection results={results} mode="summary" />

                {/* Tabs: Chat (default) | Details */}
                <Tabs
                  value={activeTab}
                  onValueChange={setActiveTab}
                  className="w-full"
                >
                  <TabsList className="rounded-full">
                    <TabsTrigger value="chat" className="gap-1.5 rounded-full">
                      <MessagesSquare className="size-4" />
                      Chat
                    </TabsTrigger>
                    <TabsTrigger value="details" className="gap-1.5 rounded-full">
                      <LayoutList className="size-4" />
                      Details
                    </TabsTrigger>
                  </TabsList>

                  <TabsContent value="chat">
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      transition={{ duration: 0.25 }}
                    >
                      <ChatPanel
                        messages={messages}
                        awaiting={awaiting}
                        onSend={handleSend}
                      />
                    </motion.div>
                  </TabsContent>

                  <TabsContent value="details">
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      transition={{ duration: 0.25 }}
                    >
                      <ResultsSection results={results} mode="details" />
                    </motion.div>
                  </TabsContent>
                </Tabs>
              </motion.div>
            )}
          </motion.div>
        </main>
      </div>
    </div>
  );
}
