"use client";

import * as React from "react";
import {
  Area,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ScorePoint, Status } from "@/lib/types";

type ScoreChartProps = {
  data: ScorePoint[];
  threshold: number;
  status: Status;
};

const LINE_COLOR: Record<Status, string> = {
  MONITORING: "#475569", // slate-600
  SUSPICIOUS: "#f59e0b", // amber-500
  KILLED: "#dc2626", // red-600
  COMPLETED: "#16a34a", // green-600
};

export function ScoreChart({ data, threshold, status }: ScoreChartProps) {
  const color = LINE_COLOR[status];

  // Map to indexed ticks (keeps the x-axis monotonic regardless of wall time).
  const rows = data.map((p, i) => ({
    tick: i,
    score: p.score,
    overflow: p.score > threshold ? p.score : threshold,
  }));

  return (
    <Card className="h-full flex flex-col">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground tracking-wide uppercase">
          Anomaly score
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-1 pb-4">
        <div className="h-full min-h-[260px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={rows}
              margin={{ top: 8, right: 16, bottom: 8, left: 0 }}
            >
              <defs>
                <linearGradient id="dangerFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#ef4444" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#ef4444" stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="tick"
                tick={{ fontSize: 11, fill: "#94a3b8" }}
                stroke="#cbd5e1"
                label={{
                  value: "tick",
                  position: "insideBottom",
                  offset: -2,
                  fontSize: 11,
                  fill: "#94a3b8",
                }}
              />
              <YAxis
                domain={[0, 1]}
                ticks={[0, 0.25, 0.5, 0.75, 1]}
                tick={{ fontSize: 11, fill: "#94a3b8" }}
                stroke="#cbd5e1"
                width={34}
              />
              <Tooltip
                formatter={(value: number) => value.toFixed(3)}
                contentStyle={{ fontSize: 12 }}
                labelFormatter={(tick) => `tick ${tick}`}
              />
              {/* Red area that only shows above the threshold. */}
              <Area
                type="monotone"
                dataKey={(row: (typeof rows)[number]) =>
                  row.score > threshold ? row.score : null
                }
                baseValue={threshold}
                stroke="none"
                fill="url(#dangerFill)"
                isAnimationActive={false}
                connectNulls={false}
              />
              <ReferenceLine
                y={threshold}
                stroke="#dc2626"
                strokeDasharray="4 4"
                strokeWidth={1.5}
                label={{
                  value: `threshold ${threshold}`,
                  position: "insideTopRight",
                  fontSize: 10,
                  fill: "#dc2626",
                }}
              />
              <Line
                type="monotone"
                dataKey="score"
                stroke={color}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
