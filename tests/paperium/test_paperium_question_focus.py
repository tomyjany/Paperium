import pytest

from paperium.question_focus import (
    QuestionFocusError,
    render_question_focus_markdown,
    validate_question_focus,
    write_question_focus,
)


def test_render_question_focus_markdown_groups_included_experiments():
    entries = [
        {
            "question_path": "questions/q001",
            "included_experiments": [
                "questions/q001/experiments/exp001",
                "questions/q001/experiments/exp002",
            ],
            "answer_focus": "Best tested OCR throughput setting",
        },
        {
            "question_path": "questions/q002",
            "included_experiments": ["questions/q002/experiments/exp001"],
            "answer_focus": "Most reliable parser",
        },
    ]

    markdown = render_question_focus_markdown(entries)

    assert markdown == (
        "# Paperium Question Focus\n\n"
        "## questions/q001\n\n"
        "- Answer focus: Best tested OCR throughput setting\n"
        "- Included experiments:\n"
        "  - questions/q001/experiments/exp001\n"
        "  - questions/q001/experiments/exp002\n\n"
        "## questions/q002\n\n"
        "- Answer focus: Most reliable parser\n"
        "- Included experiments:\n"
        "  - questions/q002/experiments/exp001\n"
    )


def test_validate_question_focus_accepts_approved_included_experiments():
    entries = [
        {
            "question_path": "questions/q001",
            "included_experiments": ["questions/q001/experiments/exp001"],
            "answer_focus": "Best tested OCR throughput setting",
        },
        {
            "question_path": "questions/q002",
            "included_experiments": ["questions/q002/experiments/exp001"],
            "answer_focus": "Most reliable parser",
        },
    ]

    assert (
        validate_question_focus(
            [
                "questions/q001/experiments/exp001",
                "questions/q002/experiments/exp001",
            ],
            entries,
        )
        == entries
    )


def test_validate_question_focus_rejects_missing_approved_experiment():
    entries = [
        {
            "question_path": "questions/q001",
            "included_experiments": ["questions/q001/experiments/exp001"],
            "answer_focus": "Best tested OCR throughput setting",
        },
    ]

    with pytest.raises(QuestionFocusError):
        validate_question_focus(
            [
                "questions/q001/experiments/exp001",
                "questions/q001/experiments/exp002",
            ],
            entries,
        )


def test_validate_question_focus_rejects_duplicate_included_experiment_within_entry():
    entries = [
        {
            "question_path": "questions/q001",
            "included_experiments": [
                "questions/q001/experiments/exp001",
                "questions/q001/experiments/exp001",
            ],
            "answer_focus": "Best tested OCR throughput setting",
        },
    ]

    with pytest.raises(QuestionFocusError):
        validate_question_focus(["questions/q001/experiments/exp001"], entries)


def test_validate_question_focus_rejects_duplicate_included_experiment_across_entries():
    entries = [
        {
            "question_path": "questions/q001",
            "included_experiments": ["questions/q001/experiments/exp001"],
            "answer_focus": "Best tested OCR throughput setting",
        },
        {
            "question_path": "questions/q001",
            "included_experiments": ["questions/q001/experiments/exp001"],
            "answer_focus": "Duplicate focus",
        },
    ]

    with pytest.raises(QuestionFocusError):
        validate_question_focus(["questions/q001/experiments/exp001"], entries)


def test_validate_question_focus_rejects_unapproved_experiment():
    entries = [
        {
            "question_path": "questions/q001",
            "included_experiments": ["questions/q001/experiments/exp002"],
            "answer_focus": "Best tested OCR throughput setting",
        },
    ]

    with pytest.raises(QuestionFocusError):
        validate_question_focus(["questions/q001/experiments/exp001"], entries)


def test_validate_question_focus_rejects_wrong_question_folder_mapping():
    entries = [
        {
            "question_path": "questions/q002",
            "included_experiments": ["questions/q001/experiments/exp001"],
            "answer_focus": "Best tested OCR throughput setting",
        },
    ]

    with pytest.raises(QuestionFocusError):
        validate_question_focus(["questions/q001/experiments/exp001"], entries)


def test_validate_question_focus_rejects_experiment_paths_that_are_not_mappable():
    entries = [
        {
            "question_path": "questions/q001",
            "included_experiments": ["questions/q001/exp001"],
            "answer_focus": "Best tested OCR throughput setting",
        },
    ]

    with pytest.raises(QuestionFocusError):
        validate_question_focus(["questions/q001/exp001"], entries)


