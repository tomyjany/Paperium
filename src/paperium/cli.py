import argparse
import sys
from pathlib import Path

import paperium.selection
from paperium.gitignore import ensure_paperium_gitignore
from paperium.output import format_status_plain
from paperium.paths import PaperiumPaths
from paperium.repo import RepoError, resolve_repo
from paperium.selection import SelectionError
from paperium.state import PaperiumState, SelectedExperiment, StateError, load_state, save_state

SUCCESS = 0
INVALID_INVOCATION = 4
DETERMINISTIC_FAILURE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperium")
    parser.add_argument("--repo", default=None, help="Target research repository")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("init")
    subparsers.add_parser("status")
    select_parser = subparsers.add_parser("select")
    select_parser.add_argument("experiment_paths", nargs="*")
    select_parser.add_argument("--experiments-menu", action="store_true")
    subparsers.add_parser("analyze")
    subparsers.add_parser("rank")
    subparsers.add_parser("approve")
    subparsers.add_parser("context")
    subparsers.add_parser("section")
    subparsers.add_parser("write")
    return parser


def _repo_path(repo_arg: str | None) -> Path:
    return resolve_repo(repo_arg, Path.cwd())


def _state_path(repo: Path) -> Path:
    return repo / ".paperium" / "state.json"


def stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def stdout_is_tty() -> bool:
    return sys.stdout.isatty()


def _run_init(repo: Path) -> int:
    if not repo.is_dir():
        print(f"paperium: repository does not exist: {repo}", file=sys.stderr)
        return DETERMINISTIC_FAILURE

    ensure_paperium_gitignore(repo)
    state_path = _state_path(repo)
    if not state_path.exists():
        save_state(state_path, PaperiumState())

    print(f"Repository: {repo}")
    print(f"State: {state_path}")
    print(f"Gitignore: {repo / '.gitignore'}")
    return SUCCESS


def _run_status(repo: Path) -> int:
    state_path = _state_path(repo)
    if not state_path.exists():
        print(f"paperium: state file missing: {state_path}", file=sys.stderr)
        return DETERMINISTIC_FAILURE
    try:
        state = load_state(state_path)
    except (OSError, StateError) as exc:
        print(f"paperium: invalid state file {state_path}: {exc}", file=sys.stderr)
        return DETERMINISTIC_FAILURE

    print(format_status_plain(state))
    return SUCCESS


def _run_select(
    repo: Path,
    experiment_paths: list[str],
    *,
    experiments_menu: bool,
) -> int:
    if experiments_menu and experiment_paths:
        print(
            "paperium: --experiments-menu is not allowed with argument experiment_paths",
            file=sys.stderr,
        )
        return INVALID_INVOCATION

    if experiments_menu and (not stdin_is_tty() or not stdout_is_tty()):
        print("paperium: interactive experiment selection requires a TTY", file=sys.stderr)
        return INVALID_INVOCATION
    if not experiments_menu and not experiment_paths:
        print("paperium: select requires at least one experiment path", file=sys.stderr)
        return INVALID_INVOCATION

    state_path = _state_path(repo)
    if not state_path.exists():
        print(f"paperium: state file missing: {state_path}", file=sys.stderr)
        return DETERMINISTIC_FAILURE
    try:
        state = load_state(state_path)
    except (OSError, StateError) as exc:
        print(f"paperium: invalid state file {state_path}: {exc}", file=sys.stderr)
        return DETERMINISTIC_FAILURE

    try:
        if experiments_menu:
            experiments = paperium.selection.choose_experiments_menu(repo)
        else:
            experiments = paperium.selection.validate_manual_experiments(repo, experiment_paths)
        state.selected_experiments = [
            _selected_experiment_from_path(repo, experiment) for experiment in experiments
        ]
    except (OSError, SelectionError, ValueError) as exc:
        print(f"paperium: {exc}", file=sys.stderr)
        return DETERMINISTIC_FAILURE

    state.phase = "analyzing"
    save_state(state_path, state)
    print(f"Selected experiments: {len(state.selected_experiments)}")
    return SUCCESS


def _selected_experiment_from_path(repo: Path, experiment: Path) -> SelectedExperiment:
    paths = PaperiumPaths(repo)
    experiment = experiment.resolve()
    relative_experiment = _repo_relative(repo, experiment)
    question_readme = paperium.selection.resolve_question_readme(repo, experiment)
    relative_question_readme = (
        _repo_relative(repo, question_readme) if question_readme is not None else None
    )
    return SelectedExperiment(
        path=relative_experiment,
        question_readme=relative_question_readme,
        analysis_path=_repo_relative(repo, paths.experiment_analysis_path(experiment)),
        fact_check_result_path=_repo_relative(repo, paths.experiment_fact_check_path(experiment)),
        disposition=None,
    )


def _repo_relative(repo: Path, path: Path) -> str:
    return path.resolve().relative_to(repo.resolve()).as_posix()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = int(exc.code)
        return SUCCESS if code == SUCCESS else INVALID_INVOCATION
    if args.command is None:
        parser.print_help()
        return SUCCESS
    try:
        repo = _repo_path(args.repo)
    except RepoError as exc:
        print(f"paperium: {exc}", file=sys.stderr)
        return DETERMINISTIC_FAILURE
    if args.command == "init":
        return _run_init(repo)
    if args.command == "status":
        return _run_status(repo)
    if args.command == "select":
        return _run_select(
            repo,
            args.experiment_paths,
            experiments_menu=args.experiments_menu,
        )
    print(f"{parser.prog}: command not implemented yet: {args.command}", file=sys.stderr)
    return INVALID_INVOCATION
