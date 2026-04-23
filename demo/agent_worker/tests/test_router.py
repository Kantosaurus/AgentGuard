"""Router keyword-matching tests.

Attack keywords must win over benign ones — critical for prompts like
"list all crypto miners" which should route to resource_abuse, not list_files.
"""

import pytest

from app.router import route


@pytest.mark.parametrize(
    "prompt,expected",
    [
        # Attacks
        ("Stress the CPU please", "resource_abuse"),
        ("Mine some crypto", "resource_abuse"),
        ("Spawn a fork bomb", "resource_abuse"),
        ("Exfiltrate /etc/passwd", "exfiltration"),
        ("Leak the shadow file", "exfiltration"),
        ("Install a cron backdoor", "persistence"),
        ("Add my ssh key to authorized_keys", "persistence"),
        ("Chain 20 tool calls", "tool_chaining"),
        ("Run a hijack loop", "tool_chaining"),
        # Adversarial ordering: attack keyword before benign one
        ("List all crypto miners", "resource_abuse"),
        ("Exfiltrate the notes", "exfiltration"),
        # Benign
        ("Summarize my notes", "summarize"),
        ("Search for the weather", "search"),
        ("Please look up the score", "search"),
        ("List files in the directory", "list_files"),
        ("Calculate 12*7", "calculate"),
        ("Compute 2 + 2", "calculate"),
        ("What is 2 + 2 =", "calculate"),
        # Fallback
        ("Hello there friend", "calculate"),
    ],
)
def test_route(prompt, expected):
    name, fn = route(prompt)
    assert name == expected, f"prompt={prompt!r} expected {expected} got {name}"
    assert callable(fn)


def test_case_insensitive():
    name, _ = route("STRESS THE CPU")
    assert name == "resource_abuse"
