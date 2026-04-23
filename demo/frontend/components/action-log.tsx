"use client";

import * as React from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type ActionLogProps = {
  lines: string[];
};

export function ActionLog({ lines }: ActionLogProps) {
  const viewportRef = React.useRef<HTMLDivElement | null>(null);

  // Auto-scroll to bottom whenever new lines arrive.
  React.useEffect(() => {
    const root = viewportRef.current;
    if (!root) return;
    const vp = root.querySelector<HTMLDivElement>(
      "[data-radix-scroll-area-viewport]",
    );
    if (vp) vp.scrollTop = vp.scrollHeight;
  }, [lines]);

  return (
    <Card className="flex flex-col h-full">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground tracking-wide uppercase flex items-center justify-between">
          <span>Action log</span>
          <span className="text-[10px] font-normal normal-case text-muted-foreground">
            {lines.length} {lines.length === 1 ? "line" : "lines"}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-1 pb-3">
        <ScrollArea
          ref={viewportRef}
          className="h-full min-h-[180px] rounded-md border bg-slate-950 text-slate-100"
        >
          <pre className="font-mono text-xs leading-5 p-3 whitespace-pre-wrap break-words">
            {lines.length === 0 ? (
              <span className="text-slate-500">
                {"// no actions yet — submit a prompt to begin"}
              </span>
            ) : (
              lines.map((line, i) => (
                <div key={i}>
                  <span className="text-slate-500 select-none">
                    {String(i + 1).padStart(3, "0")}{" "}
                  </span>
                  <span>{line}</span>
                </div>
              ))
            )}
          </pre>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
