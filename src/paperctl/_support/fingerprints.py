from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import ValidationError

from paperctl._support.hashing import canonical_json_hash, sha256_file
from paperctl._support.schema import validate_artifact


class FingerprintError(ValueError):
    pass


@dataclass(frozen=True)
class SourceFile:
    path: str
    file: Path
    sha256: str | None = None


@dataclass(frozen=True)
class PrerequisiteArtifact:
    path: str
    file: Path
    schema_name: str


def build_stage_fingerprint(
    *,
    stage_name: str,
    stage_version: int,
    schema_version: int,
    relevant_config: dict[str, Any],
    source_files: list[SourceFile] | None = None,
    prerequisite_artifacts: list[PrerequisiteArtifact] | None = None,
    extra_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sources = [
        {"path": source.path, "sha256": source.sha256 or sha256_file(source.file)}
        for source in sorted(source_files or [], key=lambda source: source.path)
    ]
    prerequisites = [
        {
            "path": prerequisite.path,
            "schema_name": prerequisite.schema_name,
            "sha256": _validated_artifact_sha256(prerequisite),
        }
        for prerequisite in sorted(
            prerequisite_artifacts or [], key=lambda prerequisite: prerequisite.path
        )
    ]
    extra_inputs_payload = extra_inputs or {}
    payload = {
        "stage": {"name": stage_name, "version": stage_version},
        "schema_version": schema_version,
        "config_sha256": canonical_json_hash(relevant_config),
        "source_files": sources,
        "source_files_sha256": canonical_json_hash(sources),
        "prerequisite_artifacts": prerequisites,
        "prerequisite_artifacts_sha256": canonical_json_hash(prerequisites),
        "extra_inputs": extra_inputs_payload,
        "extra_inputs_sha256": canonical_json_hash(extra_inputs_payload),
    }
    payload["fingerprint_sha256"] = canonical_json_hash(payload)
    return payload


def fingerprint_is_fresh(
    *,
    existing: dict[str, Any],
    expected: dict[str, Any],
    prerequisite_artifacts: list[PrerequisiteArtifact] | None = None,
) -> bool:
    for prerequisite in prerequisite_artifacts or []:
        _validated_artifact_sha256(prerequisite)
    return existing.get("fingerprint_sha256") == expected.get("fingerprint_sha256")


def _validated_artifact_sha256(prerequisite: PrerequisiteArtifact) -> str:
    try:
        with prerequisite.file.open(encoding="utf-8") as handle:
            artifact = json.load(handle)
        validate_artifact(prerequisite.schema_name, artifact)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise FingerprintError(
            f"invalid prerequisite artifact: {prerequisite.path}: {exc}"
        ) from exc
    return sha256_file(prerequisite.file)
