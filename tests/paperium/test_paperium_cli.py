import json

import paperium.selection
from paperium.cli import main
from paperium.state import PaperiumState, SelectedExperiment, WorkerRecord, load_state, save_state


def create_selectable_experiment(repo, relative_path, *, with_question_readme=True):
    experiment = repo / relative_path
    experiment.mkdir(parents=True)
    if with_question_readme:
        (experiment.parents[1] / "README.md").write_text("# Question\n", encoding="utf-8")
    (experiment / "metrics.jsonl").write_text('{"pages": 10}\n', encoding="utf-8")
    return experiment


def test_help_returns_success(capsys):
    assert main(["--help"]) == 0
    assert "paperium" in capsys.readouterr().out


def test_requires_command(capsys):
    assert main([]) == 0
    assert "usage:" in capsys.readouterr().out


def test_unknown_option_returns_invalid_invocation(capsys):
    assert main(["--unknown"]) == 4
    captured = capsys.readouterr()
    assert "error:" in captured.err


def test_unimplemented_command_reports_error_on_stderr(capsys):
    assert main(["analyze"]) == 4
    captured = capsys.readouterr()
    assert "command not implemented yet: analyze" in captured.err
    assert "command not implemented yet: analyze" not in captured.out


def test_select_manual_paths_records_experiments(tmp_path, capsys):
    repo = tmp_path / "repo"
    create_selectable_experiment(repo, "questions/q001/experiments/exp001")
    save_state(repo / ".paperium" / "state.json", PaperiumState())

    assert main(["--repo", str(repo), "select", "questions/q001/experiments/exp001"]) == 0

    state = load_state(repo / ".paperium" / "state.json")
    assert state.phase == "analyzing"
    assert state.selected_experiments == [
        SelectedExperiment(
            path="questions/q001/experiments/exp001",
            question_readme="questions/q001/README.md",
            analysis_path="questions/q001/experiments/exp001/.paperium/analysis.md",
            fact_check_result_path="questions/q001/experiments/exp001/.paperium/fact-check.json",
            disposition=None,
        )
    ]
    captured = capsys.readouterr()
    assert "Selected experiments: 1" in captured.out
    assert captured.err == ""


