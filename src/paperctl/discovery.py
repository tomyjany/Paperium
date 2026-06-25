from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import ValidationError

from paperctl._support.hashing import canonical_json_hash, sha256_file
from paperctl._support.jsonio import dump_json_bytes, write_json_atomic
from paperctl._support.paths import resolve_repo_relative_path
from paperctl._support.schema import validate_artifact


class DiscoveryError(ValueError):
    pass


@dataclass(frozen=True)
class ManifestResult:
    path: str
    experiment_count: int
    status: str
    manifest: dict[str, Any]


def discover(repo: Path, config: dict[str, Any], force: bool = False) -> ManifestResult:
    repo = repo.resolve()
    questions_config = config["questions"]
    paper_config = config["paper"]
    questions_root = resolve_repo_relative_path(repo, questions_config["root"])
    if not questions_root.exists():
        raise DiscoveryError(f"missing configured questions root: {questions_config['root']}")
    if not questions_root.is_dir():
        raise DiscoveryError(
            f"configured questions root is not a directory: {questions_config['root']}"
        )

    work_directory = paper_config["work_directory"]
    manifest_path = f"{work_directory}/manifest.json"
    manifest = _build_manifest(repo, config, questions_root)
    try:
        validate_artifact("manifest.schema.json", manifest)
    except ValidationError as exc:
        raise DiscoveryError(f"invalid generated manifest: {exc.message}") from exc

    output_path = resolve_repo_relative_path(repo, manifest_path)
    status = _write_manifest(output_path, manifest, force)
    return ManifestResult(
        path=manifest_path,
        experiment_count=len(manifest["experiments"]),
        status=status,
        manifest=manifest,
    )


def _build_manifest(repo: Path, config: dict[str, Any], questions_root: Path) -> dict[str, Any]:
    questions_config = config["questions"]
    work_directory = config["paper"]["work_directory"]
    directory_entries: list[dict[str, str | None]] = [
        {"kind": "questions_root", "path": _repo_relative(repo, questions_root)}
    ]
    experiments: list[dict[str, str | None]] = []

    question_dirs = sorted(
        (path for path in questions_root.glob(questions_config["pattern"]) if path.is_dir()),
        key=lambda path: _repo_relative(repo, path),
    )
    for question_dir in question_dirs:
        question_path = _repo_relative(repo, question_dir)
        directory_entries.append({"kind": "question", "path": question_path})
        readme_path = question_dir / "README.md"
        question_readme_path = None
        question_readme_sha256 = None
        if readme_path.is_file():
            question_readme_path = _repo_relative(repo, readme_path)
            question_readme_sha256 = sha256_file(readme_path)
            directory_entries.append(
                {
                    "kind": "question_readme",
                    "path": question_readme_path,
                    "sha256": question_readme_sha256,
                }
            )

        experiments_dir = question_dir / questions_config["experiments_directory"]
        experiments_dir_path = _repo_relative(repo, experiments_dir)
        if not experiments_dir.is_dir():
            directory_entries.append(
                {"kind": "experiments_directory_missing", "path": experiments_dir_path}
            )
            continue

        directory_entries.append({"kind": "experiments_directory", "path": experiments_dir_path})
        experiment_dirs = sorted(
            (path for path in experiments_dir.iterdir() if path.is_dir()),
            key=lambda path: _repo_relative(repo, path),
        )
        for experiment_dir in experiment_dirs:
            experiment_path = _repo_relative(repo, experiment_dir)
            directory_entries.append({"kind": "experiment", "path": experiment_path})
            experiments.append(
                {
                    "question_ref": question_dir.name,
                    "question_path": question_path,
                    "question_readme_path": question_readme_path,
                    "question_readme_sha256": question_readme_sha256,
                    "experiment_ref": experiment_dir.name,
                    "experiment_path": experiment_path,
                    "inventory_path": f"{work_directory}/inventories/{experiment_path}.json",
                    "evidence_path": f"{work_directory}/evidence/{experiment_path}.json",
                }
            )

    experiments.sort(key=lambda entry: (entry["question_path"], entry["experiment_path"]))
    return {
        "schema_version": 1,
        "artifact_type": "manifest",
        "fingerprint": {
            "config_sha256": canonical_json_hash(_relevant_config(config)),
            "directory_entries_sha256": canonical_json_hash(directory_entries),
        },
        "experiments": experiments,
    }


def _write_manifest(output_path: Path, manifest: dict[str, Any], force: bool) -> str:
    new_bytes = dump_json_bytes(manifest)
    if output_path.exists():
        try:
            old_bytes = output_path.read_bytes()
        except OSError as exc:
            raise DiscoveryError(
                f"could not read existing manifest: {_path_for_error(output_path)}: {exc}"
            ) from exc
        if old_bytes == new_bytes:
            return "unchanged"
        if not force:
            raise DiscoveryError("manifest already exists and differs; use --force to replace it")
        status = "replaced"
    else:
        status = "created"

    try:
        write_json_atomic(output_path, manifest)
    except OSError as exc:
        raise DiscoveryError(
            f"could not write manifest: {_path_for_error(output_path)}: {exc}"
        ) from exc
    return status


def _relevant_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "questions": {
            "root": config["questions"]["root"],
            "pattern": config["questions"]["pattern"],
            "experiments_directory": config["questions"]["experiments_directory"],
        },
        "paper": {
            "work_directory": config["paper"]["work_directory"],
        },
    }


def _repo_relative(repo: Path, path: Path) -> str:
    return path.relative_to(repo).as_posix()


def _path_for_error(path: Path) -> str:
    return path.as_posix()
