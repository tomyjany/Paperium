from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from conftest import copy_fixture_repo, read_json, run_paperctl
from paperctl._support.hashing import sha256_file
from paperctl._support.schema import validate_artifact


MANIFEST_PATH = Path("paper/work/manifest.json")
FORBIDDEN_MANIFEST_FIELDS = {
    "preanalysis_disposition",
    "execution_status",
    "evidence_status",
    "reason_codes",
}


def test_missing_configured_questions_root_is_deterministic_failure(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    shutil.rmtree(repo / "questions")

    result = run_paperctl(repo, "discover")

    assert result.returncode == 2
    assert "missing configured questions root: questions" in result.stderr
    assert not (repo / MANIFEST_PATH).exists()


def test_existing_root_with_zero_experiments_writes_empty_manifest(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    shutil.rmtree(repo / "questions")
    (repo / "questions").mkdir()

    result = run_paperctl(repo, "discover")

    assert result.returncode == 0
    assert "wrote paper/work/manifest.json" in result.stdout
    manifest = read_json(repo / MANIFEST_PATH)
    validate_artifact("manifest.schema.json", manifest)
    assert manifest["experiments"] == []


def test_all_fixture_experiments_are_discovered_including_legacy_names(tmp_path):
    repo = copy_fixture_repo(tmp_path)

    result = run_paperctl(repo, "discover")

    assert result.returncode == 0
    manifest = read_json(repo / MANIFEST_PATH)
    experiment_paths = [entry["experiment_path"] for entry in manifest["experiments"]]
    assert experiment_paths == [
        "questions/q001-throughput/experiments/exp001-completed",
        "questions/q001-throughput/experiments/exp002-incomplete",
        "questions/q001-throughput/experiments/exp003-structured-conflict",
        "questions/q001-throughput/experiments/exp004-smoke-and-full",
        "questions/q001-throughput/experiments/exp005-unsupported-and-previews",
        "questions/q001-throughput/experiments/legacy-baseline",
    ]
    assert [entry["experiment_ref"] for entry in manifest["experiments"]][-1] == "legacy-baseline"


def test_manifest_entries_include_question_readme_path_and_hash(tmp_path):
    repo = copy_fixture_repo(tmp_path)

    result = run_paperctl(repo, "discover")

    assert result.returncode == 0
    manifest = read_json(repo / MANIFEST_PATH)
    expected_readme = "questions/q001-throughput/README.md"
    expected_hash = sha256_file(repo / expected_readme)
    assert {
        (entry["question_readme_path"], entry["question_readme_sha256"])
        for entry in manifest["experiments"]
    } == {(expected_readme, expected_hash)}


def test_manifest_entries_include_mirrored_inventory_and_evidence_paths(tmp_path):
    repo = copy_fixture_repo(tmp_path)

    result = run_paperctl(repo, "discover")

    assert result.returncode == 0
    manifest = read_json(repo / MANIFEST_PATH)
    for entry in manifest["experiments"]:
        assert entry["inventory_path"] == f"paper/work/inventories/{entry['experiment_path']}.json"
        assert entry["evidence_path"] == f"paper/work/evidence/{entry['experiment_path']}.json"


def test_manifest_has_no_status_or_disposition_fields(tmp_path):
    repo = copy_fixture_repo(tmp_path)

    result = run_paperctl(repo, "discover")

    assert result.returncode == 0
    manifest = read_json(repo / MANIFEST_PATH)
    assert FORBIDDEN_MANIFEST_FIELDS.isdisjoint(manifest)
    for entry in manifest["experiments"]:
        assert FORBIDDEN_MANIFEST_FIELDS.isdisjoint(entry)


def test_discovery_output_is_byte_identical_across_two_clean_fixture_copies(tmp_path):
    repo_a = copy_fixture_repo(tmp_path / "a")
    repo_b = copy_fixture_repo(tmp_path / "b")

    result_a = run_paperctl(repo_a, "discover")
    result_b = run_paperctl(repo_b, "discover")

    assert result_a.returncode == 0
    assert result_b.returncode == 0
    assert (repo_a / MANIFEST_PATH).read_bytes() == (repo_b / MANIFEST_PATH).read_bytes()


def test_configured_question_pattern_controls_discovery(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    config_path = repo / "paper.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["questions"]["pattern"] = "missing-*"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    result = run_paperctl(repo, "discover")

    assert result.returncode == 0
    manifest = read_json(repo / MANIFEST_PATH)
    assert manifest["experiments"] == []
