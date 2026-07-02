from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
PHASES = {
    "selecting",
    "analyzing",
    "fact_checking",
    "ranking",
    "mapping",
    "writing",
    "reviewing",
    "complete",
    "failed",
}
EXPERIMENT_STATUSES = {
    "pending",
    "running",
    "approved",
    "failed",
    "needs_human_review",
    "skipped",
}
DISPOSITIONS = {
    "included",
    "excluded",
    "deferred",
    "artifact_missing",
    "fact_check_failed",
    "needs_human_review",
    "skipped",
}
WORKER_STATUSES = {
    "pending",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "needs_context",
}
BACKENDS = {"codex", "claude"}
WORKER_ROLES = {"analyze", "fact_check", "rank", "write", "review"}
CONTEXT_REQUEST_STATUSES = {"pending", "approved", "denied"}
SECTION_STATUSES = {
    "not_started",
    "drafted",
    "review_failed",
    "approved",
    "skipped",
}
FACTUAL_REVIEW_STATUSES = {"not_started", "passed", "failed"}
FINAL_WRITE_STATUSES = {"not_started", "ready", "written", "failed"}


class StateError(Exception):
    pass


def _validate_enum(name: str, value: str | None, allowed: set[str]) -> None:
    if value is not None and (not isinstance(value, str) or value not in allowed):
        raise StateError(f"invalid {name}: {value}")


def _expect_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StateError(f"{name} must be an object")
    return value


def _list_of_strings(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise StateError(f"{name} must be a list of strings")
    return value


def _list_value(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise StateError(f"{name} must be a list")
    return value


@dataclass
class SelectedExperiment:
    path: str
    question_readme: str | None
    analysis_path: str
    fact_check_result_path: str
    disposition: str | None
    status: str = "pending"
    repair_attempts: int = 0

    def __post_init__(self) -> None:
        _validate_enum("selected experiment status", self.status, EXPERIMENT_STATUSES)
        _validate_enum("selected experiment disposition", self.disposition, DISPOSITIONS)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_path": self.analysis_path,
            "disposition": self.disposition,
            "fact_check_result_path": self.fact_check_result_path,
            "path": self.path,
            "question_readme": self.question_readme,
            "repair_attempts": self.repair_attempts,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SelectedExperiment:
        data = _expect_mapping(data, "selected experiment")
        try:
            return cls(
                path=data["path"],
                question_readme=data.get("question_readme"),
                analysis_path=data["analysis_path"],
                fact_check_result_path=data["fact_check_result_path"],
                disposition=data.get("disposition"),
                status=data.get("status", "pending"),
                repair_attempts=data.get("repair_attempts", 0),
            )
        except KeyError as exc:
            raise StateError(f"missing selected experiment field: {exc.args[0]}") from exc


@dataclass
class WorkerRecord:
    id: str
    backend: str
    role: str
    experiment_path: str | None = None
    status: str = "pending"
    started_at: str | None = None
    ended_at: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    output_path: str | None = None
    result_json_path: str | None = None
    canonical_result_path: str | None = None
    readable_paths: list[str] = field(default_factory=list)
    writable_paths: list[str] = field(default_factory=list)
    approved_expansions: list[str] = field(default_factory=list)
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        _validate_enum("worker backend", self.backend, BACKENDS)
        _validate_enum("worker role", self.role, WORKER_ROLES)
        _validate_enum("worker status", self.status, WORKER_STATUSES)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved_expansions": self.approved_expansions,
            "backend": self.backend,
            "canonical_result_path": self.canonical_result_path,
            "ended_at": self.ended_at,
            "experiment_path": self.experiment_path,
            "failure_reason": self.failure_reason,
            "id": self.id,
            "output_path": self.output_path,
            "readable_paths": self.readable_paths,
            "result_json_path": self.result_json_path,
            "role": self.role,
            "started_at": self.started_at,
            "status": self.status,
            "stderr_path": self.stderr_path,
            "stdout_path": self.stdout_path,
            "writable_paths": self.writable_paths,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkerRecord:
        data = _expect_mapping(data, "worker")
        try:
            return cls(
                id=data["id"],
                backend=data["backend"],
                role=data["role"],
                experiment_path=data.get("experiment_path"),
                status=data.get("status", "pending"),
                started_at=data.get("started_at"),
                ended_at=data.get("ended_at"),
                stdout_path=data.get("stdout_path"),
                stderr_path=data.get("stderr_path"),
                output_path=data.get("output_path"),
                result_json_path=data.get("result_json_path"),
                canonical_result_path=data.get("canonical_result_path"),
                readable_paths=_list_of_strings(data.get("readable_paths", []), "readable_paths"),
                writable_paths=_list_of_strings(data.get("writable_paths", []), "writable_paths"),
                approved_expansions=_list_of_strings(
                    data.get("approved_expansions", []), "approved_expansions"
                ),
                failure_reason=data.get("failure_reason"),
            )
        except KeyError as exc:
            raise StateError(f"missing worker field: {exc.args[0]}") from exc


@dataclass
class RankingState:
    path: str = ".paperium/ranking.md"
    json_path: str = ".paperium/ranking.json"
    approved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"approved": self.approved, "json_path": self.json_path, "path": self.path}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RankingState:
        data = _expect_mapping(data, "ranking")
        return cls(
            path=data.get("path", ".paperium/ranking.md"),
            json_path=data.get("json_path", ".paperium/ranking.json"),
            approved=data.get("approved", False),
        )


@dataclass
class QuestionFocusState:
    path: str = ".paperium/question-focus.md"
    json_path: str = ".paperium/question-focus.json"
    approved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"approved": self.approved, "json_path": self.json_path, "path": self.path}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QuestionFocusState:
        data = _expect_mapping(data, "question focus")
        return cls(
            path=data.get("path", ".paperium/question-focus.md"),
            json_path=data.get("json_path", ".paperium/question-focus.json"),
            approved=data.get("approved", False),
        )


