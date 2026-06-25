from __future__ import annotations

from pathlib import Path

from conftest import copy_fixture_repo, read_json, run_paperctl
from paperctl._support.hashing import sha256_file
from paperctl._support.schema import validate_artifact


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
        repo
        / "questions"
        / "q001-throughput"
        / "experiments"
        / "exp999-after-discovery"
    )
    new_experiment.mkdir()
    (new_experiment / "README.md").write_text("# Late experiment\n", encoding="utf-8")

    stale = _inventory(repo)

    assert stale.returncode == 2
    assert "stale discovery manifest" in stale.stderr
    assert "run paperctl discover --force before inventory" in stale.stderr


def test_inventory_records_regular_files_and_symlinks_without_following_them(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = (
        repo
        / "questions"
        / "q001-throughput"
        / "experiments"
        / "exp001-completed"
    )
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
    experiment = (
        repo
        / "questions"
        / "q001-throughput"
        / "experiments"
        / "exp001-completed"
    )
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
    experiment = (
        repo
        / "questions"
        / "q001-throughput"
        / "experiments"
        / "exp002-incomplete"
    )
    for name in EXCLUDED_NAMES - {".DS_Store"}:
        directory = experiment / name
        directory.mkdir()
        (directory / "should-not-appear.txt").write_text("ignored\n", encoding="utf-8")
    (experiment / ".DS_Store").write_text("ignored\n", encoding="utf-8")
    (experiment / "not_excluded.pyc").write_text("kept\n", encoding="utf-8")
    _discover(repo)

    result = _inventory(repo)

    assert result.returncode == 0, result.stderr
    artifact_paths = [artifact["path"] for artifact in _inventory_for(repo, "exp002-incomplete")["artifacts"]]
    assert any(path.endswith("/not_excluded.pyc") for path in artifact_paths)
    for path in artifact_paths:
        assert EXCLUDED_NAMES.isdisjoint(Path(path).parts)


def test_external_symlink_is_unsupported_artifact_not_global_failure(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    experiment = (
        repo
        / "questions"
        / "q001-throughput"
        / "experiments"
        / "exp005-unsupported-and-previews"
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
    escaped = (
        repo
        / "questions"
        / "q001-throughput"
        / "experiments"
        / "exp999-escaped"
    )
    escaped.symlink_to(outside_experiment, target_is_directory=True)
    _discover(repo)

    result = _inventory(repo)

    assert result.returncode == 2
    assert "manifest path resolves outside repository" in result.stderr
    assert "questions/q001-throughput/experiments/exp999-escaped" in result.stderr


def test_fixed_extension_map_classifies_known_kinds_and_binary_unknowns(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = (
        repo
        / "questions"
        / "q001-throughput"
        / "experiments"
        / "exp001-completed"
    )
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


def test_inventory_fingerprint_detects_file_additions_deletions_type_and_content_changes(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    experiment = (
        repo
        / "questions"
        / "q001-throughput"
        / "experiments"
        / "exp001-completed"
    )
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
