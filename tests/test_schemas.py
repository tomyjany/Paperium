import copy
import json
import re
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, ValidationError


SCHEMA_VALID_ANALYSIS_FIXTURES = {
    "exp001-success.json",
    "no-measured-claim.json",
    "execution-status-mismatch.json",
    "stale-source-hash.json",
    "bad-selector.json",
    "source-outside-experiment.json",
    "claim-not-in-evidence.json",
    "valid-derived.json",
    "bad-derived-literal.json",
    "unknown-derived-input.json",
    "rounded-division.json",
    "division-by-zero.json",
    "numeric-prose.json",
}
SCHEMA_INVALID_ANALYSIS_FIXTURES = {"invalid-schema.json"}

ANALYSIS_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "analysis"


def _evidence_packet(**overrides):
    packet = {
        "schema_version": 1,
        "artifact_type": "evidence_packet",
        "question_path": "questions/q001-throughput",
        "experiment_path": "questions/q001-throughput/experiments/exp001-baseline",
        "inventory_path": (
            "paper/work/inventories/questions/q001-throughput/experiments/exp001-baseline.json"
        ),
        "fingerprint": {"stage": "test"},
        "preanalysis_disposition": "blocked",
        "execution_status": "unknown",
        "evidence_status": "missing",
        "reason_codes": ["no_usable_evidence"],
        "counts": {
            "canonical_fact_count": 0,
            "observed_value_count": 0,
            "preview_count": 0,
            "diagnostic_count": 0,
            "conflict_count": 0,
            "unsupported_artifact_count": 0,
            "warning_count": 0,
            "redaction_count": 0,
        },
        "canonical_facts": [],
        "observed_values": [],
        "previews": [],
        "diagnostics": [],
        "conflicts": [],
        "unsupported_artifacts": [],
        "warnings": [],
    }
    packet.update(overrides)
    return packet


def _strict_json_source(**overrides):
    source = {
        "path": "questions/q001-throughput/experiments/exp001-baseline/outputs/result.json",
        "source_hash": "sha256:" + "b" * 64,
        "selector_type": "json_pointer",
        "selector": "/metrics/pages_per_second",
        "adapter": "json",
        "adapter_version": "1",
    }
    source.update(overrides)
    return source


def _experiment_report(**fact_overrides):
    fact = {
        "fact_id": "measured_throughput",
        "value": 13.585,
        "value_type": "number",
        "unit": "pages_per_second",
        "source": {
            "path": "outputs/hpi_2wpg_summary.json",
            "selector_type": "json_pointer",
            "selector": "/primary_slice/pages_per_second",
        },
    }
    fact.update(fact_overrides)
    return {
        "schema_version": 1,
        "execution_status": "completed",
        "canonical_facts": [fact],
    }


def _paper_config(selector="/metrics/pages_per_second"):
    return {
        "schema_version": 1,
        "questions": {
            "root": "questions",
            "pattern": "q*",
            "experiments_directory": "experiments",
        },
        "paper": {
            "work_directory": "paper/work",
            "draft_output": "PAPER.draft.md",
            "final_output": "PAPER.md",
            "audit_report": "paper/PAPER.audit.json",
        },
        "inventory": {
            "exclude_names": [
                ".git",
                ".hg",
                ".svn",
                "__pycache__",
                ".pytest_cache",
                ".mypy_cache",
                ".ruff_cache",
                ".DS_Store",
                ".venv",
                ".uv-cache",
                "node_modules",
            ],
        },
        "evidence": {
            "default_canonical_artifacts": ["outputs/experiment_report.json"],
            "canonical_facts": {
                "questions/q001-throughput/experiments/exp001-baseline": [
                    {
                        "fact_id": "measured_throughput",
                        "source": "outputs/hpi_2wpg_summary.json",
                        "selector_type": "json_pointer",
                        "selector": selector,
                        "expected_type": "number",
                        "unit": "pages_per_second",
                    }
                ]
            },
            "extraction_limits": {
                "maximum_file_bytes": 10000000,
                "maximum_scalar_observations_per_file": 200,
                "maximum_nesting_depth": 12,
                "preview_rows": 20,
                "log_head_lines": 100,
                "log_tail_lines": 100,
            },
        },
        "audit": {
            "default_stage": "publication",
        },
    }


def _manifest():
    return {
        "schema_version": 1,
        "artifact_type": "manifest",
        "experiments": [
            {
                "question_ref": "q001",
                "question_path": "questions/q001-throughput",
                "question_readme_path": "questions/q001-throughput/README.md",
                "question_readme_sha256": "sha256:" + "a" * 64,
                "experiment_ref": "exp001",
                "experiment_path": "questions/q001-throughput/experiments/exp001-baseline",
                "inventory_path": "paper/work/inventories/questions/q001-throughput/experiments/exp001-baseline.json",
                "evidence_path": "paper/work/evidence/questions/q001-throughput/experiments/exp001-baseline.json",
            }
        ],
    }


def _render_state():
    hashes = ["sha256:" + "c" * 64]
    return {
        "schema_version": 1,
        "artifact_type": "render_state",
        "draft_output": "PAPER.draft.md",
        "fingerprint": {
            "stage": {"name": "render", "version": 1},
            "schema_version": 1,
            "renderer_version": "1",
            "config_sha256": "sha256:" + "a" * 64,
            "manifest_path": "paper/work/manifest.json",
            "manifest_sha256": "sha256:" + "b" * 64,
            "evidence_packet_sha256": hashes,
            "draft_path": "PAPER.draft.md",
            "draft_sha256": "sha256:" + "d" * 64,
            "input_counts": {
                "experiment_count": 1,
                "evidence_packet_count": 1,
            },
            "fingerprint_sha256": "sha256:" + "e" * 64,
        },
        "manifest_sha256": "sha256:" + "b" * 64,
        "evidence_packet_sha256": hashes,
    }


