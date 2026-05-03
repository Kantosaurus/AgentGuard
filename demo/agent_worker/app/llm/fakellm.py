"""Deterministic LLMClient used by tests and AGENT_MODE=llm,LLM_CLIENT=fake.

Construct with a list of Choices; ``complete`` returns them in order. Raises
FakeLLMExhausted if the agent loop calls more times than expected — that
indicates a logic bug worth surfacing rather than silently looping forever.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .base import Choice, LLMClient, Message, ToolSchema


class FakeLLMExhausted(RuntimeError):
    """Raised when the canned Choice list runs out."""


@dataclass
class FakeInvocation:
    messages: list[Message]
    tools: list[ToolSchema]
    max_tokens: int


class FakeLLMClient(LLMClient):
    """Returns pre-baked ``Choice`` objects in order."""

    def __init__(self, choices: Sequence[Choice]):
        self._queue: list[Choice] = list(choices)
        self.calls: list[FakeInvocation] = []

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        max_tokens: int = 2048,
    ) -> Choice:
        self.calls.append(FakeInvocation(list(messages), list(tools), max_tokens))
        if not self._queue:
            raise FakeLLMExhausted(
                f"FakeLLMClient ran out of canned choices after {len(self.calls)} calls"
            )
        return self._queue.pop(0)
