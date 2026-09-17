import subprocess

import pytest

from paperium import worker_runner
from paperium.workers import WorkerSpec
from paperium.worker_runner import run_worker


class FakeProcess:
    def __init__(self, returncode=0, stdout="ok", stderr=""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    def communicate(self, input=None, timeout=None):
        self.input = input
        self.timeout = timeout
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True


def test_run_worker_sends_prompt_on_stdin_and_captures_output(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    process = FakeProcess()

    def fake_popen(cmd, cwd, text, encoding, stdin, stdout, stderr):
        assert cmd == ["codex", "exec", "-"]
        assert cwd == repo
        assert text is True
        assert encoding == "utf-8"
        assert stdin == subprocess.PIPE
        assert stdout == subprocess.PIPE
        assert stderr == subprocess.PIPE
        return process

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    spec = WorkerSpec(
        worker_id="w1",
        backend="codex",
        role="analyze",
        readable_paths=["questions/q001/experiments/exp001"],
        writable_paths=[".paperium/workers/w1"],
        prompt="analyze this",
        timeout_seconds=30,
    )
    result = run_worker(repo, spec)
    assert result.status == "succeeded"
    assert result.started_at is not None
    assert result.ended_at is not None
    assert process.input == "analyze this"
    assert (repo / ".paperium/workers/w1/stdout.txt").read_text() == "ok"
    assert (repo / ".paperium/workers/w1/stderr.txt").read_text() == ""


def test_run_worker_refuses_preexisting_stdout_symlink_escape_without_overwrite(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    worker_dir = repo / ".paperium/workers/w1"
    worker_dir.mkdir(parents=True)
    (worker_dir / "stdout.txt").symlink_to(outside)

    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: FakeProcess(stdout="pwn"))
    spec = WorkerSpec("w1", "codex", "analyze", [], [".paperium/workers/w1"], "prompt", 30)

    result = run_worker(repo, spec)

    assert result.status == "failed"
    assert result.failure_reason == "boundary_audit_failed"
    assert outside.read_text(encoding="utf-8") == "keep"


def test_run_worker_refuses_symlinked_paperium_directory_before_mkdir(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    (repo / ".paperium").symlink_to(outside, target_is_directory=True)

    def fake_popen(*args, **kwargs):
        raise AssertionError("unsafe worker directory should not start a subprocess")

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    spec = WorkerSpec("w1", "codex", "analyze", [], [".paperium/workers/w1"], "prompt", 30)

    result = run_worker(repo, spec)

    assert result.status == "failed"
    assert result.failure_reason == "boundary_audit_failed"
    assert not (outside / "workers").exists()


def test_run_worker_does_not_count_runner_output_capture_as_worker_write(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: FakeProcess(stdout="ok"))
    spec = WorkerSpec("w1", "codex", "analyze", [], [], "prompt", 30)

    result = run_worker(repo, spec)

    assert result.status == "succeeded"
    assert result.failure_reason is None


def test_run_worker_rejects_worker_id_path_traversal_without_writing_outside_workers(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    repo.mkdir()

    def fake_popen(*args, **kwargs):
        raise AssertionError("invalid worker id should not spawn a subprocess")

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    spec = WorkerSpec(
        "../escape",
        "codex",
        "analyze",
        [],
        [".paperium/workers/../escape"],
        "prompt",
        30,
    )
    result = run_worker(repo, spec)
    assert result.status == "failed"
    assert result.failure_reason == "invalid_worker_id"
    assert not (repo / ".paperium/escape/stdout.txt").exists()


@pytest.mark.parametrize(
    "canonical_result_path_kind",
    ["traversal", "absolute"],
)
def test_run_worker_rejects_unsafe_canonical_result_path_without_copying_outside_repo(
    tmp_path, monkeypatch, canonical_result_path_kind
):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside_path = tmp_path / "outside.json"
    canonical_result_path = (
        "../outside.json"
        if canonical_result_path_kind == "traversal"
        else str(outside_path)
    )

    def fake_popen(*args, **kwargs):
        worker_dir = repo / ".paperium/workers/w1"
        worker_dir.mkdir(parents=True, exist_ok=True)
        (worker_dir / "result.json").write_text(
            '{"status": "passed", "findings": []}', encoding="utf-8"
        )
        return FakeProcess()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    spec = WorkerSpec(
        "w1",
        "codex",
        "fact_check",
        [],
        [".paperium/workers/w1"],
        "prompt",
        30,
        canonical_result_path=canonical_result_path,
    )
    result = run_worker(repo, spec)
    assert result.status == "failed"
    assert result.failure_reason == "invalid_canonical_result_path"
    assert not outside_path.exists()


def test_run_worker_records_nonzero_exit_as_failed(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(
        "subprocess.Popen", lambda *args, **kwargs: FakeProcess(returncode=2, stderr="bad")
    )
    spec = WorkerSpec("w1", "claude", "write", [], [".paperium/workers/w1"], "prompt", 30)
    result = run_worker(repo, spec)
    assert result.status == "failed"
    assert result.failure_reason == "nonzero_exit:2"


def test_run_worker_fails_closed_when_git_status_fails_before_worker_starts(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 128, "", "fatal: not a git repository")

    def fake_popen(*args, **kwargs):
        raise AssertionError("worker should not start when boundary audit cannot run")

    monkeypatch.setattr(worker_runner.boundary_audit.subprocess, "run", fake_run)
    monkeypatch.setattr("subprocess.Popen", fake_popen)
    spec = WorkerSpec("w1", "codex", "analyze", [], [".paperium/workers/w1"], "prompt", 30)
    result = run_worker(repo, spec)
    assert result.status == "failed"
    assert result.failure_reason == "boundary_audit_failed"


def test_run_worker_fails_closed_when_boundary_audit_fails_after_worker_starts(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    repo.mkdir()
    snapshots = iter(
        [
            ([], {}),
            worker_runner.boundary_audit.BoundaryAuditError("git status failed"),
        ]
    )
    worker_started = False

    def fake_boundary_snapshot(repo, spec):
        snapshot = next(snapshots)
        if isinstance(snapshot, worker_runner.boundary_audit.BoundaryAuditError):
            raise snapshot
        return snapshot

    def fake_popen(*args, **kwargs):
        nonlocal worker_started
        worker_started = True
        return FakeProcess()

    monkeypatch.setattr(worker_runner, "_boundary_snapshot", fake_boundary_snapshot)
    monkeypatch.setattr("subprocess.Popen", fake_popen)
    spec = WorkerSpec("w1", "codex", "analyze", [], [".paperium/workers/w1"], "prompt", 30)
    result = run_worker(repo, spec)
    assert worker_started is True
    assert result.status == "failed"
    assert result.failure_reason == "boundary_audit_failed"


def test_run_worker_copies_result_json_to_canonical_path(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()

    def fake_popen(*args, **kwargs):
        worker_dir = repo / ".paperium/workers/w1"
        worker_dir.mkdir(parents=True, exist_ok=True)
        (worker_dir / "result.json").write_text('{"status": "passed", "findings": []}')
        return FakeProcess()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    spec = WorkerSpec(
        worker_id="w1",
        backend="codex",
        role="fact_check",
        readable_paths=["questions/q001/experiments/exp001"],
        writable_paths=[
            ".paperium/workers/w1",
            "questions/q001/experiments/exp001/.paperium",
        ],
        prompt="check",
        timeout_seconds=30,
        canonical_result_path="questions/q001/experiments/exp001/.paperium/fact-check.json",
    )
    result = run_worker(repo, spec)
    assert result.status == "succeeded"
    assert (repo / "questions/q001/experiments/exp001/.paperium/fact-check.json").exists()


def test_run_worker_marks_missing_expected_result_as_failed(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: FakeProcess())
    spec = WorkerSpec(
        "w1",
        "codex",
        "fact_check",
        [],
        [".paperium/workers/w1"],
        "prompt",
        30,
        canonical_result_path="exp/.paperium/fact-check.json",
    )
    result = run_worker(repo, spec)
    assert result.status == "failed"
    assert result.failure_reason == "missing_result_json"


def test_run_worker_detects_context_request_and_returns_needs_context(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    repo.mkdir()

    def fake_popen(*args, **kwargs):
        request_dir = repo / ".paperium/context-requests"
        request_dir.mkdir(parents=True, exist_ok=True)
        (request_dir / "req1.json").write_text(
            '{"id": "req1", "worker_id": "w1", "requested_paths": ["questions/q001/src"]}'
        )
        return FakeProcess()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    spec = WorkerSpec(
        "w1",
        "codex",
        "analyze",
        [],
        [".paperium/workers/w1", ".paperium/context-requests"],
        "prompt",
        30,
    )
    result = run_worker(repo, spec)
    assert result.status == "needs_context"
    assert result.canonical_result_path is None


def test_run_worker_context_request_without_writable_context_dir_is_boundary_violation(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    repo.mkdir()

    def fake_popen(*args, **kwargs):
        request_dir = repo / ".paperium/context-requests"
        request_dir.mkdir(parents=True, exist_ok=True)
        (request_dir / "req1.json").write_text(
            '{"id": "req1", "worker_id": "w1", "requested_paths": ["questions/q001/src"]}'
        )
        return FakeProcess()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    spec = WorkerSpec("w1", "codex", "analyze", [], [".paperium/workers/w1"], "prompt", 30)
    result = run_worker(repo, spec)
    assert result.status == "failed"
    assert result.failure_reason == "write_boundary_violation"


def test_run_worker_ignores_stale_or_other_worker_context_requests(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    stale_dir = repo / ".paperium/context-requests"
    stale_dir.mkdir(parents=True)
    (stale_dir / "old.json").write_text('{"id": "old", "worker_id": "old-worker"}')
    repo.mkdir(exist_ok=True)
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: FakeProcess())
    spec = WorkerSpec("w1", "codex", "analyze", [], [".paperium/workers/w1"], "prompt", 30)
    result = run_worker(repo, spec)
    assert result.status == "succeeded"


def test_run_worker_detects_overwritten_current_worker_context_request(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    request_dir = repo / ".paperium/context-requests"
    request_dir.mkdir(parents=True)
    request_path = request_dir / "req1.json"
    request_path.write_text('{"id": "req1", "worker_id": "old-worker"}', encoding="utf-8")

    def fake_popen(*args, **kwargs):
        request_path.write_text('{"id": "req1", "worker_id": "w1"}', encoding="utf-8")
        return FakeProcess()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    spec = WorkerSpec(
        "w1",
        "codex",
        "analyze",
        [],
        [".paperium/workers/w1", ".paperium/context-requests"],
        "prompt",
        30,
    )
    result = run_worker(repo, spec)
    assert result.status == "needs_context"


def test_run_worker_malformed_context_request_json_fails(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()

    def fake_popen(*args, **kwargs):
        request_dir = repo / ".paperium/context-requests"
        request_dir.mkdir(parents=True, exist_ok=True)
        (request_dir / "req1.json").write_text("{not json", encoding="utf-8")
        return FakeProcess()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    spec = WorkerSpec(
        "w1",
        "codex",
        "analyze",
        [],
        [".paperium/workers/w1", ".paperium/context-requests"],
        "prompt",
        30,
    )
    result = run_worker(repo, spec)
    assert result.status == "failed"
    assert result.failure_reason == "invalid_context_request"


@pytest.mark.parametrize(
    ("valid_request_name", "malformed_request_name"),
    [
        ("aaa-valid.json", "zzz-malformed.json"),
        ("zzz-valid.json", "aaa-malformed.json"),
    ],
)
def test_run_worker_malformed_changed_context_request_wins_over_valid_request(
    tmp_path, monkeypatch, valid_request_name, malformed_request_name
):
    repo = tmp_path / "repo"
    repo.mkdir()

    def fake_popen(*args, **kwargs):
        request_dir = repo / ".paperium/context-requests"
        request_dir.mkdir(parents=True, exist_ok=True)
        (request_dir / valid_request_name).write_text(
            '{"id": "valid", "worker_id": "w1"}', encoding="utf-8"
        )
        (request_dir / malformed_request_name).write_text("{not json", encoding="utf-8")
        return FakeProcess()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    spec = WorkerSpec(
        "w1",
        "codex",
        "analyze",
        [],
        [".paperium/workers/w1", ".paperium/context-requests"],
        "prompt",
        30,
    )
    result = run_worker(repo, spec)
    assert result.status == "failed"
    assert result.failure_reason == "invalid_context_request"


def test_run_worker_malformed_changed_context_request_wins_when_snapshot_lists_valid_first(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    repo.mkdir()
    request_dir = repo / ".paperium/context-requests"
    valid_request = request_dir / "valid.json"
    malformed_request = request_dir / "malformed.json"
    snapshot_calls = 0

    def fake_request_snapshot(context_dir):
        nonlocal snapshot_calls
        snapshot_calls += 1
        if snapshot_calls == 1:
            return {}
        return {
            valid_request: "valid-digest",
            malformed_request: "malformed-digest",
        }

    def fake_popen(*args, **kwargs):
        request_dir.mkdir(parents=True, exist_ok=True)
        valid_request.write_text('{"id": "valid", "worker_id": "w1"}', encoding="utf-8")
        malformed_request.write_text("{not json", encoding="utf-8")
        return FakeProcess()

    monkeypatch.setattr(worker_runner, "_request_snapshot", fake_request_snapshot)
    monkeypatch.setattr("subprocess.Popen", fake_popen)
    spec = WorkerSpec(
        "w1",
        "codex",
        "analyze",
        [],
        [".paperium/workers/w1", ".paperium/context-requests"],
        "prompt",
        30,
    )
    result = run_worker(repo, spec)
    assert result.status == "failed"
    assert result.failure_reason == "invalid_context_request"


def test_run_worker_timeout_reaps_process_and_captures_final_buffered_output(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    repo.mkdir()

    class TimeoutThenFinalProcess(FakeProcess):
        returncode = None

        def __init__(self):
            super().__init__()
            self.communicate_calls = 0

        def communicate(self, input=None, timeout=None):
            self.communicate_calls += 1
            if self.communicate_calls == 1:
                self.input = input
                self.timeout = timeout
                raise subprocess.TimeoutExpired(
                    ["codex"], timeout, output="partial", stderr="slow"
                )
            return "final", "done"

    process = TimeoutThenFinalProcess()
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: process)
    spec = WorkerSpec("w1", "codex", "analyze", [], [".paperium/workers/w1"], "prompt", 1)
    result = run_worker(repo, spec)
    assert result.status == "timed_out"
    assert result.failure_reason == "timeout"
    assert process.killed is True
    assert process.communicate_calls == 2
    assert (repo / ".paperium/workers/w1/stdout.txt").read_text(encoding="utf-8") == "final"
    assert (repo / ".paperium/workers/w1/stderr.txt").read_text(encoding="utf-8") == "done"


def test_run_worker_timeout_kills_process_and_captures_partial_output(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    repo.mkdir()

    class TimeoutProcess(FakeProcess):
        returncode = None

        def __init__(self):
            super().__init__()
            self.communicate_calls = 0

        def communicate(self, input=None, timeout=None):
            self.communicate_calls += 1
            if self.communicate_calls > 1:
                return "", ""
            self.input = input
            self.timeout = timeout
            raise subprocess.TimeoutExpired(
                ["codex"], timeout, output="partial", stderr="slow"
            )

    process = TimeoutProcess()
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: process)
    spec = WorkerSpec("w1", "codex", "analyze", [], [".paperium/workers/w1"], "prompt", 1)
    result = run_worker(repo, spec)
    assert result.status == "timed_out"
    assert result.failure_reason == "timeout"
    assert process.killed is True
    assert process.communicate_calls == 2
    assert (repo / ".paperium/workers/w1/stdout.txt").read_text(encoding="utf-8") == "partial"
    assert (repo / ".paperium/workers/w1/stderr.txt").read_text(encoding="utf-8") == "slow"
