from decimal import Decimal
from pathlib import Path
import copy
import dataclasses
import json

import pytest

from paperctl._support.hashing import sha256_file
from paperctl.analysis_validation import (
    ANALYSIS_VALIDATION_VERSION,
    AnalysisDiagnostic,
    CODE_ABSOLUTE_SOURCE_PATH,
    CODE_DERIVED_DIVISION_BY_ZERO,
    CODE_DERIVED_INEXACT_DIVISION,
    CODE_DERIVED_NON_INTEGRAL_RESULT,
    CODE_DERIVED_NON_NUMERIC_INPUT,
    CODE_DERIVED_UNCITED_NUMERIC_LITERAL,
    CODE_DERIVED_UNKNOWN_INPUT,
    CODE_DERIVED_VALUE_MISMATCH,
    CODE_DUPLICATE_CLAIM_ID,
    CODE_EXECUTION_STATUS_MISMATCH,
    CODE_EXPERIMENT_PATH_MISMATCH,
    CODE_INVALID_JSON_POINTER,
    CODE_MEASURED_CLAIM_NOT_IN_EVIDENCE,
    CODE_NO_MEASURED_CLAIM,
    CODE_NON_SCALAR_SOURCE_VALUE,
    CODE_NUMERIC_PROSE,
    CODE_QUESTION_PATH_MISMATCH,
    CODE_SOURCE_FILE_MISSING,
    CODE_SOURCE_HASH_MISMATCH,
    CODE_SOURCE_KIND_UNSUPPORTED,
    CODE_SOURCE_PATH_OUTSIDE_EXPERIMENT,
    CODE_SOURCE_PATH_TRAVERSAL,
    CODE_SOURCE_SYMLINK_OUTSIDE_EXPERIMENT,
    CODE_UNIT_MISMATCH,
    CODE_VALUE_MISMATCH,
    CODE_VALUE_TYPE_MISMATCH,
    validate_analysis_claims,
)
from paperctl.formula import FormulaError, evaluate_formula_exact


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / "tests/fixtures/minimal-research-repo"
ANALYSIS_FIXTURES = ROOT / "tests/fixtures/analysis"
EVIDENCE = (
    ROOT
    / "tests/golden/minimal-research-repo/paper/work/evidence/questions/q001-throughput/experiments/exp001-completed.json"
)
MANIFEST = ROOT / "tests/golden/minimal-research-repo/paper/work/manifest.json"


def _load_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("artifact_type") == "experiment_analysis":
        _add_default_analysis_adapter_metadata(data)
    return data


def _add_default_analysis_adapter_metadata(analysis: dict) -> None:
    for claim in analysis.get("claims", []):
        if not isinstance(claim, dict) or claim.get("claim_type") != "measured_value":
            continue
        source = claim.get("source")
        if not isinstance(source, dict):
            continue
        source_path = source.get("path")
        if isinstance(source_path, str) and source_path.endswith(".json"):
            source.setdefault("adapter", "json")
            source.setdefault("adapter_version", "1")


def _success_analysis() -> dict:
    return _load_json(ANALYSIS_FIXTURES / "exp001-success.json")


def _success_evidence() -> dict:
    return _load_json(EVIDENCE)


def _manifest_entry() -> dict:
    return _load_json(MANIFEST)["experiments"][0]


def _diagnostics(analysis: dict, evidence_packet: dict | None = None, repo: Path = REPO):
    return validate_analysis_claims(
        repo=repo,
        manifest_entry=_manifest_entry(),
        evidence_packet=evidence_packet or _success_evidence(),
        analysis=analysis,
    )


def _codes(analysis: dict, evidence_packet: dict | None = None, repo: Path = REPO) -> list[str]:
    return [diagnostic.code for diagnostic in _diagnostics(analysis, evidence_packet, repo)]


def _only_code(analysis: dict, evidence_packet: dict | None = None, repo: Path = REPO) -> str:
    codes = _codes(analysis, evidence_packet, repo)
    assert len(codes) == 1
    return codes[0]


