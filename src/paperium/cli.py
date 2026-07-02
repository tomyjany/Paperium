import argparse
import sys
from pathlib import Path

import paperium.analyze
import paperium.assemble
import paperium.commands
import paperium.output
import paperium.reconcile
import paperium.sections
import paperium.selection
import paperium.templates
from paperium.gitignore import ensure_paperium_gitignore
from paperium.notes import extract_notes
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
    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument("--jobs", type=_positive_int, default=2)
    rank_parser = subparsers.add_parser("rank")
    rank_parser.add_argument("--generate", action="store_true")
    approve_parser = subparsers.add_parser("approve")
    approve_parser.add_argument("artifact", choices=["ranking", "question-focus"])
    context_parser = subparsers.add_parser("context")
    context_subparsers = context_parser.add_subparsers(dest="context_action")
    for action in ("approve", "deny"):
        action_parser = context_subparsers.add_parser(action)
        action_parser.add_argument("request_id")
    section_parser = subparsers.add_parser("section")
    section_subparsers = section_parser.add_subparsers(dest="section_action")
    section_add = section_subparsers.add_parser("add")
    section_add.add_argument("section_id")
    section_add.add_argument("--title", required=True)
    section_add.add_argument("--order", type=int, default=None)
    section_add.add_argument("--break-before", action="store_true", dest="break_before")
    section_subparsers.add_parser("list")
    for name in ("drop", "approve", "notes", "prompt"):
        simple = section_subparsers.add_parser(name)
        simple.add_argument("section_id")
    section_record = section_subparsers.add_parser("record")
    section_record.add_argument("section_id")
    section_record.add_argument("--approve", action="store_true")
    section_run = section_subparsers.add_parser("run")
    section_run.add_argument("section_id")
    section_run.add_argument("--backend", choices=["claude", "codex"], default="claude")
    assemble_parser = subparsers.add_parser("assemble")
    assemble_parser.add_argument("--allow-draft", action="store_true", dest="allow_draft")
    assemble_parser.add_argument("--force", action="store_true")
    reconcile_parser = subparsers.add_parser("reconcile")
    reconcile_parser.add_argument("--fix", action="store_true")
    return parser


def _repo_path(repo_arg: str | None) -> Path:
    return resolve_repo(repo_arg, Path.cwd())


def _state_path(repo: Path) -> Path:
    return repo / ".paperium" / "state.json"


def stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def stdout_is_tty() -> bool:
    return sys.stdout.isatty()


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("jobs must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("jobs must be a positive integer")
    return parsed


def _run_init(repo: Path) -> int:
    if not repo.is_dir():
        print(f"paperium: repository does not exist: {repo}", file=sys.stderr)
        return DETERMINISTIC_FAILURE

    ensure_paperium_gitignore(repo)
    state_path = _state_path(repo)
    if not state_path.exists():
        save_state(state_path, PaperiumState())

    paperium.templates.ensure_scaffolds(repo)

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


def _run_analyze(repo: Path, jobs: int) -> int:
    state_path = _state_path(repo)
    if not state_path.exists():
        print(f"paperium: state file missing: {state_path}", file=sys.stderr)
        return DETERMINISTIC_FAILURE
    try:
        state = load_state(state_path)
    except (OSError, StateError) as exc:
        print(f"paperium: invalid state file {state_path}: {exc}", file=sys.stderr)
        return DETERMINISTIC_FAILURE
    if not state.selected_experiments:
        print("paperium: analyze requires selected experiments in state", file=sys.stderr)
        return DETERMINISTIC_FAILURE

    paperium.output.render_progress(
        state, f"Analyzing {len(state.selected_experiments)} experiments"
    )
    try:
        paperium.analyze.analyze_selected_experiments(repo, state, jobs=jobs)
    except paperium.analyze.AnalyzeError as exc:
        save_state(state_path, state)
        print(f"paperium: analyze failed: {exc}", file=sys.stderr)
        return DETERMINISTIC_FAILURE

    save_state(state_path, state)
    return SUCCESS


def _load_state_for_command(repo: Path) -> tuple[Path, PaperiumState] | int:
    state_path = _state_path(repo)
    if not state_path.exists():
        print(f"paperium: state file missing: {state_path}", file=sys.stderr)
        return DETERMINISTIC_FAILURE
    try:
        return state_path, load_state(state_path)
    except (OSError, StateError) as exc:
        print(f"paperium: invalid state file {state_path}: {exc}", file=sys.stderr)
        return DETERMINISTIC_FAILURE


def _run_rank(repo: Path, *, generate: bool) -> int:
    loaded = _load_state_for_command(repo)
    if isinstance(loaded, int):
        return loaded
    state_path, state = loaded
    try:
        paperium.commands.run_rank(repo, state, generate=generate)
    except paperium.commands.CommandError as exc:
        print(f"paperium: {exc}", file=sys.stderr)
        return DETERMINISTIC_FAILURE
    save_state(state_path, state)
    return SUCCESS


def _run_approve(repo: Path, artifact: str) -> int:
    loaded = _load_state_for_command(repo)
    if isinstance(loaded, int):
        return loaded
    state_path, state = loaded
    try:
        paperium.commands.approve_artifact(repo, state, artifact)
    except paperium.commands.CommandError as exc:
        print(f"paperium: {exc}", file=sys.stderr)
        return DETERMINISTIC_FAILURE
    save_state(state_path, state)
    return SUCCESS


def _run_context(repo: Path, action: str | None, request_id: str | None) -> int:
    if action is None or request_id is None:
        print("paperium: context requires approve|deny and request-id", file=sys.stderr)
        return INVALID_INVOCATION
    loaded = _load_state_for_command(repo)
    if isinstance(loaded, int):
        return loaded
    state_path, state = loaded
    try:
        paperium.commands.decide_context(
            repo,
            state,
            request_id,
            approved=action == "approve",
        )
    except paperium.commands.CommandError as exc:
        print(f"paperium: {exc}", file=sys.stderr)
        return DETERMINISTIC_FAILURE
    save_state(state_path, state)
    return SUCCESS


def _run_section_v2(repo: Path, args: argparse.Namespace) -> int:
    action = args.section_action
    if action is None:
        print("paperium: section requires a subcommand", file=sys.stderr)
        return INVALID_INVOCATION
    loaded = _load_state_for_command(repo)
    if isinstance(loaded, int):
        return loaded
    state_path, state = loaded
    try:
        if action == "add":
            paperium.sections.add_section(
                repo,
                state,
                args.section_id,
                title=args.title,
                order=args.order,
                break_before=args.break_before,
            )
        elif action == "list":
            for section in sorted(state.sections, key=lambda item: (item.order, item.id)):
                print(
                    f"{section.order:>3}  {section.id}  {section.status}"
                    f"  rounds={section.revision_rounds}  {section.title}"
                )
        elif action == "drop":
            paperium.sections.drop_section(state, args.section_id)
        elif action == "approve":
            paperium.sections.approve_section_v2(state, args.section_id)
        elif action == "record":
            paperium.sections.record_section(repo, state, args.section_id, approve=args.approve)
        elif action == "notes":
            section = paperium.sections.find_section(state, args.section_id)
            draft = repo / section.path
            text = draft.read_text(encoding="utf-8") if draft.exists() else ""
            for index, note in enumerate(extract_notes(text), start=1):
                print(f"{index}. {note}")
        elif action == "prompt":
            archive, prompt = paperium.sections.prepare_prompt(repo, state, args.section_id)
            print(prompt)
            print(f"archived: {archive.relative_to(repo).as_posix()}", file=sys.stderr)
        elif action == "run":
            section = paperium.sections.run_section(
                repo, state, args.section_id, backend=args.backend
            )
            if section.last_run_failed is not None:
                save_state(state_path, state)
                print(
                    f"paperium: section run failed: {section.last_run_failed}",
                    file=sys.stderr,
                )
                return DETERMINISTIC_FAILURE
        else:
            print(f"paperium: unknown section action: {action}", file=sys.stderr)
            return INVALID_INVOCATION
    except paperium.sections.SectionError as exc:
        print(f"paperium: {exc}", file=sys.stderr)
        return DETERMINISTIC_FAILURE
    save_state(state_path, state)
    return SUCCESS


def _run_assemble(repo: Path, *, allow_draft: bool, force: bool) -> int:
    loaded = _load_state_for_command(repo)
    if isinstance(loaded, int):
        return loaded
    state_path, state = loaded
    try:
        target = paperium.assemble.assemble_report(
            repo, state, allow_draft=allow_draft, force=force
        )
    except paperium.assemble.AssembleError as exc:
        print(f"paperium: {exc}", file=sys.stderr)
        return DETERMINISTIC_FAILURE
    save_state(state_path, state)
    print(f"Assembled: {target.relative_to(repo).as_posix()}")
    return SUCCESS


def _run_reconcile(repo: Path, *, fix: bool) -> int:
    loaded = _load_state_for_command(repo)
    if isinstance(loaded, int):
        return loaded
    state_path, state = loaded
    drift = paperium.reconcile.reconcile_state(repo, state, fix=fix)
    for message in drift:
        print(message)
    if fix:
        save_state(state_path, state)
    if not drift:
        print("no drift")
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
    if args.command == "analyze":
        return _run_analyze(repo, jobs=args.jobs)
    if args.command == "rank":
        return _run_rank(repo, generate=args.generate)
    if args.command == "approve":
        return _run_approve(repo, args.artifact)
    if args.command == "context":
        return _run_context(repo, args.context_action, getattr(args, "request_id", None))
    if args.command == "section":
        return _run_section_v2(repo, args)
    if args.command == "assemble":
        return _run_assemble(repo, allow_draft=args.allow_draft, force=args.force)
    if args.command == "reconcile":
        return _run_reconcile(repo, fix=args.fix)
    parser.print_help()
    return INVALID_INVOCATION
