import argparse

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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    if args.command is None:
        parser.print_help()
        return SUCCESS
    print(f"{parser.prog}: command not implemented yet: {args.command}")
    return INVALID_INVOCATION
