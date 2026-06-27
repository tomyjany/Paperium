import subprocess
import sys
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from conftest import copy_fixture_repo, read_json, run_paperctl
from paperctl.analysis_batch import BatchAnalyzeItem, BatchAnalyzeResult, BatchStatus


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PAPER_BUILD_SKILL = PROJECT_ROOT / "skills" / "paper-build" / "SKILL.md"
PAPER_BUILD_WORKFLOW = (
    PROJECT_ROOT / "skills" / "paper-build" / "references" / "milestone-1-workflow.md"
)
COMPLETED_EXPERIMENT = "questions/q001-throughput/experiments/exp001-completed"
CONFLICT_EXPERIMENT = "questions/q001-throughput/experiments/exp003-structured-conflict"
ANALYSIS_FIXTURE = PROJECT_ROOT / "tests/fixtures/analysis/exp001-success.json"


def _console_script_command() -> list[str]:
    paperctl = shutil.which("paperctl")
    if paperctl is not None:
        return [paperctl]
    uv = shutil.which("uv")
    if uv is not None:
        return [uv, "run", "--project", str(PROJECT_ROOT), "paperctl"]
    pytest.skip("paperctl console script is not available")


def test_module_entrypoint_shows_help():
    result = subprocess.run(
        [sys.executable, "-m", "paperctl", "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0
    assert "paperctl" in result.stdout


def test_console_script_shows_help():
    result = subprocess.run(
        [*_console_script_command(), "--help"],
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0
    assert "paperctl" in result.stdout


@pytest.mark.parametrize(
    "command",
    ["discover", "inventory", "normalize", "render", "audit", "build", "analyze"],
)
def test_implemented_commands_report_missing_config_instead_of_placeholder(tmp_path, command):
    args = [sys.executable, "-m", "paperctl", "--repo", str(tmp_path), command]
    if command == "analyze":
        args.append(COMPLETED_EXPERIMENT)
    result = subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 2
    assert "missing config file: paper.yaml" in result.stderr
    assert f"command not implemented yet: {command}" not in result.stderr


def test_analyze_fake_backend_writes_accepted_analysis_state(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    for command in ("discover", "inventory", "normalize"):
        prerequisite = run_paperctl(repo, command)
        assert prerequisite.returncode == 0, prerequisite.stderr

    result = run_paperctl(
        repo,
        "analyze",
        COMPLETED_EXPERIMENT,
        "--backend",
        "fake",
        "--fake-response",
        str(ANALYSIS_FIXTURE),
    )

    analysis_path = (
        "paper/work/analyses/questions/q001-throughput/experiments/exp001-completed.json"
    )
    assert result.returncode == 0
    assert f"experiment: {COMPLETED_EXPERIMENT}" in result.stdout
    assert "status: accepted" in result.stdout
    assert f"analysis: {analysis_path}" in result.stdout
    assert "diagnostics: none" in result.stdout
    state = read_json(repo / analysis_path)
    assert state["status"] == "accepted"
    assert state["backend"]["name"] == "fake"


def test_analyze_preflight_failure_exits_2_without_backend_state(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    for command in ("discover", "inventory", "normalize"):
        prerequisite = run_paperctl(repo, command)
        assert prerequisite.returncode == 0, prerequisite.stderr

    result = run_paperctl(
        repo,
        "analyze",
        CONFLICT_EXPERIMENT,
        "--backend",
        "fake",
        "--fake-response",
        str(ANALYSIS_FIXTURE),
    )

    analysis_path = (
        repo / "paper/work/analyses/questions/q001-throughput/experiments/"
        "exp003-structured-conflict.json"
    )
    assert result.returncode == 2
    assert f"experiment: {CONFLICT_EXPERIMENT}" in result.stdout
    assert "status: blocked" in result.stdout
    assert "diagnostics: needs_human_review" in result.stdout
    assert not analysis_path.exists()


def test_analyze_fake_backend_requires_fake_response_before_invocation(tmp_path):
    repo = copy_fixture_repo(tmp_path)

    result = run_paperctl(repo, "analyze", COMPLETED_EXPERIMENT, "--backend", "fake")

    assert result.returncode == 4
    assert "--backend fake requires --fake-response" in result.stderr
    assert not (repo / "paper/work/analyses").exists()


def test_analyze_fake_response_requires_fake_backend(monkeypatch, tmp_path, capsys):
    from paperctl import cli

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("analyze_experiments should not be invoked")

    monkeypatch.setattr(cli, "analyze_experiments", fail_if_called)

    exit_code = cli.main(
        [
            "--repo",
            str(tmp_path),
            "analyze",
            COMPLETED_EXPERIMENT,
            "--fake-response",
            str(ANALYSIS_FIXTURE),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 4
    assert "--fake-response requires --backend fake" in captured.err


def test_analyze_missing_experiment_argument_without_menu_exits_invalid_invocation(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "paperctl", "--repo", str(tmp_path), "analyze"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 4
    assert "the following arguments are required: experiments or --experiments-menu" in result.stderr


def test_analyze_multiple_experiment_args_are_routed_to_batch_runner(
    monkeypatch, tmp_path, capsys
):
    from paperctl import cli

    calls = []

    def fake_analyze_experiments(repo, experiments, **kwargs):
        calls.append((repo, experiments, kwargs))
        return _batch_result(
            [
                _batch_item(COMPLETED_EXPERIMENT, BatchStatus.ACCEPTED),
                _batch_item(CONFLICT_EXPERIMENT, BatchStatus.FAILED, ["needs_human_review"]),
            ],
            exit_success=False,
        )

    monkeypatch.setattr(cli, "analyze_experiments", fake_analyze_experiments)

    exit_code = cli.main(
        [
            "--repo",
            str(tmp_path),
            "analyze",
            COMPLETED_EXPERIMENT,
            CONFLICT_EXPERIMENT,
            "--backend",
            "fake",
            "--fake-response",
            str(ANALYSIS_FIXTURE),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 2
    assert calls[0][1] == [COMPLETED_EXPERIMENT, CONFLICT_EXPERIMENT]
    assert f"experiment: {COMPLETED_EXPERIMENT}" in output
    assert f"experiment: {CONFLICT_EXPERIMENT}" in output
    assert "status: accepted" in output
    assert "status: failed" in output


def test_analyze_options_can_appear_between_experiment_paths(monkeypatch, tmp_path):
    from paperctl import cli

    calls = []

    def fake_analyze_experiments(repo, experiments, **kwargs):
        calls.append((repo, experiments, kwargs))
        return _batch_result(
            [
                _batch_item(COMPLETED_EXPERIMENT, BatchStatus.ACCEPTED),
                _batch_item(CONFLICT_EXPERIMENT, BatchStatus.ACCEPTED),
            ]
        )

    monkeypatch.setattr(cli, "analyze_experiments", fake_analyze_experiments)

    exit_code = cli.main(
        [
            "--repo",
            str(tmp_path),
            "analyze",
            COMPLETED_EXPERIMENT,
            "--jobs",
            "3",
            CONFLICT_EXPERIMENT,
            "--plain",
        ]
    )

    assert exit_code == 0
    assert calls[0][1] == [COMPLETED_EXPERIMENT, CONFLICT_EXPERIMENT]
    assert calls[0][2]["jobs"] == 3


def test_analyze_experiments_menu_is_mutually_exclusive_with_explicit_paths(
    monkeypatch, tmp_path, capsys
):
    from paperctl import cli

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("analyze_experiments should not be invoked")

    monkeypatch.setattr(cli, "analyze_experiments", fail_if_called)

    exit_code = cli.main(
        [
            "--repo",
            str(tmp_path),
            "analyze",
            COMPLETED_EXPERIMENT,
            "--experiments-menu",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 4
    assert "--experiments-menu cannot be used with explicit experiments" in captured.err


def test_analyze_experiments_menu_refuses_non_tty_before_config_load(
    monkeypatch, tmp_path, capsys
):
    from paperctl import cli

    def fail_load_config(_repo):
        raise AssertionError("load_config should not be called for non-TTY menu")

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(cli, "load_config", fail_load_config)

    exit_code = cli.main(["--repo", str(tmp_path), "analyze", "--experiments-menu"])

    captured = capsys.readouterr()
    assert exit_code == 4
    assert "--experiments-menu requires an interactive terminal" in captured.err


def test_analyze_experiments_menu_selected_paths_are_passed_to_batch_runner(
    monkeypatch, tmp_path
):
    from paperctl import cli

    calls = []
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(cli, "load_config", lambda repo: {"loaded": True})
    monkeypatch.setattr(
        cli,
        "choose_experiments_interactively",
        lambda repo, config: [COMPLETED_EXPERIMENT, CONFLICT_EXPERIMENT],
    )

    def fake_analyze_experiments(repo, experiments, **kwargs):
        calls.append((repo, experiments, kwargs))
        return _batch_result(
            [
                _batch_item(COMPLETED_EXPERIMENT, BatchStatus.ACCEPTED),
                _batch_item(CONFLICT_EXPERIMENT, BatchStatus.BLOCKED, ["needs_human_review"]),
            ],
            exit_success=False,
        )

    monkeypatch.setattr(cli, "analyze_experiments", fake_analyze_experiments)

    exit_code = cli.main(
        [
            "--repo",
            str(tmp_path),
            "analyze",
            "--experiments-menu",
            "--backend",
            "fake",
            "--fake-response",
            str(ANALYSIS_FIXTURE),
            "--jobs",
            "3",
            "--plain",
        ]
    )

    assert exit_code == 2
    assert calls[0][1] == [COMPLETED_EXPERIMENT, CONFLICT_EXPERIMENT]
    assert calls[0][2]["jobs"] == 3


def test_analyze_experiments_menu_rejects_empty_selection(monkeypatch, tmp_path, capsys):
    from paperctl import cli

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("analyze_experiments should not be invoked")

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(cli, "load_config", lambda repo: {"loaded": True})
    monkeypatch.setattr(cli, "choose_experiments_interactively", lambda repo, config: [])
    monkeypatch.setattr(cli, "analyze_experiments", fail_if_called)

    exit_code = cli.main(["--repo", str(tmp_path), "analyze", "--experiments-menu"])

    captured = capsys.readouterr()
    assert exit_code == 4
    assert "no experiments selected" in captured.err


def test_analyze_experiments_menu_reports_inventory_errors(monkeypatch, tmp_path, capsys):
    from paperctl import cli
    from paperctl.inventory import InventoryError

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(cli, "load_config", lambda repo: {"loaded": True})

    def raise_inventory_error(_repo, _config):
        raise InventoryError("missing discovery manifest: paper/work/manifest.json")

    monkeypatch.setattr(cli, "choose_experiments_interactively", raise_inventory_error)

    exit_code = cli.main(["--repo", str(tmp_path), "analyze", "--experiments-menu"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "missing discovery manifest: paper/work/manifest.json" in captured.err


@pytest.mark.parametrize("jobs", ["0", "-1"])
def test_analyze_jobs_must_be_positive(monkeypatch, tmp_path, capsys, jobs):
    from paperctl import cli

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("analyze_experiments should not be invoked")

    monkeypatch.setattr(cli, "analyze_experiments", fail_if_called)

    exit_code = cli.main(
        ["--repo", str(tmp_path), "analyze", COMPLETED_EXPERIMENT, "--jobs", jobs]
    )

    captured = capsys.readouterr()
    assert exit_code == 4
    assert "--jobs must be a positive integer" in captured.err


def test_analyze_cli_options_are_passed_to_batch_runner(monkeypatch, tmp_path):
    from paperctl import cli
    from paperctl.analysis_backends import FakeBackend

    calls = []

    def fake_analyze_experiments(repo, experiments, **kwargs):
        calls.append((repo, experiments, kwargs))
        return _batch_result([_batch_item(COMPLETED_EXPERIMENT, BatchStatus.ACCEPTED)])

    monkeypatch.setattr(cli, "analyze_experiments", fake_analyze_experiments)

    exit_code = cli.main(
        [
            "--repo",
            str(tmp_path),
            "analyze",
            COMPLETED_EXPERIMENT,
            "--backend",
            "fake",
            "--fake-response",
            str(ANALYSIS_FIXTURE),
            "--timeout-seconds",
            "17",
            "--jobs",
            "3",
            "--force",
            "--plain",
        ]
    )

    assert exit_code == 0
    repo, experiments, kwargs = calls[0]
    assert repo == tmp_path
    assert experiments == [COMPLETED_EXPERIMENT]
    assert isinstance(kwargs["backend"], FakeBackend)
    assert kwargs["backend_options_override"] == {
        "fake_response_path": str(ANALYSIS_FIXTURE)
    }
    assert kwargs["timeout_seconds_override"] == 17
    assert kwargs["jobs"] == 3
    assert kwargs["force"] is True
    assert kwargs["on_update"] is None


def test_analyze_plain_output_includes_item_and_total_tokens(monkeypatch, tmp_path, capsys):
    from paperctl import cli

    item_tokens = {
        "input_tokens": 11,
        "cached_input_tokens": 3,
        "output_tokens": 7,
        "reasoning_output_tokens": 2,
        "total_tokens": 18,
    }
    total_tokens = {
        "input_tokens": 22,
        "cached_input_tokens": 6,
        "output_tokens": 14,
        "reasoning_output_tokens": 4,
        "total_tokens": 36,
    }

    def fake_analyze_experiments(_repo, _experiments, **_kwargs):
        return _batch_result(
            [
                _batch_item(
                    COMPLETED_EXPERIMENT,
                    BatchStatus.ACCEPTED,
                    token_usage=item_tokens,
                )
            ],
            token_totals=total_tokens,
        )

    monkeypatch.setattr(cli, "analyze_experiments", fake_analyze_experiments)

    exit_code = cli.main(
        ["--repo", str(tmp_path), "analyze", COMPLETED_EXPERIMENT, "--plain"]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "tokens: input_tokens=11" in output
    assert "cached_input_tokens=3" in output
    assert "token totals: input_tokens=22" in output
    assert "total_tokens=36" in output
    assert "counts: selected=1 skipped=0 accepted=1 failed=0 blocked=0 not_started=0" in output


def test_analyze_rich_output_can_be_forced_for_interactive_stdout(
    monkeypatch, tmp_path, capsys
):
    from paperctl import cli

    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(
        cli,
        "analyze_experiments",
        lambda _repo, _experiments, **_kwargs: _batch_result(
            [_batch_item(COMPLETED_EXPERIMENT, BatchStatus.ACCEPTED)]
        ),
    )

    exit_code = cli.main(["--repo", str(tmp_path), "analyze", COMPLETED_EXPERIMENT])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "paperctl analyze" in output
    assert "Batch Analysis" in output
    assert COMPLETED_EXPERIMENT in output
    assert "accepted" in output


def test_analyze_rich_progress_callback_is_passed_for_interactive_stdout(
    monkeypatch, tmp_path, capsys
):
    from paperctl import cli

    callbacks = []
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    def fake_analyze_experiments(_repo, _experiments, **kwargs):
        callbacks.append(kwargs["on_update"])
        kwargs["on_update"](_batch_item(COMPLETED_EXPERIMENT, BatchStatus.RUNNING))
        return _batch_result([_batch_item(COMPLETED_EXPERIMENT, BatchStatus.ACCEPTED)])

    monkeypatch.setattr(cli, "analyze_experiments", fake_analyze_experiments)

    exit_code = cli.main(["--repo", str(tmp_path), "analyze", COMPLETED_EXPERIMENT])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert callbacks and callable(callbacks[0])
    assert "running" in output
    assert COMPLETED_EXPERIMENT in output


def test_analyze_invalid_backend_choice_exits_invalid_invocation(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "paperctl",
            "--repo",
            str(tmp_path),
            "analyze",
            COMPLETED_EXPERIMENT,
            "--backend",
            "bad",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 4
    assert "invalid choice: 'bad'" in result.stderr


def test_build_uses_plain_output_when_stdout_is_captured(tmp_path):
    from paperctl import cli

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "paperctl",
            "--repo",
            str(tmp_path),
            "build",
            "--plain",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 2
    assert "missing config file: paper.yaml" in result.stderr
    assert cli.PUBLICATION_BLOCKED == 3


def test_build_rich_output_can_be_forced_for_interactive_stdout(monkeypatch, tmp_path, capsys):
    from paperctl import cli

    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(cli, "load_config", lambda repo: {"ok": True})
    monkeypatch.setattr(cli, "build", lambda repo, config, force=False: _build_result())

    exit_code = cli.main(["--repo", str(tmp_path), "build"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "paperctl build" in output
    assert "Deterministic Build" in output
    assert "PAPER.draft.md" in output
    assert "missing_semantic_analysis" in output


def test_audit_rich_output_preserves_publication_blocked_exit(monkeypatch, tmp_path, capsys):
    from paperctl import cli

    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(
        cli, "load_config", lambda repo: {"audit": {"default_stage": "publication"}}
    )
    monkeypatch.setattr(cli, "audit", lambda repo, config, stage, force=False: _audit_result(stage))

    exit_code = cli.main(["--repo", str(tmp_path), "audit", "--stage", "publication"])

    assert exit_code == cli.PUBLICATION_BLOCKED
    output = capsys.readouterr().out
    assert "paperctl audit" in output
    assert "Publication Gate" in output
    assert "blocked" in output
    assert "paper/PAPER.audit.json" in output


def _build_result():
    return SimpleNamespace(
        discovery=SimpleNamespace(status="created"),
        inventory=SimpleNamespace(created=1, replaced=0, unchanged=5),
        normalize=SimpleNamespace(created=1, replaced=0, unchanged=5),
        render=SimpleNamespace(status="wrote"),
        deterministic_status="passed",
        publication_status="blocked",
        publication_blocker_codes=["missing_semantic_analysis"],
        draft_path="PAPER.draft.md",
        audit_path="paper/PAPER.audit.json",
    )


def _audit_result(stage: str):
    return SimpleNamespace(
        stage=stage,
        write_status="wrote",
        report_path="paper/PAPER.audit.json",
        deterministic_status="passed",
        publication_status="blocked",
        publishable=False,
        blocker_count=1,
        issue_codes=[],
    )


def _batch_item(
    experiment_path: str,
    status: BatchStatus,
    diagnostic_codes: list[str] | None = None,
    token_usage: dict[str, int] | None = None,
) -> BatchAnalyzeItem:
    return BatchAnalyzeItem(
        experiment_path=experiment_path,
        status=status,
        analysis_path=f"paper/work/analyses/{experiment_path}.json",
        diagnostic_codes=diagnostic_codes or [],
        token_usage=token_usage,
    )


def _batch_result(
    items: list[BatchAnalyzeItem],
    *,
    token_totals: dict[str, int] | None = None,
    exit_success: bool = True,
) -> BatchAnalyzeResult:
    counts = {
        "selected": len(items),
        "skipped": 0,
        "accepted": 0,
        "failed": 0,
        "blocked": 0,
        "not_started": 0,
    }
    for item in items:
        if item.status.value in counts:
            counts[item.status.value] += 1
    return BatchAnalyzeResult(
        items=items,
        counts=counts,
        token_totals=token_totals
        or {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_output_tokens": 0,
            "total_tokens": 0,
        },
        exit_success=exit_success,
    )


def test_paper_build_skill_file_has_required_frontmatter():
    text = PAPER_BUILD_SKILL.read_text(encoding="utf-8")

    assert text.startswith("---\n")
    assert "\nname: paper-build\n" in text
    assert "\ndescription: " in text


def test_paper_build_skill_is_explicit_paperctl_wrapper():
    text = PAPER_BUILD_SKILL.read_text(encoding="utf-8")
    lower_text = text.lower()

    assert "use only when explicitly requested" in lower_text
    assert "installed `paperctl` executable" in lower_text
    assert "`paperctl --repo <repository-root> build`" in text
    assert "deterministic pre-analysis evidence draft" in lower_text
    assert "confirm `paper.yaml` exists" in lower_text
    assert "do not manually alter generated artifacts" in lower_text
    assert "milestone 1 never writes `paper.md`" in lower_text


def test_paper_build_skill_avoids_future_analysis_language():
    text = PAPER_BUILD_SKILL.read_text(encoding="utf-8")
    lower_text = text.lower()

    assert "llm" not in lower_text
    assert "subagent" not in lower_text
    assert "promote" not in lower_text
    assert "promotion" not in lower_text


def test_paper_build_workflow_reference_exists_and_is_concise():
    text = PAPER_BUILD_WORKFLOW.read_text(encoding="utf-8")

    assert "paperctl --repo <repository-root> build" in text
    assert "PAPER.draft.md" in text
    assert len(text.splitlines()) <= 80
