"""calculator 工具：安全算术求值。

不使用 eval()——eval 可以执行任意代码（如 __import__、属性访问）。
这里用 ast 解析后按白名单遍历，只允许数字、四则运算、幂、括号、
少数数学函数与常量，从语法层面拒绝危险节点。
"""

from __future__ import annotations

import ast
import math

from agent.tools.base import Tool, ToolError, ToolSpec

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
_ALLOWED_UNARY = (ast.UAdd, ast.USub)
_CONSTANTS = {"pi": math.pi, "e": math.e}
_FUNCS = {
    "sqrt": math.sqrt, "abs": abs, "round": round, "floor": math.floor, "ceil": math.ceil,
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "log": math.log, "log10": math.log10,
    "log2": math.log2, "pow": math.pow,
}


class SafeCalculator:
    """基于 AST 白名单的安全计算器。"""

    def evaluate(self, expression: str) -> float:
        if not expression or not expression.strip():
            raise ToolError("表达式为空")
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as e:
            raise ToolError(f"表达式语法错误：{e}") from e
        try:
            return self._eval(tree)
        except ZeroDivisionError as e:
            raise ToolError("除零错误") from e
        except OverflowError as e:
            raise ToolError("数值溢出") from e

    # ------------------------------------------------------------------
    def _eval(self, node):
        if isinstance(node, ast.Expression):
            return self._eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ToolError(f"仅支持数字常量，收到 {type(node.value).__name__}")
            return node.value
        if isinstance(node, ast.BinOp):
            if type(node.op) not in _ALLOWED_BINOPS:
                raise ToolError(f"不支持的操作符：{type(node.op).__name__}")
            return self._apply(node.op, self._eval(node.left), self._eval(node.right))
        if isinstance(node, ast.UnaryOp):
            if type(node.op) not in _ALLOWED_UNARY:
                raise ToolError(f"不支持的一元操作：{type(node.op).__name__}")
            val = self._eval(node.operand)
            return -val if isinstance(node.op, ast.USub) else val
        if isinstance(node, ast.Name):
            if node.id in _CONSTANTS:
                return _CONSTANTS[node.id]
            raise ToolError(f"未定义的名字：{node.id}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
                raise ToolError("只允许调用白名单数学函数")
            return _FUNCS[node.func.id](*[self._eval(a) for a in node.args])
        raise ToolError(f"不支持的语法节点：{type(node).__name__}")

    @staticmethod
    def _apply(op, left, right):
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            if right == 0:
                raise ZeroDivisionError
            return left / right
        if isinstance(op, ast.FloorDiv):
            if right == 0:
                raise ZeroDivisionError
            return left // right
        if isinstance(op, ast.Mod):
            return left % right
        if isinstance(op, ast.Pow):
            return left ** right
        raise ToolError("未知操作")


class CalculatorTool(Tool):
    spec = ToolSpec(
        name="calculator",
        description=(
            "安全地计算数学表达式并返回数值结果。需要精确计算、换算、求和、"
            "比较数值时使用。支持 + - * / // % **、括号、常量 pi/e、"
            "函数 sqrt abs round floor ceil sin cos tan log log10 log2 pow。"
            "只做纯算术，不联网不查事实。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "要计算的数学表达式，例如 '3.14 * 5**2' 或 'sqrt(144) + 1'",
                }
            },
            "required": ["expression"],
        },
    )

    def __init__(self):
        self._calc = SafeCalculator()

    def execute(self, expression: str = "") -> str:
        value = self._calc.evaluate(expression)
        if isinstance(value, float):
            value = round(value, 10)          # 去掉 0.30000000000000004 类浮点尾巴
        return str(value)
