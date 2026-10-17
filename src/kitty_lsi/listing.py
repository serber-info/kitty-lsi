"""Filesystem metadata and ls-style text formatting; no terminal graphics."""

from datetime import datetime
from functools import lru_cache
import grp
import pwd
import stat
import re
from pathlib import Path


def sorted_paths(paths: list[Path], order: str, reverse: bool,
                 directories_first: bool = False) -> list[Path]:
    # Deterministic Unicode ordering rather than platform-dependent collation.
    result = list(paths)
    if order != "none":
        result.sort(key=lambda p: p.name)
        if order == "size":
            result.sort(key=lambda p: -p.lstat().st_size)
        elif order == "time":
            result.sort(key=lambda p: -p.lstat().st_mtime_ns)
        elif order == "extension":
            result.sort(key=lambda p: p.suffix)
        elif order == "version":
            result.sort(key=lambda p: [
                (1, int(piece)) if piece.isdigit() else (0, piece)
                for piece in re.split(r"(\d+)", p.name)
            ])
        if reverse:
            result.reverse()
    if directories_first:
        result.sort(key=lambda p: not (not p.is_symlink() and p.is_dir()))
    return result


@lru_cache(maxsize=256)
def owner(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


@lru_cache(maxsize=256)
def group(gid: int) -> str:
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


def file_size(size: int, human: bool = False, si: bool = False) -> str:
    if not human and not si:
        return str(size)
    base = 1000 if si else 1024
    value = float(size)
    suffixes = ("", "k", "M", "G", "T", "P", "E") if si else ("", "K", "M", "G", "T", "P", "E")
    for suffix in suffixes:
        if value < base or suffix == suffixes[-1]:
            if not suffix:
                return str(size)
            return (f"{value:.1f}" if value < 10 else f"{value:.0f}") + suffix
        value /= base
    raise AssertionError("unreachable")


def long_fields(path: Path, human: bool = False, *, numeric: bool = False,
                si: bool = False, hide_owner: bool = False,
                hide_group: bool = False, full_time: bool = False) -> list[str]:
    info = path.lstat()
    size = file_size(info.st_size, human, si)
    if stat.S_ISCHR(info.st_mode) or stat.S_ISBLK(info.st_mode):
        import os
        size = f"{os.major(info.st_rdev)}, {os.minor(info.st_rdev)}"
    fields = [stat.filemode(info.st_mode), str(info.st_nlink)]
    if not hide_owner:
        fields.append(str(info.st_uid) if numeric else owner(info.st_uid))
    if not hide_group:
        fields.append(str(info.st_gid) if numeric else group(info.st_gid))
    date = datetime.fromtimestamp(info.st_mtime).astimezone()
    if full_time:
        date_text = date.strftime("%Y-%m-%d %H:%M:%S %z")
    else:
        now = datetime.now().astimezone()
        recent = -3600 <= (now - date).total_seconds() <= 15_778_476
        date_text = date.strftime("%b %d %H:%M" if recent else "%b %d  %Y")
    fields.extend([size, date_text])
    return fields
