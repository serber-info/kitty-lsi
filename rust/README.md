# Rust implementation

The executable does not import,
invoke, embed or require Python, `icat`, ImageMagick or other codec programs.

## Build prerequisites (developers only)

- Rust/Cargo **1.98+** (required by the AVIF decoder), a C linker for Rust's
  build-time artifacts, and **NASM 2.14+** for rav1d's bundled x86 assembly.
- `rustup target add x86_64-unknown-linux-musl` for standalone releases.
- Network access on the first `cargo fetch`; later builds support `--offline`.

NASM is a compile-time assembler, not a decoder executable used by `lsi`.
The AVIF decoder is the Rust `avif-decode` / `rav1d` stack; there is no
runtime `libdav1d`, `libavif`, `libaom`, `libjpeg`, `libpng` or `libwebp` link.

```sh
cd rust
cargo fetch --locked
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
cargo fmt --check
cargo build --locked --release --target x86_64-unknown-linux-musl
```

`.cargo/config.toml` selects Rust's bundled `rust-lld` linker and static musl
runtime for that target. **Run from `rust/`** so Cargo loads that configuration.
A normal GNU debug build is not the distributed standalone artifact.

## Regression testing

Native Cargo integration tests exercise the command interface without Python.
Acceptance tests run directly against the Rust process/PTY interface. Pillow
generates and inspects developer-only fixtures; no alternative application is shipped.

```sh
# From the repository root, using the existing development venv:
LSI_REAL_BINARY="$PWD/rust/target/x86_64-unknown-linux-musl/release/lsi" \
LSI_BINARY="$PWD/tools/isolate_binary.py" \
  .venv/bin/python -m unittest discover -s rust/tests -p 'test_*.py' -v
```

The compatibility suite retains original flag/CLI/PTy scenarios, with explicit
Rust overrides for default directory grouping, raster icons and the `lli` alias.
It verifies all eight image codecs, neutral icons for every entry type and
case-insensitive extension badges, including compound archives. Non-image files
are never opened for these icons, SVG is never interpreted, and symbolic links
are never followed. All file types remain visible; unknown extensions use a
generic file icon. Malformed-image tests must run through the isolated wrapper.

## Runtime independence

```sh
file target/x86_64-unknown-linux-musl/release/lsi
ldd target/x86_64-unknown-linux-musl/release/lsi
readelf -l target/x86_64-unknown-linux-musl/release/lsi  # no INTERP
readelf -d target/x86_64-unknown-linux-musl/release/lsi  # no NEEDED
```

From the root, the optional isolation test needs bubblewrap and Python/Pillow
**outside** its sandbox. Inside, only the executable, generated pictures,
`/proc` and `/dev` are mounted; `/bin`, `/usr` and `/lib` do not exist. Every
image format is decoded and its Kitty PNG transmission inspected. `lli` and
metadata are also tested, with numeric owner/group fallback.

```sh
.venv/bin/python rust/scripts/standalone_smoke.py \
  rust/target/x86_64-unknown-linux-musl/release/lsi
```

For visual verification on Linux X11/XWayland, the optional test helper needs
`kitty`, `kitten`, `xdotool`, and ImageMagick `import` **as QA tools only**:

```sh
.venv/bin/python rust/scripts/visual_smoke.py \
  rust/target/x86_64-unknown-linux-musl/release/lsi
```

It opens and captures only isolated test windows and closes them on exit.
No existing session or Kitty configuration is altered. Inspect all four PNGs;
script completion alone is not a visual pass.

## Modules

- `main.rs`, `options.rs`: command orchestration and CLI.
- `scan.rs`: non-following traversal, metadata snapshots and sorting.
- `listing.rs`: metadata formatting, local account names and numeric fallback.
- `render.rs`: grid, rows, metadata wrapping and plain-output fallback.
- `preview.rs`: bounded raster decoding, orientation and PNG encoding.
- `graphics.rs`: Kitty chunking, virtual placements and Unicode placeholders.
- `text.rs`, `terminal.rs`: safe cell-aware text, terminal capability and ioctl.
- `cache.rs`: private descriptor-anchored, bounded thumbnail storage.
- `pager.rs`, `budget.rs`: opt-in steps and processing time excluding user waits.

The stable test seam is the executable interface; module internals may change.

## Hardened build and checks

From the repository root, prefer `sh tools/build_static.sh` for release builds.
It uses the musl linker configuration and remaps private source/cache paths.
The binary invokes itself as a limited decoder process; no additional runtime
application is needed. Linux `/proc`, seccomp and CPU affinity are required for
previews. See [security policy](../SECURITY.md) for budgets and residual risks.

```sh
python tools/security_tests.py --binary rust/target/x86_64-unknown-linux-musl/release/lsi
LSI_BINARY="$PWD/tools/isolate_binary.py" .venv/bin/python -B -m unittest discover -s rust/tests -p 'test_*.py' -v
python tools/build_release.py --binary rust/target/x86_64-unknown-linux-musl/release/lsi --out /tmp/lsi-candidate-NEW
```

Security tests fail closed if user/network/mount namespaces or resource-limit
verification fail. They need bwrap and Python/Pillow as development tools and
retain all results. Never run malformed-image tests on your personal filesystem.
`worker.rs` owns decoder process limits, seccomp and bounded IPC;
`secure_fs.rs` owns descriptor-relative traversal; `errors.rs` caps diagnostics.
