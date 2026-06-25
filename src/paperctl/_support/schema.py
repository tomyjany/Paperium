from __future__ import annotations

import json
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

from paperctl import schemas


def load_schema(name: str) -> dict[str, Any]:
    if "/" in name or "\\" in name:
        raise ValueError(f"schema name must be a resource basename: {name}")
    resource = resources.files(schemas).joinpath(name)
    return json.loads(resource.read_text(encoding="utf-8"))


def validate_artifact(name: str, obj: Any) -> None:
    schema = load_schema(name)
    validator = Draft202012Validator(schema)
    validator.validate(obj)
