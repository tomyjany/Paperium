from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .jsonio import dump_json_bytes


def sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def canonical_json_hash(obj: Any) -> str:
    return sha256_bytes(dump_json_bytes(obj))
