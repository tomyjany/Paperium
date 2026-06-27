from paperium.paths import PaperiumPaths


def test_root_and_experiment_paths(tmp_path):
    repo = tmp_path / "repo"
    exp = repo / "questions/q001/experiments/exp001"
    exp.mkdir(parents=True)
    paths = PaperiumPaths(repo)
    assert paths.root_dir == repo / ".paperium"
    assert paths.state_path == repo / ".paperium/state.json"
    assert paths.experiment_analysis_path(exp) == exp / ".paperium/analysis.md"
    assert paths.experiment_fact_check_path(exp) == exp / ".paperium/fact-check.json"
