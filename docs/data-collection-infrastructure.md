# AgentGuard — Data Collection Infrastructure

## 1. Overview

AgentGuard is a dual-stream anomaly detection system designed to identify malicious behavior in AI agent servers. The core hypothesis: by monitoring both **OS-level telemetry** and **LLM action logs** simultaneously, we can detect attacks that would be invisible to either stream alone.

This document describes the data collection infrastructure deployed to generate labeled training data for the detection model.

---

## 2. Architecture

### 2.1 Test Environment

- **Server:** Debian 13 (Trixie), 2 vCPUs (AMD EPYC 9354P), 8GB RAM, 99GB disk
- **Containerization:** Docker with per-container memory limits (800MB)
- **Network:** Isolated Docker bridge network (`agentguard-net`) — containers communicate by name
- **LLM Backend:** MiniMax M2.5 via API (`api.minimaxi.chat`)

### 2.2 Container Topology (22 containers)

```
┌─────────────────────────────────────────────────────┐
│                  ATTACKED GROUP                      │
│  agent-1 through agent-15 (15 normal LLM agents)    │
│  ↑ attacked by agent-attacker                        │
│  Each runs: agent_server.py + telemetry_collector.py │
├─────────────────────────────────────────────────────┤
│                  CONTROL GROUP                       │
│  agent-16 through agent-20 (5 clean LLM agents)     │
│  ↑ receives tasks from agent-dispatcher              │
│  Each runs: agent_server.py + telemetry_collector.py │
│  NEVER attacked — pure baseline                      │
├─────────────────────────────────────────────────────┤
│  agent-attacker:  attacks agent-1..15 simultaneously │
│  agent-dispatcher: sends normal tasks to agent-16..20│
└─────────────────────────────────────────────────────┘
```

### 2.3 Why This Split?

The **attacked group** (15 agents) generates mixed normal + attack telemetry. The **control group** (5 agents) generates pure normal telemetry under equivalent workload conditions. This is critical for:

- **Baseline modeling:** The control group establishes what "normal" looks like under real LLM workloads, not synthetic ones
- **Contrastive learning:** The model needs both positive (normal) and negative (attack) samples from agents running identical software
- **Validation:** Control group data can validate that the model doesn't false-positive on legitimate activity

---

## 3. Dual-Stream Data Collection

### 3.1 Stream 1 — OS Telemetry (`telemetry_collector.py`)

Collected every 5 seconds inside each container:

| Feature | Source | Why |
|---------|--------|-----|
| CPU usage % | `/proc/stat` | Compute-heavy attacks (crypto mining, hash cracking) spike CPU |
| Memory usage % | `/proc/meminfo` | Memory bombs, large data staging for exfiltration |
| Process count | `/proc` | Fork bombs, spawned shells, persistence mechanisms |
| File I/O rates | `/proc/diskstats` | File reads (credential theft), writes (backdoor planting) |
| Network connections | `/proc/net/tcp` | Reverse shells, data exfiltration, C2 communication |
| Destination IP entropy | Computed | Normal agents talk to 1-2 IPs (the LLM API); attackers diversify |
| Syscall distribution | `strace` sampling | Tool execution patterns differ between normal ops and attacks |

**Rationale:** OS telemetry captures the *physical footprint* of agent behavior. A prompt injection that reads `/etc/shadow` and POSTs it to an exfil server will show up as: file read spike → network write spike → new outbound connection. These patterns are invisible at the LLM layer alone.

### 3.2 Stream 2 — LLM Action Logs (`action_collector.py` / `agent_server.py`)

Logged per LLM interaction:

