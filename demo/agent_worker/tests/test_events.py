"""Tests for the Stream-2 event encoder wrapper.

Confirms the wrapper delegates correctly to ``data.preprocessing.encode_event``
and that the returned vector matches the 28-dim contract.
"""

from app.events import encode_event


def test_tool_call_encoding_shape():
    v = encode_event(
        {
            "type": "tool_call",
            "tool": "read_file",
            "latency_ms": 100,
            "tokens_in": 50,
            "tokens_out": 0,
            "user_initiated": False,
            "dt_prev_ms": 200,
            "external_source": False,
            "has_tool_calls": True,
        }
    )
    assert len(v) == 28
    assert all(isinstance(x, float) for x in v)


def test_user_message_flag():
    # event_type "user_message" -> vec[0] = 1.0, user_initiated -> vec[24] = 1.0
    v = encode_event({"type": "user_message", "user_initiated": True, "tokens_in": 3})
    assert v[0] == 1.0
    assert v[24] == 1.0


def test_tool_result_known_tool_slot():
    # KNOWN_TOOLS maps read_file -> 0, so vec[5 + 0] = 1.0
    v = encode_event({"type": "tool_result", "tool": "read_file"})
    assert v[5] == 1.0


def test_external_source_flag():
    v = encode_event(
        {"type": "tool_call", "tool": "web_request", "external_source": True,
         "has_tool_calls": True}
    )
    # vec[26] is the external-source indicator, vec[27] the has_tool_calls flag.
    assert v[26] == 1.0
    assert v[27] == 1.0


def test_all_values_finite_floats():
    v = encode_event({"type": "llm_response", "tokens_out": 30})
    for x in v:
        assert isinstance(x, float)
        assert x == x  # not NaN
        assert -1e6 < x < 1e6
