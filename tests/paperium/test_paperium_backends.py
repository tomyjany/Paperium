import pytest

from paperium.backends import BackendError, backend_command, detect_required_backends


def test_detects_missing_backend(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = detect_required_backends()
    assert not result.available
    assert "codex" in result.missing
    assert "claude" in result.missing


def test_detects_available_backends(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    result = detect_required_backends()
    assert result.available
    assert result.paths["codex"] == "/usr/bin/codex"
    assert result.paths["claude"] == "/usr/bin/claude"


def test_backend_command_uses_stdin_prompt_transport():
    assert backend_command("codex") == ["codex", "exec", "-"]
    assert backend_command("claude") == ["claude", "-p"]


def test_backend_command_rejects_unknown_backend():
    with pytest.raises(BackendError):
        backend_command("other")
