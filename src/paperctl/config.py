from __future__ import annotations

import copy
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml
from jsonschema import ValidationError

from paperctl._support.atomic import write_text_atomic
from paperctl._support.paths import resolve_repo_relative_path
from paperctl._support.schema import validate_artifact


CONFIG_NAME = "paper.yaml"
WORK_SUBDIRECTORIES = ("inventories", "evidence", "cache")


class ConfigError(ValueError):
    pass


class RepoResolutionError(ConfigError):
    pass


@dataclass(frozen=True)
class InitResult:
    created: list[str]
    replaced: list[str]


_DEFAULT_CONFIG: dict[str, Any] = {
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


def resolve_repo(repo_arg: str | None, cwd: Path) -> Path:
    if repo_arg is not None:
        repo = Path(repo_arg).expanduser()
        if not repo.is_absolute():
            repo = cwd / repo
        if not repo.exists():
            raise RepoResolutionError(f"repository path does not exist: {repo}")
        if not repo.is_dir():
            raise RepoResolutionError(f"repository path is not a directory: {repo}")
        return repo.resolve()

    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "git rev-parse failed"
        raise RepoResolutionError(f"could not resolve repository from current Git root: {detail}")
    return Path(result.stdout.strip()).resolve()


def default_config() -> dict[str, Any]:
    return copy.deepcopy(_DEFAULT_CONFIG)


def load_config(repo: Path) -> dict[str, Any]:
    config_path = repo / CONFIG_NAME
    try:
        text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"missing config file: {CONFIG_NAME}") from exc

    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {CONFIG_NAME}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ConfigError(f"{CONFIG_NAME} must contain a mapping")
    return validate_config(loaded, repo)


def validate_config(config: dict[str, Any], repo: Path) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ConfigError("configuration must be a mapping")

    _validate_config_paths(config, repo)
    try:
        validate_artifact("paper-config.schema.json", config)
    except ValidationError as exc:
        raise ConfigError(f"invalid {CONFIG_NAME}: {exc.message}") from exc
    return copy.deepcopy(config)


def init_repo(repo: Path, force: bool) -> InitResult:
    repo = repo.resolve()
    config_path = repo / CONFIG_NAME
    if config_path.exists() and not force:
        raise ConfigError(f"{CONFIG_NAME} already exists; use --force to replace it")

    created: list[str] = []
    replaced: list[str] = []

    if config_path.exists():
        replaced.append(CONFIG_NAME)
    else:
        created.append(CONFIG_NAME)
    write_text_atomic(config_path, _dump_config(default_config()))

    work_directory = default_config()["paper"]["work_directory"]
    for name in WORK_SUBDIRECTORIES:
        directory = resolve_repo_relative_path(repo, f"{work_directory}/{name}")
        existed = directory.exists()
        directory.mkdir(parents=True, exist_ok=True)
        if not existed:
            created.append(directory.relative_to(repo).as_posix())

    return InitResult(created=created, replaced=replaced)


def _dump_config(config: dict[str, Any]) -> str:
    return yaml.safe_dump(config, sort_keys=False, allow_unicode=False)


def _validate_config_paths(config: dict[str, Any], repo: Path) -> None:
    for label, path in _configured_paths(config):
        if not isinstance(path, str):
            continue
        try:
            resolve_repo_relative_path(repo, path)
        except ValueError as exc:
            message = str(exc)
            if "outside repository" in message:
                raise ConfigError(f"configured path resolves outside repository: {label}={path!r}") from exc
            raise ConfigError(f"configured path must be repo-relative POSIX: {label}={path!r}") from exc


def _configured_paths(config: dict[str, Any]) -> Iterable[tuple[str, Any]]:
    questions = config.get("questions")
    if isinstance(questions, dict):
        yield "questions.root", questions.get("root")
        yield "questions.experiments_directory", questions.get("experiments_directory")

    paper = config.get("paper")
    if isinstance(paper, dict):
        for key in ["work_directory", "draft_output", "final_output", "audit_report"]:
            yield f"paper.{key}", paper.get(key)

    evidence = config.get("evidence")
    if not isinstance(evidence, dict):
        return

    default_artifacts = evidence.get("default_canonical_artifacts")
    if isinstance(default_artifacts, list):
        for index, path in enumerate(default_artifacts):
            yield f"evidence.default_canonical_artifacts[{index}]", path

    canonical_facts = evidence.get("canonical_facts")
    if not isinstance(canonical_facts, dict):
        return
    for experiment_path, mappings in canonical_facts.items():
        yield "evidence.canonical_facts key", experiment_path
        if not isinstance(mappings, list):
            continue
        for index, mapping in enumerate(mappings):
            if isinstance(mapping, dict):
                yield f"evidence.canonical_facts[{experiment_path!r}][{index}].source", mapping.get(
                    "source"
                )
