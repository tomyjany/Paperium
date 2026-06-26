from __future__ import annotations

import json
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

from paperctl import schemas


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
    expected_analysis_path = f"paper/work/analyses/{experiment_path}.json"
    if state.get("analysis_path") != expected_analysis_path:
        raise AnalysisStateIntegrityError(
            "analysis_state analysis_path mismatch: "
            f"expected {expected_analysis_path!r}, got {state.get('analysis_path')!r}"
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
