import type { Metadata } from "next";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgentGuard — Live demo",
  description:
    "Real-time monitoring of LLM agents with AgentGuard’s anomaly detector.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-slate-50 antialiased">
        {children}
        <Toaster richColors position="top-right" />
      </body>
    </html>
  );
}