def test_exposes_public_api_version_and_frozen_diagnostic_shape():
    diagnostic = AnalysisDiagnostic(
        code="sample_code",
        message="Sample message.",
        path="questions/q001-throughput/experiments/exp001-completed/outputs/result.json",
        selector_type="json_pointer",
        selector="/value",
        detail={"field": "value"},
    )

    assert ANALYSIS_VALIDATION_VERSION == 1
    assert dataclasses.asdict(diagnostic) == {
        "code": "sample_code",
        "message": "Sample message.",
        "path": "questions/q001-throughput/experiments/exp001-completed/outputs/result.json",
        "selector_type": "json_pointer",
        "selector": "/value",
        "detail": {"field": "value"},
    }
    with pytest.raises(dataclasses.FrozenInstanceError):
        diagnostic.code = "changed"


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


@pytest.mark.parametrize(
    "formula",
    [
        "1.0000000000000001",
        "0.99999999999999999",
        "99.999999999999999999",
    ],
)
def test_rejects_float_literals_that_ast_would_round_to_allowed_values(formula):
    with pytest.raises(FormulaError) as excinfo:
        evaluate_formula_exact(formula, {}, [])

    assert excinfo.value.code == "invalid_numeric_literal"


@pytest.mark.parametrize(
    "formula",
    [
        "0x64",
        "0b1",
        "1_00",
        "0_0",
    ],
)
def test_rejects_alternate_integer_spellings(formula):
    with pytest.raises(FormulaError) as excinfo:
        evaluate_formula_exact(formula, {}, [])

    assert excinfo.value.code == "invalid_numeric_literal"


@pytest.mark.parametrize(
    "formula",
    [
        "a # + missing",
        "a\n# + missing",
        "a\n",
    ],
)
def test_rejects_comments_and_newlines(formula):
    with pytest.raises(FormulaError) as excinfo:
        evaluate_formula_exact(formula, {"a": Decimal("1")}, ["a"])

    assert excinfo.value.code == "invalid_syntax"


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


def test_accepts_negative_results_from_binary_subtraction():
    result = evaluate_formula_exact(
        "a - b",
        {"a": Decimal("1"), "b": Decimal("3")},
        ["a", "b"],
    )

    assert result == Decimal("-2")


def test_formula_rejects_division_by_zero():
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


def test_accepts_measured_claim_matching_canonical_facts():
    assert _diagnostics(_success_analysis()) == []


def test_accepts_measured_claim_matching_observed_values():
    evidence = _success_evidence()
    evidence["observed_values"] = [copy.deepcopy(evidence["canonical_facts"][0])]
    evidence["canonical_facts"] = []

    assert _diagnostics(_success_analysis(), evidence) == []


def test_rejects_duplicate_claim_id_before_per_claim_validation():
    analysis = _success_analysis()
    analysis["claims"].append(copy.deepcopy(analysis["claims"][0]))
    analysis["claims"][1]["source"]["selector"] = "/canonical_facts/99/value"

    assert _only_code(analysis) == CODE_DUPLICATE_CLAIM_ID


def test_rejects_no_measured_claim():
    assert _only_code(_load_json(ANALYSIS_FIXTURES / "no-measured-claim.json")) == (
        CODE_NO_MEASURED_CLAIM
    )


def test_rejects_measured_claim_absent_from_evidence():
    assert _only_code(_load_json(ANALYSIS_FIXTURES / "claim-not-in-evidence.json")) == (
        CODE_MEASURED_CLAIM_NOT_IN_EVIDENCE
    )


def test_rejects_measured_claim_adapter_mismatch_when_metadata_present():
    analysis = _success_analysis()
    analysis["claims"][0]["source"]["adapter"] = "yaml"
    evidence = _success_evidence()

    assert _only_code(analysis, evidence) == CODE_MEASURED_CLAIM_NOT_IN_EVIDENCE


def test_rejects_measured_claim_adapter_version_mismatch_when_metadata_present():
    analysis = _success_analysis()
    analysis["claims"][0]["source"]["adapter"] = "json"
    analysis["claims"][0]["source"]["adapter_version"] = "2"
    evidence = _success_evidence()

    assert _only_code(analysis, evidence) == CODE_MEASURED_CLAIM_NOT_IN_EVIDENCE


def test_rejects_source_outside_selected_experiment():
    assert _only_code(_load_json(ANALYSIS_FIXTURES / "source-outside-experiment.json")) == (
        CODE_SOURCE_PATH_OUTSIDE_EXPERIMENT
    )


