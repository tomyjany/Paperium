from __future__ import annotations

from collections import Counter
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table


_TOKEN_KEYS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


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


def print_analyze_plain(result: Any) -> None:
    for index, item in enumerate(result.items):
        if index:
            print()
        print(f"experiment: {item.experiment_path}")
        print(f"status: {item.status.value}")
        print(f"analysis: {item.analysis_path or 'none'}")
        print(f"diagnostics: {_diagnostic_summary(item.diagnostic_codes)}")
        if item.token_usage:
            print(f"tokens: {_token_summary(item.token_usage)}")
    print()
    print(f"counts: {_count_summary(result.counts)}")
    if _has_tokens(result.token_totals):
        print(f"token totals: {_token_summary(result.token_totals)}")


def print_analyze_rich(result: Any) -> None:
    console = Console()
    console.print(Panel.fit("Batch experiment analysis", title="paperctl analyze"))
    for item in result.items:
        console.print(f"experiment: {item.experiment_path}")
    console.print(_analyze_table(result.items, title="Batch Analysis"))

    counts = Table(title="Counts", show_header=False)
    counts.add_column("Status")
    counts.add_column("Count")
    for key in ("selected", "skipped", "accepted", "failed", "blocked", "not_started"):
        counts.add_row(key, str(result.counts.get(key, 0)))
    console.print(counts)

    if _has_tokens(result.token_totals):
        tokens = Table(title="Token Totals", show_header=False)
        tokens.add_column("Token")
        tokens.add_column("Count")
        for key in _TOKEN_KEYS:
            if key in result.token_totals:
                tokens.add_row(key, str(result.token_totals[key]))
        console.print(tokens)


class RichAnalyzeProgressReporter:
    def __init__(self) -> None:
        self._console = Console()
        self._progress = Progress(
            TextColumn("[bold]Analyzing experiments"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total} done"),
            TimeElapsedColumn(),
            console=self._console,
        )
        self._task_id = self._progress.add_task("Analyzing experiments", total=0)
        self._items: dict[str, Any] = {}
        self._live = Live(
            self._renderable(),
            console=self._console,
            refresh_per_second=8,
            transient=False,
        )
        self._live.start()

    def on_update(self, item: Any) -> None:
        self._items[item.experiment_path] = item
        self._live.update(self._renderable(), refresh=True)

    def close(self) -> None:
        self._live.stop()

    def _renderable(self) -> Group:
        self._sync_progress()
        return Group(
            Panel(self._summary_text(), title="paperctl analyze"),
            self._progress,
            self._progress_table(),
        )

    def _sync_progress(self) -> None:
        total = len(self._items)
        completed = sum(
            1
            for item in self._items.values()
            if item.status.value
            in {"skipped", "accepted", "failed", "blocked", "not_started"}
        )
        self._progress.update(self._task_id, total=total, completed=completed)

    def _summary_text(self) -> str:
        if not self._items:
            return "Preparing analysis batch..."
        counts = Counter(item.status.value for item in self._items.values())
        finished = sum(
            counts[status]
            for status in ("skipped", "accepted", "failed", "blocked", "not_started")
        )
        parts = [
            f"selected={len(self._items)}",
            f"queued={counts['queued']}",
            f"running={counts['running']}",
            f"done={finished}",
        ]
        running = [
            item.experiment_path
            for item in self._items.values()
            if item.status.value == "running"
        ]
        if running:
            parts.append("running_now=" + ", ".join(running))
        return " ".join(parts)

    def _progress_table(self) -> Table:
        return _analyze_table(self._items.values(), title="Analyze Progress")


def _counts(result: Any) -> str:
    return f"{result.created} created, {result.replaced} replaced, {result.unchanged} unchanged"


def _publication_summary(blocker_codes: list[str]) -> str:
    if not blocker_codes:
        return "[green]passed[/green]"
    return f"[red]blocked[/red] by {', '.join(blocker_codes)}"


def _styled_status(status: str) -> str:
    if status in {"passed", "complete", "created", "wrote", "accepted"}:
        return f"[green]{status}[/green]"
    if status in {"blocked", "failed", "not_started"}:
        return f"[red]{status}[/red]"
    if status in {"unchanged", "skipped"}:
        return f"[blue]{status}[/blue]"
    if status in {"queued", "running"}:
        return f"[yellow]{status}[/yellow]"
    return status


def _analyze_table(items: Any, *, title: str) -> Table:
    table = Table(title=title, show_lines=False)
    table.add_column("Experiment", overflow="fold")
    table.add_column("Status")
    table.add_column("Analysis")
    table.add_column("Diagnostics")
    table.add_column("Tokens")
    for item in items:
        table.add_row(
            item.experiment_path,
            _styled_status(item.status.value),
            item.analysis_path or "none",
            _diagnostic_summary(item.diagnostic_codes),
            _token_summary(item.token_usage) if item.token_usage else "",
        )
    return table


def _diagnostic_summary(codes: list[str]) -> str:
    if not codes:
        return "none"
    return ", ".join(codes)


def _count_summary(counts: dict[str, int]) -> str:
    return " ".join(
        f"{key}={counts.get(key, 0)}"
        for key in ("selected", "skipped", "accepted", "failed", "blocked", "not_started")
    )


def _token_summary(tokens: dict[str, int]) -> str:
    return " ".join(f"{key}={tokens[key]}" for key in _TOKEN_KEYS if key in tokens)


def _has_tokens(tokens: dict[str, int]) -> bool:
    return any(tokens.get(key, 0) > 0 for key in _TOKEN_KEYS)
