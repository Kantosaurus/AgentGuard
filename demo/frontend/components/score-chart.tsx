"use client";

import * as React from "react";
import {
  Area,
  ComposedChart,
  Line,
  ReferenceLine,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { cn } from "@/lib/utils";
import type { ScorePoint, Status } from "@/lib/types";

type ScoreChartProps = {
  data: ScorePoint[];
  threshold: number;
  status: Status;
  activePrompt: string | null;
  onReset: () => void;
  resetDisabled: boolean;
};

export function ScoreChart({
  data,
  threshold,
  status,
  activePrompt,
  onReset,
  resetDisabled,
}: ScoreChartProps) {
  const { rows, firstCrossTick, peak } = React.useMemo(() => {
    let firstCross = -1;
    let peakVal = 0;
    const mapped = data.map((p, i) => {
      if (p.score > threshold && firstCross < 0) firstCross = i;
      if (p.score > peakVal) peakVal = p.score;
      return {
        tick: i,
        score: p.score,
        // Split for two-color rendering. Overlap at the boundary tick so the
        // line is visually continuous across the crossing.
        below: p.score <= threshold ? p.score : null,
        above: p.score >= threshold ? p.score : null,
        danger: p.score > threshold ? p.score : threshold,
      };
    });
    return { rows: mapped, firstCrossTick: firstCross, peak: peakVal };
  }, [data, threshold]);

  const lastTick = rows.length;
  const lastScore = rows.at(-1)?.score ?? 0;
  const caption = captionFor({
    status,
    activePrompt,
    lastTick,
    lastScore,
    peak,
    threshold,
    firstCrossTick,
  });

  return (
    <figure className="flex flex-col gap-3">
      <header className="flex items-center gap-3">
        <span className="text-fig-title uppercase tracking-caps text-ink-muted font-sans font-medium">
          Fig. 1 — Anomaly score
        </span>
        <span aria-hidden className="flex-1 rule" />
        <span className="text-micro uppercase tracking-caps text-ink-faint tabular font-mono">
          {lastTick > 0
            ? `${lastTick} tick${lastTick === 1 ? "" : "s"}`
            : "idle"}
        </span>
      </header>

      <div className="relative h-[320px] w-full border border-rule bg-paper-2">
        {/* Axis guides subtle; the data does the talking. */}
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={rows}
            margin={{ top: 18, right: 24, bottom: 20, left: 8 }}
          >
            <defs>
              <linearGradient id="agTriggerFill" x1="0" y1="0" x2="0" y2="1">
                <stop
                  offset="0%"
                  stopColor="var(--vermillion)"
                  stopOpacity={0.22}
                />
                <stop
                  offset="100%"
                  stopColor="var(--vermillion)"
                  stopOpacity={0.04}
                />
              </linearGradient>
            </defs>

            <XAxis
              dataKey="tick"
              tick={{ fontSize: 10.5 }}
              stroke="var(--rule-strong)"
              tickLine={{ stroke: "var(--rule)" }}
              domain={[0, (dataMax: number) => Math.max(12, dataMax)]}
              type="number"
              label={{
                value: "tick",
                position: "insideBottomRight",
                offset: -2,
                fontSize: 10,
                fill: "var(--ink-faint)",
                fontFamily: "var(--font-supply-mono)",
              }}
            />
            <YAxis
              domain={[0, 1]}
              ticks={[0, 0.25, 0.5, 0.75, 1]}
              tick={{ fontSize: 10.5 }}
              stroke="var(--rule-strong)"
              tickLine={{ stroke: "var(--rule)" }}
              width={32}
            />

            <Tooltip
              cursor={{
                stroke: "var(--rule-strong)",
                strokeDasharray: "2 3",
                strokeWidth: 1,
              }}
              contentStyle={{
                background: "var(--paper)",
                border: "1px solid var(--rule-strong)",
                borderRadius: 0,
                fontSize: 11,
                padding: "6px 10px",
                fontFamily: "var(--font-supply-mono)",
                color: "var(--ink)",
              }}
              itemStyle={{ color: "var(--ink)" }}
              labelStyle={{ color: "var(--ink-faint)" }}
              formatter={(value) => {
                const n =
                  typeof value === "number" ? value : Number(value ?? NaN);
                return Number.isFinite(n) ? n.toFixed(3) : "—";
              }}
              labelFormatter={(tick) => `tick ${tick}`}
            />

            {/* Red fill above threshold — only present when exceeded. */}
            <Area
              type="monotone"
              dataKey="danger"
              baseValue={threshold}
              stroke="none"
              fill="url(#agTriggerFill)"
              isAnimationActive={false}
              connectNulls={false}
            />

            <ReferenceLine
              y={threshold}
              stroke="var(--rule-strong)"
              strokeDasharray="3 4"
              strokeWidth={1}
              label={{
                value: `threshold ${threshold}`,
                position: "insideTopRight",
                fontSize: 10,
                fill: "var(--ink-faint)",
                fontFamily: "var(--font-supply-mono)",
              }}
            />

            {/* Below-threshold segments in ink. */}
            <Line
              type="monotone"
              dataKey="below"
              stroke="var(--ink)"
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
              connectNulls={false}
            />
            {/* Above-threshold segments in vermillion. */}
            <Line
              type="monotone"
              dataKey="above"
              stroke="var(--vermillion)"
              strokeWidth={1.75}
              dot={false}
              isAnimationActive={false}
              connectNulls={false}
            />

            {/* Crossing annotation — small vermillion dot + vertical tick. */}
            {firstCrossTick >= 0 && (
              <>
                <ReferenceLine
                  x={firstCrossTick}
                  stroke="var(--vermillion)"
                  strokeDasharray="2 3"
                  strokeWidth={1}
                />
                <ReferenceDot
                  x={firstCrossTick}
                  y={rows[firstCrossTick]?.score ?? threshold}
                  r={3}
                  fill="var(--vermillion)"
                  stroke="var(--paper)"
                  strokeWidth={1.5}
                  isFront
                  label={{
                    value: `t=${firstCrossTick}`,
                    position: "top",
                    fontSize: 10,
                    fill: "var(--vermillion)",
                    fontFamily: "var(--font-supply-mono)",
                    offset: 8,
                  }}
                />
              </>
            )}

            {/* Terminal state dot on the last point. */}
            {(status === "KILLED" || status === "COMPLETED") &&
              lastTick > 0 && (
                <ReferenceDot
                  x={lastTick - 1}
                  y={lastScore}
                  r={3.5}
                  fill={
                    status === "KILLED"
                      ? "var(--vermillion)"
                      : "var(--ink)"
                  }
                  stroke="var(--paper)"
                  strokeWidth={1.5}
                  isFront
                />
              )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <figcaption className="flex items-start justify-between gap-4">
        <p
          key={caption}
          className={cn(
            "font-display italic text-body text-ink-muted max-w-[60ch]",
            "tracking-tight motion-safe:animate-caption-fade",
          )}
        >
          {caption}
        </p>
        <button
          type="button"
          onClick={onReset}
          disabled={resetDisabled}
          className={cn(
            "shrink-0 text-micro uppercase tracking-caps font-sans font-medium",
            "text-ink-faint hover:text-ink underline underline-offset-[6px]",
            "decoration-rule hover:decoration-ink decoration-[1px]",
            "transition-colors duration-150 ease-out-strong",
            "active:scale-[0.97]",
            "disabled:opacity-30 disabled:pointer-events-none disabled:active:scale-100",
          )}
        >
          Reset
        </button>
      </figcaption>
    </figure>
  );
}

type CaptionArgs = {
  status: Status;
  activePrompt: string | null;
  lastTick: number;
  lastScore: number;
  peak: number;
  threshold: number;
  firstCrossTick: number;
};

function captionFor({
  status,
  activePrompt,
  lastTick,
  lastScore,
  peak,
  threshold,
  firstCrossTick,
}: CaptionArgs): string {
  if (!activePrompt && lastTick === 0) {
    return "Awaiting prompt. Score updates every five seconds over the 30-second telemetry window.";
  }
  if (status === "KILLED") {
    return `Worker terminated at tick ${lastTick}, final score ${lastScore.toFixed(3)}.`;
  }
  if (status === "COMPLETED") {
    return `Run completed in ${lastTick} ticks, peak score ${peak.toFixed(3)}.`;
  }
  if (firstCrossTick >= 0 && status === "SUSPICIOUS") {
    return `Threshold crossed at t=${firstCrossTick}. Kill fires if the score sustains above ${threshold} for two consecutive ticks.`;
  }
  if (activePrompt) {
    return `Live trace of “${activePrompt}” — threshold ${threshold}, ink below, vermillion above.`;
  }
  return "Awaiting prompt.";
}