def test_rejects_source_file_missing():
    analysis = _success_analysis()
    claim = analysis["claims"][0]
    claim["source"]["path"] = (
        "questions/q001-throughput/experiments/exp001-completed/outputs/missing.json"
    )
    evidence = _success_evidence()
    evidence["canonical_facts"][0]["source"] = copy.deepcopy(claim["source"])

    assert _only_code(analysis, evidence) == CODE_SOURCE_FILE_MISSING


def test_rejects_stale_source_hash():
    assert _only_code(_load_json(ANALYSIS_FIXTURES / "stale-source-hash.json")) == (
        CODE_SOURCE_HASH_MISMATCH
    )


def test_rejects_invalid_json_pointer():
    analysis = _success_analysis()
    claim = analysis["claims"][0]
    claim["source"]["selector"] = "/bad~2escape"
    evidence = _success_evidence()
    evidence["canonical_facts"][0]["source"] = copy.deepcopy(claim["source"])

    assert _only_code(analysis, evidence) == CODE_INVALID_JSON_POINTER


def test_rejects_selector_resolving_to_non_scalar():
    analysis = _success_analysis()
    claim = analysis["claims"][0]
    claim["source"]["selector"] = "/canonical_facts"
    evidence = _success_evidence()
    evidence["canonical_facts"][0]["source"] = copy.deepcopy(claim["source"])

    assert _only_code(analysis, evidence) == CODE_NON_SCALAR_SOURCE_VALUE


def test_rejects_source_kind_other_than_json_or_yaml():
    analysis = _success_analysis()
    claim = analysis["claims"][0]
    claim["source"]["path"] = "questions/q001-throughput/experiments/exp001-completed/README.md"
    claim["source"]["source_hash"] = (
        "sha256:bd8b54158667cfd139740a854a3f3e3f19b642ebb19fd77e7dee0e1c7e6f96cc"
    )
    claim["source"].pop("adapter")
    claim["source"].pop("adapter_version")
    evidence = _success_evidence()
    evidence["canonical_facts"][0]["source"] = copy.deepcopy(claim["source"])

    assert _only_code(analysis, evidence) == CODE_SOURCE_KIND_UNSUPPORTED


def test_rejects_raw_source_value_mismatch():
    analysis = _success_analysis()
    claim = analysis["claims"][0]
    claim["value"] = 43
    evidence = _success_evidence()
    evidence["canonical_facts"][0]["value"] = 43

    assert _only_code(analysis, evidence) == CODE_VALUE_MISMATCH


def test_rejects_value_type_mismatch():
    analysis = _success_analysis()
    analysis["claims"][0]["value_type"] = "string"
    evidence = _success_evidence()
    evidence["canonical_facts"][0]["value_type"] = "string"

    assert _only_code(analysis, evidence) == CODE_VALUE_TYPE_MISMATCH


def test_integer_source_may_satisfy_number_claim(tmp_path):
    repo = tmp_path / "repo"
    experiment = repo / "questions/q001-throughput/experiments/exp001-completed/outputs"
    experiment.mkdir(parents=True)
    raw = experiment / "integer.json"
    raw.write_text('{"value": 42}\n', encoding="utf-8")

    analysis = _success_analysis()
    claim = analysis["claims"][0]
    claim["value"] = 42
    claim["value_type"] = "number"
    claim["unit"] = None
    claim["source"] = {
        "path": "questions/q001-throughput/experiments/exp001-completed/outputs/integer.json",
        "source_hash": sha256_file(raw),
        "selector_type": "json_pointer",
        "selector": "/value",
    }
    evidence = _success_evidence()
    evidence["canonical_facts"][0] = {
        "fact_id": "integer_value",
        "value": 42,
        "value_type": "number",
        "unit": None,
        "source": copy.deepcopy(claim["source"]),
    }

    assert _diagnostics(analysis, evidence, repo) == []


def test_rejects_unit_mismatch():
    analysis = _success_analysis()
    analysis["claims"][0]["unit"] = "docs/s"

    assert _only_code(analysis) == CODE_UNIT_MISMATCH


def test_rejects_analysis_question_path_mismatch():
    analysis = _success_analysis()
    analysis["question_path"] = "questions/q999-other"

    assert _only_code(analysis) == CODE_QUESTION_PATH_MISMATCH


