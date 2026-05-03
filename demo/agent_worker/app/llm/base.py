"""LLMClient abstract base + the shared dataclasses every adapter returns.

The agent loop only ever sees these types; provider-specific quirks live in
the adapter modules (minimax.py, fakellm.py).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence


class LLMError(Exception):
    """Base class for LLM adapter failures."""


class LLMAuthError(LLMError):
    """Raised when the OAuth token is rejected and cannot be refreshed."""


@dataclass
class Message:
    """One chat message. ``role`` follows the OpenAI taxonomy."""
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class ToolCall:
    """A single tool invocation parsed out of an LLM response."""
    id: str
    name: str
    args: dict[str, Any]
    latency_ms: float = 0.0


@dataclass
class Choice:
    """The single returned choice from an LLM completion."""
    finish_reason: Literal["stop", "tool_calls", "length"]
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class ToolSchema:
    """JSONSchema for a single tool, in a provider-neutral shape."""
    name: str
    description: str
    parameters: dict[str, Any]

    def to_openai_dict(self) -> dict[str, Any]:
        """Render in OpenAI/MiniMax `tools[]` shape."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class LLMClient(ABC):
    """Provider-neutral chat-completions interface."""

    @abstractmethod
    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        max_tokens: int = 2048,
    ) -> Choice:
        """Run one inference round."""
