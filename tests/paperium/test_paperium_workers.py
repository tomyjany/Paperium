from paperium.workers import WorkerSpec, build_worker_record, worker_id_for


def test_worker_record_has_readable_and_writable_paths(tmp_path):
    spec = WorkerSpec(
        worker_id="w1",
        backend="codex",
        role="analyze",
        readable_paths=["questions/q001/experiments/exp001"],
        writable_paths=[".paperium/workers/w1"],
        prompt="do work",
        timeout_seconds=30,
    )
    record = build_worker_record(spec)
    assert record["id"] == "w1"
    assert record["backend"] == "codex"
    assert record["role"] == "analyze"
    assert record["experiment_path"] is None
    assert record["started_at"] is None
    assert record["ended_at"] is None
    assert record["readable_paths"] == ["questions/q001/experiments/exp001"]
    assert record["writable_paths"] == [".paperium/workers/w1"]
    assert record["stdout_path"] == ".paperium/workers/w1/stdout.txt"
    assert record["stderr_path"] == ".paperium/workers/w1/stderr.txt"
    assert record["output_path"] == ".paperium/workers/w1/output.md"
    assert record["result_json_path"] == ".paperium/workers/w1/result.json"
    assert record["canonical_result_path"] is None
    assert record["approved_expansions"] == []
    assert record["failure_reason"] is None
    assert record["status"] == "pending"


def test_worker_id_for_is_deterministic_and_collision_resistant():
    first = worker_id_for("analyze", "questions/q001/experiments/exp001")
    second = worker_id_for("analyze", "questions/q001/experiments/exp001")
    other = worker_id_for("analyze", "questions/q001/experiments/exp001-copy")
    assert first == second
    assert first.startswith("analyze-questions-q001-experiments-exp001-")
    assert first != other


def test_worker_id_for_canonicalizes_role_slug_without_changing_record_role():
    spec = WorkerSpec(
        worker_id=worker_id_for("fact_check", "questions/q001/experiments/exp001"),
        backend="codex",
        role="fact_check",
        readable_paths=["questions/q001/experiments/exp001"],
        writable_paths=[".paperium/workers/fact-check"],
        prompt="check",
        timeout_seconds=30,
    )
    assert spec.worker_id.startswith("fact-check-questions-q001-experiments-exp001-")
    assert build_worker_record(spec)["role"] == "fact_check"
