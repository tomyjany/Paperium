from paperium.notes import extract_notes


def test_extracts_simple_note():
    assert extract_notes("Text /remove this sentence/ more text") == ["remove this sentence"]


def test_extracts_multiple_notes_in_order():
    text = "A /first note here/ B\nrow | cell /second note too/ |\n"
    assert extract_notes(text) == ["first note here", "second note too"]


def test_ignores_paths_and_slashes_without_spaces():
    text = "See questions/q001/experiments/exp001 and a/b pairs."
    assert extract_notes(text) == []


def test_ignores_two_paths_in_one_line():
    assert extract_notes("compare experiments/exp001 and experiments/exp002 daily") == []


def test_note_inside_table_cell():
    text = "| Nastavení | HPI /remove that it was already mentioned/ | Výsledek |"
    assert extract_notes(text) == ["remove that it was already mentioned"]


def test_no_notes_returns_empty():
    assert extract_notes("Plain text without any markers.") == []


def test_unterminated_marker_is_not_a_note():
    assert extract_notes("Broken /note without closing slash") == []
