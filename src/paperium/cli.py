import argparse
import sys
from pathlib import Path

from paperium.gitignore import ensure_paperium_gitignore
from paperium.output import format_status_plain
from paperium.repo import RepoError, resolve_repo
from paperium.state import PaperiumState, StateError, load_state, save_state

SUCCESS = 0
INVALID_INVOCATION = 4
DETERMINISTIC_FAILURE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperium")
    parser.add_argument("--repo", default=None, help="Target research repository")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("init")
    subparsers.add_parser("status")
    subparsers.add_parser("select")
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
    print(f"{parser.prog}: command not implemented yet: {args.command}", file=sys.stderr)
    return INVALID_INVOCATION
