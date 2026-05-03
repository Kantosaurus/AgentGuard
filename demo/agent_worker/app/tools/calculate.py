"""Bounded arithmetic expression evaluator (no name lookup, no calls)."""
from __future__ import annotations

import ast
import operator
from typing import Any

from .base import Tool

_BIN_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval(node.operand))
    raise ValueError(f"unsupported expr: {ast.dump(node)}")


class Calculate(Tool):
    name = "calculate"
    description = "Evaluate a numeric arithmetic expression."
    is_external = False
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"expr": {"type": "string"}},
        "required": ["expr"],
    }

    async def run(self, run_id: str, *, expr: str) -> str:
        try:
            tree = ast.parse(expr, mode="eval")
            result = _eval(tree.body)
        except (SyntaxError, ValueError, ZeroDivisionError) as e:
            return f"error: {e}"
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        return str(result)
