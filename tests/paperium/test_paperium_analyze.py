import json

import pytest

from paperium.analyze import (
    FactCheckError,
    FactCheckResult,
    apply_fact_check_result,
    load_fact_check_result,
    next_fact_check_status,
    prepare_selected_experiment,
)


def _write_fact_check(path, payload):
    path.write_text(json.dumps(payload))


def _finding(**overrides):
    finding = {
        "severity": "error",
        "claim": "Throughput was 10 pages/s",
        "reason": "contradicted: metrics disagree",
        "artifact_path": "outputs/metrics.json",
        "selector": "/pages_per_second",
    }
    finding.update(overrides)
    return finding


def test_readme_only_experiment_becomes_artifact_missing(tmp_path):
    repo = tmp_path / "repo"
    exp = repo / "questions/q001/experiments/exp001"
    exp.mkdir(parents=True)
    (exp / "README.md").write_text("# Exp\n")
    selected = prepare_selected_experiment(repo, exp)
    assert selected.path == "questions/q001/experiments/exp001"
    assert selected.question_readme is None
    assert (
        selected.analysis_path
        == "questions/q001/experiments/exp001/.paperium/analysis.md"
    )
    assert (
        selected.fact_check_result_path
        == "questions/q001/experiments/exp001/.paperium/fact-check.json"
    )
    assert selected.disposition == "artifact_missing"
    assert selected.status == "needs_human_review"
    assert selected.repair_attempts == 0


def test_failed_fact_check_allows_two_repairs_then_human_review():
    assert next_fact_check_status(repair_attempts=0, fact_check_passed=False) == (
        "running",
        1,
    )
    assert next_fact_check_status(repair_attempts=1, fact_check_passed=False) == (
        "running",
        2,
    )
    assert next_fact_check_status(repair_attempts=2, fact_check_passed=False) == (
        "needs_human_review",
        2,
    )


def test_passed_fact_check_approves_experiment():
    assert next_fact_check_status(repair_attempts=1, fact_check_passed=True) == (
        "approved",
        1,
    )


def test_load_fact_check_result_requires_status_and_findings(tmp_path):
    path = tmp_path / "fact-check.json"
    _write_fact_check(
        path,
        {
            "status": "failed",
            "findings": [
                _finding(
                    reason="unsupported: no supporting artifact",
                    artifact_path=None,
                    selector=None,
                )
            ],
        },
    )
    result = load_fact_check_result(path)
    assert result == FactCheckResult(
        status="failed",
        findings=[
            {
                "severity": "error",
                "claim": "Throughput was 10 pages/s",
                "reason": "unsupported: no supporting artifact",
                "artifact_path": None,
                "selector": None,
            }
        ],
    )

    _write_fact_check(path, {"findings": []})
    with pytest.raises(FactCheckError):
        load_fact_check_result(path)

    _write_fact_check(path, {"status": "passed"})
    with pytest.raises(FactCheckError):
        load_fact_check_result(path)

    _write_fact_check(path, {"status": "unknown", "findings": []})
    with pytest.raises(FactCheckError):
        load_fact_check_result(path)

    _write_fact_check(path, {"status": "passed", "findings": {}})
    with pytest.raises(FactCheckError):
        load_fact_check_result(path)


def test_load_fact_check_result_validates_finding_fields_and_selector_rules(tmp_path):
    path = tmp_path / "fact-check.json"
    _write_fact_check(path, {"status": "failed", "findings": [_finding()]})
    assert load_fact_check_result(path).findings[0]["selector"] == "/pages_per_second"

    _write_fact_check(
        path,
        {"status": "failed", "findings": [_finding(selector=None)]},
    )
    with pytest.raises(FactCheckError):
        load_fact_check_result(path)

    _write_fact_check(
        path,
        {"status": "failed", "findings": [_finding(artifact_path=None)]},
    )
    with pytest.raises(FactCheckError):
        load_fact_check_result(path)

    _write_fact_check(
        path,
        {
            "status": "failed",
            "findings": [
                _finding(
                    reason="contradicted: metrics disagree",
                    artifact_path=None,
                    selector=None,
                )
            ],
        },
    )
    with pytest.raises(FactCheckError):
        load_fact_check_result(path)

    _write_fact_check(
        path,
        {
            "status": "failed",
            "findings": [
                _finding(
                    reason="unsupported: no artifact",
                    artifact_path=None,
                    selector=None,
                )
            ],
        },
    )
    assert load_fact_check_result(path).findings[0]["artifact_path"] is None


@pytest.mark.parametrize(
    ("reason", "artifact_path", "selector"),
    [
        ("unsupported:", None, None),
        ("no_artifact:", None, None),
        ("contradicted:", "outputs/metrics.json", "/pages_per_second"),
        ("needs_correction:", "outputs/metrics.json", "/pages_per_second"),
    ],
)
def test_load_fact_check_result_rejects_prefix_only_reasons(
    tmp_path,
    reason,
    artifact_path,
    selector,
):
    path = tmp_path / "fact-check.json"
    _write_fact_check(
        path,
        {
            "status": "failed",
            "findings": [
                _finding(
                    reason=reason,
                    artifact_path=artifact_path,
                    selector=selector,
                )
            ],
        },
    )

    with pytest.raises(FactCheckError):
        load_fact_check_result(path)


