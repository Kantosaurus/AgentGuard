"use client";

/**
 * Stream-1 telemetry panel. Not a card grid — editorial label/value rows
 * with small trend sparklines. Index map verified in lib/feature-map.ts.
 */

import * as React from "react";
import { Line, LineChart, ResponsiveContainer, YAxis } from "recharts";

import { cn } from "@/lib/utils";
import type { TelemetryPoint } from "@/lib/types";

type TelemetryProps = {
  data: TelemetryPoint[];
};

type Metric = {
  key: "cpu" | "mem" | "net";
  label: string;
  unit: string;
};

const METRICS: Metric[] = [
  { key: "cpu", label: "CPU", unit: "%" },
  { key: "mem", label: "Memory", unit: "%" },
  { key: "net", label: "Network", unit: "conn." },
];

function formatValue(v: number | undefined, unit: string) {
  if (v == null || Number.isNaN(v)) return "—";
  if (unit === "conn.") return v.toFixed(0);
  return v.toFixed(1);
}

export function Telemetry({ data }: TelemetryProps) {
  return (
    <section aria-label="Stream 1 telemetry" className="flex flex-col gap-3">
      <SectionLabel>Stream 1 · OS telemetry</SectionLabel>

      <div className="flex flex-col">
        {METRICS.map((m, i) => {
          const series = data.map((p, idx) => ({ i: idx, v: p[m.key] }));
          const current = series.at(-1)?.v;
          const idle = series.length === 0 || current == null;

          return (
            <div
              key={m.key}
              className={cn(
                "grid grid-cols-[1fr_auto_70px] items-baseline gap-4 py-3",
                i > 0 && "border-t border-rule",
              )}
            >
              <div className="flex items-baseline gap-1.5">
                <span className="font-sans text-body text-ink">
                  {m.label}
                </span>
                <span className="text-micro uppercase tracking-micro text-ink-faint">
                  {m.unit}
                </span>
              </div>
              <span
                className={cn(
                  "tabular font-mono text-body-lg leading-none",
                  idle ? "text-ink-faint" : "text-ink",
                )}
              >
                {formatValue(current, m.unit)}
              </span>
              <div className="h-5 w-full" aria-hidden>
                {series.length >= 2 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart
                      data={series}
                      margin={{ top: 2, right: 0, bottom: 2, left: 0 }}
                    >
                      <YAxis hide domain={["auto", "auto"]} />
                      <Line
                        type="monotone"
                        dataKey="v"
                        stroke="var(--ink-muted)"
                        strokeWidth={1}
                        dot={false}
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full w-full border-b border-dashed border-rule" />
                )}
              </div>
            </div>
          );
        })}
      </div>
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
