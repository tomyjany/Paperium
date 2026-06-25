from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


FIXTURES_DIR = Path(__file__).parent / "fixtures"
MINIMAL_RESEARCH_REPO = FIXTURES_DIR / "minimal-research-repo"


def copy_fixture_repo(tmp_path: Path) -> Path:
    destination = tmp_path / "minimal-research-repo"
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(MINIMAL_RESEARCH_REPO, destination)
    return destination


def init_git_repo(path: Path) -> None:
    subprocess.run(
        ["git", "init"],
        cwd=path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def run_paperctl(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "paperctl", "--repo", str(repo), *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)