def test_load_fact_check_result_rejects_unsafe_artifact_paths_selectors_and_unallowed_artifacts(
    tmp_path,
):
    path = tmp_path / "fact-check.json"
    for artifact_path in [
        "/etc/passwd",
        "../outside.json",
        "outputs\\metrics.json",
        "C:/tmp/metrics.json",
        "",
    ]:
        _write_fact_check(
            path,
            {
                "status": "failed",
                "findings": [_finding(artifact_path=artifact_path)],
            },
        )
        with pytest.raises(FactCheckError):
            load_fact_check_result(path)

    for selector in ["pages_per_second", "", None]:
        _write_fact_check(
            path,
            {"status": "failed", "findings": [_finding(selector=selector)]},
        )
        with pytest.raises(FactCheckError):
            load_fact_check_result(path)

    _write_fact_check(
        path,
        {
            "status": "failed",
            "findings": [_finding(artifact_path="outputs/other.json")],
        },
    )
    with pytest.raises(FactCheckError):
        load_fact_check_result(path, allowed_artifact_paths={"outputs/metrics.json"})


def test_load_fact_check_result_rejects_extra_top_level_or_finding_keys(tmp_path):
    path = tmp_path / "fact-check.json"
    _write_fact_check(
        path,
        {"status": "passed", "findings": [], "extra": True},
    )
    with pytest.raises(FactCheckError):
        load_fact_check_result(path)

    finding = _finding(kind="unsupported")
    _write_fact_check(path, {"status": "failed", "findings": [finding]})
    with pytest.raises(FactCheckError):
        load_fact_check_result(path)


def test_load_fact_check_result_rejects_invalid_severity_empty_fields_and_failed_empty_findings(
    tmp_path,
):
    path = tmp_path / "fact-check.json"
    for overrides in [
        {"severity": "info"},
        {"claim": ""},
        {"reason": ""},
        {"reason": "unsupported"},
    ]:
        _write_fact_check(
            path,
            {"status": "failed", "findings": [_finding(**overrides)]},
        )
        with pytest.raises(FactCheckError):
            load_fact_check_result(path)

    _write_fact_check(path, {"status": "failed", "findings": []})
    with pytest.raises(FactCheckError):
        load_fact_check_result(path)


@pytest.mark.parametrize("severity", [[], None, 1])
def test_load_fact_check_result_rejects_non_string_severity(tmp_path, severity):
    path = tmp_path / "fact-check.json"
    _write_fact_check(
        path,
        {"status": "failed", "findings": [_finding(severity=severity)]},
    )

    with pytest.raises(FactCheckError):
        load_fact_check_result(path)


def test_apply_passed_fact_check_makes_experiment_ranking_eligible():
    selected = {"status": "running", "repair_attempts": 1, "disposition": "deferred"}
    updated = apply_fact_check_result(
        selected,
        FactCheckResult(status="passed", findings=[]),
    )
    assert updated["status"] == "approved"
    assert updated["disposition"] is None
    assert updated["repair_attempts"] == 1
    assert selected["status"] == "running"
    assert selected["disposition"] == "deferred"


def test_apply_failed_fact_check_after_repairs_requires_human_review():
    selected = {"status": "running", "repair_attempts": 2, "disposition": None}
    updated = apply_fact_check_result(
        selected,
        FactCheckResult(status="failed", findings=[_finding()]),
    )
    assert updated["status"] == "needs_human_review"
    assert updated["disposition"] == "fact_check_failed"
    assert updated["repair_attempts"] == 2
    assert selected["status"] == "running"


def test_apply_failed_fact_check_with_repairs_remaining_keeps_experiment_running():
    selected = {"status": "running", "repair_attempts": 1, "disposition": None}
    updated = apply_fact_check_result(
        selected,
        FactCheckResult(status="failed", findings=[_finding()]),
    )
    assert updated["status"] == "running"
    assert updated["disposition"] is None
    assert updated["repair_attempts"] == 2


def test_prepare_selected_experiment_resolves_question_readme_and_creates_output_dir(
    tmp_path,
):
    repo = tmp_path / "repo"
    q = repo / "questions/q001"
    exp = q / "experiments/exp001"
    outputs = exp / "outputs"
    outputs.mkdir(parents=True)
    (q / "README.md").write_text("# Q\n")
    (outputs / "metrics.json").write_text("{}\n")
    selected = prepare_selected_experiment(repo, exp)
    assert selected.question_readme == "questions/q001/README.md"
    assert (exp / ".paperium").exists()


def test_prepare_selected_experiment_accepts_root_level_metrics_artifact(tmp_path):
    repo = tmp_path / "repo"
    exp = repo / "questions/q001/experiments/exp001"
    exp.mkdir(parents=True)
    (exp / "metrics.jsonl").write_text('{"pages": 10}\n')
    selected = prepare_selected_experiment(repo, exp)
    assert selected.status == "pending"
    assert selected.disposition is None


def test_prepare_selected_experiment_treats_metadata_only_as_artifact_missing(tmp_path):
    repo = tmp_path / "repo"
    exp = repo / "questions/q001/experiments/exp001"
    exp.mkdir(parents=True)
    (exp / "metadata.json").write_text("{}\n")
    selected = prepare_selected_experiment(repo, exp)
    assert selected.status == "needs_human_review"
    assert selected.disposition == "artifact_missing"


def test_prepare_selected_experiment_rejects_experiment_outside_repo(tmp_path):
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ValueError, match="outside repository"):
        prepare_selected_experiment(repo, outside)


def test_prepare_selected_experiment_rejects_symlinked_output_dir_outside_repo(
    tmp_path,
):
    repo = tmp_path / "repo"
    exp = repo / "questions/q001/experiments/exp001"
    outside = tmp_path / "outside"
    exp.mkdir(parents=True)
    outside.mkdir()
    (exp / ".paperium").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match=r"\.paperium.*symlink.*outside"):
        prepare_selected_experiment(repo, exp)

    assert list(outside.iterdir()) == []
