from __future__ import annotations

import json
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from paperctl._support.paths import is_repo_relative_posix
from paperctl.analysis import (
    AnalyzeResult,
    accepted_analysis_is_fresh,
    analyze_experiment,
    preflight_experiment,
)


class BatchStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SKIPPED = "skipped"
    ACCEPTED = "accepted"
    FAILED = "failed"
    BLOCKED = "blocked"
    NOT_STARTED = "not_started"


@dataclass(frozen=True)
class BatchAnalyzeItem:
    experiment_path: str
    status: BatchStatus
    analysis_path: str | None = None
    diagnostic_codes: list[str] = field(default_factory=list)
    token_usage: dict[str, int] | None = None


@dataclass(frozen=True)
class BatchAnalyzeResult:
    items: list[BatchAnalyzeItem]
    counts: dict[str, int]
    token_totals: dict[str, int]
    exit_success: bool


class AnalyzeOne(Protocol):
    def __call__(
        self,
        *,
        repo: Path,
        experiment: str,
        backend: object | None,
        backend_options_override: dict[str, Any] | None,
        timeout_seconds_override: int | None,
    ) -> AnalyzeResult:
        ...


class ProgressCallback(Protocol):
    def __call__(self, item: BatchAnalyzeItem) -> None:
        ...


_TOKEN_KEYS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


def analyze_experiments(
    repo: Path,
    experiments: list[str],
    *,
    backend: object | None = None,
    backend_options_override: dict[str, Any] | None = None,
    timeout_seconds_override: int | None = None,
    jobs: int = 2,
    force: bool = False,
    analyze_one: AnalyzeOne | None = None,
    on_update: ProgressCallback | None = None,
) -> BatchAnalyzeResult:
    if jobs <= 0:
        raise ValueError("jobs must be positive")

    repo = Path(repo)
    runner = analyze_one if analyze_one is not None else _analyze_one
    items = [
        BatchAnalyzeItem(experiment_path=experiment, status=BatchStatus.QUEUED)
        for experiment in experiments
    ]
    for item in items:
        _emit(on_update, item)

    validation_failed = False
    for index, item in enumerate(items):
        diagnostic_codes, analysis_path = _selection_validation(repo, item.experiment_path)
        if diagnostic_codes:
            validation_failed = True
            items[index] = replace(
                item,
                status=BatchStatus.BLOCKED,
                diagnostic_codes=diagnostic_codes,
            )
        else:
            items[index] = replace(item, analysis_path=analysis_path)

    if validation_failed:
        for index, item in enumerate(items):
            if item.status is BatchStatus.QUEUED:
                items[index] = replace(item, status=BatchStatus.NOT_STARTED)
            _emit(on_update, items[index])
        return _batch_result(items)

    runnable_indexes = []
    backend_name = _backend_name(backend)
    for index, item in enumerate(items):
        if not force:
            freshness = accepted_analysis_is_fresh(
                repo,
                item.experiment_path,
                backend_name=backend_name,
                backend_options_override=backend_options_override,
                timeout_seconds_override=timeout_seconds_override,
            )
            if freshness.fresh:
                items[index] = replace(
                    item,
                    status=BatchStatus.SKIPPED,
                    analysis_path=freshness.analysis_path,
                    diagnostic_codes=[],
                )
                _emit(on_update, items[index])
                continue
        runnable_indexes.append(index)

    token_totals = _zero_token_totals()
    if runnable_indexes:
        written_token_usage = _run_backend_items(
            repo=repo,
            items=items,
            runnable_indexes=runnable_indexes,
            runner=runner,
            backend=backend,
            backend_options_override=backend_options_override,
            timeout_seconds_override=timeout_seconds_override,
            jobs=jobs,
            on_update=on_update,
        )
        for token_usage in written_token_usage:
            _add_token_usage(token_totals, token_usage)

    result = _batch_result(items)
    return BatchAnalyzeResult(
        items=result.items,
        counts=result.counts,
        token_totals=token_totals,
        exit_success=result.exit_success,
    )


def _analyze_one(
    *,
    repo: Path,
    experiment: str,
    backend: object | None,
    backend_options_override: dict[str, Any] | None,
    timeout_seconds_override: int | None,
) -> AnalyzeResult:
    return analyze_experiment(
        repo,
        experiment,
        backend=backend,
        backend_options_override=backend_options_override,
        timeout_seconds_override=timeout_seconds_override,
    )


def _selection_validation(repo: Path, experiment: str) -> tuple[list[str], str | None]:
    if not is_repo_relative_posix(experiment):
        return ["invalid_experiment_path"], None
    preflight = preflight_experiment(repo, experiment)
    if not preflight.runnable:
        return preflight.diagnostic_codes or ["experiment_not_found"], None
    return [], preflight.analysis_path


