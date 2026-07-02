from __future__ import annotations

import sys
from typing import TextIO

from paperium.state import PaperiumState


def _status_counts(state: PaperiumState) -> tuple[int, int, int, int, int]:
    selected_count = len(state.selected_experiments)
    running_count = sum(worker.status == "running" for worker in state.workers)
    failed_count = sum(worker.status == "failed" for worker in state.workers)
    needs_context_count = sum(worker.status == "needs_context" for worker in state.workers)
    issue_count = sum(
        experiment.status in {"failed", "needs_human_review"}
        for experiment in state.selected_experiments
    )
    return selected_count, running_count, failed_count, needs_context_count, issue_count


def format_status_plain(state: PaperiumState) -> str:
    selected_count, running_count, failed_count, needs_context_count, issue_count = _status_counts(
        state
    )
    return "\n".join(
        [
            f"Phase: {state.phase}",
            f"Selected experiments: {selected_count}",
            (
                "Workers: "
                f"{running_count} running, "
                f"{failed_count} failed, "
                f"{needs_context_count} waiting for user"
            ),
            f"Experiment issues: {issue_count}",
        ]
    )


def render_progress(state: PaperiumState, message: str) -> None:
    print(message)


def print_status_rich(state: PaperiumState, file: TextIO | None = None) -> None:
    output = file if file is not None else sys.stdout
    if not output.isatty():
        print(format_status_plain(state), file=output)
        return

    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
    except ImportError:
        print(format_status_plain(state), file=output)
        return

    selected_count, running_count, failed_count, needs_context_count, issue_count = _status_counts(
        state
    )
    table = Table(show_header=False)
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Phase", state.phase)
    table.add_row("Selected experiments", str(selected_count))
    table.add_row(
        "Workers",
        f"{running_count} running, {failed_count} failed, {needs_context_count} waiting for user",
    )
    table.add_row("Experiment issues", str(issue_count))

    console = Console(file=output)
    console.print(Panel(table, title="Paperium Status"))
