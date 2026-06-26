"""Deterministic validation for experiment analysis claims."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
import re
from typing import Any

from paperctl._support.hashing import sha256_file
from paperctl._support.paths import is_repo_relative_posix, resolve_repo_relative_path
from paperctl.adapters import json_adapter, yaml_adapter
from paperctl.formula import FormulaError, evaluate_formula_exact


ANALYSIS_VALIDATION_VERSION = 1

CODE_DUPLICATE_CLAIM_ID = "duplicate_claim_id"
CODE_NO_MEASURED_CLAIM = "no_measured_claim"
CODE_MEASURED_CLAIM_NOT_IN_EVIDENCE = "measured_claim_not_in_evidence"
CODE_ABSOLUTE_SOURCE_PATH = "absolute_source_path"
CODE_SOURCE_PATH_TRAVERSAL = "source_path_traversal"
CODE_SOURCE_PATH_OUTSIDE_EXPERIMENT = "source_path_outside_experiment"
CODE_SOURCE_SYMLINK_OUTSIDE_EXPERIMENT = "source_symlink_outside_experiment"
CODE_SOURCE_FILE_MISSING = "source_file_missing"
CODE_SOURCE_HASH_MISMATCH = "source_hash_mismatch"
CODE_INVALID_JSON_POINTER = "invalid_json_pointer"
CODE_NON_SCALAR_SOURCE_VALUE = "non_scalar_source_value"
CODE_SOURCE_KIND_UNSUPPORTED = "source_kind_unsupported"
CODE_VALUE_MISMATCH = "value_mismatch"
CODE_VALUE_TYPE_MISMATCH = "value_type_mismatch"
CODE_UNIT_MISMATCH = "unit_mismatch"
CODE_QUESTION_PATH_MISMATCH = "question_path_mismatch"
CODE_EXPERIMENT_PATH_MISMATCH = "experiment_path_mismatch"
CODE_EXECUTION_STATUS_MISMATCH = "execution_status_mismatch"
CODE_NUMERIC_PROSE = "numeric_prose"
CODE_DERIVED_NON_NUMERIC_INPUT = "derived_non_numeric_input"
CODE_DERIVED_UNKNOWN_INPUT = "derived_unknown_input"
CODE_DERIVED_UNCITED_NUMERIC_LITERAL = "derived_uncited_numeric_literal"
CODE_DERIVED_INEXACT_DIVISION = "derived_inexact_division"
CODE_DERIVED_DIVISION_BY_ZERO = "derived_division_by_zero"
CODE_DERIVED_VALUE_MISMATCH = "derived_value_mismatch"
CODE_DERIVED_NON_INTEGRAL_RESULT = "derived_non_integral_result"
CODE_DERIVED_FORMULA_INVALID = "derived_formula_invalid"

_ALLOWED_SOURCE_ADAPTERS = {"json", "yaml", "yml"}
_NUMERIC_PROSE_RE = re.compile(
    r"(?<![A-Za-z0-9_])-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?%?(?![A-Za-z0-9_])"
)
_INVALID_POINTER_ESCAPE_RE = re.compile(r"~(?![01])")
_SCALAR_TYPES = (str, int, float, bool, type(None))


@dataclass(frozen=True)
class AnalysisDiagnostic:
    code: str
    message: str
    path: str | None = None
    selector_type: str | None = None
    selector: str | None = None
    detail: dict[str, Any] | None = None


@dataclass(frozen=True)
class _ClaimableValue:
    value: Any
    value_type: str
    unit: str | None
    source: dict[str, Any]


def validate_analysis_claims(
    *,
    repo: Path,
    manifest_entry: dict[str, Any],
    evidence_packet: dict[str, Any],
    analysis: dict[str, Any],
) -> list[AnalysisDiagnostic]:
    diagnostics: list[AnalysisDiagnostic] = []
    claims = analysis.get("claims")
    if not isinstance(claims, list):
        return diagnostics

    duplicate_diagnostics = _duplicate_claim_id_diagnostics(claims)
    if duplicate_diagnostics:
        return duplicate_diagnostics

    diagnostics.extend(_metadata_diagnostics(manifest_entry, evidence_packet, analysis))
    diagnostics.extend(_numeric_prose_diagnostics(analysis))

    claimables = _claimable_values(evidence_packet)
    accepted_values: dict[str, Any] = {}
    accepted_value_types: dict[str, str] = {}
    measured_claim_count = 0

    experiment_path = manifest_entry.get("experiment_path") or evidence_packet.get(
        "experiment_path"
    )
    experiment_dir = _resolve_experiment_dir(repo, experiment_path)

    for claim in claims:
        if claim.get("claim_type") != "measured_value":
            continue
        measured_claim_count += 1
        claim_diagnostics = _validate_measured_claim(
            repo=repo,
            experiment_dir=experiment_dir,
            claim=claim,
            claimables=claimables,
        )
        diagnostics.extend(claim_diagnostics)
        if not claim_diagnostics:
            claim_id = claim.get("claim_id")
            if isinstance(claim_id, str):
                accepted_values[claim_id] = claim.get("value")
                accepted_value_types[claim_id] = str(claim.get("value_type"))

    if measured_claim_count == 0:
        diagnostics.append(
            AnalysisDiagnostic(
                CODE_NO_MEASURED_CLAIM,
                "At least one measured claim is required.",
            )
        )

    diagnostics.extend(
        _validate_derived_claims(
            claims=claims,
            accepted_values=accepted_values,
            accepted_value_types=accepted_value_types,
        )
    )

    return diagnostics


def _duplicate_claim_id_diagnostics(claims: list[Any]) -> list[AnalysisDiagnostic]:
    seen: set[str] = set()
    diagnostics: list[AnalysisDiagnostic] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str):
            continue
        if claim_id in seen:
            diagnostics.append(
                AnalysisDiagnostic(
                    CODE_DUPLICATE_CLAIM_ID,
                    f"Duplicate claim_id {claim_id!r}.",
                    detail={"claim_id": claim_id},
                )
            )
        seen.add(claim_id)
    return diagnostics


def _metadata_diagnostics(
    manifest_entry: dict[str, Any],
    evidence_packet: dict[str, Any],
    analysis: dict[str, Any],
) -> list[AnalysisDiagnostic]:
    diagnostics: list[AnalysisDiagnostic] = []
    expected_question_path = manifest_entry.get("question_path") or evidence_packet.get(
        "question_path"
    )
    if analysis.get("question_path") != expected_question_path:
        diagnostics.append(
            AnalysisDiagnostic(
                CODE_QUESTION_PATH_MISMATCH,
                "Analysis question_path does not match the selected experiment.",
                detail={
                    "expected": expected_question_path,
                    "actual": analysis.get("question_path"),
                },
            )
        )

    expected_experiment_path = manifest_entry.get("experiment_path") or evidence_packet.get(
        "experiment_path"
    )
    if analysis.get("experiment_path") != expected_experiment_path:
        diagnostics.append(
            AnalysisDiagnostic(
                CODE_EXPERIMENT_PATH_MISMATCH,
                "Analysis experiment_path does not match the selected experiment.",
                detail={
                    "expected": expected_experiment_path,
                    "actual": analysis.get("experiment_path"),
                },
            )
        )

    evidence_status = evidence_packet.get("execution_status")
    if evidence_status != "unknown" and analysis.get("execution_status") != evidence_status:
        diagnostics.append(
            AnalysisDiagnostic(
                CODE_EXECUTION_STATUS_MISMATCH,
                "Analysis execution_status does not match evidence execution_status.",
                detail={
                    "expected": evidence_status,
                    "actual": analysis.get("execution_status"),
                },
            )
        )
    return diagnostics


def _numeric_prose_diagnostics(analysis: dict[str, Any]) -> list[AnalysisDiagnostic]:
    diagnostics: list[AnalysisDiagnostic] = []
    for field in ("title", "objective", "answer", "meaning"):
        value = analysis.get(field)
        if isinstance(value, str):
            diagnostics.extend(_scan_numeric_prose(value, field))
    limitations = analysis.get("limitations")
    if isinstance(limitations, list):
        for index, limitation in enumerate(limitations):
            if isinstance(limitation, str):
                diagnostics.extend(_scan_numeric_prose(limitation, f"limitations/{index}"))
    return diagnostics


def _scan_numeric_prose(value: str, field: str) -> list[AnalysisDiagnostic]:
    match = _NUMERIC_PROSE_RE.search(value)
    if match is None:
        return []
    return [
        AnalysisDiagnostic(
            CODE_NUMERIC_PROSE,
            "Numeric prose must be represented as a structured claim.",
            detail={"field": field, "token": match.group(0)},
        )
    ]


def _claimable_values(evidence_packet: dict[str, Any]) -> list[_ClaimableValue]:
    claimables: list[_ClaimableValue] = []
    for section in ("canonical_facts", "observed_values"):
        values = evidence_packet.get(section)
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, dict):
                continue
            source = value.get("source")
            if not _source_is_claimable(source):
                continue
            claimables.append(
                _ClaimableValue(
                    value=value.get("value"),
                    value_type=str(value.get("value_type")),
                    unit=value.get("unit"),
                    source=source,
                )
            )
    return claimables


def _source_is_claimable(source: Any) -> bool:
    if not isinstance(source, dict):
        return False
    if source.get("selector_type") != "json_pointer":
        return False
    adapter = source.get("adapter")
    return adapter is None or str(adapter).lower() in _ALLOWED_SOURCE_ADAPTERS


def _resolve_experiment_dir(repo: Path, experiment_path: Any) -> Path | None:
    if not isinstance(experiment_path, str):
        return None
    try:
        return resolve_repo_relative_path(repo, experiment_path)
    except ValueError:
        return None


def _validate_measured_claim(
    *,
    repo: Path,
    experiment_dir: Path | None,
    claim: dict[str, Any],
    claimables: list[_ClaimableValue],
) -> list[AnalysisDiagnostic]:
    source = claim.get("source")
    if not isinstance(source, dict):
        return [
            AnalysisDiagnostic(
                CODE_MEASURED_CLAIM_NOT_IN_EVIDENCE,
                "Measured claim source is missing or invalid.",
            )
        ]

    path = source.get("path")
    path_diagnostic = _source_path_diagnostic(repo, experiment_dir, path, source)
    if path_diagnostic is not None:
        return [path_diagnostic]
    assert isinstance(path, str)
    assert experiment_dir is not None

    if not _source_kind_is_supported(path, source):
        return [
            _source_diagnostic(
                CODE_SOURCE_KIND_UNSUPPORTED,
                "Measured claim source is not JSON or YAML.",
                source,
            )
        ]

    raw_path = resolve_repo_relative_path(repo, path)
    if not raw_path.exists():
        return [
            _source_diagnostic(
                CODE_SOURCE_FILE_MISSING,
                "Measured claim source file does not exist.",
                source,
            )
        ]

    actual_hash = sha256_file(raw_path)
    if actual_hash != source.get("source_hash"):
        return [
            _source_diagnostic(
                CODE_SOURCE_HASH_MISMATCH,
                "Measured claim source hash is stale.",
                source,
                detail={"expected": source.get("source_hash"), "actual": actual_hash},
            )
        ]

    selector = source.get("selector")
    if not _is_json_pointer(selector):
        return [
            _source_diagnostic(
                CODE_INVALID_JSON_POINTER,
                "Measured claim selector is not a valid JSON Pointer.",
                source,
            )
        ]

    try:
        raw_value = _load_and_resolve(raw_path, path, source, selector)
    except (json_adapter.JsonAdapterError, yaml_adapter.YamlAdapterError, KeyError):
        return [
            _source_diagnostic(
                CODE_INVALID_JSON_POINTER,
                "Measured claim selector does not resolve.",
                source,
            )
        ]

    if not _is_scalar(raw_value):
        return [
            _source_diagnostic(
                CODE_NON_SCALAR_SOURCE_VALUE,
                "Measured claim selector resolves to a non-scalar value.",
                source,
            )
        ]

    source_matches = [
        claimable for claimable in claimables if _same_source(claimable.source, source)
    ]

    raw_value_type = _value_type(raw_value)
    claim_value_type = claim.get("value_type")
    if not _source_value_type_satisfies(raw_value_type, claim_value_type):
        return [
            _source_diagnostic(
                CODE_VALUE_TYPE_MISMATCH,
                "Measured claim value_type does not match the source value.",
                source,
                detail={"expected": claim_value_type, "actual": raw_value_type},
            )
        ]

    if not _values_equal(raw_value, claim.get("value"), claim_value_type):
        if source_matches and not any(
            _matches_claimable(claimable, claim) for claimable in source_matches
        ):
            return [
                _source_diagnostic(
                    CODE_MEASURED_CLAIM_NOT_IN_EVIDENCE,
                    "Measured claim signature is not present in the selected evidence packet.",
                    source,
                )
            ]
        return [
            _source_diagnostic(
                CODE_VALUE_MISMATCH,
                "Measured claim value does not match the source value.",
                source,
                detail={"expected": claim.get("value"), "actual": raw_value},
            )
        ]

    if not source_matches:
        return [
            _source_diagnostic(
                CODE_MEASURED_CLAIM_NOT_IN_EVIDENCE,
                "Measured claim is not present in the selected evidence packet.",
                source,
            )
        ]

    if not any(claimable.unit == claim.get("unit") for claimable in source_matches):
        return [
            _source_diagnostic(
                CODE_UNIT_MISMATCH,
                "Measured claim unit does not match evidence.",
                source,
                detail={"actual": claim.get("unit")},
            )
        ]

    if not any(_matches_claimable(claimable, claim) for claimable in source_matches):
        return [
            _source_diagnostic(
                CODE_MEASURED_CLAIM_NOT_IN_EVIDENCE,
                "Measured claim signature is not present in the selected evidence packet.",
                source,
            )
        ]

    return []


def _source_path_diagnostic(
    repo: Path,
    experiment_dir: Path | None,
    path: Any,
    source: dict[str, Any],
) -> AnalysisDiagnostic | None:
    if not isinstance(path, str) or not path:
        return _source_diagnostic(
            CODE_MEASURED_CLAIM_NOT_IN_EVIDENCE,
            "Measured claim source path is missing.",
            source,
        )
    if path.startswith("/"):
        return _source_diagnostic(
            CODE_ABSOLUTE_SOURCE_PATH,
            "Measured claim source path must be repository-relative.",
            source,
        )
    if ".." in PurePosixPath(path).parts:
        return _source_diagnostic(
            CODE_SOURCE_PATH_TRAVERSAL,
            "Measured claim source path must not contain traversal components.",
            source,
        )
    if not is_repo_relative_posix(path):
        return _source_diagnostic(
            CODE_SOURCE_PATH_OUTSIDE_EXPERIMENT,
            "Measured claim source path is not repository-relative POSIX.",
            source,
        )
    if experiment_dir is None:
        return _source_diagnostic(
            CODE_SOURCE_PATH_OUTSIDE_EXPERIMENT,
            "Selected experiment directory is invalid.",
            source,
        )

    repo_root = repo.resolve()
    logical_path = repo_root / Path(*PurePosixPath(path).parts)
    try:
        logical_path.relative_to(experiment_dir)
    except ValueError:
        return _source_diagnostic(
            CODE_SOURCE_PATH_OUTSIDE_EXPERIMENT,
            "Measured claim source path is outside the selected experiment.",
            source,
        )

    try:
        raw_path = resolve_repo_relative_path(repo, path)
    except ValueError:
        return _source_diagnostic(
            CODE_SOURCE_SYMLINK_OUTSIDE_EXPERIMENT,
            "Measured claim source path resolves outside the selected experiment.",
            source,
        )
    try:
        raw_path.relative_to(experiment_dir)
    except ValueError:
        return _source_diagnostic(
            CODE_SOURCE_SYMLINK_OUTSIDE_EXPERIMENT,
            "Measured claim source path resolves outside the selected experiment.",
            source,
        )
    return None


def _source_kind_is_supported(path: str, source: dict[str, Any]) -> bool:
    adapter = source.get("adapter")
    if adapter is not None:
        return str(adapter).lower() in _ALLOWED_SOURCE_ADAPTERS
    return Path(path).suffix.lower() in {".json", ".yaml", ".yml"}


def _is_json_pointer(selector: Any) -> bool:
    if not isinstance(selector, str):
        return False
    if selector != "" and not selector.startswith("/"):
        return False
    return _INVALID_POINTER_ESCAPE_RE.search(selector) is None


def _load_and_resolve(raw_path: Path, path: str, source: dict[str, Any], selector: str) -> Any:
    adapter = str(source.get("adapter") or "").lower()
    if adapter in {"yaml", "yml"} or Path(path).suffix.lower() in {".yaml", ".yml"}:
        return yaml_adapter.resolve_pointer(yaml_adapter.load(raw_path), selector)
    return json_adapter.resolve_pointer(json_adapter.load(raw_path), selector)


def _is_scalar(value: Any) -> bool:
    return isinstance(value, _SCALAR_TYPES)


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def _source_value_type_satisfies(raw_value_type: str, claim_value_type: Any) -> bool:
    if raw_value_type == "integer" and claim_value_type == "number":
        return True
    return raw_value_type == claim_value_type


def _values_equal(raw_value: Any, claim_value: Any, value_type: Any) -> bool:
    if value_type in {"number", "integer"}:
        raw_decimal = _to_decimal(raw_value)
        claim_decimal = _to_decimal(claim_value)
        return (
            raw_decimal is not None and claim_decimal is not None and raw_decimal == claim_decimal
        )
    return raw_value == claim_value


def _to_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _same_source(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left.get("path") == right.get("path")
        and left.get("source_hash") == right.get("source_hash")
        and left.get("selector_type") == right.get("selector_type")
        and left.get("selector") == right.get("selector")
        and _optional_source_field_matches(left, right, "adapter", normalize=True)
        and _optional_source_field_matches(left, right, "adapter_version")
    )


def _optional_source_field_matches(
    left: dict[str, Any],
    right: dict[str, Any],
    field: str,
    *,
    normalize: bool = False,
) -> bool:
    if field not in left or field not in right:
        return True
    left_value = left.get(field)
    right_value = right.get(field)
    if normalize:
        left_value = str(left_value).lower() if left_value is not None else None
        right_value = str(right_value).lower() if right_value is not None else None
    return left_value == right_value


def _matches_claimable(claimable: _ClaimableValue, claim: dict[str, Any]) -> bool:
    return (
        _source_value_type_satisfies(claimable.value_type, claim.get("value_type"))
        and claimable.unit == claim.get("unit")
        and _values_equal(claimable.value, claim.get("value"), claim.get("value_type"))
    )


def _validate_derived_claims(
    *,
    claims: list[Any],
    accepted_values: dict[str, Any],
    accepted_value_types: dict[str, str],
) -> list[AnalysisDiagnostic]:
    diagnostics: list[AnalysisDiagnostic] = []
    all_claims_by_id = {
        claim.get("claim_id"): claim
        for claim in claims
        if isinstance(claim, dict) and isinstance(claim.get("claim_id"), str)
    }
    pending = {
        claim["claim_id"]: claim
        for claim in claims
        if isinstance(claim, dict)
        and claim.get("claim_type") == "derived_value"
        and isinstance(claim.get("claim_id"), str)
    }

    while pending:
        progressed = False
        for claim_id, claim in list(pending.items()):
            input_claim_ids = claim.get("input_claim_ids")
            if not isinstance(input_claim_ids, list):
                diagnostics.append(
                    AnalysisDiagnostic(
                        CODE_DERIVED_UNKNOWN_INPUT,
                        "Derived claim input_claim_ids must be a list.",
                        detail={"claim_id": claim_id},
                    )
                )
                del pending[claim_id]
                progressed = True
                continue

            missing_inputs = [
                input_claim_id
                for input_claim_id in input_claim_ids
                if input_claim_id not in all_claims_by_id
                or (input_claim_id not in accepted_values and input_claim_id not in pending)
            ]
            if missing_inputs:
                diagnostics.append(
                    AnalysisDiagnostic(
                        CODE_DERIVED_UNKNOWN_INPUT,
                        "Derived claim references an unknown or invalid input claim.",
                        detail={"claim_id": claim_id, "input_claim_id": missing_inputs[0]},
                    )
                )
                del pending[claim_id]
                progressed = True
                continue

            if any(input_claim_id in pending for input_claim_id in input_claim_ids):
                continue

            claim_diagnostics = _validate_derived_claim(
                claim=claim,
                accepted_values=accepted_values,
                accepted_value_types=accepted_value_types,
            )
            diagnostics.extend(claim_diagnostics)
            if not claim_diagnostics:
                accepted_values[claim_id] = claim.get("value")
                accepted_value_types[claim_id] = str(claim.get("value_type"))
            del pending[claim_id]
            progressed = True

        if not progressed:
            diagnostics.append(
                AnalysisDiagnostic(
                    CODE_DERIVED_UNKNOWN_INPUT,
                    "Derived claim dependency graph contains an unresolved cycle.",
                    detail={"claim_ids": sorted(pending)},
                )
            )
            break

    return diagnostics


def _validate_derived_claim(
    *,
    claim: dict[str, Any],
    accepted_values: dict[str, Any],
    accepted_value_types: dict[str, str],
) -> list[AnalysisDiagnostic]:
    claim_id = claim.get("claim_id")
    input_claim_ids = claim.get("input_claim_ids")
    if not isinstance(input_claim_ids, list):
        return [
            AnalysisDiagnostic(
                CODE_DERIVED_UNKNOWN_INPUT,
                "Derived claim input_claim_ids must be a list.",
                detail={"claim_id": claim_id},
            )
        ]

    for input_claim_id in input_claim_ids:
        if accepted_value_types.get(input_claim_id) not in {"number", "integer"}:
            return [
                AnalysisDiagnostic(
                    CODE_DERIVED_NON_NUMERIC_INPUT,
                    "Derived claim input must be numeric.",
                    detail={
                        "claim_id": claim_id,
                        "input_claim_id": input_claim_id,
                        "value_type": accepted_value_types.get(input_claim_id),
                    },
                )
            ]

    formula_values = {
        input_claim_id: _to_decimal(accepted_values[input_claim_id])
        for input_claim_id in input_claim_ids
    }
    if any(value is None for value in formula_values.values()):
        return [
            AnalysisDiagnostic(
                CODE_DERIVED_NON_NUMERIC_INPUT,
                "Derived claim input must be a finite decimal value.",
                detail={"claim_id": claim_id},
            )
        ]

    try:
        result = evaluate_formula_exact(
            str(claim.get("formula")),
            {key: value for key, value in formula_values.items() if value is not None},
            input_claim_ids,
        )
    except FormulaError as exc:
        return [_formula_diagnostic(exc, claim)]

    if claim.get("value_type") == "integer" and result != result.to_integral_value():
        return [
            AnalysisDiagnostic(
                CODE_DERIVED_NON_INTEGRAL_RESULT,
                "Derived integer claim formula result is not integral.",
                detail={"claim_id": claim_id, "actual": str(result)},
            )
        ]

    reported = _to_decimal(claim.get("value"))
    if reported is None or reported != result:
        return [
            AnalysisDiagnostic(
                CODE_DERIVED_VALUE_MISMATCH,
                "Derived claim value does not exactly match the formula result.",
                detail={
                    "claim_id": claim_id,
                    "expected": str(result),
                    "actual": str(claim.get("value")),
                },
            )
        ]

    return []


def _formula_diagnostic(exc: FormulaError, claim: dict[str, Any]) -> AnalysisDiagnostic:
    code_by_formula_code = {
        "unknown_symbol": CODE_DERIVED_UNKNOWN_INPUT,
        "unlisted_claim_reference": CODE_DERIVED_UNKNOWN_INPUT,
        "unused_input_claim_id": CODE_DERIVED_UNKNOWN_INPUT,
        "invalid_numeric_literal": CODE_DERIVED_UNCITED_NUMERIC_LITERAL,
        "inexact_division": CODE_DERIVED_INEXACT_DIVISION,
        "division_by_zero": CODE_DERIVED_DIVISION_BY_ZERO,
    }
    return AnalysisDiagnostic(
        code_by_formula_code.get(exc.code, CODE_DERIVED_FORMULA_INVALID),
        str(exc),
        detail={"claim_id": claim.get("claim_id"), "formula_error_code": exc.code},
    )


def _source_diagnostic(
    code: str,
    message: str,
    source: dict[str, Any],
    *,
    detail: dict[str, Any] | None = None,
) -> AnalysisDiagnostic:
    return AnalysisDiagnostic(
        code,
        message,
        path=source.get("path"),
        selector_type=source.get("selector_type"),
        selector=source.get("selector"),
        detail=detail,
    )
