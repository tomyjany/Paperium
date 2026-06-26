from __future__ import annotations

import os
from pathlib import Path

import pytest

from conftest import copy_fixture_repo, read_json, run_paperctl
from paperctl._support.hashing import sha256_file
from paperctl._support.schema import validate_artifact
from paperctl import inventory as inventory_module
from paperctl.inventory import InventoryError


MANIFEST_PATH = Path("paper/work/manifest.json")
EXCLUDED_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".DS_Store",
}


def _discover(repo: Path) -> dict:
    result = run_paperctl(repo, "discover")
    assert result.returncode == 0, result.stderr
    return read_json(repo / MANIFEST_PATH)


def _inventory(repo: Path):
    return run_paperctl(repo, "inventory")


def _inventory_for(repo: Path, experiment_ref: str) -> dict:
    manifest = read_json(repo / MANIFEST_PATH)
    entry = next(
        entry for entry in manifest["experiments"] if entry["experiment_ref"] == experiment_ref
    )
    inventory = read_json(repo / entry["inventory_path"])
    validate_artifact("artifact-inventory.schema.json", inventory)
    return inventory


def _artifact_by_path(inventory: dict) -> dict[str, dict]:
    return {artifact["path"]: artifact for artifact in inventory["artifacts"]}


def test_inventory_command_fails_when_manifest_is_missing_or_stale(tmp_path):
    repo = copy_fixture_repo(tmp_path)

    missing = _inventory(repo)

    assert missing.returncode == 2
    assert "missing discovery manifest: paper/work/manifest.json" in missing.stderr
    assert "run paperctl discover first" in missing.stderr

    _discover(repo)
    new_experiment = (
        repo / "questions" / "q001-throughput" / "experiments" / "exp999-after-discovery"
    )
    new_experiment.mkdir()
    (new_experiment / "README.md").write_text("# Late experiment\n", encoding="utf-8")

    stale = _inventory(repo)

    assert stale.returncode == 2
    assert "stale discovery manifest" in stale.stderr
    assert "run paperctl discover --force before inventory" in stale.stderr


