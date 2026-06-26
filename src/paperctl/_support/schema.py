from __future__ import annotations

import json
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

from paperctl import schemas
from paperctl._support.paths import is_repo_relative_posix


class AnalysisStateIntegrityError(ValueError):
    pass


def load_schema(name: str) -> dict[str, Any]:
    if "/" in name or "\\" in name:
        raise ValueError(f"schema name must be a resource basename: {name}")
    resource = resources.files(schemas).joinpath(name)
    return json.loads(resource.read_text(encoding="utf-8"))


def validate_artifact(name: str, obj: Any) -> None:
    schema = load_schema(name)
    validator = Draft202012Validator(schema)
    validator.validate(obj)


def validate_analysis_state_integrity(state: dict[str, Any]) -> None:
    experiment_path = state.get("experiment_path")
    analysis_path = state.get("analysis_path")
    if not isinstance(experiment_path, str) or not isinstance(analysis_path, str):
        raise AnalysisStateIntegrityError(
            "analysis_state experiment_path and analysis_path must be strings"
        )
    if not is_repo_relative_posix(analysis_path):
        raise AnalysisStateIntegrityError(
            f"analysis_state analysis_path is not repo-relative POSIX: {analysis_path!r}"
        )

    expected_suffix = f"/analyses/{experiment_path}.json"
    if not f"/{analysis_path}".endswith(expected_suffix):
        raise AnalysisStateIntegrityError(
            "analysis_state analysis_path mismatch: "
            f"expected suffix 'analyses/{experiment_path}.json', got {analysis_path!r}"
        )

    if state.get("status") != "accepted":
        return

    analysis = state.get("analysis")
    if not isinstance(analysis, dict):
        raise AnalysisStateIntegrityError("accepted analysis_state must include analysis object")

    for key in ["question_path", "experiment_path"]:
        state_path = state.get(key)
        analysis_path = analysis.get(key)
        if state_path != analysis_path:
            raise AnalysisStateIntegrityError(
                f"accepted analysis_state {key} mismatch: "
                f"state has {state_path!r}, analysis has {analysis_path!r}"
            )
