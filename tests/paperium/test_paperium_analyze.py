import pytest

from paperium.analyze import prepare_selected_experiment


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
