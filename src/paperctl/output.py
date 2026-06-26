from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


def print_build_rich(result: Any) -> None:
    console = Console()
    console.print(Panel.fit("Deterministic pre-analysis evidence draft", title="paperctl build"))

    stages = Table(title="Deterministic Build", show_lines=False)
    stages.add_column("Stage")
    stages.add_column("Status")
    stages.add_column("Details")
    stages.add_row("discovery", _styled_status(result.discovery.status), "")
    stages.add_row(
        "inventory",
        _styled_status("complete"),
        _counts(result.inventory),
    )
    stages.add_row(
        "evidence",
        _styled_status("complete"),
        _counts(result.normalize),
    )
    stages.add_row("render", _styled_status(result.render.status), "")
    stages.add_row("deterministic", _styled_status(result.deterministic_status), "")
    console.print(stages)

    paths = Table(title="Outputs", show_header=False)
    paths.add_column("Output")
    paths.add_column("Path")
    paths.add_row("draft", str(result.draft_path))
    paths.add_row("audit", str(result.audit_path))
    console.print(paths)

    console.print(
        Panel.fit(
            _publication_summary(result.publication_blocker_codes),
            title="Publication",
            border_style="red" if result.publication_blocker_codes else "green",
        )
    )


def print_audit_rich(result: Any) -> None:
    console = Console()
    console.print(Panel.fit(str(result.report_path), title="paperctl audit"))

    statuses = Table(title="Audit Status", show_lines=False)
    statuses.add_column("Gate")
    statuses.add_column("Status")
    statuses.add_column("Details")
    statuses.add_row(
        "Deterministic Health",
        _styled_status(result.deterministic_status),
        "",
    )
    statuses.add_row(
        "Publication Gate",
        _styled_status(result.publication_status),
        f"blockers: {result.blocker_count}",
    )
    statuses.add_row(
        "Publishable", _styled_status("passed" if result.publishable else "blocked"), ""
    )
    console.print(statuses)


def _counts(result: Any) -> str:
    return f"{result.created} created, {result.replaced} replaced, {result.unchanged} unchanged"


def _publication_summary(blocker_codes: list[str]) -> str:
    if not blocker_codes:
        return "[green]passed[/green]"
    return f"[red]blocked[/red] by {', '.join(blocker_codes)}"


def _styled_status(status: str) -> str:
    if status in {"passed", "complete", "created", "wrote"}:
        return f"[green]{status}[/green]"
    if status in {"blocked", "failed"}:
        return f"[red]{status}[/red]"
    if status in {"unchanged"}:
        return f"[blue]{status}[/blue]"
    return status
