from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BoundedText:
    text: str
    inspected_byte_count: int
    omitted_byte_count: int
    truncated: bool


def read_utf8(path: Path, *, max_bytes: int | None = None) -> BoundedText:
    if max_bytes is None:
        data = path.read_bytes()
        return BoundedText(
            text=data.decode("utf-8"),
            inspected_byte_count=len(data),
            omitted_byte_count=0,
            truncated=False,
        )

    with path.open("rb") as handle:
        data = handle.read(max_bytes + 1)
    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    byte_size = path.stat().st_size
    text = _decode_truncated_utf8(data) if truncated else data.decode("utf-8")
    return BoundedText(
        text=text,
        inspected_byte_count=len(data),
        omitted_byte_count=max(0, byte_size - len(data)),
        truncated=truncated,
    )


def _decode_truncated_utf8(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        if exc.reason == "unexpected end of data" and exc.end == len(data):
            return data[: exc.start].decode("utf-8")
        raise