def _experiment_analysis(**overrides):
    analysis = {
        "schema_version": 1,
        "artifact_type": "experiment_analysis",
        "question_path": "questions/q001-throughput",
        "experiment_path": "questions/q001-throughput/experiments/exp001-completed",
        "title": "Completed throughput run",
        "execution_status": "completed",
        "hypothesis_verdict": "supported",
        "objective": "Evaluate throughput using claim throughput_pages_per_second.",
        "answer": "The measured claim throughput_pages_per_second is available.",
        "meaning": "The run has structured measured evidence.",
        "limitations": ["No semantic synthesis is rendered in M2."],
        "confidence": "medium",
        "claims": [
            {
                "claim_id": "throughput_pages_per_second",
                "claim_type": "measured_value",
                "label": "Throughput",
                "value": 42.5,
                "value_type": "number",
                "unit": "pages/s",
                "source": {
                    "path": (
                        "questions/q001-throughput/experiments/exp001-completed/"
                        "outputs/experiment_report.json"
                    ),
                    "source_hash": (
                        "sha256:4bf7977e2379089b948891299acad85afb21056d02280f360549b1b4b7d86fdb"
                    ),
                    "selector_type": "json_pointer",
                    "selector": "/canonical_facts/0/value",
                },
            }
        ],
    }
    analysis.update(overrides)
    return analysis


def _analysis_fingerprint(**overrides):
    fingerprint = {
        "stage": {"name": "analyze", "version": 1},
        "schema_version": 1,
        "config_sha256": "sha256:" + "a" * 64,
        "source_files": [
            {
                "path": "questions/q001-throughput/experiments/exp001-completed/README.md",
                "sha256": "sha256:" + "b" * 64,
            }
        ],
        "source_files_sha256": "sha256:" + "c" * 64,
        "prerequisite_artifacts": [
            {
                "path": (
                    "paper/work/evidence/questions/q001-throughput/experiments/"
                    "exp001-completed.json"
                ),
                "schema_name": "evidence-packet.schema.json",
                "sha256": "sha256:" + "d" * 64,
            }
        ],
        "prerequisite_artifacts_sha256": "sha256:" + "e" * 64,
        "extra_inputs": {},
        "extra_inputs_sha256": "sha256:" + "f" * 64,
        "fingerprint_sha256": "sha256:" + "1" * 64,
    }
    fingerprint.update(overrides)
    return fingerprint


def _analysis_backend(**overrides):
    backend = {
        "name": "fake",
        "status": "completed",
        "return_code": 0,
        "stdout_preview": "analysis ok",
        "stderr_preview": None,
        "token_usage": None,
    }
    backend.update(overrides)
    return backend


def _analysis_diagnostic(**overrides):
    diagnostic = {
        "code": "backend_failed",
        "message": "The backend did not produce valid experiment analysis.",
        "path": "questions/q001-throughput/experiments/exp001-completed/README.md",
        "selector": "/analysis",
        "detail": {"backend_status": "failed"},
    }
    diagnostic.update(overrides)
    return diagnostic


def _analysis_state(**overrides):
    state = {
        "schema_version": 1,
        "artifact_type": "analysis_state",
        "status": "accepted",
        "question_path": "questions/q001-throughput",
        "experiment_path": "questions/q001-throughput/experiments/exp001-completed",
        "analysis_path": (
            "paper/work/analyses/questions/q001-throughput/experiments/exp001-completed.json"
        ),
        "fingerprint": _analysis_fingerprint(),
        "backend": _analysis_backend(),
        "diagnostics": [],
        "analysis": _experiment_analysis(),
        "raw_output_sha256": "sha256:" + "2" * 64,
    }
    state.update(overrides)
    return state


def _failed_analysis_state(**overrides):
    state = _analysis_state(
        status="failed",
        backend=_analysis_backend(status="failed", return_code=1, stderr_preview="invalid json"),
        diagnostics=[_analysis_diagnostic()],
        analysis=None,
        raw_output_sha256=None,
    )
    state.update(overrides)
    return state


def _derived_claim(**overrides):
    claim = {
        "claim_id": "throughput_percent",
        "claim_type": "derived_value",
        "label": "Throughput percent",
        "value": 100,
        "value_type": "integer",
        "unit": "%",
        "formula": "throughput_pages_per_second / throughput_pages_per_second * 100",
        "input_claim_ids": ["throughput_pages_per_second"],
    }
    claim.update(overrides)
    return claim


def test_packaged_schemas_load_through_importlib_resources():
    from importlib import resources

    import paperctl.schemas as schemas_package

    expected_names = {
        "paper-config.schema.json",
        "manifest.schema.json",
        "artifact-inventory.schema.json",
        "evidence-packet.schema.json",
        "render-state.schema.json",
        "paper-audit.schema.json",
        "experiment-report.schema.json",
        "experiment-analysis.schema.json",
        "analysis-state.schema.json",
    }

    available_names = {
        child.name
        for child in resources.files(schemas_package).iterdir()
        if child.name.endswith(".json")
    }

    assert expected_names <= available_names


def test_packaged_schemas_are_valid_json_schemas():
    from paperctl._support.schema import load_schema

    for name in [
        "paper-config.schema.json",
        "manifest.schema.json",
        "artifact-inventory.schema.json",
        "evidence-packet.schema.json",
        "render-state.schema.json",
        "paper-audit.schema.json",
        "experiment-report.schema.json",
        "experiment-analysis.schema.json",
        "analysis-state.schema.json",
    ]:
        Draft202012Validator.check_schema(load_schema(name))


def test_experiment_analysis_schema_accepts_minimal_valid_analysis():
    from paperctl._support.schema import validate_artifact

    validate_artifact("experiment-analysis.schema.json", _experiment_analysis())


