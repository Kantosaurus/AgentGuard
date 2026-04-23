import type { Config } from "tailwindcss";
import tailwindcssAnimate from "tailwindcss-animate";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    container: {
      center: true,
      padding: "1.5rem",
      screens: { "2xl": "1120px" },
    },
    extend: {
      fontFamily: {
        display: ["var(--font-gambarino)", "ui-serif", "Georgia", "serif"],
        sans: [
          "var(--font-switzer)",
          "ui-sans-serif",
          "system-ui",
          "sans-serif",
        ],
        mono: [
          "var(--font-supply-mono)",
          "ui-monospace",
          "SF Mono",
          "Menlo",
          "monospace",
        ],
      },
      colors: {
        // Editorial semantic tokens — drive everything new.
        paper: "var(--paper)",
        "paper-2": "var(--paper-2)",
        "paper-3": "var(--paper-3)",
        ink: "var(--ink)",
        "ink-muted": "var(--ink-muted)",
        "ink-faint": "var(--ink-faint)",
        rule: "var(--rule)",
        "rule-strong": "var(--rule-strong)",
        vermillion: "var(--vermillion)",
        "vermillion-soft": "var(--vermillion-soft)",

        // Shadcn primitives — kept for residual Button/Input/Toaster.
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius))",
        sm: "0",
      },
      fontSize: {
        // Editorial type scale — fixed rem for UI predictability;
        // hero title uses clamp() inline where fluid sizing matters.
        micro: ["0.688rem", { lineHeight: "1.4", letterSpacing: "0.06em" }],
        caption: ["0.75rem", { lineHeight: "1.55", letterSpacing: "0.005em" }],
        body: ["0.875rem", { lineHeight: "1.55" }],
        "body-lg": ["1rem", { lineHeight: "1.6" }],
        lead: ["1.125rem", { lineHeight: "1.55" }],
        "fig-title": [
          "0.75rem",
          { lineHeight: "1.3", letterSpacing: "0.12em" },
        ],
      },
      letterSpacing: {
        caps: "0.12em",
        micro: "0.06em",
      },
      keyframes: {
        "line-draw": {
          "0%": { transform: "scaleX(0)", transformOrigin: "left" },
          "100%": { transform: "scaleX(1)", transformOrigin: "left" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        "enter-up": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "caption-fade": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        "log-line-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        "hairline-sweep": {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(400%)" },
        },
      },
      animation: {
        // Editorial motion. Strong ease-out curves, tight durations.
        "line-draw": "line-draw 600ms cubic-bezier(0.22, 1, 0.36, 1)",
        "fade-in": "fade-in 220ms cubic-bezier(0.23, 1, 0.32, 1)",
        "enter-up": "enter-up 480ms cubic-bezier(0.23, 1, 0.32, 1) both",
        "caption-fade":
          "caption-fade 220ms cubic-bezier(0.23, 1, 0.32, 1) both",
        "log-line-in":
          "log-line-in 200ms cubic-bezier(0.23, 1, 0.32, 1) both",
        "hairline-sweep":
          "hairline-sweep 1600ms cubic-bezier(0.45, 0, 0.55, 1) infinite",
      },
      transitionTimingFunction: {
        "out-strong": "cubic-bezier(0.23, 1, 0.32, 1)",
        "out-expo": "cubic-bezier(0.16, 1, 0.3, 1)",
        "out-quart": "cubic-bezier(0.25, 1, 0.5, 1)",
      },
    },
  },
  plugins: [tailwindcssAnimate],
};

export default config;
