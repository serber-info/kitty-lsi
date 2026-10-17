# Linux distribution — local candidates, not published

Only Linux x86-64/amd64 is verified. Rust and NASM are build tools, never runtime
requirements. Python is used only by developer test/package scripts. Do not use
Python `pip install` as the recommended end-user distribution.

## Build and prepare

```sh
sh tools/build_static.sh
python tools/check_elf.py rust/target/x86_64-unknown-linux-musl/release/lsi
python tools/build_release.py \
  --binary rust/target/x86_64-unknown-linux-musl/release/lsi \
  --out /tmp/lsi-candidate-NEW
```

The output directory must not exist. The tool verifies ELF commands successfully
before parsing results and generates:

- `lsi-VERSION-linux-x86_64.tar.gz`: `lsi`, relative `lli -> lsi`, documentation,
  dependency license texts, exact MPL source, dependency inventory, provenance.
- `lsi_VERSION_amd64.deb`: the same executable/alias in `/usr/bin`, documentation
  and license/source material in `/usr/share/doc/lsi`; no maintainer scripts,
  no declared Python/Rust/Cargo/converter runtime dependencies.
- SHA-256 sums and provenance. Archives use normalized owner, mode, timestamps
  and ordered paths. Equal outputs were tested locally; this is not proof of
  reproducibility across independent toolchains or environments.

A default build is explicitly a **candidate**. Its Debian maintainer is
`UNCONFIGURED <noreply@example.invalid>`, a reserved test-only contact, not a real
maintainer. Before public packaging supply actual owner/repo, a clean matching
40-character source commit, real maintainer contact and `--release`:

```sh
python tools/build_release.py --binary PATH --out NEW_DIRECTORY \
  --repository serber-info/kitty-lsi --revision FULL_COMMIT_SHA \
  --maintainer 'serber-info <39016027+serber-info@users.noreply.github.com>' \
  --epoch SOURCE_COMMIT_UNIX_TIME --release
```

The repository and public maintainer identity above were explicitly approved.
`FULL_COMMIT_SHA` and `SOURCE_COMMIT_UNIX_TIME` must refer to the actual reviewed
source commit. The GitHub noreply address is intentionally not a support mailbox;
use GitHub Issues for general support and the repository's private vulnerability
reporting channel for security. The tool never uploads or publishes anything.

Release mode also rejects obvious placeholder repositories and reserved example
email domains. This is validation, not proof of account ownership or an active
contact: the maintainer must verify the actual repository/contact before use.
The packager and standalone verifier share the same static ELF gate. Rebuild
from the approved source commit before packaging; assigning a revision to a
supplied executable does not itself prove that executable's build origin.

## Arch / CachyOS / EndeavourOS

Priority: **lsi-bin**, a precompiled standalone executable. Templates:
`packaging/aur/PKGBUILD.in`, `.SRCINFO.in`. Actual metadata is rendered only with
a real versioned release location and archive hash. Licenses include all
reviewed expressions; exact notices/source accompany the payload. `!strip` and
`!debug` avoid altering the already stripped binary or requiring debugedit.

For offline package validation:

```sh
python tools/prepare_local_aur.py --archive PATH_TO_ARCHIVE --out NEW_AUR_DIRECTORY
cd NEW_AUR_DIRECTORY
makepkg --printsrcinfo > .SRCINFO
makepkg --nodeps --nocheck --nosign
```

Local validation changes the source to the supplied local archive only. Do not
publish that local-only recipe. Generate `.SRCINFO` with makepkg and compare it
with the rendered template before submission. Test install/integrity/remove in
a disposable Arch environment. `lsi-bin` provides `lsi` and conflicts with the
optional source package `lsi`. The proposed AUR names returned no packages on
2026-10-17; this is not a reservation, and availability must be rechecked.

The Arch package was built with makepkg and installed/checked/removed with pacman
in a private Arch bootstrap filesystem. `paru` itself has not been run: no AUR
entry exists and there is no honest `paru -S lsi-bin` end-to-end result yet.
A source-built `lsi` recipe remains deferred: musl-target toolchain requirements
must be resolved according to Arch packaging policy rather than downloading a
toolchain from an install script. This does not block the binary package.

## Debian / Ubuntu / Mint

Local .deb install, execution and purge were tested on Debian 12 (Bookworm) and
Ubuntu 24.04.5 amd64 root filesystems with APT/dpkg. The test namespaces contain
no network or host HOME and map root only to the ordinary host user. An APT log
ownership warning is expected when its `adm` group is unmapped; transactions and
clean purge still succeed. Installation does not require privileged maintainer
scripts. Permissions are 0755 for the executable and 0644 for documentation.

Reproduce using pinned official images and verified hashes:

```sh
python tools/test_deb.py --distro debian --package PATH.deb --out NEW_DIRECTORY
python tools/test_deb.py --distro ubuntu --package PATH.deb --out NEW_DIRECTORY
```

An existing verified tar can be provided with `--rootfs-archive`; otherwise the
tool downloads the pinned image, never an external script. Rootfs test results
are retained, not automatically removed. These are container/filesystem tests,
not boots of full VMs. Mint and other Debian/Ubuntu releases are not yet claimed
as independently tested. Lintian/piuparts and a full VM matrix remain useful
additional checks, not implied by the APT install tests.

Downloadable `.deb` files are **not** a signed APT repository and do not provide
repository-based automatic updates. No repository, keys or signing service has
been configured or published.

## CI and publication boundary

GitHub Actions uses read-only repository permissions, checkout without persisted
credentials and third-party actions pinned to verified commits. Tests, Clippy,
RustSec, cargo-deny, license text collection, fail-closed ELF checks, isolated
adversarial tests, SHA-256 and candidate packaging precede clean Debian/Ubuntu
and pinned Arch-container package validation. Candidate workflow artifacts are
not GitHub Releases. No release publishing step or write token is configured.

The workflow has been reviewed locally but has **not run on GitHub**. Before a
release: run it on the approved source commit, validate real metadata and package
names, review secrets/unwanted files and hashes, and obtain explicit publication
authorization. Do not describe a local test as a successful hosted CI run.
