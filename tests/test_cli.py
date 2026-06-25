import subprocess
import sys
from pathlib import Path
import shutil

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
