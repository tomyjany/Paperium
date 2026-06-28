from __future__ import annotations

from pathlib import Path

from paperium.selection import has_usable_run_artifact, resolve_question_readme
from paperium.state import SelectedExperiment


def prepare_selected_experiment(repo: Path, exp: Path) -> SelectedExperiment:
    repo = repo.resolve()
    exp = exp.resolve()
    experiment_path = _repo_relative_posix(repo, exp)
    paperium_dir = exp / ".paperium"
    _validate_paperium_output_dir(repo, paperium_dir)
    paperium_dir.mkdir(exist_ok=True)

    question_readme = resolve_question_readme(repo, exp)
    if question_readme is not None:
        question_readme_path = _repo_relative_posix(repo, question_readme)
    else:
        question_readme_path = None

    if has_usable_run_artifact(exp):
        disposition = None
        status = "pending"
    else:
        disposition = "artifact_missing"
        status = "needs_human_review"

    return SelectedExperiment(
        path=experiment_path,
        question_readme=question_readme_path,
        analysis_path=f"{experiment_path}/.paperium/analysis.md",
        fact_check_result_path=f"{experiment_path}/.paperium/fact-check.json",
        disposition=disposition,
        status=status,
        repair_attempts=0,
    )


def _repo_relative_posix(repo: Path, path: Path) -> str:
    try:
        return path.relative_to(repo).as_posix()
    except ValueError as exc:
        raise ValueError(f"path is outside repository: {path}") from exc


def _validate_paperium_output_dir(repo: Path, paperium_dir: Path) -> None:
    resolved = paperium_dir.resolve()
    if paperium_dir.is_symlink():
        try:
            resolved.relative_to(repo)
        except ValueError as exc:
            raise ValueError(
                f".paperium symlink resolves outside repository: {paperium_dir}"
            ) from exc
        raise ValueError(f".paperium symlink is not allowed: {paperium_dir}")
    _repo_relative_posix(repo, resolved)
