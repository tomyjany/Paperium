from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import ValidationError

from paperctl._support.fingerprints import (
    PrerequisiteArtifact,
    SourceFile,
    build_stage_fingerprint,
)
from paperctl._support.hashing import canonical_json_hash, sha256_file
from paperctl._support.jsonio import dump_json_bytes, write_json_atomic
from paperctl._support.paths import resolve_repo_relative_path
from paperctl._support.schema import validate_artifact
from paperctl._support.sorting import posix_path_sort_key
from paperctl.discovery import _build_manifest


INVENTORY_SCHEMA_VERSION = 1
INVENTORY_STAGE_VERSION = 1
MANIFEST_PATH_TEMPLATE = "{work_directory}/manifest.json"
EXCLUDED_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".DS_Store",
}
EXTENSION_KIND_MAP = {
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".csv": "csv",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".md": "markdown",
    ".markdown": "markdown",
    ".log": "log",
    ".txt": "text",
}


class InventoryError(ValueError):
    pass


@dataclass(frozen=True)
class InventoryWriteResult:
    experiment_path: str
    inventory_path: str
    status: str


@dataclass(frozen=True)
class InventoryAllResult:
    manifest_path: str
    experiment_count: int
    created: int
    replaced: int
    unchanged: int
    results: list[InventoryWriteResult]


def load_manifest(repo: Path, config: dict[str, Any]) -> dict[str, Any]:
    repo = repo.resolve()
    manifest_path = _manifest_path(config)
    absolute_path = repo / manifest_path
    try:
        with absolute_path.open(encoding="utf-8") as handle:
            manifest = json.load(handle)
    except FileNotFoundError as exc:
        raise InventoryError(
            f"missing discovery manifest: {manifest_path}; run paperctl discover first"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise InventoryError(f"could not read discovery manifest: {manifest_path}: {exc}") from exc

    _validate_manifest(manifest, manifest_path)
    _validate_manifest_fresh(repo, config, manifest)
    return manifest


def inventory_all(
    repo: Path,
    config: dict[str, Any],
    manifest: dict[str, Any],
    force: bool = False,
) -> InventoryAllResult:
    repo = repo.resolve()
    manifest_path = _manifest_path(config)
    _validate_manifest(manifest, manifest_path)
    _validate_manifest_fresh(repo, config, manifest)

    results = [
        inventory_one(repo, config, experiment, manifest_path=manifest_path, force=force)
        for experiment in manifest["experiments"]
    ]
    return InventoryAllResult(
        manifest_path=manifest_path,
        experiment_count=len(results),
        created=sum(1 for result in results if result.status == "created"),
        replaced=sum(1 for result in results if result.status == "replaced"),
        unchanged=sum(1 for result in results if result.status == "unchanged"),
        results=results,
    )


def inventory_one(
    repo: Path,
    config: dict[str, Any],
    manifest_entry: dict[str, Any],
    *,
    manifest_path: str | None = None,
    force: bool = False,
) -> InventoryWriteResult:
    repo = repo.resolve()
    manifest_path = manifest_path or _manifest_path(config)
    experiment_path = manifest_entry["experiment_path"]
    experiment_dir = _resolve_manifest_path(repo, experiment_path)
    if not experiment_dir.is_dir():
        raise InventoryError(f"manifest experiment path is not a directory: {experiment_path}")

    artifacts = _inventory_artifacts(repo, experiment_dir)
    inventory = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "artifact_type": "artifact_inventory",
        "question_path": manifest_entry["question_path"],
        "experiment_path": experiment_path,
        "fingerprint": _inventory_fingerprint(
            repo=repo,
            config=config,
            manifest_path=manifest_path,
            artifacts=artifacts,
        ),
        "artifacts": artifacts,
    }
    try:
        validate_artifact("artifact-inventory.schema.json", inventory)
    except ValidationError as exc:
        raise InventoryError(f"invalid generated inventory for {experiment_path}: {exc.message}") from exc

    inventory_path = manifest_entry["inventory_path"]
    output_path = _resolve_manifest_path(repo, inventory_path)
    status = _write_inventory(output_path, inventory, force=force)
    return InventoryWriteResult(
        experiment_path=experiment_path,
        inventory_path=inventory_path,
        status=status,
    )


def _inventory_artifacts(repo: Path, experiment_dir: Path) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    pending = [experiment_dir]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            relative = directory.relative_to(repo).as_posix()
            raise InventoryError(f"could not list experiment directory: {relative}: {exc}") from exc

        for entry in entries:
            if entry.name in EXCLUDED_NAMES:
                continue
            path = Path(entry.path)
            if entry.is_symlink():
                artifacts.append(_symlink_artifact(repo, path))
                continue
            if entry.is_dir(follow_symlinks=False):
                pending.append(path)
                continue
            if entry.is_file(follow_symlinks=False):
                artifacts.append(_regular_file_artifact(repo, path))

    return sorted(artifacts, key=lambda artifact: posix_path_sort_key(artifact["path"]))


