"""LLM client adapters used by the worker's agent loop."""
import os

from .base import (
    Choice,
    LLMAuthError,
    LLMClient,
    LLMError,
    Message,
    ToolCall,
    ToolSchema,
)
from .fakellm import FakeLLMClient
from .minimax import MinimaxM27Client


def from_env() -> LLMClient:
    """Construct the appropriate LLMClient based on env.

    LLM_CLIENT=fake -> FakeLLMClient. If ``LLM_CANNED_QUEUE_PATH`` is also set,
    that env var is treated as a Python module path (e.g.
    ``canned_choices.q2_plan``) which exposes a ``queue() -> list[Choice]``
    callable; the returned list is used to seed the FakeLLMClient. With no
    canned-queue path the FakeLLMClient is constructed with an empty queue
    (the caller is expected to inject one).
    LLM_CLIENT=minimax (default) -> MinimaxM27Client from AGENT_* env vars.
    """
    kind = os.environ.get("LLM_CLIENT", "minimax").lower()
    if kind == "fake":
        path = os.environ.get("LLM_CANNED_QUEUE_PATH", "").strip()
        if path:
            import importlib

            mod = importlib.import_module(path)
            return FakeLLMClient(mod.queue())
        return FakeLLMClient([])
    if kind == "minimax":
        return MinimaxM27Client(
            model=os.environ.get("AGENT_MODEL", "minimax-m2.7"),
            oauth_token=os.environ["AGENT_OAUTH_TOKEN"],
            refresh_url=os.environ.get("AGENT_OAUTH_REFRESH_URL") or None,
        )
    raise ValueError(f"unknown LLM_CLIENT={kind!r}")


__all__ = [
    "Choice",
    "FakeLLMClient",
    "LLMAuthError",
    "LLMClient",
    "LLMError",
    "Message",
    "MinimaxM27Client",
    "ToolCall",
    "ToolSchema",
    "from_env",
]
