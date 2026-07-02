import json
import re

import paperium.analyze
import paperium.output
import paperium.selection
from paperium.state import ContextRequestState, SectionState
from paperium.cli import main
from paperium.state import PaperiumState, SelectedExperiment, WorkerRecord, load_state, save_state
from paperium.workers import worker_id_for


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
    assert main(["not-a-command"]) == 4
    captured = capsys.readouterr()
    assert "invalid choice" in captured.err
    assert "invalid choice" not in captured.out


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


def test_analyze_marks_artifact_missing_without_worker(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    experiment = repo / "questions/q001/experiments/exp001"
    experiment.mkdir(parents=True)
    (experiment / "README.md").write_text("# Experiment\n", encoding="utf-8")
    save_state(
        repo / ".paperium" / "state.json",
        PaperiumState(
            phase="analyzing",
            selected_experiments=[
                SelectedExperiment(
                    path="questions/q001/experiments/exp001",
                    question_readme=None,
                    analysis_path="questions/q001/experiments/exp001/.paperium/analysis.md",
                    fact_check_result_path=(
                        "questions/q001/experiments/exp001/.paperium/fact-check.json"
                    ),
                    disposition=None,
                )
            ],
        ),
    )

    def fail_run_worker(_repo, _spec):
        raise AssertionError("artifact-missing experiments must not run workers")

    monkeypatch.setattr(paperium.analyze, "run_worker", fail_run_worker)

    assert main(["--repo", str(repo), "analyze"]) == 0

    state = load_state(repo / ".paperium" / "state.json")
    assert state.selected_experiments[0].disposition == "artifact_missing"
    assert state.selected_experiments[0].status == "needs_human_review"
    assert state.workers == []
    assert capsys.readouterr().err == ""


def test_analyze_usable_experiment_with_fake_runner_approves_analysis(
    tmp_path, monkeypatch, capsys
):
    repo = tmp_path / "repo"
    experiment_path = "questions/q001/experiments/exp001"
    experiment = repo / experiment_path
    (experiment / "outputs").mkdir(parents=True)
    (experiment / "outputs" / "metrics.json").write_text('{"accuracy": 1}\n', encoding="utf-8")
    save_state(
        repo / ".paperium" / "state.json",
        PaperiumState(
            phase="analyzing",
            selected_experiments=[
                SelectedExperiment(
                    path=experiment_path,
                    question_readme=None,
                    analysis_path=f"{experiment_path}/.paperium/analysis.md",
                    fact_check_result_path=f"{experiment_path}/.paperium/fact-check.json",
                    disposition=None,
                )
            ],
        ),
    )

    def fake_run_worker(selected_repo, spec):
        assert selected_repo == repo.resolve()
        if spec.role == "analyze":
            analysis_path = selected_repo / spec.writable_paths[0]
            analysis_path.parent.mkdir(parents=True, exist_ok=True)
            analysis_path.write_text("analysis\n", encoding="utf-8")
        elif spec.role == "fact_check":
            result_path = selected_repo / ".paperium" / "workers" / spec.worker_id / "result.json"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(
                json.dumps({"status": "passed", "findings": []}),
                encoding="utf-8",
            )
        return {
            "worker_id": spec.worker_id,
            "status": "succeeded",
            "stdout_path": f".paperium/workers/{spec.worker_id}/stdout.txt",
            "stderr_path": f".paperium/workers/{spec.worker_id}/stderr.txt",
            "output_path": f".paperium/workers/{spec.worker_id}/output.md",
            "result_json_path": f".paperium/workers/{spec.worker_id}/result.json",
            "canonical_result_path": spec.canonical_result_path,
            "started_at": "2026-06-28T00:00:00Z",
            "ended_at": "2026-06-28T00:00:01Z",
            "failure_reason": None,
        }

    monkeypatch.setattr(paperium.analyze, "run_worker", fake_run_worker)

    assert main(["--repo", str(repo), "analyze"]) == 0

    state = load_state(repo / ".paperium" / "state.json")
    selected = state.selected_experiments[0]
    assert selected.status == "approved"
    assert selected.disposition is None
    assert state.phase == "ranking"
    assert [worker.role for worker in state.workers] == ["analyze", "fact_check"]
    assert [worker.id for worker in state.workers] == [
        worker_id_for("analyze", experiment_path),
        worker_id_for("fact_check", experiment_path),
    ]
    assert [worker.status for worker in state.workers] == ["succeeded", "succeeded"]
    assert capsys.readouterr().err == ""


def test_analyze_accepts_jobs_and_renders_progress(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    experiment_path = "questions/q001/experiments/exp001"
    experiment = repo / experiment_path
    (experiment / "outputs").mkdir(parents=True)
    (experiment / "outputs" / "metrics.json").write_text('{"accuracy": 1}\n', encoding="utf-8")
    save_state(
        repo / ".paperium" / "state.json",
        PaperiumState(
            phase="analyzing",
            selected_experiments=[
                SelectedExperiment(
                    path=experiment_path,
                    question_readme=None,
                    analysis_path=f"{experiment_path}/.paperium/analysis.md",
                    fact_check_result_path=f"{experiment_path}/.paperium/fact-check.json",
                    disposition=None,
                )
            ],
        ),
    )

    monkeypatch.setattr(
        paperium.output,
        "render_progress",
        lambda _state, message: print(f"PROGRESS {message}"),
    )
    monkeypatch.setattr(
        paperium.analyze,
        "run_worker",
        lambda _repo, spec: {
            "worker_id": spec.worker_id,
            "status": "failed",
            "failure_reason": "test",
        },
    )

    assert main(["--repo", str(repo), "analyze", "--jobs", "2"]) == 2

    captured = capsys.readouterr()
    assert "PROGRESS" in captured.out
    state = load_state(repo / ".paperium" / "state.json")
    assert state.selected_experiments[0].status == "needs_human_review"
    assert state.selected_experiments[0].disposition == "needs_human_review"


def test_analyze_rejects_invalid_jobs(tmp_path, capsys):
    repo = tmp_path / "repo"
    save_state(repo / ".paperium" / "state.json", PaperiumState())

    assert main(["--repo", str(repo), "analyze", "--jobs", "0"]) == 4
    assert "positive integer" in capsys.readouterr().err

    assert main(["--repo", str(repo), "analyze", "--jobs", "not-int"]) == 4
    assert "positive integer" in capsys.readouterr().err


def test_analyze_rejects_missing_state_or_empty_selection(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()

    assert main(["--repo", str(repo), "analyze"]) == 2
    captured = capsys.readouterr()
    assert "state" in captured.err
    assert "missing" in captured.err

    save_state(repo / ".paperium" / "state.json", PaperiumState())

    assert main(["--repo", str(repo), "analyze"]) == 2
    captured = capsys.readouterr()
    assert "selected experiments" in captured.err


def test_analyze_rejects_unsafe_selected_state_paths(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    save_state(
        repo / ".paperium" / "state.json",
        PaperiumState(
            phase="analyzing",
            selected_experiments=[
                SelectedExperiment(
                    path="../outside",
                    question_readme=None,
                    analysis_path="../outside/.paperium/analysis.md",
                    fact_check_result_path="../outside/.paperium/fact-check.json",
                    disposition=None,
                )
            ],
        ),
    )

    def fail_run_worker(_repo, _spec):
        raise AssertionError("unsafe selected paths must fail before workers run")

    monkeypatch.setattr(paperium.analyze, "run_worker", fail_run_worker)

    assert main(["--repo", str(repo), "analyze"]) == 2

    captured = capsys.readouterr()
    assert "unsafe selected experiment path" in captured.err


def approved_selected_experiment(path="questions/q001/experiments/exp001"):
    return SelectedExperiment(
        path=path,
        question_readme=None,
        analysis_path=f"{path}/.paperium/analysis.md",
        fact_check_result_path=f"{path}/.paperium/fact-check.json",
        disposition=None,
        status="approved",
    )


def _init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert main(["--repo", str(repo), "init"]) == 0
    return repo


def test_section_add_list_and_approve_flow(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    assert main(["--repo", str(repo), "section", "add", "ch1-s1", "--title", "Dataset"]) == 0
    (repo / ".paperium/sections/ch1-s1.md").write_text("## Dataset\nbody\n")
    assert main(["--repo", str(repo), "section", "record", "ch1-s1"]) == 0
    assert main(["--repo", str(repo), "section", "approve", "ch1-s1"]) == 0
    assert main(["--repo", str(repo), "section", "list"]) == 0
    output = capsys.readouterr().out
    assert "ch1-s1" in output
    assert "approved" in output


def test_section_notes_and_prompt(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    assert main(["--repo", str(repo), "section", "add", "ch1-s1", "--title", "Dataset"]) == 0
    (repo / ".paperium/sections/ch1-s1.md").write_text("Text /fix this wording/ more.\n")
    assert main(["--repo", str(repo), "section", "record", "ch1-s1"]) == 0
    assert main(["--repo", str(repo), "section", "notes", "ch1-s1"]) == 0
    assert "fix this wording" in capsys.readouterr().out
    assert main(["--repo", str(repo), "section", "prompt", "ch1-s1"]) == 0
    assert "You are revising one section" in capsys.readouterr().out
    assert (repo / ".paperium/prompts/ch1-s1.round2.prompt.md").exists()


def test_assemble_and_reconcile_commands(tmp_path):
    repo = _init_repo(tmp_path)
    assert main(["--repo", str(repo), "section", "add", "ch1-s1", "--title", "Dataset"]) == 0
    (repo / ".paperium/sections/ch1-s1.md").write_text("## Dataset\nbody\n")
    assert main(["--repo", str(repo), "section", "record", "ch1-s1", "--approve"]) == 0
    assert main(["--repo", str(repo), "assemble"]) == 0
    assert (repo / ".paperium/REPORT.md").exists()
    assert main(["--repo", str(repo), "reconcile"]) == 0
    # unapproved section blocks full assembly, draft mode succeeds
    assert main(["--repo", str(repo), "section", "add", "ch2-s1", "--title", "CPU"]) == 0
    (repo / ".paperium/sections/ch2-s1.md").write_text("## CPU\nbody\n")
    assert main(["--repo", str(repo), "section", "record", "ch2-s1"]) == 0
    assert main(["--repo", str(repo), "assemble"]) == 2
    assert main(["--repo", str(repo), "assemble", "--allow-draft"]) == 0
    assert (repo / ".paperium/REPORT.draft.md").exists()


def test_write_command_is_gone(tmp_path):
    repo = _init_repo(tmp_path)
    assert main(["--repo", str(repo), "write"]) == 4


def test_status_shows_sections(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    assert main(["--repo", str(repo), "section", "add", "ch1-s1", "--title", "Dataset"]) == 0
    assert main(["--repo", str(repo), "status"]) == 0
    output = capsys.readouterr().out
    assert "ch1-s1" in output
    assert "report: not assembled" in output


def test_rank_writes_required_artifacts_from_existing_ranking_json(tmp_path):
    repo = tmp_path / "repo"
    exp = repo / "questions/q001/experiments/exp001"
    exp.mkdir(parents=True)
    assert main(["--repo", str(repo), "init"]) == 0
    state = load_state(repo / ".paperium" / "state.json")
    state.selected_experiments = [approved_selected_experiment()]
    save_state(repo / ".paperium" / "state.json", state)
    (repo / ".paperium" / "ranking.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "experiment_path": "questions/q001/experiments/exp001",
                        "bucket": "include",
                        "reason": "best",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (repo / ".paperium" / "question-focus.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "question_path": "questions/q001",
                        "included_experiments": ["questions/q001/experiments/exp001"],
                        "answer_focus": "Best tested result",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert main(["--repo", str(repo), "rank"]) == 0

    assert (repo / ".paperium" / "ranking.md").exists()
    assert (repo / ".paperium" / "dispositions.md").exists()
    assert (repo / ".paperium" / "question-focus.md").exists()
    ranked = load_state(repo / ".paperium" / "state.json")
    assert ranked.phase == "mapping"


def test_rank_resets_prior_approvals(tmp_path):
    repo = tmp_path / "repo"
    exp = repo / "questions/q001/experiments/exp001"
    exp.mkdir(parents=True)
    assert main(["--repo", str(repo), "init"]) == 0
    state = load_state(repo / ".paperium" / "state.json")
    state.selected_experiments = [approved_selected_experiment()]
    state.ranking.approved = True
    state.question_focus.approved = True
    state.sections = [
        SectionState(
            id="old",
            title="Old",
            path=".paperium/sections/old.md",
            facts_path=".paperium/sections/old.facts.md",
            status="approved",
        )
    ]
    save_state(repo / ".paperium" / "state.json", state)
    (repo / ".paperium" / "ranking.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "experiment_path": "questions/q001/experiments/exp001",
                        "bucket": "include",
                        "reason": "best",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (repo / ".paperium" / "question-focus.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "question_path": "questions/q001",
                        "included_experiments": ["questions/q001/experiments/exp001"],
                        "answer_focus": "Best tested result",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert main(["--repo", str(repo), "rank"]) == 0

    reranked = load_state(repo / ".paperium" / "state.json")
    assert reranked.ranking.approved is False
    assert reranked.question_focus.approved is False


def test_rank_rejects_invalid_ranking_json(tmp_path, capsys):
    repo = tmp_path / "repo"
    exp = repo / "questions/q001/experiments/exp001"
    exp.mkdir(parents=True)
    assert main(["--repo", str(repo), "init"]) == 0
    state = load_state(repo / ".paperium" / "state.json")
    state.selected_experiments = [approved_selected_experiment()]
    save_state(repo / ".paperium" / "state.json", state)
    (repo / ".paperium" / "ranking.json").write_text('{"entries": []}', encoding="utf-8")

    assert main(["--repo", str(repo), "rank"]) == 2

    assert "ranking.json is invalid" in capsys.readouterr().err


def test_approve_question_focus_rejects_malformed_ranking_json(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert main(["--repo", str(repo), "init"]) == 0
    paperium_dir = repo / ".paperium"
    (paperium_dir / "ranking.json").write_text('{"entries": [1]}', encoding="utf-8")
    (paperium_dir / "question-focus.md").write_text("# Focus\n", encoding="utf-8")
    (paperium_dir / "question-focus.json").write_text('{"entries": []}', encoding="utf-8")

    assert main(["--repo", str(repo), "approve", "question-focus"]) == 2

    assert "ranking.json is invalid" in capsys.readouterr().err


def test_rank_generates_missing_ranking_json_with_fake_claude_worker(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    exp = repo / "questions/q001/experiments/exp001"
    exp_analysis = exp / ".paperium" / "analysis.md"
    exp_analysis.parent.mkdir(parents=True)
    exp_analysis.write_text("Approved analysis.", encoding="utf-8")
    assert main(["--repo", str(repo), "init"]) == 0
    state = load_state(repo / ".paperium" / "state.json")
    state.selected_experiments = [approved_selected_experiment()]
    save_state(repo / ".paperium" / "state.json", state)

    def fake_runner(selected_repo, spec):
        assert selected_repo == repo.resolve()
        assert spec.role == "rank"
        worker_dir = selected_repo / ".paperium" / "workers" / spec.worker_id
        worker_dir.mkdir(parents=True, exist_ok=True)
        (worker_dir / "result.json").write_text(
            json.dumps(
                {
                    "entries": [
                        {
                            "experiment_path": "questions/q001/experiments/exp001",
                            "bucket": "include",
                            "reason": "best",
                        }
                    ],
                    "question_focus": [
                        {
                            "question_path": "questions/q001",
                            "included_experiments": ["questions/q001/experiments/exp001"],
                            "answer_focus": "Best tested result",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return {
            "worker_id": spec.worker_id,
            "status": "succeeded",
            "result_json_path": f".paperium/workers/{spec.worker_id}/result.json",
            "failure_reason": None,
        }

    monkeypatch.setattr("paperium.commands.run_worker", fake_runner)

    assert main(["--repo", str(repo), "rank", "--generate"]) == 0

    assert (repo / ".paperium" / "ranking.json").exists()
    assert (repo / ".paperium" / "ranking.md").exists()
    assert (repo / ".paperium" / "question-focus.json").exists()
    assert (repo / ".paperium" / "question-focus.md").exists()


def test_approve_ranking_and_question_focus_commands_set_state_flags(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert main(["--repo", str(repo), "init"]) == 0
    paperium_dir = repo / ".paperium"
    (paperium_dir / "ranking.md").write_text("# Ranking\n", encoding="utf-8")
    (paperium_dir / "ranking.json").write_text('{"entries": []}', encoding="utf-8")
    (paperium_dir / "question-focus.md").write_text("# Focus\n", encoding="utf-8")
    (paperium_dir / "question-focus.json").write_text('{"entries": []}', encoding="utf-8")

    assert main(["--repo", str(repo), "approve", "ranking"]) == 0
    assert main(["--repo", str(repo), "approve", "question-focus"]) == 0

    state = load_state(repo / ".paperium" / "state.json")
    assert state.ranking.approved is True
    assert state.question_focus.approved is True
    assert state.phase == "writing"


def test_approve_question_focus_requires_machine_readable_json(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert main(["--repo", str(repo), "init"]) == 0
    (repo / ".paperium" / "question-focus.md").write_text("# Focus\n", encoding="utf-8")

    assert main(["--repo", str(repo), "approve", "question-focus"]) == 2

    assert "question-focus.json" in capsys.readouterr().err


def test_context_approve_and_deny_commands_record_decision(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert main(["--repo", str(repo), "init"]) == 0
    state = load_state(repo / ".paperium" / "state.json")
    state.context_requests = [
        ContextRequestState(
            id="req1",
            worker_id="w1",
            requested_paths=["questions/q001/src"],
            reason="Need parser",
            decision_path=".paperium/context-requests/req1.decision.json",
        )
    ]
    save_state(repo / ".paperium" / "state.json", state)

    assert main(["--repo", str(repo), "context", "approve", "req1"]) == 0
    approved = load_state(repo / ".paperium" / "state.json")
    assert approved.context_requests[0].status == "approved"
    assert (repo / ".paperium" / "context-requests" / "req1.decision.json").exists()

    approved.context_requests[0].status = "pending"
    save_state(repo / ".paperium" / "state.json", approved)

    assert main(["--repo", str(repo), "context", "deny", "req1"]) == 0
    denied = load_state(repo / ".paperium" / "state.json")
    assert denied.context_requests[0].status == "denied"


def test_context_approve_rejects_unsafe_persisted_requested_path(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert main(["--repo", str(repo), "init"]) == 0
    state_path = repo / ".paperium" / "state.json"
    data = json.loads(state_path.read_text(encoding="utf-8"))
    data["context_requests"] = [
        {
            "id": "req1",
            "worker_id": "w1",
            "requested_paths": ["../outside"],
            "reason": "Need parser",
            "status": "pending",
            "decision_path": ".paperium/context-requests/req1.decision.json",
        }
    ]
    state_path.write_text(json.dumps(data), encoding="utf-8")

    assert main(["--repo", str(repo), "context", "approve", "req1"]) == 2

    assert "requested path" in capsys.readouterr().err


def test_approved_context_decision_is_applied_to_next_analyze_worker(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    exp_path = "questions/q001/experiments/exp001"
    exp = repo / exp_path
    outputs = exp / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "metrics.json").write_text("{}\n", encoding="utf-8")
    assert main(["--repo", str(repo), "init"]) == 0
    assert main(["--repo", str(repo), "select", exp_path]) == 0
    state = load_state(repo / ".paperium" / "state.json")
    state.context_requests = [
        ContextRequestState(
            id="req1",
            worker_id=worker_id_for("analyze", exp_path),
            requested_paths=["questions/q001/src"],
            reason="Need parser",
            decision_path=".paperium/context-requests/req1.decision.json",
            status="approved",
        )
    ]
    save_state(repo / ".paperium" / "state.json", state)

    def fake_runner(_repo, spec):
        if spec.role == "analyze":
            assert "questions/q001/src" in spec.approved_expansions
            assert "questions/q001/src" in spec.prompt
            analysis_path = repo / exp_path / ".paperium" / "analysis.md"
            analysis_path.parent.mkdir(parents=True, exist_ok=True)
            analysis_path.write_text("Analysis.", encoding="utf-8")
        if spec.role == "fact_check":
            worker_dir = repo / ".paperium" / "workers" / spec.worker_id
            worker_dir.mkdir(parents=True, exist_ok=True)
            (worker_dir / "result.json").write_text(
                '{"status": "passed", "findings": []}', encoding="utf-8"
            )
        return {"status": "succeeded", "failure_reason": None}

    monkeypatch.setattr(paperium.analyze, "run_worker", fake_runner)

    assert main(["--repo", str(repo), "analyze"]) == 0


def test_analyze_ingests_context_request_from_worker(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    exp_path = "questions/q001/experiments/exp001"
    exp = repo / exp_path
    outputs = exp / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "metrics.json").write_text("{}\n", encoding="utf-8")
    assert main(["--repo", str(repo), "init"]) == 0
    assert main(["--repo", str(repo), "select", exp_path]) == 0

    def fake_runner(selected_repo, spec):
        assert ".paperium/context-requests" in spec.writable_paths
        request_dir = selected_repo / ".paperium" / "context-requests"
        request_dir.mkdir(parents=True, exist_ok=True)
        (request_dir / "req1.json").write_text(
            json.dumps(
                {
                    "id": "req1",
                    "worker_id": spec.worker_id,
                    "requested_paths": ["questions/q001/src"],
                    "reason": "Need parser",
                }
            ),
            encoding="utf-8",
        )
        return {
            "worker_id": spec.worker_id,
            "status": "needs_context",
            "failure_reason": None,
        }

    monkeypatch.setattr(paperium.analyze, "run_worker", fake_runner)

    assert main(["--repo", str(repo), "analyze"]) == 0

    updated = load_state(repo / ".paperium" / "state.json")
    assert updated.context_requests[0].id == "req1"
    assert updated.context_requests[0].worker_id == worker_id_for("analyze", exp_path)
    assert updated.context_requests[0].status == "pending"


def test_analyze_ignores_stale_malformed_context_request_from_other_worker(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    exp_path = "questions/q001/experiments/exp001"
    exp = repo / exp_path
    outputs = exp / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "metrics.json").write_text("{}\n", encoding="utf-8")
    stale_dir = repo / ".paperium" / "context-requests"
    assert main(["--repo", str(repo), "init"]) == 0
    assert main(["--repo", str(repo), "select", exp_path]) == 0
    stale_dir.mkdir(parents=True, exist_ok=True)
    (stale_dir / "old.json").write_text(
        f"{{not json {worker_id_for('analyze', exp_path)}",
        encoding="utf-8",
    )

    def fake_runner(selected_repo, spec):
        request_dir = selected_repo / ".paperium" / "context-requests"
        request_dir.mkdir(parents=True, exist_ok=True)
        (request_dir / "req1.json").write_text(
            json.dumps(
                {
                    "id": "req1",
                    "worker_id": spec.worker_id,
                    "requested_paths": ["questions/q001/src"],
                    "reason": "Need parser",
                }
            ),
            encoding="utf-8",
        )
        return {
            "worker_id": spec.worker_id,
            "status": "needs_context",
            "failure_reason": None,
        }

    monkeypatch.setattr(paperium.analyze, "run_worker", fake_runner)

    assert main(["--repo", str(repo), "analyze"]) == 0

    updated = load_state(repo / ".paperium" / "state.json")
    assert [request.id for request in updated.context_requests] == ["req1"]


def test_denied_context_decision_leaves_experiment_needing_human_review(tmp_path):
    repo = tmp_path / "repo"
    exp_path = "questions/q001/experiments/exp001"
    exp = repo / exp_path
    outputs = exp / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "metrics.json").write_text("{}\n", encoding="utf-8")
    assert main(["--repo", str(repo), "init"]) == 0
    assert main(["--repo", str(repo), "select", exp_path]) == 0
    state = load_state(repo / ".paperium" / "state.json")
    state.context_requests = [
        ContextRequestState(
            id="req1",
            worker_id=worker_id_for("analyze", exp_path),
            requested_paths=["questions/q001/src"],
            reason="Need parser",
            decision_path=".paperium/context-requests/req1.decision.json",
            status="denied",
        )
    ]
    save_state(repo / ".paperium" / "state.json", state)

    assert main(["--repo", str(repo), "analyze"]) == 0

    updated = load_state(repo / ".paperium" / "state.json")
    assert updated.selected_experiments[0].status == "needs_human_review"
    assert updated.selected_experiments[0].disposition == "needs_human_review"


def test_command_surface_lists_v2_commands(capsys):
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
        "assemble",
        "reconcile",
    ]:
        assert command in output
    assert re.search(r"\bwrite\b", output) is None


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


def test_init_scaffolds_style_and_report_template(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert main(["--repo", str(repo), "init"]) == 0
    style = (repo / ".paperium/style.md").read_text()
    template = (repo / ".paperium/report-template.md").read_text()
    assert "Terminology" in style
    assert "{{sections}}" in template
    # idempotent: user edits survive re-init
    (repo / ".paperium/style.md").write_text("user edited")
    assert main(["--repo", str(repo), "init"]) == 0
    assert (repo / ".paperium/style.md").read_text() == "user edited"
