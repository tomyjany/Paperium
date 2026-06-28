import json

import pytest

from paperium.ranking import (
    RankingError,
    render_ranking_markdown,
    validate_ranking_entries,
    write_ranking_artifacts,
)


def test_valid_ranking_requires_every_approved_experiment_once():
    entries = [
        {"experiment": "exp1", "bucket": "include", "reason": "best"},
        {"experiment": "exp2", "bucket": "exclude", "reason": "weak evidence"},
        {"experiment": "exp3", "bucket": "defer", "reason": "needs follow-up"},
    ]

    assert validate_ranking_entries({"exp1", "exp2", "exp3"}, entries) == entries


def test_missing_approved_experiment_raises_ranking_error():
    entries = [{"experiment": "exp1", "bucket": "include", "reason": "best"}]

    with pytest.raises(RankingError):
        validate_ranking_entries({"exp1", "exp2"}, entries)


def test_duplicate_approved_experiment_raises_ranking_error():
    entries = [
        {"experiment": "exp1", "bucket": "include", "reason": "best"},
        {"experiment": "exp1", "bucket": "exclude", "reason": "worse duplicate"},
    ]

    with pytest.raises(RankingError):
        validate_ranking_entries({"exp1"}, entries)


@pytest.mark.parametrize(
    "entries",
    [
        [{"experiment": "exp2", "bucket": "include", "reason": "unapproved"}],
        [{"experiment": "exp1", "bucket": "maybe", "reason": "bad bucket"}],
        [{"experiment": "exp1", "bucket": "include", "reason": ""}],
        [{"experiment": "exp1", "bucket": "include", "reason": "   "}],
    ],
)
def test_invalid_ranking_entry_fields_raise_ranking_error(entries):
    with pytest.raises(RankingError):
        validate_ranking_entries({"exp1"}, entries)


@pytest.mark.parametrize(
    "entries",
    [
        None,
        {},
        ["not an object"],
        [{"bucket": "include", "reason": "missing experiment"}],
        [{"experiment": "exp1", "reason": "missing bucket"}],
        [{"experiment": "exp1", "bucket": "include"}],
        [{"experiment": 1, "bucket": "include", "reason": "bad experiment"}],
        [{"experiment": "exp1", "bucket": 1, "reason": "bad bucket"}],
        [{"experiment": "exp1", "bucket": "include", "reason": 1}],
    ],
)
def test_malformed_ranking_entries_raise_ranking_error(entries):
    with pytest.raises(RankingError):
        validate_ranking_entries({"exp1"}, entries)


def test_render_ranking_markdown_has_ordered_bucket_tables():
    entries = [
        {"experiment": "exp3", "bucket": "defer", "reason": "later"},
        {"experiment": "exp1", "bucket": "include", "reason": "best"},
        {"experiment": "exp2", "bucket": "exclude", "reason": "weak"},
    ]

    markdown = render_ranking_markdown(entries)

    assert markdown == (
        "## Include\n\n"
        "| Experiment | Reason |\n"
        "| --- | --- |\n"
        "| exp1 | best |\n\n"
        "## Exclude\n\n"
        "| Experiment | Reason |\n"
        "| --- | --- |\n"
        "| exp2 | weak |\n\n"
        "## Defer\n\n"
        "| Experiment | Reason |\n"
        "| --- | --- |\n"
        "| exp3 | later |\n"
    )


def test_write_ranking_artifacts_creates_markdown_and_json(tmp_path):
    md_path = tmp_path / ".paperium/ranking.md"
    json_path = tmp_path / ".paperium/ranking.json"
    entries = [{"experiment": "exp1", "bucket": "include", "reason": "best"}]

    write_ranking_artifacts(md_path, json_path, entries)

    assert md_path.read_text() == render_ranking_markdown(entries)
    assert json.loads(json_path.read_text()) == {"entries": entries}
    assert json_path.read_text() == json.dumps({"entries": entries}, indent=2, sort_keys=True) + "\n"
