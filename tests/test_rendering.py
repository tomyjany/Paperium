from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from conftest import copy_fixture_repo, read_json, run_paperctl
from paperctl._support.hashing import sha256_file
from paperctl._support.schema import validate_artifact


MANIFEST_PATH = Path("paper/work/manifest.json")
RENDER_STATE_PATH = Path("paper/work/render-state.json")
DRAFT_PATH = Path("PAPER.draft.md")
FINAL_PATH = Path("PAPER.md")


def _run_prerequisites(repo: Path) -> dict[str, Any]:
    discovered = run_paperctl(repo, "discover")
    assert discovered.returncode == 0, discovered.stderr
    inventoried = run_paperctl(repo, "inventory")
    assert inventoried.returncode == 0, inventoried.stderr
    normalized = run_paperctl(repo, "normalize")
    assert normalized.returncode == 0, normalized.stderr
    return read_json(repo / MANIFEST_PATH)


def _entry(manifest: dict[str, Any], experiment_ref: str) -> dict[str, Any]:
    return next(
        entry for entry in manifest["experiments"] if entry["experiment_ref"] == experiment_ref
    )


def test_render_requires_fresh_manifest_inventory_and_evidence_without_running_prerequisites(
    tmp_path,
):
    repo = copy_fixture_repo(tmp_path)

    missing_manifest = run_paperctl(repo, "render")

    assert missing_manifest.returncode == 2
    assert "missing discovery manifest" in missing_manifest.stderr
    assert not (repo / DRAFT_PATH).exists()
    assert not (repo / RENDER_STATE_PATH).exists()

    discovered = run_paperctl(repo, "discover")
    assert discovered.returncode == 0, discovered.stderr
    missing_inventory = run_paperctl(repo, "render")

    assert missing_inventory.returncode == 2
    assert "missing artifact inventory" in missing_inventory.stderr
    assert "run paperctl inventory first" in missing_inventory.stderr
    assert not (repo / DRAFT_PATH).exists()

    inventoried = run_paperctl(repo, "inventory")
    assert inventoried.returncode == 0, inventoried.stderr
    missing_evidence = run_paperctl(repo, "render")

    assert missing_evidence.returncode == 2
    assert "missing evidence packet" in missing_evidence.stderr
    assert "run paperctl normalize first" in missing_evidence.stderr
    assert not (repo / DRAFT_PATH).exists()

    normalized = run_paperctl(repo, "normalize")
    assert normalized.returncode == 0, normalized.stderr
    late_experiment = (
        repo / "questions" / "q001-throughput" / "experiments" / "exp999-after-discovery"
    )
    late_experiment.mkdir()
    (late_experiment / "README.md").write_text("# Late experiment\n", encoding="utf-8")
    stale_manifest = run_paperctl(repo, "render")

    assert stale_manifest.returncode == 2
    assert "stale discovery manifest" in stale_manifest.stderr
    assert not (repo / DRAFT_PATH).exists()