def test_experiment_analysis_schema_codex_output_schema_enums_have_explicit_types():
    from paperctl._support.schema import load_schema

    schema = load_schema("experiment-analysis.schema.json")
    missing_type_paths: list[str] = []

    def walk(value, path):
        if isinstance(value, dict):
            if "type" not in value:
                if "const" in value:
                    missing_type_paths.append("/".join(path + ["const"]))
                enum_values = value.get("enum")
                if isinstance(enum_values, list) and enum_values:
                    missing_type_paths.append("/".join(path + ["enum"]))
            for key, nested in value.items():
                walk(nested, path + [key])
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                walk(nested, path + [str(index)])

    walk(schema, [])

    assert missing_type_paths == []


def test_experiment_analysis_schema_avoids_codex_unsupported_composition_keywords():
    from paperctl._support.schema import load_schema

    schema = load_schema("experiment-analysis.schema.json")
    unsupported_paths: list[str] = []
    unsupported_keywords = {"allOf", "oneOf", "if", "then", "else", "uniqueItems"}

    def walk(value, path):
        if isinstance(value, dict):
            for key, nested in value.items():
                if key in unsupported_keywords:
                    unsupported_paths.append("/".join(path + [key]))
                walk(nested, path + [key])
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                walk(nested, path + [str(index)])

    walk(schema, [])

    assert unsupported_paths == []


def test_experiment_analysis_schema_avoids_codex_unsupported_regex_lookaround():
    from paperctl._support.schema import load_schema

    schema = load_schema("experiment-analysis.schema.json")
    unsupported_paths: list[str] = []

    def walk(value, path):
        if isinstance(value, dict):
            pattern = value.get("pattern")
            if isinstance(pattern, str) and "(?" in pattern:
                unsupported_paths.append("/".join(path + ["pattern"]))
            for key, nested in value.items():
                walk(nested, path + [key])
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                walk(nested, path + [str(index)])

    walk(schema, [])

    assert unsupported_paths == []


def test_experiment_analysis_fixture_schema_intent_table_is_complete():
    from paperctl._support.schema import validate_artifact

    fixture_names = {fixture_path.name for fixture_path in ANALYSIS_FIXTURE_DIR.glob("*.json")}
    classified_names = SCHEMA_VALID_ANALYSIS_FIXTURES | SCHEMA_INVALID_ANALYSIS_FIXTURES

    assert SCHEMA_VALID_ANALYSIS_FIXTURES.isdisjoint(SCHEMA_INVALID_ANALYSIS_FIXTURES)
    assert fixture_names == classified_names

    for fixture_name in sorted(SCHEMA_VALID_ANALYSIS_FIXTURES):
        fixture = json.loads((ANALYSIS_FIXTURE_DIR / fixture_name).read_text())
        validate_artifact("experiment-analysis.schema.json", fixture)

    for fixture_name in sorted(SCHEMA_INVALID_ANALYSIS_FIXTURES):
        fixture = json.loads((ANALYSIS_FIXTURE_DIR / fixture_name).read_text())
        with pytest.raises(ValidationError):
            validate_artifact("experiment-analysis.schema.json", fixture)


@pytest.mark.parametrize("property_name", ["unexpected"])
def test_experiment_analysis_schema_rejects_unknown_top_level_properties(property_name):
    from paperctl._support.schema import validate_artifact

    analysis = _experiment_analysis(**{property_name: True})

    with pytest.raises(ValidationError):
        validate_artifact("experiment-analysis.schema.json", analysis)


def test_experiment_analysis_schema_rejects_unknown_nested_claim_and_source_properties():
    from paperctl._support.schema import validate_artifact

    analysis = _experiment_analysis()
    analysis["claims"][0]["unexpected"] = True
    with pytest.raises(ValidationError):
        validate_artifact("experiment-analysis.schema.json", analysis)

    analysis = _experiment_analysis()
    analysis["claims"][0]["source"]["unexpected"] = True
    with pytest.raises(ValidationError):
        validate_artifact("experiment-analysis.schema.json", analysis)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("execution_status", "running"),
        ("hypothesis_verdict", "proven"),
        ("confidence", "certain"),
    ],
)
def test_experiment_analysis_schema_rejects_unknown_enums(field, value):
    from paperctl._support.schema import validate_artifact

    analysis = _experiment_analysis(**{field: value})

    with pytest.raises(ValidationError):
        validate_artifact("experiment-analysis.schema.json", analysis)


@pytest.mark.parametrize("field", ["question_path", "experiment_path"])
@pytest.mark.parametrize(
    "path",
    [
        "questions\\q001-throughput",
        "C:\\repo\\questions\\q001-throughput",
    ],
)
def test_experiment_analysis_schema_rejects_backslash_paths(field, path):
    from paperctl._support.schema import validate_artifact

    analysis = _experiment_analysis(**{field: path})

    with pytest.raises(ValidationError):
        validate_artifact("experiment-analysis.schema.json", analysis)


def test_experiment_analysis_schema_rejects_bad_claim_id():
    from paperctl._support.schema import validate_artifact

    analysis = _experiment_analysis()
    analysis["claims"][0]["claim_id"] = "bad-id"

    with pytest.raises(ValidationError):
        validate_artifact("experiment-analysis.schema.json", analysis)


