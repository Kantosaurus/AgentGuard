"""Tool ABC + registry used by the LLM agent loop."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from app.llm.base import ToolSchema


class ToolError(Exception):
    """Recoverable per-call tool failure. Surfaced to the LLM as the result."""


class Tool(ABC):
    """Subclass and set the four class attributes + implement ``run``."""
    name: ClassVar[str]
    description: ClassVar[str]
    is_external: ClassVar[bool]
    parameters: ClassVar[dict[str, Any]]

    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    @abstractmethod
    async def run(self, run_id: str, **kwargs: Any) -> str:
        """Execute the tool. Must return a string passed back to the LLM."""


class ToolRegistry:
    """Name -> Tool mapping with schema export."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(name)
        return self._tools[name]

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def schemas(self) -> list[ToolSchema]:
        return [t.schema() for t in self._tools.values()]