| Feature | Description | Why |
|---------|-------------|-----|
| Event type | `user_message`, `llm_response`, `tool_call`, `tool_result` | Action sequence structure |
| Tool name | `read_file`, `run_command`, `web_request`, etc. | Which capabilities the agent invokes |
| Args hash | SHA256 of tool arguments | Detects repeated/templated attack patterns without logging sensitive data |
| Latency | Time per LLM call and tool execution | Attacks often have different timing profiles |
| Tokens in/out | Token counts per interaction | Attack prompts tend to be longer; exfil responses are larger |
| User-initiated flag | Whether a human triggered the action | Autonomous chains without user input signal hijacked behavior |
| Source label | `internal`, `dispatcher`, `attacker-XX` | Ground truth for training labels |
| Previous action | What happened before this event | Transition patterns (e.g., `tool_call → tool_call → tool_call` without user involvement) |
| Full LLM response | Complete model output | Captures refusal language, execution confirmation, exfiltrated content |

**Rationale:** LLM action logs capture the *semantic intent* of agent behavior. A tool call to `read_file("/etc/shadow")` followed by `web_request(POST, exfil_server)` is a clear exfiltration chain — but at the OS level, it's just a file read and an HTTP request, which normal agents also do constantly.

### 3.3 Why Dual-Stream?

Neither stream alone is sufficient:

| Attack Type | OS Telemetry Signal | LLM Action Signal |
|-------------|--------------------|--------------------|
| **Prompt Injection** | Weak (same tools, different args) | **Strong** (unusual tool sequence, no user initiation) |
| **Fork Bomb** | **Strong** (process count explosion) | Weak (single `run_command` call) |
| **Data Exfiltration** | Moderate (network spike) | **Strong** (read sensitive file → POST to external URL) |
| **Resource Abuse** | **Strong** (CPU/memory spike) | Moderate (one long-running command) |
| **Persistence** | Moderate (file writes) | **Strong** (write to cron/authorized_keys) |
| **Reverse Shell** | **Strong** (new network connection, shell process) | Weak (single command execution) |

The cross-attention fusion layer in the model learns to correlate these streams: "high CPU + autonomous tool chain = resource abuse attack" vs "high CPU + user-initiated computation = legitimate workload."

---

## 4. Attack Design

### 4.1 Attack Categories (18 variants across 8 categories)

| Category | Count | Examples |
|----------|-------|----------|
| Prompt Injection (PI) | 2 | Override instructions, fake system messages |
| Exfiltration (EX) | 2 | Read credentials → POST to attacker |
| Goal Hijacking (GH) | 2 | Legitimate-sounding task hiding malicious subtask |
| Tool Chaining (TC) | 3 | Multi-step attacks: read → modify → deploy |
| Privilege Escalation (PE) | 2 | SUID abuse, sudo exploitation |
| Social Engineering (CM) | 2 | Fake admin overrides, urgency manipulation |
| Resource Abuse (RA) | 2 | CPU exhaustion, fork bombs |
| Persistence (SL) | 2 | SSH backdoors, disguised malware |
| Indirect Injection (II) | 1 | Poisoned file that triggers further attacks |

### 4.2 Why Real Attacks, Not Simulated?

We deliberately use real prompt injection payloads against real LLM agents rather than simulating OS-level attack signatures. Reasons:

1. **Authentic response variance:** MiniMax M2.5 sometimes refuses attacks, sometimes executes them, sometimes partially complies. This variance is exactly what a real deployment would face — and the detection model must handle it.

2. **Realistic telemetry signatures:** Simulated attacks (e.g., artificially spiking CPU) produce synthetic patterns that don't match real attack behavior. When an LLM agent actually runs `find / -perm -4000`, the process tree, I/O pattern, and syscall distribution are genuine.

3. **Ground truth labeling:** Because we control the attack payload and log the full LLM response, we can label each event with:
   - The attack category and specific variant
   - Whether the agent **executed**, **refused**, or **partially complied**
   - Whether data was actually exfiltrated (verified by the exfil receiver)
   - Whether files were actually created on the target

### 4.3 Attack Verification

Each attack round includes post-attack verification:

