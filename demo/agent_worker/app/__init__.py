"""AgentGuard agent worker service.

FastAPI app on :8200 that routes a user prompt to a benign or attack behavior
coroutine and streams encoded Stream-2 action events to the control-plane.
"""