def test_render_rejects_stale_evidence_packet_without_rebuilding_it(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    manifest = _run_prerequisites(repo)
    evidence_path = repo / _entry(manifest, "exp001-completed")["evidence_path"]
    packet = read_json(evidence_path)
    packet["execution_status"] = "failed"
    evidence_path.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")

    result = run_paperctl(repo, "render")

    assert result.returncode == 2
    assert "stale evidence packet" in result.stderr
    assert "run paperctl normalize --force first" in result.stderr
    assert read_json(evidence_path)["execution_status"] == "failed"
    assert not (repo / DRAFT_PATH).exists()


def test_render_writes_bounded_preanalysis_draft_and_state_without_touching_final_paper(
    tmp_path,
):
    repo = copy_fixture_repo(tmp_path)
    experiment = (
        repo / "questions" / "q001-throughput" / "experiments" / "exp005-unsupported-and-previews"
    )
    (experiment / "outputs" / "metrics.csv").write_text(
        "name,value,api_token\n"
        + "\n".join(f"row-{index},{index},secret-{index}" for index in range(1, 26))
        + "\n",
        encoding="utf-8",
    )
    (experiment / "outputs" / "unsafe.md").write_text(
        "# Unsafe <heading> token=super-secret\nPlain | table marker\n",
        encoding="utf-8",
    )
    empty_experiment = repo / "questions" / "q001-throughput" / "experiments" / "exp006-empty"
    empty_experiment.mkdir()
    final_before = (repo / FINAL_PATH).read_bytes()
    manifest = _run_prerequisites(repo)

    result = run_paperctl(repo, "render")

    assert result.returncode == 0, result.stderr
    assert "wrote PAPER.draft.md" in result.stdout
    assert (repo / FINAL_PATH).read_bytes() == final_before
    draft_bytes = (repo / DRAFT_PATH).read_bytes()
    draft = draft_bytes.decode("utf-8")

    assert "PRE-ANALYSIS EVIDENCE DRAFT" in draft
    assert "not a publishable paper" in draft
    assert "never promoted to PAPER.md in Milestone 1" in draft
    assert "## Question `questions/q001-throughput`" in draft
    assert "README: `questions/q001-throughput/README.md`" in draft
    assert sha256_file(repo / "questions/q001-throughput/README.md") in draft
    assert "`questions/q001-throughput/experiments/exp001-completed`" in draft
    assert "preanalysis_disposition: `analysis_candidate`" in draft
    assert "execution_status: `completed`" in draft
    assert "evidence_status: `available`" in draft
    assert "#### Canonical Facts" in draft
    assert "throughput_pages_per_second" in draft
    assert "#### Observed Values" in draft
    assert "#### Previews" in draft
    assert "#### Diagnostics" in draft
    assert "#### Warnings" in draft
    assert "#### Unsupported Artifacts" in draft
    assert "omitted" in draft
    assert _entry(manifest, "exp005-unsupported-and-previews")["evidence_path"] in draft

    assert "missing_semantic_analysis" in draft
    assert "needs_human_review" in draft
    assert "unresolved_evidence_conflict" in draft
    assert "unresolved_evidence_blocker" in draft

    forbidden_fragments = [
        "## interpretation",
        "## recommendations",
        "## conclusions",
        "semantic comparison",
        "ranking",
        "ranked",
        "ratio",
        "best",
        "interpretation unavailable",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in draft.lower()

    exp005_section = draft.split(
        "### Experiment `questions/q001-throughput/experiments/exp005-unsupported-and-previews`",
        1,
    )[1].split("### Experiment `questions/q001-throughput/experiments/legacy-baseline`", 1)[0]
    canonical_section = exp005_section.split("#### Canonical Facts", 1)[1].split(
        "#### Observed Values", 1
    )[0]
    observed_section = exp005_section.split("#### Observed Values", 1)[1].split("#### Previews", 1)[
        0
    ]
    diagnostic_section = exp005_section.split("#### Diagnostics", 1)[1].split("#### Warnings", 1)[0]
    assert "csv_numeric_column_summary" not in canonical_section
    assert "jsonl_numeric_field_summary" not in canonical_section
    assert "csv_numeric_column_summary" not in observed_section
    assert "jsonl_numeric_field_summary" not in observed_section
    assert "csv_numeric_column_summary" in diagnostic_section
    assert "jsonl_numeric_field_summary" in diagnostic_section

    assert "<heading>" not in draft
    assert "super-secret" not in draft
    assert "secret-1" not in draft
    assert "[REDACTED]" in draft

    state = read_json(repo / RENDER_STATE_PATH)
    validate_artifact("render-state.schema.json", state)
    assert state["draft_output"] == "PAPER.draft.md"
    assert state["manifest_sha256"] == sha256_file(repo / MANIFEST_PATH)
    assert state["evidence_packet_sha256"] == [
        sha256_file(repo / entry["evidence_path"]) for entry in manifest["experiments"]
    ]
    assert state["fingerprint"]["renderer_version"] == "1"
    assert state["fingerprint"]["draft_path"] == "PAPER.draft.md"
    assert state["fingerprint"]["draft_sha256"] == sha256_file(repo / DRAFT_PATH)
    assert state["fingerprint"]["manifest_sha256"] == state["manifest_sha256"]
    assert state["fingerprint"]["evidence_packet_sha256"] == state["evidence_packet_sha256"]
    assert state["fingerprint"]["config_sha256"].startswith("sha256:")
    assert state["fingerprint"]["fingerprint_sha256"].startswith("sha256:")


def test_render_is_byte_identical_and_force_only_bypasses_render_cache(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    _run_prerequisites(repo)

    first = run_paperctl(repo, "render")
    assert first.returncode == 0, first.stderr
    draft_first = (repo / DRAFT_PATH).read_bytes()
    state_first = (repo / RENDER_STATE_PATH).read_bytes()
    draft_mtime_first = (repo / DRAFT_PATH).stat().st_mtime_ns
    state_mtime_first = (repo / RENDER_STATE_PATH).stat().st_mtime_ns

    cached = run_paperctl(repo, "render")
    assert cached.returncode == 0, cached.stderr
    assert "unchanged PAPER.draft.md" in cached.stdout
    assert (repo / DRAFT_PATH).read_bytes() == draft_first
    assert (repo / RENDER_STATE_PATH).read_bytes() == state_first
    assert (repo / DRAFT_PATH).stat().st_mtime_ns == draft_mtime_first
    assert (repo / RENDER_STATE_PATH).stat().st_mtime_ns == state_mtime_first

    time.sleep(0.01)
    forced = run_paperctl(repo, "render", "--force")
    assert forced.returncode == 0, forced.stderr
    assert "wrote PAPER.draft.md" in forced.stdout
    assert (repo / DRAFT_PATH).read_bytes() == draft_first
    assert (repo / RENDER_STATE_PATH).read_bytes() == state_first
    assert (repo / DRAFT_PATH).stat().st_mtime_ns != draft_mtime_first
    assert (repo / RENDER_STATE_PATH).stat().st_mtime_ns != state_mtime_first
