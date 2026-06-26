"""Backend boundary for single-experiment analysis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Literal, Protocol

from paperctl.analysis_validation import AnalysisDiagnostic


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


CODE_CODEX_MISSING_DEPENDENCY = "codex_missing_dependency"
CODE_CODEX_CAPABILITY_MISSING = "codex_capability_missing"
CODE_CODEX_HELP_FAILED = "codex_help_failed"


def check_codex_exec_capabilities(codex_bin: str) -> list[AnalysisDiagnostic]:
    """Verify the local codex executable supports the constrained exec contract."""
    args = [codex_bin, "exec", "--help"]
    try:
        result = subprocess.run(
            args,
            shell=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        return [
            AnalysisDiagnostic(
                code=CODE_CODEX_MISSING_DEPENDENCY,
                message=f"Codex executable missing dependency: {codex_bin}",
                detail={"error": str(exc)},
            )
        ]

    diagnostics: list[AnalysisDiagnostic] = []
    if result.returncode != 0:
        diagnostics.append(
            AnalysisDiagnostic(
                code=CODE_CODEX_HELP_FAILED,
                message="Codex exec capability probe failed.",
                detail={"return_code": result.returncode},
            )
        )

    help_text = "\n".join(part for part in (result.stdout, result.stderr) if part)
    required_substrings = (
        "--output-schema",
        "--sandbox",
        "read-only",
        "--ask-for-approval",
        "never",
    )
    for required in required_substrings:
        if required not in help_text:
            diagnostics.append(
                AnalysisDiagnostic(
                    code=CODE_CODEX_CAPABILITY_MISSING,
                    message=f"Codex exec help does not advertise required {required} support.",
                    detail={"required": required},
                )
            )
    return diagnostics


class CodexExecBackend:
    name = "codex-exec"

    def __init__(self, codex_bin: str = "codex") -> None:
        self.codex_bin = codex_bin

    def analyze(self, job: AnalysisJob) -> AnalysisBackendResult:
        diagnostics = check_codex_exec_capabilities(self.codex_bin)
        if diagnostics:
            return AnalysisBackendResult(
                backend_name=self.name,
                status="failed",
                raw_response=None,
                return_code=None,
                stdout=None,
                stderr=_format_diagnostics(diagnostics),
            )

        with tempfile.TemporaryDirectory(prefix="paperctl-analysis-") as tmp_dir:
            response_path = Path(tmp_dir) / "codex-final-message.json"
            args = [
                self.codex_bin,
                "exec",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--ask-for-approval",
                "never",
                "--output-schema",
                str(job.output_schema_path),
                "--output-last-message",
                str(response_path),
                "-",
            ]

            try:
                result = subprocess.run(
                    args,
                    cwd=job.repo,
                    input=job.prompt,
                    text=True,
                    capture_output=True,
                    timeout=job.timeout_seconds,
                    shell=False,
                )
            except subprocess.TimeoutExpired as exc:
                return AnalysisBackendResult(
                    backend_name=self.name,
                    status="timed_out",
                    raw_response=None,
                    return_code=None,
                    stdout=_coerce_subprocess_text(exc.output),
                    stderr=_coerce_subprocess_text(exc.stderr),
                )

            if result.returncode != 0:
                return AnalysisBackendResult(
                    backend_name=self.name,
                    status="failed",
                    raw_response=None,
                    return_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )

            try:
                raw_response = response_path.read_bytes()
            except OSError as exc:
                stderr = _append_stderr_detail(
                    result.stderr,
                    f"Codex final message file could not be read: {exc}",
                )
                return AnalysisBackendResult(
                    backend_name=self.name,
                    status="failed",
                    raw_response=None,
                    return_code=result.returncode,
                    stdout=result.stdout,
                    stderr=stderr,
                )

            return AnalysisBackendResult(
                backend_name=self.name,
                status="completed",
                raw_response=raw_response,
                return_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )


def _format_diagnostics(diagnostics: list[AnalysisDiagnostic]) -> str:
    return "\n".join(f"{diagnostic.code}: {diagnostic.message}" for diagnostic in diagnostics)


def _append_stderr_detail(stderr: str | None, detail: str) -> str:
    if stderr:
        return f"{stderr}\n{detail}"
    return detail


def _coerce_subprocess_text(value: str | bytes | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
