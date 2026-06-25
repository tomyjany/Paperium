from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import yaml

from conftest import copy_fixture_repo, read_json, run_paperctl
from paperctl import normalize as normalize_module
from paperctl._support.schema import validate_artifact


MANIFEST_PATH = Path("paper/work/manifest.json")


def _run_prerequisites(repo: Path) -> dict[str, Any]:
    discovered = run_paperctl(repo, "discover")
    assert discovered.returncode == 0, discovered.stderr
    inventoried = run_paperctl(repo, "inventory")
    assert inventoried.returncode == 0, inventoried.stderr
    return read_json(repo / MANIFEST_PATH)


def _normalize(repo: Path, *args: str):
    return run_paperctl(repo, "normalize", *args)


def _entry(manifest: dict[str, Any], experiment_ref: str) -> dict[str, Any]:
    return next(
        entry for entry in manifest["experiments"] if entry["experiment_ref"] == experiment_ref
    )


def _packet(repo: Path, manifest: dict[str, Any], experiment_ref: str) -> dict[str, Any]:
    packet = read_json(repo / _entry(manifest, experiment_ref)["evidence_path"])
    validate_artifact("evidence-packet.schema.json", packet)
    return packet


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _load_config(repo: Path) -> dict[str, Any]:
    with (repo / "paper.yaml").open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _write_config(repo: Path, config: dict[str, Any]) -> None:
    (repo / "paper.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def _add_experiment(repo: Path, name: str) -> Path:
    experiment = repo / "questions" / "q001-throughput" / "experiments" / name
    experiment.mkdir(parents=True)
    (experiment / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    return experiment


def _add_bare_experiment(repo: Path, name: str) -> Path:
    experiment = repo / "questions" / "q001-throughput" / "experiments" / name
    experiment.mkdir(parents=True)
    return experiment


def _add_canonical_mapping(
    repo: Path,
    experiment_name: str,
    *,
    fact_id: str = "configured_metric",
    source: str = "outputs/metrics.json",
    selector: str = "/metric",
    expected_type: str = "number",
    unit: str | None = "widgets",
) -> None:
    config = _load_config(repo)
    experiment_path = f"questions/q001-throughput/experiments/{experiment_name}"
    config["evidence"]["canonical_facts"][experiment_path] = [
        {
            "fact_id": fact_id,
            "source": source,
            "selector_type": "json_pointer",
            "selector": selector,
            "expected_type": expected_type,
            "unit": unit,
        }
    ]
    _write_config(repo, config)


def test_normalize_requires_fresh_manifest_and_inventory(tmp_path):
    repo = copy_fixture_repo(tmp_path)

    missing = _normalize(repo)

    assert missing.returncode == 2
    assert "missing discovery manifest" in missing.stderr

    manifest = _run_prerequisites(repo)
    Path(repo / _entry(manifest, "exp001-completed")["inventory_path"]).unlink()

    missing_inventory = _normalize(repo)

    assert missing_inventory.returncode == 2
    assert "missing artifact inventory" in missing_inventory.stderr
    assert "run paperctl inventory first" in missing_inventory.stderr

    _run_prerequisites(repo)
    result = _normalize(repo)
    assert result.returncode == 0, result.stderr

    experiment = repo / "questions" / "q001-throughput" / "experiments" / "exp001-completed"
    (experiment / "late.json").write_text('{"late": true}\n', encoding="utf-8")

    stale = _normalize(repo)

    assert stale.returncode == 2
    assert "stale artifact inventory" in stale.stderr


def test_normalize_rejects_final_experiment_path_symlink_when_verifying_inventory(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    manifest = _run_prerequisites(repo)
    entry = _entry(manifest, "exp002-incomplete")
    experiment = repo / entry["experiment_path"]
    outside = tmp_path / "outside-experiment"
    shutil.copytree(experiment, outside)
    shutil.rmtree(experiment)
    experiment.symlink_to(outside, target_is_directory=True)

    result = _normalize(repo)

    assert result.returncode == 2
    assert "manifest experiment path is a symlink" in result.stderr
    assert entry["experiment_path"] in result.stderr
    assert not (outside / "paper").exists()


def test_json_yaml_scalar_observations_use_json_pointer_and_canonical_bypasses_limits(
    tmp_path,
):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_experiment(repo, "exp010-json-yaml")
    _write_json(
        experiment / "outputs" / "metrics.json",
        {
            "skip0": 0,
            "skip1": 1,
            "skip2": 2,
            "skip3": 3,
            "deep": {"chosen": 123.5},
            "password": "open-sesame",
        },
    )
    (experiment / "outputs" / "config.yaml").write_text(
        "enabled: true\nnested:\n  label: baseline\napi_key: sk-secret-value\n",
        encoding="utf-8",
    )
    _add_canonical_mapping(
        repo,
        "exp010-json-yaml",
        fact_id="chosen_metric",
        source="outputs/metrics.json",
        selector="/deep/chosen",
        expected_type="number",
        unit="widgets/s",
    )
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    packet = _packet(repo, manifest, "exp010-json-yaml")
    assert packet["evidence_status"] == "available"
    assert packet["preanalysis_disposition"] == "analysis_candidate"
    assert packet["canonical_facts"] == [
        {
            "fact_id": "chosen_metric",
            "value": 123.5,
            "value_type": "number",
            "unit": "widgets/s",
            "source": {
                "path": "questions/q001-throughput/experiments/exp010-json-yaml/outputs/metrics.json",
                "source_hash": packet["canonical_facts"][0]["source"]["source_hash"],
                "selector_type": "json_pointer",
                "selector": "/deep/chosen",
                "adapter": "json",
                "adapter_version": "1",
            },
        }
    ]
    observed_selectors = {value["source"]["selector"] for value in packet["observed_values"]}
    assert "/deep/chosen" not in observed_selectors
    assert "/skip0" in observed_selectors
    assert "/enabled" in observed_selectors
    assert all(
        value["source"]["selector_type"] == "json_pointer" for value in packet["observed_values"]
    )
    serialized = json.dumps(packet, sort_keys=True)
    assert "open-sesame" not in serialized
    assert "sk-secret-value" not in serialized
    assert "[REDACTED]" in serialized
    assert packet["counts"]["redaction_count"] >= 2


def test_validated_report_canonical_facts_are_not_duplicated_as_observed_values(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    packet = _packet(repo, manifest, "exp001-completed")
    assert packet["execution_status"] == "completed"
    assert packet["canonical_facts"][0]["fact_id"] == "throughput_pages_per_second"
    observed = [
        value
        for value in packet["observed_values"]
        if value["source"]["path"].endswith("/outputs/experiment_report.json")
    ]
    assert all(value["source"]["selector"] != "/canonical_facts/0/value" for value in observed)


def test_report_number_value_type_accepts_integer_source_value(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_experiment(repo, "exp041-report-number-integer")
    _write_json(
        experiment / "outputs" / "experiment_report.json",
        {
            "schema_version": 1,
            "execution_status": "completed",
            "canonical_facts": [
                {
                    "fact_id": "whole_number_metric",
                    "value": 1,
                    "value_type": "number",
                    "unit": "count",
                    "source": {
                        "path": "outputs/experiment_report.json",
                        "selector_type": "json_pointer",
                        "selector": "/canonical_facts/0/value",
                    },
                }
            ],
        },
    )
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    packet = _packet(repo, manifest, "exp041-report-number-integer")
    assert packet["evidence_status"] == "available"
    assert packet["preanalysis_disposition"] == "analysis_candidate"
    assert "source_contract_type_mismatch" not in packet["reason_codes"]
    assert packet["canonical_facts"] == [
        {
            "fact_id": "whole_number_metric",
            "value": 1,
            "value_type": "number",
            "unit": "count",
            "source": {
                "path": (
                    "questions/q001-throughput/experiments/"
                    "exp041-report-number-integer/outputs/experiment_report.json"
                ),
                "source_hash": packet["canonical_facts"][0]["source"]["source_hash"],
                "selector_type": "json_pointer",
                "selector": "/canonical_facts/0/value",
                "adapter": "json",
                "adapter_version": "1",
            },
        }
    ]


def test_configured_number_expected_type_emits_integer_source_value_as_number(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_experiment(repo, "exp042-configured-number-integer")
    _write_json(experiment / "outputs" / "metrics.json", {"metric": 1})
    _add_canonical_mapping(
        repo,
        "exp042-configured-number-integer",
        fact_id="whole_number_metric",
        source="outputs/metrics.json",
        selector="/metric",
        expected_type="number",
        unit="count",
    )
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    packet = _packet(repo, manifest, "exp042-configured-number-integer")
    assert packet["canonical_facts"] == [
        {
            "fact_id": "whole_number_metric",
            "value": 1,
            "value_type": "number",
            "unit": "count",
            "source": {
                "path": (
                    "questions/q001-throughput/experiments/"
                    "exp042-configured-number-integer/outputs/metrics.json"
                ),
                "source_hash": packet["canonical_facts"][0]["source"]["source_hash"],
                "selector_type": "json_pointer",
                "selector": "/metric",
                "adapter": "json",
                "adapter_version": "1",
            },
        }
    ]


def test_secret_like_canonical_values_are_redacted(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_experiment(repo, "exp011-secret-canonical")
    _write_json(experiment / "outputs" / "secrets.json", {"api_key": "sk-live-secret"})
    _add_canonical_mapping(
        repo,
        "exp011-secret-canonical",
        fact_id="api_key",
        source="outputs/secrets.json",
        selector="/api_key",
        expected_type="string",
        unit=None,
    )
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    packet = _packet(repo, manifest, "exp011-secret-canonical")
    serialized = json.dumps(packet, sort_keys=True)
    assert "sk-live-secret" not in serialized
    assert packet["canonical_facts"][0]["value"] == "[REDACTED]"
    assert packet["counts"]["redaction_count"] >= 1


def test_secret_like_non_string_values_are_redacted_everywhere(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_experiment(repo, "exp012-secret-non-string")
    _write_json(
        experiment / "outputs" / "metrics.json",
        {
            "password": 12345,
            "token": False,
            "secret": None,
            "private_key": {"id": 67890},
            "safe": 1,
        },
    )
    (experiment / "outputs" / "config.yaml").write_text(
        "passwd: 24680\naccess_key: false\nplain: 2\n",
        encoding="utf-8",
    )
    (experiment / "outputs" / "events.jsonl").write_text(
        '{"api_key": 13579, "nested": {"token": 97531}, "plain": true}\n',
        encoding="utf-8",
    )
    _add_canonical_mapping(
        repo,
        "exp012-secret-non-string",
        fact_id="password",
        selector="/password",
        expected_type="integer",
        unit=None,
    )
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    packet = _packet(repo, manifest, "exp012-secret-non-string")
    assert packet["canonical_facts"][0]["value"] == "[REDACTED]"
    observed_by_selector = {
        value["source"]["selector"]: value["value"] for value in packet["observed_values"]
    }
    assert observed_by_selector["/token"] == "[REDACTED]"
    assert observed_by_selector["/secret"] == "[REDACTED]"
    assert observed_by_selector["/private_key/id"] == "[REDACTED]"
    assert observed_by_selector["/passwd"] == "[REDACTED]"
    assert observed_by_selector["/access_key"] == "[REDACTED]"
    assert observed_by_selector["/safe"] == 1
    jsonl_preview = next(
        preview
        for preview in packet["previews"]
        if preview["source"]["path"].endswith("/outputs/events.jsonl")
    )
    assert "13579" not in jsonl_preview["message"]
    assert "97531" not in jsonl_preview["message"]
    assert jsonl_preview["message"] == (
        '{"api_key": "[REDACTED]", "nested": {"token": "[REDACTED]"}, "plain": true}'
    )
    assert packet["counts"]["redaction_count"] >= 7


def test_report_contract_errors_block_experiment_evidence(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    mismatch = _add_experiment(repo, "exp011-report-mismatch")
    _write_json(mismatch / "outputs" / "source.json", {"metric": 41})
    _write_json(
        mismatch / "outputs" / "experiment_report.json",
        {
            "schema_version": 1,
            "execution_status": "completed",
            "canonical_facts": [
                {
                    "fact_id": "metric",
                    "value": 42,
                    "value_type": "integer",
                    "unit": "ms",
                    "source": {
                        "path": "outputs/source.json",
                        "selector_type": "json_pointer",
                        "selector": "/metric",
                    },
                }
            ],
        },
    )
    malformed = _add_experiment(repo, "exp012-report-malformed")
    _write_json(malformed / "outputs" / "experiment_report.json", {"schema_version": 1})
    unknown = _add_experiment(repo, "exp013-report-unknown")
    _write_json(
        unknown / "outputs" / "experiment_report.json",
        {"schema_version": 999, "canonical_facts": []},
    )
    missing = _add_experiment(repo, "exp014-report-missing")
    (missing / "outputs").mkdir()
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    mismatch_packet = _packet(repo, manifest, "exp011-report-mismatch")
    malformed_packet = _packet(repo, manifest, "exp012-report-malformed")
    unknown_packet = _packet(repo, manifest, "exp013-report-unknown")
    missing_packet = _packet(repo, manifest, "exp014-report-missing")
    assert mismatch_packet["preanalysis_disposition"] == "blocked"
    assert "source_contract_value_mismatch" in mismatch_packet["reason_codes"]
    assert malformed_packet["preanalysis_disposition"] == "blocked"
    assert "malformed_experiment_report" in malformed_packet["reason_codes"]
    assert unknown_packet["preanalysis_disposition"] == "blocked"
    assert "unknown_experiment_report_version" in unknown_packet["reason_codes"]
    assert "malformed_experiment_report" not in missing_packet["reason_codes"]
    assert "unknown_experiment_report_version" not in missing_packet["reason_codes"]


def test_missing_and_unsupported_only_evidence_block_preanalysis(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    _add_bare_experiment(repo, "exp015-empty")
    unsupported = _add_bare_experiment(repo, "exp016-unsupported-only")
    (unsupported / "outputs").mkdir()
    (unsupported / "outputs" / "model.bin").write_bytes(b"\x00\x01\x02")
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    empty_packet = _packet(repo, manifest, "exp015-empty")
    unsupported_packet = _packet(repo, manifest, "exp016-unsupported-only")
    assert empty_packet["evidence_status"] == "missing"
    assert empty_packet["preanalysis_disposition"] == "blocked"
    assert empty_packet["reason_codes"] == ["no_usable_evidence"]
    assert unsupported_packet["evidence_status"] == "unsupported"
    assert unsupported_packet["preanalysis_disposition"] == "blocked"
    assert "unsupported_only" in unsupported_packet["reason_codes"]


def test_canonical_conflicts_compare_value_type_and_unit_not_provenance(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    same = _add_experiment(repo, "exp015-same-canonical")
    _write_json(same / "outputs" / "a.json", {"metric": 10})
    _write_json(same / "outputs" / "b.json", {"metric": 10})
    _write_json(
        same / "outputs" / "experiment_report.json",
        {
            "schema_version": 1,
            "canonical_facts": [
                {
                    "fact_id": "metric",
                    "value": 10,
                    "value_type": "integer",
                    "unit": "ms",
                    "source": {
                        "path": "outputs/a.json",
                        "selector_type": "json_pointer",
                        "selector": "/metric",
                    },
                }
            ],
        },
    )
    config = _load_config(repo)
    config["evidence"]["canonical_facts"][
        "questions/q001-throughput/experiments/exp015-same-canonical"
    ] = [
        {
            "fact_id": "metric",
            "source": "outputs/b.json",
            "selector_type": "json_pointer",
            "selector": "/metric",
            "expected_type": "integer",
            "unit": "ms",
        }
    ]
    _write_config(repo, config)
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    existing_conflict = _packet(repo, manifest, "exp003-structured-conflict")
    same_packet = _packet(repo, manifest, "exp015-same-canonical")
    assert existing_conflict["evidence_status"] == "conflicting"
    assert existing_conflict["preanalysis_disposition"] == "needs_human_review"
    assert "canonical_conflict" in existing_conflict["reason_codes"]
    assert existing_conflict["conflicts"][0]["fact_id"] == "throughput_pages_per_second"
    assert same_packet["evidence_status"] == "available"
    assert "canonical_conflict" not in same_packet["reason_codes"]
    assert len(same_packet["canonical_facts"]) == 1


def test_user_configured_canonical_fact_errors_are_deterministic_configuration_failures(
    tmp_path,
):
    cases = [
        (
            "missing-file",
            {"source": "outputs/missing.json"},
            "canonical source file does not exist",
        ),
        ("invalid-selector", {"selector": "/missing"}, "canonical selector did not resolve"),
        ("type-mismatch", {"expected_type": "string"}, "canonical selector type mismatch"),
        ("duplicate-id", {"duplicate": True}, "duplicate configured canonical fact id"),
        (
            "path-escape",
            {"source": "../outside.json"},
            "configured path must be repo-relative POSIX",
        ),
        (
            "symlink-escape",
            {"source": "outputs/link.json"},
            "canonical source resolves outside repository",
        ),
    ]
    for case_name, override, expected in cases:
        repo = copy_fixture_repo(tmp_path / case_name)
        experiment = _add_experiment(repo, f"exp020-{case_name}")
        _write_json(experiment / "outputs" / "metrics.json", {"metric": 7})
        source = override.get("source", "outputs/metrics.json")
        if case_name == "symlink-escape":
            outside = tmp_path / f"{case_name}-outside.json"
            outside.write_text('{"metric": 7}\n', encoding="utf-8")
            (experiment / "outputs" / "link.json").symlink_to(outside)
        _add_canonical_mapping(
            repo,
            f"exp020-{case_name}",
            source=source,
            selector=override.get("selector", "/metric"),
            expected_type=override.get("expected_type", "number"),
        )
        if override.get("duplicate"):
            config = _load_config(repo)
            key = f"questions/q001-throughput/experiments/exp020-{case_name}"
            config["evidence"]["canonical_facts"][key].append(
                dict(config["evidence"]["canonical_facts"][key][0])
            )
            _write_config(repo, config)

        if case_name == "path-escape":
            result = run_paperctl(repo, "discover")
        else:
            _run_prerequisites(repo)
            result = _normalize(repo)

        assert result.returncode == 2, result.stderr
        assert expected in result.stderr


def test_configured_canonical_json_pointer_rejects_negative_array_index(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_experiment(repo, "exp020-negative-array-index")
    _write_json(experiment / "outputs" / "metrics.json", {"items": [10]})
    _add_canonical_mapping(
        repo,
        "exp020-negative-array-index",
        selector="/items/-1",
        expected_type="number",
    )
    _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 2
    assert "canonical selector did not resolve" in result.stderr
    assert "/items/-1" in result.stderr


def test_duplicate_configured_fact_id_with_different_sources_is_configuration_failure(
    tmp_path,
):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_experiment(repo, "exp021-duplicate-configured-id")
    _write_json(experiment / "outputs" / "a.json", {"metric": 7})
    _write_json(experiment / "outputs" / "b.json", {"metric": 8})
    config = _load_config(repo)
    experiment_path = "questions/q001-throughput/experiments/exp021-duplicate-configured-id"
    config["evidence"]["canonical_facts"][experiment_path] = [
        {
            "fact_id": "metric",
            "source": "outputs/a.json",
            "selector_type": "json_pointer",
            "selector": "/metric",
            "expected_type": "number",
            "unit": "widgets",
        },
        {
            "fact_id": "metric",
            "source": "outputs/b.json",
            "selector_type": "json_pointer",
            "selector": "/metric",
            "expected_type": "number",
            "unit": "widgets",
        },
    ]
    _write_config(repo, config)
    _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 2
    assert (
        "duplicate configured canonical fact id: "
        "questions/q001-throughput/experiments/exp021-duplicate-configured-id: metric"
        in result.stderr
    )


def test_preview_only_markdown_and_logs_are_available_analysis_candidates(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    packet = _packet(repo, manifest, "exp005-unsupported-and-previews")
    assert packet["evidence_status"] == "available"
    assert packet["preanalysis_disposition"] == "analysis_candidate"
    assert packet["observed_values"] == []
    assert packet["previews"]
    assert packet["diagnostics"]
    assert packet["unsupported_artifacts"]


def test_csv_and_jsonl_numeric_summaries_are_diagnostics_not_observed_values(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_experiment(repo, "exp030-tabular")
    (experiment / "outputs").mkdir()
    (experiment / "outputs" / "table.csv").write_text(
        "name,score\nalpha,1.5\nbeta,\ngamma,2.5\n", encoding="utf-8"
    )
    (experiment / "outputs" / "events.jsonl").write_text(
        '{"score": 1}\n{"score": "skip"}\n{"score": 2}\n', encoding="utf-8"
    )
    config = _load_config(repo)
    config["evidence"]["extraction_limits"]["preview_rows"] = 3
    _write_config(repo, config)
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    packet = _packet(repo, manifest, "exp030-tabular")
    assert packet["evidence_status"] == "available"
    assert packet["observed_values"] == []
    csv_summary = next(
        diagnostic
        for diagnostic in packet["diagnostics"]
        if diagnostic.get("calculation_label") == "csv_numeric_column_summary"
        and diagnostic.get("column") == "score"
    )
    assert csv_summary["source"]["path"].endswith("/outputs/table.csv")
    assert csv_summary["source"]["source_hash"].startswith("sha256:")
    assert csv_summary["source"]["line_start"] == 2
    assert csv_summary["source"]["line_end"] == 4
    assert csv_summary["inspected_row_start"] == 1
    assert csv_summary["inspected_row_end"] == 3
    assert csv_summary["inspected_row_count"] == 3
    assert csv_summary["numeric_value_count"] == 2
    assert csv_summary["omitted_value_count"] == 1
    assert csv_summary["summary"] == {"count": 2, "max": 2.5, "min": 1.5}
    csv_previews = [
        preview
        for preview in packet["previews"]
        if preview["source"]["path"].endswith("/outputs/table.csv")
    ]
    assert [
        (preview["source"]["line_start"], preview["source"]["line_end"]) for preview in csv_previews
    ] == [(2, 2), (3, 3), (4, 4)]
    jsonl_summary = next(
        diagnostic
        for diagnostic in packet["diagnostics"]
        if diagnostic.get("calculation_label") == "jsonl_numeric_field_summary"
        and diagnostic.get("field") == "score"
    )
    assert jsonl_summary["source"]["path"].endswith("/outputs/events.jsonl")
    assert jsonl_summary["source"]["source_hash"].startswith("sha256:")
    assert jsonl_summary["source"]["line_start"] == 1
    assert jsonl_summary["source"]["line_end"] == 3
    assert jsonl_summary["inspected_line_start"] == 1
    assert jsonl_summary["inspected_line_end"] == 3
    assert jsonl_summary["inspected_line_count"] == 3
    assert jsonl_summary["numeric_value_count"] == 2
    assert jsonl_summary["omitted_value_count"] == 1
    assert jsonl_summary["summary"] == {"count": 2, "max": 2.0, "min": 1.0}


def test_over_limit_csv_markdown_jsonl_and_log_extraction_is_bounded(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_bare_experiment(repo, "exp035-large-supported-files")
    (experiment / "outputs").mkdir()
    (experiment / "outputs" / "table.csv").write_text(
        "score\n" + "".join(f"{index}\n" for index in range(30)),
        encoding="utf-8",
    )
    (experiment / "outputs" / "notes.md").write_text(
        "# Heading\n" + ("body line\n" * 12),
        encoding="utf-8",
    )
    (experiment / "outputs" / "events.jsonl").write_text(
        "".join(f'{{"score": {index}}}\n' for index in range(20)),
        encoding="utf-8",
    )
    (experiment / "outputs" / "run.log").write_text(
        "".join(f"line {index}\n" for index in range(20)),
        encoding="utf-8",
    )
    config = _load_config(repo)
    config["evidence"]["extraction_limits"]["maximum_file_bytes"] = 40
    _write_config(repo, config)
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    packet = _packet(repo, manifest, "exp035-large-supported-files")
    assert "normalization_truncated" in packet["reason_codes"]
    assert not [
        record
        for record in packet["previews"] + packet["diagnostics"]
        if record["source"]["path"].endswith(("/table.csv", "/notes.md"))
    ]
    truncation_warnings = [
        warning
        for warning in packet["warnings"]
        if warning.get("warning_type") == "byte_limit_truncated"
    ]
    assert sorted(
        (
            warning["source"]["path"].rsplit("/", 1)[-1],
            warning["inspected_byte_count"],
            warning["omitted_byte_count"] > 0,
        )
        for warning in truncation_warnings
    ) == [
        ("events.jsonl", 40, True),
        ("notes.md", 0, True),
        ("run.log", 40, True),
        ("table.csv", 0, True),
    ]
    assert any(
        diagnostic.get("calculation_label") == "jsonl_numeric_field_summary"
        and diagnostic["source"]["path"].endswith("/events.jsonl")
        for diagnostic in packet["diagnostics"]
    )
    log_summary = next(
        diagnostic
        for diagnostic in packet["diagnostics"]
        if diagnostic.get("calculation_label") == "log_line_summary"
        and diagnostic["source"]["path"].endswith("/run.log")
    )
    assert log_summary["byte_limit_truncated"] is True
    assert log_summary["omitted_byte_count"] > 0


def test_evidence_fingerprint_uses_inventory_hashes_without_rehashing_sources(
    tmp_path, monkeypatch
):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_bare_experiment(repo, "exp036-fingerprint-large-supported-files")
    (experiment / "outputs").mkdir()
    (experiment / "outputs" / "table.csv").write_text(
        "score\n" + "".join(f"{index}\n" for index in range(30)),
        encoding="utf-8",
    )
    (experiment / "outputs" / "notes.md").write_text(
        "# Heading\n" + ("body line\n" * 12),
        encoding="utf-8",
    )
    (experiment / "outputs" / "events.jsonl").write_text(
        "".join(f'{{"score": {index}}}\n' for index in range(20)),
        encoding="utf-8",
    )
    (experiment / "outputs" / "run.log").write_text(
        "".join(f"line {index}\n" for index in range(20)),
        encoding="utf-8",
    )
    config = _load_config(repo)
    config["evidence"]["extraction_limits"]["maximum_file_bytes"] = 40
    _write_config(repo, config)
    manifest = _run_prerequisites(repo)
    entry = _entry(manifest, "exp036-fingerprint-large-supported-files")
    inventory = read_json(repo / entry["inventory_path"])
    source_paths = {
        artifact["path"]
        for artifact in inventory["artifacts"]
        if artifact["file_type"] == "regular" and artifact["support_status"] == "supported"
    }

    import paperctl._support.fingerprints as fingerprints

    original_sha256_file = fingerprints.sha256_file

    def reject_source_rehash(path: Path) -> str:
        relative = path.relative_to(repo).as_posix()
        if relative in source_paths:
            raise AssertionError(f"normalize rehashed source file: {relative}")
        return original_sha256_file(path)

    monkeypatch.setattr(fingerprints, "sha256_file", reject_source_rehash)

    packet = normalize_module._build_packet(
        repo, config, entry, inventory, MANIFEST_PATH.as_posix()
    )

    fingerprint_source_hashes = {
        source["path"]: source["sha256"] for source in packet["fingerprint"]["source_files"]
    }
    inventory_source_hashes = {
        artifact["path"]: artifact["sha256"]
        for artifact in inventory["artifacts"]
        if artifact["file_type"] == "regular" and artifact["kind"] not in {"binary", "unknown"}
    }
    assert fingerprint_source_hashes == inventory_source_hashes


def test_supported_text_decode_error_after_inventory_sniff_is_deterministic(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_bare_experiment(repo, "exp035-invalid-utf8-csv")
    (experiment / "outputs").mkdir()
    csv_path = experiment / "outputs" / "table.csv"
    csv_path.write_bytes(b"score\n1\n" + (b"2\n" * 33000) + b"\xff\n")
    config = _load_config(repo)
    config["evidence"]["extraction_limits"]["maximum_file_bytes"] = csv_path.stat().st_size + 1
    _write_config(repo, config)
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    packet = _packet(repo, manifest, "exp035-invalid-utf8-csv")
    assert any(
        diagnostic["source"]["path"].endswith("/outputs/table.csv")
        and "could not decode CSV" in diagnostic["message"]
        for diagnostic in packet["diagnostics"]
    )


def test_log_diagnostics_record_fixed_warning_error_patterns_by_line(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_bare_experiment(repo, "exp036-log-patterns")
    (experiment / "outputs").mkdir()
    (experiment / "outputs" / "run.log").write_text(
        "setup\n"
        "WARN cache warmed slowly\n"
        "ERROR failed once\n"
        "WARNING retrying\n"
        "Fatal stop\n"
        "Traceback (most recent call last):\n",
        encoding="utf-8",
    )
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    packet = _packet(repo, manifest, "exp036-log-patterns")
    matches = [
        diagnostic
        for diagnostic in packet["diagnostics"]
        if diagnostic.get("calculation_label") == "log_pattern_match"
    ]
    assert [
        (match["pattern_label"], match["source"]["line_start"], match["source"]["line_end"])
        for match in matches
    ] == [
        ("WARN", 2, 2),
        ("ERROR", 3, 3),
        ("WARNING", 4, 4),
        ("FATAL", 5, 5),
        ("TRACEBACK", 6, 6),
    ]
    assert all(match["source"]["source_hash"].startswith("sha256:") for match in matches)


def test_csv_and_jsonl_previews_redact_secret_columns_and_keys(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_bare_experiment(repo, "exp031-secret-previews")
    (experiment / "outputs").mkdir()
    (experiment / "outputs" / "table.csv").write_text(
        "name,api_key,password\nalpha,sk-csv-key,hunter2\n",
        encoding="utf-8",
    )
    (experiment / "outputs" / "events.jsonl").write_text(
        '{"name": "alpha", "access_key": "ak-jsonl", "nested": {"token": "nested-token"}}\n',
        encoding="utf-8",
    )
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    packet = _packet(repo, manifest, "exp031-secret-previews")
    serialized = json.dumps(packet, sort_keys=True)
    assert "sk-csv-key" not in serialized
    assert "hunter2" not in serialized
    assert "ak-jsonl" not in serialized
    assert "nested-token" not in serialized
    assert packet["counts"]["redaction_count"] == 4
    assert serialized.count("[REDACTED]") >= 4
    redaction_warnings = [
        warning for warning in packet["warnings"] if warning.get("warning_type") == "redaction"
    ]
    assert sorted(
        (warning["source"]["path"].rsplit("/", 1)[-1], warning["redaction_count"])
        for warning in redaction_warnings
    ) == [("events.jsonl", 2), ("table.csv", 2)]
    assert all(warning["redaction_category"] == "secret_like" for warning in redaction_warnings)
    assert "sk-csv-key" not in json.dumps(redaction_warnings, sort_keys=True)


def test_raw_text_previews_redact_quoted_json_style_secret_assignments(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_bare_experiment(repo, "exp043-json-style-secret-previews")
    (experiment / "outputs").mkdir()
    (experiment / "outputs" / "events.jsonl").write_text(
        '{"api_key": "sk-jsonl-preview-secret",\n',
        encoding="utf-8",
    )
    (experiment / "outputs" / "notes.md").write_text(
        '# {"token": "sk-markdown-preview-secret",\n',
        encoding="utf-8",
    )
    (experiment / "outputs" / "run.log").write_text(
        'INFO payload={"access_key": "sk-log-preview-secret", "ok": true}\n',
        encoding="utf-8",
    )
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    packet = _packet(repo, manifest, "exp043-json-style-secret-previews")
    serialized = json.dumps(packet, sort_keys=True)
    assert "sk-jsonl-preview-secret" not in serialized
    assert "sk-markdown-preview-secret" not in serialized
    assert "sk-log-preview-secret" not in serialized
    preview_messages = {
        Path(preview["source"]["path"]).name: preview["message"] for preview in packet["previews"]
    }
    assert preview_messages["events.jsonl"] == '{"api_key": "[REDACTED]",'
    assert "[REDACTED]" in preview_messages["notes.md"]
    assert "[REDACTED]" in preview_messages["run.log"]
    assert packet["counts"]["redaction_count"] == 3


def test_csv_and_jsonl_secret_numeric_fields_are_not_summarized(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_bare_experiment(repo, "exp032-secret-numeric-diagnostics")
    (experiment / "outputs").mkdir()
    (experiment / "outputs" / "table.csv").write_text(
        "name,password,score\nalpha,871923451,1.5\nbeta,619283745,2.5\n",
        encoding="utf-8",
    )
    (experiment / "outputs" / "events.jsonl").write_text(
        '{"api_key": 248613579, "score": 1}\n{"api_key": 975312468, "score": 2}\n',
        encoding="utf-8",
    )
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    packet = _packet(repo, manifest, "exp032-secret-numeric-diagnostics")
    serialized = json.dumps(packet, sort_keys=True)
    for secret_value in ("871923451", "619283745", "248613579", "975312468"):
        assert secret_value not in serialized
    assert packet["counts"]["redaction_count"] == 4
    assert not any(
        diagnostic.get("calculation_label") == "csv_numeric_column_summary"
        and diagnostic.get("column") == "password"
        for diagnostic in packet["diagnostics"]
    )
    assert not any(
        diagnostic.get("calculation_label") == "jsonl_numeric_field_summary"
        and diagnostic.get("field") == "api_key"
        for diagnostic in packet["diagnostics"]
    )
    assert any(
        diagnostic.get("calculation_label") == "csv_numeric_column_summary"
        and diagnostic.get("column") == "score"
        and diagnostic["summary"] == {"count": 2, "max": 2.5, "min": 1.5}
        for diagnostic in packet["diagnostics"]
    )
    assert any(
        diagnostic.get("calculation_label") == "jsonl_numeric_field_summary"
        and diagnostic.get("field") == "score"
        and diagnostic["summary"] == {"count": 2, "max": 2.0, "min": 1.0}
        for diagnostic in packet["diagnostics"]
    )


def test_secret_like_canonical_redaction_records_warning_without_secret_value(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_experiment(repo, "exp037-secret-canonical-warning")
    _write_json(experiment / "outputs" / "metrics.json", {"api_key": "sk-configured-secret"})
    _add_canonical_mapping(
        repo,
        "exp037-secret-canonical-warning",
        fact_id="api_key",
        selector="/api_key",
        expected_type="string",
        unit=None,
    )
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    packet = _packet(repo, manifest, "exp037-secret-canonical-warning")
    serialized = json.dumps(packet, sort_keys=True)
    assert "sk-configured-secret" not in serialized
    warnings = [
        warning for warning in packet["warnings"] if warning.get("warning_type") == "redaction"
    ]
    assert len(warnings) == 1
    assert warnings[0]["source"]["selector"] == "/api_key"
    assert warnings[0]["redaction_count"] == 1


def test_secret_like_canonical_conflicts_compare_raw_values_without_leaking(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_experiment(repo, "exp044-secret-canonical-conflict")
    _write_json(experiment / "outputs" / "a.json", {"api_key": "sk-conflict-secret-a"})
    _write_json(experiment / "outputs" / "b.json", {"api_key": "sk-conflict-secret-b"})
    _write_json(
        experiment / "outputs" / "experiment_report.json",
        {
            "schema_version": 1,
            "canonical_facts": [
                {
                    "fact_id": "api_key",
                    "value": "sk-conflict-secret-a",
                    "value_type": "string",
                    "unit": None,
                    "source": {
                        "path": "outputs/a.json",
                        "selector_type": "json_pointer",
                        "selector": "/api_key",
                    },
                }
            ],
        },
    )
    config = _load_config(repo)
    config["evidence"]["canonical_facts"][
        "questions/q001-throughput/experiments/exp044-secret-canonical-conflict"
    ] = [
        {
            "fact_id": "api_key",
            "source": "outputs/b.json",
            "selector_type": "json_pointer",
            "selector": "/api_key",
            "expected_type": "string",
            "unit": None,
        }
    ]
    _write_config(repo, config)
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    packet = _packet(repo, manifest, "exp044-secret-canonical-conflict")
    serialized = json.dumps(packet, sort_keys=True)
    assert "sk-conflict-secret-a" not in serialized
    assert "sk-conflict-secret-b" not in serialized
    assert packet["evidence_status"] == "conflicting"
    assert packet["preanalysis_disposition"] == "needs_human_review"
    assert "canonical_conflict" in packet["reason_codes"]
    assert packet["conflicts"] == [
        {
            "reason_code": "canonical_conflict",
            "fact_id": "api_key",
            "sources": [fact["source"] for fact in packet["canonical_facts"]],
        }
    ]
    assert {fact["value"] for fact in packet["canonical_facts"]} == {"[REDACTED]"}


def test_secret_like_canonical_same_raw_value_dedupes_without_conflict(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_experiment(repo, "exp045-secret-canonical-same-value")
    _write_json(experiment / "outputs" / "a.json", {"api_key": "sk-same-secret"})
    _write_json(experiment / "outputs" / "b.json", {"api_key": "sk-same-secret"})
    _write_json(
        experiment / "outputs" / "experiment_report.json",
        {
            "schema_version": 1,
            "canonical_facts": [
                {
                    "fact_id": "api_key",
                    "value": "sk-same-secret",
                    "value_type": "string",
                    "unit": None,
                    "source": {
                        "path": "outputs/a.json",
                        "selector_type": "json_pointer",
                        "selector": "/api_key",
                    },
                }
            ],
        },
    )
    config = _load_config(repo)
    config["evidence"]["canonical_facts"][
        "questions/q001-throughput/experiments/exp045-secret-canonical-same-value"
    ] = [
        {
            "fact_id": "api_key",
            "source": "outputs/b.json",
            "selector_type": "json_pointer",
            "selector": "/api_key",
            "expected_type": "string",
            "unit": None,
        }
    ]
    _write_config(repo, config)
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    packet = _packet(repo, manifest, "exp045-secret-canonical-same-value")
    serialized = json.dumps(packet, sort_keys=True)
    assert "sk-same-secret" not in serialized
    assert packet["evidence_status"] == "available"
    assert "canonical_conflict" not in packet["reason_codes"]
    assert len(packet["canonical_facts"]) == 1
    assert packet["canonical_facts"][0]["value"] == "[REDACTED]"


def test_json_yaml_observed_non_finite_numbers_are_warnings_not_values(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_bare_experiment(repo, "exp038-non-finite-observed")
    (experiment / "outputs").mkdir()
    (experiment / "outputs" / "metrics.json").write_text(
        '{"metric": NaN, "valid": 1}\n', encoding="utf-8"
    )
    (experiment / "outputs" / "metrics.yaml").write_text(
        "metric: .inf\nvalid: 2\n", encoding="utf-8"
    )
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    packet = _packet(repo, manifest, "exp038-non-finite-observed")
    assert {value["source"]["selector"] for value in packet["observed_values"]} == {
        "/valid",
    }
    warnings = [
        warning
        for warning in packet["warnings"]
        if warning.get("warning_type") == "non_finite_numeric"
    ]
    assert [
        (warning["source"]["path"].rsplit("/", 1)[-1], warning["source"]["selector"])
        for warning in warnings
    ] == [("metrics.json", "/metric"), ("metrics.yaml", "/metric")]


def test_configured_canonical_non_finite_number_fails_before_serialization(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_experiment(repo, "exp039-non-finite-canonical")
    (experiment / "outputs").mkdir()
    (experiment / "outputs" / "metrics.json").write_text('{"metric": Infinity}\n', encoding="utf-8")
    _add_canonical_mapping(repo, "exp039-non-finite-canonical")
    _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 2
    assert "non-finite numeric value" in result.stderr
    assert (
        "questions/q001-throughput/experiments/exp039-non-finite-canonical/outputs/metrics.json"
        in (result.stderr)
    )


def test_csv_jsonl_numeric_diagnostics_warn_and_omit_non_finite_values(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_experiment(repo, "exp040-non-finite-tabular")
    (experiment / "outputs").mkdir()
    (experiment / "outputs" / "table.csv").write_text(
        "score\n1\nNaN\nInfinity\n2\n", encoding="utf-8"
    )
    (experiment / "outputs" / "events.jsonl").write_text(
        '{"score": 1}\n{"score": NaN}\n{"score": Infinity}\n{"score": 2}\n',
        encoding="utf-8",
    )
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    packet = _packet(repo, manifest, "exp040-non-finite-tabular")
    warnings = [
        warning
        for warning in packet["warnings"]
        if warning.get("warning_type") == "non_finite_numeric"
    ]
    assert sorted(
        (warning["source"]["path"].rsplit("/", 1)[-1], warning["source"]["line_start"])
        for warning in warnings
    ) == [
        ("events.jsonl", 2),
        ("events.jsonl", 3),
        ("table.csv", 3),
        ("table.csv", 4),
    ]
    summaries = [
        diagnostic
        for diagnostic in packet["diagnostics"]
        if diagnostic.get("calculation_label")
        in {"csv_numeric_column_summary", "jsonl_numeric_field_summary"}
    ]
    assert {summary["non_finite_omitted_count"] for summary in summaries} == {2}
    assert all(summary["summary"]["count"] == 2 for summary in summaries)


def test_evidence_fingerprint_records_only_adapters_used_by_packet(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    json_only = _add_bare_experiment(repo, "exp032-json-only")
    _write_json(json_only / "outputs" / "metrics.json", {"metric": 1})
    csv_only = _add_bare_experiment(repo, "exp033-csv-only")
    (csv_only / "outputs").mkdir()
    (csv_only / "outputs" / "table.csv").write_text("name,score\nalpha,1\n", encoding="utf-8")
    unsupported = _add_bare_experiment(repo, "exp034-unsupported-only")
    (unsupported / "outputs").mkdir()
    (unsupported / "outputs" / "model.bin").write_bytes(b"\x00\x01")
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    json_packet = _packet(repo, manifest, "exp032-json-only")
    csv_packet = _packet(repo, manifest, "exp033-csv-only")
    unsupported_packet = _packet(repo, manifest, "exp034-unsupported-only")
    assert json_packet["fingerprint"]["extra_inputs"]["adapter_versions"] == {"json": "1"}
    assert csv_packet["fingerprint"]["extra_inputs"]["adapter_versions"] == {"csv": "1"}
    assert unsupported_packet["fingerprint"]["extra_inputs"]["adapter_versions"] == {}


def test_markdown_and_log_previews_escape_untrusted_text_and_bound_heading_count(
    tmp_path,
):
    repo = copy_fixture_repo(tmp_path)
    experiment = _add_bare_experiment(repo, "exp035-escaped-previews")
    (experiment / "README.md").write_text(
        "# First [link](https://example.test)\n"
        "body\n"
        "## Second *bold*\n"
        "### Third should not be emitted\n",
        encoding="utf-8",
    )
    (experiment / "outputs").mkdir()
    (experiment / "outputs" / "run.log").write_text(
        "# log heading\n[link](https://example.test)\nmiddle\n*tail*\n",
        encoding="utf-8",
    )
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    packet = _packet(repo, manifest, "exp035-escaped-previews")
    markdown_previews = [
        preview
        for preview in packet["previews"]
        if preview["source"]["path"].endswith("/README.md")
    ]
    log_previews = [
        preview
        for preview in packet["previews"]
        if preview["source"]["path"].endswith("/outputs/run.log")
    ]
    assert [preview["source"]["line_start"] for preview in markdown_previews] == [1, 3]
    assert markdown_previews[0]["message"] == (r"\# First \[link\]\(https://example.test\)")
    assert markdown_previews[1]["message"] == r"\#\# Second \*bold\*"
    assert [preview["source"]["line_start"] for preview in log_previews] == [1, 2, 4]
    assert log_previews[0]["message"] == r"\# log heading"
    assert log_previews[1]["message"] == r"\[link\]\(https://example.test\)"
    assert log_previews[2]["message"] == r"\*tail\*"


def test_normalize_writes_one_packet_per_manifest_entry_at_mirrored_paths(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    manifest = _run_prerequisites(repo)
    manifest_before = read_json(repo / MANIFEST_PATH)
    paper_before = (repo / "PAPER.md").read_text(encoding="utf-8")
    inventories_before = {
        entry["inventory_path"]: read_json(repo / entry["inventory_path"])
        for entry in manifest["experiments"]
    }

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    assert read_json(repo / MANIFEST_PATH) == manifest_before
    for entry in manifest["experiments"]:
        assert (repo / entry["evidence_path"]).is_file()
        assert (
            read_json(repo / entry["inventory_path"]) == inventories_before[entry["inventory_path"]]
        )

    evidence_packets = sorted(
        path.relative_to(repo).as_posix()
        for path in (repo / "paper" / "work" / "evidence").rglob("*.json")
    )
    assert evidence_packets == sorted(entry["evidence_path"] for entry in manifest["experiments"])
    assert not (repo / "PAPER.draft.md").exists()
    assert (repo / "PAPER.md").read_text(encoding="utf-8") == paper_before


def test_normalize_rejects_symlinked_evidence_output_path_without_touching_target(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    manifest = _run_prerequisites(repo)
    entry = _entry(manifest, "exp001-completed")
    target = repo / "paper" / "work" / "target-evidence.json"
    original = b'{"sentinel": true}\n'
    target.write_bytes(original)
    output = repo / entry["evidence_path"]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.symlink_to(os.path.relpath(target, output.parent))

    result = _normalize(repo)

    assert result.returncode == 2
    assert "evidence output path is a symlink" in result.stderr
    assert entry["evidence_path"] in result.stderr
    assert target.read_bytes() == original