def test_select_interactive_menu_records_chosen_experiment(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    experiment = create_selectable_experiment(repo, "questions/q001/experiments/exp001")
    save_state(repo / ".paperium" / "state.json", PaperiumState())
    monkeypatch.setattr("paperium.cli.stdin_is_tty", lambda: True)
    monkeypatch.setattr("paperium.cli.stdout_is_tty", lambda: True)
    monkeypatch.setattr(
        paperium.selection,
        "choose_experiments_menu",
        lambda selected_repo: [experiment] if selected_repo == repo.resolve() else [],
    )

    assert main(["--repo", str(repo), "select", "--experiments-menu"]) == 0

    state = load_state(repo / ".paperium" / "state.json")
    assert state.phase == "analyzing"
    assert state.selected_experiments[0].path == "questions/q001/experiments/exp001"
    assert state.selected_experiments[0].question_readme == "questions/q001/README.md"
    assert "Selected experiments: 1" in capsys.readouterr().out


def test_select_menu_rejects_non_interactive(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    save_state(repo / ".paperium" / "state.json", PaperiumState())
    monkeypatch.setattr("paperium.cli.stdin_is_tty", lambda: False)
    monkeypatch.setattr("paperium.cli.stdout_is_tty", lambda: True)

    assert main(["--repo", str(repo), "select", "--experiments-menu"]) == 4

    captured = capsys.readouterr()
    assert "interactive" in captured.err
    assert captured.out == ""


def test_select_rejects_empty_manual_selection(tmp_path, capsys):
    repo = tmp_path / "repo"
    save_state(repo / ".paperium" / "state.json", PaperiumState())

    assert main(["--repo", str(repo), "select"]) == 4

    captured = capsys.readouterr()
    assert "experiment path" in captured.err
    assert captured.out == ""


def test_select_manual_and_menu_are_mutually_exclusive(tmp_path, capsys):
    repo = tmp_path / "repo"
    create_selectable_experiment(repo, "questions/q001/experiments/exp001")
    save_state(repo / ".paperium" / "state.json", PaperiumState())

    assert (
        main(
            [
                "--repo",
                str(repo),
                "select",
                "questions/q001/experiments/exp001",
                "--experiments-menu",
            ]
        )
        == 4
    )

    captured = capsys.readouterr()
    assert "not allowed with argument" in captured.err


def test_select_rejects_missing_state(tmp_path, capsys):
    repo = tmp_path / "repo"
    create_selectable_experiment(repo, "questions/q001/experiments/exp001")

    assert main(["--repo", str(repo), "select", "questions/q001/experiments/exp001"]) == 2

    captured = capsys.readouterr()
    assert "state" in captured.err
    assert "missing" in captured.err
    assert captured.out == ""


def test_select_rejects_invalid_experiment_path(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    save_state(repo / ".paperium" / "state.json", PaperiumState())

    assert main(["--repo", str(repo), "select", "missing"]) == 2

    captured = capsys.readouterr()
    assert "Experiment path does not exist" in captured.err
    assert captured.out == ""


def test_select_replaces_previous_selection(tmp_path, capsys):
    repo = tmp_path / "repo"
    create_selectable_experiment(repo, "questions/q001/experiments/exp001")
    create_selectable_experiment(repo, "questions/q001/experiments/exp002")
    save_state(
        repo / ".paperium" / "state.json",
        PaperiumState(
            selected_experiments=[
                SelectedExperiment(
                    path="questions/q001/experiments/exp001",
                    question_readme="questions/q001/README.md",
                    analysis_path="questions/q001/experiments/exp001/.paperium/analysis.md",
                    fact_check_result_path=(
                        "questions/q001/experiments/exp001/.paperium/fact-check.json"
                    ),
                    disposition="included",
                    status="approved",
                )
            ],
        ),
    )

    assert main(["--repo", str(repo), "select", "questions/q001/experiments/exp002"]) == 0

    state = load_state(repo / ".paperium" / "state.json")
    assert [experiment.path for experiment in state.selected_experiments] == [
        "questions/q001/experiments/exp002"
    ]
    assert state.selected_experiments[0].status == "pending"
    assert state.selected_experiments[0].disposition is None
    assert "Selected experiments: 1" in capsys.readouterr().out


def test_command_surface_lists_v1_commands(capsys):
    assert main(["--help"]) == 0
    output = capsys.readouterr().out
    for command in [
        "init",
        "status",
        "select",
        "analyze",
        "rank",
        "approve",
        "context",
        "section",
        "write",
    ]:
        assert command in output


def test_init_creates_state_and_gitignore(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()

    assert main(["--repo", str(repo), "init"]) == 0

    state_path = repo / ".paperium" / "state.json"
    gitignore_path = repo / ".gitignore"
    assert load_state(state_path) == PaperiumState()
    assert ".paperium/" in gitignore_path.read_text(encoding="utf-8")
    captured = capsys.readouterr()
    assert str(state_path) in captured.out
    assert str(gitignore_path) in captured.out
    assert captured.err == ""


def test_init_without_repo_uses_current_git_root(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    nested = repo / "a" / "b"
    nested.mkdir(parents=True)
    (repo / ".git").mkdir()
    monkeypatch.chdir(nested)

    assert main(["init"]) == 0

    assert (repo / ".paperium" / "state.json").exists()
    assert not (nested / ".paperium" / "state.json").exists()
    assert str(repo / ".paperium" / "state.json") in capsys.readouterr().out


def test_init_does_not_overwrite_existing_state(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    state_path = repo / ".paperium" / "state.json"
    save_state(state_path, PaperiumState(phase="analyzing"))
    original_content = state_path.read_text(encoding="utf-8")

    assert main(["--repo", str(repo), "init"]) == 0

    assert state_path.read_text(encoding="utf-8") == original_content
    assert load_state(state_path).phase == "analyzing"
    assert "state.json" in capsys.readouterr().out


def test_init_missing_repo_returns_failure(tmp_path, capsys):
    missing_repo = tmp_path / "missing"

    assert main(["--repo", str(missing_repo), "init"]) == 2

    captured = capsys.readouterr()
    assert "target repo does not exist" in captured.err
    assert str(missing_repo) in captured.err
    assert captured.out == ""


def test_status_prints_phase(tmp_path, capsys):
    repo = tmp_path / "repo"
    state_path = repo / ".paperium" / "state.json"
    save_state(state_path, PaperiumState(phase="ranking"))

    assert main(["--repo", str(repo), "status"]) == 0

    captured = capsys.readouterr()
    assert "Phase: ranking" in captured.out
    assert captured.err == ""


def test_status_reports_running_failed_waiting_workers_and_experiment_issues(tmp_path, capsys):
    repo = tmp_path / "repo"
    save_state(
        repo / ".paperium" / "state.json",
        PaperiumState(
            workers=[
                WorkerRecord(id="running", backend="codex", role="analyze", status="running"),
                WorkerRecord(id="failed", backend="codex", role="analyze", status="failed"),
                WorkerRecord(
                    id="needs-context",
                    backend="codex",
                    role="analyze",
                    status="needs_context",
                ),
                WorkerRecord(id="done", backend="codex", role="analyze", status="succeeded"),
            ],
            selected_experiments=[
                SelectedExperiment(
                    path="experiments/ok",
                    question_readme=None,
                    analysis_path=".paperium/ok.json",
                    fact_check_result_path=".paperium/ok-fact.json",
                    disposition="included",
                    status="approved",
                ),
                SelectedExperiment(
                    path="experiments/failed",
                    question_readme=None,
                    analysis_path=".paperium/failed.json",
                    fact_check_result_path=".paperium/failed-fact.json",
                    disposition="fact_check_failed",
                    status="failed",
                ),
                SelectedExperiment(
                    path="experiments/review",
                    question_readme=None,
                    analysis_path=".paperium/review.json",
                    fact_check_result_path=".paperium/review-fact.json",
                    disposition="needs_human_review",
                    status="needs_human_review",
                ),
            ],
        ),
    )

    assert main(["--repo", str(repo), "status"]) == 0

    captured = capsys.readouterr()
    assert "Selected experiments: 3" in captured.out
    assert "Workers: 1 running, 1 failed, 1 waiting for user" in captured.out
    assert "Experiment issues: 2" in captured.out
    assert captured.err == ""


def test_status_missing_state_returns_failure(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()

    assert main(["--repo", str(repo), "status"]) == 2

    captured = capsys.readouterr()
    assert "state" in captured.err
    assert "missing" in captured.err
    assert captured.out == ""


def test_status_invalid_state_returns_failure(tmp_path, capsys):
    repo = tmp_path / "repo"
    state_path = repo / ".paperium" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")

    assert main(["--repo", str(repo), "status"]) == 2

    captured = capsys.readouterr()
    assert "invalid state" in captured.err
    assert captured.out == ""
