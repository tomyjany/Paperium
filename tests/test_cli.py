import subprocess
import sys


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
        ["paperctl", "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0
    assert "paperctl" in result.stdout


def test_placeholder_command_returns_invalid_invocation():
    result = subprocess.run(
        [sys.executable, "-m", "paperctl", "render"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 4
    assert "command not implemented yet: render" in result.stderr
