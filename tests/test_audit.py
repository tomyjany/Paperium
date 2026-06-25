from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from conftest import copy_fixture_repo, read_json, run_paperctl
from paperctl._support.blockers import derive_publication_blockers
from paperctl._support.hashing import canonical_json_hash, sha256_file
from paperctl._support.jsonio import dump_json_bytes
from paperctl._support.schema import validate_artifact
from paperctl.config import load_config


AUDIT_PATH = Path("paper/PAPER.audit.json")
DRAFT_PATH = Path("PAPER.draft.md")
FINAL_PATH = Path("PAPER.md")
MANIFEST_PATH = Path("paper/work/manifest.json")
RENDER_STATE_PATH = Path("paper/work/render-state.json")


def _run_pipeline(repo: Path) -> dict[str, Any]:
    for command in ["discover", "inventory", "normalize", "render"]:
        result = run_paperctl(repo, command)
        assert result.returncode == 0, result.stderr
    return read_json(repo / MANIFEST_PATH)


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(dump_json_bytes(value))


def _load_config_yaml(repo: Path) -> dict[str, Any]:
    return yaml.safe_load((repo / "paper.yaml").read_text(encoding="utf-8"))


def _write_config_yaml(repo: Path, config: dict[str, Any]) -> None:
    (repo / "paper.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def test_deterministic_audit_writes_full_report_and_exits_zero_when_publication_blocked(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    sentinel = (repo / FINAL_PATH).read_bytes()
    manifest = _run_pipeline(repo)

    result = run_paperctl(repo, "audit", "--stage", "deterministic")

    assert result.returncode == 0, result.stderr
    assert (repo / FINAL_PATH).read_bytes() == sentinel
    report = read_json(repo / AUDIT_PATH)
    validate_artifact("paper-audit.schema.json", report)
    assert report["schema_version"] == 1
    assert report["artifact_type"] == "paper_audit"
    assert report["stage"] == "deterministic"
    assert report["deterministic_health"] == {"status": "passed", "issues": []}
    assert report["publication_gate"]["status"] == "blocked"
    assert report["publishable"] is False
    assert report["publishable"] == (
        report["deterministic_health"]["status"] == "passed"
        and report["publication_gate"]["status"] == "passed"
    )
    assert len(report["publication_gate"]["blockers"]) == len(manifest["experiments"]) + 1
    assert {blocker["code"] for blocker in report["publication_gate"]["blockers"]} == {
        "missing_semantic_analysis",
        "needs_human_review",
        "unresolved_evidence_conflict",
    }
    assert report["fingerprint"]["manifest_sha256"] == sha256_file(repo / MANIFEST_PATH)
    assert report["fingerprint"]["render_state_sha256"] == sha256_file(repo / RENDER_STATE_PATH)
    assert report["fingerprint"]["draft_sha256"] == sha256_file(repo / DRAFT_PATH)
    assert report["fingerprint"]["fingerprint_sha256"].startswith("sha256:")


def test_publication_audit_uses_config_default_stage_and_exits_three_when_blocked(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    _run_pipeline(repo)

    result = run_paperctl(repo, "audit")

    assert result.returncode == 3
    assert "publication: blocked" in result.stdout
    report = read_json(repo / AUDIT_PATH)
    assert report["stage"] == "publication"
    assert report["deterministic_health"]["status"] == "passed"
    assert report["publication_gate"]["status"] == "blocked"
    assert report["publishable"] is False


def test_audit_python_api_returns_result_and_uses_derived_publishable(tmp_path):
    from paperctl.audit import audit

    repo = copy_fixture_repo(tmp_path)
    _run_pipeline(repo)
    config = load_config(repo)

    result = audit(repo, config, "publication")

    assert result.report_path == "paper/PAPER.audit.json"
    assert result.stage == "publication"
    assert result.deterministic_status == "passed"
    assert result.publication_status == "blocked"
    assert result.publishable is False
    assert result.blocker_count > 0


def test_publication_blocker_derivation_is_deduplicated_and_sorted_by_precedence():
    manifest = {
        "experiments": [
            {
                "question_path": "questions/q002",
                "experiment_path": "questions/q002/experiments/exp002",
            },
            {
                "question_path": "questions/q001",
                "experiment_path": "questions/q001/experiments/exp001",
            },
            {
                "question_path": "questions/q001",
                "experiment_path": "questions/q001/experiments/exp003",
            },
        ]
    }
    packets = [
        {
            "experiment_path": "questions/q002/experiments/exp002",
            "preanalysis_disposition": "analysis_candidate",
            "evidence_status": "unsupported",
        },
        {
            "experiment_path": "questions/q001/experiments/exp001",
            "preanalysis_disposition": "needs_human_review",
            "evidence_status": "conflicting",
        },
        {
            "experiment_path": "questions/q001/experiments/exp003",
            "preanalysis_disposition": "blocked",
            "evidence_status": "missing",
        },
    ]

    blockers = derive_publication_blockers(manifest, packets)

    assert [(blocker["experiment_path"], blocker["code"]) for blocker in blockers] == [
        ("questions/q001/experiments/exp001", "needs_human_review"),
        ("questions/q001/experiments/exp001", "unresolved_evidence_conflict"),
        ("questions/q001/experiments/exp003", "unresolved_preanalysis_blocker"),
        ("questions/q001/experiments/exp003", "unresolved_evidence_blocker"),
        ("questions/q002/experiments/exp002", "missing_semantic_analysis"),
        ("questions/q002/experiments/exp002", "unresolved_evidence_blocker"),
    ]
    for experiment_path in {blocker["experiment_path"] for blocker in blockers}:
        codes = [b["code"] for b in blockers if b["experiment_path"] == experiment_path]
        assert len(codes) == len(set(codes))
        primary_codes = {
            "needs_human_review",
            "unresolved_preanalysis_blocker",
            "missing_semantic_analysis",
        }
        evidence_codes = {"unresolved_evidence_conflict", "unresolved_evidence_blocker"}
        assert sum(code in primary_codes for code in codes) <= 1
        assert sum(code in evidence_codes for code in codes) <= 1


def test_zero_experiments_produce_publication_blocker(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    config = _load_config_yaml(repo)
    config["evidence"]["canonical_facts"] = {}
    _write_config_yaml(repo, config)
    experiments_dir = repo / "questions" / "q001-throughput" / "experiments"
    for child in experiments_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
    _run_pipeline(repo)

    result = run_paperctl(repo, "audit", "--stage", "publication")

    assert result.returncode == 3
    report = read_json(repo / AUDIT_PATH)
    assert report["deterministic_health"]["status"] == "passed"
    assert report["publication_gate"]["status"] == "blocked"
    assert report["publication_gate"]["blockers"] == [
        {
            "severity": "blocker",
            "code": "no_experiments_discovered",
            "message": "No experiments were discovered in the manifest.",
            "question_path": None,
            "experiment_path": None,
        }
    ]


def test_missing_questions_root_is_deterministic_failure_not_publication_block(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    _run_pipeline(repo)
    shutil.rmtree(repo / "questions")

    result = run_paperctl(repo, "audit", "--stage", "publication")

    assert result.returncode == 2
    report = read_json(repo / AUDIT_PATH)
    assert report["deterministic_health"]["status"] == "failed"
    assert report["publication_gate"] == {"status": "passed", "blockers": []}
    assert report["publishable"] is False
    assert any(
        issue["code"] == "missing_questions_root"
        and issue["severity"] == "error"
        and "questions" in issue["message"]
        for issue in report["deterministic_health"]["issues"]
    )


def test_deterministic_audit_failure_does_not_contaminate_publication_gate(tmp_path):
    repo = copy_fixture_repo(tmp_path)

    result = run_paperctl(repo, "audit", "--stage", "deterministic")

    assert result.returncode == 2
    report = read_json(repo / AUDIT_PATH)
    assert report["deterministic_health"]["status"] == "failed"
    assert report["publication_gate"] == {"status": "passed", "blockers": []}
    assert report["publishable"] is False


def test_audit_reports_missing_and_stale_prerequisites_without_rebuilding_them(tmp_path):
    repo = copy_fixture_repo(tmp_path)

    missing_manifest = run_paperctl(repo, "audit", "--stage", "deterministic")
    assert missing_manifest.returncode == 2
    assert "missing_discovery_manifest" in missing_manifest.stderr
    assert (
        not (repo / AUDIT_PATH).exists()
        or read_json(repo / AUDIT_PATH)["deterministic_health"]["status"] == "failed"
    )

    manifest = _run_pipeline(repo)
    first_entry = manifest["experiments"][0]
    inventory_path = repo / first_entry["inventory_path"]
    inventory_path.unlink()

    missing_inventory = run_paperctl(repo, "audit", "--stage", "deterministic")

    assert missing_inventory.returncode == 2
    assert "missing_inventory" in missing_inventory.stderr
    assert not inventory_path.exists()

    inventory = run_paperctl(repo, "inventory", "--force")
    assert inventory.returncode == 0, inventory.stderr
    normalize = run_paperctl(repo, "normalize", "--force")
    assert normalize.returncode == 0, normalize.stderr
    render = run_paperctl(repo, "render", "--force")
    assert render.returncode == 0, render.stderr

    source_path = repo / first_entry["experiment_path"] / "outputs" / "experiment_report.json"
    source_path.write_text(
        source_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    stale = run_paperctl(repo, "audit", "--stage", "deterministic")

    assert stale.returncode == 2
    report = read_json(repo / AUDIT_PATH)
    assert any(
        issue["code"] in {"stale_inventory", "stale_evidence"}
        for issue in report["deterministic_health"]["issues"]
    )


def test_audit_detects_draft_nondeterminism_without_modifying_outputs(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    _run_pipeline(repo)
    draft_before = (repo / DRAFT_PATH).read_bytes()
    state_before = (repo / RENDER_STATE_PATH).read_bytes()
    final_before = (repo / FINAL_PATH).read_bytes()
    (repo / DRAFT_PATH).write_bytes(draft_before + b"\nmanual drift\n")
    tampered_draft = (repo / DRAFT_PATH).read_bytes()

    result = run_paperctl(repo, "audit", "--stage", "deterministic")

    assert result.returncode == 2
    assert (repo / DRAFT_PATH).read_bytes() == tampered_draft
    assert (repo / RENDER_STATE_PATH).read_bytes() == state_before
    assert (repo / FINAL_PATH).read_bytes() == final_before
    report = read_json(repo / AUDIT_PATH)
    assert any(
        issue["code"] in {"draft_hash_mismatch", "draft_content_mismatch"}
        for issue in report["deterministic_health"]["issues"]
    )


def test_audit_schema_records_deterministic_fingerprint_without_timestamps(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    manifest = _run_pipeline(repo)

    result = run_paperctl(repo, "audit", "--stage", "deterministic")

    assert result.returncode == 0, result.stderr
    report = read_json(repo / AUDIT_PATH)
    encoded = (repo / AUDIT_PATH).read_bytes()
    assert encoded == dump_json_bytes(report)
    assert b"timestamp" not in encoded.lower()
    fingerprint = dict(report["fingerprint"])
    fingerprint_sha256 = fingerprint.pop("fingerprint_sha256")
    assert fingerprint_sha256 == canonical_json_hash(fingerprint)
    assert fingerprint["inventory_sha256"] == [
        sha256_file(repo / entry["inventory_path"]) for entry in manifest["experiments"]
    ]
    assert fingerprint["evidence_packet_sha256"] == [
        sha256_file(repo / entry["evidence_path"]) for entry in manifest["experiments"]
    ]


def test_audit_rejects_repository_root_paper_md_report_without_touching_sentinel(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    config = _load_config_yaml(repo)
    config["paper"]["audit_report"] = "./PAPER.md"
    _write_config_yaml(repo, config)
    sentinel = (repo / FINAL_PATH).read_bytes()

    result = run_paperctl(repo, "audit", "--stage", "deterministic")

    assert result.returncode == 2
    assert "paper.audit_report must not target repository-root PAPER.md" in result.stderr
    assert (repo / FINAL_PATH).read_bytes() == sentinel


def test_audit_rejects_report_collision_with_draft_output_without_writing(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    config = _load_config_yaml(repo)
    config["paper"]["audit_report"] = "./PAPER.draft.md"
    _write_config_yaml(repo, config)
    sentinel_path = repo / DRAFT_PATH
    sentinel_path.write_text("protected draft sentinel\n", encoding="utf-8")

    result = run_paperctl(repo, "audit", "--stage", "deterministic")

    assert result.returncode == 2
    assert "paper.audit_report must not target protected paper.draft_output" in result.stderr
    assert sentinel_path.read_text(encoding="utf-8") == "protected draft sentinel\n"


def test_audit_rejects_report_collision_with_final_output_without_touching_sentinel(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    config = _load_config_yaml(repo)
    config["paper"]["final_output"] = "paper/final.md"
    config["paper"]["audit_report"] = "./paper/final.md"
    _write_config_yaml(repo, config)
    sentinel_path = repo / "paper" / "final.md"
    sentinel_path.parent.mkdir(parents=True, exist_ok=True)
    sentinel_path.write_text("protected final sentinel\n", encoding="utf-8")

    result = run_paperctl(repo, "audit", "--stage", "deterministic")

    assert result.returncode == 2
    assert "paper.audit_report must not target protected paper.final_output" in result.stderr
    assert sentinel_path.read_text(encoding="utf-8") == "protected final sentinel\n"


def test_audit_rejects_root_paper_symlink_to_report_target_without_touching_sentinel(
    tmp_path,
):
    repo = copy_fixture_repo(tmp_path)
    sentinel_path = repo / AUDIT_PATH
    sentinel_path.parent.mkdir(parents=True, exist_ok=True)
    sentinel_path.write_bytes(b"protected audit target sentinel\n")
    (repo / FINAL_PATH).unlink()
    (repo / FINAL_PATH).symlink_to(AUDIT_PATH)

    result = run_paperctl(repo, "audit", "--stage", "deterministic")

    assert result.returncode == 2
    assert sentinel_path.read_bytes() == b"protected audit target sentinel\n"
    assert "paper.audit_report must not target protected paper.final_output" in result.stderr


def test_audit_rejects_configured_final_output_symlink_to_report_target_without_touching_sentinel(
    tmp_path,
):
    repo = copy_fixture_repo(tmp_path)
    config = _load_config_yaml(repo)
    config["paper"]["final_output"] = "paper/final.md"
    _write_config_yaml(repo, config)
    sentinel_path = repo / AUDIT_PATH
    sentinel_path.parent.mkdir(parents=True, exist_ok=True)
    sentinel_path.write_bytes(b"protected audit target sentinel\n")
    (repo / "paper" / "final.md").symlink_to("PAPER.audit.json")

    result = run_paperctl(repo, "audit", "--stage", "deterministic")

    assert result.returncode == 2
    assert sentinel_path.read_bytes() == b"protected audit target sentinel\n"
    assert "paper.audit_report must not target protected paper.final_output" in result.stderr


def test_audit_rejects_report_collision_with_render_state_before_prerequisites(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    config = _load_config_yaml(repo)
    config["paper"]["audit_report"] = "paper/work/render-state.json"
    _write_config_yaml(repo, config)
    sentinel_path = repo / RENDER_STATE_PATH
    sentinel_path.parent.mkdir(parents=True, exist_ok=True)
    sentinel_path.write_text("protected render-state sentinel\n", encoding="utf-8")

    result = run_paperctl(repo, "audit", "--stage", "deterministic")

    assert result.returncode == 2
    assert "paper.audit_report must not target render state output" in result.stderr
    assert sentinel_path.read_text(encoding="utf-8") == "protected render-state sentinel\n"
    assert "missing discovery manifest" not in result.stderr


def test_audit_rejects_symlinked_report_output_directory_component(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    (repo / "paper").mkdir(exist_ok=True)
    (repo / "linked-output").symlink_to("paper", target_is_directory=True)
    config = _load_config_yaml(repo)
    config["paper"]["audit_report"] = "linked-output/PAPER.audit.json"
    _write_config_yaml(repo, config)

    result = run_paperctl(repo, "audit", "--stage", "deterministic")

    assert result.returncode == 2
    assert "paper.audit_report output path contains a symlink: linked-output" in result.stderr
    assert not (repo / "paper" / "PAPER.audit.json").exists()