@pytest.mark.parametrize(
    ("value", "value_type"),
    [
        ("42.5", "number"),
        (42.5, "integer"),
        (True, "string"),
        ("not null", "null"),
    ],
)
def test_experiment_analysis_schema_leaves_claim_value_type_pairing_to_validator(
    value, value_type
):
    from paperctl._support.schema import validate_artifact

    analysis = _experiment_analysis()
    analysis["claims"][0]["value"] = value
    analysis["claims"][0]["value_type"] = value_type

    validate_artifact("experiment-analysis.schema.json", analysis)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (["title"], "x" * 161),
        (["objective"], "x" * 1001),
        (["answer"], "x" * 1501),
        (["meaning"], "x" * 1501),
        (["limitations", 0], "x" * 501),
        (["claims", 0, "value"], "x" * 2001),
        (["claims", 0, "label"], "x" * 161),
        (["claims", 0, "unit"], "x" * 81),
        (["claims", 1, "formula"], "x" * 301),
        (["claims", 0, "source", "path"], "x" * 1001),
        (["claims", 0, "source", "selector"], "/" + "x" * 1000),
    ],
)
def test_experiment_analysis_schema_rejects_unbounded_strings(path, value):
    from paperctl._support.schema import validate_artifact

    analysis = _experiment_analysis(claims=[_experiment_analysis()["claims"][0], _derived_claim()])
    target = analysis
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ValidationError):
        validate_artifact("experiment-analysis.schema.json", analysis)


@pytest.mark.parametrize(
    "path",
    [
        "questions\\q001-throughput\\experiments\\exp001-completed\\outputs\\result.json",
        "C:\\repo\\questions\\q001-throughput\\result.json",
    ],
)
def test_experiment_analysis_schema_rejects_backslash_source_paths(path):
    from paperctl._support.schema import validate_artifact

    analysis = _experiment_analysis()
    analysis["claims"][0]["source"]["path"] = path

    with pytest.raises(ValidationError):
        validate_artifact("experiment-analysis.schema.json", analysis)


def test_experiment_analysis_schema_rejects_too_many_limitations_and_claims():
    from paperctl._support.schema import validate_artifact

    analysis = _experiment_analysis(limitations=["limitation"] * 11)
    with pytest.raises(ValidationError):
        validate_artifact("experiment-analysis.schema.json", analysis)

    analysis = _experiment_analysis()
    base_claim = analysis["claims"][0]
    analysis["claims"] = [
        {**copy.deepcopy(base_claim), "claim_id": f"claim_{index}"} for index in range(51)
    ]
    with pytest.raises(ValidationError):
        validate_artifact("experiment-analysis.schema.json", analysis)


def test_experiment_analysis_schema_rejects_malformed_source_hash():
    from paperctl._support.schema import validate_artifact

    analysis = _experiment_analysis()
    analysis["claims"][0]["source"]["source_hash"] = "sha256:" + "z" * 64

    with pytest.raises(ValidationError):
        validate_artifact("experiment-analysis.schema.json", analysis)


@pytest.mark.parametrize("selector", ["canonical_facts/0/value"])
def test_experiment_analysis_schema_requires_json_pointer_selector_prefix(selector):
    from paperctl._support.schema import validate_artifact

    analysis = _experiment_analysis()
    analysis["claims"][0]["source"]["selector"] = selector

    with pytest.raises(ValidationError):
        validate_artifact("experiment-analysis.schema.json", analysis)


def test_experiment_analysis_schema_rejects_derived_claim_with_empty_inputs():
    from paperctl._support.schema import validate_artifact

    analysis = _experiment_analysis(claims=[_experiment_analysis()["claims"][0], _derived_claim()])
    analysis["claims"][1]["input_claim_ids"] = []

    with pytest.raises(ValidationError):
        validate_artifact("experiment-analysis.schema.json", analysis)


@pytest.mark.parametrize("state", [_analysis_state(), _failed_analysis_state()])
def test_analysis_state_schema_accepts_valid_states(state):
    from paperctl._support.schema import validate_artifact

    validate_artifact("analysis-state.schema.json", state)


@pytest.mark.parametrize(
    "field",
    [
        "schema_version",
        "artifact_type",
        "status",
        "question_path",
        "experiment_path",
        "analysis_path",
        "fingerprint",
        "backend",
        "diagnostics",
        "analysis",
        "raw_output_sha256",
    ],
)
@pytest.mark.parametrize("state_builder", [_analysis_state, _failed_analysis_state])
def test_analysis_state_schema_requires_generated_state_fields(field, state_builder):
    from paperctl._support.schema import validate_artifact

    state = state_builder()
    del state[field]

    with pytest.raises(ValidationError):
        validate_artifact("analysis-state.schema.json", state)


@pytest.mark.parametrize("field", ["question_path", "experiment_path", "analysis_path"])
@pytest.mark.parametrize(
    "path",
    [
        "/absolute/path",
        "../escape",
        "questions/q001-throughput/../escape",
        "questions\\q001-throughput",
        "C:\\repo\\questions\\q001-throughput",
    ],
)
def test_analysis_state_paths_must_be_posix_repo_relative(field, path):
    from paperctl._support.schema import validate_artifact

    state = _analysis_state(**{field: path})

    with pytest.raises(ValidationError):
        validate_artifact("analysis-state.schema.json", state)


@pytest.mark.parametrize(
    "analysis_path",
    [
        "paper/work/analysis/questions/q001-throughput/experiments/exp001-completed.json",
        "paper/work/analyses/questions/q001-throughput/experiments/exp001-completed.txt",
        "paper/work/analyses.json",
        "paper/work/analyses/",
    ],
)
def test_analysis_state_analysis_path_must_use_m2_output_layout(analysis_path):
    from paperctl._support.schema import validate_artifact

    state = _analysis_state(analysis_path=analysis_path)

    with pytest.raises(ValidationError):
        validate_artifact("analysis-state.schema.json", state)


def test_analysis_state_schema_requires_stage_fingerprint_contract():
    from paperctl._support.schema import validate_artifact

    validate_artifact("analysis-state.schema.json", _analysis_state())

    for key in [
        "stage",
        "schema_version",
        "config_sha256",
        "source_files",
        "source_files_sha256",
        "prerequisite_artifacts",
        "prerequisite_artifacts_sha256",
        "extra_inputs",
        "extra_inputs_sha256",
        "fingerprint_sha256",
    ]:
        state = _analysis_state()
        del state["fingerprint"][key]
        with pytest.raises(ValidationError):
            validate_artifact("analysis-state.schema.json", state)