def _regular_file_artifact(repo: Path, path: Path) -> dict[str, Any]:
    relative_path = path.relative_to(repo).as_posix()
    kind = _kind_for_regular_file(path)
    return {
        "path": relative_path,
        "file_type": "regular",
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
        "kind": kind,
        "support_status": "supported" if kind != "binary" and kind != "unknown" else "unsupported",
        "symlink_target": None,
    }


def _symlink_artifact(repo: Path, path: Path) -> dict[str, Any]:
    relative_path = path.relative_to(repo).as_posix()
    return {
        "path": relative_path,
        "file_type": "symlink",
        "byte_size": None,
        "sha256": None,
        "kind": _kind_from_extension(path),
        "support_status": "unsupported",
        "symlink_target": os.readlink(path),
    }


def _kind_for_regular_file(path: Path) -> str:
    if _is_binary(path):
        return "binary"
    return _kind_from_extension(path)


def _kind_from_extension(path: Path) -> str:
    return EXTENSION_KIND_MAP.get(path.suffix.lower(), "unknown")


def _is_binary(path: Path) -> bool:
    try:
        path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return True
    return False


def _inventory_fingerprint(
    *,
    repo: Path,
    config: dict[str, Any],
    manifest_path: str,
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    source_files = [
        SourceFile(path=artifact["path"], file=repo / artifact["path"])
        for artifact in artifacts
        if artifact["file_type"] == "regular"
    ]
    listing_inputs = [
        {
            "path": artifact["path"],
            "file_type": artifact["file_type"],
            "byte_size": artifact["byte_size"],
            "sha256": artifact["sha256"],
            "kind": artifact["kind"],
            "support_status": artifact["support_status"],
            "symlink_target": artifact.get("symlink_target"),
        }
        for artifact in artifacts
    ]
    return build_stage_fingerprint(
        stage_name="inventory",
        stage_version=INVENTORY_STAGE_VERSION,
        schema_version=INVENTORY_SCHEMA_VERSION,
        relevant_config=_relevant_config(config),
        source_files=source_files,
        prerequisite_artifacts=[
            PrerequisiteArtifact(
                path=manifest_path,
                file=repo / manifest_path,
                schema_name="manifest.schema.json",
            )
        ],
        extra_inputs={
            "artifact_listing_sha256": canonical_json_hash(listing_inputs),
            "artifact_count": len(artifacts),
        },
    )


def _validate_manifest(manifest: dict[str, Any], manifest_path: str) -> None:
    try:
        validate_artifact("manifest.schema.json", manifest)
    except ValidationError as exc:
        raise InventoryError(f"invalid discovery manifest: {manifest_path}: {exc.message}") from exc


def _validate_manifest_fresh(repo: Path, config: dict[str, Any], manifest: dict[str, Any]) -> None:
    questions_root = resolve_repo_relative_path(repo, config["questions"]["root"])
    expected_manifest = _build_manifest(repo, config, questions_root)
    if dump_json_bytes(manifest) != dump_json_bytes(expected_manifest):
        raise InventoryError(
            "stale discovery manifest: run paperctl discover --force before inventory"
        )


def _write_inventory(output_path: Path, inventory: dict[str, Any], *, force: bool) -> str:
    new_bytes = dump_json_bytes(inventory)
    if output_path.exists() and not force:
        try:
            if output_path.read_bytes() == new_bytes:
                return "unchanged"
        except OSError as exc:
            raise InventoryError(f"could not read existing inventory: {output_path}: {exc}") from exc
    status = "replaced" if output_path.exists() else "created"
    try:
        write_json_atomic(output_path, inventory)
    except OSError as exc:
        raise InventoryError(f"could not write inventory: {output_path}: {exc}") from exc
    return status


def _manifest_path(config: dict[str, Any]) -> str:
    return MANIFEST_PATH_TEMPLATE.format(work_directory=config["paper"]["work_directory"])


def _resolve_manifest_path(repo: Path, path: str) -> Path:
    try:
        return resolve_repo_relative_path(repo, path)
    except ValueError as exc:
        message = str(exc)
        if "outside repository" in message:
            raise InventoryError(f"manifest path resolves outside repository: {path}") from exc
        raise InventoryError(f"manifest path must be repo-relative POSIX: {path}") from exc


def _relevant_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "paper": {
            "work_directory": config["paper"]["work_directory"],
        }
    }
