# Contributing

Keep this a small inline image listing, not an interactive file manager.
Do not replace `ls`, modify shell profiles, or require Kitty remote control
for normal use. Preserve the plain-output fallback and do not change originals.

## Tests and design

The test seam is the command-line interface: subprocess + filesystem for
behaviour, and actual PTYs for terminal output. Prefer tests of observable
behaviour over internal mocks. For new behaviour, write a failing acceptance
test, implement the smallest vertical slice, then run the suite. Visual claims
also require an actual Kitty check, not just a successful PTY test.

Keep interfaces small and put knowledge in its owning module. In particular,
rendering code should not know how to walk directories or decode image formats.
Do not add abstract adapters for hypothetical future backends.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m build
```

## Visual smoke test (Linux + X11/XWayland)

The optional `scripts/visual_smoke.py` requires `kitty`, `kitten`, `xdotool`
and ImageMagick's `import` on PATH. It opens **its own** isolated Kitty process,
creates generated image fixtures in a private temporary directory, and captures
only that test window. It never connects to existing Kitty sessions. Remote
control is enabled only on that test process, through a private Unix socket.
It closes that process on exit; it does not change `kitty.conf`.

```sh
.venv/bin/python scripts/visual_smoke.py
```

The script prints the temporary artifact directory. Inspect the grid, detailed
list, scrollback and narrow screenshots for missing pictures, overlap and text
alignment. Do not call a visual test passed merely because the script exits 0.
Pure Wayland without XWayland is not supported by this optional test helper.

## Security and releases

- Keep raster limits and filename sanitisation covered by acceptance tests.
- Never shell-interpolate filenames or open symlinks/special files for decoding.
- Do not introduce remote fetches, persistent caches or telemetry implicitly.
- Review dependency changes and run `pip-audit` before a public release.
- Build a wheel/sdist and test an installation outside the source tree.
- Review the complete publication file list for secrets, local paths,
  private instructions and machine-specific artifacts before publishing.
- Release screenshots must contain generated fixtures, not personal files.

There is no automatic publishing workflow; releases require a maintainer's
explicit action.
