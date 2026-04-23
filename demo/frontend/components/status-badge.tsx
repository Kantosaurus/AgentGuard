"use client";

import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { Status } from "@/lib/types";

type StatusBadgeProps = {
  status: Status;
  score: number;
};

const STYLE: Record<Status, { label: string; className: string; dot: string }> =
  {
    MONITORING: {
      label: "Monitoring",
      className: "border-slate-300 text-slate-700 bg-slate-50",
      dot: "bg-slate-400",
    },
    SUSPICIOUS: {
      label: "Suspicious",
      className: "border-amber-500 text-amber-700 bg-amber-50",
      dot: "bg-amber-500 animate-pulse",
    },
    KILLED: {
      label: "Killed",
      className: "border-red-600 text-red-700 bg-red-50",
      dot: "bg-red-600",
    },
    COMPLETED: {
      label: "Completed",
      className: "border-green-600 text-green-700 bg-green-50",
      dot: "bg-green-600",
    },
  };

export function StatusBadge({ status, score }: StatusBadgeProps) {
  const s = STYLE[status];

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground tracking-wide uppercase">
          Status
        </CardTitle>
      </CardHeader>
      <CardContent className="flex items-center justify-between gap-3">
        <Badge
          variant="outline"
          className={cn(
            "flex items-center gap-2 px-3 py-1.5 text-sm font-semibold",
            s.className,
          )}
        >
          <span className={cn("h-2 w-2 rounded-full", s.dot)} />
          {s.label}
        </Badge>
        <div className="text-right">
          <div className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">
            Score
          </div>
          <div className="font-mono text-lg tabular-nums">
            {score.toFixed(3)}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
