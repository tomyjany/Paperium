import pytest

from paperium.selection import (
    SelectionError,
    discover_menu_experiments,
    has_usable_run_artifact,
    resolve_question_readme,
    validate_manual_experiments,
)


def test_discovers_question_experiments(tmp_path):
    repo = tmp_path / "repo"
    exp_b = repo / "questions/q001/experiments/exp-b"
    exp_a = repo / "questions/q001/experiments/exp-a"
    exp_b.mkdir(parents=True)
    exp_a.mkdir(parents=True)
    (exp_b / "README.md").write_text("# Exp B\n")
    (exp_a / "README.md").write_text("# Exp A\n")
    assert discover_menu_experiments(repo) == [exp_a, exp_b]


def test_discovery_ignores_non_experiment_contract_directories(tmp_path):
    repo = tmp_path / "repo"
    valid = repo / "questions/q001/experiments/valid"
    invalid = repo / "questions/q001/experiments/empty"
    valid.mkdir(parents=True)
    invalid.mkdir(parents=True)
    (valid / "README.md").write_text("# Exp\n")

    assert discover_menu_experiments(repo) == [valid]


def test_discovery_ignores_symlink_experiment_escape(tmp_path):
    repo = tmp_path / "repo"
    experiments = repo / "questions/q001/experiments"
    experiments.mkdir(parents=True)
    outside = tmp_path / "outside-exp"
    outside.mkdir()
    symlink = experiments / "escape"
    try:
        symlink.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation unsupported: {exc}")

    assert discover_menu_experiments(repo) == []


def test_discovery_ignores_nested_helper_experiments(tmp_path):
    repo = tmp_path / "repo"
    exp_a = repo / "questions/q001/experiments/exp-a"
    helper = exp_a / "src/experiments/helper"
    helper.mkdir(parents=True)
    (exp_a / "README.md").write_text("# Exp A\n")

    assert discover_menu_experiments(repo) == [exp_a]


def test_outputs_file_is_usable_run_artifact(tmp_path):
    exp = tmp_path / "exp"
    outputs = exp / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "metrics.json").write_text("{}\n")
    assert has_usable_run_artifact(exp)


def test_run_artifact_patterns_outside_outputs_are_usable(tmp_path):
    exp = tmp_path / "exp"
    exp.mkdir()
    for file_name in [
        "metrics.jsonl",
        "result_summary.md",
        "stdout.log",
        "telemetry.csv",
        "benchmark_report.txt",
    ]:
        artifact = exp / file_name
        artifact.write_text("run data\n")
        assert has_usable_run_artifact(exp)
        artifact.unlink()


def test_root_level_excluded_artifact_patterns_are_not_usable(tmp_path):
    exp = tmp_path / "exp"
    exp.mkdir()
    for file_name in ["metrics.py", "summary.sh", "metrics.lock"]:
        artifact = exp / file_name
        artifact.write_text("not run data\n")
        assert not has_usable_run_artifact(exp)
        artifact.unlink()

    (exp / "summary.json").write_text("{}\n")
    assert has_usable_run_artifact(exp)


def test_readme_only_is_not_usable_run_artifact(tmp_path):
    exp = tmp_path / "exp"
    exp.mkdir()
    (exp / "README.md").write_text("# Generated context\n")
    assert not has_usable_run_artifact(exp)


def test_empty_outputs_is_not_usable_run_artifact(tmp_path):
    exp = tmp_path / "exp"
    (exp / "outputs").mkdir(parents=True)
    assert not has_usable_run_artifact(exp)


def test_empty_outputs_is_selectable_but_not_claimable(tmp_path):
    repo = tmp_path / "repo"
    exp = repo / "questions/q001/experiments/exp001"
    (exp / "outputs").mkdir(parents=True)
    assert validate_manual_experiments(repo, ["questions/q001/experiments/exp001"]) == [exp]
    assert not has_usable_run_artifact(exp)


def test_outputs_readme_is_not_usable_run_artifact(tmp_path):
    exp = tmp_path / "exp"
    outputs = exp / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "README.md").write_text("# Notes\n")
    assert not has_usable_run_artifact(exp)


def test_excluded_files_under_outputs_are_not_usable_run_artifacts(tmp_path):
    exp = tmp_path / "exp"
    outputs = exp / "outputs"
    outputs.mkdir(parents=True)
    excluded_files = [
        outputs / "docker-compose.yml",
        outputs / "metadata.json",
        outputs / "pyproject.toml",
        outputs / "README.md",
        outputs / "runner.sh",
        outputs / ".venv/lib/python/site-packages/package.py",
    ]
    for artifact in excluded_files:
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("not run data\n")
        assert not has_usable_run_artifact(exp)
        artifact.unlink()

    (outputs / "metrics.json").write_text("{}\n")
    assert has_usable_run_artifact(exp)