def test_analysis_state_fingerprint_stage_name_must_be_analyze():
    from paperctl._support.schema import validate_artifact

    state = _analysis_state()
    state["fingerprint"]["stage"]["name"] = "analysis"

    with pytest.raises(ValidationError):
        validate_artifact("analysis-state.schema.json", state)


def test_analysis_state_fingerprint_allows_non_empty_extra_inputs():
    from paperctl._support.schema import validate_artifact

    state = _analysis_state()
    state["fingerprint"]["extra_inputs"] = {
        "backend_name": "fake",
        "raw_output_sha256": "sha256:" + "3" * 64,
        "retry": {"attempt": 1, "repair_applied": False},
    }

    validate_artifact("analysis-state.schema.json", state)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: state.update(raw_output_sha256="sha256:" + "z" * 64),
        lambda state: state["fingerprint"].update(config_sha256="not-a-hash"),
        lambda state: state["fingerprint"]["source_files"][0].update(sha256="sha256:" + "g" * 64),
        lambda state: state["fingerprint"].update(source_files_sha256="sha256:" + "G" * 64),
        lambda state: state["fingerprint"]["prerequisite_artifacts"][0].update(
            sha256="sha256:" + "x" * 63
        ),
        lambda state: state["fingerprint"].update(
            prerequisite_artifacts_sha256="sha256:" + "x" * 65
        ),
        lambda state: state["fingerprint"].update(extra_inputs_sha256="sha256:abc"),
        lambda state: state["fingerprint"].update(fingerprint_sha256="abc"),
    ],
)
def test_analysis_state_schema_rejects_malformed_hashes(mutation):
    from paperctl._support.schema import validate_artifact

    state = _analysis_state()
    mutation(state)

    with pytest.raises(ValidationError):
        validate_artifact("analysis-state.schema.json", state)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: state.update(status="failed"),
        lambda state: state.update(analysis=None),
        lambda state: state.update(diagnostics=[_analysis_diagnostic()]),
        lambda state: state.update(raw_output_sha256=None),
    ],
)
def test_analysis_state_accepted_state_requires_analysis_empty_diagnostics_and_raw_output(
    mutation,
):
    from paperctl._support.schema import validate_artifact

    state = _analysis_state()
    mutation(state)

    with pytest.raises(ValidationError):
        validate_artifact("analysis-state.schema.json", state)


@pytest.mark.parametrize("backend_status", ["failed", "timed_out"])
def test_analysis_state_accepted_state_requires_completed_backend(backend_status):
    from paperctl._support.schema import validate_artifact

    state = _analysis_state(backend=_analysis_backend(status=backend_status))

    with pytest.raises(ValidationError):
        validate_artifact("analysis-state.schema.json", state)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: state.update(status="accepted"),
        lambda state: state.update(analysis=_experiment_analysis()),
        lambda state: state.update(diagnostics=[]),
    ],
)
def test_analysis_state_failed_state_requires_null_analysis_and_non_empty_diagnostics(
    mutation,
):
    from paperctl._support.schema import validate_artifact

    state = _failed_analysis_state()
    mutation(state)

    with pytest.raises(ValidationError):
        validate_artifact("analysis-state.schema.json", state)


def test_analysis_state_failed_state_allows_raw_output_sha256():
    from paperctl._support.schema import validate_artifact

    state = _failed_analysis_state(raw_output_sha256="sha256:" + "3" * 64)
    validate_artifact("analysis-state.schema.json", state)


@pytest.mark.parametrize("name", ["fake", "codex-exec"])
@pytest.mark.parametrize("return_code", [0, 1, None])
def test_analysis_state_accepted_backend_metadata_accepts_completed_status(name, return_code):
    from paperctl._support.schema import validate_artifact

    state = _analysis_state(
        backend=_analysis_backend(name=name, status="completed", return_code=return_code)
    )

    validate_artifact("analysis-state.schema.json", state)


def test_analysis_state_integrity_accepts_matching_accepted_state_paths():
    from paperctl._support.schema import validate_analysis_state_integrity

    validate_analysis_state_integrity(_analysis_state())


@pytest.mark.parametrize(
    ("state_path", "analysis_path"),
    [
        ("question_path", "questions/q999-other"),
        ("experiment_path", "questions/q001-throughput/experiments/exp999-other"),
    ],
)
def test_analysis_state_integrity_rejects_mismatched_accepted_state_paths(
    state_path,
    analysis_path,
):
    from paperctl._support.schema import AnalysisStateIntegrityError
    from paperctl._support.schema import validate_analysis_state_integrity

    state = _analysis_state()
    state["analysis"][state_path] = analysis_path

    with pytest.raises(AnalysisStateIntegrityError, match=state_path):
        validate_analysis_state_integrity(state)


@pytest.mark.parametrize("state_builder", [_analysis_state, _failed_analysis_state])
def test_analysis_state_integrity_rejects_mismatched_analysis_path(state_builder):
    from paperctl._support.schema import AnalysisStateIntegrityError
    from paperctl._support.schema import validate_analysis_state_integrity

    state = state_builder(
        analysis_path="paper/work/analyses/questions/q999-other/experiments/exp999-other.json"
    )

    with pytest.raises(AnalysisStateIntegrityError, match="analysis_path"):
        validate_analysis_state_integrity(state)


def test_analysis_state_integrity_accepts_failed_state_without_analysis():
    from paperctl._support.schema import validate_analysis_state_integrity

    validate_analysis_state_integrity(_failed_analysis_state())


