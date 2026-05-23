"""Calc — safe arithmetic-expression evaluator.

Walks the Python AST manually so the evaluator can never call ``eval()``
or import code. Supports the four operations, ``**``, ``%``, ``//``,
unary minus/plus, and a small allow-list of math functions.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from typing import TYPE_CHECKING, Any

from ibid.plugin import Plugin, command, match

if TYPE_CHECKING:
    from ibid.event import Event

_BIN_OPS: dict[type[ast.AST], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type[ast.AST], Any] = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}
_FUNCS: dict[str, Any] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "floor": math.floor,
    "ceil": math.ceil,
}
_CONSTANTS: dict[str, float] = {"pi": math.pi, "e": math.e, "tau": math.tau}


class CalcError(ValueError):
    pass


def safe_eval(expr: str) -> float:
    """Evaluate a numeric expression, raising :class:`CalcError` on misuse."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise CalcError(f"can't parse: {exc.msg}") from exc
    return _walk(tree.body)


def _walk(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise CalcError(f"unsupported constant: {node.value!r}")
    if isinstance(node, ast.BinOp):
        op_t = type(node.op)
        if op_t not in _BIN_OPS:
            raise CalcError(f"unsupported operator: {op_t.__name__}")
        left = _walk(node.left)
        right = _walk(node.right)
        try:
            return float(_BIN_OPS[op_t](left, right))
        except ZeroDivisionError as exc:
            raise CalcError("division by zero") from exc
    if isinstance(node, ast.UnaryOp):
        uop_t = type(node.op)
        if uop_t not in _UNARY_OPS:
            raise CalcError(f"unsupported unary: {uop_t.__name__}")
        return float(_UNARY_OPS[uop_t](_walk(node.operand)))
    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise CalcError(f"unknown name: {node.id}")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise CalcError("functions are restricted to abs, round, sqrt, log, sin, ...")
        if node.keywords:
            raise CalcError("keyword arguments not supported")
        args = [_walk(a) for a in node.args]
        return float(_FUNCS[node.func.id](*args))
    raise CalcError(f"unsupported syntax: {type(node).__name__}")


# ``5+3`` style — accept anything that doesn't have letters except function names.
_CALC_RE = re.compile(r"^[\d\s+\-*/().,%^a-z_]+$")


class Calc(Plugin):
    name = "calc"

    @command("calc", "math")
    async def calc(self, event: Event, args: str) -> None:
        """calc <expression> — safely evaluate an arithmetic expression."""
        expr = args.strip().replace("^", "**")
        if not expr:
            await event.reply("usage: calc <expression>")
            return
        try:
            result = safe_eval(expr)
        except CalcError as exc:
            await event.reply(f"calc: {exc}")
            return
        # Show integers as integers.
        if isinstance(result, float) and result.is_integer():
            await event.reply(f"{int(result)}")
        else:
            await event.reply(f"{result}")


# Also auto-fire on messages like ``5 + 3`` when addressed.
class CalcAuto(Plugin):
    name = "calc-auto"

    @match(r"^\s*[\d.][\d\s+\-*/().,%^]*$", addressed=True)
    async def fire(self, event: Event, _m: re.Match[str]) -> None:
        expr = event.text.strip().replace("^", "**")
        if not _CALC_RE.match(expr):
            return
        try:
            result = safe_eval(expr)
        except CalcError:
            return
        if isinstance(result, float) and result.is_integer():
            await event.reply(f"{int(result)}")
        else:
            await event.reply(f"{result}")


PLUGINS = [Calc, CalcAuto]
