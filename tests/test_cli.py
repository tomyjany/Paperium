import subprocess
import sys
from pathlib import Path
import shutil

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PAPER_BUILD_SKILL = PROJECT_ROOT / "skills" / "paper-build" / "SKILL.md"
PAPER_BUILD_WORKFLOW = (
    PROJECT_ROOT / "skills" / "paper-build" / "references" / "milestone-1-workflow.md"
)


def _console_script_command() -> list[str]:
    paperctl = shutil.which("paperctl")
    if paperctl is not None:
        return [paperctl]
    uv = shutil.which("uv")
    if uv is not None:
        return [uv, "run", "--project", str(PROJECT_ROOT), "paperctl"]
    pytest.skip("paperctl console script is not available")


def test_module_entrypoint_shows_help():
    result = subprocess.run(
        [sys.executable, "-m", "paperctl", "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0
    assert "paperctl" in result.stdout


def test_console_script_shows_help():
    result = subprocess.run(
        [*_console_script_command(), "--help"],
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0
    assert "paperctl" in result.stdout


@pytest.mark.parametrize(
    "command",
    ["discover", "inventory", "normalize", "render", "audit", "build"],
)
def test_implemented_commands_report_missing_config_instead_of_placeholder(tmp_path, command):
    result = subprocess.run(
        [sys.executable, "-m", "paperctl", "--repo", str(tmp_path), command],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 2
    assert "missing config file: paper.yaml" in result.stderr
    assert f"command not implemented yet: {command}" not in result.stderr


def test_paper_build_skill_file_has_required_frontmatter():
    text = PAPER_BUILD_SKILL.read_text(encoding="utf-8")

    assert text.startswith("---\n")
    assert "\nname: paper-build\n" in text
    assert "\ndescription: " in text


def test_paper_build_skill_is_explicit_paperctl_wrapper():
    text = PAPER_BUILD_SKILL.read_text(encoding="utf-8")
    lower_text = text.lower()

    assert "use only when explicitly requested" in lower_text
    assert "installed `paperctl` executable" in lower_text
    assert "`paperctl --repo <repository-root> build`" in text
    assert "deterministic pre-analysis evidence draft" in lower_text
    assert "confirm `paper.yaml` exists" in lower_text
    assert "do not manually alter generated artifacts" in lower_text
    assert "milestone 1 never writes `paper.md`" in lower_text


def test_paper_build_skill_avoids_future_analysis_language():
    text = PAPER_BUILD_SKILL.read_text(encoding="utf-8")
    lower_text = text.lower()

    assert "llm" not in lower_text
    assert "subagent" not in lower_text
    assert "promote" not in lower_text
    assert "promotion" not in lower_text


def test_paper_build_workflow_reference_exists_and_is_concise():
    text = PAPER_BUILD_WORKFLOW.read_text(encoding="utf-8")

    assert "paperctl --repo <repository-root> build" in text
    assert "PAPER.draft.md" in text
    assert len(text.splitlines()) <= 80
