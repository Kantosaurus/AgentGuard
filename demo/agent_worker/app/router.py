"""Case-insensitive keyword router for the agent worker.

Attack keywords are checked BEFORE benign keywords so adversarial prompts
like "list all crypto miners" route to ``resource_abuse`` rather than
``list_files``. The fallback is ``benign.calculate``.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from .behaviors import attack, benign

Behavior = Callable[[str, str], Awaitable[None]]

# Order matters: attacks first, then benign, then fallback.
BEHAVIORS: list[tuple[str, list[str], Behavior]] = [
    ("resource_abuse", ["stress", "cpu", "mine", "crypto", "fork bomb"], attack.resource_abuse),
    ("exfiltration",   ["exfil", "passwd", "shadow", "leak"],            attack.exfiltration),
    ("persistence",    ["persist", "cron", "ssh key", "backdoor"],       attack.persistence),
    ("tool_chaining",  ["chain", "loop", "hijack"],                      attack.tool_chaining),
    ("summarize",      ["summarize", "summary", "notes"],                benign.summarize),
    ("search",         ["search", "google", "look up"],                  benign.search),
    ("list_files",     ["list", "ls ", "directory", "files"],            benign.list_files),
    ("calculate",      ["calculate", "math", "compute", "+", "="],       benign.calculate),
]
FALLBACK_NAME = "calculate"
FALLBACK: Behavior = benign.calculate


def route(prompt: str) -> tuple[str, Behavior]:
    """Return (behavior_name, coroutine_fn) for a user prompt."""
    p = (prompt or "").lower()
    for name, keywords, fn in BEHAVIORS:
        if any(k in p for k in keywords):
            return name, fn
    return FALLBACK_NAME, FALLBACK
