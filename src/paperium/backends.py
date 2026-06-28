from __future__ import annotations

import shutil
from dataclasses import dataclass


class BackendError(Exception):
    """Raised when a worker backend cannot be used."""


@dataclass(frozen=True)
class BackendAvailability:
    paths: dict[str, str]
    missing: list[str]

    @property
    def available(self) -> bool:
        return not self.missing


def detect_required_backends() -> BackendAvailability:
    paths = {}
    missing = []

    for backend in ["codex", "claude"]:
        path = shutil.which(backend)
        if path is None:
            missing.append(backend)
        else:
            paths[backend] = path

    return BackendAvailability(paths=paths, missing=missing)


def backend_command(backend: str) -> list[str]:
    if backend == "codex":
        return ["codex", "exec", "-"]
    if backend == "claude":
        return ["claude", "-p"]
    raise BackendError(f"Unknown backend: {backend}")
