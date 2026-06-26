from decimal import Decimal

import pytest

from paperctl.formula import FormulaError, evaluate_formula_exact


def test_evaluates_exact_terminating_division():
    result = evaluate_formula_exact(
        "throughput / baseline",
        {"throughput": Decimal("10"), "baseline": Decimal("4")},
        ["throughput", "baseline"],
    )

    assert result == Decimal("2.5")


def test_evaluates_parenthesized_multiplication_before_division():
    result = evaluate_formula_exact(
        "(a * 100) / b",
        {"a": Decimal("3"), "b": Decimal("4")},
        ["a", "b"],
    )

    assert result == Decimal("75")


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("0", Decimal("0")),
        ("1", Decimal("1")),
        ("100", Decimal("100")),
    ],
)
def test_allows_only_documented_numeric_literals(formula, expected):
    assert evaluate_formula_exact(formula, {}, []) == expected


def test_rejects_arbitrary_numeric_literal():
    with pytest.raises(FormulaError) as excinfo:
        evaluate_formula_exact("2", {}, [])

    assert excinfo.value.code == "invalid_numeric_literal"


def test_rejects_unknown_symbol():
    with pytest.raises(FormulaError) as excinfo:
        evaluate_formula_exact("missing", {}, ["missing"])

    assert excinfo.value.code == "unknown_symbol"


def test_rejects_unlisted_claim_reference():
    with pytest.raises(FormulaError) as excinfo:
        evaluate_formula_exact("extra", {"extra": Decimal("1")}, [])

    assert excinfo.value.code == "unlisted_claim_reference"


def test_rejects_unused_input_claim_ids():
    with pytest.raises(FormulaError) as excinfo:
        evaluate_formula_exact(
            "a",
            {"a": Decimal("1"), "b": Decimal("2")},
            ["a", "b"],
        )

    assert excinfo.value.code == "unused_input_claim_id"


def test_accepts_binary_addition_and_subtraction():
    result = evaluate_formula_exact(
        "a + b - c",
        {"a": Decimal("5"), "b": Decimal("3.5"), "c": Decimal("1.25")},
        ["a", "b", "c"],
    )

    assert result == Decimal("7.25")


def test_rejects_division_by_zero():
    with pytest.raises(FormulaError) as excinfo:
        evaluate_formula_exact(
            "a / b",
            {"a": Decimal("1"), "b": Decimal("0")},
            ["a", "b"],
        )

    assert excinfo.value.code == "division_by_zero"


def test_rejects_non_terminating_division_before_reported_value_rounding():
    with pytest.raises(FormulaError) as excinfo:
        evaluate_formula_exact(
            "a / b",
            {"a": Decimal("1"), "b": Decimal("3")},
            ["a", "b"],
        )

    assert excinfo.value.code == "inexact_division"