def test_inventory_records_regular_files_and_symlinks_without_following_them(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = repo / "questions" / "q001-throughput" / "experiments" / "exp001-completed"
    (experiment / "readme-link.md").symlink_to("README.md")
    (experiment / "outputs-link").symlink_to("outputs", target_is_directory=True)
    _discover(repo)

    result = _inventory(repo)

    assert result.returncode == 0, result.stderr
    artifacts = _artifact_by_path(_inventory_for(repo, "exp001-completed"))
    readme_path = "questions/q001-throughput/experiments/exp001-completed/README.md"
    report_path = (
        "questions/q001-throughput/experiments/exp001-completed/outputs/experiment_report.json"
    )
    link_path = "questions/q001-throughput/experiments/exp001-completed/readme-link.md"
    linked_dir_path = "questions/q001-throughput/experiments/exp001-completed/outputs-link"

    assert artifacts[readme_path]["file_type"] == "regular"
    assert artifacts[readme_path]["byte_size"] == (repo / readme_path).stat().st_size
    assert artifacts[readme_path]["sha256"] == sha256_file(repo / readme_path)
    assert artifacts[report_path]["file_type"] == "regular"
    assert artifacts[link_path] == {
        "path": link_path,
        "file_type": "symlink",
        "byte_size": None,
        "sha256": None,
        "kind": "markdown",
        "support_status": "unsupported",
        "symlink_target": "README.md",
    }
    assert artifacts[linked_dir_path]["file_type"] == "symlink"
    assert not any(path.startswith(f"{linked_dir_path}/") for path in artifacts)


def test_inventory_fingerprint_exposes_complete_artifact_listing(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = repo / "questions" / "q001-throughput" / "experiments" / "exp001-completed"
    (experiment / "readme-link.md").symlink_to("README.md")
    _discover(repo)

    result = _inventory(repo)

    assert result.returncode == 0, result.stderr
    inventory = _inventory_for(repo, "exp001-completed")
    listing = inventory["fingerprint"]["extra_inputs"]["artifact_listing"]
    artifacts = inventory["artifacts"]

    assert listing == artifacts
    assert [artifact["path"] for artifact in listing] == sorted(
        artifact["path"] for artifact in listing
    )

    base = "questions/q001-throughput/experiments/exp001-completed"
    assert {
        "path": f"{base}/README.md",
        "file_type": "regular",
        "byte_size": (repo / base / "README.md").stat().st_size,
        "sha256": sha256_file(repo / base / "README.md"),
        "kind": "markdown",
        "support_status": "supported",
        "symlink_target": None,
    } in listing
    assert {
        "path": f"{base}/readme-link.md",
        "file_type": "symlink",
        "byte_size": None,
        "sha256": None,
        "kind": "markdown",
        "support_status": "unsupported",
        "symlink_target": "README.md",
    } in listing


def test_inventory_honors_exact_exclusion_list(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = repo / "questions" / "q001-throughput" / "experiments" / "exp002-incomplete"
    for name in EXCLUDED_NAMES - {".DS_Store"}:
        directory = experiment / name
        directory.mkdir()
        (directory / "should-not-appear.txt").write_text("ignored\n", encoding="utf-8")
    (experiment / ".DS_Store").write_text("ignored\n", encoding="utf-8")
    (experiment / "not_excluded.pyc").write_text("kept\n", encoding="utf-8")
    _discover(repo)

    result = _inventory(repo)

    assert result.returncode == 0, result.stderr
    artifact_paths = [
        artifact["path"] for artifact in _inventory_for(repo, "exp002-incomplete")["artifacts"]
    ]
    assert any(path.endswith("/not_excluded.pyc") for path in artifact_paths)
    for path in artifact_paths:
        assert EXCLUDED_NAMES.isdisjoint(Path(path).parts)


def test_inventory_records_configured_exclusions_without_descending_into_them(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = repo / "questions" / "q001-throughput" / "experiments" / "exp002-incomplete"
    for name in [".venv", ".uv-cache", "node_modules"]:
        directory = experiment / name
        directory.mkdir()
        (directory / "dependency.json").write_text('{"ignored": true}\n', encoding="utf-8")
    _discover(repo)

    result = _inventory(repo)

    assert result.returncode == 0, result.stderr
    inventory = _inventory_for(repo, "exp002-incomplete")
    artifact_paths = [artifact["path"] for artifact in inventory["artifacts"]]
    excluded_paths = [entry["path"] for entry in inventory["excluded_artifacts"]]

    assert not any(".venv" in Path(path).parts for path in artifact_paths)
    assert not any(".uv-cache" in Path(path).parts for path in artifact_paths)
    assert not any("node_modules" in Path(path).parts for path in artifact_paths)
    assert excluded_paths == [
        "questions/q001-throughput/experiments/exp002-incomplete/.uv-cache",
        "questions/q001-throughput/experiments/exp002-incomplete/.venv",
        "questions/q001-throughput/experiments/exp002-incomplete/node_modules",
    ]
    assert inventory["counts"]["artifact_count"] == len(inventory["artifacts"])
    assert inventory["counts"]["excluded_artifact_count"] == 3
    assert (
        inventory["fingerprint"]["extra_inputs"]["excluded_artifacts"]
        == inventory["excluded_artifacts"]
    )


def test_external_symlink_is_unsupported_artifact_not_global_failure(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    experiment = (
        repo / "questions" / "q001-throughput" / "experiments" / "exp005-unsupported-and-previews"
    )
    external_link = experiment / "external-result.json"
    external_link.symlink_to(outside)
    _discover(repo)

    result = _inventory(repo)

    assert result.returncode == 0, result.stderr
    artifacts = _artifact_by_path(_inventory_for(repo, "exp005-unsupported-and-previews"))
    record = artifacts[
        "questions/q001-throughput/experiments/exp005-unsupported-and-previews/external-result.json"
    ]
    assert record["file_type"] == "symlink"
    assert record["sha256"] is None
    assert record["byte_size"] is None
    assert record["support_status"] == "unsupported"
    assert record["symlink_target"] == outside.as_posix()


def test_manifest_symlink_escape_is_rejected_after_discovery(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    outside_experiment = tmp_path / "outside-experiment"
    outside_experiment.mkdir()
    (outside_experiment / "README.md").write_text("# Outside\n", encoding="utf-8")
    escaped = repo / "questions" / "q001-throughput" / "experiments" / "exp999-escaped"
    escaped.symlink_to(outside_experiment, target_is_directory=True)
    _discover(repo)

    result = _inventory(repo)

    assert result.returncode == 2
    assert "manifest path resolves outside repository" in result.stderr
    assert "questions/q001-throughput/experiments/exp999-escaped" in result.stderr


def test_manifest_internal_symlink_experiment_root_is_rejected_after_discovery(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiments = repo / "questions" / "q001-throughput" / "experiments"
    linked = experiments / "exp998-linked-to-completed"
    linked.symlink_to("exp001-completed", target_is_directory=True)

    manifest = _discover(repo)

    linked_path = "questions/q001-throughput/experiments/exp998-linked-to-completed"
    assert any(entry["experiment_path"] == linked_path for entry in manifest["experiments"])

    result = _inventory(repo)

    assert result.returncode == 2
    assert "manifest experiment path is a symlink" in result.stderr
    assert linked_path in result.stderr


def test_manifest_symlinked_experiment_path_ancestor_is_rejected_before_inventory_write(
    tmp_path,
):
    repo = copy_fixture_repo(tmp_path)
    question = repo / "questions" / "q001-throughput"
    experiments = question / "experiments"
    real_experiments = question / "experiments-real"
    experiments.rename(real_experiments)
    experiments.symlink_to("experiments-real", target_is_directory=True)

    manifest = _discover(repo)

    linked_component = "questions/q001-throughput/experiments"
    linked_experiment_path = f"{linked_component}/exp001-completed"
    assert any(
        entry["experiment_path"] == linked_experiment_path for entry in manifest["experiments"]
    )

    result = _inventory(repo)

    assert result.returncode == 2
    assert "manifest experiment path contains a symlink" in result.stderr
    assert linked_component in result.stderr
    assert linked_experiment_path in result.stderr
    inventory_root = repo / "paper" / "work" / "inventories"
    if inventory_root.exists():
        assert not any(inventory_root.rglob("*.json"))


def test_inventory_rejects_existing_inventory_output_symlink_without_touching_target(
    tmp_path,
):
    repo = copy_fixture_repo(tmp_path)
    manifest = _discover(repo)
    entry = next(
        entry for entry in manifest["experiments"] if entry["experiment_ref"] == "exp001-completed"
    )
    target = repo / "paper" / "work" / "target-inventory.json"
    original_target_bytes = b'{"sentinel":true}\n'
    target.write_bytes(original_target_bytes)
    output_path = repo / entry["inventory_path"]
    output_path.parent.mkdir(parents=True)
    output_path.symlink_to(os.path.relpath(target, output_path.parent))

    result = _inventory(repo)

    assert result.returncode == 2
    assert "inventory output path is a symlink" in result.stderr
    assert entry["inventory_path"] in result.stderr
    assert target.read_bytes() == original_target_bytes


def test_inventory_rejects_symlinked_inventory_output_directory_component(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    _discover(repo)
    redirected = repo / "paper" / "work" / "redirected-inventories"
    redirected.mkdir()
    inventory_root = repo / "paper" / "work" / "inventories"
    inventory_root.mkdir()
    linked_component = inventory_root / "questions"
    linked_component.symlink_to(
        os.path.relpath(redirected, inventory_root),
        target_is_directory=True,
    )

    result = _inventory(repo)

    assert result.returncode == 2
    assert "inventory output path contains a symlink" in result.stderr
    assert "paper/work/inventories/questions" in result.stderr
    assert not any(path.is_file() for path in redirected.rglob("*"))


def test_fixed_extension_map_classifies_known_kinds_and_binary_unknowns(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = repo / "questions" / "q001-throughput" / "experiments" / "exp001-completed"
    (experiment / "config.yaml").write_text("a: 1\n", encoding="utf-8")
    (experiment / "table.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (experiment / "events.jsonl").write_text('{"a": 1}\n', encoding="utf-8")
    (experiment / "notes.txt").write_text("notes\n", encoding="utf-8")
    (experiment / "debug.log").write_text("ok\n", encoding="utf-8")
    _discover(repo)

    result = _inventory(repo)

    assert result.returncode == 0, result.stderr
    completed = _artifact_by_path(_inventory_for(repo, "exp001-completed"))
    unsupported = _artifact_by_path(_inventory_for(repo, "exp005-unsupported-and-previews"))

    base = "questions/q001-throughput/experiments/exp001-completed"
    assert completed[f"{base}/outputs/experiment_report.json"]["kind"] == "json"
    assert completed[f"{base}/config.yaml"]["kind"] == "yaml"
    assert completed[f"{base}/table.csv"]["kind"] == "csv"
    assert completed[f"{base}/events.jsonl"]["kind"] == "jsonl"
    assert completed[f"{base}/README.md"]["kind"] == "markdown"
    assert completed[f"{base}/debug.log"]["kind"] == "log"
    assert completed[f"{base}/notes.txt"]["kind"] == "text"

    binary = unsupported[
        "questions/q001-throughput/experiments/exp005-unsupported-and-previews/outputs/model.bin"
    ]
    assert binary["kind"] == "binary"
    assert binary["support_status"] == "unsupported"


def test_binary_detection_uses_bounded_byte_sniff(tmp_path):
    file = tmp_path / "sample.txt"
    file.write_bytes(b"abcd\xff")

    assert inventory_module._is_binary(file, sniff_size=4) is False
    assert inventory_module._is_binary(file, sniff_size=5) is True


def test_regular_file_scan_errors_are_inventory_errors(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    file = repo / "questions" / "q001" / "experiments" / "exp001" / "result.txt"
    file.parent.mkdir(parents=True)
    file.write_text("result\n", encoding="utf-8")

    def fail_stat(self, *, follow_symlinks=True):
        if self == file:
            raise OSError("stat denied")
        return original_stat(self, follow_symlinks=follow_symlinks)

    original_stat = Path.stat
    monkeypatch.setattr(Path, "stat", fail_stat)

    with pytest.raises(InventoryError, match="questions/q001/experiments/exp001/result.txt"):
        inventory_module._regular_file_artifact(repo, file)


def test_binary_sniff_and_hash_errors_are_inventory_errors(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    file = repo / "questions" / "q001" / "experiments" / "exp001" / "result.txt"
    file.parent.mkdir(parents=True)
    file.write_text("result\n", encoding="utf-8")

    def fail_sniff(path, *, sniff_size=inventory_module.BINARY_SNIFF_BYTES):
        raise OSError("read denied")

    monkeypatch.setattr(inventory_module, "_is_binary", fail_sniff)
    with pytest.raises(
        InventoryError,
        match="could not classify artifact kind: questions/q001/experiments/exp001/result.txt",
    ):
        inventory_module._regular_file_artifact(repo, file)

    monkeypatch.setattr(inventory_module, "_is_binary", lambda path: False)
    monkeypatch.setattr(
        inventory_module, "sha256_file", lambda path: (_ for _ in ()).throw(OSError("hash denied"))
    )
    with pytest.raises(
        InventoryError,
        match="could not hash artifact: questions/q001/experiments/exp001/result.txt",
    ):
        inventory_module._regular_file_artifact(repo, file)


def test_symlink_read_errors_are_inventory_errors(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    link = repo / "questions" / "q001" / "experiments" / "exp001" / "result.txt"
    link.parent.mkdir(parents=True)
    link.symlink_to("target.txt")

    monkeypatch.setattr(
        inventory_module.os,
        "readlink",
        lambda path: (_ for _ in ()).throw(OSError("readlink denied")),
    )

    with pytest.raises(
        InventoryError,
        match="could not read symlink target: questions/q001/experiments/exp001/result.txt",
    ):
        inventory_module._symlink_artifact(repo, link)


def test_inventory_cli_reports_unreadable_artifact_as_deterministic_failure(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    locked = (
        repo / "questions" / "q001-throughput" / "experiments" / "exp001-completed" / "locked.txt"
    )
    locked.write_text("locked\n", encoding="utf-8")
    locked.chmod(0)
    try:
        try:
            locked.read_bytes()
        except PermissionError:
            pass
        else:
            pytest.skip("current user can still read chmod-000 files")

        _discover(repo)
        result = _inventory(repo)
    finally:
        locked.chmod(0o600)

    assert result.returncode == 2
    assert "questions/q001-throughput/experiments/exp001-completed/locked.txt" in result.stderr
    assert "Traceback" not in result.stderr


def test_inventory_fingerprint_detects_file_additions_deletions_type_and_content_changes(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = repo / "questions" / "q001-throughput" / "experiments" / "exp001-completed"
    marker = experiment / "fingerprint.txt"
    marker.write_text("one\n", encoding="utf-8")
    _discover(repo)

    assert _inventory(repo).returncode == 0
    initial = _inventory_for(repo, "exp001-completed")["fingerprint"]["fingerprint_sha256"]

    marker.write_text("two\n", encoding="utf-8")
    assert _inventory(repo).returncode == 0
    content_changed = _inventory_for(repo, "exp001-completed")["fingerprint"]["fingerprint_sha256"]
    assert content_changed != initial

    added = experiment / "added.txt"
    added.write_text("added\n", encoding="utf-8")
    assert _inventory(repo).returncode == 0
    added_changed = _inventory_for(repo, "exp001-completed")["fingerprint"]["fingerprint_sha256"]
    assert added_changed != content_changed

    added.unlink()
    assert _inventory(repo).returncode == 0
    deleted_changed = _inventory_for(repo, "exp001-completed")["fingerprint"]["fingerprint_sha256"]
    assert deleted_changed != added_changed

    marker.unlink()
    marker.symlink_to("README.md")
    assert _inventory(repo).returncode == 0
    type_changed = _inventory_for(repo, "exp001-completed")["fingerprint"]["fingerprint_sha256"]
    assert type_changed != deleted_changed
