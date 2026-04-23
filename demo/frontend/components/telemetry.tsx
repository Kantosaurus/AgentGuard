"use client";

/**
 * Telemetry sparklines.
 *
 * Index map (verified against `data/preprocessing.py::flatten_telemetry` —
 * see `lib/feature-map.ts` for the full 32-dim layout):
 *   stream1_last[0]  = cpu.mean                → CPU card
 *   stream1_last[4]  = memory.mean             → Memory card
 *   stream1_last[12] = network_connections.mean → Network card
 *
 * If `data/preprocessing.py::STAT_GROUPS` changes order, update
 * `lib/feature-map.ts` — this component reads from that map.
 */

import * as React from "react";
import {
  Line,
  LineChart,
  ResponsiveContainer,
  YAxis,
} from "recharts";

import { Card, CardContent } from "@/components/ui/card";
import type { TelemetryPoint } from "@/lib/types";

type TelemetryProps = {
  data: TelemetryPoint[];
};

type Metric = {
  key: "cpu" | "mem" | "net";
  label: string;
  unit: string;
  color: string;
};

const METRICS: Metric[] = [
  { key: "cpu", label: "CPU", unit: "%", color: "#2563eb" },
  { key: "mem", label: "Memory", unit: "%", color: "#7c3aed" },
  { key: "net", label: "Network", unit: "conn", color: "#0891b2" },
];

function formatValue(v: number | undefined, unit: string) {
  if (v == null || Number.isNaN(v)) return "—";
  if (unit === "conn") return v.toFixed(0);
  return v.toFixed(1);
}

export function Telemetry({ data }: TelemetryProps) {
  return (
    <div className="grid grid-cols-3 gap-2">
      {METRICS.map((m) => {
        const series = data.map((p, i) => ({ i, v: p[m.key] }));
        const current = series.at(-1)?.v;
        return (
          <Card key={m.key} className="overflow-hidden">
            <CardContent className="p-3">
              <div className="flex items-baseline justify-between">
                <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                  {m.label}
                </span>
                <span className="text-[10px] text-muted-foreground">
                  {m.unit}
                </span>
              </div>
              <div className="font-mono text-base font-semibold tabular-nums">
                {formatValue(current, m.unit)}
              </div>
              <div className="h-10 w-full mt-1">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={series}
                    margin={{ top: 2, right: 0, bottom: 0, left: 0 }}
                  >
                    <YAxis hide domain={["auto", "auto"]} />
                    <Line
                      type="monotone"
                      dataKey="v"
                      stroke={m.color}
                      strokeWidth={1.5}
                      dot={false}
                      isAnimationActive={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
