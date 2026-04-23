import type { Metadata } from "next";
import { ThemeProvider } from "next-themes";

import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgentGuard — live anomaly detection for LLM agents",
  description:
    "Dual-stream (OS + action) anomaly detector scoring a real containerized agent in real time. Research demo.",
};

// Fontshare CDN — three families via one request.
// Gambarino (display), Switzer (body), Supply Mono (numerics/log).
const FONTSHARE_HREF =
  "https://api.fontshare.com/v2/css?f[]=gambarino@400,500,700" +
  "&f[]=switzer@400,500,600,700" +
  "&f[]=supply-mono@400,500" +
  "&display=swap";

// CSS variables the rest of the app reads. Set on <html> so next-themes class
// switching doesn't flicker the font stack.
const FONT_VARS = `
  :root {
    --font-gambarino: "Gambarino", ui-serif, Georgia, "Times New Roman", serif;
    --font-switzer: "Switzer", ui-sans-serif, system-ui, sans-serif;
    --font-supply-mono: "Supply Mono", ui-monospace, "SF Mono", Menlo, monospace;
  }
`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://api.fontshare.com" />
        <link rel="preconnect" href="https://cdn.fontshare.com" crossOrigin="" />
        <link rel="stylesheet" href={FONTSHARE_HREF} />
        <style dangerouslySetInnerHTML={{ __html: FONT_VARS }} />
      </head>
      <body className="min-h-screen bg-paper text-ink antialiased">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange={false}
        >
          {children}
          <Toaster
            position="bottom-right"
            toastOptions={{
              classNames: {
                toast:
                  "!bg-paper-2 !text-ink !border !border-rule-strong !rounded-none !font-sans",
                title: "!font-medium",
                description: "!text-ink-muted",
              },
            }}
          />
        </ThemeProvider>
      </body>
    </html>
  );
}
