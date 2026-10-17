# Security policy and limits

This local CLI processes untrusted image parsers. Rust, static linking and a
passing dependency audit do not guarantee memory safety or absence of defects.
Never run image previews as root. Only Linux x86-64 is currently supported.

## Runtime containment

- Decoders run in another invocation of the **same executable**, not Python,
  icat, a shell or a system converter. No extra runtime executable is required.
- Each decoder has 768 MiB address space (not an RSS guarantee), 3 CPU seconds,
  one allowed CPU and a parent-enforced 5-second wall deadline; output is capped
  at 8 MiB. Failure, OOM or signal affects the preview, not the remaining list.
  Parent-death SIGKILL is armed and its spawn race checked before decoding.
- Linux seccomp is required for previews; failure is closed. It denies new
  file opens, sockets, exec, non-thread clone/fork and selected dangerous calls.
  It is an x86-64 syscall allowlist (including explicit rejection of x32),
  not a proof of absence of codec vulnerabilities. Threads
  remain possible, constrained by address space and the codec's single CPU.
- Main process: 1 GiB address space, 60 CPU seconds, at most 1,024 descriptors. A traversal and rendering
  budget is checked cooperatively at 120 seconds; this cannot cancel kernel
  I/O stalled on an unresponsive remote/FUSE filesystem. Explicit interactive
  paging excludes time waiting for ENTER from this shared processing budget;
  decoder and CPU limits are unchanged.
- Inputs: regular files only, at most 64 MiB, 40 MP. General decoder limits add
  256 MiB non-strict allocation budget and strict 40,000 per-axis dimensions.
- A listing admits at most 20,000 visible entries/operands, 512 pending recursive
  directories/operand parent contexts, recursion depth 64, 4,096-byte paths and
  100 detailed errors plus an omission notice. Hitting a limit
  is an explicit error, not silently successful truncation.

## Filesystem and terminal boundaries

Paths are resolved component-by-component without symlink ancestors. Symlink
entries are displayed, not previewed or recursively traversed. This deliberately
rejects explicit operands through a symlinked parent (use the real directory).
Directory traversal is anchored to open descriptors; files are reopened relative
to the anchored parent and compared by inode/device/mode/size/mtime/ctime before
use. A second comparison after read detects ordinary concurrent modification.
This is not an atomic filesystem snapshot; concurrent writers or hostile kernels
remain outside the guarantee. Read-only operation does not confer privilege.
Linux /proc must be mounted and seccomp/CPU affinity must be available for
previews. Text-only fallback does not need a decoder sandbox.

All application text and CLI error diagnostics are sanitized. Reencoded PNGs
are transmitted directly through Kitty graphics, not original image bytes.
Image IDs are independent random 28-bit nonzero values, unique within a listing;
collisions with prior programs remain possible because the terminal provides no
private image namespace. Images intentionally remain for scrollback; the CLI
never deletes other applications' images. A supported Kitty graphics terminal
is needed for previews; other terminals/pipes receive names and metadata only.

## Thumbnail cache

Only successful regular-file previews are cached, by default under
`${XDG_CACHE_HOME:-$HOME/.cache}/kitty-lsi`. `--no-cache` disables both reads
and writes. Pipe/plain-output runs do not create the cache. Private directory
and file modes are required (0700/0600), with current-user ownership; unsafe
existing permissions are not changed. Symlink path components, hardlinked
entries and special files are rejected. Resolution, creation, renaming and
eviction are anchored to the opened cache directory, not a reconstructed path.

The cache uses an exclusive, nonblocking lock; a busy/unavailable cache is
skipped. Managed entries are bounded to 256 MiB total, 4,096 entries and 8 MiB
plus a 16-byte header per entry. Oldest managed entries are evicted first;
corrupt/unreadable candidate entries still count towards both budgets. If
space cannot be recovered safely, the cache is skipped rather than growing;
unrelated or unrecognized contents are not deleted. Source identity and access are checked even
on hits. Device/inode/mode/size/mtime/ctime, geometry and application version
identify entries. This is metadata invalidation, not a cryptographic snapshot.

Cached dimensions and PNG headers are bounded before parsing. Cached PNGs still
pass through the resource-limited decoder and are reencoded before transmission;
corruption falls back to the source. Cache data remains untrusted. Thumbnails
may persist after originals are deleted; disabling the cache does not purge it.
Other processes running as the same UID, a hostile filesystem/kernel and
previously copied thumbnails remain outside the privacy guarantee. Disk budgets
apply to managed entries, not unrelated files manually placed in this directory.

## Dependency exception: RUSTSEC-2024-0436

`paste 1.0.15` is unmaintained, a build-only proc macro via rav1d. There is no
known vulnerability in this advisory and no patched release. We do not blanket
upgrade or vendor an entire codec merely to silence this warning. The precise
maintenance advisory is recorded in deny.toml; other vulnerabilities are not
ignored. Review before each release and no later than 2026-11-17; remove the
exception when an upstream maintained replacement is available, or reassess the
codec. Build scripts, proc macros, native assembly and unknown vulnerabilities
remain supply-chain risks even when RustSec reports zero known vulnerabilities.

## Distribution gates

No public release without a reviewed source commit, actual repository URL,
matching provenance, current dependency/license checks, clean package validation
and explicit maintainer authorization. Candidate artifacts marked UNCOMMITTED
are local test packages, not verified public releases. Distribute dependency
license texts and the exact MPL-covered source included by the packaging tool.

## Reporting

Maintainer: **serber-info**. Report vulnerabilities privately through
[GitHub private vulnerability reporting](https://github.com/serber-info/kitty-lsi/security/advisories/new).
Private reporting is enabled for this repository. Do not put exploit details in
public issues. General support belongs in
[GitHub Issues](https://github.com/serber-info/kitty-lsi/issues).
The GitHub noreply address used for Git/package metadata is not a support mailbox.
