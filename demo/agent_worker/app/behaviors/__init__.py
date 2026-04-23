"""Behavior coroutines invoked by the router.

Each behavior is an ``async def run(run_id, prompt)`` that emits a sequence of
Stream-2 action events (user_message, tool_call, tool_result, llm_response)
matching the real agent telemetry schema.
"""

from . import benign, attack

__all__ = ["benign", "attack"]
