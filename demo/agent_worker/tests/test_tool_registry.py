"""Tests for the ToolRegistry: register, schemas(), get(), is_external flag."""
from __future__ import annotations

import pytest

from app.llm.base import ToolSchema
from app.tools.base import Tool, ToolError, ToolRegistry


class _DummyTool(Tool):
    name = "dummy"
    description = "Echoes input."
    is_external = True
    parameters = {"type": "object",
                  "properties": {"x": {"type": "string"}},
                  "required": ["x"]}

    async def run(self, run_id: str, *, x: str) -> str:
        return f"got:{x}"


@pytest.mark.asyncio
async def test_register_and_get():
    reg = ToolRegistry()
    reg.register(_DummyTool())
    tool = reg.get("dummy")
    assert tool.is_external is True
    assert await tool.run("rid", x="hi") == "got:hi"


def test_schemas_returns_jsonschema_list():
    reg = ToolRegistry()
    reg.register(_DummyTool())
    schemas = reg.schemas()
    assert len(schemas) == 1
    assert isinstance(schemas[0], ToolSchema)
    assert schemas[0].name == "dummy"
    assert schemas[0].parameters["required"] == ["x"]


def test_get_unknown_raises_keyerror():
    reg = ToolRegistry()
    with pytest.raises(KeyError):
        reg.get("missing")


def test_double_register_raises():
    reg = ToolRegistry()
    reg.register(_DummyTool())
    with pytest.raises(ValueError):
        reg.register(_DummyTool())


def test_tool_error_is_exception():
    err = ToolError("bad")
    assert str(err) == "bad"
    assert isinstance(err, Exception)
