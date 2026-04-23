import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// Teach tailwind-merge about our custom editorial type-scale tokens so it
// stops classifying e.g. `text-body` as a color and dropping it when paired
// with `text-ink-muted`. See tailwind.config.ts::fontSize.
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [
        "text-micro",
        "text-caption",
        "text-body",
        "text-body-lg",
        "text-lead",
        "text-fig-title",
      ],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
