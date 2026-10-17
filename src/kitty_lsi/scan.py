"""Walk one directory at a time. Never recurse into symlinks."""

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable, Iterator
import os
import stat

from .listing import sorted_paths


@dataclass(frozen=True)
class Entry:
    path: Path
    name: str


@dataclass(frozen=True)
class Section:
    heading: str | None
    entries: list[Entry]


def sections(paths: list[Path], *, hidden: str, directory: bool, recursive: bool,
             order: str, reverse: bool, directories_first: bool,
             error: Callable[[OSError], None]) -> Iterator[Section]:
    def ordered(items: list[Path]) -> list[Path]:
        return sorted_paths(items, order, reverse, directories_first)

    files, folders = [], []
    for path in paths:
        try:
            mode = path.lstat().st_mode
            (folders if stat.S_ISDIR(mode) and not directory else files).append(path)
        except OSError as exc:
            error(exc)
    if files:
        yield Section(None, [Entry(p, os.fspath(p)) for p in ordered(files)])
    stack = list(reversed(ordered(folders)))
    seen: set[tuple[int, int]] = set()
    while stack:
        folder = stack.pop()
        try:
            info = folder.lstat()
            # Handles a path swapped to a symlink while traversing as well.
            if not stat.S_ISDIR(info.st_mode):
                continue
            identity = (info.st_dev, info.st_ino)
            if recursive and identity in seen:
                error(OSError(f"recursive directory already visited: {folder}"))
                continue
            seen.add(identity)
            children = []
            for child in folder.iterdir():
                if hidden == "none" and child.name.startswith("."):
                    continue
                try:
                    child.lstat()
                    children.append(child)
                except OSError as exc:
                    error(exc)
            children = ordered(children)
            entries = [Entry(p, p.name) for p in children]
            if hidden == "all":
                entries = [Entry(folder / ".", "."), Entry(folder / "..", "..")] + entries
            heading = str(folder) if recursive or len(paths) > 1 else None
            yield Section(heading, entries)
            if recursive:
                stack.extend(reversed([
                    child for child in children
                    if not child.is_symlink() and child.is_dir()
                ]))
        except OSError as exc:
            error(exc)
