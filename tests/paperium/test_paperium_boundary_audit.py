from paperium.boundary_audit import (
    changed_paths_from_porcelain,
    find_disallowed_writes,
    snapshot_changed_paths,
    snapshot_generated_paths,
)


def test_disallowed_writes_detects_paths_outside_writable_roots():
    changed = ["questions/q001/README.md", ".paperium/workers/w1/output.md"]
    disallowed = find_disallowed_writes(
        changed_paths=changed,
        writable_paths=[".paperium/workers/w1"],
    )
    assert disallowed == ["questions/q001/README.md"]


def test_writable_path_matching_is_path_segment_safe():
    disallowed = find_disallowed_writes(
        changed_paths=[".paperium/workers/w10/output.md"],
        writable_paths=[".paperium/workers/w1"],
    )
    assert disallowed == [".paperium/workers/w10/output.md"]


def test_changed_paths_from_porcelain_parses_git_status():
    output = " M questions/q001/README.md\n?? .paperium/workers/w1/output.md\n"
    assert changed_paths_from_porcelain(output) == [
        "questions/q001/README.md",
        ".paperium/workers/w1/output.md",
    ]


def test_run_worker_fails_on_write_boundary_violation(tmp_path, monkeypatch):
    from paperium.worker_runner import run_worker
    from paperium.workers import WorkerSpec

    repo = tmp_path / "repo"
    repo.mkdir()
    statuses = iter(["", " M questions/q001/README.md\n"])
    monkeypatch.setattr(
        "paperium.boundary_audit.git_status_porcelain", lambda repo: next(statuses)
    )
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda *args, **kwargs: type(
            "P",
            (),
            {
                "returncode": 0,
                "communicate": lambda self, input=None, timeout=None: ("", ""),
            },
        )(),
    )
    spec = WorkerSpec(
        "w1",
        "codex",
        "analyze",
        ["questions/q001/experiments/exp001"],
        [".paperium/workers/w1"],
        "prompt",
        30,
    )
    result = run_worker(repo, spec)
    assert result.status == "failed"
    assert result.failure_reason == "write_boundary_violation"


def test_ignored_paperium_files_are_still_audited(tmp_path):
    repo = tmp_path / "repo"
    disallowed = repo / ".paperium/other-worker/output.md"
    disallowed.parent.mkdir(parents=True)
    before = snapshot_generated_paths(repo)
    disallowed.write_text("bad")
    after = snapshot_generated_paths(repo)
    assert find_disallowed_writes(
        changed_paths=[],
        writable_paths=[".paperium/workers/w1"],
        before_snapshot=before,
        after_snapshot=after,
    ) == [".paperium/other-worker/output.md"]


def test_dirty_repo_content_change_outside_writable_roots_is_violation(tmp_path):
    repo = tmp_path / "repo"
    changed = repo / "questions/q001/README.md"
    changed.parent.mkdir(parents=True)
    changed.write_text("before")
    before = snapshot_changed_paths(repo, ["questions/q001/README.md"])
    changed.write_text("after")
    after = snapshot_changed_paths(repo, ["questions/q001/README.md"])
    assert find_disallowed_writes(
        changed_paths=["questions/q001/README.md"],
        writable_paths=[".paperium/workers/w1"],
        before_snapshot=before,
        after_snapshot=after,
    ) == ["questions/q001/README.md"]