@dataclass
class ContextRequestState:
    id: str
    worker_id: str
    requested_paths: list[str]
    reason: str
    decision_path: str
    status: str = "pending"

    def __post_init__(self) -> None:
        _validate_enum("context request status", self.status, CONTEXT_REQUEST_STATUSES)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_path": self.decision_path,
            "id": self.id,
            "reason": self.reason,
            "requested_paths": self.requested_paths,
            "status": self.status,
            "worker_id": self.worker_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContextRequestState:
        data = _expect_mapping(data, "context request")
        try:
            return cls(
                id=data["id"],
                worker_id=data["worker_id"],
                requested_paths=_list_of_strings(data["requested_paths"], "requested_paths"),
                reason=data["reason"],
                decision_path=data["decision_path"],
                status=data.get("status", "pending"),
            )
        except KeyError as exc:
            raise StateError(f"missing context request field: {exc.args[0]}") from exc


@dataclass
class SectionState:
    id: str
    title: str
    path: str
    status: str = "not_started"
    factual_review_status: str = "not_started"
    factual_review_result_path: str | None = None

    def __post_init__(self) -> None:
        _validate_enum("section status", self.status, SECTION_STATUSES)
        _validate_enum(
            "section factual review status",
            self.factual_review_status,
            FACTUAL_REVIEW_STATUSES,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "factual_review_result_path": self.factual_review_result_path,
            "factual_review_status": self.factual_review_status,
            "id": self.id,
            "path": self.path,
            "status": self.status,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SectionState:
        data = _expect_mapping(data, "section")
        try:
            return cls(
                id=data["id"],
                title=data["title"],
                path=data["path"],
                status=data.get("status", "not_started"),
                factual_review_status=data.get("factual_review_status", "not_started"),
                factual_review_result_path=data.get("factual_review_result_path"),
            )
        except KeyError as exc:
            raise StateError(f"missing section field: {exc.args[0]}") from exc


@dataclass
class FinalWriteState:
    paper_path: str = "PAPER.md"
    status: str = "not_started"
    written_at: str | None = None

    def __post_init__(self) -> None:
        _validate_enum("final write status", self.status, FINAL_WRITE_STATUSES)

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_path": self.paper_path,
            "status": self.status,
            "written_at": self.written_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FinalWriteState:
        data = _expect_mapping(data, "final write")
        return cls(
            paper_path=data.get("paper_path", "PAPER.md"),
            status=data.get("status", "not_started"),
            written_at=data.get("written_at"),
        )


@dataclass
class PaperiumState:
    schema_version: int = SCHEMA_VERSION
    phase: str = "selecting"
    selected_experiments: list[SelectedExperiment] = field(default_factory=list)
    workers: list[WorkerRecord] = field(default_factory=list)
    ranking: RankingState = field(default_factory=RankingState)
    dispositions_path: str = ".paperium/dispositions.md"
    question_focus: QuestionFocusState = field(default_factory=QuestionFocusState)
    context_requests: list[ContextRequestState] = field(default_factory=list)
    sections: list[SectionState] = field(default_factory=list)
    expected_section_ids: list[str] = field(default_factory=list)
    final_write: FinalWriteState = field(default_factory=FinalWriteState)

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise StateError(f"unsupported schema version: {self.schema_version}")
        _validate_enum("phase", self.phase, PHASES)

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_requests": [request.to_dict() for request in self.context_requests],
            "dispositions_path": self.dispositions_path,
            "expected_section_ids": self.expected_section_ids,
            "final_write": self.final_write.to_dict(),
            "phase": self.phase,
            "question_focus": self.question_focus.to_dict(),
            "ranking": self.ranking.to_dict(),
            "schema_version": self.schema_version,
            "sections": [section.to_dict() for section in self.sections],
            "selected_experiments": [
                experiment.to_dict() for experiment in self.selected_experiments
            ],
            "workers": [worker.to_dict() for worker in self.workers],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaperiumState:
        data = _expect_mapping(data, "state")
        schema_version = data.get("schema_version")
        if schema_version != SCHEMA_VERSION:
            raise StateError(f"unsupported schema version: {schema_version}")
        return cls(
            schema_version=schema_version,
            phase=data.get("phase", "selecting"),
            selected_experiments=[
                SelectedExperiment.from_dict(experiment)
                for experiment in _list_value(
                    data.get("selected_experiments", []), "selected_experiments"
                )
            ],
            workers=[
                WorkerRecord.from_dict(worker)
                for worker in _list_value(data.get("workers", []), "workers")
            ],
            ranking=RankingState.from_dict(data.get("ranking", {})),
            dispositions_path=data.get("dispositions_path", ".paperium/dispositions.md"),
            question_focus=QuestionFocusState.from_dict(data.get("question_focus", {})),
            context_requests=[
                ContextRequestState.from_dict(request)
                for request in _list_value(data.get("context_requests", []), "context_requests")
            ],
            sections=[
                SectionState.from_dict(section)
                for section in _list_value(data.get("sections", []), "sections")
            ],
            expected_section_ids=_list_of_strings(
                data.get("expected_section_ids", []), "expected_section_ids"
            ),
            final_write=FinalWriteState.from_dict(data.get("final_write", {})),
        )


def load_state(path: str | Path) -> PaperiumState:
    try:
        with Path(path).open(encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise StateError(f"invalid state JSON: {exc}") from exc
    return PaperiumState.from_dict(data)


def save_state(path: str | Path, state: PaperiumState) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(
        state.to_dict(),
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            delete=False,
            dir=destination.parent,
            encoding="utf-8",
            prefix=f".{destination.name}.",
            suffix=".tmp",
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(f"{data}\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, destination)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
