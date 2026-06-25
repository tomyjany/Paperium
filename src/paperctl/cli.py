import argparse
from pathlib import Path
import sys

from paperctl.config import ConfigError, RepoResolutionError, init_repo, load_config, resolve_repo
from paperctl.discovery import DiscoveryError, discover


SUCCESS = 0
DETERMINISTIC_FAILURE = 2
PUBLICATION_BLOCKED = 3
INVALID_INVOCATION = 4
MISSING_DEPENDENCY = 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperctl")
    parser.add_argument("--repo", default=None)
    subparsers = parser.add_subparsers(dest="command", required=False)
    for name in ["init", "discover", "inventory", "normalize", "render", "build"]:
        command = subparsers.add_parser(name)
        command.add_argument("--force", action="store_true")
    audit = subparsers.add_parser("audit")
    audit.add_argument("--stage", choices=["deterministic", "publication"], default=None)
    audit.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return SUCCESS
    try:
        repo = resolve_repo(args.repo, Path.cwd())
    except RepoResolutionError as exc:
        print(f"{parser.prog}: {exc}", file=sys.stderr)
        return INVALID_INVOCATION
    if args.command == "init":
        try:
            result = init_repo(repo, args.force)
        except ConfigError as exc:
            print(f"{parser.prog}: {exc}", file=sys.stderr)
            return DETERMINISTIC_FAILURE
        for path in result.created:
            print(f"created {path}")
        for path in result.replaced:
            print(f"replaced {path}")
        return SUCCESS
    if args.command == "discover":
        try:
            config = load_config(repo)
            result = discover(repo, config, args.force)
        except (ConfigError, DiscoveryError) as exc:
            print(f"{parser.prog}: {exc}", file=sys.stderr)
            return DETERMINISTIC_FAILURE
        print(f"wrote {result.path}")
        print(f"discovered {result.experiment_count} experiments")
        return SUCCESS
    print(f"{parser.prog}: command not implemented yet: {args.command}", file=sys.stderr)
    return INVALID_INVOCATION
