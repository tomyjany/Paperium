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


def test_placeholder_command_returns_invalid_invocation_for_unimplemented_commands():
    for command in ["audit", "build"]:
        result = subprocess.run(
            [sys.executable, "-m", "paperctl", command],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert result.returncode == 4
        assert f"command not implemented yet: {command}" in result.stderr


def test_render_command_is_not_placeholder():
    result = subprocess.run(
        [sys.executable, "-m", "paperctl", "render"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert "command not implemented yet: render" not in result.stderr
