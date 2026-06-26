"""Backend boundary for single-experiment analysis."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Literal, NamedTuple, Protocol

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
CODE_CODEX_LAUNCH_FAILED = "codex_launch_failed"
CODE_CODEX_CAPABILITY_MISSING = "codex_capability_missing"
CODE_CODEX_HELP_FAILED = "codex_help_failed"
CODE_CODEX_TEMP_DIR_UNAVAILABLE = "codex_temp_dir_unavailable"


class _CodexCapabilityCheck(NamedTuple):
    diagnostics: list[AnalysisDiagnostic]
    approval_flag_scope: Literal["exec", "global"] | None


def check_codex_exec_capabilities(codex_bin: str) -> list[AnalysisDiagnostic]:
    """Verify the local codex executable supports the constrained exec contract."""
    return _probe_codex_exec_capabilities(codex_bin).diagnostics


def _probe_codex_exec_capabilities(codex_bin: str) -> _CodexCapabilityCheck:
    args = [codex_bin, "exec", "--help"]
    try:
        result = subprocess.run(
            args,
            shell=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        return _CodexCapabilityCheck(
            [
                AnalysisDiagnostic(
                    code=CODE_CODEX_MISSING_DEPENDENCY,
                    message=f"Codex executable missing dependency: {codex_bin}",
                    detail={"error": str(exc)},
                )
            ],
            None,
        )
    except OSError as exc:
        return _CodexCapabilityCheck(
            [
                AnalysisDiagnostic(
                    code=CODE_CODEX_LAUNCH_FAILED,
                    message=f"Codex exec capability probe launch failed: {exc}",
                    detail={"error": str(exc)},
                )
            ],
            None,
        )

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
        "--output-last-message",
        "--sandbox",
        "read-only",
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

    approval_flag_scope, approval_diagnostics = _codex_approval_flag_scope(codex_bin, help_text)
    diagnostics.extend(approval_diagnostics)
    return _CodexCapabilityCheck(diagnostics, approval_flag_scope)


def _codex_approval_flag_scope(
    codex_bin: str, exec_help_text: str
) -> tuple[Literal["exec", "global"] | None, list[AnalysisDiagnostic]]:
    if _has_no_approval_help(exec_help_text):
        return "exec", []

    args = [codex_bin, "--help"]
    try:
        result = subprocess.run(
            args,
            shell=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return None, [
            AnalysisDiagnostic(
                code=CODE_CODEX_LAUNCH_FAILED,
                message=f"Codex top-level capability probe launch failed: {exc}",
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
    if _has_no_approval_help(help_text):
        return "global", diagnostics

    diagnostics.append(
        AnalysisDiagnostic(
            code=CODE_CODEX_CAPABILITY_MISSING,
            message="Codex help does not advertise required --ask-for-approval never support.",
            detail={"required": "--ask-for-approval never"},
        )
    )
    return None, diagnostics


def _has_no_approval_help(help_text: str) -> bool:
    return "--ask-for-approval" in help_text and "never" in help_text


class CodexExecBackend:
    name = "codex-exec"

    def __init__(self, codex_bin: str = "codex") -> None:
        self.codex_bin = codex_bin

    def analyze(self, job: AnalysisJob) -> AnalysisBackendResult:
        capability_check = _probe_codex_exec_capabilities(self.codex_bin)
        if capability_check.diagnostics:
            return AnalysisBackendResult(
                backend_name=self.name,
                status="failed",
                raw_response=None,
                return_code=None,
                stdout=None,
                stderr=_format_diagnostics(capability_check.diagnostics),
            )
        if capability_check.approval_flag_scope is None:
            return AnalysisBackendResult(
                backend_name=self.name,
                status="failed",
                raw_response=None,
                return_code=None,
                stdout=None,
                stderr=f"{CODE_CODEX_CAPABILITY_MISSING}: Codex approval flag scope unavailable",
            )

        response_temp_dir, temp_dir_error = _create_response_temp_dir(job.repo)
        if response_temp_dir is None:
            return AnalysisBackendResult(
                backend_name=self.name,
                status="failed",
                raw_response=None,
                return_code=None,
                stdout=None,
                stderr=temp_dir_error,
            )

        with response_temp_dir as tmp_dir:
            response_path = Path(tmp_dir) / "codex-final-message.json"
            args = _codex_exec_args(
                codex_bin=self.codex_bin,
                approval_flag_scope=capability_check.approval_flag_scope,
                output_schema_path=job.output_schema_path,
                response_path=response_path,
            )

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
            except OSError as exc:
                return AnalysisBackendResult(
                    backend_name=self.name,
                    status="failed",
                    raw_response=None,
                    return_code=None,
                    stdout=None,
                    stderr=f"{CODE_CODEX_LAUNCH_FAILED}: Codex exec launch failed: {exc}",
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


def _codex_exec_args(
    *,
    codex_bin: str,
    approval_flag_scope: Literal["exec", "global"],
    output_schema_path: Path,
    response_path: Path,
) -> list[str]:
    if approval_flag_scope == "global":
        return [
            codex_bin,
            "--ask-for-approval",
            "never",
            "exec",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--output-schema",
            str(output_schema_path),
            "--output-last-message",
            str(response_path),
            "-",
        ]
    return [
        codex_bin,
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--ask-for-approval",
        "never",
        "--output-schema",
        str(output_schema_path),
        "--output-last-message",
        str(response_path),
        "-",
    ]


def _format_diagnostics(diagnostics: list[AnalysisDiagnostic]) -> str:
    return "\n".join(f"{diagnostic.code}: {diagnostic.message}" for diagnostic in diagnostics)


def _create_response_temp_dir(
    repo: Path,
) -> tuple[tempfile.TemporaryDirectory[str] | None, str | None]:
    repo_resolved = repo.resolve(strict=False)
    rejected: list[str] = []

    for parent in _response_temp_parent_candidates():
        parent_resolved = parent.resolve(strict=False)
        if _is_relative_to(parent_resolved, repo_resolved):
            rejected.append(f"{parent_resolved} is inside the target repo")
            continue

        try:
            temp_dir = tempfile.TemporaryDirectory(
                prefix="paperctl-analysis-",
                dir=parent,
            )
        except OSError as exc:
            rejected.append(f"{parent_resolved} could not be used: {exc}")
            continue

        temp_dir_resolved = Path(temp_dir.name).resolve(strict=False)
        if _is_relative_to(temp_dir_resolved, repo_resolved):
            rejected.append(f"{temp_dir_resolved} is inside the target repo")
            temp_dir.cleanup()
            continue

        return temp_dir, None

    detail = "; ".join(rejected) if rejected else "no temp directory candidates"
    return (
        None,
        (
            f"{CODE_CODEX_TEMP_DIR_UNAVAILABLE}: Could not create Codex final message "
            f"temp directory outside the target repo: {detail}"
        ),
    )


def _response_temp_parent_candidates() -> list[Path]:
    candidates = [
        Path(tempfile.gettempdir()),
        *(Path(value) for value in _temp_env_values()),
        Path("/tmp"),
        Path("/var/tmp"),
        Path("/usr/tmp"),
    ]
    return _deduplicate_paths(candidates)


def _temp_env_values() -> list[str]:
    return [value for name in ("TMPDIR", "TEMP", "TMP") if (value := os.getenv(name))]


def _deduplicate_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    deduplicated: list[Path] = []
    for path in paths:
        key = str(path.resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(path)
    return deduplicated


def _is_relative_to(path: Path, base: Path) -> bool:
    return path == base or path.is_relative_to(base)


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