@pytest.mark.parametrize("name", ["fake", "codex-exec"])
@pytest.mark.parametrize("status", ["completed", "failed", "timed_out"])
@pytest.mark.parametrize("return_code", [0, 1, None])
def test_analysis_state_failed_backend_metadata_accepts_known_statuses(name, status, return_code):
    from paperctl._support.schema import validate_artifact

    state = _failed_analysis_state(
        backend=_analysis_backend(name=name, status=status, return_code=return_code)
    )

    validate_artifact("analysis-state.schema.json", state)


@pytest.mark.parametrize(
    "backend",
    [
        _analysis_backend(name="local"),
        _analysis_backend(status="running"),
        _analysis_backend(return_code="1"),
        _analysis_backend(stdout_preview="\U0001f642" * 4001),
        _analysis_backend(stderr_preview="\U0001f642" * 4001),
        _analysis_backend(token_usage={}),
        _analysis_backend(token_usage={"input_tokens": -1}),
        _analysis_backend(token_usage={"input_tokens": 1.5}),
        _analysis_backend(token_usage={"unknown_tokens": 1}),
    ],
)
def test_analysis_state_schema_rejects_invalid_backend_metadata(backend):
    from paperctl._support.schema import validate_artifact

    state = _analysis_state(backend=backend)

    with pytest.raises(ValidationError):
        validate_artifact("analysis-state.schema.json", state)


def test_analysis_state_failed_diagnostics_are_capped():
    from paperctl._support.schema import validate_artifact

    validate_artifact(
        "analysis-state.schema.json",
        _failed_analysis_state(diagnostics=[_analysis_diagnostic()] * 20),
    )

    with pytest.raises(ValidationError):
        validate_artifact(
            "analysis-state.schema.json",
            _failed_analysis_state(diagnostics=[_analysis_diagnostic()] * 21),
        )


@pytest.mark.parametrize(
    "diagnostic",
    [
        _analysis_diagnostic(code="BadCode"),
        _analysis_diagnostic(code="bad-code"),
        _analysis_diagnostic(code="a" * 81),
        _analysis_diagnostic(message="x" * 1001),
        _analysis_diagnostic(path="/absolute/result.json"),
        _analysis_diagnostic(path="../result.json"),
        _analysis_diagnostic(path="questions\\q001\\result.json"),
        _analysis_diagnostic(selector="canonical_facts/0/value"),
        _analysis_diagnostic(selector="/bad~2escape"),
    ],
)
def test_analysis_state_schema_rejects_invalid_diagnostics(diagnostic):
    from paperctl._support.schema import validate_artifact

    state = _failed_analysis_state(diagnostics=[diagnostic])

    with pytest.raises(ValidationError):
        validate_artifact("analysis-state.schema.json", state)


def test_analysis_state_diagnostic_path_and_selector_can_be_null():
    from paperctl._support.schema import validate_artifact

    state = _failed_analysis_state(
        diagnostics=[_analysis_diagnostic(path=None, selector=None, detail={"nested": [1]})]
    )

    validate_artifact("analysis-state.schema.json", state)


@pytest.mark.parametrize(
    ("state_builder", "mutation"),
    [
        (_failed_analysis_state, lambda state: state.update(unexpected=True)),
        (_failed_analysis_state, lambda state: state["fingerprint"].update(unexpected=True)),
        (
            _failed_analysis_state,
            lambda state: state["fingerprint"]["stage"].update(unexpected=True),
        ),
        (
            _failed_analysis_state,
            lambda state: state["fingerprint"]["source_files"][0].update(unexpected=True),
        ),
        (
            _failed_analysis_state,
            lambda state: state["fingerprint"]["prerequisite_artifacts"][0].update(unexpected=True),
        ),
        (_failed_analysis_state, lambda state: state["backend"].update(unexpected=True)),
        (_failed_analysis_state, lambda state: state["diagnostics"][0].update(unexpected=True)),
        (_analysis_state, lambda state: state["analysis"].update(unexpected=True)),
        (_analysis_state, lambda state: state["analysis"]["claims"][0].update(unexpected=True)),
    ],
)
def test_analysis_state_schema_rejects_unknown_properties(state_builder, mutation):
    from paperctl._support.schema import validate_artifact

    state = state_builder()
    mutation(state)

    with pytest.raises(ValidationError):
        validate_artifact("analysis-state.schema.json", state)


def test_manifest_schema_excludes_status_and_disposition_fields():
    from paperctl._support.schema import validate_artifact

    manifest = _manifest()

    validate_artifact("manifest.schema.json", manifest)

    manifest["experiments"][0]["execution_status"] = "completed"
    with pytest.raises(ValidationError):
        validate_artifact("manifest.schema.json", manifest)


def test_manifest_relative_paths_must_be_posix_repo_relative():
    from paperctl._support.schema import validate_artifact

    validate_artifact("manifest.schema.json", _manifest())

    for invalid_path in [
        "questions\\q001\\experiments\\exp001",
        "C:\\repo\\exp",
    ]:
        manifest = _manifest()
        manifest["experiments"][0]["experiment_path"] = invalid_path

        with pytest.raises(ValidationError):
            validate_artifact("manifest.schema.json", manifest)


def test_evidence_packet_schema_has_closed_reason_codes_and_status_fields():
    from paperctl._support.schema import validate_artifact

    packet = _evidence_packet()

    validate_artifact("evidence-packet.schema.json", packet)

    packet["reason_codes"] = ["made_up_reason"]
    with pytest.raises(ValidationError):
        validate_artifact("evidence-packet.schema.json", packet)


def test_evidence_packet_schema_requires_generated_metadata():
    from paperctl._support.schema import validate_artifact

    validate_artifact("evidence-packet.schema.json", _evidence_packet())

    missing_inventory = _evidence_packet()
    del missing_inventory["inventory_path"]
    with pytest.raises(ValidationError):
        validate_artifact("evidence-packet.schema.json", missing_inventory)

    missing_fingerprint = _evidence_packet()
    del missing_fingerprint["fingerprint"]
    with pytest.raises(ValidationError):
        validate_artifact("evidence-packet.schema.json", missing_fingerprint)


