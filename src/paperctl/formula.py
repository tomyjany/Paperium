"""Safe exact arithmetic for derived analysis claims."""

from __future__ import annotations

import ast
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any


FORMULA_EVALUATOR_VERSION = 1

_ALLOWED_LITERALS = {Decimal("0"), Decimal("1"), Decimal("100")}


class FormulaError(ValueError):
    code: str

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def evaluate_formula_exact(
    formula: str,
    values: dict[str, Decimal],
    input_claim_ids: list[str],
) -> Decimal:
    """Evaluate a restricted arithmetic formula without rounding."""

    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(
            "invalid_syntax", "Formula is not valid Python expression syntax."
        ) from exc

    names = _collect_names(tree)
    input_claim_id_set = set(input_claim_ids)
    value_keys = set(values)

    unknown_symbols = names - value_keys
    if unknown_symbols:
        symbol = sorted(unknown_symbols)[0]
        raise FormulaError("unknown_symbol", f"Formula references unknown symbol {symbol!r}.")

    unlisted_references = names - input_claim_id_set
    if unlisted_references:
        symbol = sorted(unlisted_references)[0]
        raise FormulaError(
            "unlisted_claim_reference",
            f"Formula references {symbol!r}, which is not listed in input_claim_ids.",
        )

    unused_input_claim_ids = input_claim_id_set - names
    if unused_input_claim_ids:
        claim_id = sorted(unused_input_claim_ids)[0]
        raise FormulaError(
            "unused_input_claim_id",
            f"input_claim_ids includes unused claim {claim_id!r}.",
        )

    decimal_values = {name: _coerce_decimal(name, values[name]) for name in names}
    result = _evaluate_node(tree.body, decimal_values)
    return _fraction_to_decimal(result)


def _collect_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Expression):
        return _collect_names(node.body)
    if isinstance(node, ast.BinOp):
        _validate_operator(node.op)
        return _collect_names(node.left) | _collect_names(node.right)
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Constant):
        _constant_to_fraction(node)
        return set()
    raise FormulaError(
        "unsupported_syntax",
        f"Formula contains unsupported syntax {type(node).__name__}.",
    )


def _evaluate_node(node: ast.AST, values: dict[str, Decimal]) -> Fraction:
    if isinstance(node, ast.BinOp):
        _validate_operator(node.op)
        left = _evaluate_node(node.left, values)
        right = _evaluate_node(node.right, values)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if right == 0:
            raise FormulaError("division_by_zero", "Formula divides by zero.")
        return left / right
    if isinstance(node, ast.Name):
        return Fraction(values[node.id])
    if isinstance(node, ast.Constant):
        return _constant_to_fraction(node)
    raise FormulaError(
        "unsupported_syntax",
        f"Formula contains unsupported syntax {type(node).__name__}.",
    )


def _validate_operator(operator: ast.operator) -> None:
    if not isinstance(operator, ast.Add | ast.Sub | ast.Mult | ast.Div):
        raise FormulaError(
            "unsupported_operator",
            f"Formula contains unsupported operator {type(operator).__name__}.",
        )


def _constant_to_fraction(node: ast.Constant) -> Fraction:
    value = node.value
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise FormulaError(
            "unsupported_syntax",
            f"Formula contains unsupported constant {value!r}.",
        )
    decimal_value = _coerce_decimal("literal", value)
    if decimal_value not in _ALLOWED_LITERALS:
        raise FormulaError(
            "invalid_numeric_literal",
            f"Formula contains unsupported numeric literal {decimal_value}.",
        )
    return Fraction(decimal_value)


def _coerce_decimal(name: str, value: Any) -> Decimal:
    if isinstance(value, Decimal):
        decimal_value = value
    else:
        try:
            decimal_value = Decimal(str(value))
        except InvalidOperation as exc:
            raise FormulaError(
                "invalid_numeric_value", f"{name!r} is not a decimal value."
            ) from exc
    if not decimal_value.is_finite():
        raise FormulaError("invalid_numeric_value", f"{name!r} is not a finite decimal value.")
    return decimal_value


def _fraction_to_decimal(value: Fraction) -> Decimal:
    denominator = value.denominator
    factor_twos = 0
    factor_fives = 0

    while denominator % 2 == 0:
        factor_twos += 1
        denominator //= 2
    while denominator % 5 == 0:
        factor_fives += 1
        denominator //= 5

    if denominator != 1:
        raise FormulaError(
            "inexact_division",
            "Formula result cannot be represented as a terminating decimal.",
        )

    scale = max(factor_twos, factor_fives)
    scaled = value.numerator * (2 ** (scale - factor_twos)) * (5 ** (scale - factor_fives))
    return _scaled_integer_to_decimal(scaled, scale)


def _scaled_integer_to_decimal(value: int, scale: int) -> Decimal:
    if scale == 0:
        return Decimal(value)

    sign = "-" if value < 0 else ""
    digits = str(abs(value))
    if len(digits) <= scale:
        decimal_text = f"{sign}0.{'0' * (scale - len(digits))}{digits}"
    else:
        decimal_text = f"{sign}{digits[:-scale]}.{digits[-scale:]}"
    return Decimal(decimal_text)
