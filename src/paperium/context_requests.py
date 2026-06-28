from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

WINDOWS_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


class ContextRequestError(Exception):
    pass


@dataclass
class ContextRequest:
    id: str
    worker_id: str
    requested_paths: list[str]
    reason: str


def read_context_request(path: str | Path) -> ContextRequest:
    try:
        with Path(path).open(encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ContextRequestError(f"invalid context request JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ContextRequestError("context request must be an object")

    try:
        request = ContextRequest(
            id=_required_string(data, "id"),
            worker_id=_required_string(data, "worker_id"),
            requested_paths=_validated_requested_paths(data["requested_paths"]),
            reason=_required_string(data, "reason"),
        )
    except KeyError as exc:
        raise ContextRequestError(f"missing context request field: {exc.args[0]}") from exc
    return request


def write_context_request(path: str | Path, request: ContextRequest) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        _sorted_json(
            {
                "id": request.id,
                "reason": request.reason,
                "requested_paths": _validated_requested_paths(request.requested_paths),
                "worker_id": request.worker_id,
            }
        ),
        encoding="utf-8",
    )


def write_context_decision(path: str | Path, request_id: str, approved: bool) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        _sorted_json({"approved": approved, "request_id": request_id}),
        encoding="utf-8",
    )


def context_request_state_from_request(
    request: ContextRequest, decision_path: str
) -> dict[str, Any]:
    return {
        "decision_path": decision_path,
        "id": request.id,
        "reason": request.reason,
        "requested_paths": list(request.requested_paths),
        "status": "pending",
        "worker_id": request.worker_id,
    }


def apply_context_decision(
    worker_record: dict[str, Any], requested_paths: list[str], approved: bool
) -> dict[str, Any]:
    paths = _validated_requested_paths(requested_paths)
    if approved:
        worker_record.setdefault("approved_expansions", []).extend(paths)
    else:
        worker_record.setdefault("denied_expansions", []).extend(paths)
    return worker_record


def _sorted_json(data: dict[str, Any]) -> str:
    return (
        json.dumps(data, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    )


def _required_string(data: dict[str, Any], field: str) -> str:
    value = data[field]
    if not isinstance(value, str) or value == "":
        raise ContextRequestError(f"{field} must be a non-empty string")
    return value


def _validated_requested_paths(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ContextRequestError("requested_paths must be a non-empty list of strings")
    if not all(isinstance(item, str) and item for item in value):
        raise ContextRequestError("requested_paths must be a non-empty list of strings")

    for requested_path in value:
        if "\\" in requested_path or WINDOWS_DRIVE_PREFIX.match(requested_path):
            raise ContextRequestError(
                f"requested path must be repo-relative without traversal: {requested_path}"
            )
        path = PurePosixPath(requested_path)
        if path.is_absolute() or ".." in path.parts:
            raise ContextRequestError(
                f"requested path must be repo-relative without traversal: {requested_path}"
            )
    return list(value)
