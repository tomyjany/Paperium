import argparse


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
    parser.error(f"command not implemented yet: {args.command}")
    return INVALID_INVOCATION
