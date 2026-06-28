from paperium.writing import can_write_paper, render_paper


def approved_section(**overrides):
    section = {
        "status": "approved",
        "factual_review_status": "passed",
        "factual_review_result_path": "reviews/intro.json",
        "path": "sections/intro.md",
    }
    section.update(overrides)
    return section


def test_cannot_write_until_sections_approved():
    sections = [
        {
            "status": "drafted",
            "factual_review_status": "passed",
            "factual_review_result_path": "reviews/intro.json",
            "path": "sections/intro.md",
        }
    ]

    assert can_write_paper(sections, final_write_status="ready") is False


def test_can_write_when_non_skipped_sections_approved_and_final_status_ready():
    assert can_write_paper([approved_section()], final_write_status="ready") is True


def test_empty_section_list_and_final_status_not_ready_cannot_write():
    assert can_write_paper([], final_write_status="ready") is False
    assert can_write_paper([approved_section()], final_write_status="not_started") is False


def test_all_skipped_sections_cannot_write():
    assert can_write_paper([{"status": "skipped"}], final_write_status="ready") is False


def test_skipped_sections_alongside_approved_do_not_block_write():
    sections = [
        {"status": "skipped"},
        approved_section(path="sections/methods.md"),
    ]

    assert can_write_paper(sections, final_write_status="ready") is True


def test_approved_section_without_passed_factual_review_cannot_write():
    sections = [approved_section(factual_review_status="failed")]

    assert can_write_paper(sections, final_write_status="ready") is False


def test_approved_section_without_review_result_path_cannot_write():
    sections = [approved_section(factual_review_result_path="")]

    assert can_write_paper(sections, final_write_status="ready") is False


def test_malformed_section_entries_and_paths_cannot_write():
    assert can_write_paper(["not a dict"], final_write_status="ready") is False
    assert can_write_paper([approved_section(path="")], final_write_status="ready") is False


def test_render_paper_concatenates_one_section(tmp_path):
    section_path = tmp_path / "intro.md"
    section_path.write_text("# Intro\n\nBody\n\n", encoding="utf-8")

    assert render_paper([section_path]) == "# Intro\n\nBody\n"


def test_render_paper_uses_exactly_one_blank_line_between_sections(tmp_path):
    intro_path = tmp_path / "intro.md"
    methods_path = tmp_path / "methods.md"
    intro_path.write_text("# Intro\n\nBody\n\n", encoding="utf-8")
    methods_path.write_text("# Methods\n\nSteps   \n\n\n", encoding="utf-8")

    assert render_paper([str(intro_path), methods_path]) == (
        "# Intro\n\nBody\n\n# Methods\n\nSteps\n"
    )


def test_render_paper_empty_list_returns_empty_string():
    assert render_paper([]) == ""