def test_rejects_analysis_experiment_path_mismatch():
    analysis = _success_analysis()
    analysis["experiment_path"] = "questions/q001-throughput/experiments/exp999-other"

    assert _only_code(analysis) == CODE_EXPERIMENT_PATH_MISMATCH


def test_rejects_execution_status_mismatch_when_evidence_status_known():
    assert (
        _only_code(_load_json(ANALYSIS_FIXTURES / "execution-status-mismatch.json"))
        == CODE_EXECUTION_STATUS_MISMATCH
    )


def test_allows_execution_status_mismatch_when_evidence_status_unknown():
    evidence = _success_evidence()
    evidence["execution_status"] = "unknown"

    assert (
        _diagnostics(_load_json(ANALYSIS_FIXTURES / "execution-status-mismatch.json"), evidence)
        == []
    )


@pytest.mark.parametrize("field", ["title", "objective", "answer", "meaning"])
def test_rejects_numeric_prose_in_scanned_top_level_fields(field):
    analysis = _success_analysis()
    analysis[field] = "The backend wrote 42.5 in prose."

    assert _only_code(analysis) == CODE_NUMERIC_PROSE


def test_rejects_numeric_prose_in_each_limitation():
    analysis = _success_analysis()
    analysis["limitations"] = ["The backend wrote 99% in prose."]

    assert _only_code(analysis) == CODE_NUMERIC_PROSE


def test_accepts_digits_embedded_in_identifiers():
    analysis = _success_analysis()
    analysis["answer"] = "The exp014 run identifier is mentioned without numeric prose."

    assert _diagnostics(analysis) == []


def test_accepts_valid_derived_arithmetic():
    assert _diagnostics(_load_json(ANALYSIS_FIXTURES / "valid-derived.json")) == []


@pytest.mark.parametrize(
    ("value", "value_type"),
    [("42", "string"), (True, "boolean"), (None, "null")],
)
def test_rejects_non_numeric_derived_inputs(tmp_path, value, value_type):
    repo = tmp_path / "repo"
    output_dir = repo / "questions/q001-throughput/experiments/exp001-completed/outputs"
    output_dir.mkdir(parents=True)
    raw = output_dir / "non_numeric.json"
    raw.write_text(json.dumps({"value": value}), encoding="utf-8")

    analysis = _success_analysis()
    measured = analysis["claims"][0]
    measured["value"] = value
    measured["value_type"] = value_type
    measured["unit"] = None
    measured["source"] = {
        "path": ("questions/q001-throughput/experiments/exp001-completed/outputs/non_numeric.json"),
        "source_hash": sha256_file(raw),
        "selector_type": "json_pointer",
        "selector": "/value",
    }
    analysis["claims"].append(
        {
            "claim_id": "derived_from_non_numeric",
            "claim_type": "derived_value",
            "label": "Derived",
            "value": 1,
            "value_type": "integer",
            "unit": None,
            "formula": "throughput_pages_per_second",
            "input_claim_ids": ["throughput_pages_per_second"],
        }
    )
    evidence = _success_evidence()
    evidence["canonical_facts"][0]["value"] = value
    evidence["canonical_facts"][0]["value_type"] = value_type
    evidence["canonical_facts"][0]["unit"] = None
    evidence["canonical_facts"][0]["source"] = copy.deepcopy(measured["source"])

    assert _only_code(analysis, evidence, repo) == CODE_DERIVED_NON_NUMERIC_INPUT


def test_rejects_unknown_derived_input():
    assert _only_code(_load_json(ANALYSIS_FIXTURES / "unknown-derived-input.json")) == (
        CODE_DERIVED_UNKNOWN_INPUT
    )


def test_rejects_uncited_numeric_literal():
    assert _only_code(_load_json(ANALYSIS_FIXTURES / "bad-derived-literal.json")) == (
        CODE_DERIVED_VALUE_MISMATCH
    )
    analysis = _load_json(ANALYSIS_FIXTURES / "valid-derived.json")
    analysis["claims"][1]["formula"] = "throughput_pages_per_second + 2"
    analysis["claims"][1]["value"] = 44.5
    analysis["claims"][1]["value_type"] = "number"

    assert _only_code(analysis) == CODE_DERIVED_UNCITED_NUMERIC_LITERAL


