from pathlib import Path


def can_write_paper(sections, final_write_status="not_started") -> bool:
    if final_write_status != "ready":
        return False

    has_writable_section = False
    try:
        iterator = iter(sections)
    except TypeError:
        return False

    for section in iterator:
        if not isinstance(section, dict):
            return False

        status = section.get("status")
        if status == "skipped":
            continue
        if status != "approved":
            return False
        if section.get("factual_review_status") != "passed":
            return False
        if not _is_non_blank_string(section.get("factual_review_result_path")):
            return False
        if not _is_non_blank_string(section.get("path")):
            return False

        has_writable_section = True

    return has_writable_section


def render_paper(paths) -> str:
    sections = [Path(path).read_text(encoding="utf-8").rstrip() for path in paths]
    if not sections:
        return ""
    return "\n\n".join(sections) + "\n"


def _is_non_blank_string(value) -> bool:
    return isinstance(value, str) and bool(value.strip())
