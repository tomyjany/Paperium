import pytest

from paperium.dispositions import (
    DispositionError,
    render_dispositions_markdown,
    validate_dispositions,
    write_dispositions,
)


def test_render_dispositions_markdown_lists_every_selected_experiment():
    rows = [
        {"path": "experiments/exp-b", "disposition": "excluded", "reason": "baseline only"},
        {"path": "experiments/exp-a", "disposition": "included", "reason": "complete"},
        {"path": "experiments/exp-c", "disposition": "deferred", "reason": "follow-up"},
    ]

    markdown = render_dispositions_markdown(rows)

    assert markdown == (
        "# Paperium Experiment Dispositions\n\n"
        "| Experiment | Disposition | Reason |\n"
        "|---|---|---|\n"
        "| experiments/exp-b | excluded | baseline only |\n"
        "| experiments/exp-a | included | complete |\n"
        "| experiments/exp-c | deferred | follow-up |\n"
    )


def test_validate_dispositions_requires_every_selected_experiment_once():
    rows = [
        {"path": "experiments/exp-a", "disposition": "included", "reason": "complete"},
        {"path": "experiments/exp-b", "disposition": "excluded", "reason": "baseline only"},
        {"path": "experiments/exp-c", "disposition": "deferred", "reason": "follow-up"},
    ]

    assert (
        validate_dispositions(
            ["experiments/exp-a", "experiments/exp-b", "experiments/exp-c"],
            rows,
        )
        == rows
    )


def test_validate_dispositions_rejects_missing_selected_path():
    rows = [
        {"path": "experiments/exp-a", "disposition": "included", "reason": "complete"},
    ]

    with pytest.raises(DispositionError):
        validate_dispositions(["experiments/exp-a", "experiments/exp-b"], rows)


def test_validate_dispositions_rejects_duplicate_row_path():
    rows = [
        {"path": "experiments/exp-a", "disposition": "included", "reason": "complete"},
        {"path": "experiments/exp-a", "disposition": "excluded", "reason": "duplicate"},
    ]

    with pytest.raises(DispositionError):
        validate_dispositions(["experiments/exp-a"], rows)


def test_validate_dispositions_rejects_unselected_row_path():
    rows = [
        {"path": "experiments/exp-b", "disposition": "included", "reason": "unselected"},
    ]

    with pytest.raises(DispositionError):
        validate_dispositions(["experiments/exp-a"], rows)


@pytest.mark.parametrize(
    "disposition",
    [
        "include",
        "excluded ",
        "",
        1,
    ],
)
def test_validate_dispositions_rejects_invalid_disposition(disposition):
    rows = [{"path": "experiments/exp-a", "disposition": disposition, "reason": "complete"}]

    with pytest.raises(DispositionError):
        validate_dispositions(["experiments/exp-a"], rows)


@pytest.mark.parametrize("reason", ["", "   ", "\n\t", 1])
def test_validate_dispositions_rejects_empty_or_non_string_reason(reason):
    rows = [{"path": "experiments/exp-a", "disposition": "included", "reason": reason}]

    with pytest.raises(DispositionError):
        validate_dispositions(["experiments/exp-a"], rows)


@pytest.mark.parametrize(
    "selected_paths",
    [
        "experiments/exp-a",
        [1],
        ["experiments/exp-a", ""],
        ["experiments/exp-a", "experiments/exp-a"],
        object(),
    ],
)
def test_validate_dispositions_rejects_malformed_selected_paths(selected_paths):
    rows = [
        {"path": "experiments/exp-a", "disposition": "included", "reason": "complete"},
    ]

    with pytest.raises(DispositionError):
        validate_dispositions(selected_paths, rows)


@pytest.mark.parametrize(
    "rows",
    [
        None,
        {},
        ["not an object"],
        [{"disposition": "included", "reason": "missing path"}],
        [{"path": "experiments/exp-a", "reason": "missing disposition"}],
        [{"path": "experiments/exp-a", "disposition": "included"}],
        [
            {
                "path": "experiments/exp-a",
                "disposition": "included",
                "reason": "complete",
                "extra": "field",
            }
        ],
        [{"path": "", "disposition": "included", "reason": "complete"}],
        [{"path": 1, "disposition": "included", "reason": "complete"}],
    ],
)
def test_validate_dispositions_rejects_malformed_row_shapes(rows):
    with pytest.raises(DispositionError):
        validate_dispositions(["experiments/exp-a"], rows)


def test_render_dispositions_markdown_escapes_table_cell_content():
    rows = [
        {
            "path": "experiments/exp|a",
            "disposition": "fact_check_failed",
            "reason": "missing\nmetric | conflict",
        }
    ]

    markdown = render_dispositions_markdown(rows)

    assert "| experiments/exp\\|a | fact_check_failed | missing metric \\| conflict |" in markdown


def test_write_dispositions_creates_parent_directory_and_markdown(tmp_path):
    path = tmp_path / ".paperium" / "dispositions.md"
    selected_paths = ["experiments/exp-a"]
    rows = [
        {"path": "experiments/exp-a", "disposition": "included", "reason": "complete"},
    ]

    write_dispositions(path, selected_paths, rows)

    assert path.read_text() == render_dispositions_markdown(rows)
