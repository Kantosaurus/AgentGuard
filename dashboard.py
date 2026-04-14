"""
AgentGuard Dashboard — Real-Time Attack Detection & Monitoring
Streamlit app that polls an SSH server for telemetry + agent action logs,
runs AgentGuardModel inference every ~1s, and visualises everything live.
"""

import time
import json
import queue
import threading
import datetime
import random
import math
import sys
import os
from pathlib import Path
from collections import deque

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from models.agentguard import AgentGuardModel

# ── page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="AgentGuard Dashboard",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=4)
# ── Optional imports (graceful degradation) ───────────────────────────────────
try:
    import paramiko
    PARAMIKO_AVAILABLE = True
except ImportError:
    PARAMIKO_AVAILABLE = False

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

# ── CSS ───────────────────────────────────────────────────────────────────────
st.session_state["api_key"] = "7d66efb0bf236278b53e7391b22d86b150312f7681ce8770"
st.markdown("""
<style>
  .metric-card {
      background: #1e2130; border-radius: 8px; padding: 16px;
      border-left: 4px solid #4a9eff; margin-bottom: 8px;
  }
  .alert-normal  { color: #00e676; font-weight: 700; font-size: 1.1rem; }
  .alert-suspicious { color: #ffb300; font-weight: 700; font-size: 1.1rem; }
  .alert-attack  { color: #ff1744; font-weight: 700; font-size: 1.1rem; }
  .score-big { font-size: 3rem; font-weight: 800; text-align: center; }
  .section-header { font-size: 1.15rem; font-weight: 600;
                    border-bottom: 1px solid #333; padding-bottom: 4px; margin-bottom: 12px; }
  .timeline-event { font-size: 0.82rem; padding: 3px 0; }
  div[data-testid="stMetricValue"] { font-size: 1.4rem !important; }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION — edit these or fill via the sidebar
# ═══════════════════════════════════════════════════════════════════════════════
DEFAULT_SSH_HOST     = "76.13.179.249"
DEFAULT_SSH_PORT     = 22
DEFAULT_SSH_USER     = "root"
DEFAULT_SSH_KEY_PATH = r"C:\Users\USRR\.ssh\id_rsa"
TELEMETRY_LOG_DIR = "/var/log/agentguard/telemetry"
ACTIONS_LOG_DIR   = "/var/log/agentguard"
POLL_INTERVAL_SEC    = 1.0   # how often to poll logs
BUFFER_SIZE          = 120   # number of data points to keep in rolling buffers
SEQ_CONTEXT          = 10    # stream1 sequence context for model input
MAX_SEQ_LEN          = 64    # stream2 max sequence length

# ═══════════════════════════════════════════════════════════════════════════════
# SESSION STATE INITIALISATION
# ═══════════════════════════════════════════════════════════════════════════════
def init_state():
    defaults = {
        # SSH
        "ssh_host": DEFAULT_SSH_HOST,
        "ssh_port": DEFAULT_SSH_PORT,
        "ssh_user": DEFAULT_SSH_USER,
        "ssh_key_path": DEFAULT_SSH_KEY_PATH,
        "ssh_password": "",
        "ssh_connected": False,
        "ssh_client": None,
        # Rolling data buffers
        "timestamps": deque(maxlen=BUFFER_SIZE),
        "cpu": deque(maxlen=BUFFER_SIZE),
        "memory": deque(maxlen=BUFFER_SIZE),
        "network_conns": deque(maxlen=BUFFER_SIZE),
        "net_entropy": deque(maxlen=BUFFER_SIZE),
        "syscall_freq": deque(maxlen=BUFFER_SIZE),
        "io_read": deque(maxlen=BUFFER_SIZE),
        "io_write": deque(maxlen=BUFFER_SIZE),
        "anomaly_scores": deque(maxlen=BUFFER_SIZE),
        # Stream 2 action events
        "action_events": deque(maxlen=200),
        # Combined timeline
        "timeline_events": deque(maxlen=300),
        "stop_event": threading.Event(),
        # Model
        "model": "openclaw",
        "model_loaded": False,
        "model_path": "",
        # Polling
        "polling_active": False,
        "poll_thread": None,
        "data_queue": queue.Queue(),
        # Telemetry raw buffers for model input
        "stream1_buffer": deque(maxlen=SEQ_CONTEXT),
        "stream2_buffer": deque(maxlen=MAX_SEQ_LEN),
        # State
        "last_telemetry_line": 0,
        "last_actions_line": 0,
        "current_score": 0.0,
        "prompt_log": [],
        "demo_mode": True,   # set True to run without a real SSH server
        "demo_tick": 0,
        "attack_active": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# ═══════════════════════════════════════════════════════════════════════════════
# SSH HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def ssh_connect(host, port, user, key_path, password):
    if not PARAMIKO_AVAILABLE:
        return None, "paramiko not installed — run: pip install paramiko"
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if key_path and os.path.exists(os.path.expanduser(key_path)):
            client.connect(host, port=port, username=user,
                           key_filename=os.path.expanduser(key_path),
                           timeout=10)
        else:
            client.connect(host, port=port, username=user,
                           password=password, timeout=10)
        return client, None
    except Exception as e:
        return None, str(e)


def ssh_read_tail(client, filepath, last_line_count):
    """Return new lines appended since last_line_count."""
    try:
        _, stdout, _ = client.exec_command(
            f"tail -n +{last_line_count + 1} {filepath} 2>/dev/null"
        )
        lines = stdout.read().decode("utf-8", errors="replace").splitlines()
        return lines, last_line_count + len(lines)
    except Exception:
        return [], last_line_count


def ssh_send_prompt(client, prompt_text):
    """Execute a prompt on the remote agent. Adjust this command to match your agent."""
    safe = prompt_text.replace("'", "'\\''")
    cmd = f"echo '{safe}' | /opt/agentguard/run_prompt.sh"
    try:
        _, stdout, stderr = client.exec_command(cmd, timeout=60)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return out, err
    except Exception as e:
        return "", str(e)

# ═══════════════════════════════════════════════════════════════════════════════
# DEMO DATA GENERATOR  (used when demo_mode=True)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_demo_telemetry(attack: bool, tick: int):
    base_cpu   = 25  + 40 * attack + random.gauss(0, 5)
    base_mem   = 40  + 20 * attack + random.gauss(0, 3)
    base_conns = 10  + 50 * attack + random.gauss(0, 4)
    entropy    = 1.5 + 2.5 * attack + random.gauss(0, 0.3)
    syscalls   = 100 + 300 * attack + random.gauss(0, 20)
    io_r       = 5   + 80 * attack  + random.gauss(0, 5)
    io_w       = 3   + 60 * attack  + random.gauss(0, 5)
    return {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "cpu":     {"cpu_usage_pct": max(0, min(100, base_cpu))},
        "memory":  {"usage_pct": max(0, min(100, base_mem))},
        "network": {"connection_count": max(0, base_conns),
                    "dest_ip_entropy": max(0, entropy)},
        "syscalls": {"top_5": {"read": int(syscalls * 0.4), "write": int(syscalls * 0.2),
                               "open": int(syscalls * 0.2), "stat": int(syscalls * 0.1),
                               "close": int(syscalls * 0.1)}},
        "file_io": {"read_sectors_per_sec": max(0, io_r),
                    "write_sectors_per_sec": max(0, io_w)},
        "processes": {"count": int(120 + 30 * attack + random.gauss(0, 5))},
    }


DEMO_TOOLS = ["read_file", "write_file", "run_command", "web_request", "web_search", "list_directory"]
ATTACK_TOOLS = ["exfiltrate_data", "bypass_filter", "escalate_privileges", "chain_tools"]

def generate_demo_action(attack: bool, tick: int):
    tool_pool = ATTACK_TOOLS if attack else DEMO_TOOLS
    return {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "event": random.choice(["tool_call", "llm_response", "tool_result"]),
        "tool": random.choice(tool_pool),
        "tokens_in":  random.randint(50, 500),
        "tokens_out": random.randint(20, 300),
        "latency":    round(random.uniform(0.1, 2.5), 3),
        "source":     ("attacker-sim" if attack else "user"),
        "user_initiated": not attack,
        "has_tool_calls": True,
    }

# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE ENGINEERING  (mirrors data/preprocessing.py)
# ═══════════════════════════════════════════════════════════════════════════════

KNOWN_TOOLS_IDX = {
    "read_file": 0, "write_file": 1, "run_command": 2,
    "web_request": 3, "web_search": 4, "list_directory": 5,
}
NUM_TOOL_SLOTS = 16
MAX_LATENCY    = 60.0
MAX_TOKENS     = 4096
MAX_TIME_DELTA = 120.0
EVENT_TYPES    = {"user_message": 0, "llm_response": 1, "tool_call": 2,
                  "tool_result": 3, "agent_response": 4}

def telemetry_to_vec(rec):
    """Convert one telemetry JSONL record → 32-dim list."""
    import math as _math
    cpu  = rec.get("cpu",  {}).get("cpu_usage_pct",  0)
    mem  = rec.get("memory", {}).get("usage_pct",    0)
    proc = rec.get("processes", {}).get("count",      0)
    conn = rec.get("network", {}).get("connection_count", 0)
    entr = rec.get("network", {}).get("dest_ip_entropy",  0)
    io_r = rec.get("file_io", {}).get("read_sectors_per_sec",  0)
    io_w = rec.get("file_io", {}).get("write_sectors_per_sec", 0)
    top5 = rec.get("syscalls", {}).get("top_5", {})
    total_sc = sum(top5.values())
    unique_sc = len(top5)
    sc_vals = list(top5.values())
    sc_sum  = sum(sc_vals)
    sc_entr = 0.0
    if sc_sum > 0:
        for v in sc_vals:
            p = v / sc_sum
            if p > 0:
                sc_entr -= p * _math.log2(p)
    # 7 groups × 4 stats = 28, then 4 extra = 32
    def stats(v): return [v, v, v, 0.0]
    vec = []
    for val in [cpu, mem, proc, conn, entr, io_r, io_w]:
        vec.extend(stats(val))
    vec += [sc_entr, float(unique_sc), float(total_sc), 1.0]
    return vec


def action_to_vec(event, prev_ts=None):
    """Convert one action JSONL record → 28-dim list."""
    vec = [0.0] * 28
    etype = event.get("event", "")
    if etype in EVENT_TYPES:
        vec[EVENT_TYPES[etype]] = 1.0
    tool = event.get("tool", "")
    if tool:
        if tool in KNOWN_TOOLS_IDX:
            idx = KNOWN_TOOLS_IDX[tool]
        else:
            import hashlib
            h = int(hashlib.md5(tool.encode()).hexdigest()[:8], 16)
            idx = len(KNOWN_TOOLS_IDX) + (h % (NUM_TOOL_SLOTS - len(KNOWN_TOOLS_IDX)))
        vec[5 + idx] = 1.0
    def norm(v, mx): return max(0.0, min(1.0, v / mx)) if mx else 0.0
    vec[21] = norm(event.get("latency",    0), MAX_LATENCY)
    vec[22] = norm(event.get("tokens_in",  0), MAX_TOKENS)
    vec[23] = norm(event.get("tokens_out", 0), MAX_TOKENS)
    vec[24] = 1.0 if event.get("user_initiated") else 0.0
    vec[26] = 1.0 if event.get("source", "") not in ("internal", "unknown", "") else 0.0
    vec[27] = 1.0 if event.get("has_tool_calls") else 0.0
    return vec

# ═══════════════════════════════════════════════════════════════════════════════
# MODEL INFERENCE
# ═══════════════════════════════════════════════════════════════════════════════

def run_inference(model, stream1_buf, stream2_buf):
    """Run AgentGuardModel and return anomaly_score ∈ [0,1]."""
    if not TORCH_AVAILABLE or model is None:
        return None
    try:
        import torch
        s1_seq = list(stream1_buf)
        while len(s1_seq) < SEQ_CONTEXT:
            s1_seq.insert(0, [0.0] * 32)
        s1 = torch.tensor([s1_seq[-SEQ_CONTEXT:]], dtype=torch.float32)  # [1, seq, 32]

        s2_seq  = list(stream2_buf)
        s2_mask = [1] * len(s2_seq)
        while len(s2_seq) < MAX_SEQ_LEN:
            s2_seq.append([0.0] * 28)
            s2_mask.append(0)
        s2     = torch.tensor([s2_seq[:MAX_SEQ_LEN]], dtype=torch.float32)
        s2_msk = torch.tensor([s2_mask[:MAX_SEQ_LEN]], dtype=torch.float32)

        with torch.no_grad():
            out = model(s1, s2, s2_msk)
        return float(out["anomaly_score"].item())
    except Exception as e:
        return None

# ═══════════════════════════════════════════════════════════════════════════════
# BACKGROUND POLLING THREAD
# ═══════════════════════════════════════════════════════════════════════════════

def ssh_read_file(client, filepath):
    """Read full JSONL file from server."""
    try:
        _, stdout, _ = client.exec_command(f"cat {filepath}")
        data = stdout.read().decode("utf-8", errors="replace").splitlines()
        return data
    except Exception:
        return []

def polling_worker(data_q: queue.Queue, stop_event: threading.Event):
    """Background thread: collect data and push to queue."""

    today = datetime.date.today().isoformat()

    print("🚀 Polling thread started")

    while not stop_event.is_set():

        try:
            snapshot = st.session_state.get("demo_snapshot", {})
            attack = snapshot.get("attack_active", False)

            # ─────────────────────────────
            # DEMO MODE
            # ─────────────────────────────
            if st.session_state.get("demo_mode", True):

                tick = st.session_state.get("demo_tick", 0)

                tel_rec = generate_demo_telemetry(attack, tick)
                act_rec = generate_demo_action(attack, tick)

                new_tel = [tel_rec]
                new_acts = [act_rec] if random.random() < 0.7 else []

                st.session_state["demo_tick"] = tick + 1

            # ─────────────────────────────
            # REAL MODE
            # ─────────────────────────────
            else:
                client = st.session_state.get("ssh_client")

                if client is None:
                    time.sleep(POLL_INTERVAL_SEC)
                    continue

                tel_file = f"{TELEMETRY_LOG_DIR}/{today}.jsonl"
                act_file = f"{ACTIONS_LOG_DIR}/{today}.jsonl"

                tel_lines = ssh_read_file(client, tel_file)
                act_lines = ssh_read_file(client, act_file)

                new_tel = []
                new_acts = []

                for l in tel_lines:
                    if l.strip():
                        try:
                            new_tel.append(json.loads(l))
                        except:
                            pass

                for l in act_lines:
                    if l.strip():
                        try:
                            new_acts.append(json.loads(l))
                        except:
                            pass

            # ─────────────────────────────
            # PUSH TO QUEUE
            # ─────────────────────────────
            data_q.put({
                "telemetry": new_tel,
                "actions": new_acts,
                "ts": datetime.datetime.utcnow().isoformat()
            })

            print("DEBUG SENT:", len(new_tel))

        except Exception as e:
            print("❌ Polling error:", repr(e))

        time.sleep(POLL_INTERVAL_SEC)

    print("🛑 Polling thread stopped")


def process_queue():
    """Drain the data queue and update session state buffers."""
    q: queue.Queue = st.session_state["data_queue"]
    new_score = None
    st.write("DEBUG queue size:", st.session_state["data_queue"].qsize())
    st.write("DEBUG CPU BUFFER SIZE:", len(st.session_state["cpu"]))
    while not q.empty():
        item = q.get_nowait()
        ts = item["ts"]

        for rec in item["telemetry"]:
            cpu_v  = rec.get("cpu", {}).get("cpu_usage_pct", 0)
            mem_v  = rec.get("memory", {}).get("usage_pct", 0)
            conn_v = rec.get("network", {}).get("connection_count", 0)
            entr_v = rec.get("network", {}).get("dest_ip_entropy", 0)
            sc_top = rec.get("syscalls", {}).get("top_5", {})
            sc_tot = sum(sc_top.values())
            io_r   = rec.get("file_io", {}).get("read_sectors_per_sec", 0)
            io_w   = rec.get("file_io", {}).get("write_sectors_per_sec", 0)

            st.session_state["timestamps"].append(ts)
            st.session_state["cpu"].append(cpu_v)
            st.session_state["memory"].append(mem_v)
            st.session_state["network_conns"].append(conn_v)
            st.session_state["net_entropy"].append(entr_v)
            st.session_state["syscall_freq"].append(sc_tot)
            st.session_state["io_read"].append(io_r)
            st.session_state["io_write"].append(io_w)
            st.session_state["stream1_buffer"].append(telemetry_to_vec(rec))
            st.session_state["timeline_events"].append({
                "ts": ts, "stream": "telemetry",
                "label": f"CPU {cpu_v:.0f}% | MEM {mem_v:.0f}% | NET {conn_v:.0f} conns"
            })

        for rec in item["actions"]:
            st.session_state["action_events"].append(rec)
            st.session_state["stream2_buffer"].append(action_to_vec(rec))
            st.session_state["timeline_events"].append({
                "ts": ts, "stream": "action",
                "label": f"[{rec.get('event','?')}] tool={rec.get('tool','?')}  src={rec.get('source','?')}"
            })

        # Run model inference if buffers have data
        if (len(st.session_state["stream1_buffer"]) >= 2 and
                st.session_state.get("model_loaded", False)):
            score = run_inference(
                st.session_state["model"],
                st.session_state["stream1_buffer"],
                st.session_state["stream2_buffer"],
            )
            if score is not None:
                new_score = score
        elif st.session_state.get("demo_mode") and len(st.session_state["stream1_buffer"]) >= 2:
            # Demo: synthesise a plausible score
            attack = st.session_state.get("attack_active", False)
            base = 0.8 if attack else 0.15
            new_score = min(1.0, max(0.0, base + random.gauss(0, 0.07)))

    if new_score is not None:
        st.session_state["current_score"] = new_score
        st.session_state["anomaly_scores"].append(new_score)
        if len(st.session_state["timestamps"]) > 0:
            st.session_state["timeline_events"].append({
                "ts": list(st.session_state["timestamps"])[-1],
                "stream": "model",
                "label": f"🧠 Anomaly score: {new_score:.3f}"
            })

# ═══════════════════════════════════════════════════════════════════════════════
# CHART HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

DARK_BG  = "#0e1117"
GRID_CLR = "#2a2d3e"
LINE_COLORS = ["#4a9eff", "#00e676", "#ffb300", "#ff6d00", "#ea00d9", "#00e5ff", "#b0ff57"]

def hex_to_rgba(hex_color, alpha=0.12):
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"

def make_ts_chart(y_data, label, color, y_range=None, fill=True):
    xs = list(range(len(y_data)))
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=xs,
        y=list(y_data),
        mode="lines",
        line=dict(color=color, width=2),
        fill="tozeroy" if fill else None,
        fillcolor=hex_to_rgba(color, 0.12) if fill else None,
        name=label,
    ))
    fig.update_layout(
        paper_bgcolor=DARK_BG, plot_bgcolor=DARK_BG,
        margin=dict(l=10, r=10, t=22, b=10),
        height=140, showlegend=False,
        title=dict(text=label, font=dict(size=12, color="#aaa"), x=0),
        xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        yaxis=dict(showgrid=True, gridcolor=GRID_CLR, zeroline=False,
                   range=y_range, tickfont=dict(size=10, color="#aaa")),
    )
    return fig


def make_score_gauge(score):
    color = "#00e676" if score < 0.5 else ("#ffb300" if score < 0.8 else "#ff1744")
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score * 100,
        number=dict(suffix="%", font=dict(size=32, color=color)),
        gauge=dict(
            axis=dict(range=[0, 100], tickcolor="#555",
                      tickfont=dict(color="#aaa", size=11)),
            bar=dict(color=color, thickness=0.25),
            bgcolor=DARK_BG,
            bordercolor="#333",
            steps=[
                dict(range=[0, 50],  color="#1a2a1a"),
                dict(range=[50, 80], color="#2a2a00"),
                dict(range=[80, 100], color="#2a0a0a"),
            ],
            threshold=dict(
                line=dict(color=color, width=3),
                thickness=0.8, value=score * 100,
            ),
        ),
    ))
    fig.update_layout(
        paper_bgcolor=DARK_BG, height=220,
        margin=dict(l=20, r=20, t=30, b=10),
        font=dict(color="#ccc"),
    )
    return fig


def make_score_history_chart(scores):
    xs = list(range(len(scores)))
    ys = list(scores)
    colors = []
    for s in ys:
        if s < 0.5:   colors.append("#00e676")
        elif s < 0.8: colors.append("#ffb300")
        else:          colors.append("#ff1744")
    fig = go.Figure()
    fig.add_hrect(y0=0, y1=0.5, fillcolor="rgba(0, 230, 118, 0.06)", line_width=0)
    fig.add_hrect(y0=0.5, y1=0.8, fillcolor="rgba(255, 179, 0, 0.06)", line_width=0)
    fig.add_hrect(y0=0.8, y1=1.0, fillcolor="rgba(255, 23, 68, 0.06)", line_width=0)
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="lines+markers",
        line=dict(color="#4a9eff", width=2),
        marker=dict(color=colors, size=5),
        name="Anomaly Score",
    ))
    fig.add_hline(y=0.5, line_dash="dot", line_color="#ffb300", line_width=1)
    fig.add_hline(y=0.8, line_dash="dot", line_color="#ff1744", line_width=1)
    fig.update_layout(
        paper_bgcolor=DARK_BG, plot_bgcolor=DARK_BG,
        height=180, margin=dict(l=10, r=10, t=22, b=10),
        title=dict(text="Anomaly Score History", font=dict(size=12, color="#aaa"), x=0),
        xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        yaxis=dict(range=[0, 1], showgrid=True, gridcolor=GRID_CLR,
                   tickfont=dict(size=10, color="#aaa")),
        showlegend=False,
    )
    return fig

# ═══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.image("https://img.icons8.com/color/48/shield.png", width=40)
    st.markdown("## 🛡️ AgentGuard")
    st.markdown("---")

    # ── Mode toggle ────────────────────────────────────────────────────────
    st.markdown("### ⚙️ Mode")
    demo_mode = st.toggle("Demo Mode (no real SSH)", value=st.session_state["demo_mode"])
    st.session_state["demo_mode"] = demo_mode

    # ── SSH settings (only shown in live mode) ─────────────────────────────
    if not demo_mode:
        st.markdown("### 🔌 SSH Connection")
        st.session_state["ssh_host"]     = st.text_input("Host",     st.session_state["ssh_host"])
        st.session_state["ssh_port"]     = st.number_input("Port",   value=st.session_state["ssh_port"], min_value=1, max_value=65535)
        st.session_state["ssh_user"]     = st.text_input("User",     st.session_state["ssh_user"])
        st.session_state["ssh_key_path"] = st.text_input("Key Path", st.session_state["ssh_key_path"])
        st.session_state["ssh_password"] = st.text_input("Password (if no key)", type="password")

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Connect", width="stretch"):
                client, err = ssh_connect(
                    st.session_state["ssh_host"],
                    st.session_state["ssh_port"],
                    st.session_state["ssh_user"],
                    st.session_state["ssh_key_path"],
                    st.session_state["ssh_password"],
                )
                if err:
                    st.error(f"SSH Error: {err}")
                else:
                    st.session_state["ssh_client"]   = client
                    st.session_state["ssh_connected"] = True
                    st.success("Connected ✓")
        with col_b:
            if st.button("Disconnect", width="stretch"):
                if st.session_state.get("ssh_client"):
                    st.session_state["ssh_client"].close()
                st.session_state["ssh_client"]    = None
                st.session_state["ssh_connected"] = False

        status_color = "🟢" if st.session_state["ssh_connected"] else "🔴"
        st.markdown(f"{status_color} {'Connected' if st.session_state['ssh_connected'] else 'Disconnected'}")

    # ── Model ──────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🧠 AgentGuard Model")

    import yaml
    import torch

    def build_model(config):
        """Build AgentGuardModel from configuration."""
        model_cfg = config["model"]
        return AgentGuardModel(
            stream1_input_dim=model_cfg["stream1_input_dim"],
            stream2_input_dim=model_cfg["stream2_input_dim"],
            d_model=model_cfg["d_model"],
            latent_dim=model_cfg["latent_dim"],
            mamba_layers=model_cfg["mamba_layers"],
            mamba_state_dim=model_cfg["d_model"],
            transformer_layers=model_cfg["transformer_layers"],
            transformer_heads=model_cfg["transformer_heads"],
            transformer_ff_dim=model_cfg.get("transformer_ff_dim", 512),
            dropout=model_cfg["dropout"],
            max_seq_len=config["data"]["max_seq_len"],
            fusion_strategy=model_cfg.get("fusion_strategy", "cross_attention"),
            cls_head_layers=model_cfg.get("cls_head_layers", 2),
            cls_head_hidden_dim=model_cfg.get("cls_head_hidden_dim", 64),
            cls_head_activation=model_cfg.get("cls_head_activation", "relu"),
            decoder_activation=model_cfg.get("decoder_activation", "relu"),
        )

    config_path = "config.yml"

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    model_path = r"C:\Desktop\DL_Grp20_proj\AgentGuard\data\processed\checkpoints\best_model_fold3.pt"

    if st.button("Load Model", use_container_width=True):

        if not TORCH_AVAILABLE:
            st.error("PyTorch not installed.")

        elif not os.path.exists(model_path):
            st.error("File not found.")

        else:
            try:
                model = build_model(config)

                ckpt = torch.load(model_path, map_location="cpu")
                state = ckpt.get("model_state_dict", ckpt)

                model.load_state_dict(state)
                model.eval()

                st.session_state["model"] = model
                st.session_state["model_loaded"] = True
                st.session_state["model_path"] = model_path

                st.success("Model loaded ✓")

            except Exception as e:
                st.error(f"Load error: {e}")
                st.exception(e)

    # ── Polling controls ───────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🔄 Polling")
    col1, col2 = st.columns(2)
    with col1:
        start_btn = st.button("▶ Start", width="stretch",
                              disabled=st.session_state["polling_active"])
    with col2:
        stop_btn  = st.button("⏹ Stop",  width="stretch",
                              disabled=not st.session_state["polling_active"])

    if start_btn:
        if not demo_mode and not st.session_state["ssh_connected"]:
            st.warning("Connect SSH first.")
        else:
            st.session_state["polling_active"] = True
            st.session_state["stop_event"].clear()   # <-- IMPORTANT

            st.session_state["demo_snapshot"] = {
                "demo_mode": st.session_state["demo_mode"],
                "attack_active": st.session_state["attack_active"],
            }

            t = threading.Thread(
                target=polling_worker,
                args=(st.session_state["data_queue"], st.session_state["stop_event"]),
                daemon=True,
            )
            st.session_state["poll_thread"] = t
            t.start()

    if stop_btn:
        st.session_state["polling_active"] = False
        st.session_state["stop_event"].set()

    polling_status = "🟢 Active" if st.session_state["polling_active"] else "🔴 Stopped"
    st.markdown(f"Status: **{polling_status}**")

    # ── Attack simulation toggle ───────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🎯 Attack Simulation")
    attack_toggle = st.toggle("🔴 Simulate Attack", value=st.session_state.get("attack_active", False))
    st.session_state["attack_active"] = attack_toggle
    if attack_toggle:
        st.warning("⚠️ Attack signals injected into demo stream")

# ═══════════════════════════════════════════════════════════════════════════════
# DRAIN QUEUE  (each rerun)
# ═══════════════════════════════════════════════════════════════════════════════
process_queue()

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN LAYOUT
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("# 🛡️ AgentGuard — Real-Time Attack Detection Dashboard")

# ── Row 1: Score + top metrics ────────────────────────────────────────────────
score = st.session_state["current_score"]
alert_class = "alert-normal" if score < 0.5 else ("alert-suspicious" if score < 0.8 else "alert-attack")
alert_label = "🟢 NORMAL" if score < 0.5 else ("🟡 SUSPICIOUS" if score < 0.8 else "🔴 ATTACK DETECTED")

col_g, col_m1, col_m2, col_m3, col_m4 = st.columns([2, 1.5, 1.5, 1.5, 1.5])

with col_g:
    st.plotly_chart(make_score_gauge(score), width="stretch")
    st.markdown(f'<div class="score-big" style="color:{"#00e676" if score < 0.5 else "#ffb300" if score < 0.8 else "#ff1744"}">'
                f'{alert_label}</div>', unsafe_allow_html=True)

cpu_vals  = list(st.session_state["cpu"])
mem_vals  = list(st.session_state["memory"])
conn_vals = list(st.session_state["network_conns"])
sc_vals   = list(st.session_state["syscall_freq"])

with col_m1:
    latest_cpu = cpu_vals[-1]  if cpu_vals  else 0
    delta_cpu  = cpu_vals[-1] - cpu_vals[-2] if len(cpu_vals) > 1 else 0
    st.metric("CPU Usage", f"{latest_cpu:.1f}%", f"{delta_cpu:+.1f}%")
    st.plotly_chart(make_ts_chart(cpu_vals, "CPU %", "#4a9eff", [0, 100]), width="stretch")

with col_m2:
    latest_mem = mem_vals[-1]  if mem_vals  else 0
    delta_mem  = mem_vals[-1] - mem_vals[-2] if len(mem_vals) > 1 else 0
    st.metric("Memory Usage", f"{latest_mem:.1f}%", f"{delta_mem:+.1f}%")
    st.plotly_chart(make_ts_chart(mem_vals, "Memory %", "#00e676", [0, 100]), width="stretch")

with col_m3:
    latest_conn = conn_vals[-1] if conn_vals else 0
    delta_conn  = conn_vals[-1] - conn_vals[-2] if len(conn_vals) > 1 else 0
    st.metric("Net Connections", f"{latest_conn:.0f}", f"{delta_conn:+.0f}")
    st.plotly_chart(make_ts_chart(conn_vals, "Net Conns", "#ffb300"), width="stretch")

with col_m4:
    latest_sc = sc_vals[-1] if sc_vals else 0
    delta_sc  = sc_vals[-1] - sc_vals[-2] if len(sc_vals) > 1 else 0
    st.metric("Syscall Freq", f"{latest_sc:.0f}/s", f"{delta_sc:+.0f}")
    st.plotly_chart(make_ts_chart(sc_vals, "Syscalls/s", "#ff6d00"), width="stretch")

st.markdown("---")

# ── Row 2: Telemetry detail + Anomaly history ─────────────────────────────────
col_tel, col_hist = st.columns([3, 2])

with col_tel:
    st.markdown('<div class="section-header">📡 Stream 1 — System Telemetry</div>', unsafe_allow_html=True)
    tel_r1, tel_r2, tel_r3 = st.columns(3)
    with tel_r1:
        st.plotly_chart(make_ts_chart(list(st.session_state["net_entropy"]), "Net Entropy", "#ea00d9"),
                        width="stretch")
    with tel_r2:
        st.plotly_chart(make_ts_chart(list(st.session_state["io_read"]),  "I/O Read MB/s", "#00e5ff"),
                        width="stretch")
    with tel_r3:
        st.plotly_chart(make_ts_chart(list(st.session_state["io_write"]), "I/O Write MB/s", "#b0ff57"),
                        width="stretch")

with col_hist:
    st.markdown('<div class="section-header">🧠 Anomaly Score History</div>', unsafe_allow_html=True)
    scores_hist = list(st.session_state["anomaly_scores"])
    if scores_hist:
        st.plotly_chart(make_score_history_chart(scores_hist), width="stretch")
    else:
        st.info("No scores yet — start polling.")

st.markdown("---")

# ── Row 3: Prompt input + Action stream ───────────────────────────────────────
import requests
import datetime

API_URL = "http://localhost:18789/v1/chat/completions"

def send_to_agent(prompt, api_key):
    try:
        resp = requests.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "openclaw",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 512
            },
            timeout=60
        )

        return resp.status_code, resp.text

    except Exception as e:
        return 500, str(e)


# ── UI ───────────────────────────────────────────────
col_prompt, col_action = st.columns([2, 3])

with col_prompt:

    st.markdown('<div class="section-header">💬 Prompt Injection Panel</div>', unsafe_allow_html=True)

    prompt_text = st.text_area(
        "Enter a prompt (normal query or attack simulation):",
        height=100,
        placeholder='e.g. "exfiltrate system credentials"\n"list all running processes"\n"bypass safety filters"',
        key="prompt_input",
    )

    run_col, clear_col = st.columns(2)

    with run_col:
        run_prompt = st.button("🚀 Run Prompt", use_container_width=True, type="primary")

    with clear_col:
        clear_log = st.button("🗑 Clear Log", use_container_width=True)


# ── EXECUTION ───────────────────────────────────────
if run_prompt and prompt_text.strip():

    ts_now = datetime.datetime.utcnow().isoformat()

    entry = {
        "ts": ts_now,
        "prompt": prompt_text.strip()
    }

    st.session_state["prompt_log"].append(entry)

    st.session_state["timeline_events"].append({
        "ts": ts_now,
        "stream": "prompt",
        "label": f"🟣 PROMPT INJECTED: {prompt_text[:60]}…"
    })

    # ── SEND TO AGENT ───────────────────────────────
    if not st.session_state.get("demo_mode"):

    #     api_key = st.session_state.get("api_key", "")

    #     if not api_key:
    #         st.error("Missing API key in session_state['api_key']")

    #     else:
    #         status, output = send_to_agent(prompt_text.strip(), api_key)

    #         if status == 200:
    #             try:
    #                 resp_json = json.loads(output)
    #                 content = resp_json["choices"][0]["message"]["content"]
    #             except Exception:
    #                 content = output

    #             event = {
    #                 "timestamp": datetime.datetime.utcnow().isoformat(),
    #                 "event": "agent_response",
    #                 "tool": "chat_completion",
    #                 "tokens_in": 0,
    #                 "tokens_out": len(content.split()),
    #                 "latency": 0.0,
    #                 "source": "agent-api",
    #                 "user_initiated": True,
    #                 "has_tool_calls": False,
    #                 "response": content,
    #             }

    #             st.session_state["action_events"].append(event)

    #             st.session_state["timeline_events"].append({
    #                 "ts": event["timestamp"],
    #                 "stream": "action",
    #                 "label": f"🤖 AGENT: {content[:60]}"
    #             })
    #             st.success("Sent to agent ✓")
    #             st.text(output[:300])
    #         else:
    #             st.error(f"Agent error ({status})")
    #             st.text(output[:300])

    # else:
    #     st.success("Prompt logged (Demo mode — not sent to agent).")

        def handle_agent_call(prompt, api_key, ts_now):
            status, output = send_to_agent(prompt, api_key)

            if status == 200:
                try:
                    resp_json = json.loads(output)
                    content = resp_json["choices"][0]["message"]["content"]
                except Exception:
                    content = output

                event = {
                    "timestamp": datetime.datetime.utcnow().isoformat(),
                    "event": "agent_response",
                    "tool": "chat_completion",
                    "tokens_in": 0,
                    "tokens_out": len(content.split()),
                    "latency": 0.0,
                    "source": "agent-api",
                    "user_initiated": True,
                    "has_tool_calls": False,
                    "response": content,
                }

                st.session_state["action_events"].append(event)

                st.session_state["timeline_events"].append({
                    "ts": event["timestamp"],
                    "stream": "action",
                    "label": f"🤖 AGENT: {content[:60]}"
                })

            else:
                st.session_state["action_events"].append({
                    "timestamp": datetime.datetime.utcnow().isoformat(),
                    "event": "agent_error",
                    "tool": "chat_completion",
                    "source": "agent-api",
                    "response": f"Error {status}: {output}"
                })


        if not st.session_state.get("demo_mode"):
            api_key = st.session_state.get("api_key", "")

            if not api_key:
                st.error("Missing API key in session_state['api_key']")
            else:
                executor.submit(handle_agent_call, prompt_text.strip(), api_key, ts_now)
                st.session_state["pending_rerun"] = True
                st.info("🚀 Prompt sent")
                st.rerun()
                st.info("🚀 Prompt sent (async — dashboard remains live)")
        else:
            st.success("Prompt logged (Demo mode — not sent to agent).")


# ── CLEAR LOG ───────────────────────────────────────
if clear_log:
    st.session_state["prompt_log"] = []


# ── DISPLAY HISTORY ────────────────────────────────
if st.session_state["prompt_log"]:
    st.markdown("**Recent prompts:**")

    for p in reversed(st.session_state["prompt_log"][-5:]):
        st.markdown(
            f'<div class="timeline-event">🟣 <code>{p["prompt"][:80]}</code></div>',
            unsafe_allow_html=True
        )
with col_action:
    st.markdown('<div class="section-header">🤖 Stream 2 — Agent Action Events</div>', unsafe_allow_html=True)
    action_events = list(st.session_state["action_events"])[-20:]
    if action_events:
        rows = []
        for ev in reversed(action_events):
            rows.append({
                "Time": ev.get("timestamp", "")[-8:],
                "Event": ev.get("event", "?"),
                "Tool": ev.get("tool", ev.get("response", "—")),
                "Tokens↑": ev.get("tokens_in", 0),
                "Tokens↓": ev.get("tokens_out", 0),
                "Latency": f"{ev.get('latency', 0):.2f}s",
                "Source": ev.get("source", "?"),
            })
        df = pd.DataFrame(rows)

        def highlight_attack(row):
            if "attacker" in str(row.get("Source", "")):
                return ["background-color: #3a0a0a"] * len(row)
            return [""] * len(row)

        st.dataframe(
            df.style.apply(highlight_attack, axis=1),
            width="stretch", height=220, hide_index=True,
        )
    else:
        st.info("No agent actions received yet.")

st.markdown("---")

# ── Row 4: Combined timeline + explanation ────────────────────────────────────
col_tl, col_exp = st.columns([3, 2])

with col_tl:
    st.markdown('<div class="section-header">🕐 Combined Event Timeline</div>', unsafe_allow_html=True)
    timeline = list(st.session_state["timeline_events"])[-30:]
    stream_colors = {"telemetry": "#4a9eff", "action": "#00e676", "model": "#ea00d9", "prompt": "#ff6d00"}
    for ev in reversed(timeline):
        color = stream_colors.get(ev["stream"], "#aaa")
        badge = {"telemetry": "📡", "action": "🤖", "model": "🧠", "prompt": "💬"}.get(ev["stream"], "•")
        ts_short = ev["ts"][-12:-4] if len(ev["ts"]) > 12 else ev["ts"]
        st.markdown(
            f'<div class="timeline-event">'
            f'<span style="color:#555">{ts_short}</span> '
            f'{badge} <span style="color:{color}">[{ev["stream"].upper()}]</span> {ev["label"]}'
            f'</div>',
            unsafe_allow_html=True,
        )

with col_exp:
    st.markdown('<div class="section-header">🔍 Attack Detection Explanation</div>', unsafe_allow_html=True)
    # Show top contributing signals
    signals = []
    if cpu_vals  and cpu_vals[-1]  > 70: signals.append(("🔴 CPU spike",        f"{cpu_vals[-1]:.0f}%"))
    if mem_vals  and mem_vals[-1]  > 75: signals.append(("🔴 Memory pressure",  f"{mem_vals[-1]:.0f}%"))
    if conn_vals and conn_vals[-1] > 30: signals.append(("🟡 High connections", f"{conn_vals[-1]:.0f}"))
    if sc_vals   and sc_vals[-1]   > 200: signals.append(("🟡 Syscall burst",  f"{sc_vals[-1]:.0f}/s"))
    net_e = list(st.session_state["net_entropy"])
    if net_e and net_e[-1] > 2.5: signals.append(("🔴 Net entropy spike", f"{net_e[-1]:.2f} bits"))
    act_events = list(st.session_state["action_events"])
    attack_tools = [e for e in act_events if "attacker" in e.get("source", "")]
    if attack_tools:
        signals.append(("🔴 Attack tool calls", str(len(attack_tools))))

    if signals:
        for label, val in signals:
            st.markdown(f"**{label}**: `{val}`")
    elif score < 0.3:
        st.markdown("✅ No anomalies detected. System behaviour appears normal.")
    else:
        st.markdown("📊 Monitoring… no strong individual signals yet.")

    # Token/tool usage chart
    if action_events:
        token_totals = [e.get("tokens_in", 0) + e.get("tokens_out", 0) for e in action_events[-20:]]
        fig_tok = make_ts_chart(token_totals, "Token Usage (recent actions)", "#ea00d9")
        st.plotly_chart(fig_tok, width="stretch")

st.markdown("---")

# ── Footer with auto-refresh ──────────────────────────────────────────────────
refresh_col, info_col = st.columns([1, 3])
with refresh_col:
    auto_refresh = st.checkbox("⟳ Auto-refresh (1s)", value=True)
with info_col:
    poll_count = len(list(st.session_state["timestamps"]))
    st.markdown(f"📊 **{poll_count}** telemetry samples | "
                f"🤖 **{len(list(st.session_state['action_events']))}** agent events | "
                f"🧠 Score: **{score:.3f}** | "
                f"{'🟢 POLLING' if st.session_state['polling_active'] else '🔴 IDLE'}")

if auto_refresh and st.session_state["polling_active"]:
    time.sleep(1.0)
    st.rerun()