def test_rejects_non_exact_rounded_division():
    analysis = _success_analysis()
    one_claim = copy.deepcopy(analysis["claims"][0])
    one_claim["claim_id"] = "schema_version"
    one_claim["label"] = "Schema version"
    one_claim["value"] = 1
    one_claim["value_type"] = "integer"
    one_claim["unit"] = None
    one_claim["source"]["selector"] = "/schema_version"
    analysis["claims"].append(one_claim)
    analysis["claims"].append(
        {
            "claim_id": "inexact_ratio",
            "claim_type": "derived_value",
            "label": "Inexact ratio",
            "value": 0.02,
            "value_type": "number",
            "unit": None,
            "formula": "schema_version / throughput_pages_per_second",
            "input_claim_ids": ["schema_version", "throughput_pages_per_second"],
        }
    )
    evidence = _success_evidence()
    evidence["canonical_facts"].append(
        {
            "fact_id": "schema_version",
            "value": 1,
            "value_type": "integer",
            "unit": None,
            "source": copy.deepcopy(one_claim["source"]),
        }
    )

    assert _only_code(analysis, evidence) == CODE_DERIVED_INEXACT_DIVISION


def test_rejects_derived_integer_claim_with_non_integral_exact_result():
    analysis = _success_analysis()
    schema_version_claim = copy.deepcopy(analysis["claims"][0])
    schema_version_claim["claim_id"] = "schema_version"
    schema_version_claim["label"] = "Schema version"
    schema_version_claim["value"] = 1
    schema_version_claim["value_type"] = "integer"
    schema_version_claim["unit"] = None
    schema_version_claim["source"]["selector"] = "/schema_version"
    analysis["claims"].append(schema_version_claim)
    analysis["claims"].append(
        {
            "claim_id": "schema_version_percent",
            "claim_type": "derived_value",
            "label": "Schema version percent",
            "value": 0,
            "value_type": "integer",
            "unit": None,
            "formula": "schema_version / 100",
            "input_claim_ids": ["schema_version"],
        }
    )
    evidence = _success_evidence()
    evidence["canonical_facts"].append(
        {
            "fact_id": "schema_version",
            "value": 1,
            "value_type": "integer",
            "unit": None,
            "source": copy.deepcopy(schema_version_claim["source"]),
        }
    )

    assert _only_code(analysis, evidence) == CODE_DERIVED_NON_INTEGRAL_RESULT


def test_rejects_derived_division_by_zero():
    assert _only_code(_load_json(ANALYSIS_FIXTURES / "division-by-zero.json")) == (
        CODE_DERIVED_DIVISION_BY_ZERO
    )


def test_rejects_absolute_source_paths():
    analysis = _success_analysis()
    analysis["claims"][0]["source"]["path"] = "/tmp/source.json"

    assert _only_code(analysis) == CODE_ABSOLUTE_SOURCE_PATH


def test_rejects_traversal_source_paths():
    analysis = _success_analysis()
    analysis["claims"][0]["source"]["path"] = (
        "questions/q001-throughput/experiments/exp001-completed/../exp001-completed/"
        "outputs/experiment_report.json"
    )

    assert _only_code(analysis) == CODE_SOURCE_PATH_TRAVERSAL


def test_rejects_symlink_escape_source_paths(tmp_path):
    repo = tmp_path / "repo"
    experiment = repo / "questions/q001-throughput/experiments/exp001-completed"
    outside = repo / "outside"
    outside.mkdir(parents=True)
    outside_source = outside / "source.json"
    outside_source.write_text('{"value": 42.5}\n', encoding="utf-8")
    experiment.mkdir(parents=True)
    (experiment / "link.json").symlink_to(outside_source)

    analysis = _success_analysis()
    claim = analysis["claims"][0]
    claim["source"] = {
        "path": "questions/q001-throughput/experiments/exp001-completed/link.json",
        "source_hash": "sha256:a4fa6f4ef48ef6d8aa15648d3e396aff306c7f1d84d8572b8544369ad02b07a5",
        "selector_type": "json_pointer",
        "selector": "/value",
    }
    evidence = _success_evidence()
    evidence["canonical_facts"][0]["source"] = copy.deepcopy(claim["source"])

    assert _only_code(analysis, evidence, repo) == CODE_SOURCE_SYMLINK_OUTSIDE_EXPERIMENT
