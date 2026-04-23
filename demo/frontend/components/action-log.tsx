"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

type ActionLogProps = {
  lines: string[];
};

export function ActionLog({ lines }: ActionLogProps) {
  const viewportRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [lines]);

  const count = lines.length;

  return (
    <figure className="flex flex-col gap-3">
      <header className="flex items-center gap-3">
        <span className="text-fig-title uppercase tracking-caps text-ink-muted font-sans font-medium">
          Fig. 2 — Action log
        </span>
        <span aria-hidden className="flex-1 rule" />
        <span className="text-micro uppercase tracking-caps text-ink-faint tabular font-mono">
          {count} {count === 1 ? "event" : "events"}
        </span>
      </header>

      <div
        ref={viewportRef}
        className={cn(
          "relative max-h-[280px] min-h-[180px] overflow-y-auto",
          "border border-rule bg-paper-2",
        )}
      >
        <pre
          className={cn(
            "font-mono text-[12px] leading-[1.85] text-ink",
            "px-5 py-4 whitespace-pre-wrap break-words",
          )}
        >
          {count === 0 ? (
            <span className="text-ink-faint">
              <span className="text-ink-faint">//</span>
              {"  "}awaiting events — submit a prompt to begin
            </span>
          ) : (
            lines.map((line, i) => {
              const highlighted = HIGHLIGHT.test(line);
              return (
                <div
                  key={i}
                  className={cn(
                    "grid grid-cols-[2.5rem_1fr] gap-3",
                    "motion-safe:animate-log-line-in",
                    highlighted && "text-vermillion",
                  )}
                >
                  <span className="text-ink-faint select-none text-right tabular">
                    {String(i + 1).padStart(3, "0")}
                  </span>
                  <span>{line}</span>
                </div>
              );
            })
          )}
        </pre>
      </div>
    </figure>
  );
}

// Soft highlight: mark lines that look like they matter — external POSTs,
// file reads to sensitive paths, /tmp persistence. Intentionally coarse;
// the server controls the exact copy.
const HIGHLIGHT =
  /(exfil|passwd|shadow|\/tmp\/|authorized_keys|cron|POST\s+https?:\/\/)/i;
