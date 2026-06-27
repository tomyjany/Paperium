from __future__ import annotations

import json
import subprocess
import sys
import threading
from concurrent.futures import wait as real_futures_wait
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from conftest import copy_fixture_repo
from paperctl.analysis import AnalyzeResult, analyze_experiment
from paperctl.analysis_backends import AnalysisBackendResult
from paperctl.analysis_batch import BatchStatus, analyze_experiments


COMPLETED_EXPERIMENT = "questions/q001-throughput/experiments/exp001-completed"
INCOMPLETE_EXPERIMENT = "questions/q001-throughput/experiments/exp002-incomplete"
CONFLICT_EXPERIMENT = "questions/q001-throughput/experiments/exp003-structured-conflict"
SMOKE_EXPERIMENT = "questions/q001-throughput/experiments/exp004-smoke-and-full"
LEGACY_EXPERIMENT = "questions/q001-throughput/experiments/legacy-baseline"
MISSING_EXPERIMENT = "questions/q001-throughput/experiments/missing"


class NamedBackend:
    name = "fake"

    def __init__(self, result: AnalysisBackendResult | None = None) -> None:
        self.result = result
        self.calls = 0

    def analyze(self, _job: Any) -> AnalysisBackendResult:
        self.calls += 1
        if self.result is None:
            raise AssertionError("backend should not have been called")
        return self.result


def _run_analysis_prerequisites(repo: Path) -> None:
    for command in ("discover", "inventory", "normalize"):
        result = subprocess.run(
            [sys.executable, "-m", "paperctl", "--repo", str(repo), command],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def _analysis_path(repo: Path, experiment: str) -> Path:
    return repo / "paper/work/analyses" / f"{experiment}.json"


def _analysis_fixture_bytes() -> bytes:
    return Path("tests/fixtures/analysis/exp001-success.json").read_bytes()


def _accepted_backend_result(*, token_usage: dict[str, int] | None = None) -> AnalysisBackendResult:
    return AnalysisBackendResult(
        backend_name="fake",
        status="completed",
        raw_response=_analysis_fixture_bytes(),
        return_code=0,
        stdout=None,
        stderr=None,
        token_usage=token_usage,
    )


def _write_analysis_state(repo: Path, experiment: str, token_usage: dict[str, int]) -> str:
    path = _analysis_path(repo, experiment)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"backend": {"token_usage": token_usage}}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path.relative_to(repo).as_posix()


