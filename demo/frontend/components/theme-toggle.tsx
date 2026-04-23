"use client";

import * as React from "react";
import { useTheme } from "next-themes";
import { Monitor, Moon, Sun } from "lucide-react";

import { cn } from "@/lib/utils";

type Option = { value: "light" | "system" | "dark"; label: string; Icon: typeof Sun };

const OPTIONS: Option[] = [
  { value: "light", label: "Light", Icon: Sun },
  { value: "system", label: "System", Icon: Monitor },
  { value: "dark", label: "Dark", Icon: Moon },
];

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => setMounted(true), []);

  return (
    <div
      role="radiogroup"
      aria-label="Theme"
      className="inline-flex items-center gap-0 font-sans text-[11px] uppercase tracking-caps"
    >
      {OPTIONS.map(({ value, label, Icon }, i) => {
        const active = mounted && theme === value;
        return (
          <React.Fragment key={value}>
            {i > 0 && (
              <span
                aria-hidden
                className="select-none px-1.5 text-ink-faint"
              >
                ·
              </span>
            )}
            <button
              type="button"
              role="radio"
              aria-checked={active}
              aria-label={label}
              onClick={() => setTheme(value)}
              className={cn(
                "inline-flex items-center gap-1.5 py-1 transition-colors",
                "focus-visible:outline-none focus-visible:text-ink",
                active
                  ? "text-ink font-medium"
                  : "text-ink-faint hover:text-ink-muted",
              )}
            >
              <Icon
                aria-hidden
                strokeWidth={1.5}
                className="h-3.5 w-3.5"
              />
              <span className="hidden sm:inline">{label}</span>
            </button>
          </React.Fragment>
        );
      })}
    </div>
  );
}
