from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import yaml

from conftest import copy_fixture_repo, read_json, run_paperctl
from paperctl._support.hashing import sha256_file
from paperctl._support.schema import validate_artifact
from paperctl.config import load_config


AUDIT_PATH = Path("paper/PAPER.audit.json")
DRAFT_PATH = Path("PAPER.draft.md")
FINAL_PATH = Path("PAPER.md")
MANIFEST_PATH = Path("paper/work/manifest.json")
RENDER_STATE_PATH = Path("paper/work/render-state.json")


def _load_config_yaml(repo: Path) -> dict[str, Any]:
    return yaml.safe_load((repo / "paper.yaml").read_text(encoding="utf-8"))


def _write_config_yaml(repo: Path, config: dict[str, Any]) -> None:
    (repo / "paper.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def _entry(manifest: dict[str, Any], experiment_ref: str) -> dict[str, Any]:
    return next(
        entry for entry in manifest["experiments"] if entry["experiment_ref"] == experiment_ref
    )


def _generated_hashes(repo: Path, manifest: dict[str, Any]) -> dict[str, str]:
    paths = [
        MANIFEST_PATH.as_posix(),
        DRAFT_PATH.as_posix(),
        RENDER_STATE_PATH.as_posix(),
        AUDIT_PATH.as_posix(),
    ]
    for entry in manifest["experiments"]:
        paths.append(entry["inventory_path"])
        paths.append(entry["evidence_path"])
    return {path: sha256_file(repo / path) for path in sorted(paths)}


def test_build_requires_existing_valid_config_and_does_not_implicitly_init(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    (repo / "paper.yaml").unlink()

    result = run_paperctl(repo, "build")

    assert result.returncode == 2
    assert "missing config file: paper.yaml" in result.stderr
    assert not (repo / "paper.yaml").exists()
    assert not (repo / MANIFEST_PATH).exists()
    assert not (repo / DRAFT_PATH).exists()


def test_build_runs_direct_python_stage_apis_in_order(monkeypatch, tmp_path):
    from paperctl import build as build_module

    repo = copy_fixture_repo(tmp_path)
    config = load_config(repo)
    calls: list[str] = []

    class StubDiscovery:
        path = "paper/work/manifest.json"
        experiment_count = 1
        status = "created"
        manifest = {"experiments": [{"experiment_path": "questions/q001/experiments/exp001"}]}

    class StubInventory:
        experiment_count = 1
        created = 1
        replaced = 0
        unchanged = 0

    class StubNormalize:
        experiment_count = 1
        created = 1
        replaced = 0
        unchanged = 0

    class StubRender:
        draft_path = "PAPER.draft.md"
        render_state_path = "paper/work/render-state.json"
        status = "wrote"
        experiment_count = 1
        blocker_count = 1

    class StubAudit:
        report_path = "paper/PAPER.audit.json"
        stage = "deterministic"
        deterministic_status = "passed"
        publication_status = "blocked"
        publishable = False
        issue_count = 0
        blocker_count = 1
        issue_codes: list[str] = []
        blocker_codes = ["missing_semantic_analysis"]

    def fake_discover(*args, **kwargs):
        calls.append("discover")
        assert kwargs["force"] is False
        return StubDiscovery()

    def fake_inventory_all(*args, **kwargs):
        calls.append("inventory")
        assert kwargs["manifest"] == StubDiscovery.manifest
        assert kwargs["force"] is False
        return StubInventory()

    def fake_normalize_all(*args, **kwargs):
        calls.append("normalize")
        assert kwargs["force"] is False
        return StubNormalize()

    def fake_render(*args, **kwargs):
        calls.append("render")
        assert kwargs["force"] is False
        return StubRender()

    def fake_audit(*args, **kwargs):
        calls.append("audit")
        assert kwargs["stage"] == "deterministic"
        assert kwargs["force"] is False
        return StubAudit()

    def fail_subprocess_run(*args, **kwargs):
        raise AssertionError("build must not invoke CLI subprocesses")

    monkeypatch.setattr(build_module, "discover", fake_discover)
    monkeypatch.setattr(build_module, "inventory_all", fake_inventory_all)
    monkeypatch.setattr(build_module, "normalize_all", fake_normalize_all)
    monkeypatch.setattr(build_module, "render", fake_render)
    monkeypatch.setattr(build_module, "audit", fake_audit)
    monkeypatch.setattr(subprocess, "run", fail_subprocess_run)

    result = build_module.build(repo, config)

    assert calls == ["discover", "inventory", "normalize", "render", "audit"]
    assert result.deterministic_status == "passed"
    assert result.publication_status == "blocked"
    assert result.publication_blocker_codes == ["missing_semantic_analysis"]


def test_build_writes_full_audit_report_and_preserves_final_paper(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    final_before = (repo / FINAL_PATH).read_bytes()

    result = run_paperctl(repo, "build")

    assert result.returncode == 0, result.stderr
    assert "deterministic build: passed" in result.stdout
    assert "draft: PAPER.draft.md" in result.stdout
    assert "audit: paper/PAPER.audit.json" in result.stdout
    assert "publication: blocked by" in result.stdout
    assert "missing_semantic_analysis" in result.stdout
    assert (repo / FINAL_PATH).read_bytes() == final_before
    report = read_json(repo / AUDIT_PATH)
    validate_artifact("paper-audit.schema.json", report)
    assert report["stage"] == "deterministic"
    assert report["deterministic_health"] == {"status": "passed", "issues": []}
    assert report["publication_gate"]["status"] == "blocked"
    assert {blocker["code"] for blocker in report["publication_gate"]["blockers"]} >= {
        "missing_semantic_analysis"
    }
    assert report["publishable"] is False


def test_build_stops_on_deterministic_stage_failure_and_exits_two(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    config = _load_config_yaml(repo)
    config["evidence"]["canonical_facts"]["questions/q001-throughput/experiments/exp001-completed"][
        0
    ]["selector"] = "/does/not/exist"
    _write_config_yaml(repo, config)

    result = run_paperctl(repo, "build")

    assert result.returncode == 2
    assert "canonical selector did not resolve" in result.stderr
    assert not (repo / DRAFT_PATH).exists()
    assert not (repo / AUDIT_PATH).exists()


def test_failed_rebuild_replaces_stale_success_audit_with_deterministic_failure(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    final_before = (repo / FINAL_PATH).read_bytes()
    first = run_paperctl(repo, "build")
    assert first.returncode == 0, first.stderr
    stale_success_report = read_json(repo / AUDIT_PATH)
    assert stale_success_report["deterministic_health"]["status"] == "passed"

    config = _load_config_yaml(repo)
    config["evidence"]["canonical_facts"]["questions/q001-throughput/experiments/exp001-completed"][
        0
    ]["selector"] = "/does/not/exist"
    _write_config_yaml(repo, config)

    result = run_paperctl(repo, "build")

    assert result.returncode == 2
    assert "canonical selector did not resolve" in result.stderr
    assert (repo / FINAL_PATH).read_bytes() == final_before
    report = read_json(repo / AUDIT_PATH)
    validate_artifact("paper-audit.schema.json", report)
    assert report["deterministic_health"]["status"] == "failed"
    assert report["publication_gate"]["status"] == "passed"
    assert report["publishable"] is False
    assert [issue["code"] for issue in report["deterministic_health"]["issues"]] == [
        "build_stage_failed"
    ]
    assert (
        "canonical selector did not resolve"
        in report["deterministic_health"]["issues"][0]["message"]
    )


def test_second_unchanged_build_reuses_outputs_and_force_is_byte_identical(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    first = run_paperctl(repo, "build")
    assert first.returncode == 0, first.stderr
    manifest = read_json(repo / MANIFEST_PATH)
    first_hashes = _generated_hashes(repo, manifest)
    first_audit_bytes = (repo / AUDIT_PATH).read_bytes()
    sentinel_ns = 1_700_000_000_000_000_000
    os.utime(repo / AUDIT_PATH, ns=(sentinel_ns, sentinel_ns))
    first_audit_mtime = (repo / AUDIT_PATH).stat().st_mtime_ns

    second = run_paperctl(repo, "build")

    assert second.returncode == 0, second.stderr
    assert "discovery: unchanged" in second.stdout
    assert "inventory: 0 created, 0 replaced" in second.stdout
    assert "evidence: 0 created, 0 replaced" in second.stdout
    assert "render: unchanged" in second.stdout
    assert _generated_hashes(repo, manifest) == first_hashes
    assert (repo / AUDIT_PATH).stat().st_mtime_ns == first_audit_mtime

    forced = run_paperctl(repo, "build", "--force")

    assert forced.returncode == 0, forced.stderr
    assert "inventory: 0 created, 6 replaced, 0 unchanged" in forced.stdout
    assert "evidence: 0 created, 6 replaced, 0 unchanged" in forced.stdout
    assert "render: wrote" in forced.stdout
    assert _generated_hashes(repo, manifest) == first_hashes
    assert (repo / AUDIT_PATH).read_bytes() == first_audit_bytes
    assert (repo / AUDIT_PATH).stat().st_mtime_ns != first_audit_mtime


def test_changing_one_experiment_regenerates_only_that_inventory_and_evidence_plus_downstream(
    tmp_path,
):
    repo = copy_fixture_repo(tmp_path)
    first = run_paperctl(repo, "build")
    assert first.returncode == 0, first.stderr
    manifest = read_json(repo / MANIFEST_PATH)
    hashes_before = _generated_hashes(repo, manifest)
    changed_entry = _entry(manifest, "exp002-incomplete")
    changed_file = repo / changed_entry["experiment_path"] / "outputs" / "status.json"
    payload = json.loads(changed_file.read_text(encoding="utf-8"))
    payload["note"] = "changed by build cache test"
    changed_file.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    result = run_paperctl(repo, "build")

    assert result.returncode == 0, result.stderr
    assert "inventory: 0 created, 1 replaced, 5 unchanged" in result.stdout
    assert "evidence: 0 created, 1 replaced, 5 unchanged" in result.stdout
    hashes_after = _generated_hashes(repo, manifest)
    changed_paths = {
        changed_entry["inventory_path"],
        changed_entry["evidence_path"],
        DRAFT_PATH.as_posix(),
        RENDER_STATE_PATH.as_posix(),
        AUDIT_PATH.as_posix(),
    }
    for path, before_hash in hashes_before.items():
        if path in changed_paths:
            assert hashes_after[path] != before_hash
        else:
            assert hashes_after[path] == before_hash


def test_adding_experiment_refreshes_discovery_and_downstream_outputs(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    first = run_paperctl(repo, "build")
    assert first.returncode == 0, first.stderr
    old_manifest = read_json(repo / MANIFEST_PATH)
    hashes_before = _generated_hashes(repo, old_manifest)
    new_experiment = repo / "questions" / "q001-throughput" / "experiments" / "exp999-added"
    (new_experiment / "outputs").mkdir(parents=True)
    (new_experiment / "README.md").write_text("# Added experiment\n", encoding="utf-8")
    (new_experiment / "outputs" / "result.json").write_text('{"value": 42}\n', encoding="utf-8")

    result = run_paperctl(repo, "build")

    assert result.returncode == 0, result.stderr
    assert "discovery: replaced" in result.stdout
    assert "inventory: 1 created, 6 replaced, 0 unchanged" in result.stdout
    assert "evidence: 1 created, 6 replaced, 0 unchanged" in result.stdout
    new_manifest = read_json(repo / MANIFEST_PATH)
    assert len(new_manifest["experiments"]) == len(old_manifest["experiments"]) + 1
    hashes_after = _generated_hashes(repo, new_manifest)
    downstream_paths = {entry["inventory_path"] for entry in old_manifest["experiments"]} | {
        entry["evidence_path"] for entry in old_manifest["experiments"]
    }
    for path in downstream_paths:
        assert hashes_after[path] != hashes_before[path]
    assert hashes_after[MANIFEST_PATH.as_posix()] != hashes_before[MANIFEST_PATH.as_posix()]
    assert hashes_after[DRAFT_PATH.as_posix()] != hashes_before[DRAFT_PATH.as_posix()]
    assert hashes_after[AUDIT_PATH.as_posix()] != hashes_before[AUDIT_PATH.as_posix()]


def test_changing_renderer_config_leaves_inventory_and_evidence_reusable(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    first = run_paperctl(repo, "build")
    assert first.returncode == 0, first.stderr
    manifest = read_json(repo / MANIFEST_PATH)
    hashes_before = _generated_hashes(repo, manifest)
    config = _load_config_yaml(repo)
    config["paper"]["draft_output"] = "paper/custom-draft.md"
    _write_config_yaml(repo, config)

    result = run_paperctl(repo, "build")

    assert result.returncode == 0, result.stderr
    assert "draft: paper/custom-draft.md" in result.stdout
    assert "inventory: 0 created, 0 replaced, 6 unchanged" in result.stdout
    assert "evidence: 0 created, 0 replaced, 6 unchanged" in result.stdout
    for entry in manifest["experiments"]:
        assert sha256_file(repo / entry["inventory_path"]) == hashes_before[entry["inventory_path"]]
        assert sha256_file(repo / entry["evidence_path"]) == hashes_before[entry["evidence_path"]]
    assert (repo / "paper" / "custom-draft.md").exists()
    assert sha256_file(repo / RENDER_STATE_PATH) != hashes_before[RENDER_STATE_PATH.as_posix()]
