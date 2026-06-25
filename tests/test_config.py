from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from conftest import copy_fixture_repo, init_git_repo, read_json, run_paperctl


FIXTURE_PAPER_PREFIX = b"# SENTINEL PAPER.md\n"


def _git_init(path: Path) -> None:
    subprocess.run(
        ["git", "init"], cwd=path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )


def test_safe_yaml_parsing_rejects_custom_tags(tmp_path):
    from paperctl.config import ConfigError, load_config

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "paper.yaml").write_text(
        "schema_version: !!python/object/apply:os.system ['echo unsafe']\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(repo)


def test_load_config_rejects_duplicate_yaml_keys(tmp_path):
    from paperctl.config import ConfigError, load_config

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "paper.yaml").write_text(
        "\n".join(
            [
                "schema_version: 1",
                "paper:",
                "  work_directory: paper/work",
                "  draft_output: PAPER.draft.md",
                "  final_output: PAPER.md",
                "  audit_report: paper/PAPER.audit.json",
                "paper:",
                "  work_directory: alternate/work",
                "  draft_output: PAPER.draft.md",
                "  final_output: PAPER.md",
                "  audit_report: paper/PAPER.audit.json",
                "questions:",
                "  root: questions",
                "  pattern: q*",
                "  experiments_directory: experiments",
                "evidence:",
                "  default_canonical_artifacts:",
                "    - outputs/experiment_report.json",
                "  canonical_facts: {}",
                "  extraction_limits:",
                "    maximum_file_bytes: 10000000",
                "    maximum_scalar_observations_per_file: 200",
                "    maximum_nesting_depth: 12",
                "    preview_rows: 20",
                "    log_head_lines: 100",
                "    log_tail_lines: 100",
                "audit:",
                "  default_stage: publication",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="duplicate key"):
        load_config(repo)


def test_load_config_rejects_directory_paper_yaml_as_config_error(tmp_path):
    from paperctl.config import ConfigError, load_config

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "paper.yaml").mkdir()

    with pytest.raises(ConfigError, match="could not read config file"):
        load_config(repo)


def test_unknown_config_keys_fail_validation(tmp_path):
    from paperctl.config import ConfigError, default_config, validate_config

    repo = tmp_path / "repo"
    repo.mkdir()
    config = default_config()
    config["unexpected"] = True

    with pytest.raises(ConfigError, match="unexpected"):
        validate_config(config, repo)


def test_default_config_matches_spec():
    from paperctl._support.schema import validate_artifact
    from paperctl.config import default_config

    config = default_config()

    assert config == {
        "schema_version": 1,
        "questions": {
            "root": "questions",
            "pattern": "q*",
            "experiments_directory": "experiments",
        },
        "paper": {
            "work_directory": "paper/work",
            "draft_output": "PAPER.draft.md",
            "final_output": "PAPER.md",
            "audit_report": "paper/PAPER.audit.json",
        },
        "evidence": {
            "default_canonical_artifacts": ["outputs/experiment_report.json"],
            "canonical_facts": {},
            "extraction_limits": {
                "maximum_file_bytes": 10_000_000,
                "maximum_scalar_observations_per_file": 200,
                "maximum_nesting_depth": 12,
                "preview_rows": 20,
                "log_head_lines": 100,
                "log_tail_lines": 100,
            },
        },
        "audit": {
            "default_stage": "publication",
        },
    }
    validate_artifact("paper-config.schema.json", config)


def test_all_configured_paths_are_repo_relative(tmp_path):
    from paperctl.config import default_config, validate_config

    repo = tmp_path / "repo"
    repo.mkdir()
    config = default_config()
    config["evidence"]["canonical_facts"] = {
        "questions/q001/experiments/exp001": [
            {
                "fact_id": "accuracy",
                "source": "outputs/metrics.json",
                "selector_type": "json_pointer",
                "selector": "/accuracy",
                "expected_type": "number",
                "unit": "percent",
            }
        ]
    }

    validated = validate_config(config, repo)

    assert validated == config


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("questions", "root", "/tmp/questions"),
        ("questions", "root", "../questions"),
        ("questions", "root", "questions\\q001"),
        ("paper", "work_directory", "/tmp/paper/work"),
        ("paper", "work_directory", "../paper/work"),
        ("paper", "work_directory", "paper\\work"),
    ],
)
def test_absolute_paths_and_dotdot_escapes_fail(tmp_path, section, key, value):
    from paperctl.config import ConfigError, default_config, validate_config

    repo = tmp_path / "repo"
    repo.mkdir()
    config = default_config()
    config[section][key] = value

    with pytest.raises(ConfigError, match="repo-relative POSIX"):
        validate_config(config, repo)


