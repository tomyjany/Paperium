import argparse
from pathlib import Path
import sys

from paperctl.audit import AuditError, audit
from paperctl.config import ConfigError, RepoResolutionError, init_repo, load_config, resolve_repo
from paperctl.discovery import DiscoveryError, discover
from paperctl.inventory import InventoryError, inventory_all, load_manifest
from paperctl.normalize import NormalizeError, normalize_all
from paperctl.rendering import RenderError, render


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
    if args.command == "inventory":
        try:
            config = load_config(repo)
            manifest = load_manifest(repo, config)
            result = inventory_all(repo, config, manifest, args.force)
        except (ConfigError, InventoryError) as exc:
            print(f"{parser.prog}: {exc}", file=sys.stderr)
            return DETERMINISTIC_FAILURE
        print(f"read {result.manifest_path}")
        print(f"inventoried {result.experiment_count} experiments")
        print(
            f"inventory artifacts: {result.created} created, "
            f"{result.replaced} replaced, {result.unchanged} unchanged"
        )
        return SUCCESS
    if args.command == "normalize":
        try:
            config = load_config(repo)
            result = normalize_all(repo, config, args.force)
        except (ConfigError, NormalizeError) as exc:
            print(f"{parser.prog}: {exc}", file=sys.stderr)
            return DETERMINISTIC_FAILURE
        print(f"read {result.manifest_path}")
        print(f"normalized {result.experiment_count} experiments")
        print(
            f"evidence packets: {result.created} created, "
            f"{result.replaced} replaced, {result.unchanged} unchanged"
        )
        return SUCCESS
    if args.command == "render":
        try:
            config = load_config(repo)
            result = render(repo, config, args.force)
        except (ConfigError, RenderError) as exc:
            print(f"{parser.prog}: {exc}", file=sys.stderr)
            return DETERMINISTIC_FAILURE
        verb = "unchanged" if result.status == "unchanged" else "wrote"
        print(f"{verb} {result.draft_path}")
        print(f"{verb} {result.render_state_path}")
        print(f"rendered {result.experiment_count} experiments")
        print(f"known publication blockers: {result.blocker_count}")
        print("Milestone 1 render never writes PAPER.md")
        return SUCCESS
    if args.command == "audit":
        try:
            config = load_config(repo)
            stage = args.stage or config["audit"]["default_stage"]
            result = audit(repo, config, stage)
        except (ConfigError, AuditError) as exc:
            print(f"{parser.prog}: {exc}", file=sys.stderr)
            return DETERMINISTIC_FAILURE
        print(f"wrote {result.report_path}")
        print(f"deterministic: {result.deterministic_status}")
        print(f"publication: {result.publication_status}")
        print(f"publication blockers: {result.blocker_count}")
        print(f"publishable: {str(result.publishable).lower()}")
        if result.deterministic_status != "passed":
            print(
                f"{parser.prog}: deterministic audit failed: {', '.join(result.issue_codes)}",
                file=sys.stderr,
            )
            return DETERMINISTIC_FAILURE
        if result.stage == "publication" and result.publication_status != "passed":
            return PUBLICATION_BLOCKED
        return SUCCESS
    print(f"{parser.prog}: command not implemented yet: {args.command}", file=sys.stderr)
    return INVALID_INVOCATION
