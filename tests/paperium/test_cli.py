from paperium.cli import main


def test_help_returns_success(capsys):
    assert main(["--help"]) == 0
    assert "paperium" in capsys.readouterr().out


def test_requires_command(capsys):
    assert main([]) == 0
    assert "usage:" in capsys.readouterr().out


def test_command_surface_lists_v1_commands(capsys):
    assert main(["--help"]) == 0
    output = capsys.readouterr().out
    for command in [
        "init",
        "status",
        "select",
        "analyze",
        "rank",
        "approve",
        "context",
        "section",
        "write",
    ]:
        assert command in output
