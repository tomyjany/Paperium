from pathlib import Path

from paperctl.analysis_backends import AnalysisJob, FakeBackend


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
    result = FakeBackend().analyze(
        _job(tmp_path, backend_options={"fake_response_path": str(tmp_path / "missing.json")})
    )

    assert result.backend_name == "fake"
    assert result.status == "failed"
    assert result.raw_response is None
    assert result.return_code is None
    assert result.stdout is None
    assert result.stderr == "fake response file could not be read"


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
