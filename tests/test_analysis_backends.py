from pathlib import Path
import subprocess

import pytest

from paperctl.analysis_backends import (
    AnalysisJob,
    CodexExecBackend,
    FakeBackend,
    check_codex_exec_capabilities,
)


def _job(
    tmp_path: Path,
    *,
    backend_options: dict | None = None,
    timeout_seconds: int = 30,
) -> AnalysisJob:
    return AnalysisJob(
        repo=tmp_path / "repo",
        config={},
        question_path="questions/q001-throughput",
        question_readme_path="questions/q001-throughput/README.md",
        question_readme_hash="sha256:" + "0" * 64,
        experiment_path="questions/q001-throughput/experiments/exp001-completed",
        inventory_path=(
            "paper/work/inventories/questions/q001-throughput/experiments/exp001-completed.json"
        ),
        evidence_path=(
            "paper/work/evidence/questions/q001-throughput/experiments/exp001-completed.json"
        ),
        output_schema_path=tmp_path / "schema.json",
        prompt="Analyze the experiment.",
        timeout_seconds=timeout_seconds,
        backend_options=backend_options or {},
    )


def test_fake_response_path_resolves_relative_to_current_working_directory(tmp_path, monkeypatch):
    cwd = tmp_path / "cwd"
    cwd_response = cwd / "responses" / "analysis.json"
    cwd_response.parent.mkdir(parents=True)
    cwd_response.write_bytes(b"from current working directory")

    repo_response = tmp_path / "repo" / "responses" / "analysis.json"
    repo_response.parent.mkdir(parents=True)
    repo_response.write_bytes(b"from repo")

    monkeypatch.chdir(cwd)

    result = FakeBackend().analyze(
        _job(tmp_path, backend_options={"fake_response_path": "responses/analysis.json"})
    )

    assert result.status == "completed"
    assert result.raw_response == b"from current working directory"


def test_fake_backend_returns_raw_bytes_without_parsing_json(tmp_path):
    response_path = tmp_path / "invalid.json"
    raw_response = b'{"not": "valid json",'
    response_path.write_bytes(raw_response)

    result = FakeBackend().analyze(
        _job(tmp_path, backend_options={"fake_response_path": str(response_path)})
    )

    assert result.backend_name == "fake"
    assert result.status == "completed"
    assert result.raw_response == raw_response
    assert result.return_code == 0
    assert result.stderr is None


def test_missing_fake_response_returns_failed_backend_status(tmp_path):
    missing_path = tmp_path / "missing.json"
    result = FakeBackend().analyze(
        _job(tmp_path, backend_options={"fake_response_path": str(missing_path)})
    )

    assert result.backend_name == "fake"
    assert result.status == "failed"
    assert result.raw_response is None
    assert result.return_code is None
    assert result.stdout is None
    assert result.stderr is not None
    assert "fake response file could not be read" in result.stderr
    assert str(missing_path) in result.stderr
    assert "No such file" in result.stderr or "not found" in result.stderr


def test_missing_fake_response_path_option_returns_failed_backend_status(tmp_path):
    result = FakeBackend().analyze(_job(tmp_path))

    assert result.backend_name == "fake"
    assert result.status == "failed"
    assert result.raw_response is None
    assert result.return_code is None
    assert result.stdout is None
    assert result.stderr == "fake_response_path backend option is required"


def test_fake_backend_does_not_apply_codex_timeout_behavior(tmp_path):
    response_path = tmp_path / "analysis.json"
    response_path.write_bytes(b'{"status": "still read"}')

    result = FakeBackend().analyze(
        _job(
            tmp_path,
            backend_options={"fake_response_path": str(response_path)},
            timeout_seconds=0,
        )
    )

    assert result.status == "completed"
    assert result.raw_response == b'{"status": "still read"}'


def _codex_help(
    *,
    output_schema: bool = True,
    output_last_message: bool = True,
    sandbox: bool = True,
    read_only: bool = True,
    ask_for_approval: bool = True,
    never: bool = True,
) -> str:
    parts = ["Usage: codex exec [OPTIONS] -"]
    if output_schema:
        parts.append("--output-schema <PATH>")
    if output_last_message:
        parts.append("--output-last-message <PATH>")
    if sandbox:
        parts.append("--sandbox <MODE>")
    if read_only:
        parts.append("read-only")
    if ask_for_approval:
        parts.append("--ask-for-approval <POLICY>")
    if never:
        parts.append("never")
    return "\n".join(parts)


def _completed(
    args: list[str],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=args, returncode=returncode, stdout=stdout, stderr=stderr
    )


def _install_subprocess_run(monkeypatch, run_impl):
    monkeypatch.setattr("paperctl.analysis_backends.subprocess.run", run_impl)


def _successful_codex_run(monkeypatch, *, raw_response: bytes = b'{"analysis": true}'):
    calls = []
    response_paths: list[Path] = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if args == ["codex-test", "exec", "--help"]:
            return _completed(args, stdout=_codex_help())
        response_path = Path(args[args.index("--output-last-message") + 1])
        response_paths.append(response_path)
        response_path.write_bytes(raw_response)
        return _completed(args, stdout='{"stdout": "metadata only"}', stderr="diagnostic text")

    _install_subprocess_run(monkeypatch, fake_run)
    return calls, response_paths