def _run_backend_items(
    *,
    repo: Path,
    items: list[BatchAnalyzeItem],
    runnable_indexes: list[int],
    runner: AnalyzeOne,
    backend: object | None,
    backend_options_override: dict[str, Any] | None,
    timeout_seconds_override: int | None,
    jobs: int,
    on_update: ProgressCallback | None,
) -> list[dict[str, int]]:
    written_token_usage: list[dict[str, int]] = []
    submitted = 0
    stop_launching = False
    futures: dict[Future[tuple[AnalyzeResult, _FileSnapshot | None]], int] = {}

    def submit(index: int, executor: ThreadPoolExecutor) -> None:
        nonlocal submitted
        item = replace(items[index], status=BatchStatus.RUNNING)
        items[index] = item
        _emit(on_update, item)
        expected_analysis_path = item.analysis_path
        snapshot = _analysis_snapshot(repo, expected_analysis_path)
        future = executor.submit(
            _run_one,
            repo=repo,
            experiment=item.experiment_path,
            runner=runner,
            backend=backend,
            backend_options_override=backend_options_override,
            timeout_seconds_override=timeout_seconds_override,
            before=snapshot,
            expected_analysis_path=expected_analysis_path,
        )
        futures[future] = index
        submitted += 1

    with ThreadPoolExecutor(max_workers=jobs) as executor:
        while submitted < len(runnable_indexes) and len(futures) < jobs:
            submit(runnable_indexes[submitted], executor)

        while futures:
            done, _pending = wait(futures, return_when=FIRST_COMPLETED)
            done = set(done)
            done.update(future for future in futures if future.done())
            for future in done:
                index = futures.pop(future)
                try:
                    result, before = future.result()
                except Exception:  # pragma: no cover - defensive boundary
                    result = AnalyzeResult(
                        experiment_path=items[index].experiment_path,
                        analysis_path=None,
                        status="failed",
                        diagnostic_codes=["analysis_exception"],
                    )
                    before = None
                final_item = _item_from_analyze_result(result)
                if before is not None and _analysis_was_written(repo, result.analysis_path, before):
                    token_usage = _read_token_usage(repo, result.analysis_path)
                    if token_usage is not None:
                        final_item = replace(final_item, token_usage=token_usage)
                        written_token_usage.append(token_usage)
                items[index] = final_item
                _emit(on_update, final_item)
                if final_item.status is not BatchStatus.ACCEPTED:
                    stop_launching = True

            while (
                not stop_launching
                and submitted < len(runnable_indexes)
                and len(futures) < jobs
            ):
                submit(runnable_indexes[submitted], executor)

    for index in runnable_indexes[submitted:]:
        items[index] = replace(items[index], status=BatchStatus.NOT_STARTED)
        _emit(on_update, items[index])

    return written_token_usage


def _run_one(
    *,
    repo: Path,
    experiment: str,
    runner: AnalyzeOne,
    backend: object | None,
    backend_options_override: dict[str, Any] | None,
    timeout_seconds_override: int | None,
    before: "_FileSnapshot | None",
    expected_analysis_path: str | None,
) -> tuple[AnalyzeResult, "_FileSnapshot | None"]:
    result = runner(
        repo=repo,
        experiment=experiment,
        backend=backend,
        backend_options_override=backend_options_override,
        timeout_seconds_override=timeout_seconds_override,
    )
    if result.analysis_path != expected_analysis_path:
        return result, None
    return result, before


def _item_from_analyze_result(result: AnalyzeResult) -> BatchAnalyzeItem:
    status = BatchStatus.ACCEPTED if result.status == "accepted" else BatchStatus.FAILED
    return BatchAnalyzeItem(
        experiment_path=result.experiment_path,
        status=status,
        analysis_path=result.analysis_path,
        diagnostic_codes=list(result.diagnostic_codes),
    )


@dataclass(frozen=True)
class _FileSnapshot:
    exists: bool
    stat: tuple[int, int, int] | None


def _analysis_snapshot(repo: Path, analysis_path: str | None) -> _FileSnapshot | None:
    if analysis_path is None or not is_repo_relative_posix(analysis_path):
        return None
    path = repo / analysis_path
    try:
        stat = path.stat()
    except FileNotFoundError:
        return _FileSnapshot(exists=False, stat=None)
    return _FileSnapshot(
        exists=True,
        stat=(stat.st_ino, stat.st_size, stat.st_mtime_ns),
    )


def _analysis_was_written(
    repo: Path, analysis_path: str | None, before: _FileSnapshot
) -> bool:
    if analysis_path is None or not is_repo_relative_posix(analysis_path):
        return False
    path = repo / analysis_path
    try:
        stat = path.stat()
    except FileNotFoundError:
        return False
    after = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
    return not before.exists or after != before.stat


def _read_token_usage(repo: Path, analysis_path: str | None) -> dict[str, int] | None:
    if analysis_path is None or not is_repo_relative_posix(analysis_path):
        return None
    try:
        with (repo / analysis_path).open(encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    backend = state.get("backend")
    if not isinstance(backend, dict):
        return None
    token_usage = backend.get("token_usage")
    if not isinstance(token_usage, dict):
        return None
    normalized = {
        key: value
        for key in _TOKEN_KEYS
        if isinstance((value := token_usage.get(key)), int) and value >= 0
    }
    return normalized or None


def _zero_token_totals() -> dict[str, int]:
    return {key: 0 for key in _TOKEN_KEYS}


def _add_token_usage(token_totals: dict[str, int], token_usage: dict[str, int]) -> None:
    for key in _TOKEN_KEYS:
        token_totals[key] += token_usage.get(key, 0)


def _batch_result(items: list[BatchAnalyzeItem]) -> BatchAnalyzeResult:
    counts = {
        "selected": len(items),
        "skipped": 0,
        "accepted": 0,
        "failed": 0,
        "blocked": 0,
        "not_started": 0,
    }
    for item in items:
        if item.status in {
            BatchStatus.SKIPPED,
            BatchStatus.ACCEPTED,
            BatchStatus.FAILED,
            BatchStatus.BLOCKED,
            BatchStatus.NOT_STARTED,
        }:
            counts[item.status.value] += 1
    return BatchAnalyzeResult(
        items=list(items),
        counts=counts,
        token_totals=_zero_token_totals(),
        exit_success=(
            counts["failed"] == 0
            and counts["blocked"] == 0
            and counts["not_started"] == 0
        ),
    )


def _backend_name(backend: object | None) -> str:
    if backend is None:
        return "unknown"
    name = getattr(backend, "name", None)
    if isinstance(name, str) and name:
        return name
    return "unknown"


def _emit(on_update: ProgressCallback | None, item: BatchAnalyzeItem) -> None:
    if on_update is not None:
        on_update(item)
