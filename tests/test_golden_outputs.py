from __future__ import annotations

import re
from pathlib import Path

from conftest import copy_fixture_repo, read_json, run_paperctl
from paperctl._support.jsonio import dump_json_bytes
from paperctl._support.schema import validate_artifact


GOLDEN_DIR = Path(__file__).parent / "golden" / "minimal-research-repo"

FIXED_GOLDEN_OUTPUTS = {
    Path("paper/work/manifest.json"): (
        GOLDEN_DIR / "paper/work/manifest.json",
        "manifest.schema.json",
    ),
    Path("paper/work/render-state.json"): (
        GOLDEN_DIR / "paper/work/render-state.json",
        "render-state.schema.json",
    ),
    Path("PAPER.draft.md"): (
        GOLDEN_DIR / "PAPER.draft.md",
        None,
    ),
    Path("paper/PAPER.audit.json"): (
        GOLDEN_DIR / "paper/PAPER.audit.json",
        "paper-audit.schema.json",
    ),
}

FORBIDDEN_PATTERNS = [
    re.compile(rb"/tmp/"),
    re.compile(rb"/home/"),
    re.compile(rb"/Users/"),
    re.compile(rb"/var/"),
    re.compile(rb"/private/"),
    re.compile(rb"/etc/"),
    re.compile(rb"[A-Za-z]:\\"),
    re.compile(rb"\btmp_path\b"),
    re.compile(rb"\bpytest-[^/\s]+"),
    re.compile(rb"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"),
]

FORBIDDEN_SECRETS = [
    b"sk-test-obvious-secret",
    b"API_KEY=sk-test-obvious-secret",
]


def test_compact_fixture_generated_outputs_match_goldens_and_are_reproducible(tmp_path):
    first_repo = copy_fixture_repo(tmp_path / "first")
    second_repo = copy_fixture_repo(tmp_path / "second")
    first_paper_sentinel = (first_repo / "PAPER.md").read_bytes()
    second_paper_sentinel = (second_repo / "PAPER.md").read_bytes()

    first = run_paperctl(first_repo, "build")
    second = run_paperctl(second_repo, "build")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert (first_repo / "PAPER.md").read_bytes() == first_paper_sentinel
    assert (second_repo / "PAPER.md").read_bytes() == second_paper_sentinel

    expected_outputs = _expected_outputs_from_manifest(
        read_json(first_repo / "paper/work/manifest.json")
    )

    for generated_path, (golden_path, schema_name) in expected_outputs.items():
        first_bytes = (first_repo / generated_path).read_bytes()
        second_bytes = (second_repo / generated_path).read_bytes()
        golden_bytes = golden_path.read_bytes()

        assert first_bytes == second_bytes, generated_path.as_posix()
        assert first_bytes == golden_bytes, generated_path.as_posix()
        _assert_stable_artifact_bytes(golden_path, golden_bytes)

        if schema_name is not None:
            golden_json = read_json(golden_path)
            validate_artifact(schema_name, golden_json)
            assert golden_bytes == dump_json_bytes(golden_json)
            _assert_no_platform_separators_in_paths(golden_path, golden_json)


def _expected_outputs_from_manifest(
    manifest: dict[str, object],
) -> dict[Path, tuple[Path, str | None]]:
    outputs = dict(FIXED_GOLDEN_OUTPUTS)
    experiments = manifest["experiments"]
    assert isinstance(experiments, list)
    for experiment in experiments:
        assert isinstance(experiment, dict)
        inventory_path = Path(str(experiment["inventory_path"]))
        evidence_path = Path(str(experiment["evidence_path"]))
        outputs[inventory_path] = (
            GOLDEN_DIR / inventory_path,
            "artifact-inventory.schema.json",
        )
        outputs[evidence_path] = (
            GOLDEN_DIR / evidence_path,
            "evidence-packet.schema.json",
        )
    return dict(sorted(outputs.items(), key=lambda item: item[0].as_posix()))


def _assert_stable_artifact_bytes(path: Path, content: bytes) -> None:
    for pattern in FORBIDDEN_PATTERNS:
        assert not pattern.search(content), f"{path.as_posix()} matched {pattern.pattern!r}"
    for secret in FORBIDDEN_SECRETS:
        assert secret not in content, path.as_posix()


def _assert_no_platform_separators_in_paths(path: Path, value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _is_path_field(key) and isinstance(item, str):
                assert not item.startswith("/"), (
                    f"{path.as_posix()} contains absolute path {item!r}"
                )
                assert "\\" not in item, f"{path.as_posix()} contains backslash path {item!r}"
            _assert_no_platform_separators_in_paths(path, item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_platform_separators_in_paths(path, item)


def _is_path_field(key: str) -> bool:
    return key == "path" or key.endswith("_path") or key.endswith("_output")
