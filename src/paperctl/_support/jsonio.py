from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def dump_json_bytes(obj: Any) -> bytes:
    text = json.dumps(
        obj,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"{text}\n".encode("utf-8")


def write_json_atomic(path: str | Path, obj: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = dump_json_bytes(obj)

    with tempfile.NamedTemporaryFile(
        "wb",
        delete=False,
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    ) as temp_file:
        temp_path = Path(temp_file.name)
        temp_file.write(data)
        temp_file.flush()
        os.fsync(temp_file.fileno())

    try:
        os.replace(temp_path, destination)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
