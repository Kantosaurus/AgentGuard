import type { DemoEvent } from "./types";

export const API =
  process.env.NEXT_PUBLIC_CONTROL_PLANE ?? "http://localhost:8000";

export type HealthInfo = {
  ok: boolean;
  run_manager_ready: boolean;
  run_manager_error: string | null;
  threshold?: number;
  tick_sec?: number;
  run_timeout_sec?: number;
};

export async function getHealth(): Promise<HealthInfo | null> {
  try {
    const r = await fetch(`${API}/health`, { cache: "no-store" });
    if (!r.ok) return null;
    return (await r.json()) as HealthInfo;
  } catch {
    return null;
  }
}

/**
 * Thrown when the control-plane responds 409 Conflict — its single-tenant
 * mutex is held by another session. The body shape is
 * `{ "error": "busy", "retry_after": <seconds> }`.
 */
export class BusyError extends Error {
  retryAfter?: number;
  constructor(retryAfter?: number) {
    super("busy");
    this.name = "BusyError";
    this.retryAfter = retryAfter;
  }
}

export async function postRun(prompt: string): Promise<{ run_id: string }> {
  const r = await fetch(`${API}/run`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
  if (r.status === 409) {
    let retryAfter: number | undefined;
    try {
      const body = (await r.json()) as { retry_after?: number };
      if (typeof body?.retry_after === "number") {
        retryAfter = body.retry_after;
      }
    } catch {
      // body may be empty or malformed; fall back to undefined
    }
    throw new BusyError(retryAfter);
  }
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
