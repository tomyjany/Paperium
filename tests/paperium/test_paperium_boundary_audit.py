from paperium.boundary_audit import (
    BoundaryAuditError,
    changed_paths_from_porcelain,
    find_disallowed_writes,
    git_status_porcelain,
    snapshot_changed_paths,
    snapshot_generated_paths,
)
import pytest


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


def test_generated_snapshot_refuses_symlinked_root_paperium(tmp_path):
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    (repo / ".paperium").symlink_to(outside, target_is_directory=True)

    with pytest.raises(BoundaryAuditError):
        snapshot_generated_paths(repo)


def test_generated_snapshot_refuses_symlinked_paperium_file_escape(tmp_path):
    repo = tmp_path / "repo"
    outside = tmp_path / "outside.txt"
    paperium = repo / ".paperium"
    paperium.mkdir(parents=True)
    outside.write_text("outside", encoding="utf-8")
    (paperium / "leak.txt").symlink_to(outside)

    with pytest.raises(BoundaryAuditError):
        snapshot_generated_paths(repo)


def test_generated_snapshot_is_bounded_to_explicit_generated_roots(tmp_path):
    repo = tmp_path / "repo"
    root_file = repo / ".paperium/workers/w1/result.json"
    explicit_file = repo / "questions/q001/experiments/exp001/.paperium/analysis.json"
    unrelated_file = repo / "questions/q999/experiments/exp999/.paperium/analysis.json"
    for path in (root_file, explicit_file, unrelated_file):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")

    snapshot = snapshot_generated_paths(
        repo,
        generated_roots=["questions/q001/experiments/exp001/.paperium"],
    )

    assert sorted(snapshot) == [
        ".paperium/workers/w1/result.json",
        "questions/q001/experiments/exp001/.paperium/analysis.json",
    ]


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


def test_unchanged_pre_existing_dirty_file_outside_writable_roots_is_not_violation(
    tmp_path,
):
    repo = tmp_path / "repo"
    dirty = repo / "questions/q001/README.md"
    dirty.parent.mkdir(parents=True)
    dirty.write_text("dirty")

    before = snapshot_changed_paths(repo, ["questions/q001/README.md"])
    after = snapshot_changed_paths(repo, ["questions/q001/README.md"])

    assert (
        find_disallowed_writes(
            changed_paths=["questions/q001/README.md"],
            writable_paths=[".paperium/workers/w1"],
            before_snapshot=before,
            after_snapshot=after,
        )
        == []
    )


def test_new_file_outside_writable_roots_is_snapshot_violation(tmp_path):
    repo = tmp_path / "repo"
    new_file = repo / "questions/q001/README.md"
    before = snapshot_changed_paths(repo, ["questions/q001/README.md"])
    new_file.parent.mkdir(parents=True)
    new_file.write_text("new")
    after = snapshot_changed_paths(repo, ["questions/q001/README.md"])

    assert find_disallowed_writes(
        changed_paths=["questions/q001/README.md"],
        writable_paths=[".paperium/workers/w1"],
        before_snapshot=before,
        after_snapshot=after,
    ) == ["questions/q001/README.md"]


def test_git_status_porcelain_wraps_launch_oserror(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git missing")

    monkeypatch.setattr("paperium.boundary_audit.subprocess.run", fake_run)

    with pytest.raises(BoundaryAuditError):
        git_status_porcelain(repo)
