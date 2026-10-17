# kitty-lsi

**An `ls` with real image thumbnails, right inside Kitty.**

Run `lsi` to recognise the pictures in a folder without opening them one by one.
It prints a thumbnail grid with filenames, then returns your prompt. Use
`lsi -l` (or `lli`) for a row-based listing with thumbnails and file metadata.
No full-screen browser. No Kitty fork. No replacement for your existing `ls`.

## Install from a local checkout

Requires **Python 3.11+** and **Kitty with Unicode-placeholder support**.
Linux is the primary target; macOS is not yet verified. Windows is not supported.

```sh
cd kitty-lsi
pipx install .
# Or, if you use uv:
uv tool install .
```

For development (editable install, so your changes take effect immediately):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
source .venv/bin/activate
```

Both `lsi` and `lli` are installed as commands. No aliases, shell functions,
remote-control settings or changes to `kitty.conf` are needed. PyPI publication
is not yet available; the commands above install this checkout.

## Usage

```sh
lsi                          # Grid in the current directory
lsi ~/Pictures               # Grid in another directory
lsi -l ~/Pictures            # Thumbnails + permissions, links, owner, group, bytes, date
lli -h ~/Pictures            # Same as lsi -lh
lsi -lah                     # Long listing, hidden files, human-readable sizes
lsi -A                       # Hidden files, but not . and ..
lsi -lSh                     # Largest files first, readable sizes
lsi -tr                      # Oldest modification time first
lsi -v                       # Natural order: photo2 before photo10
lsi --width 24 --height 6     # Larger thumbnail area (terminal cells)
lsi -1                       # One thumbnail per row, without long metadata
lsi -- *.png *.jpg           # Explicit files / shell-expanded patterns
lsi -R --group-directories-first
lsi --no-images              # Plain text
lsi --help
```

Other files and directories remain visible, with text labels instead of
thumbnails. A non-image-only folder is still a useful listing. A symlink is
listed as a symlink, never decoded or traversed. GIFs show their first frame.

### Supported `ls`-style flags

| Flags | Meaning |
| --- | --- |
| `-l` / `lli` | Long format, including permissions, hard-link count, owner, group, size and modification date |
| `-1` | One thumbnail per row |
| `-a`, `--all` | Include hidden entries, `.` and `..` |
| `-A`, `--almost-all` | Include hidden entries without `.` and `..` |
| `-h`, `--human-readable` | Base-1024 readable sizes with long format |
| `--si` | Base-1000 readable sizes |
| `-t` | Newest modification time first |
| `-S` | Largest size first |
| `-X` | Sort by extension |
| `-v` | Natural numeric filename order |
| `-U` | Preserve directory enumeration order |
| `-r`, `--reverse` | Reverse the selected sort; ignored with `-U` |
| `--sort=name,time,size,extension,version,none` | Select one sort mode (one value, not a comma-separated list) |
| `--group-directories-first` | Keep real directories before other entries |
| `-d`, `--directory` | List directory operands themselves |
| `-R`, `--recursive` | List subdirectories; never follow symlink directories |
| `-F`, `--classify` | Append `/`, `@`, `*`, `\|`, `=` by type |
| `-p` | Append `/` to directories only |
| `-i`, `--inode` | Include inode numbers |
| `-n`, `--numeric-uid-gid` | Long format with numeric owner/group |
| `-g` / `-o` | Long format without owner / without group |
| `--full-time` | Long format with full date, seconds and timezone |

Short flags can be combined: `lsi -laSh`. `-h` means readable sizes, not help;
use `--help`. Unknown options fail explicitly rather than silently changing
behaviour. This is **not** a drop-in GNU `ls` implementation: only the flags
above are supported. Ordering is deterministic Unicode ordering, not locale
collation, and natural sorting is not an exact clone of GNU version sorting.
The two dot entries from `-a` are prepended, and never recursively expanded.
Metadata does not include ACL/SELinux annotations, directory block totals, or
nanosecond timestamps. Explicit symlink-directory operands are not followed.

### Terminal behaviour

- Output goes inline and images follow text in Kitty's scrollback, subject to
  Kitty's configured scrollback and graphics-memory limits.
- Filenames are shortened to fit thumbnail cells; increase `--width`, use
  `-1`/`-l`, or `--no-images` for more space/full untruncated text.
- Graphics use the terminal's colours/background; there is no imposed theme.
- Redirects and pipes contain plain filenames/metadata, never image escapes.
- Outside Kitty, or inside tmux/screen, the command falls back to text.
  Multiplexer graphics support is intentionally not claimed in v0.1.
- Very narrow terminals fall back to text. Geometry is selected for each
  directory section; previously printed content is not interactively relaid out.
- SSH has no file-transfer dependency (PNG bytes are streamed), but automatic
  detection requires `TERM=xterm-kitty` on the remote end and installation there.
  SSH compatibility has not yet been verified live.

## Formats and safety

PNG, JPEG, GIF, WebP, BMP, TIFF, ICO and AVIF are recognised. Availability depends
on the codecs included with your Pillow build. SVG/PDF/video/RAW are deliberately
not decoded in this release. Originals are never changed. There is no network
fetching, telemetry, subprocess decoder or persistent thumbnail cache.

Previews are limited to **64 MiB per source file** and **40 megapixels**. Invalid
images remain listed and produce a warning; other entries continue. Filesystem
errors are also reported. Exit statuses: `0` success, `1` file/preview error,
`2` invalid arguments, `130` interrupted.

Non-regular files and symlinks are not decoded. Filenames and error text have
terminal control characters neutralised, including escape sequences and bidi
controls. Literal names containing these characters therefore display with `?`.

## Development

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests exercise the command interface using actual subprocesses, temporary
files and pseudo-terminals. They verify flags, error handling, safe filenames,
metadata, raster conversion, grid/list placement and plain redirected output.
A PTY is not a graphics renderer: the separate visual smoke test opens an
isolated Kitty window with generated fixtures (see `CONTRIBUTING.md`).

Implementation modules:

- `cli.py`: arguments and entrypoints.
- `scan.py`: non-following traversal and directory sections.
- `listing.py`: sorting and metadata.
- `render.py`: grid/row layout and plain-text fallback.
- `preview.py`: bounded raster decoding.
- `graphics.py`: PNG transmission and Unicode placeholders.
- `text.py`, `terminal.py`: safe text and terminal detection.

The graphics implementation follows the [Kitty graphics protocol](https://sw.kovidgoyal.net/kitty/graphics-protocol/#unicode-placeholders).
Image processing uses [Pillow](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.thumbnail).

## License

[MIT](LICENSE). Use it, modify it, share it.