def test_resolved_paths_outside_repo_fail(tmp_path):
    from paperctl.config import ConfigError, default_config, validate_config

    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    (repo / "linked").symlink_to(outside, target_is_directory=True)
    config = default_config()
    config["paper"]["work_directory"] = "linked/work"

    with pytest.raises(ConfigError, match="outside repository"):
        validate_config(config, repo)


def test_omitted_repo_resolves_git_root(tmp_path):
    from paperctl.config import resolve_repo

    repo = tmp_path / "repo"
    nested = repo / "questions" / "q001"
    nested.mkdir(parents=True)
    _git_init(repo)

    assert resolve_repo(None, nested) == repo.resolve()


def test_omitted_repo_outside_git_exits_category_4(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "paperctl", "init"],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 4
    assert "could not resolve repository" in result.stderr


def test_explicit_repo_must_exist(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "paperctl", "--repo", str(tmp_path / "missing"), "init"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 4
    assert "repository path does not exist" in result.stderr
    assert not (tmp_path / "missing").exists()


def test_paperctl_init_creates_only_config_and_work_directories(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "paperctl", "--repo", str(repo), "init"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0
    assert "paper.yaml" in result.stdout
    assert sorted(
        path.relative_to(repo).as_posix()
        for path in repo.rglob("*")
        if ".git" not in path.relative_to(repo).parts
    ) == [
        "paper",
        "paper.yaml",
        "paper/work",
        "paper/work/cache",
        "paper/work/evidence",
        "paper/work/inventories",
    ]
    assert not (repo / "PAPER.md").exists()
    assert not (repo / "PAPER.draft.md").exists()


def test_init_validates_generated_default_config_before_success(tmp_path, monkeypatch):
    import paperctl.config as config_module
    from paperctl.config import ConfigError, default_config, init_repo

    repo = tmp_path / "repo"
    repo.mkdir()
    invalid_default = default_config()
    invalid_default["unexpected"] = True
    monkeypatch.setattr(config_module, "default_config", lambda: invalid_default)

    with pytest.raises(ConfigError, match="unexpected"):
        init_repo(repo, force=False)

    assert not (repo / "paper.yaml").exists()


def test_init_rejects_unsafe_runtime_directory_without_partial_config(tmp_path):
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    (repo / "paper").symlink_to(outside, target_is_directory=True)

    result = subprocess.run(
        [sys.executable, "-m", "paperctl", "--repo", str(repo), "init"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 2
    assert "outside repository" in result.stderr
    assert not (repo / "paper.yaml").exists()


def test_init_wraps_paper_yaml_write_failure(tmp_path, monkeypatch):
    import paperctl.config as config_module
    from paperctl.config import ConfigError, init_repo

    repo = tmp_path / "repo"
    repo.mkdir()

    def fail_write(path, text):
        raise OSError("no write")

    monkeypatch.setattr(config_module, "write_text_atomic", fail_write)

    with pytest.raises(ConfigError, match="could not write config file: paper.yaml: no write"):
        init_repo(repo, force=False)

    assert not (repo / "paper.yaml").exists()


def test_init_force_rejects_directory_obstructing_paper_yaml(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "paper.yaml").mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "paperctl", "--repo", str(repo), "init", "--force"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 2
    assert "paper.yaml" in result.stderr
    assert "not a file" in result.stderr
    assert "Traceback" not in result.stderr
    assert (repo / "paper.yaml").is_dir()


def test_init_force_replaces_only_paper_yaml(tmp_path):
    from paperctl.config import init_repo

    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo(repo, force=False)
    cache_artifact = repo / "paper" / "work" / "cache" / "kept.json"
    cache_artifact.write_text('{"kept": true}\n', encoding="utf-8")
    (repo / "paper.yaml").write_text("stale: true\n", encoding="utf-8")

    result = init_repo(repo, force=True)

    assert result.replaced == ["paper.yaml"]
    assert cache_artifact.read_text(encoding="utf-8") == '{"kept": true}\n'
    assert "schema_version: 1" in (repo / "paper.yaml").read_text(encoding="utf-8")


def test_copy_fixture_repo_mutates_tmp_copy_not_committed_fixture(tmp_path):
    committed_fixture = Path(__file__).parent / "fixtures" / "minimal-research-repo"

    repo = copy_fixture_repo(tmp_path)

    assert repo != committed_fixture
    assert (repo / "PAPER.md").read_bytes().startswith(FIXTURE_PAPER_PREFIX)

    (repo / "PAPER.md").write_text("# changed copy only\n", encoding="utf-8")

    assert (repo / "PAPER.md").read_text(encoding="utf-8") == "# changed copy only\n"
    assert (committed_fixture / "PAPER.md").read_bytes().startswith(FIXTURE_PAPER_PREFIX)


def test_fixture_helpers_read_json_init_git_and_run_paperctl(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    init_git_repo(repo)

    result = run_paperctl(repo, "init", "--force")
    report = read_json(
        repo
        / "questions"
        / "q001-throughput"
        / "experiments"
        / "exp001-completed"
        / "outputs"
        / "experiment_report.json"
    )

    assert result.returncode == 0
    assert "replaced paper.yaml" in result.stdout
    assert report["execution_status"] == "completed"
    assert (repo / "PAPER.md").read_bytes().startswith(FIXTURE_PAPER_PREFIX)


def test_fixture_incomplete_experiment_has_stale_readme_and_structured_observation(tmp_path):
    from paperctl.config import load_config

    repo = copy_fixture_repo(tmp_path)
    experiment_path = "questions/q001-throughput/experiments/exp002-incomplete"

    readme = (repo / experiment_path / "README.md").read_text(encoding="utf-8")
    status = read_json(repo / experiment_path / "outputs" / "status.json")
    config = load_config(repo)

    assert "throughput reached 999 pages/s" in readme
    assert status["observations"]["throughput_pages_per_second"] == 21.5
    assert experiment_path not in config["evidence"]["canonical_facts"]


def test_fixture_unsupported_binary_contains_non_text_bytes(tmp_path):
    repo = copy_fixture_repo(tmp_path)

    payload = (
        repo
        / "questions"
        / "q001-throughput"
        / "experiments"
        / "exp005-unsupported-and-previews"
        / "outputs"
        / "model.bin"
    ).read_bytes()

    assert len(payload) <= 8
    assert b"\x00" in payload
    with pytest.raises(UnicodeDecodeError):
        payload.decode("utf-8")


def test_fixture_extraction_limits_parse_completed_report_but_keep_preview_cases(tmp_path):
    from paperctl.config import load_config

    repo = copy_fixture_repo(tmp_path)
    config = load_config(repo)
    limits = config["evidence"]["extraction_limits"]
    preview_experiment = (
        repo
        / "questions"
        / "q001-throughput"
        / "experiments"
        / "exp005-unsupported-and-previews"
        / "outputs"
    )
    completed_report = (
        repo
        / "questions"
        / "q001-throughput"
        / "experiments"
        / "exp001-completed"
        / "outputs"
        / "experiment_report.json"
    )

    assert limits["maximum_file_bytes"] >= completed_report.stat().st_size
    assert (
        len((preview_experiment / "events.jsonl").read_text(encoding="utf-8").splitlines())
        > (limits["preview_rows"])
    )
    assert (
        len((preview_experiment / "run.log").read_text(encoding="utf-8").splitlines())
        > (limits["log_head_lines"])
    )
    assert (
        len((preview_experiment / "run.log").read_text(encoding="utf-8").splitlines())
        > (limits["log_tail_lines"])
    )