def test_codex_capability_probe_runs_exec_help(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return _completed(args, stdout=_codex_help())

    _install_subprocess_run(monkeypatch, fake_run)

    diagnostics = check_codex_exec_capabilities("codex-test")

    assert diagnostics == []
    assert calls == [
        (
            ["codex-test", "exec", "--help"],
            {"shell": False, "capture_output": True, "text": True},
        )
    ]


def test_missing_codex_executable_reports_missing_dependency_before_invocation(
    tmp_path, monkeypatch
):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        raise FileNotFoundError("missing codex")

    _install_subprocess_run(monkeypatch, fake_run)

    result = CodexExecBackend(codex_bin="missing-codex").analyze(_job(tmp_path))

    assert calls == [["missing-codex", "exec", "--help"]]
    assert result.backend_name == "codex-exec"
    assert result.status == "failed"
    assert result.raw_response is None
    assert result.return_code is None
    assert result.stdout is None
    assert result.stderr is not None
    assert "missing dependency" in result.stderr


@pytest.mark.parametrize(
    ("help_text", "expected"),
    [
        (_codex_help(output_schema=False), "--output-schema"),
        (_codex_help(output_last_message=False), "--output-last-message"),
        (_codex_help(sandbox=False), "--sandbox"),
        (_codex_help(read_only=False), "read-only"),
        (_codex_help(ask_for_approval=False), "--ask-for-approval"),
        (_codex_help(never=False), "never"),
    ],
)
def test_codex_capability_failures_refuse_before_model_invocation(
    tmp_path, monkeypatch, help_text, expected
):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args == ["codex-test", "exec", "--help"]:
            return _completed(args, stdout=help_text)
        raise AssertionError("model invocation should not run")

    _install_subprocess_run(monkeypatch, fake_run)

    result = CodexExecBackend(codex_bin="codex-test").analyze(_job(tmp_path))

    assert calls == [["codex-test", "exec", "--help"]]
    assert result.status == "failed"
    assert result.raw_response is None
    assert result.stderr is not None
    assert expected in result.stderr


def test_codex_capability_probe_reports_permission_launch_failure(monkeypatch):
    def fake_run(args, **kwargs):
        raise PermissionError("permission denied")

    _install_subprocess_run(monkeypatch, fake_run)

    diagnostics = check_codex_exec_capabilities("codex-test")

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "codex_launch_failed"
    assert "permission denied" in diagnostics[0].message


def test_codex_command_uses_required_flags_stdin_and_schema(tmp_path, monkeypatch):
    calls, response_paths = _successful_codex_run(monkeypatch)

    job = _job(tmp_path)
    result = CodexExecBackend(codex_bin="codex-test").analyze(job)

    assert result.status == "completed"
    assert result.raw_response == b'{"analysis": true}'
    assert result.return_code == 0
    assert result.stdout == '{"stdout": "metadata only"}'
    assert result.stderr == "diagnostic text"

    args, kwargs = calls[1]
    assert isinstance(args, list)
    assert args[:2] == ["codex-test", "exec"]
    assert "--ephemeral" in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert args[args.index("--ask-for-approval") + 1] == "never"
    assert args[args.index("--output-schema") + 1] == str(job.output_schema_path)
    assert args[args.index("--output-last-message") + 1] == str(response_paths[0])
    assert args[-1] == "-"
    assert response_paths[0].is_absolute()
    assert not response_paths[0].is_relative_to(job.repo)
    assert not response_paths[0].exists()
    assert kwargs == {
        "cwd": job.repo,
        "input": job.prompt,
        "text": True,
        "capture_output": True,
        "timeout": job.timeout_seconds,
        "shell": False,
    }


def test_codex_response_temp_path_stays_outside_repo_when_default_temp_is_inside_repo(
    tmp_path, monkeypatch
):
    job = _job(tmp_path)
    inside_repo_temp = job.repo / "tmp"
    inside_repo_temp.mkdir(parents=True)
    monkeypatch.setattr("paperctl.analysis_backends.tempfile.tempdir", str(inside_repo_temp))
    calls, response_paths = _successful_codex_run(monkeypatch)

    result = CodexExecBackend(codex_bin="codex-test").analyze(job)

    assert result.status == "completed"
    assert calls[1][0][calls[1][0].index("--output-last-message") + 1] == str(response_paths[0])
    assert (
        not response_paths[0].resolve(strict=False).is_relative_to(job.repo.resolve(strict=False))
    )
    assert not response_paths[0].exists()


def test_codex_fails_before_invocation_when_no_safe_response_temp_dir(tmp_path, monkeypatch):
    job = _job(tmp_path)
    unsafe_temp = job.repo / "tmp"
    unsafe_temp.mkdir(parents=True)
    calls = []

    monkeypatch.setattr(
        "paperctl.analysis_backends._response_temp_parent_candidates",
        lambda: [unsafe_temp],
        raising=False,
    )

    def fake_run(args, **kwargs):
        calls.append(args)
        if args == ["codex-test", "exec", "--help"]:
            return _completed(args, stdout=_codex_help())
        raise AssertionError("model invocation should not run")

    _install_subprocess_run(monkeypatch, fake_run)

    result = CodexExecBackend(codex_bin="codex-test").analyze(job)

    assert calls == [["codex-test", "exec", "--help"]]
    assert result.status == "failed"
    assert result.raw_response is None
    assert result.return_code is None
    assert result.stdout is None
    assert result.stderr is not None
    assert "outside the target repo" in result.stderr


def test_codex_stdout_stderr_are_metadata_not_raw_analysis(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if args == ["codex-test", "exec", "--help"]:
            return _completed(args, stdout=_codex_help())
        response_path = Path(args[args.index("--output-last-message") + 1])
        response_path.write_bytes(b'{"from": "final message"}')
        return _completed(
            args,
            stdout='{"from": "stdout"}',
            stderr='{"from": "stderr"}',
        )

    _install_subprocess_run(monkeypatch, fake_run)

    result = CodexExecBackend(codex_bin="codex-test").analyze(_job(tmp_path))

    assert result.status == "completed"
    assert result.raw_response == b'{"from": "final message"}'
    assert result.stdout == '{"from": "stdout"}'
    assert result.stderr == '{"from": "stderr"}'


def test_codex_nonzero_return_code_returns_failed_status_without_raw_response(
    tmp_path, monkeypatch
):
    def fake_run(args, **kwargs):
        if args == ["codex-test", "exec", "--help"]:
            return _completed(args, stdout=_codex_help())
        response_path = Path(args[args.index("--output-last-message") + 1])
        response_path.write_bytes(b'{"should": "not be used"}')
        return _completed(args, returncode=2, stdout="out", stderr="err")

    _install_subprocess_run(monkeypatch, fake_run)

    result = CodexExecBackend(codex_bin="codex-test").analyze(_job(tmp_path))

    assert result.status == "failed"
    assert result.raw_response is None
    assert result.return_code == 2
    assert result.stdout == "out"
    assert result.stderr == "err"


def test_codex_model_invocation_oserror_returns_failed_status(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args == ["codex-test", "exec", "--help"]:
            return _completed(args, stdout=_codex_help())
        raise OSError("exec format error")

    _install_subprocess_run(monkeypatch, fake_run)

    result = CodexExecBackend(codex_bin="codex-test").analyze(_job(tmp_path))

    assert len(calls) == 2
    assert result.status == "failed"
    assert result.raw_response is None
    assert result.return_code is None
    assert result.stdout is None
    assert result.stderr is not None
    assert "exec format error" in result.stderr


def test_codex_missing_final_message_file_returns_failed_status(tmp_path, monkeypatch):
    def fake_run(args, **kwargs):
        if args == ["codex-test", "exec", "--help"]:
            return _completed(args, stdout=_codex_help())
        return _completed(args, stdout="out", stderr="err")

    _install_subprocess_run(monkeypatch, fake_run)

    result = CodexExecBackend(codex_bin="codex-test").analyze(_job(tmp_path))

    assert result.status == "failed"
    assert result.raw_response is None
    assert result.return_code == 0
    assert result.stdout == "out"
    assert result.stderr is not None
    assert "final message" in result.stderr
    assert "err" in result.stderr


def test_codex_unreadable_final_message_file_returns_failed_status(tmp_path, monkeypatch):
    response_paths: list[Path] = []

    def fake_run(args, **kwargs):
        if args == ["codex-test", "exec", "--help"]:
            return _completed(args, stdout=_codex_help())
        response_path = Path(args[args.index("--output-last-message") + 1])
        response_paths.append(response_path)
        response_path.write_bytes(b'{"unreadable": true}')
        return _completed(args, stdout="out", stderr="err")

    def fake_read_bytes(path: Path):
        if response_paths and path == response_paths[0]:
            raise OSError("permission denied")
        return original_read_bytes(path)

    original_read_bytes = Path.read_bytes
    _install_subprocess_run(monkeypatch, fake_run)
    monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)

    result = CodexExecBackend(codex_bin="codex-test").analyze(_job(tmp_path))

    assert result.status == "failed"
    assert result.raw_response is None
    assert result.return_code == 0
    assert result.stdout == "out"
    assert result.stderr is not None
    assert "final message" in result.stderr
    assert "permission denied" in result.stderr
    assert not response_paths[0].exists()


def test_codex_timeout_returns_timed_out_status(tmp_path, monkeypatch):
    def fake_run(args, **kwargs):
        if args == ["codex-test", "exec", "--help"]:
            return _completed(args, stdout=_codex_help())
        raise subprocess.TimeoutExpired(
            cmd=args,
            timeout=kwargs["timeout"],
            output="partial stdout",
            stderr="partial stderr",
        )

    _install_subprocess_run(monkeypatch, fake_run)

    result = CodexExecBackend(codex_bin="codex-test").analyze(_job(tmp_path))

    assert result.status == "timed_out"
    assert result.raw_response is None
    assert result.return_code is None
    assert result.stdout == "partial stdout"
    assert result.stderr == "partial stderr"