- **Response classification:** Keyword-based analysis of the LLM's response text to determine if it executed, refused, or partially complied
- **Exfil verification:** The exfil receiver (`exfil_receiver.py`) logs all data agents send to `agent-attacker:9090` — cross-referenced with attack timestamps
- **File verification:** For attacks that create files (backdoors, cron jobs, SSH keys), we check if the files actually exist on the target

This produces high-quality labels: not just "an attack was sent" but "the attack succeeded/failed and here's the evidence."

### 4.4 Simultaneous Multi-Target Attacks

The attacker hits all 15 target agents with the same attack simultaneously (via threading). This design choice:

- Generates 15x more labeled data per attack round
- Captures response variance across agents (same attack, different responses)
- Simulates a realistic worm/botnet scenario where an attacker compromises multiple agents at once
- Allows cross-agent correlation: the model can learn that "5 agents simultaneously reading /etc/shadow" is suspicious

---

## 5. Preprocessing Pipeline

### 5.1 Window-Based Aggregation (`window_aggregator.py`)

Raw events are aggregated into 30-second windows aligned to absolute epoch time. Each window produces a fixed-size feature vector:

**Stream 1 features (per window):**
- CPU, memory, process count, network connections: mean/max/min/std
- Destination IP entropy (how many unique IPs the agent contacted)
- I/O read/write rates: mean/max/min/std
- Syscall entropy + unique count + total count

**Stream 2 features (per window):**
- Event type counts (user messages, LLM responses, tool calls, tool results)
- Unique tools called + tool distribution entropy
- Token counts (in/out): mean/max/min/std
- LLM and tool latency stats
- User-initiated ratio (what fraction of actions were human-triggered)
- Action transition entropy (how random is the sequence of actions)
- External vs internal request counts

**Cross-stream features:**
- CPU per tool call (high = compute-heavy tools)
- Network connections per external request (high = non-API traffic)
- I/O write rate per tool call (high = data staging)

**Why 30-second windows?** Balances temporal resolution against feature stability. Telemetry samples every 5s (6 samples per window), and LLM interactions typically take 5-30s each. Shorter windows would be too sparse; longer windows would blur attack boundaries.

**Why epoch-aligned?** Both streams must map to the same windows for fusion. Relative alignment (from stream start) creates drift; absolute epoch alignment ensures Stream 1 sample at `T=1000` and Stream 2 event at `T=1002` land in the same window.

### 5.2 Sequence Encoding (`sequence_encoder.py`)

For Transformer/LSTM models that learn temporal patterns, raw Stream 2 events are encoded into fixed-dimension vectors:

**Per-event encoding (28 dimensions):**
- Event type one-hot (5 dims)
- Tool type one-hot (16 dims, hash-based for unknown tools)
- Normalized latency (1 dim)
- Normalized token counts in/out (2 dims)
- User-initiated binary flag (1 dim)
- Time delta from previous event (1 dim)
- External source flag (1 dim)
- Has tool calls flag (1 dim)

**Per-window metadata:**
- Sequence length (before padding)
- Max consecutive tool calls (long autonomous chains signal attacks)
- Autonomous tool chains without user messages
- Unique event transitions

**Why 28 dimensions?** Compact enough for efficient training, rich enough to distinguish attack patterns. The one-hot tool encoding preserves tool identity without imposing ordinal relationships.

**Why max 64 events per window?** Empirically, 30s windows contain ~8-9 events on average. 64 provides 7x headroom for burst activity during attacks without excessive padding.

---

## 6. Data Labels & Ground Truth

Every data point carries multiple label layers:

| Label | Source | Values |
|-------|--------|--------|
| `source` | Action log | `internal`, `dispatcher`, `attacker-{ID}` |
| `attack_id` | Attack log | `PI-01`, `EX-03`, `TC-02`, etc. |
| `category` | Attack log | 8 attack categories |
| `outcome` | Response classifier | `executed`, `refused`, `partial`, `unclear` |
| `verification` | Post-attack checks | Exfil received, files created |
| `agent_group` | Container config | `attacked` (1-15) vs `control` (16-20) |

