"use client";

import * as React from "react";
import { toast } from "sonner";

import { ActionLog } from "@/components/action-log";
import { PromptBar } from "@/components/prompt-bar";
import { ScoreChart } from "@/components/score-chart";
import { StatusBadge } from "@/components/status-badge";
import { Telemetry } from "@/components/telemetry";
import { ThemeToggle } from "@/components/theme-toggle";
import { getHealth, postRun, subscribeStream } from "@/lib/api";
import { FEATURE_INDEX } from "@/lib/feature-map";
import type {
  DemoEvent,
  ScorePoint,
  Status,
  TelemetryPoint,
} from "@/lib/types";

// Fallback if /health is unreachable on first paint. Control-plane owns the
// canonical value; the effect below replaces this with the live value.
const DEFAULT_THRESHOLD = 0.45;

type TerminalKind = "KILLED" | "COMPLETED";

export default function Page() {
  const [scores, setScores] = React.useState<ScorePoint[]>([]);
  const [telemetry, setTelemetry] = React.useState<TelemetryPoint[]>([]);
  const [logs, setLogs] = React.useState<string[]>([]);
  const [status, setStatus] = React.useState<Status>("MONITORING");
  const [currentScore, setCurrentScore] = React.useState(0);
  const [running, setRunning] = React.useState(false);
  const [activePrompt, setActivePrompt] = React.useState<string | null>(null);
  const [threshold, setThreshold] = React.useState(DEFAULT_THRESHOLD);

  const esRef = React.useRef<EventSource | null>(null);

  // Pull the live threshold from the control plane so graph + analysis match
  // whatever AGENTGUARD_THRESHOLD the backend was started with.
  React.useEffect(() => {
    let cancelled = false;
    getHealth().then((h) => {
      if (!cancelled && h && typeof h.threshold === "number") {
        setThreshold(h.threshold);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const closeStream = React.useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  const resetState = React.useCallback(() => {
    closeStream();
    setScores([]);
    setTelemetry([]);
    setLogs([]);
    setStatus("MONITORING");
    setCurrentScore(0);
    setRunning(false);
    setActivePrompt(null);
  }, [closeStream]);

  const announceTerminal = React.useCallback(
    (kind: TerminalKind, finalScore: number) => {
      if (kind === "KILLED") {
        toast.error("Worker terminated", {
          description: `Score ${finalScore.toFixed(3)} crossed threshold ${threshold}.`,
        });
      } else {
        toast.success("Run completed", {
          description: `Final score ${finalScore.toFixed(3)}. Agent finished normally.`,
        });
      }
    },
    [],
  );

  const handleEvent = React.useCallback(
    (evt: DemoEvent) => {
      if (evt.type === "tick") {
        setScores((prev) => [...prev, { t: prev.length, score: evt.score }]);
        setTelemetry((prev) => {
          const v = evt.stream1_last ?? [];
          return [
            ...prev,
            {
              t: prev.length,
              cpu: Number(v[FEATURE_INDEX.cpu] ?? 0),
              mem: Number(v[FEATURE_INDEX.mem] ?? 0),
              net: Number(v[FEATURE_INDEX.net] ?? 0),
            },
          ];
        });
        setStatus(evt.status);
        setCurrentScore(evt.score);
      } else if (evt.type === "log") {
        setLogs((prev) => [...prev, evt.line]);
      } else if (evt.type === "status") {
        setStatus(evt.status);
        setCurrentScore(evt.score);
        setRunning(false);
        closeStream();
        if (evt.status === "KILLED" || evt.status === "COMPLETED") {
          announceTerminal(evt.status, evt.score);
        }
      }
    },
    [announceTerminal, closeStream],
  );

  const onSubmit = React.useCallback(
    async (prompt: string) => {
      resetState();
      setRunning(true);
      setActivePrompt(prompt);
      try {
        const { run_id } = await postRun(prompt);
        esRef.current = subscribeStream(run_id, handleEvent, () => {
          /* transient; terminal status event is authoritative. */
        });
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        toast.error("Failed to start run", { description: msg });
        setRunning(false);
        setActivePrompt(null);
      }
    },
    [handleEvent, resetState],
  );

  React.useEffect(() => closeStream, [closeStream]);

  return (
    <main
      className={[
        "mx-auto max-w-[1120px] px-6 md:px-10",
        "pt-10 md:pt-14 pb-16",
        "flex flex-col gap-10 md:gap-12",
      ].join(" ")}
    >
      {/* ───────────────────── Masthead ───────────────────── */}
      {/* Whole masthead animates as one block. Inner type composition is
          already a hierarchy; adding per-element stagger on top compounded
          transforms and felt baroque. */}
      <header
        className="flex flex-col gap-5 motion-safe:animate-enter-up"
        style={{ animationDelay: "0ms" }}
      >
        <div className="flex items-start justify-between gap-6">
          <div className="flex flex-col gap-3 max-w-[58ch]">
            <span className="text-micro uppercase tracking-caps text-ink-muted font-sans font-medium">
              Dual-stream anomaly detection · Live demo
            </span>
            <h1
              className="font-display text-ink tracking-tight leading-[0.95]"
              style={{ fontSize: "clamp(2.75rem, 6vw, 4.5rem)" }}
            >
              AgentGuard
            </h1>
            <p className="text-body-lg font-sans text-ink-muted leading-[1.55] max-w-[52ch]">
              A trained Mamba + Transformer with cross-attention fusion scores
              OS telemetry and LLM action logs every five seconds. Prompts that
              look adversarial get their worker container killed; benign
              prompts run to completion.
            </p>
          </div>
          <div className="pt-2 shrink-0">
            <ThemeToggle />
          </div>
        </div>
        <div className="relative">
          <div aria-hidden className="rule-strong" />
          {/* Indeterminate running hairline — only visible between submit and
              the first tick, so the page acknowledges the request without
              dashboard chrome. Muted ink keeps it below the signal of the
              data itself. */}
          {running && scores.length === 0 && (
            <div
              aria-hidden
              className="absolute inset-x-0 top-0 overflow-hidden h-px"
            >
              <div className="h-full w-1/4 bg-ink-muted motion-safe:animate-hairline-sweep" />
            </div>
          )}
        </div>
      </header>

      {/* ───────────────────── Prompt row ───────────────────── */}
      <section
        aria-label="Submit a prompt"
        className="flex flex-col gap-4 motion-safe:animate-enter-up"
        style={{ animationDelay: "80ms" }}
      >
        <PromptBar disabled={running} onSubmit={onSubmit} />
        {activePrompt && (
          <p
            className="font-mono text-[12px] italic text-ink-faint pl-0.5 motion-safe:animate-fade-in"
            aria-live="polite"
          >
            <span className="not-italic text-ink-muted">Now running · </span>
            {activePrompt}
          </p>
        )}
      </section>

      {/* ───────────────────── Figure 1 + apparatus ───────────────────── */}
      <section
        aria-label="Live trace"
        className="grid grid-cols-1 lg:grid-cols-12 gap-10 lg:gap-12 motion-safe:animate-enter-up"
        style={{ animationDelay: "140ms" }}
      >
        <div className="lg:col-span-7">
          <ScoreChart
            data={scores}
            threshold={threshold}
            status={status}
            activePrompt={activePrompt}
            onReset={resetState}
            resetDisabled={running && status === "MONITORING"}
          />
        </div>

        <aside className="lg:col-span-5 flex flex-col gap-8">
          <StatusBadge status={status} score={currentScore} />
          <Telemetry data={telemetry} />
        </aside>
      </section>

      {/* ───────────────────── Figure 2: action log ───────────────────── */}
      <section
        aria-label="Action log"
        className="motion-safe:animate-enter-up"
        style={{ animationDelay: "200ms" }}
      >
        <ActionLog lines={logs} />
      </section>

      {/* ───────────────────── Footer ───────────────────── */}
      <footer
        className="flex flex-col gap-3 pt-2 motion-safe:animate-enter-up"
        style={{ animationDelay: "260ms" }}
      >
        <div aria-hidden className="rule" />
        <p className="font-sans text-caption text-ink-muted leading-[1.7] max-w-[85ch]">
          <span className="text-ink">Model</span>
          <span className="text-ink-faint"> · </span>
          Mamba + Transformer with bidirectional cross-attention fusion.
          <Sep />
          Threshold{" "}
          <span className="font-mono tabular">{threshold.toFixed(2)}</span>.
          <Sep />
          Debounce <span className="font-mono tabular">2</span> ticks.
          <Sep />
          Window <span className="font-mono tabular">30</span>s.
          <Sep />
          Trained on a dual-stream corpus of{" "}
          <span className="font-mono tabular">20</span> agents
          (<span className="font-mono tabular">15</span> attacked,{" "}
          <span className="font-mono tabular">5</span> control).
        </p>
      </footer>
    </main>
  );
}

function Sep() {
  return <span className="text-ink-faint mx-1">·</span>;
}
