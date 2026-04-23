"use client";

import * as React from "react";

import { cn } from "@/lib/utils";
import type { Status } from "@/lib/types";

type StatusBadgeProps = {
  status: Status;
  score: number;
};

type Cfg = { label: string; glyph: string; tone: "ink" | "vermillion" };

const CFG: Record<Status, Cfg> = {
  MONITORING: { label: "Monitoring", glyph: "—", tone: "ink" },
  SUSPICIOUS: { label: "Suspicious", glyph: "·", tone: "vermillion" },
  KILLED: { label: "Killed", glyph: "✕", tone: "vermillion" },
  COMPLETED: { label: "Completed", glyph: "✓", tone: "ink" },
};

export function StatusBadge({ status, score }: StatusBadgeProps) {
  const cfg = CFG[status];
  const vermillion = cfg.tone === "vermillion";

  return (
    <section aria-label="Current status" className="flex flex-col gap-3">
      <SectionLabel>Status</SectionLabel>

      <div
        key={status}
        className="flex items-baseline gap-2 motion-safe:animate-caption-fade"
      >
        <span
          aria-hidden
          className={cn(
            "font-mono text-lg leading-none w-4 inline-block",
            "transition-colors duration-200 ease-out-strong",
            vermillion ? "text-vermillion" : "text-ink-muted",
          )}
        >
          {cfg.glyph}
        </span>
        <span
          className={cn(
            "font-display text-[1.75rem] leading-none tracking-tight",
            "transition-colors duration-200 ease-out-strong",
            vermillion ? "text-vermillion" : "text-ink",
          )}
        >
          {cfg.label}
        </span>
      </div>

      <dl className="flex items-baseline justify-between pt-1">
        <dt className="text-micro uppercase tracking-caps text-ink-faint">
          Score
        </dt>
        <dd className="tabular font-mono text-body-lg text-ink">
          {score.toFixed(3)}
        </dd>
      </dl>
    </section>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-fig-title uppercase tracking-caps text-ink-muted font-sans font-medium">
        {children}
      </span>
      <span aria-hidden className="flex-1 rule" />
    </div>
  );
}
