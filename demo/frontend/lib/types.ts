export type Status = "MONITORING" | "SUSPICIOUS" | "KILLED" | "COMPLETED";

export type TickEvent = {
  type: "tick";
  score: number;
  status: Status;
  stream1_last: number[]; // length 32; see lib/feature-map.ts for index layout
};

export type LogEvent = {
  type: "log";
  line: string;
};

export type StatusEvent = {
  type: "status";
  status: Status;
  score: number;
};

export type HeartbeatEvent = {
  type: "heartbeat";
};

export type DemoEvent = TickEvent | LogEvent | StatusEvent | HeartbeatEvent;

export type ScorePoint = {
  t: number;
  score: number;
};

export type TelemetryPoint = {
  t: number;
  cpu: number;
  mem: number;
  net: number;
};