def test_render_state_schema_requires_generated_metadata_and_fingerprint_contract():
    from paperctl._support.schema import validate_artifact

    validate_artifact("render-state.schema.json", _render_state())

    for key in ["fingerprint", "manifest_sha256", "evidence_packet_sha256"]:
        state = _render_state()
        del state[key]
        with pytest.raises(ValidationError):
            validate_artifact("render-state.schema.json", state)

    for key in [
        "stage",
        "schema_version",
        "renderer_version",
        "config_sha256",
        "manifest_path",
        "manifest_sha256",
        "evidence_packet_sha256",
        "draft_path",
        "draft_sha256",
        "input_counts",
        "fingerprint_sha256",
    ]:
        state = _render_state()
        del state["fingerprint"][key]
        with pytest.raises(ValidationError):
            validate_artifact("render-state.schema.json", state)


def test_evidence_packet_relative_paths_must_be_posix_repo_relative():
    from paperctl._support.schema import validate_artifact

    validate_artifact("evidence-packet.schema.json", _evidence_packet())

    for invalid_path in [
        "questions\\q001\\experiments\\exp001",
        "C:\\repo\\exp",
    ]:
        packet = _evidence_packet(experiment_path=invalid_path)

        with pytest.raises(ValidationError):
            validate_artifact("evidence-packet.schema.json", packet)


def test_evidence_canonical_facts_require_full_selector_provenance():
    from paperctl._support.schema import validate_artifact

    packet = _evidence_packet(
        canonical_facts=[
            {
                "fact_id": "measured_throughput",
                "value": 13.585,
                "value_type": "number",
                "unit": "pages_per_second",
                "source": _strict_json_source(),
            }
        ]
    )
    validate_artifact("evidence-packet.schema.json", packet)

    packet["canonical_facts"][0]["source"] = {
        "path": "questions/q001-throughput/experiments/exp001-baseline/outputs/result.json"
    }
    with pytest.raises(ValidationError):
        validate_artifact("evidence-packet.schema.json", packet)


def test_evidence_observed_values_require_full_selector_provenance():
    from paperctl._support.schema import validate_artifact

    packet = _evidence_packet(
        observed_values=[
            {
                "value": 13.585,
                "value_type": "number",
                "unit": "pages_per_second",
                "source": _strict_json_source(),
            }
        ]
    )
    validate_artifact("evidence-packet.schema.json", packet)

    packet["observed_values"][0]["source"] = {
        "path": "questions/q001-throughput/experiments/exp001-baseline/outputs/result.json"
    }
    with pytest.raises(ValidationError):
        validate_artifact("evidence-packet.schema.json", packet)


def test_evidence_canonical_fact_value_type_must_match_value():
    from paperctl._support.schema import validate_artifact

    packet = _evidence_packet(
        canonical_facts=[
            {
                "fact_id": "measured_throughput",
                "value": "13.585",
                "value_type": "number",
                "unit": "pages_per_second",
                "source": _strict_json_source(),
            }
        ]
    )
    with pytest.raises(ValidationError):
        validate_artifact("evidence-packet.schema.json", packet)

    packet["canonical_facts"][0]["value"] = 13.585
    packet["canonical_facts"][0]["value_type"] = "integer"
    with pytest.raises(ValidationError):
        validate_artifact("evidence-packet.schema.json", packet)

    packet["canonical_facts"][0]["value"] = 1
    packet["canonical_facts"][0]["value_type"] = "number"
    validate_artifact("evidence-packet.schema.json", packet)


def test_evidence_observed_value_type_must_match_value():
    from paperctl._support.schema import validate_artifact

    packet = _evidence_packet(
        observed_values=[
            {
                "value": "13.585",
                "value_type": "number",
                "unit": "pages_per_second",
                "source": _strict_json_source(),
            }
        ]
    )
    with pytest.raises(ValidationError):
        validate_artifact("evidence-packet.schema.json", packet)

    packet["observed_values"][0]["value"] = 13.585
    packet["observed_values"][0]["value_type"] = "integer"
    with pytest.raises(ValidationError):
        validate_artifact("evidence-packet.schema.json", packet)

    packet["observed_values"][0]["value"] = 1
    packet["observed_values"][0]["value_type"] = "number"
    validate_artifact("evidence-packet.schema.json", packet)


def test_evidence_json_pointer_selector_must_be_empty_or_start_with_slash():
    from paperctl._support.schema import validate_artifact

    packet = _evidence_packet(
        canonical_facts=[
            {
                "fact_id": "measured_throughput",
                "value": 13.585,
                "value_type": "number",
                "unit": "pages_per_second",
                "source": _strict_json_source(selector=""),
            }
        ]
    )
    validate_artifact("evidence-packet.schema.json", packet)

    packet["canonical_facts"][0]["source"]["selector"] = "metrics/pages_per_second"
    with pytest.raises(ValidationError):
        validate_artifact("evidence-packet.schema.json", packet)

    packet["canonical_facts"][0]["source"]["selector"] = "/bad/~2escape"
    with pytest.raises(ValidationError):
        validate_artifact("evidence-packet.schema.json", packet)


def test_inventory_regular_files_require_byte_size_and_sha256():
    from paperctl._support.schema import validate_artifact

    inventory = {
        "schema_version": 1,
        "artifact_type": "artifact_inventory",
        "question_path": "questions/q001-throughput",
        "experiment_path": "questions/q001-throughput/experiments/exp001-baseline",
        "counts": {
            "artifact_count": 1,
            "excluded_artifact_count": 0,
        },
        "excluded_artifacts": [],
        "artifacts": [
            {
                "path": "questions/q001-throughput/experiments/exp001-baseline/outputs/result.json",
                "file_type": "regular",
                "byte_size": 123,
                "sha256": "sha256:" + "c" * 64,
                "kind": "json",
                "support_status": "supported",
            }
        ],
    }
    validate_artifact("artifact-inventory.schema.json", inventory)

    del inventory["artifacts"][0]["byte_size"]
    with pytest.raises(ValidationError):
        validate_artifact("artifact-inventory.schema.json", inventory)

    inventory["artifacts"][0]["byte_size"] = 123
    del inventory["artifacts"][0]["sha256"]
    with pytest.raises(ValidationError):
        validate_artifact("artifact-inventory.schema.json", inventory)


