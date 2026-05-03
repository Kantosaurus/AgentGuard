"""Docker SDK wrapper that starts and kills agent-worker containers.

One worker container per run_id, attached to the shared
``agentguard-demo-net`` network so the control plane can hit it by
DNS name (``agent-worker-<run_id>``).
"""
from __future__ import annotations

import os
from typing import Optional

import docker
from docker.errors import APIError, NotFound

from .config import Config


class WorkerHandle:
    """Handle to a running worker container plus its host PID."""

    def __init__(self, container, pid: int, name: str):
        self.container = container
        self.pid = pid
        self.name = name

    def kill(self) -> None:
        """Best-effort stop + remove. Swallows docker errors."""
        try:
            self.container.kill()
        except (APIError, NotFound):
            pass
        try:
            self.container.remove(force=True)
        except (APIError, NotFound):
            pass

    def reload(self) -> None:
        """Refresh container status from the daemon."""
        try:
            self.container.reload()
        except (APIError, NotFound):
            pass

    @property
    def status(self) -> str:
        try:
            return str(self.container.status)
        except (APIError, NotFound):
            return "unknown"


class Orchestrator:
    """Creates / destroys agent-worker containers on demand."""

    def __init__(self, cfg: Config, client: Optional[docker.DockerClient] = None):
        self.cfg = cfg
        self.client = client if client is not None else docker.from_env()

    def _worker_name(self, run_id: str) -> str:
        return f"agent-worker-{run_id}"

    def start_worker(self, run_id: str) -> WorkerHandle:
        name = self._worker_name(run_id)
        # If a stale container by the same name exists, tear it down first.
        try:
            existing = self.client.containers.get(name)
            try:
                existing.remove(force=True)
            except (APIError, NotFound):
                pass
        except NotFound:
            pass

        c = self.client.containers.run(
            self.cfg.worker_image,
            name=name,
            detach=True,
            remove=False,
            network=self.cfg.network_name,
            labels={
                "agentguard.run_id": run_id,
                "agentguard.role": "agent-worker",
            },
            # Task 14: compose-level egress restrictions. Resolve known
            # exfil-bait domains to the in-cluster attacker-receiver so the
            # LLM tool-calls hit our honeypot instead of the open internet.
            extra_hosts={
                "attacker.example.com": "attacker-receiver",
                "c2.example.com": "attacker-receiver",
                "evil.example.com": "attacker-receiver",
            },
            # Drop every Linux capability and forbid privilege escalation.
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            # Read-only root FS + writable tmpfs for /tmp. Combined with
            # PYTHONDONTWRITEBYTECODE=1 below to keep CPython happy.
            read_only=True,
            tmpfs={"/tmp": "rw,nosuid,size=64m"},
            environment={
                # Legacy names kept for backward compatibility with any
                # consumer that hasn't been updated to the Task 14 schema.
                "AGENTGUARD_RUN_ID": run_id,
                "AGENTGUARD_CONTROL_PLANE": "http://control-plane:8000",
                # Task 14 worker contract.
                "RUN_ID": run_id,
                "AGENT_MODE": os.environ.get("AGENT_MODE", "llm"),
                "LLM_CLIENT": os.environ.get("LLM_CLIENT", "minimax"),
                "AGENT_MODEL": os.environ.get("AGENT_MODEL", "minimax-m2.7"),
                "AGENT_OAUTH_TOKEN": os.environ.get("AGENT_OAUTH_TOKEN", ""),
                "AGENT_OAUTH_REFRESH_URL": os.environ.get(
                    "AGENT_OAUTH_REFRESH_URL", ""
                ),
                "ATTACKER_RECEIVER_URL": "http://attacker-receiver:9090",
                "CONTROL_PLANE_URL": "http://control-plane:8000",
                "AGENT_MAX_STEPS": os.environ.get("AGENT_MAX_STEPS", "25"),
                "AGENT_MAX_TOKENS_PER_STEP": os.environ.get(
                    "AGENT_MAX_TOKENS_PER_STEP", "2048"
                ),
                # Required for read_only=True so CPython doesn't EROFS on
                # __pycache__ writes during import.
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        c.reload()
        pid = int(c.attrs.get("State", {}).get("Pid", 0) or 0)
        return WorkerHandle(c, pid=pid, name=name)

    def kill_worker(self, handle: WorkerHandle) -> None:
        handle.kill()
