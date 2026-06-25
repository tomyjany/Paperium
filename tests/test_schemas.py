import re

import pytest
import yaml
from jsonschema import Draft202012Validator, ValidationError


def _evidence_packet(**overrides):
    packet = {
        "schema_version": 1,
        "artifact_type": "evidence_packet",
        "question_path": "questions/q001-throughput",
        "experiment_path": "questions/q001-throughput/experiments/exp001-baseline",
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
    ]:
        Draft202012Validator.check_schema(load_schema(name))


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
