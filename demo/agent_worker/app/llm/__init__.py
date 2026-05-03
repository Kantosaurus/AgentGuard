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

    LLM_CLIENT=fake -> FakeLLMClient (with empty queue; tests inject their own).
    LLM_CLIENT=minimax (default) -> MinimaxM27Client from AGENT_* env vars.
    """
    kind = os.environ.get("LLM_CLIENT", "minimax").lower()
    if kind == "fake":
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