def test_symlinked_output_artifact_escape_is_not_usable_run_artifact(tmp_path):
    exp = tmp_path / "exp"
    outputs = exp / "outputs"
    outputs.mkdir(parents=True)
    outside_artifact = tmp_path / "outside-metrics.json"
    outside_artifact.write_text("{}\n")
    symlink = outputs / "metrics.json"
    try:
        symlink.symlink_to(outside_artifact)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation unsupported: {exc}")

    assert not has_usable_run_artifact(exp)

    symlink.unlink()
    (outputs / "metrics.json").write_text("{}\n")
    assert has_usable_run_artifact(exp)


def test_helper_tree_artifact_directories_are_not_usable_run_artifacts(tmp_path):
    exp = tmp_path / "exp"
    source_metrics = exp / "src/metrics"
    source_metrics.mkdir(parents=True)
    (source_metrics / "schema.json").write_text("{}\n")
    assert not has_usable_run_artifact(exp)

    (exp / "metrics").mkdir()
    (exp / "metrics/metrics.json").write_text("{}\n")
    assert has_usable_run_artifact(exp)

    (exp / "metrics/metrics.json").unlink()
    (exp / "outputs").mkdir()
    (exp / "outputs/metrics.json").write_text("{}\n")
    assert has_usable_run_artifact(exp)


def test_resolves_parent_question_readme(tmp_path):
    repo = tmp_path / "repo"
    q = repo / "questions/q001"
    exp = q / "experiments/exp001"
    exp.mkdir(parents=True)
    (q / "README.md").write_text("# Question\n")
    assert resolve_question_readme(repo, exp) == q / "README.md"


def test_resolve_question_readme_ignores_experiments_directory_readme(tmp_path):
    repo = tmp_path / "repo"
    q = repo / "questions/q001"
    experiments = q / "experiments"
    exp = experiments / "exp001"
    exp.mkdir(parents=True)
    (q / "README.md").write_text("# Question\n")
    (experiments / "README.md").write_text("# Experiments index\n")

    assert resolve_question_readme(repo, exp) == q / "README.md"


def test_missing_question_readme_returns_none(tmp_path):
    repo = tmp_path / "repo"
    exp = repo / "questions/q001/experiments/exp001"
    exp.mkdir(parents=True)
    assert resolve_question_readme(repo, exp) is None


def test_validate_manual_experiments_rejects_missing_file_and_outside_paths(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    file_path = repo / "file.txt"
    file_path.write_text("not an experiment")
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(SelectionError):
        validate_manual_experiments(repo, ["missing"])
    with pytest.raises(SelectionError):
        validate_manual_experiments(repo, ["file.txt"])
    with pytest.raises(SelectionError):
        validate_manual_experiments(repo, [str(outside)])


def test_validate_manual_experiments_accepts_valid_output_experiment(tmp_path):
    repo = tmp_path / "repo"
    exp = repo / "questions/q001/experiments/exp001"
    outputs = exp / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "metrics.jsonl").write_text('{"pages": 10}\n')
    assert validate_manual_experiments(repo, ["questions/q001/experiments/exp001"]) == [exp]


def test_validate_manual_experiments_accepts_root_level_run_artifact(tmp_path):
    repo = tmp_path / "repo"
    exp = repo / "questions/q001/experiments/exp001"
    exp.mkdir(parents=True)
    (exp / "metrics.jsonl").write_text('{"pages": 10}\n')
    assert validate_manual_experiments(repo, ["questions/q001/experiments/exp001"]) == [exp]


def test_validate_manual_experiments_rejects_empty_directory(tmp_path):
    repo = tmp_path / "repo"
    exp = repo / "questions/q001/experiments/empty"
    exp.mkdir(parents=True)
    with pytest.raises(SelectionError):
        validate_manual_experiments(repo, ["questions/q001/experiments/empty"])


def test_executable_runner_script_satisfies_experiment_contract(tmp_path):
    repo = tmp_path / "repo"
    exp = repo / "questions/q001/experiments/exp001"
    exp.mkdir(parents=True)
    runner = exp / "runner.sh"
    runner.write_text("#!/usr/bin/env bash\n")
    runner.chmod(0o755)
    assert validate_manual_experiments(repo, ["questions/q001/experiments/exp001"]) == [exp]


def test_readme_only_experiment_is_selectable_but_not_claimable(tmp_path):
    repo = tmp_path / "repo"
    exp = repo / "questions/q001/experiments/exp001"
    exp.mkdir(parents=True)
    (exp / "README.md").write_text("# Run plan\n")
    assert validate_manual_experiments(repo, ["questions/q001/experiments/exp001"]) == [exp]
    assert not has_usable_run_artifact(exp)


def test_metadata_compose_and_pyproject_contracts_are_selectable(tmp_path):
    repo = tmp_path / "repo"
    for name, file_name in [
        ("metadata", "metadata.json"),
        ("compose", "docker-compose.yml"),
        ("pyproject", "pyproject.toml"),
    ]:
        exp = repo / f"questions/q001/experiments/{name}"
        exp.mkdir(parents=True)
        (exp / file_name).write_text("{}\n")
        assert validate_manual_experiments(repo, [f"questions/q001/experiments/{name}"]) == [exp]
        assert not has_usable_run_artifact(exp)
