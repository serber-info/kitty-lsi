#!/usr/bin/env python3
"""Produce an explicitly local-only PKGBUILD for makepkg validation."""

import argparse
import hashlib
import pathlib
import re
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument("--archive", required=True, type=pathlib.Path)
p.add_argument("--out", required=True, type=pathlib.Path)
a = p.parse_args()
a.out.mkdir(parents=True, exist_ok=False)
version = a.archive.name.removeprefix("lsi-").removesuffix("-linux-x86_64.tar.gz")
if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
    raise SystemExit("expected numeric release version in archive name")
archive = a.archive.resolve(strict=True)
shutil.copy2(archive, a.out / archive.name)
s = (
    (ROOT / "packaging/aur/PKGBUILD.in")
    .read_text()
    .replace("@VERSION@", version)
    .replace("@REPOSITORY@", "LOCAL-VALIDATION/NOT-PUBLISHED")
    .replace("@SHA256@", hashlib.sha256(archive.read_bytes()).hexdigest())
)
s = s.replace(
    "https://github.com/LOCAL-VALIDATION/NOT-PUBLISHED/releases/download/v${pkgver}/lsi-${pkgver}-linux-x86_64.tar.gz",
    archive.name,
)
(a.out / "PKGBUILD").write_text(s)