@pytest.mark.parametrize(
    "entries",
    [
        None,
        {},
        ["not an object"],
        [
            {
                "included_experiments": ["questions/q001/experiments/exp001"],
                "answer_focus": "Missing question path",
            }
        ],
        [
            {
                "question_path": "questions/q001",
                "answer_focus": "Missing included experiments",
            }
        ],
        [
            {
                "question_path": "questions/q001",
                "included_experiments": ["questions/q001/experiments/exp001"],
            }
        ],
        [
            {
                "question_path": "questions/q001",
                "included_experiments": ["questions/q001/experiments/exp001"],
                "answer_focus": "Best tested OCR throughput setting",
                "extra": "field",
            }
        ],
        [
            {
                "question_path": 1,
                "included_experiments": ["questions/q001/experiments/exp001"],
                "answer_focus": "Best tested OCR throughput setting",
            }
        ],
        [
            {
                "question_path": "questions/q001",
                "included_experiments": (("questions/q001/experiments/exp001",)),
                "answer_focus": "Best tested OCR throughput setting",
            }
        ],
        [
            {
                "question_path": "questions/q001",
                "included_experiments": [],
                "answer_focus": "Best tested OCR throughput setting",
            }
        ],
        [
            {
                "question_path": "questions/q001",
                "included_experiments": [""],
                "answer_focus": "Best tested OCR throughput setting",
            }
        ],
        [
            {
                "question_path": "questions/q001",
                "included_experiments": [1],
                "answer_focus": "Best tested OCR throughput setting",
            }
        ],
    ],
)
def test_validate_question_focus_rejects_malformed_entry_shapes(entries):
    with pytest.raises(QuestionFocusError):
        validate_question_focus(["questions/q001/experiments/exp001"], entries)


@pytest.mark.parametrize(
    "approved_included_experiments",
    [
        "questions/q001/experiments/exp001",
        [1],
        [""],
        ["questions/q001/experiments/exp001", "questions/q001/experiments/exp001"],
        object(),
    ],
)
def test_validate_question_focus_rejects_malformed_approved_inputs(
    approved_included_experiments,
):
    entries = [
        {
            "question_path": "questions/q001",
            "included_experiments": ["questions/q001/experiments/exp001"],
            "answer_focus": "Best tested OCR throughput setting",
        },
    ]

    with pytest.raises(QuestionFocusError):
        validate_question_focus(approved_included_experiments, entries)


@pytest.mark.parametrize("question_path", ["", "   "])
def test_validate_question_focus_rejects_empty_question_path(question_path):
    entries = [
        {
            "question_path": question_path,
            "included_experiments": ["questions/q001/experiments/exp001"],
            "answer_focus": "Best tested OCR throughput setting",
        },
    ]

    with pytest.raises(QuestionFocusError):
        validate_question_focus(["questions/q001/experiments/exp001"], entries)


@pytest.mark.parametrize("answer_focus", ["", "   ", "\n\t"])
def test_validate_question_focus_rejects_empty_answer_focus(answer_focus):
    entries = [
        {
            "question_path": "questions/q001",
            "included_experiments": ["questions/q001/experiments/exp001"],
            "answer_focus": answer_focus,
        },
    ]

    with pytest.raises(QuestionFocusError):
        validate_question_focus(["questions/q001/experiments/exp001"], entries)


def test_render_question_focus_markdown_normalizes_newlines():
    entries = [
        {
            "question_path": "questions/q001\n# injected",
            "included_experiments": ["questions/q001/experiments/exp001\n- injected"],
            "answer_focus": "Best tested\n- injected",
        },
    ]

    markdown = render_question_focus_markdown(entries)

    assert markdown == (
        "# Paperium Question Focus\n\n"
        "## questions/q001 # injected\n\n"
        "- Answer focus: Best tested - injected\n"
        "- Included experiments:\n"
        "  - questions/q001/experiments/exp001 - injected\n"
    )


def test_write_question_focus_creates_parent_directory_and_markdown(tmp_path):
    path = tmp_path / ".paperium" / "question-focus.md"
    approved = ["questions/q001/experiments/exp001"]
    entries = [
        {
            "question_path": "questions/q001",
            "included_experiments": ["questions/q001/experiments/exp001"],
            "answer_focus": "Best tested OCR throughput setting",
        },
    ]

    write_question_focus(path, approved, entries)

    assert path.read_text() == render_question_focus_markdown(entries)
