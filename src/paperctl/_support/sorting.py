from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Iterable, TypeVar


T = TypeVar("T")


def posix_path_sort_key(path: str | Path) -> tuple[str, ...]:
    return PurePosixPath(Path(path).as_posix()).parts


def sorted_by_path(items: Iterable[T], path_getter) -> list[T]:
    return sorted(items, key=lambda item: posix_path_sort_key(path_getter(item)))
