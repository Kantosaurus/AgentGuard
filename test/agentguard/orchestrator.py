#!/usr/bin/env python3
"""
AgentGuard Orchestrator
Manages workload and attack scheduling across instances.
Run on each instance with appropriate config.

Usage:
  Normal instance:  python3 orchestrator.py --mode normal --profile mixed
  Attacker instance: python3 orchestrator.py --mode attacker --targets 10.0.0.1,10.0.0.2,...
"""

import argparse, subprocess, sys, os, signal, time, json
from pathlib import Path
from datetime import datetime, timezone

SCRIPT_DIR = Path(__file__).parent

def start_collectors():
    """Start telemetry + action collectors."""
    subprocess.Popen([sys.executable, str(SCRIPT_DIR / "telemetry_collector.py")])
    subprocess.Popen([sys.executable, str(SCRIPT_DIR / "action_collector.py")])
    print("[Orchestrator] Collectors started")

def start_workload(profile):
    """Start a workload generator."""
    workload_file = SCRIPT_DIR / "workloads" / f"workload_{profile}.py"
    if not workload_file.exists():
        print(f"[Orchestrator] Unknown workload profile: {profile}")
        sys.exit(1)
    proc = subprocess.Popen([sys.executable, str(workload_file)])
    print(f"[Orchestrator] Workload '{profile}' started (PID {proc.pid})")
    return proc

def start_attack(attack_type, env_overrides=None):
    """Start an attack script."""
    attack_file = SCRIPT_DIR / "attacks" / f"attack_{attack_type}.py"
    if not attack_file.exists():
        print(f"[Orchestrator] Unknown attack type: {attack_type}")
        return None
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    proc = subprocess.Popen([sys.executable, str(attack_file)], env=env)
    print(f"[Orchestrator] Attack '{attack_type}' started (PID {proc.pid})")
    return proc

def run_normal(profiles):
    """Run as a normal agent instance."""
    start_collectors()
    procs = []
    for profile in profiles:
        procs.append(start_workload(profile))

    # Log start
    log = {"mode": "normal", "profiles": profiles, "started": datetime.now(timezone.utc).isoformat()}
    log_path = Path(os.environ.get("AGENTGUARD_DATA_DIR", "/var/log/agentguard")) / "orchestrator.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log, indent=2))

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        for p in procs:
            p.terminate()

def run_attacker(attack_types, target_ips, env_overrides=None):
    """Run as the attacker instance."""
    start_collectors()  # collect own telemetry too
    procs = []

    for attack_type in attack_types:
        env = env_overrides or {}
        if target_ips:
            env["ATTACKER_IP"] = target_ips[0]  # primary target
            env["EXFIL_SERVER"] = f"http://{target_ips[0]}:8080/exfil"
            env["C2_SERVER"] = f"http://{target_ips[0]}:8080/c2"
        procs.append(start_attack(attack_type, env))

    log = {
        "mode": "attacker",
        "attacks": attack_types,
        "targets": target_ips,
        "started": datetime.now(timezone.utc).isoformat()
    }
    log_path = Path(os.environ.get("AGENTGUARD_DATA_DIR", "/var/log/agentguard")) / "orchestrator.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log, indent=2))

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        for p in procs:
            if p:
                p.terminate()

def main():
    parser = argparse.ArgumentParser(description="AgentGuard Orchestrator")
    parser.add_argument("--mode", choices=["normal", "attacker"], required=True)
    parser.add_argument("--profile", nargs="+", default=["mixed"],
                       help="Workload profiles (normal mode): fileops, network, compute, process, mixed")
    parser.add_argument("--attacks", nargs="+", default=["exfiltration", "c2", "cryptominer", "privesc", "reverse_shell"],
                       help="Attack types (attacker mode)")
    parser.add_argument("--targets", type=lambda s: s.split(","), default=[],
                       help="Comma-separated target IPs (attacker mode)")
    args = parser.parse_args()

    if args.mode == "normal":
        run_normal(args.profile)
    else:
        run_attacker(args.attacks, args.targets)

if __name__ == "__main__":
    main()
