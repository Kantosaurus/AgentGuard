#!/bin/bash
# AgentGuard — Start both collectors as background daemons
# Usage: ./run_collectors.sh [start|stop|status]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_DIR="/var/run/agentguard"
LOG_DIR="/var/log/agentguard/logs"
mkdir -p "$PID_DIR" "$LOG_DIR"

export AGENTGUARD_DATA_DIR="${AGENTGUARD_DATA_DIR:-/var/log/agentguard}"

start() {
    echo "[AgentGuard] Starting collectors..."

    # Telemetry collector
    if [ -f "$PID_DIR/telemetry.pid" ] && kill -0 "$(cat "$PID_DIR/telemetry.pid")" 2>/dev/null; then
        echo "[AgentGuard] Telemetry collector already running (PID $(cat "$PID_DIR/telemetry.pid"))"
    else
        nohup python3 "$SCRIPT_DIR/telemetry_collector.py" > "$LOG_DIR/telemetry.log" 2>&1 &
        echo $! > "$PID_DIR/telemetry.pid"
        echo "[AgentGuard] Telemetry collector started (PID $!)"
    fi

    # Action collector
    if [ -f "$PID_DIR/actions.pid" ] && kill -0 "$(cat "$PID_DIR/actions.pid")" 2>/dev/null; then
        echo "[AgentGuard] Action collector already running (PID $(cat "$PID_DIR/actions.pid"))"
    else
        nohup python3 "$SCRIPT_DIR/action_collector.py" > "$LOG_DIR/actions.log" 2>&1 &
        echo $! > "$PID_DIR/actions.pid"
        echo "[AgentGuard] Action collector started (PID $!)"
    fi
}

stop() {
    echo "[AgentGuard] Stopping collectors..."
    for name in telemetry actions; do
        if [ -f "$PID_DIR/$name.pid" ]; then
            kill "$(cat "$PID_DIR/$name.pid")" 2>/dev/null
            rm "$PID_DIR/$name.pid"
            echo "[AgentGuard] $name collector stopped"
        fi
    done
}

status() {
    for name in telemetry actions; do
        if [ -f "$PID_DIR/$name.pid" ] && kill -0 "$(cat "$PID_DIR/$name.pid")" 2>/dev/null; then
            echo "[AgentGuard] $name: running (PID $(cat "$PID_DIR/$name.pid"))"
        else
            echo "[AgentGuard] $name: stopped"
        fi
    done
}

case "${1:-start}" in
    start) start ;;
    stop) stop ;;
    status) status ;;
    restart) stop; sleep 1; start ;;
    *) echo "Usage: $0 {start|stop|status|restart}" ;;
esac