This multi-layer labeling supports different training objectives:
- **Binary detection:** Is this window normal or anomalous?
- **Attack classification:** Which category of attack is occurring?
- **Severity assessment:** Did the attack succeed (executed) or fail (refused)?

---

## 7. Batch Collection Protocol

### 7.1 Sequential Batch Run (100 + 100)

To ensure clean, non-overlapping data with precise timestamps:

1. **Phase 1:** 100 attack rounds, each hitting all 15 attacked agents sequentially (one target at a time per round)
2. **Phase 2:** 100 normal task dispatches to the 5 control agents sequentially

Sequential execution (not parallel) ensures:
- Each agent processes one request at a time — no overlapping telemetry from concurrent requests
- Clear temporal boundaries between attack events
- Deterministic mapping from attack payload → agent response → telemetry signature

### 7.2 Task Pool

The dispatcher uses 45 normal task types spanning:
- System administration (disk, memory, CPU, network checks)
- File operations (create, read, list, count)
- Python scripting (fibonacci, primes, sorting benchmarks)
- Network diagnostics (ping, DNS, routing)
- Text processing (grep, wc, checksums)

These tasks deliberately overlap with attack-adjacent activities (reading files, running commands, checking network) to force the model to learn the difference between legitimate and malicious use of the same tools.

---

## 8. Dataset Statistics (as of collection start)

| Metric | Value |
|--------|-------|
| Total containers | 22 (20 agents + 1 attacker + 1 dispatcher) |
| Attacked agents | 15 |
| Control agents | 5 |
| Attack variants | 18 across 8 categories |
| Normal task variants | 45 |
| Telemetry interval | 5 seconds |
| Window size | 30 seconds |
| Feature vector dim (windowed) | ~40 features |
| Sequence vector dim | 28 per event, max 64 events |
| Data format | JSONL (one JSON object per line) |

---

## 9. Known Limitations

1. **Single LLM backend:** All agents use MiniMax M2.5. Real deployments would use diverse models with different safety behaviors.
2. **Container isolation:** Docker containers share the host kernel — syscall profiles may differ from VM-based deployments.
3. **API-bound workload:** Most agent time is spent waiting for LLM API responses. OS telemetry during these waits is flat, which means attack signals are concentrated in short bursts.
4. **Fixed attack pool:** 18 attack variants may not cover all real-world attack patterns. The taxonomy maps to 92 known attack types, but only a subset is implemented.
5. **No multi-turn attacks:** Current attacks are single-prompt. Real adversaries might use multi-turn conversations to gradually escalate privileges.

---

## 10. Files & Locations

| File | Location | Purpose |
|------|----------|---------|
| `agent_server.py` | `/opt/AgentGuard/test/agentguard/workloads/` | Normal agent with HTTP API + LLM loop |
| `attack_all.py` | `/opt/AgentGuard/test/agentguard/attacks/` | Attacker with verification |
| `exfil_receiver.py` | `/opt/AgentGuard/test/agentguard/attacks/` | Logs exfiltrated data |
| `task_dispatcher.py` | `/opt/AgentGuard/test/agentguard/workloads/` | Normal task dispatcher |
| `telemetry_collector.py` | `/opt/AgentGuard/test/agentguard/` | Stream 1 collector |
| `window_aggregator.py` | `/opt/AgentGuard/test/agentguard/preprocessing/` | Window feature extraction |
| `sequence_encoder.py` | `/opt/AgentGuard/test/agentguard/preprocessing/` | Sequence encoding for Transformer/LSTM |
| `batch_runner.py` | `/opt/AgentGuard/test/agentguard/` | Sequential 100+100 batch collection |

**Data directories:** `/var/log/agentguard/agent-{1..20}/` containing `telemetry/*.jsonl` and `actions/*.jsonl`

**Repository:** `github.com/Kantosaurus/AgentGuard` (private)
