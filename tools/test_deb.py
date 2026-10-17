#!/usr/bin/env python3
"""Download a pinned official rootfs; test APT install/run/purge in Bubblewrap.
No sudo, host package manager, host HOME mount, or network inside the rootfs.
Requires unprivileged namespaces. Results are never automatically removed.
"""

import argparse
import hashlib
import os
import pathlib
import resource
import subprocess
import tarfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
IMAGES = {
    "ubuntu": (
        "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.5-base-amd64.tar.gz",
        "e77b6f10c2590cef872b33ee9f635a0e3fd1f57fb074c0e52b5c7f56147a0c86",
    ),
    "debian": (
        "https://raw.githubusercontent.com/debuerreotype/docker-debian-artifacts/a3751996111ce2c1c904050c84440184535e23b1/bookworm/oci/blobs/rootfs.tar.gz",
        "8cb71386cfcfc55b27b559f73c6d5c0cdcb93b83be8281314116e271cc42cea6",
    ),
}
p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--distro", choices=IMAGES, required=True)
p.add_argument("--package", type=pathlib.Path, required=True)
p.add_argument("--out", type=pathlib.Path, required=True)
p.add_argument("--rootfs-archive", type=pathlib.Path)
a = p.parse_args()
a.out.mkdir(parents=True, exist_ok=False)
os.chmod(a.out, 0o700)
url, sha = IMAGES[a.distro]
archive = a.rootfs_archive or a.out / "rootfs.tar.gz"
if not a.rootfs_archive:
    with urllib.request.urlopen(url, timeout=60) as response, archive.open("xb") as f:
        total = 0
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > 256 * 1024 * 1024:
                raise RuntimeError("rootfs download exceeds size limit")
            f.write(chunk)
if hashlib.sha256(archive.read_bytes()).hexdigest() != sha:
    raise SystemExit("rootfs checksum mismatch")
root = a.out / "root"
root.mkdir()
# Only the pinned upstream archive is extracted; tar filter rejects member traversal.
with tarfile.open(archive) as t:
    t.extractall(root, filter="tar")
(root / "packages").mkdir(exist_ok=True)
(root / "pictures").mkdir(exist_ok=True)
(root / "tmp/check-package.sh").write_bytes((ROOT / "tools/check_deb_install.sh").read_bytes())
# This is a plain text fixture, not an adversarial parser test. Clean distro
# checks need no image tools; decoding is tested separately in an empty sandbox.
(root / "pictures/sample.txt").write_text("fixture\n")


def limits():
    for key, value in [
        (resource.RLIMIT_AS, 2 * 1024**3),
        (resource.RLIMIT_CPU, 30),
        (resource.RLIMIT_NPROC, 8192),
        (resource.RLIMIT_NOFILE, 512),
    ]:
        resource.setrlimit(key, (value, value))


package = a.package.resolve(strict=True)
cmd = [
    "bwrap",
    "--unshare-all",
    "--die-with-parent",
    "--new-session",
    "--uid",
    "0",
    "--gid",
    "0",
    "--cap-drop",
    "ALL",
    "--bind",
    str(root),
    "/",
    "--ro-bind",
    str(package.parent),
    "/packages",
    "--proc",
    "/proc",
    "--dev",
    "/dev",
    "--clearenv",
    "--setenv",
    "HOME",
    "/root",
    "--setenv",
    "PATH",
    "/usr/sbin:/usr/bin:/sbin:/bin",
    "--setenv",
    "DEBIAN_FRONTEND",
    "noninteractive",
    "/bin/sh",
    "/tmp/check-package.sh",
    "/packages/" + package.name,
]
with (a.out / "install.log").open("xb") as log:
    result = subprocess.run(
        cmd, stdout=log, stderr=subprocess.STDOUT, timeout=60, preexec_fn=limits
    )
print(a.out / "install.log")
raise SystemExit(result.returncode)
