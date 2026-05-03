"use client";

import { cn } from "@/lib/utils";

type BusyBannerProps = {
  visible: boolean;
  retryAfterSec?: number;
};

export function BusyBanner({ visible, retryAfterSec }: BusyBannerProps) {
  if (!visible) return null;
  return (
    <div
      role="status"
      className={cn(
        "border border-rule-strong bg-paper-2 px-3 py-2",
        "font-mono text-micro text-ink-muted",
      )}
    >
      Demo in progress on another session
      {retryAfterSec ? `; try again in ~${retryAfterSec}s` : ""}.
    </div>
  );
}
