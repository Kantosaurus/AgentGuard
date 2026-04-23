import type { DemoEvent } from "./types";

export const API =
  process.env.NEXT_PUBLIC_CONTROL_PLANE ?? "http://localhost:8000";

export async function postRun(prompt: string): Promise<{ run_id: string }> {
  const r = await fetch(`${API}/run`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
  if (!r.ok) {
    throw new Error(`postRun failed: ${r.status} ${r.statusText}`);
  }
  return r.json();
}

/**
 * Subscribe to a run's SSE stream. Returns the EventSource so callers can
 * close() it on unmount / reset. Heartbeats are swallowed here.
 */
export function subscribeStream(
  runId: string,
  onEvent: (e: DemoEvent) => void,
  onError?: (err: Event) => void,
): EventSource {
  const es = new EventSource(`${API}/runs/${runId}/stream`);
  es.onmessage = (m) => {
    try {
      const parsed = JSON.parse(m.data) as DemoEvent;
      if (parsed.type === "heartbeat") return;
      onEvent(parsed);
    } catch {
      // swallow malformed lines
    }
  };
  if (onError) es.onerror = onError;
  return es;
}
