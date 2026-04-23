"use client";

import * as React from "react";
import { toast } from "sonner";

import { PromptBar } from "@/components/prompt-bar";
import { ScoreChart } from "@/components/score-chart";
import { StatusBadge } from "@/components/status-badge";
import { Telemetry } from "@/components/telemetry";
import { ActionLog } from "@/components/action-log";
import { Button } from "@/components/ui/button";
import { postRun, subscribeStream } from "@/lib/api";
import { FEATURE_INDEX } from "@/lib/feature-map";
import type {
  DemoEvent,
  ScorePoint,
  Status,
  TelemetryPoint,
} from "@/lib/types";

const THRESHOLD = 0.5;

type TerminalKind = "KILLED" | "COMPLETED";

export default function Page() {
  const [scores, setScores] = React.useState<ScorePoint[]>([]);
  const [telemetry, setTelemetry] = React.useState<TelemetryPoint[]>([]);
  const [logs, setLogs] = React.useState<string[]>([]);
  const [status, setStatus] = React.useState<Status>("MONITORING");
  const [currentScore, setCurrentScore] = React.useState(0);
  const [running, setRunning] = React.useState(false);
  const [activePrompt, setActivePrompt] = React.useState<string | null>(null);

  const esRef = React.useRef<EventSource | null>(null);

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
        toast.error("Agent killed", {
          description: `Anomaly score ${finalScore.toFixed(3)} crossed threshold. Worker terminated.`,
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
        setScores((prev) => [
          ...prev,
          { t: prev.length, score: evt.score },
        ]);
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
        esRef.current = subscribeStream(
          run_id,
          handleEvent,
          () => {
            // Don't surface transient errors — the server's terminal `status`
            // event normally arrives before the connection closes.
          },
        );
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        toast.error("Failed to start run", { description: msg });
        setRunning(false);
        setActivePrompt(null);
      }
    },
    [handleEvent, resetState],
  );

  // Cleanup any active stream on unmount.
  React.useEffect(() => closeStream, [closeStream]);

  return (
    <main className="mx-auto max-w-[1400px] p-4 md:p-6 space-y-4">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">AgentGuard</h1>
          <p className="text-sm text-muted-foreground">
            Live anomaly detection for LLM agents. Threshold {THRESHOLD}.
          </p>
        </div>
        {activePrompt && (
          <div className="text-sm text-muted-foreground max-w-[60ch] text-right">
            <span className="font-medium text-foreground">Active prompt:</span>{" "}
            <span className="font-mono">{activePrompt}</span>
          </div>
        )}
      </header>

      <section>
        <PromptBar disabled={running} onSubmit={onSubmit} />
      </section>

      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 space-y-4 flex flex-col">
          <ScoreChart data={scores} threshold={THRESHOLD} status={status} />
          <ActionLog lines={logs} />
          <div className="flex justify-end">
            <Button
              variant="ghost"
              size="sm"
              onClick={resetState}
              disabled={running && status === "MONITORING"}
            >
              Reset
            </Button>
          </div>
        </div>

        <aside className="space-y-4">
          <StatusBadge status={status} score={currentScore} />
          <div>
            <div className="text-xs font-medium text-muted-foreground tracking-wide uppercase mb-2 px-1">
              Telemetry
            </div>
            <Telemetry data={telemetry} />
          </div>
        </aside>
      </section>
    </main>
  );
}
