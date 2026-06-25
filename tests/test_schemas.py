import re

import pytest
import yaml
from jsonschema import ValidationError


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


def test_manifest_schema_excludes_status_and_disposition_fields():
    from paperctl._support.schema import validate_artifact

    manifest = {
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

    validate_artifact("manifest.schema.json", manifest)

    manifest["experiments"][0]["execution_status"] = "completed"
    with pytest.raises(ValidationError):
        validate_artifact("manifest.schema.json", manifest)


def test_evidence_packet_schema_has_closed_reason_codes_and_status_fields():
    from paperctl._support.schema import validate_artifact

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
        },
        "canonical_facts": [],
        "observed_values": [],
        "previews": [],
        "diagnostics": [],
        "conflicts": [],
        "unsupported_artifacts": [],
        "warnings": [],
    }

    validate_artifact("evidence-packet.schema.json", packet)

    packet["reason_codes"] = ["made_up_reason"]
    with pytest.raises(ValidationError):
        validate_artifact("evidence-packet.schema.json", packet)


def test_experiment_report_schema_is_a_source_contract_without_artifact_type():
    from paperctl._support.schema import validate_artifact

    report = {
        "schema_version": 1,
        "execution_status": "completed",
        "canonical_facts": [
            {
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
        ],
    }

    validate_artifact("experiment-report.schema.json", report)


def test_dump_json_bytes_sorts_keys_and_ends_with_newline():
    from paperctl._support.jsonio import dump_json_bytes

    assert dump_json_bytes({"z": 1, "a": {"b": 2}}) == b'{"a":{"b":2},"z":1}\n'


def test_dump_json_bytes_rejects_non_finite_numbers():
    from paperctl._support.jsonio import dump_json_bytes

    with pytest.raises(ValueError):
        dump_json_bytes({"value": float("nan")})

    with pytest.raises(ValueError):
        dump_json_bytes({"value": float("inf")})


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