def test_experiment_report_schema_is_a_source_contract_without_artifact_type():
    from paperctl._support.schema import validate_artifact

    validate_artifact("experiment-report.schema.json", _experiment_report())


def test_experiment_report_value_type_must_match_value():
    from paperctl._support.schema import validate_artifact

    with pytest.raises(ValidationError):
        validate_artifact(
            "experiment-report.schema.json",
            _experiment_report(value="13.585", value_type="number"),
        )

    with pytest.raises(ValidationError):
        validate_artifact(
            "experiment-report.schema.json",
            _experiment_report(value=13.585, value_type="integer"),
        )

    validate_artifact(
        "experiment-report.schema.json",
        _experiment_report(value=1, value_type="number"),
    )


def test_json_pointer_selectors_must_be_empty_or_start_with_slash():
    from paperctl._support.schema import validate_artifact

    validate_artifact(
        "experiment-report.schema.json",
        _experiment_report(
            source={
                "path": "outputs/hpi_2wpg_summary.json",
                "selector_type": "json_pointer",
                "selector": "",
            }
        ),
    )
    with pytest.raises(ValidationError):
        validate_artifact(
            "experiment-report.schema.json",
            _experiment_report(
                source={
                    "path": "outputs/hpi_2wpg_summary.json",
                    "selector_type": "json_pointer",
                    "selector": "metrics/pages_per_second",
                }
            ),
        )

    with pytest.raises(ValidationError):
        validate_artifact(
            "experiment-report.schema.json",
            _experiment_report(
                source={
                    "path": "outputs/hpi_2wpg_summary.json",
                    "selector_type": "json_pointer",
                    "selector": "/bad/~2escape",
                }
            ),
        )

    validate_artifact("paper-config.schema.json", _paper_config(selector=""))
    with pytest.raises(ValidationError):
        validate_artifact(
            "paper-config.schema.json",
            _paper_config(selector="metrics/pages_per_second"),
        )

    with pytest.raises(ValidationError):
        validate_artifact(
            "paper-config.schema.json",
            _paper_config(selector="/bad/~2escape"),
        )


def test_paper_config_canonical_fact_keys_must_be_relative_experiment_paths():
    from paperctl._support.schema import validate_artifact

    validate_artifact("paper-config.schema.json", _paper_config())

    for invalid_key in [
        "/absolute/experiment",
        "../escape",
        "questions/q001/../escape",
        "questions\\q001\\experiments\\exp001",
        "C:\\repo\\exp",
    ]:
        config = _paper_config()
        mappings = config["evidence"]["canonical_facts"]
        mappings[invalid_key] = mappings.pop(
            "questions/q001-throughput/experiments/exp001-baseline"
        )

        with pytest.raises(ValidationError):
            validate_artifact("paper-config.schema.json", config)


def test_dump_json_bytes_sorts_keys_and_ends_with_newline():
    from paperctl._support.jsonio import dump_json_bytes

    assert dump_json_bytes({"z": 1, "a": {"b": 2}}) == b'{"a":{"b":2},"z":1}\n'


def test_dump_json_bytes_rejects_non_finite_numbers():
    from paperctl._support.jsonio import dump_json_bytes

    with pytest.raises(ValueError):
        dump_json_bytes({"value": float("nan")})

    with pytest.raises(ValueError):
        dump_json_bytes({"value": float("inf")})


def test_write_json_atomic_uses_deterministic_encoding(tmp_path):
    from paperctl._support.jsonio import write_json_atomic

    path = tmp_path / "nested" / "data.json"
    write_json_atomic(path, {"z": 1, "a": 2})

    assert path.read_bytes() == b'{"a":2,"z":1}\n'


def test_write_json_atomic_removes_temp_file_when_fsync_fails(tmp_path, monkeypatch):
    from paperctl._support import jsonio

    path = tmp_path / "data.json"

    def fail_fsync(_file_descriptor):
        raise OSError("fsync failed")

    monkeypatch.setattr(jsonio.os, "fsync", fail_fsync)

    with pytest.raises(OSError):
        jsonio.write_json_atomic(path, {"a": 1})

    assert not path.exists()
    assert list(tmp_path.glob(".data.json.*.tmp")) == []


def test_sha256_helpers_use_lowercase_prefixed_hex(tmp_path):
    from paperctl._support.hashing import sha256_bytes, sha256_file

    digest = sha256_bytes(b"abc")
    assert digest == "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest)

    path = tmp_path / "data.bin"
    path.write_bytes(b"abc")
    assert sha256_file(path) == digest


def test_canonical_json_config_hash_ignores_yaml_formatting():
    from paperctl._support.hashing import canonical_json_hash, sha256_bytes
    from paperctl._support.jsonio import dump_json_bytes

    compact_yaml = "schema_version: 1\nquestions: {root: questions, pattern: 'q*'}\n"
    expanded_yaml = """
    questions:
      pattern: q*
      root: questions
    schema_version: 1
    """

    compact = yaml.safe_load(compact_yaml)
    expanded = yaml.safe_load(expanded_yaml)

    assert compact == expanded
    assert canonical_json_hash(compact) == canonical_json_hash(expanded)
    assert canonical_json_hash(compact) == sha256_bytes(dump_json_bytes(compact))
