import argparse
from pathlib import Path
import sys

from paperctl.audit import AuditError, audit
from paperctl.build import BuildError, build
from paperctl.config import ConfigError, RepoResolutionError, init_repo, load_config, resolve_repo
from paperctl.discovery import DiscoveryError, discover
from paperctl.inventory import InventoryError, inventory_all, load_manifest
from paperctl.normalize import NormalizeError, normalize_all
from paperctl.output import print_audit_rich, print_build_rich
from paperctl.rendering import RenderError, render


SUCCESS = 0
DETERMINISTIC_FAILURE = 2
PUBLICATION_BLOCKED = 3
INVALID_INVOCATION = 4
MISSING_DEPENDENCY = 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperctl")
    parser.add_argument("--repo", default=None)
    parser.add_argument("--plain", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=False)
    for name in ["init", "discover", "inventory", "normalize", "render", "build"]:
        command = subparsers.add_parser(name)
        command.add_argument("--force", action="store_true")
        command.add_argument("--plain", action="store_true", default=argparse.SUPPRESS)
    audit = subparsers.add_parser("audit")
    audit.add_argument("--stage", choices=["deterministic", "publication"], default=None)
    audit.add_argument("--force", action="store_true")
    audit.add_argument("--plain", action="store_true", default=argparse.SUPPRESS)
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
    if args.command == "build":
        try:
            config = load_config(repo)
            result = build(repo, config, args.force)
        except (ConfigError, BuildError) as exc:
            print(f"{parser.prog}: {exc}", file=sys.stderr)
            return DETERMINISTIC_FAILURE
        if _use_rich(args):
            print_build_rich(result)
            return SUCCESS
        print(f"discovery: {result.discovery.status}")
        print(
            f"inventory: {result.inventory.created} created, "
            f"{result.inventory.replaced} replaced, {result.inventory.unchanged} unchanged"
        )
        print(
            f"evidence: {result.normalize.created} created, "
            f"{result.normalize.replaced} replaced, {result.normalize.unchanged} unchanged"
        )
        print(f"render: {result.render.status}")
        print(f"deterministic build: {result.deterministic_status}")
        print(f"draft: {result.draft_path}")
        print(f"audit: {result.audit_path}")
        print(f"publication: {_publication_summary(result.publication_blocker_codes)}")
        return SUCCESS
    if args.command == "audit":
        try:
            config = load_config(repo)
            stage = args.stage or config["audit"]["default_stage"]
            result = audit(repo, config, stage, force=args.force)
        except (ConfigError, AuditError) as exc:
            print(f"{parser.prog}: {exc}", file=sys.stderr)
            return DETERMINISTIC_FAILURE
        if _use_rich(args):
            print_audit_rich(result)
            return _audit_exit_code(parser.prog, result)
        print(f"{result.write_status} {result.report_path}")
        print(f"deterministic: {result.deterministic_status}")
        print(f"publication: {result.publication_status}")
        print(f"publication blockers: {result.blocker_count}")
        print(f"publishable: {str(result.publishable).lower()}")
        return _audit_exit_code(parser.prog, result)
    print(f"{parser.prog}: command not implemented yet: {args.command}", file=sys.stderr)
    return INVALID_INVOCATION


def _publication_summary(blocker_codes: list[str]) -> str:
    if not blocker_codes:
        return "passed"
    return f"blocked by {', '.join(blocker_codes)}"


def _use_rich(args: argparse.Namespace) -> bool:
    return not args.plain and sys.stdout.isatty()


def _audit_exit_code(prog: str, result) -> int:
    if result.deterministic_status != "passed":
        print(
            f"{prog}: deterministic audit failed: {', '.join(result.issue_codes)}",
            file=sys.stderr,
        )
        return DETERMINISTIC_FAILURE
    if result.stage == "publication" and result.publication_status != "passed":
        return PUBLICATION_BLOCKED
    return SUCCESS
