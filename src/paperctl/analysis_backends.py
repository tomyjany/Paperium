"""Backend boundary for single-experiment analysis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class AnalysisJob:
    repo: Path
    config: dict[str, Any]
    question_path: str
    question_readme_path: str | None
    question_readme_hash: str | None
    experiment_path: str
    inventory_path: str
    evidence_path: str
    output_schema_path: Path
    prompt: str
    timeout_seconds: int
    backend_options: dict[str, Any]


@dataclass(frozen=True)
class AnalysisBackendResult:
    backend_name: str
    status: Literal["completed", "failed", "timed_out"]
    raw_response: bytes | None
    return_code: int | None
    stdout: str | None
    stderr: str | None


class AnalysisBackend(Protocol):
    def analyze(self, job: AnalysisJob) -> AnalysisBackendResult:
        """Run analysis for a single experiment."""


class FakeBackend:
    name = "fake"

    def analyze(self, job: AnalysisJob) -> AnalysisBackendResult:
        try:
            response_path = Path(job.backend_options["fake_response_path"])
        except KeyError:
            return AnalysisBackendResult(
                backend_name=self.name,
                status="failed",
                raw_response=None,
                return_code=None,
                stdout=None,
                stderr="fake_response_path backend option is required",
            )
        except TypeError:
            return AnalysisBackendResult(
                backend_name=self.name,
                status="failed",
                raw_response=None,
                return_code=None,
                stdout=None,
                stderr="fake_response_path backend option is required",
            )

        try:
            raw_response = response_path.read_bytes()
        except OSError as exc:
            return AnalysisBackendResult(
                backend_name=self.name,
                status="failed",
                raw_response=None,
                return_code=None,
                stdout=None,
                stderr=f"fake response file could not be read: {response_path}: {exc}",
            )

        return AnalysisBackendResult(
            backend_name=self.name,
            status="completed",
            raw_response=raw_response,
            return_code=0,
            stdout=None,
            stderr=None,
        )
