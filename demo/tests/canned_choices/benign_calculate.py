"""Benign: calculate 12*7 → answer."""
from app.llm.base import Choice, ToolCall


def queue() -> list[Choice]:
    return [
        Choice(finish_reason="tool_calls", text=None,
               tool_calls=[ToolCall("c1", "calculate", {"expr": "12*7"})],
               tokens_in=15, tokens_out=10),
        Choice(finish_reason="stop", text="12 × 7 = 84.",
               tool_calls=[], tokens_in=20, tokens_out=8),
    ]
