from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from conftest import copy_fixture_repo, read_json, run_paperctl
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
        "name,score\nalpha,1.5\nbeta,2.5\n", encoding="utf-8"
    )
    (experiment / "outputs" / "events.jsonl").write_text(
        '{"score": 1}\n{"score": 2}\n', encoding="utf-8"
    )
    manifest = _run_prerequisites(repo)

    result = _normalize(repo)

    assert result.returncode == 0, result.stderr
    packet = _packet(repo, manifest, "exp030-tabular")
    assert packet["evidence_status"] == "available"
    assert packet["observed_values"] == []
    messages = [diagnostic["message"] for diagnostic in packet["diagnostics"]]
    assert any("numeric column score" in message for message in messages)
    assert any("numeric field score" in message for message in messages)


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