def test_batch_model_statuses_and_counts_are_explicit(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    _run_analysis_prerequisites(repo)
    updates = []

    def analyze_one(*, repo: Path, experiment: str, **_kwargs: Any) -> AnalyzeResult:
        return AnalyzeResult(
            experiment_path=experiment,
            analysis_path=f"paper/work/analyses/{experiment}.json",
            status="accepted",
            diagnostic_codes=[],
        )

    result = analyze_experiments(
        repo,
        [COMPLETED_EXPERIMENT],
        jobs=1,
        analyze_one=analyze_one,
        on_update=updates.append,
    )

    assert result.exit_success is True
    assert BatchStatus.ACCEPTED.value == "accepted"
    assert result.counts == {
        "selected": 1,
        "skipped": 0,
        "accepted": 1,
        "failed": 0,
        "blocked": 0,
        "not_started": 0,
    }
    assert result.items == [
        replace(
            result.items[0],
            status=BatchStatus.ACCEPTED,
            analysis_path=f"paper/work/analyses/{COMPLETED_EXPERIMENT}.json",
            diagnostic_codes=[],
        )
    ]
    assert [update.status for update in updates] == [
        BatchStatus.QUEUED,
        BatchStatus.RUNNING,
        BatchStatus.ACCEPTED,
    ]


@pytest.mark.parametrize("jobs", [0, -1])
def test_jobs_must_be_positive(tmp_path, jobs):
    repo = copy_fixture_repo(tmp_path)

    with pytest.raises(ValueError, match="jobs must be positive"):
        analyze_experiments(repo, [COMPLETED_EXPERIMENT], jobs=jobs)


def test_explicit_selection_validation_blocks_all_backend_invocation(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    _run_analysis_prerequisites(repo)
    calls = []
    updates = []

    def analyze_one(**_kwargs: Any) -> AnalyzeResult:
        calls.append(_kwargs)
        raise AssertionError("analyze_one should not be invoked when validation fails")

    result = analyze_experiments(
        repo,
        [
            COMPLETED_EXPERIMENT,
            "/absolute/experiment",
            "../parent",
            MISSING_EXPERIMENT,
            CONFLICT_EXPERIMENT,
        ],
        jobs=2,
        analyze_one=analyze_one,
        on_update=updates.append,
    )

    assert result.exit_success is False
    assert calls == []
    assert [(item.experiment_path, item.status, item.diagnostic_codes) for item in result.items] == [
        (COMPLETED_EXPERIMENT, BatchStatus.NOT_STARTED, []),
        ("/absolute/experiment", BatchStatus.BLOCKED, ["invalid_experiment_path"]),
        ("../parent", BatchStatus.BLOCKED, ["invalid_experiment_path"]),
        (MISSING_EXPERIMENT, BatchStatus.BLOCKED, ["experiment_not_found"]),
        (CONFLICT_EXPERIMENT, BatchStatus.BLOCKED, ["needs_human_review"]),
    ]
    assert result.counts == {
        "selected": 5,
        "skipped": 0,
        "accepted": 0,
        "failed": 0,
        "blocked": 4,
        "not_started": 1,
    }
    assert [update.status for update in updates[:5]] == [BatchStatus.QUEUED] * 5
    assert [update.status for update in updates[5:]] == [
        BatchStatus.NOT_STARTED,
        BatchStatus.BLOCKED,
        BatchStatus.BLOCKED,
        BatchStatus.BLOCKED,
        BatchStatus.BLOCKED,
    ]


def test_fresh_accepted_analysis_is_skipped_by_default_and_force_reruns(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    _run_analysis_prerequisites(repo)
    backend = NamedBackend(_accepted_backend_result())
    accepted = analyze_experiment(repo, COMPLETED_EXPERIMENT, backend=backend)
    assert accepted.status == "accepted"

    def analyze_one(**_kwargs: Any) -> AnalyzeResult:
        raise AssertionError("fresh accepted analysis should be skipped")

    skipped = analyze_experiments(
        repo,
        [COMPLETED_EXPERIMENT],
        backend=NamedBackend(),
        jobs=1,
        analyze_one=analyze_one,
    )

    assert skipped.items[0].status is BatchStatus.SKIPPED
    assert skipped.items[0].analysis_path == accepted.analysis_path
    assert skipped.counts == {
        "selected": 1,
        "skipped": 1,
        "accepted": 0,
        "failed": 0,
        "blocked": 0,
        "not_started": 0,
    }

    calls = []

    def forced_analyze_one(*, repo: Path, experiment: str, **_kwargs: Any) -> AnalyzeResult:
        calls.append(experiment)
        return AnalyzeResult(
            experiment_path=experiment,
            analysis_path=accepted.analysis_path,
            status="accepted",
            diagnostic_codes=[],
        )

    forced = analyze_experiments(
        repo,
        [COMPLETED_EXPERIMENT],
        backend=NamedBackend(),
        jobs=1,
        force=True,
        analyze_one=forced_analyze_one,
    )

    assert calls == [COMPLETED_EXPERIMENT]
    assert forced.items[0].status is BatchStatus.ACCEPTED
    assert forced.counts["accepted"] == 1
    assert forced.counts["skipped"] == 0


def test_failed_incomplete_missing_invalid_and_stale_analysis_are_rerun(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    _run_analysis_prerequisites(repo)
    _write_analysis_state(
        repo,
        COMPLETED_EXPERIMENT,
        {
            "input_tokens": 999,
            "cached_input_tokens": 0,
            "output_tokens": 999,
            "reasoning_output_tokens": 0,
            "total_tokens": 1998,
        },
    )
    calls = []

    def analyze_one(*, repo: Path, experiment: str, **_kwargs: Any) -> AnalyzeResult:
        calls.append(experiment)
        return AnalyzeResult(
            experiment_path=experiment,
            analysis_path=f"paper/work/analyses/{experiment}.json",
            status="accepted",
            diagnostic_codes=[],
        )

    result = analyze_experiments(
        repo,
        [COMPLETED_EXPERIMENT, INCOMPLETE_EXPERIMENT],
        backend=NamedBackend(),
        jobs=1,
        analyze_one=analyze_one,
    )

    assert calls == [COMPLETED_EXPERIMENT, INCOMPLETE_EXPERIMENT]
    assert [item.status for item in result.items] == [
        BatchStatus.ACCEPTED,
        BatchStatus.ACCEPTED,
    ]


def test_fail_fast_preserves_running_results_and_marks_unsubmitted_not_started(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    _run_analysis_prerequisites(repo)
    calls = []
    second_started = threading.Event()
    failure_returned = threading.Event()

    def analyze_one(*, repo: Path, experiment: str, **_kwargs: Any) -> AnalyzeResult:
        calls.append(experiment)
        if experiment == COMPLETED_EXPERIMENT:
            failure_returned.set()
            return AnalyzeResult(
                experiment_path=experiment,
                analysis_path=f"paper/work/analyses/{experiment}.json",
                status="failed",
                diagnostic_codes=["schema_failure"],
            )
        if experiment == INCOMPLETE_EXPERIMENT:
            second_started.set()
            assert failure_returned.wait(timeout=3)
            return AnalyzeResult(
                experiment_path=experiment,
                analysis_path=f"paper/work/analyses/{experiment}.json",
                status="accepted",
                diagnostic_codes=[],
            )
        raise AssertionError(f"unexpected launch after fail-fast: {experiment}")

    result = analyze_experiments(
        repo,
        [COMPLETED_EXPERIMENT, INCOMPLETE_EXPERIMENT, SMOKE_EXPERIMENT, LEGACY_EXPERIMENT],
        backend=NamedBackend(),
        jobs=2,
        analyze_one=analyze_one,
    )

    assert second_started.is_set()
    assert set(calls) == {COMPLETED_EXPERIMENT, INCOMPLETE_EXPERIMENT}
    assert [item.status for item in result.items] == [
        BatchStatus.FAILED,
        BatchStatus.ACCEPTED,
        BatchStatus.NOT_STARTED,
        BatchStatus.NOT_STARTED,
    ]
    assert result.counts == {
        "selected": 4,
        "skipped": 0,
        "accepted": 1,
        "failed": 1,
        "blocked": 0,
        "not_started": 2,
    }
    assert result.exit_success is False


def test_fail_fast_drains_already_done_futures_before_launching_more_work(
    tmp_path, monkeypatch
):
    repo = copy_fixture_repo(tmp_path)
    _run_analysis_prerequisites(repo)
    calls = []

    def selective_wait(futures, return_when):  # noqa: ANN001
        real_futures_wait(futures)
        done = {future for future in futures if future.done()}
        accepted = {
            future
            for future in done
            if future.result()[0].experiment_path == INCOMPLETE_EXPERIMENT
        }
        if accepted:
            selected = {next(iter(accepted))}
            return selected, set(futures) - selected
        return done, set(futures) - done

    monkeypatch.setattr("paperctl.analysis_batch.wait", selective_wait)

    def analyze_one(*, repo: Path, experiment: str, **_kwargs: Any) -> AnalyzeResult:
        calls.append(experiment)
        if experiment == COMPLETED_EXPERIMENT:
            return AnalyzeResult(
                experiment_path=experiment,
                analysis_path=f"paper/work/analyses/{experiment}.json",
                status="failed",
                diagnostic_codes=["schema_failure"],
            )
        if experiment == INCOMPLETE_EXPERIMENT:
            return AnalyzeResult(
                experiment_path=experiment,
                analysis_path=f"paper/work/analyses/{experiment}.json",
                status="accepted",
                diagnostic_codes=[],
            )
        raise AssertionError(f"unexpected launch after fail-fast: {experiment}")

    result = analyze_experiments(
        repo,
        [COMPLETED_EXPERIMENT, INCOMPLETE_EXPERIMENT, SMOKE_EXPERIMENT],
        backend=NamedBackend(),
        jobs=2,
        analyze_one=analyze_one,
    )

    assert set(calls) == {COMPLETED_EXPERIMENT, INCOMPLETE_EXPERIMENT}
    assert [item.status for item in result.items] == [
        BatchStatus.FAILED,
        BatchStatus.ACCEPTED,
        BatchStatus.NOT_STARTED,
    ]


def test_token_totals_only_include_analysis_files_written_by_this_batch(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    _run_analysis_prerequisites(repo)
    stale_tokens = {
        "input_tokens": 999,
        "cached_input_tokens": 0,
        "output_tokens": 999,
        "reasoning_output_tokens": 0,
        "total_tokens": 1998,
    }
    written_tokens = {
        "input_tokens": 11,
        "cached_input_tokens": 3,
        "output_tokens": 7,
        "reasoning_output_tokens": 2,
        "total_tokens": 18,
    }
    stale_path = _write_analysis_state(repo, COMPLETED_EXPERIMENT, stale_tokens)

    def analyze_one(*, repo: Path, experiment: str, **_kwargs: Any) -> AnalyzeResult:
        if experiment == COMPLETED_EXPERIMENT:
            return AnalyzeResult(
                experiment_path=experiment,
                analysis_path=stale_path,
                status="accepted",
                diagnostic_codes=[],
            )
        written_path = _write_analysis_state(repo, INCOMPLETE_EXPERIMENT, written_tokens)
        return AnalyzeResult(
            experiment_path=experiment,
            analysis_path=written_path,
            status="accepted",
            diagnostic_codes=[],
        )

    result = analyze_experiments(
        repo,
        [COMPLETED_EXPERIMENT, INCOMPLETE_EXPERIMENT],
        backend=NamedBackend(),
        jobs=1,
        analyze_one=analyze_one,
    )

    assert result.items[0].token_usage is None
    assert result.items[1].token_usage == written_tokens
    assert result.token_totals == written_tokens
    assert result.counts["accepted"] == 2
    assert not list((repo / "paper/work").glob("*batch*"))


def test_default_backend_path_calls_existing_single_experiment_analysis(tmp_path, monkeypatch):
    repo = copy_fixture_repo(tmp_path)
    _run_analysis_prerequisites(repo)
    calls = []

    def fake_analyze_experiment(
        repo: Path,
        experiment: str,
        *,
        backend: object | None,
        backend_options_override: dict[str, Any] | None,
        timeout_seconds_override: int | None,
    ) -> AnalyzeResult:
        calls.append(
            (
                repo,
                experiment,
                backend,
                backend_options_override,
                timeout_seconds_override,
            )
        )
        return AnalyzeResult(
            experiment_path=experiment,
            analysis_path=f"paper/work/analyses/{experiment}.json",
            status="accepted",
            diagnostic_codes=[],
        )

    monkeypatch.setattr("paperctl.analysis_batch.analyze_experiment", fake_analyze_experiment)
    backend = NamedBackend()

    result = analyze_experiments(
        repo,
        [COMPLETED_EXPERIMENT],
        backend=backend,
        backend_options_override={"trace": "yes"},
        timeout_seconds_override=17,
        jobs=1,
    )

    assert result.items[0].status is BatchStatus.ACCEPTED
    assert calls == [(repo, COMPLETED_EXPERIMENT, backend, {"trace": "yes"}, 17)]
