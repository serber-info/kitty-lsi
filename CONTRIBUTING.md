# Contributing

Keep this a small inline image listing, not an interactive file manager.
Do not replace `ls`, modify shell profiles, or require Kitty remote control for
normal use. Preserve plain-output fallback and never modify source images.

The primary implementation is in `rust/`; see [its instructions](rust/README.md).
The original Python code and tests are retained as a regression reference.
Do not remove or silently rewrite that baseline during the migration.

## Design and tests

Keep module interfaces small. Filesystem traversal, image decoding, graphics
protocol and layout each own their implementation details. Do not introduce
abstract adapters for hypothetical future backends.

Use the agreed command-line and real-terminal seams. For new behaviour, start
with one failing acceptance test, implement that vertical slice, then rerun the
suite. Prefer observable behaviour over mocks of internal collaborators.
PTY tests do not prove visual correctness: also inspect actual Kitty output.

Run Cargo integration tests, compatibility tests, clippy and rustfmt. Release
candidates also require static-ELF inspection, isolated image decoding and visual
checks. Dependency updates require a native Cargo advisory audit before release.

## Publication

No automatic publishing is configured. A maintainer must approve source commits,
GitHub publishing and AUR submissions. Review complete diffs, archives and file
lists for credentials, private instructions and machine-specific artifacts.
Only generated fixtures belong in release screenshots, never personal images.
Preserve dependency license notices in binary archives. Package names and release
URLs must be verified, not assumed.

## Security and packaging gates

See `SECURITY.md`. Prefer
`sh tools/build_static.sh` for a private-path-remapped static release. Use
`tools/security_tests.py` only with effective unprivileged namespaces and the
verified resource limits; it retains all results. `tools/isolate_binary.py`
adapts the public CLI acceptance seam to bwrap without changing Python tests.

`tools/build_release.py` creates deterministic candidates and collects actual
license texts plus exact MPL source. `--release` rejects incomplete contact,
repository, source commit or dirty checkout metadata; it never publishes.
`tools/test_deb.py` verifies pinned official rootfs hashes before isolated
APT installation/execution/purge. AUR templates must be rendered from a real
release, then `.SRCINFO` regenerated with makepkg; local-only test recipes are
not publication material. No commit/push/release is automatic.
