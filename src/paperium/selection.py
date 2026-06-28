from __future__ import annotations

import os
from pathlib import Path


class SelectionError(Exception):
    """Raised when an experiment selection cannot be resolved."""


RUN_ARTIFACT_DIR_NAMES = {
    "outputs",
    "ocr_outputs",
    "metrics",
    "profiles",
    "events",
}

RUN_ARTIFACT_PREFIXES = {
    "metrics",
    "summary",
    "result_summary",
    "telemetry",
    "benchmark_report",
    "observations",
    "sample_outputs",
}

RUN_ARTIFACT_EXACT_NAMES = {
    "stdout.log",
    "stderr.log",
}

CONTRACT_FILE_NAMES = {
    "README.md",
    "metadata.json",
    "docker-compose.yml",
    "docker-stack.yml",
    "pyproject.toml",
}

RUNNER_SCRIPT_NAMES = {
    "runner",
    "runner.sh",
    "runner.py",
    "run.sh",
    "run.py",
}


def discover_menu_experiments(repo: Path) -> list[Path]:
    return sorted(
        path
        for path in repo.glob("questions/**/experiments/*")
        if path.is_dir()
    )


def has_usable_run_artifact(experiment: Path) -> bool:
    return _has_artifact_in_named_dir(experiment) or _has_root_artifact(experiment)


def resolve_question_readme(repo: Path, experiment: Path) -> Path | None:
    repo = repo.resolve()
    questions_dir = repo / "questions"
    current = experiment.resolve().parent

    while current != current.parent:
        if _is_relative_to(current, questions_dir):
            readme = current / "README.md"
            if readme.is_file():
                return readme
        if current == repo:
            break
        current = current.parent

    return None


def validate_manual_experiments(repo: Path, paths: list[str]) -> list[Path]:
    repo = repo.resolve()
    experiments = []

    for raw_path in paths:
        experiment = _resolve_selection_path(repo, raw_path)
        if not experiment.exists():
            raise SelectionError(f"Experiment path does not exist: {raw_path}")
        if not experiment.is_dir():
            raise SelectionError(f"Experiment path is not a directory: {raw_path}")
        if not _matches_experiment_contract(experiment):
            raise SelectionError(f"Experiment path is missing a recognized contract: {raw_path}")
        experiments.append(experiment)

    return experiments


def _resolve_selection_path(repo: Path, raw_path: str) -> Path:
    selected = Path(raw_path)
    if not selected.is_absolute():
        selected = repo / selected
    selected = selected.resolve()
    if not _is_relative_to(selected, repo):
        raise SelectionError(f"Experiment path is outside repository: {raw_path}")
    return selected


def _matches_experiment_contract(experiment: Path) -> bool:
    if has_usable_run_artifact(experiment):
        return True
    if any((experiment / name).exists() for name in CONTRACT_FILE_NAMES):
        return True
    return any(
        path.is_file()
        and path.name in RUNNER_SCRIPT_NAMES
        and os.access(path, os.X_OK)
        for path in experiment.iterdir()
    )


def _has_artifact_in_named_dir(experiment: Path) -> bool:
    for artifact_dir in experiment.rglob("*"):
        if not artifact_dir.is_dir() or artifact_dir.name not in RUN_ARTIFACT_DIR_NAMES:
            continue
        for artifact in artifact_dir.rglob("*"):
            if _is_non_readme_file(artifact):
                return True
    return False


def _has_root_artifact(experiment: Path) -> bool:
    if not experiment.is_dir():
        return False
    return any(
        path.is_file()
        and path.stat().st_size > 0
        and _matches_root_artifact_name(path.name)
        for path in experiment.iterdir()
    )


def _is_non_readme_file(path: Path) -> bool:
    return path.is_file() and path.name.lower() != "readme.md" and path.stat().st_size > 0


def _matches_root_artifact_name(file_name: str) -> bool:
    if file_name in RUN_ARTIFACT_EXACT_NAMES:
        return True
    stem = file_name.split(".", maxsplit=1)[0]
    return stem in RUN_ARTIFACT_PREFIXES


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
