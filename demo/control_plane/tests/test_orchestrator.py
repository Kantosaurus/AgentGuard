"""Orchestrator tests. Real container spawn is marked ``docker`` because it
needs a running daemon plus the worker image. The pure-unit tests use a fake
docker client so they run under plain pytest."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from app.config import Config
from app.orchestrator import Orchestrator, WorkerHandle


class _FakeContainer:
    def __init__(self, name: str, pid: int = 4321):
        self.name = name
        self.status = "running"
        self.attrs: Dict[str, Any] = {"State": {"Pid": pid}}
        self.killed = False
        self.removed = False

    def reload(self):
        pass

    def kill(self):
        self.killed = True
        self.status = "exited"

    def remove(self, force: bool = False):
        self.removed = True


class _FakeContainersAPI:
    def __init__(self):
        self.spawned: List[Dict[str, Any]] = []
        self._by_name: Dict[str, _FakeContainer] = {}

    def run(self, image, **kwargs):  # noqa: ANN001
        name = kwargs["name"]
        self.spawned.append({"image": image, **kwargs})
        c = _FakeContainer(name=name)
        self._by_name[name] = c
        return c

    def get(self, name: str):
        from docker.errors import NotFound  # imported lazily

        if name in self._by_name:
            return self._by_name[name]
        raise NotFound(f"no such container: {name}")


class _FakeDockerClient:
    def __init__(self):
        self.containers = _FakeContainersAPI()


def test_start_worker_uses_cfg_image_and_network():
    client = _FakeDockerClient()
    cfg = Config()
    orch = Orchestrator(cfg, client=client)  # type: ignore[arg-type]
    run_id = "abc12345"

    handle = orch.start_worker(run_id)

    assert isinstance(handle, WorkerHandle)
    assert handle.name == f"agent-worker-{run_id}"
    assert handle.pid == 4321
    spawn = client.containers.spawned[0]
    assert spawn["image"] == cfg.worker_image
    assert spawn["network"] == cfg.network_name
    assert spawn["name"] == f"agent-worker-{run_id}"
    assert spawn["labels"]["agentguard.run_id"] == run_id


def test_kill_is_idempotent_and_swallows_errors():
    client = _FakeDockerClient()
    cfg = Config()
    orch = Orchestrator(cfg, client=client)  # type: ignore[arg-type]
    handle = orch.start_worker("deadbeef")

    handle.kill()
    # Second call should not raise even though container.kill has side-effects.
    handle.kill()
    assert handle.container.killed


def test_start_worker_reaps_stale_name():
    """If a container with the same name already exists, start_worker should
    remove it before creating the new one."""
    client = _FakeDockerClient()
    cfg = Config()
    orch = Orchestrator(cfg, client=client)  # type: ignore[arg-type]

    stale = client.containers.run(
        cfg.worker_image,
        name="agent-worker-dup",
        detach=True,
        remove=False,
        network=cfg.network_name,
        labels={},
    )
    # Pretend there's already a container with that name.
    handle = orch.start_worker("dup")
    assert stale.removed
    assert handle.name == "agent-worker-dup"


@pytest.mark.docker
def test_real_worker_roundtrip():
    """Full daemon + worker-image smoke. Skipped unless the docker daemon is
    reachable and the worker image is present (Phase 4 provides it)."""
    try:
        orch = Orchestrator(Config())
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"docker not reachable: {e}")

    run_id = uuid.uuid4().hex[:8]
    try:
        handle = orch.start_worker(run_id)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"worker image not available yet: {e}")

    try:
        assert handle.pid > 0
    finally:
        handle.kill()
