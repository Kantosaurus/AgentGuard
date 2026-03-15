# AgentGuard Data Collection

## Overview
Standalone data collection modules for the AgentGuard dual-stream anomaly detection system.
Collects both system telemetry (Stream 1) and agent action sequences (Stream 2) from an OpenClaw instance.

## Components

| File | Purpose |
|------|---------|
| `telemetry_collector.py` | Stream 1: CPU, memory, processes, I/O, network, syscalls (every 5s) |
| `action_collector.py` | Stream 2: Tool calls, LLM usage, tokens, action transitions (every 10s) |
| `daily_report.py` | Generates daily summary report (JSON + Telegram-formatted text) |
| `run_collectors.sh` | Start/stop/status for both collectors as background daemons |

## Quick Start
```bash
# Start both collectors
./run_collectors.sh start

# Check status
./run_collectors.sh status

# Generate today's report
python3 daily_report.py

# Generate report for specific date
python3 daily_report.py 2026-03-15
```

## Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTGUARD_DATA_DIR` | `/var/log/agentguard` | Where data files are stored |
| `AGENTGUARD_TELEMETRY_INTERVAL` | `5` | Telemetry collection interval (seconds) |
| `AGENTGUARD_ACTION_INTERVAL` | `10` | Action collection interval (seconds) |
| `OPENCLAW_STATE_DIR` | `/root/.openclaw/state` | OpenClaw state directory for transcripts |

## Data Format
All data is stored as JSONL (one JSON object per line) in daily files:
- `telemetry/YYYY-MM-DD.jsonl` — Stream 1 samples
- `actions/YYYY-MM-DD.jsonl` — Stream 2 events
- `reports/YYYY-MM-DD.json` — Daily summary reports

## Collected Metrics

### Stream 1 (Telemetry)
- CPU utilization (%, rates)
- Memory utilization (%, used/available)
- Process count
- File I/O rates (sectors read/written per second)
- Network connection count
- Destination IP entropy (Shannon entropy)
- Syscall frequency distribution (lightweight /proc sampling)

### Stream 2 (Actions)
- Tool call type + arguments hash
- Call latency
- Token counts (in/out per LLM call)
- User-initiated vs self-initiated flag
- Action transition context (previous → current tool)
