# Changelog

## 0.2.0

### Added

- Optional paging in both grid and long-listing modes: `lsi -s` and `lsi -ls`
  show 5 entries at a time; `--step=N` accepts 5 through 50 and requires `=`.
  An explicit size overrides `-s`. Each directory starts a new sequence.
  The English `Press ENTER to continue...` prompt appears only when another
  step remains. Short/empty listings finish without a prompt; Ctrl+C stops and
  Ctrl+D at an empty prompt ends the listing. Paging is never automatic, adds
  no artificial sleep, and never waits with non-terminal input or output.
- Thumbnail caching enabled by default, with `--no-cache` to bypass reads and
  writes. Location: `${XDG_CACHE_HOME:-$HOME/.cache}/kitty-lsi`.

### Cache behavior and privacy

- First visits still decode full-size originals. Later visits reuse reencoded
  previews when file identity, size, modification/change timestamps, thumbnail
  geometry and application version are unchanged. Keys use metadata, not a
  cryptographic snapshot of the source. Source access is checked on cache hits.
- Cache data is private to the current user: 0700 directory and 0600 files.
  Managed candidates count towards a 256 MiB / 4,096-entry budget; oldest
  recognized entries are evicted first. Unsafe, unavailable, busy or over-budget
  caches fall back to uncached rendering instead of preventing image display.
- Only reencoded thumbnails and dimensions are stored. Cached PNGs remain
  untrusted: bounded headers and dimensions are checked, then parsing and
  reencoding run in the existing resource-limited decoder process.
- Thumbnails may remain after originals are deleted or access is revoked.
  `--no-cache` does not purge existing entries. To clear them, close `lsi` and
  remove only the `kitty-lsi` subdirectory from the active cache location, not
  the entire cache base. It is recreated on the next cache-enabled preview.
- No new runtime dependencies, helper programs, network access or telemetry.

### Fixed and hardened

- Keep CLI error messages readable by sanitizing argument-bearing context
  before formatting, preserving trusted line breaks without accepting injected
  terminal controls or forged lines. Out-of-range geometry remains an error;
  `--help` now states the supported width and height ranges.
- Center directory labels beneath their icons in the grid, including Unicode
  cell widths. Images, regular-file labels and long listings retain their
  alignment. With `-i`, directory inode and name occupy independent centered
  lines, so inode digits no longer consume the name's width.
- Exclude time spent waiting for ENTER from the shared processing deadline;
  decoder time/memory limits and the main CPU limit remain unchanged. The next
  step's images are not decoded until the user continues.
- Anchor cache operations to directory descriptors, reject symlink components,
  hardlinked entries and special files, and use exclusive temporary creation,
  same-directory renaming and a nonblocking exclusive lock.
- Count corrupt and unreadable cache candidates towards **both** budgets.
  Invalid headers must not bypass the disk-space or file-count policy. If safe
  eviction cannot recover space, disable caching for that run without deleting
  unrecognized contents. Regression tests reproduce the original failures and
  verify the corrected CLI behavior in an isolated filesystem.
- Extend CLI/PTY regressions for paging boundaries, EOF/interruption, redirected
  I/O, cache invalidation, malformed cache data, filesystem protections and
  bounded eviction. Security tests are not a guarantee of no vulnerabilities.

## 0.1.0

- Initial standalone Rust release for Linux x86-64, with grid and long listings,
  Kitty Graphics Protocol previews, neutral file-type icons and familiar
  `ls`-style options.
- Static executable, downloadable `.deb` and AUR `lsi-bin` distribution.
  Packages install only `lsi`; `lli` is an optional shell alias. The standalone
  archive also contains an `lli` symlink to the same executable.
