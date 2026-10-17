"""Command-line entrypoints. Filesystem, rendering and decoding live in modules."""

import argparse
import os
from pathlib import Path
import sys

from . import __version__
from .scan import sections
from .render import Renderer
from .text import safe_text


def bounded_int(low: int, high: int):
    def parse(value: str) -> int:
        try:
            number = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("must be an integer") from exc
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"must be between {low} and {high}")
        return number
    return parse


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(add_help=False, description="An ls with real image thumbnails inside Kitty.")
    result.add_argument("--help", action="help", help="show this help message and exit")
    result.add_argument("-l", dest="long", action="store_true", help="long listing with metadata")
    result.add_argument("-1", dest="one", action="store_true", help="one thumbnail per row instead of a grid")
    result.add_argument("-h", "--human-readable", action="store_true", help="human-readable sizes with -l")
    result.add_argument("--si", action="store_true", help="human-readable sizes in powers of 1000")
    result.add_argument("-n", "--numeric-uid-gid", action="store_true", help="long listing with numeric owner/group")
    result.add_argument("-g", action="store_true", help="long listing without owner")
    result.add_argument("-o", action="store_true", help="long listing without group")
    result.add_argument("--full-time", action="store_true", help="long listing with full timestamp and timezone")
    result.add_argument("-i", "--inode", action="store_true", help="show inode numbers")
    result.set_defaults(indicator="none")
    result.add_argument("-F", "--classify", dest="indicator", action="store_const", const="classify", help="append file-type indicators")
    result.add_argument("-p", dest="indicator", action="store_const", const="directory", help="append / to directories")
    result.add_argument("-r", "--reverse", action="store_true", help="reverse sort order")
    result.set_defaults(sort="name")
    for flag, order, help_text in [
        ("-t", "time", "newest modification time first"),
        ("-S", "size", "largest size first"),
        ("-X", "extension", "sort by extension"),
        ("-v", "version", "natural numeric sort"),
        ("-U", "none", "directory order, without sorting"),
    ]:
        result.add_argument(flag, dest="sort", action="store_const", const=order, help=help_text)
    result.add_argument("--sort", choices=["name", "time", "size", "extension", "version", "none"])
    result.add_argument("--group-directories-first", action="store_true", help="group directories before files")
    result.add_argument("paths", nargs="*", type=Path, help="directories or files (default: .)")
    result.set_defaults(hidden="none")
    result.add_argument("-a", "--all", dest="hidden", action="store_const", const="all", help="include hidden files and . / ..")
    result.add_argument("-A", "--almost-all", dest="hidden", action="store_const", const="almost", help="include hidden files, excluding . / ..")
    result.add_argument("-d", "--directory", action="store_true", help="list directories themselves")
    result.add_argument("-R", "--recursive", action="store_true", help="list subdirectories without following symlinks")
    result.add_argument("--width", type=bounded_int(4, 60), default=14, help="thumbnail columns (4–60; default: 14)")
    result.add_argument("--height", type=bounded_int(2, 16), default=5, help="thumbnail rows (2–16; default: 5)")
    result.add_argument("--no-images", action="store_true", help="plain filenames, without graphics")
    result.add_argument("--version", action="version", version=f"kitty-lsi {__version__}")
    return result


def run(args: argparse.Namespace) -> int:
    args.long = args.long or args.numeric_uid_gid or args.g or args.o or args.full_time
    failed = False

    def error(exc: OSError) -> None:
        nonlocal failed
        print(f"lsi: {safe_text(str(exc))}", file=sys.stderr)
        failed = True

    renderer = Renderer(args, error)
    for index, section in enumerate(sections(
        args.paths or [Path(".")], hidden=args.hidden, directory=args.directory,
        recursive=args.recursive, order=args.sort, reverse=args.reverse,
        directories_first=args.group_directories_first, error=error,
    )):
        if index:
            print()
        if section.heading is not None:
            print(safe_text(section.heading) + ":")
        renderer.show(section.entries)
    return int(failed)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return run(args)
    except BrokenPipeError:
        # Avoid Python's second flush error during interpreter shutdown.
        sys.stdout = open(os.devnull, "w")
        return 0
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        print(f"lsi: {safe_text(str(exc))}", file=sys.stderr)
        return 1


def lli_main() -> int:
    """The convenience command is exactly lsi -l, not a second implementation."""
    return main(["-l", *sys.argv[1:]])
